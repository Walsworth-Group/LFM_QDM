"""Magnetometry tab handler."""

import sys
import time
import numpy as np
from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox, QInputDialog,
    QLabel, QSpinBox, QComboBox,
)
import pyqtgraph as pg
from scipy.ndimage import gaussian_filter

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from state.odmr_state import ODMRAppState, CameraMode
from workers.magnetometry_worker import MagnetometryWorker
from widgets.inflection_table import InflectionTableWidget
from widgets.field_map_display import _make_rdbu_colormap, _ColormapSideBar
from ui.ui_odmr_magnetometry_tab import Ui_magnetometry_tab_content


class MagnetometryTabHandler:
    """Handles Magnetometry tab: inflection table, presets, measurement, live preview."""

    def __init__(self, tab_widget: QWidget, state: ODMRAppState,
                 stop_streaming_fn, set_camera_mode_fn):
        """
        Initialise the magnetometry tab handler.

        Parameters
        ----------
        tab_widget : QWidget
            The bare QWidget placeholder for the Magnetometry tab.
        state : ODMRAppState
            Central application state.
        stop_streaming_fn : callable
            Called to stop camera streaming before starting acquisition.
            Returns True if streaming was already stopped.
        set_camera_mode_fn : callable
            Called to set the camera mode (CameraMode enum value).
        """
        self.state = state
        self._stop_streaming = stop_streaming_fn
        self._set_camera_mode = set_camera_mode_fn
        self._worker = None
        self._presets = {}
        self._presets_dir = Path(__file__).parent.parent / "config" / "presets"
        self._start_time = None     # wall-clock time when acquisition began
        self._last_analysis_result = None   # most recent analysis result dict

        self.ui = Ui_magnetometry_tab_content()
        self.ui.setupUi(tab_widget)

        # --- Programmatically add magnetometry-specific camera controls ---
        form = self.ui.formLayout   # mag_params_group form layout

        lbl_exp = QLabel("Exposure time (\u00b5s):")
        self._mag_exposure_spin = QSpinBox()
        self._mag_exposure_spin.setMinimum(100)
        self._mag_exposure_spin.setMaximum(500000)
        self._mag_exposure_spin.setSingleStep(1000)
        self._mag_exposure_spin.setValue(state.mag_exposure_time_us)
        form.addRow(lbl_exp, self._mag_exposure_spin)

        lbl_frames = QLabel("Frames per point:")
        self._mag_frames_spin = QSpinBox()
        self._mag_frames_spin.setMinimum(1)
        self._mag_frames_spin.setMaximum(100)
        self._mag_frames_spin.setValue(state.mag_n_frames_per_point)
        form.addRow(lbl_frames, self._mag_frames_spin)

        self._mag_hw_bin_x_spin = QSpinBox()
        self._mag_hw_bin_x_spin.setMinimum(1)
        self._mag_hw_bin_x_spin.setMaximum(8)
        self._mag_hw_bin_x_spin.setValue(state.mag_hw_bin_x)
        self._mag_hw_bin_y_spin = QSpinBox()
        self._mag_hw_bin_y_spin.setMinimum(1)
        self._mag_hw_bin_y_spin.setMaximum(8)
        self._mag_hw_bin_y_spin.setValue(state.mag_hw_bin_y)
        hw_bin_row = QHBoxLayout()
        hw_bin_row.addWidget(self._mag_hw_bin_x_spin)
        hw_bin_row.addWidget(QLabel("/"))
        hw_bin_row.addWidget(self._mag_hw_bin_y_spin)
        form.addRow(QLabel("HW Bin (X / Y):"), hw_bin_row)

        # --- Inject InflectionTableWidget ---
        self._inf_table = InflectionTableWidget()
        layout = QVBoxLayout(self.ui.mag_inflection_table_placeholder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._inf_table)

        # --- Build live preview area with display mode selector + colorbar ---
        preview_container = self.ui.mag_preview_widget
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(4, 4, 4, 4)
        preview_layout.setSpacing(4)

        # Display mode selector row
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Display:"))
        self._display_mode_combo = QComboBox()
        self._display_mode_combo.addItems(["Raw", "Denoised", "Processed"])
        self._display_mode_combo.setToolTip(
            "Live display mode during acquisition and for post-analysis view.\n"
            "Raw = running mean field map.\n"
            "Denoised = Gaussian-smoothed mean (sigma from Analysis tab).\n"
            "Processed = Raw minus Denoised (high-frequency residuals)."
        )
        mode_row.addWidget(self._display_mode_combo)
        mode_row.addStretch()
        preview_layout.addLayout(mode_row)

        # ImageView + colorbar side by side
        img_row = QHBoxLayout()
        img_row.setSpacing(4)
        self._preview_view = pg.ImageView()
        self._preview_view.ui.roiBtn.hide()
        self._preview_view.ui.menuBtn.hide()
        self._preview_view.ui.histogram.hide()   # remove the blue histogram bar
        self._preview_view.setColorMap(_make_rdbu_colormap())
        img_row.addWidget(self._preview_view, stretch=1)

        self._preview_colorbar = _ColormapSideBar(self._preview_view)
        img_row.addWidget(self._preview_colorbar)

        preview_layout.addLayout(img_row, stretch=1)

        # Connect display mode changes
        self._display_mode_combo.currentTextChanged.connect(self._on_display_mode_changed)
        # Also update display when new analysis arrives
        self.state.analysis_completed.connect(self._on_analysis_result_for_display)

        self._load_presets()
        self._connect_widgets()
        self._sync_from_state()

        # Auto-populate from sweep if already done
        if self.state.sweep_inflection_result:
            self._inf_table.populate_from_sweep_result(
                self.state.sweep_inflection_result)

        # Listen for future sweep completions via state signal
        self.state.sweep_completed.connect(self._on_sweep_completed)

    # ------------------------------------------------------------------
    # Preset management helpers
    # ------------------------------------------------------------------

    def _load_presets(self):
        """Load preset files from the presets directory."""
        self._presets_dir.mkdir(parents=True, exist_ok=True)
        for f in self._presets_dir.glob("*.json"):
            try:
                preset = self._inf_table.load_preset_from_file(f)
                self._presets[preset["name"]] = preset
            except Exception as exc:
                print(f"[MagnetometryTab] Could not load preset {f.name}: {exc}")
        self._refresh_preset_combo()

    def _refresh_preset_combo(self):
        """Repopulate the preset combo box from the presets dict."""
        self.ui.mag_preset_combo.clear()
        self.ui.mag_preset_combo.addItems(sorted(self._presets.keys()))

    # ------------------------------------------------------------------
    # Widget wiring
    # ------------------------------------------------------------------

    def _connect_widgets(self):
        """Connect UI widgets to state attributes and slot methods."""
        s = self.state
        ui = self.ui

        # Preset controls
        ui.mag_preset_load_btn.clicked.connect(self._on_load_preset)
        ui.mag_preset_save_btn.clicked.connect(self._on_save_preset)
        ui.mag_preset_delete_btn.clicked.connect(self._on_delete_preset)

        # Point file I/O
        ui.mag_points_load_btn.clicked.connect(self._on_load_points)
        ui.mag_points_save_btn.clicked.connect(self._on_save_points)

        # Measurement parameters
        ui.mag_bin_x_spin.valueChanged.connect(lambda v: setattr(s, 'mag_bin_x', v))
        ui.mag_bin_y_spin.valueChanged.connect(lambda v: setattr(s, 'mag_bin_y', v))
        ui.mag_num_samples_spin.valueChanged.connect(
            lambda v: setattr(s, 'mag_num_samples', v))
        ui.mag_live_interval_spin.valueChanged.connect(
            lambda v: setattr(s, 'perf_live_avg_update_interval_samples', v))
        ui.mag_ref_freq_spin.valueChanged.connect(
            lambda v: setattr(s, 'sweep_ref_freq_ghz', v))
        self._mag_exposure_spin.valueChanged.connect(
            lambda v: setattr(s, 'mag_exposure_time_us', v))
        self._mag_frames_spin.valueChanged.connect(
            lambda v: setattr(s, 'mag_n_frames_per_point', v))
        self._mag_hw_bin_x_spin.valueChanged.connect(
            lambda v: setattr(s, 'mag_hw_bin_x', v))
        self._mag_hw_bin_y_spin.valueChanged.connect(
            lambda v: setattr(s, 'mag_hw_bin_y', v))

        # Update spinboxes when "Send to Magnetometry" pushes sweep camera settings
        s.mag_camera_settings_pushed.connect(self._on_camera_settings_pushed)

        # Start/Stop
        ui.mag_start_btn.clicked.connect(self._on_start)
        ui.mag_stop_btn.clicked.connect(self._on_stop)

        # Save
        ui.mag_save_npz_btn.clicked.connect(self._on_save_npz)
        ui.mag_save_png_btn.clicked.connect(self._on_save_png)

        # State signals
        s.mag_running_changed.connect(self._on_running_changed)

    def _sync_from_state(self):
        """Push current state values into the magnetometry tab widgets."""
        s = self.state
        ui = self.ui
        ui.mag_bin_x_spin.setValue(s.mag_bin_x)
        ui.mag_bin_y_spin.setValue(s.mag_bin_y)
        ui.mag_num_samples_spin.setValue(s.mag_num_samples)
        ui.mag_live_interval_spin.setValue(s.perf_live_avg_update_interval_samples)
        ui.mag_ref_freq_spin.setValue(s.sweep_ref_freq_ghz)
        self._mag_exposure_spin.setValue(s.mag_exposure_time_us)
        self._mag_frames_spin.setValue(s.mag_n_frames_per_point)
        self._mag_hw_bin_x_spin.setValue(s.mag_hw_bin_x)
        self._mag_hw_bin_y_spin.setValue(s.mag_hw_bin_y)
        ui.mag_stop_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot(dict)
    def _on_sweep_completed(self, result):
        """Auto-populate inflection table when sweep finishes."""
        self._inf_table.populate_from_sweep_result(result)

    @Slot(int, int)
    def _on_camera_settings_pushed(self, exposure_us: int, n_frames: int):
        """Update spinboxes when 'Send to Magnetometry' is clicked in Sweep tab."""
        self._mag_exposure_spin.setValue(exposure_us)
        self._mag_frames_spin.setValue(n_frames)

    # ------------------------------------------------------------------
    # Display mode
    # ------------------------------------------------------------------

    @Slot(str)
    def _on_display_mode_changed(self, mode: str):
        """Switch the preview image to the selected mode using the last known data."""
        if self._last_analysis_result is not None:
            self._show_analysis_map(self._last_analysis_result, mode)

    @Slot(dict)
    def _on_analysis_result_for_display(self, result: dict):
        """Cache new analysis result and refresh display in current mode."""
        self._last_analysis_result = result
        self._show_analysis_map(result, self._display_mode_combo.currentText())

    def _show_analysis_map(self, result: dict, mode: str):
        """Display the named analysis map in the preview view."""
        key_map = {
            "Raw":       "field_map_gauss_raw",
            "Denoised":  "field_map_gauss_denoised",
            "Processed": "field_map_gauss_processed",
        }
        key = key_map.get(mode)
        if key is None:
            return
        data = result.get(key)
        if data is None:
            return
        finite = data[np.isfinite(data)]
        if len(finite) == 0:
            return
        self._preview_view.setImage(data.T, autoLevels=True)
        self._preview_view.setColorMap(_make_rdbu_colormap())
        self._preview_colorbar.auto_range()

    # ------------------------------------------------------------------
    # Preset management
    # ------------------------------------------------------------------

    @Slot()
    def _on_load_preset(self):
        """Load the currently selected preset into the inflection table."""
        name = self.ui.mag_preset_combo.currentText()
        if name in self._presets:
            self._inf_table.apply_preset(self._presets[name])

    @Slot()
    def _on_save_preset(self):
        """Prompt user for a name and save current table as a preset."""
        name, ok = QInputDialog.getText(None, "Save Preset", "Preset name:")
        if not ok or not name:
            return
        desc, _ = QInputDialog.getText(None, "Description", "Description (optional):")
        preset = self._inf_table.get_current_as_preset(
            name, description=desc,
            ref_freq_ghz=self.state.sweep_ref_freq_ghz)
        path = self._presets_dir / f"{name}.json"
        self._inf_table.save_preset_to_file(preset, path)
        self._presets[name] = preset
        self._refresh_preset_combo()
        self.ui.mag_preset_combo.setCurrentText(name)

    @Slot()
    def _on_delete_preset(self):
        """Delete the currently selected preset from disk and the combo."""
        name = self.ui.mag_preset_combo.currentText()
        if name not in self._presets:
            return
        path = self._presets_dir / f"{name}.json"
        if path.exists():
            path.unlink()
        del self._presets[name]
        self._refresh_preset_combo()

    @Slot()
    def _on_load_points(self):
        """Open a file dialog to load inflection points from a JSON file."""
        path, _ = QFileDialog.getOpenFileName(
            None, "Load Inflection Points", "", "JSON Files (*.json)")
        if path:
            self._inf_table.load_points_from_file(Path(path))

    @Slot()
    def _on_save_points(self):
        """Open a file dialog to save current inflection points to a JSON file."""
        path, _ = QFileDialog.getSaveFileName(
            None, "Save Inflection Points", "inflection_points.json",
            "JSON Files (*.json)")
        if path:
            try:
                self._inf_table.save_points_to_file(Path(path))
            except RuntimeError as e:
                QMessageBox.warning(None, "Cannot Save", str(e))

    # ------------------------------------------------------------------
    # Measurement
    # ------------------------------------------------------------------

    @Slot()
    def _on_start(self):
        """Handle Start button click: validate, stop streaming, launch worker."""
        if not self.state.try_start_magnetometry():
            QMessageBox.warning(None, "Busy", "ODMR sweep is running. Stop it first.")
            return
        if self.state.sweep_inflection_result is None:
            QMessageBox.warning(None, "No Sweep Data",
                "Run an ODMR sweep first to identify inflection points.")
            return

        sel = self._inf_table.get_selection()
        self.state.mag_selected_indices = sel["indices"]
        self.state.mag_selected_parities = sel["parities"]

        safe = self._stop_streaming()
        if not safe:
            self.state.camera_state.camera_streaming_changed.connect(
                self._on_streaming_stopped_then_mag)
            return
        self._start_mag_worker()

    @Slot(bool)
    def _on_streaming_stopped_then_mag(self, is_streaming):
        """Start magnetometry once camera streaming has stopped."""
        if not is_streaming:
            try:
                self.state.camera_state.camera_streaming_changed.disconnect(
                    self._on_streaming_stopped_then_mag)
            except RuntimeError:
                pass
            self._start_mag_worker()

    def _start_mag_worker(self):
        """Create and start the MagnetometryWorker thread."""
        self._set_camera_mode(CameraMode.ACQUIRING)
        self._start_time = time.monotonic()
        simulation = getattr(self.state, '_simulation_mode', False)
        self._worker = MagnetometryWorker(self.state, simulation_mode=simulation)
        self._worker.mag_progress.connect(self._on_progress)
        self._worker.mag_sample_acquired.connect(self._on_sample_acquired)
        self._worker.mag_completed.connect(self._on_mag_completed)
        self._worker.mag_failed.connect(self._on_mag_failed)
        self._worker.start()
        n = self.state.mag_num_samples
        self.state.status_message.emit(
            f"Acquiring magnetometry data...  (0/{n} samples)")

    @Slot()
    def _on_stop(self):
        """Request the magnetometry worker to stop."""
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self.state.status_message.emit("Stop requested — finishing current sample...")

    @Slot(bool)
    def _on_running_changed(self, running):
        """Update button states when magnetometry running state changes."""
        self.ui.mag_start_btn.setEnabled(not running)
        self.ui.mag_stop_btn.setEnabled(running)
        if not running:
            self._set_camera_mode(CameraMode.IDLE)
            self._start_time = None

    @Slot(int, int)
    def _on_progress(self, current, total):
        """Update progress bar, timing label, and status message."""
        self.ui.mag_progress_bar.setMaximum(total)
        self.ui.mag_progress_bar.setValue(current)

        elapsed = time.monotonic() - self._start_time if self._start_time else 0.0
        if current > 0:
            per_sample = elapsed / current
            remaining = per_sample * (total - current)
            timing_str = (
                f"{current}/{total} | {elapsed:.0f}s elapsed | "
                f"~{remaining:.0f}s remaining | {per_sample:.2f}s/sample"
            )
        else:
            timing_str = f"0/{total}"

        self.ui.mag_time_label.setText(timing_str)
        self.state.status_message.emit(
            f"Acquiring magnetometry data...  {current}/{total} samples"
        )

    @Slot(int, object)
    def _on_sample_acquired(self, n, field_gauss):
        """Update live preview in the currently selected display mode."""
        mode = self._display_mode_combo.currentText()
        sigma = self.state.analysis_gaussian_sigma

        if mode == "Raw":
            display = field_gauss
        elif mode == "Denoised":
            display = gaussian_filter(field_gauss.astype(np.float64), sigma=sigma).astype(np.float32)
        else:  # "Processed"
            denoised = gaussian_filter(field_gauss.astype(np.float64), sigma=sigma).astype(np.float32)
            display = field_gauss - denoised

        self._preview_view.setImage(display.T, autoLevels=True)
        self._preview_view.setColorMap(_make_rdbu_colormap())
        self._preview_colorbar.auto_range()

    @Slot(dict)
    def _on_mag_completed(self, result):
        """Store result in state and emit state-level completed signal."""
        n = result.get("num_samples_acquired", 0)
        elapsed = time.monotonic() - self._start_time if self._start_time else 0.0
        self.state.mag_stability_result = result
        self.state.mag_completed.emit(result)
        self.state.status_message.emit(
            f"Magnetometry complete: {n} samples in {elapsed:.1f}s"
        )

    @Slot(str)
    def _on_mag_failed(self, msg):
        """Handle measurement failure by resetting camera mode and showing error."""
        self._set_camera_mode(CameraMode.IDLE)
        self.state.status_message.emit(f"Magnetometry failed: {msg[:80]}")
        QMessageBox.critical(None, "Measurement Failed", msg)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save_data(self, global_prefix=""):
        """Called by Save All. Returns True if data was saved."""
        result = self.state.mag_stability_result
        if result is None:
            return False
        self._on_save_npz(global_prefix=global_prefix)
        self._on_save_png(global_prefix=global_prefix)
        return True

    @Slot()
    def _on_save_npz(self, global_prefix=""):
        """Save magnetometry stability result to a compressed .npz file."""
        result = self.state.mag_stability_result
        if result is None:
            QMessageBox.information(None, "No Data", "Run a measurement first.")
            return
        tab_prefix = self.ui.mag_prefix_edit.text().strip()
        combined = "_".join(p for p in [global_prefix, tab_prefix] if p)
        stem = self.state.build_save_filename(
            "multipoint_stability",
            user_prefix=combined)
        save_dir = Path(self.state.save_base_path) / self.state.save_subfolder
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = save_dir / f"{stem}.npz"
        np.savez_compressed(
            save_path,
            stability_cube=result["stability_cube"],
            freq_list=np.array(result["freq_list"]),
            slope_list=np.array(result["slope_list"]),
            parity_list=np.array(result["parity_list"]),
            baseline_list=np.array(result["baseline_list"]),
            metadata=str(result.get("metadata", {})),
        )
        self.state.status_message.emit(f"Saved magnetometry data: {save_path.name}")

    @Slot()
    def _on_save_png(self, global_prefix=""):
        """Save the current live preview image as PNG."""
        tab_prefix = self.ui.mag_prefix_edit.text().strip()
        combined = "_".join(p for p in [global_prefix, tab_prefix] if p)
        stem = self.state.build_save_filename(
            "multipoint_stability",
            user_prefix=combined)
        save_dir = Path(self.state.save_base_path) / self.state.save_subfolder
        save_dir.mkdir(parents=True, exist_ok=True)
        exporter = pg.exporters.ImageExporter(self._preview_view.imageItem)
        exporter.export(str(save_dir / f"{stem}_preview.png"))
