# ODMR App — Phase 4: Tab Logic, Save/Config, Integration

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the full logic for ODMR Sweep, Magnetometry, Analysis, and Sensitivity tabs; complete the save system; and integrate with `launch_all_apps.py`.

**Architecture:** Each tab gets a `*TabHandler` class (mixin pattern from Phase 3). Handlers are instantiated by `ODMRMainWindow` and receive the tab's QWidget + shared ODMRAppState. Workers from Phase 1 are started/stopped by the handlers.

**Tech Stack:** PySide6, pyqtgraph, numpy, qdm_gen functions (existing), allantools (optional).

**Prerequisites:** Phases 1–3 complete.

---

## Task 12: ODMR Sweep Tab

**Files:**
- Create: `GUI/odmr_app/tabs/sweep_tab.py`
- Modify: `GUI/odmr_app/odmr_main_window.py` (add handler instantiation)

**Step 1: Implement `GUI/odmr_app/tabs/sweep_tab.py`**

```python
"""ODMR Sweep tab handler."""

import sys
import time
import numpy as np
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import Slot, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QMessageBox
import pyqtgraph as pg

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from state.odmr_state import ODMRAppState, CameraMode
from workers.odmr_sweep_worker import ODMRSweepWorker
from ui.ui_odmr_sweep_tab import Ui_sweep_tab_content


class SweepTabHandler:
    """Handles ODMR Sweep tab: controls, live plots, inflection table, save."""

    INFLECTION_COLS = ["#", "Freq (GHz)", "Slope (GHz⁻¹)", "Contrast"]

    def __init__(self, tab_widget: QWidget, state: ODMRAppState,
                 stop_streaming_fn, set_camera_mode_fn):
        self.state = state
        self._stop_streaming = stop_streaming_fn
        self._set_camera_mode = set_camera_mode_fn
        self._worker = None
        self._last_plot_update = 0.0

        # Setup UI
        self.ui = Ui_sweep_tab_content()
        self.ui.setupUi(tab_widget)

        # Inject pyqtgraph plot widget
        self._plot1 = pg.PlotWidget(title="Transition 1 (m=0→−1)")
        self._plot2 = pg.PlotWidget(title="Transition 2 (m=0→+1)")
        for plot in (self._plot1, self._plot2):
            plot.setLabel('left', 'Contrast (PL_sig/PL_ref)')
            plot.setLabel('bottom', 'Frequency (GHz)')
        plot_layout = QHBoxLayout(self.ui.sweep_plot_widget)
        plot_layout.addWidget(self._plot1)
        plot_layout.addWidget(self._plot2)

        self._curve1 = self._plot1.plot(pen='c', symbol=None)
        self._curve2 = self._plot2.plot(pen='y', symbol=None)
        self._fit_curve1 = self._plot1.plot(pen=pg.mkPen('r', width=2))
        self._fit_curve2 = self._plot2.plot(pen=pg.mkPen('r', width=2))

        # Inflection point vertical lines (8 total, 4 per plot)
        self._inf_lines1 = [pg.InfiniteLine(angle=90, movable=False,
                            pen=pg.mkPen('g', style=pg.QtCore.Qt.DashLine))
                            for _ in range(4)]
        self._inf_lines2 = [pg.InfiniteLine(angle=90, movable=False,
                            pen=pg.mkPen('g', style=pg.QtCore.Qt.DashLine))
                            for _ in range(4)]
        for line in self._inf_lines1:
            self._plot1.addItem(line)
            line.setVisible(False)
        for line in self._inf_lines2:
            self._plot2.addItem(line)
            line.setVisible(False)

        self._connect_widgets()
        self._sync_from_state()

    def _connect_widgets(self):
        s = self.state
        ui = self.ui

        # Sweep parameter inputs → state
        ui.sweep_freq1_start.valueChanged.connect(
            lambda v: setattr(s, 'sweep_freq1_start_ghz', v))
        ui.sweep_freq1_end.valueChanged.connect(
            lambda v: setattr(s, 'sweep_freq1_end_ghz', v))
        ui.sweep_freq1_steps.valueChanged.connect(
            lambda v: setattr(s, 'sweep_freq1_steps', v))
        ui.sweep_freq2_start.valueChanged.connect(
            lambda v: setattr(s, 'sweep_freq2_start_ghz', v))
        ui.sweep_freq2_end.valueChanged.connect(
            lambda v: setattr(s, 'sweep_freq2_end_ghz', v))
        ui.sweep_freq2_steps.valueChanged.connect(
            lambda v: setattr(s, 'sweep_freq2_steps', v))
        ui.sweep_ref_freq.valueChanged.connect(
            lambda v: setattr(s, 'sweep_ref_freq_ghz', v))
        ui.sweep_num_sweeps.valueChanged.connect(
            lambda v: setattr(s, 'sweep_num_sweeps', v))
        ui.sweep_n_lorentz.valueChanged.connect(
            lambda v: setattr(s, 'sweep_n_lorentz', v))

        # Buttons
        ui.sweep_start_btn.clicked.connect(self._on_start)
        ui.sweep_stop_btn.clicked.connect(self._on_stop)
        ui.sweep_send_to_mag_btn.clicked.connect(self._on_send_to_mag)
        ui.sweep_save_npz_btn.clicked.connect(self._on_save_npz)
        ui.sweep_save_png_btn.clicked.connect(self._on_save_png)

        # State → UI
        s.sweep_running_changed.connect(self._on_running_changed)
        s.sweep_progress.connect(self._on_progress)
        s.sweep_spectrum_updated.connect(self._on_spectrum_updated)
        s.sweep_completed.connect(self._on_sweep_completed)

    def _sync_from_state(self):
        s = self.state
        ui = self.ui
        ui.sweep_freq1_start.setValue(s.sweep_freq1_start_ghz)
        ui.sweep_freq1_end.setValue(s.sweep_freq1_end_ghz)
        ui.sweep_freq1_steps.setValue(s.sweep_freq1_steps)
        ui.sweep_freq2_start.setValue(s.sweep_freq2_start_ghz)
        ui.sweep_freq2_end.setValue(s.sweep_freq2_end_ghz)
        ui.sweep_freq2_steps.setValue(s.sweep_freq2_steps)
        ui.sweep_ref_freq.setValue(s.sweep_ref_freq_ghz)
        ui.sweep_num_sweeps.setValue(s.sweep_num_sweeps)
        ui.sweep_n_lorentz.setValue(s.sweep_n_lorentz)
        ui.sweep_stop_btn.setEnabled(False)
        ui.sweep_send_to_mag_btn.setEnabled(False)

    @Slot()
    def _on_start(self):
        if not self.state.try_start_sweep():
            QMessageBox.warning(None, "Busy",
                "Magnetometry measurement is running. Stop it first.")
            return

        # Stop camera streaming if needed
        safe = self._stop_streaming()
        if not safe:
            # Wait for streaming_changed signal to call _on_start again
            self.state.camera_state.camera_streaming_changed.connect(
                self._on_streaming_stopped_then_sweep)
            return

        self._start_sweep_worker()

    @Slot(bool)
    def _on_streaming_stopped_then_sweep(self, is_streaming):
        if not is_streaming:
            self.state.camera_state.camera_streaming_changed.disconnect(
                self._on_streaming_stopped_then_sweep)
            self._start_sweep_worker()

    def _start_sweep_worker(self):
        self._set_camera_mode(CameraMode.ACQUIRING)
        simulation = getattr(self.state, '_simulation_mode', False)
        self._worker = ODMRSweepWorker(self.state, simulation_mode=simulation)
        self._worker.sweep_progress.connect(self._on_progress)
        self._worker.spectrum_updated.connect(self._on_spectrum_updated)
        self._worker.sweep_completed.connect(self._on_sweep_completed)
        self._worker.sweep_failed.connect(self._on_sweep_failed)
        self._worker.start()

    @Slot()
    def _on_stop(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()

    @Slot(bool)
    def _on_running_changed(self, running):
        self.ui.sweep_start_btn.setEnabled(not running)
        self.ui.sweep_stop_btn.setEnabled(running)
        if not running:
            self._set_camera_mode(CameraMode.IDLE)

    @Slot(int, int)
    def _on_progress(self, current, total):
        self.ui.sweep_progress_bar.setMaximum(total)
        self.ui.sweep_progress_bar.setValue(current)
        self.ui.sweep_time_label.setText(f"{current}/{total} sweeps")

    @Slot(object, object, object, object, int)
    def _on_spectrum_updated(self, fl1, sp1, fl2, sp2, sweep_num):
        # Throttle UI updates
        now = time.monotonic()
        min_interval = 1.0 / self.state.perf_ui_plot_throttle_fps
        if now - self._last_plot_update < min_interval:
            return
        self._last_plot_update = now
        self._curve1.setData(fl1, sp1)
        self._curve2.setData(fl2, sp2)

    @Slot(dict)
    def _on_sweep_completed(self, result):
        # Update plots with final data
        self._on_spectrum_updated(
            result["freqlist1"], result["spectrum1"].mean(axis=(1,2)),
            result["freqlist2"], result["spectrum2"].mean(axis=(1,2)),
            self.state.sweep_num_sweeps)

        # Show inflection point markers
        pts = result["inflection_points"]
        for i, line in enumerate(self._inf_lines1):
            if i < 4:
                line.setValue(pts[i])
                line.setVisible(True)
        for i, line in enumerate(self._inf_lines2):
            if i + 4 < len(pts):
                line.setValue(pts[i + 4])
                line.setVisible(True)

        # Populate read-only inflection table
        self._populate_inflection_summary(result)
        self.ui.sweep_send_to_mag_btn.setEnabled(True)

    def _populate_inflection_summary(self, result):
        """Fill the read-only inflection summary table in the sweep tab."""
        table = self.ui.sweep_inflection_table
        pts = result["inflection_points"]
        slopes = result["inflection_slopes"]
        contrasts = result["inflection_contrasts"]
        table.setRowCount(len(pts))
        for i, (f, sl, co) in enumerate(zip(pts, slopes, contrasts)):
            from PySide6.QtWidgets import QTableWidgetItem
            table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            table.setItem(i, 1, QTableWidgetItem(f"{f:.6f}"))
            table.setItem(i, 2, QTableWidgetItem(f"{sl:+.4f}"))
            table.setItem(i, 3, QTableWidgetItem(f"{co:.6f}"))

    @Slot()
    def _on_send_to_mag(self):
        """Signal that sweep result should be sent to Magnetometry tab."""
        # The magnetometry tab handler listens to state.sweep_completed directly
        # This button just notifies the user visually
        self.ui.sweep_send_to_mag_btn.setText("✓ Sent to Magnetometry")
        QTimer.singleShot(2000, lambda: self.ui.sweep_send_to_mag_btn.setText(
            "Send to Magnetometry →"))

    @Slot(str)
    def _on_sweep_failed(self, msg):
        self._set_camera_mode(CameraMode.IDLE)
        QMessageBox.critical(None, "Sweep Failed", msg)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save_data(self):
        """Called by Save All. Returns True if data was saved."""
        if self.state.sweep_inflection_result is None:
            return False
        self._on_save_npz()
        self._on_save_png()
        return True

    @Slot()
    def _on_save_npz(self):
        result = self.state.sweep_inflection_result
        if result is None:
            QMessageBox.information(None, "No Data", "Run a sweep first.")
            return
        stem = self.state.build_save_filename(
            "odmr_freq_sweep",
            user_prefix=self.ui.sweep_prefix_edit.text())
        save_dir = Path(self.state.save_base_path) / self.state.save_subfolder
        save_dir.mkdir(parents=True, exist_ok=True)
        path = save_dir / f"{stem}.npz"
        import numpy as np
        np.savez_compressed(
            path,
            freqlist1=result["freqlist1"], spectrum1=result["spectrum1"],
            freqlist2=result["freqlist2"], spectrum2=result["spectrum2"],
            inflection_points=result["inflection_points"],
            inflection_slopes=result["inflection_slopes"],
            inflection_contrasts=result["inflection_contrasts"],
            metadata=str(self.state.build_metadata()),
        )

    @Slot()
    def _on_save_png(self):
        result = self.state.sweep_inflection_result
        if result is None:
            return
        stem = self.state.build_save_filename(
            "odmr_freq_sweep",
            user_prefix=self.ui.sweep_prefix_edit.text())
        save_dir = Path(self.state.save_base_path) / self.state.save_subfolder
        save_dir.mkdir(parents=True, exist_ok=True)
        # Export pyqtgraph plots
        exporter1 = pg.exporters.ImageExporter(self._plot1.plotItem)
        exporter1.export(str(save_dir / f"{stem}_t1.png"))
        exporter2 = pg.exporters.ImageExporter(self._plot2.plotItem)
        exporter2.export(str(save_dir / f"{stem}_t2.png"))
```

**Step 2: Add to ODMRMainWindow.__init__**

```python
from tabs.sweep_tab import SweepTabHandler
self._sweep_handler = SweepTabHandler(
    self.ui.sweep_tab, self.state,
    stop_streaming_fn=self._stop_streaming_if_needed,
    set_camera_mode_fn=lambda mode: setattr(self.state, 'odmr_camera_mode', mode),
)
```

Also wire "Send to Mag" by connecting `state.sweep_completed` in the magnetometry handler (Task 13).

**Step 3: Manual test**

- Launch app, connect RF (or use simulation mode)
- Enter sweep frequencies, click Start Sweep
- Verify: progress bar updates, spectrum plots update per sweep
- After completion: inflection table populated, "Send to Magnetometry →" enabled

**Step 4: Commit**
```bash
git add GUI/odmr_app/tabs/sweep_tab.py GUI/odmr_app/odmr_main_window.py
git commit -m "feat(odmr-app): implement ODMR Sweep tab with live spectrum and inflection display"
```

---

## Task 13: Magnetometry Tab

**Files:**
- Create: `GUI/odmr_app/tabs/magnetometry_tab.py`

```python
"""Magnetometry tab handler."""

import sys
import numpy as np
from pathlib import Path
from PySide6.QtCore import Slot, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QFileDialog, QMessageBox, QInputDialog
import pyqtgraph as pg

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from state.odmr_state import ODMRAppState, CameraMode
from workers.magnetometry_worker import MagnetometryWorker
from widgets.inflection_table import InflectionTableWidget
from ui.ui_odmr_magnetometry_tab import Ui_magnetometry_tab_content


class MagnetometryTabHandler:
    """Handles Magnetometry tab: inflection table, presets, measurement, live preview."""

    def __init__(self, tab_widget: QWidget, state: ODMRAppState,
                 stop_streaming_fn, set_camera_mode_fn):
        self.state = state
        self._stop_streaming = stop_streaming_fn
        self._set_camera_mode = set_camera_mode_fn
        self._worker = None
        self._presets = {}         # name → preset dict
        self._presets_dir = Path(__file__).parent.parent / "config" / "presets"

        # Setup UI
        self.ui = Ui_magnetometry_tab_content()
        self.ui.setupUi(tab_widget)

        # Inject InflectionTableWidget
        self._inf_table = InflectionTableWidget()
        layout = QVBoxLayout(self.ui.mag_inflection_table_placeholder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._inf_table)

        # Inject live preview pyqtgraph ImageView
        self._preview_view = pg.ImageView()
        self._preview_view.ui.roiBtn.hide()
        self._preview_view.ui.menuBtn.hide()
        layout2 = QVBoxLayout(self.ui.mag_preview_widget)
        layout2.setContentsMargins(0, 0, 0, 0)
        layout2.addWidget(self._preview_view)

        self._load_presets()
        self._connect_widgets()
        self._sync_from_state()

        # Auto-populate from sweep if already done
        if self.state.sweep_inflection_result:
            self._inf_table.populate_from_sweep_result(
                self.state.sweep_inflection_result)

        # Listen for future sweep completions
        self.state.sweep_completed.connect(self._on_sweep_completed)

    def _load_presets(self):
        self._presets_dir.mkdir(parents=True, exist_ok=True)
        for f in self._presets_dir.glob("*.json"):
            try:
                preset = self._inf_table.load_preset_from_file(f)
                self._presets[preset["name"]] = preset
            except Exception:
                pass
        self._refresh_preset_combo()

    def _refresh_preset_combo(self):
        self.ui.mag_preset_combo.clear()
        self.ui.mag_preset_combo.addItems(sorted(self._presets.keys()))

    def _connect_widgets(self):
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

        # Start/Stop
        ui.mag_start_btn.clicked.connect(self._on_start)
        ui.mag_stop_btn.clicked.connect(self._on_stop)

        # Save
        ui.mag_save_npz_btn.clicked.connect(self._on_save_npz)
        ui.mag_save_png_btn.clicked.connect(self._on_save_png)

        # Worker signals
        s.mag_running_changed.connect(self._on_running_changed)
        s.mag_progress.connect(self._on_progress)
        s.mag_sample_acquired.connect(self._on_sample_acquired)
        s.mag_completed.connect(self._on_mag_completed)

    def _sync_from_state(self):
        s = self.state
        ui = self.ui
        ui.mag_bin_x_spin.setValue(s.mag_bin_x)
        ui.mag_bin_y_spin.setValue(s.mag_bin_y)
        ui.mag_num_samples_spin.setValue(s.mag_num_samples)
        ui.mag_live_interval_spin.setValue(s.perf_live_avg_update_interval_samples)
        ui.mag_ref_freq_spin.setValue(s.sweep_ref_freq_ghz)
        ui.mag_stop_btn.setEnabled(False)

    @Slot(dict)
    def _on_sweep_completed(self, result):
        """Auto-populate inflection table when sweep finishes."""
        self._inf_table.populate_from_sweep_result(result)

    # ------------------------------------------------------------------
    # Preset management
    # ------------------------------------------------------------------

    @Slot()
    def _on_load_preset(self):
        name = self.ui.mag_preset_combo.currentText()
        if name in self._presets:
            self._inf_table.apply_preset(self._presets[name])

    @Slot()
    def _on_save_preset(self):
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
        path, _ = QFileDialog.getOpenFileName(
            None, "Load Inflection Points", "", "JSON Files (*.json)")
        if path:
            self._inf_table.load_points_from_file(Path(path))

    @Slot()
    def _on_save_points(self):
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
        if not self.state.try_start_magnetometry():
            QMessageBox.warning(None, "Busy", "ODMR sweep is running. Stop it first.")
            return
        if self.state.sweep_inflection_result is None:
            QMessageBox.warning(None, "No Sweep Data",
                "Run an ODMR sweep first to identify inflection points.")
            return

        # Update state from table
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
        if not is_streaming:
            self.state.camera_state.camera_streaming_changed.disconnect(
                self._on_streaming_stopped_then_mag)
            self._start_mag_worker()

    def _start_mag_worker(self):
        self._set_camera_mode(CameraMode.ACQUIRING)
        simulation = getattr(self.state, '_simulation_mode', False)
        self._worker = MagnetometryWorker(self.state, simulation_mode=simulation)
        self._worker.mag_progress.connect(self._on_progress)
        self._worker.mag_sample_acquired.connect(self._on_sample_acquired)
        self._worker.mag_completed.connect(self._on_mag_completed)
        self._worker.mag_failed.connect(self._on_mag_failed)
        self._worker.start()

    @Slot()
    def _on_stop(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()

    @Slot(bool)
    def _on_running_changed(self, running):
        self.ui.mag_start_btn.setEnabled(not running)
        self.ui.mag_stop_btn.setEnabled(running)
        if not running:
            self._set_camera_mode(CameraMode.IDLE)

    @Slot(int, int)
    def _on_progress(self, current, total):
        self.ui.mag_progress_bar.setMaximum(total)
        self.ui.mag_progress_bar.setValue(current)
        self.ui.mag_time_label.setText(f"{current}/{total} samples")

    @Slot(int, object)
    def _on_sample_acquired(self, n, field_gauss):
        """Update live cumulative average preview."""
        self._preview_view.setImage(field_gauss.T, autoLevels=True)

    @Slot(dict)
    def _on_mag_completed(self, result):
        self.state.mag_stability_result = result

    @Slot(str)
    def _on_mag_failed(self, msg):
        self._set_camera_mode(CameraMode.IDLE)
        QMessageBox.critical(None, "Measurement Failed", msg)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save_data(self):
        result = self.state.mag_stability_result
        if result is None:
            return False
        self._on_save_npz()
        return True

    @Slot()
    def _on_save_npz(self):
        result = self.state.mag_stability_result
        if result is None:
            QMessageBox.information(None, "No Data", "Run a measurement first.")
            return
        stem = self.state.build_save_filename(
            "multipoint_stability",
            user_prefix=self.ui.mag_prefix_edit.text())
        save_dir = Path(self.state.save_base_path) / self.state.save_subfolder
        save_dir.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            save_dir / f"{stem}.npz",
            stability_cube=result["stability_cube"],
            freq_list=result["freq_list"],
            slope_list=result["slope_list"],
            parity_list=result["parity_list"],
            baseline_list=result["baseline_list"],
            metadata=str(result.get("metadata", {})),
        )

    @Slot()
    def _on_save_png(self):
        """Save current live preview."""
        stem = self.state.build_save_filename(
            "multipoint_stability",
            user_prefix=self.ui.mag_prefix_edit.text())
        save_dir = Path(self.state.save_base_path) / self.state.save_subfolder
        save_dir.mkdir(parents=True, exist_ok=True)
        exporter = pg.exporters.ImageExporter(self._preview_view.imageItem)
        exporter.export(str(save_dir / f"{stem}_preview.png"))
```

**Step 2: Add to ODMRMainWindow.__init__**
```python
from tabs.magnetometry_tab import MagnetometryTabHandler
self._mag_handler = MagnetometryTabHandler(
    self.ui.magnetometry_tab, self.state,
    stop_streaming_fn=self._stop_streaming_if_needed,
    set_camera_mode_fn=lambda mode: setattr(self.state, 'odmr_camera_mode', mode),
)
```

**Step 3: Commit**
```bash
git add GUI/odmr_app/tabs/magnetometry_tab.py GUI/odmr_app/odmr_main_window.py
git commit -m "feat(odmr-app): implement Magnetometry tab with preset management and live preview"
```

---

## Task 14: Analysis Tab

**Files:**
- Create: `GUI/odmr_app/tabs/analysis_tab.py`

```python
"""Analysis tab handler — field map display and reanalysis controls."""

import sys
import numpy as np
from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QWidget, QVBoxLayout, QMessageBox
import pyqtgraph as pg
import pyqtgraph.exporters

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from state.odmr_state import ODMRAppState
from widgets.field_map_display import FieldMapDisplayWidget
from ui.ui_odmr_analysis_tab import Ui_analysis_tab_content

import qdm_gen as qdm


class AnalysisTabHandler:
    """Handles Analysis tab: 3-panel display, reanalysis, stats, save."""

    def __init__(self, tab_widget: QWidget, state: ODMRAppState):
        self.state = state

        self.ui = Ui_analysis_tab_content()
        self.ui.setupUi(tab_widget)

        # Inject FieldMapDisplayWidget
        self._field_display = FieldMapDisplayWidget()
        layout = QVBoxLayout(self.ui.analysis_display_placeholder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._field_display)

        self._connect_widgets()
        self._sync_from_state()

        # Auto-analyze when magnetometry completes
        self.state.mag_completed.connect(self._on_mag_completed)

    def _connect_widgets(self):
        s = self.state
        ui = self.ui

        ui.analysis_denoise_combo.currentTextChanged.connect(
            lambda t: setattr(s, 'analysis_denoise_method', t))
        ui.analysis_sigma_spin.valueChanged.connect(
            lambda v: setattr(s, 'analysis_gaussian_sigma', v))
        ui.analysis_outlier_spin.valueChanged.connect(
            lambda v: setattr(s, 'analysis_outlier_sigma', v))
        ui.analysis_reanalyze_btn.clicked.connect(self._on_reanalyze)
        ui.analysis_save_npz_btn.clicked.connect(self._on_save_npz)
        ui.analysis_save_png_btn.clicked.connect(self._on_save_png)

        s.analysis_completed.connect(self._on_analysis_completed)

    def _sync_from_state(self):
        s = self.state
        ui = self.ui
        idx = ui.analysis_denoise_combo.findText(s.analysis_denoise_method)
        if idx >= 0:
            ui.analysis_denoise_combo.setCurrentIndex(idx)
        ui.analysis_sigma_spin.setValue(s.analysis_gaussian_sigma)
        ui.analysis_outlier_spin.setValue(s.analysis_outlier_sigma)

    @Slot(dict)
    def _on_mag_completed(self, result):
        """Auto-run analysis when new magnetometry data arrives."""
        self._run_analysis(result["stability_cube"])

    @Slot()
    def _on_reanalyze(self):
        result = self.state.mag_stability_result
        if result is None:
            QMessageBox.information(None, "No Data", "Run a measurement first.")
            return
        self._run_analysis(result["stability_cube"])

    def _run_analysis(self, stability_cube: np.ndarray):
        s = self.state
        try:
            field_result = qdm.analyze_multi_point_magnetometry(
                stability_cube,
                outlier_sigma=s.analysis_outlier_sigma,
                reference_mode=s.analysis_reference_mode,
                denoise_method=s.analysis_denoise_method,
                gaussian_sigma=s.analysis_gaussian_sigma,
                show_plot=False,
                save_fig=False,
            )
            s.analysis_field_map_result = field_result
            s.analysis_completed.emit(field_result)
        except Exception as e:
            QMessageBox.critical(None, "Analysis Error", str(e))

    @Slot(dict)
    def _on_analysis_completed(self, result):
        self._field_display.update_from_result(result)

        # Update stats
        proc = result.get("field_map_gauss_processed")
        if proc is not None:
            self.ui.analysis_stats_label.setText(
                f"Mean: {np.nanmean(proc):+.4f} G    "
                f"Std: {np.nanstd(proc):.4f} G    "
                f"Range: [{np.nanmin(proc):.4f}, {np.nanmax(proc):.4f}] G")

    def save_data(self):
        result = self.state.analysis_field_map_result
        if result is None:
            return False
        self._on_save_npz()
        self._on_save_png()
        return True

    @Slot()
    def _on_save_npz(self):
        result = self.state.analysis_field_map_result
        if result is None:
            QMessageBox.information(None, "No Data", "Run analysis first.")
            return
        stem = self.state.build_save_filename(
            "field_map", user_prefix=self.ui.analysis_prefix_edit.text())
        save_dir = Path(self.state.save_base_path) / self.state.save_subfolder
        save_dir.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            save_dir / f"{stem}.npz",
            field_map_gauss_raw=result.get("field_map_gauss_raw"),
            field_map_gauss_denoised=result.get("field_map_gauss_denoised"),
            field_map_gauss_processed=result.get("field_map_gauss_processed"),
            metadata=str(self.state.build_metadata()),
        )

    @Slot()
    def _on_save_png(self):
        result = self.state.analysis_field_map_result
        if result is None:
            return
        stem = self.state.build_save_filename(
            "field_map", user_prefix=self.ui.analysis_prefix_edit.text())
        save_dir = Path(self.state.save_base_path) / self.state.save_subfolder
        save_dir.mkdir(parents=True, exist_ok=True)
        # Use matplotlib figure from result if available
        fig = result.get("figure")
        if fig is not None:
            fig.savefig(str(save_dir / f"{stem}.png"), dpi=150, bbox_inches='tight')
```

**Add to ODMRMainWindow.__init__:**
```python
from tabs.analysis_tab import AnalysisTabHandler
self._analysis_handler = AnalysisTabHandler(self.ui.analysis_tab, self.state)
```

**Commit:**
```bash
git add GUI/odmr_app/tabs/analysis_tab.py GUI/odmr_app/odmr_main_window.py
git commit -m "feat(odmr-app): implement Analysis tab with 3-panel field map display and reanalysis"
```

---

## Task 15: Sensitivity Tab

**Files:**
- Create: `GUI/odmr_app/tabs/sensitivity_tab.py`

```python
"""Sensitivity tab handler."""

import sys
import numpy as np
from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QMessageBox
import pyqtgraph as pg

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from state.odmr_state import ODMRAppState
from ui.ui_odmr_sensitivity_tab import Ui_sensitivity_tab_content

import qdm_gen as qdm


class SensitivityTabHandler:
    """Handles Sensitivity tab: sensitivity map, Allan deviation, save."""

    def __init__(self, tab_widget: QWidget, state: ODMRAppState):
        self.state = state
        self._sensitivity_result = None
        self._allan_result = None

        self.ui = Ui_sensitivity_tab_content()
        self.ui.setupUi(tab_widget)

        # Inject pyqtgraph widgets
        self._sens_view = pg.ImageView()
        self._sens_view.ui.roiBtn.hide()
        self._sens_view.ui.menuBtn.hide()
        sens_layout = QVBoxLayout(self.ui.sensitivity_map_widget)
        sens_layout.setContentsMargins(0, 0, 0, 0)
        sens_layout.addWidget(self._sens_view)

        self._allan_plot = pg.PlotWidget(title="Allan Deviation")
        self._allan_plot.setLabel('left', 'OADEV (T/√Hz)')
        self._allan_plot.setLabel('bottom', 'Averaging time τ (s)')
        self._allan_plot.setLogMode(True, True)
        allan_layout = QVBoxLayout(self.ui.sensitivity_allan_widget)
        allan_layout.setContentsMargins(0, 0, 0, 0)
        allan_layout.addWidget(self._allan_plot)

        self._connect_widgets()

    def _connect_widgets(self):
        ui = self.ui
        ui.sensitivity_run_btn.clicked.connect(self._on_run_sensitivity)
        ui.sensitivity_allan_btn.clicked.connect(self._on_run_allan)
        ui.sensitivity_save_npz_btn.clicked.connect(self._on_save_npz)
        ui.sensitivity_save_png_btn.clicked.connect(self._on_save_png)

    @Slot()
    def _on_run_sensitivity(self):
        mag_result = self.state.mag_stability_result
        if mag_result is None:
            QMessageBox.information(None, "No Data", "Run a magnetometry measurement first.")
            return
        sweep_result = self.state.sweep_inflection_result
        peak_params = (sweep_result.get("peak_params1", []) +
                       sweep_result.get("peak_params2", [])) if sweep_result else []

        time_override = self.ui.sensitivity_time_override_spin.value() or None
        slope_override = self.ui.sensitivity_slope_override_spin.value() or None

        try:
            self._sensitivity_result = qdm.analyze_stability_data(
                stability_cube=mag_result["stability_cube"],
                acquisition_settings=self.state.build_metadata(),
                peak_params=peak_params if peak_params else None,
                slope_override=slope_override,
                time_per_point_override=time_override,
            )
            self._update_sensitivity_display()
        except Exception as e:
            QMessageBox.critical(None, "Sensitivity Error", str(e))

    def _update_sensitivity_display(self):
        result = self._sensitivity_result
        if result is None:
            return
        sens_map = result.get("sensitivity_map_T_sqrtHz")
        if sens_map is not None:
            self._sens_view.setImage(sens_map.T * 1e6, autoLevels=True)  # µT/√Hz

        mean_sens = result.get("mean_sensitivity_nT_sqrtHz")
        shot_noise = result.get("shot_noise_limit_nT_sqrtHz")
        stats_parts = []
        if mean_sens:
            stats_parts.append(f"Mean: {mean_sens:.1f} nT/√Hz")
        if shot_noise:
            stats_parts.append(f"Shot-noise limit: {shot_noise:.1f} nT/√Hz")
        self.ui.sensitivity_stats_label.setText("   ".join(stats_parts))

    @Slot()
    def _on_run_allan(self):
        if self._sensitivity_result is None:
            QMessageBox.information(None, "Run Sensitivity First",
                "Run sensitivity analysis before Allan variance.")
            return
        try:
            self._allan_result = qdm.analyze_allan_variance(
                self._sensitivity_result, show_plot=False)
            taus = self._allan_result.get("taus", [])
            adevs = self._allan_result.get("adevs", [])
            shot_adevs = self._allan_result.get("shot_noise_adevs", [])
            self._allan_plot.clear()
            self._allan_plot.plot(taus, adevs, pen='c', name='Measured')
            if shot_adevs:
                self._allan_plot.plot(taus, shot_adevs, pen=pg.mkPen('r', style=2),
                                      name='Shot noise limit')
        except Exception as e:
            QMessageBox.critical(None, "Allan Variance Error", str(e))

    def save_data(self):
        if self._sensitivity_result is None:
            return False
        self._on_save_npz()
        return True

    @Slot()
    def _on_save_npz(self):
        if self._sensitivity_result is None:
            return
        stem = self.state.build_save_filename(
            "sensitivity", user_prefix=self.ui.sensitivity_prefix_edit.text())
        save_dir = Path(self.state.save_base_path) / self.state.save_subfolder
        save_dir.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            save_dir / f"{stem}.npz",
            metadata=str(self.state.build_metadata()),
            **{k: v for k, v in self._sensitivity_result.items()
               if isinstance(v, np.ndarray)},
        )

    @Slot()
    def _on_save_png(self):
        stem = self.state.build_save_filename(
            "sensitivity", user_prefix=self.ui.sensitivity_prefix_edit.text())
        save_dir = Path(self.state.save_base_path) / self.state.save_subfolder
        save_dir.mkdir(parents=True, exist_ok=True)
        exporter = pg.exporters.ImageExporter(self._sens_view.imageItem)
        exporter.export(str(save_dir / f"{stem}_map.png"))
        exporter2 = pg.exporters.ImageExporter(self._allan_plot.plotItem)
        exporter2.export(str(save_dir / f"{stem}_allan.png"))
```

**Add to ODMRMainWindow.__init__:**
```python
from tabs.sensitivity_tab import SensitivityTabHandler
self._sensitivity_handler = SensitivityTabHandler(self.ui.sensitivity_tab, self.state)
```

**Commit:**
```bash
git add GUI/odmr_app/tabs/sensitivity_tab.py GUI/odmr_app/odmr_main_window.py
git commit -m "feat(odmr-app): implement Sensitivity tab with sensitivity map and Allan deviation"
```

---

## Task 16: Wire "Save All" Button

**In `odmr_main_window.py`, replace `_on_save_all`:**

```python
@Slot()
def _on_save_all(self):
    """Trigger save on all tabs that have data."""
    saved = []
    handlers = [
        ("Sweep",        self._sweep_handler),
        ("Magnetometry", self._mag_handler),
        ("Analysis",     self._analysis_handler),
        ("Sensitivity",  self._sensitivity_handler),
    ]
    for name, handler in handlers:
        try:
            if handler.save_data():
                saved.append(name)
        except Exception as e:
            self.statusBar().showMessage(f"Save error in {name}: {e}", 5000)
            return
    if saved:
        self.statusBar().showMessage(f"Saved: {', '.join(saved)}", 4000)
    else:
        self.statusBar().showMessage("No data to save yet.", 3000)
```

**Commit:**
```bash
git add GUI/odmr_app/odmr_main_window.py
git commit -m "feat(odmr-app): wire Save All button to all tab handlers"
```

---

## Task 17: Integrate with launch_all_apps.py

**Files:**
- Backup: `GUI/legacy/launch_all_apps_2026-02-20_v1.py`
- Modify: `GUI/launch_all_apps.py`

**Step 1: Backup**
```bash
cp GUI/launch_all_apps.py GUI/legacy/launch_all_apps_2026-02-20_v1.py
```

**Step 2: Add ODMR app to launcher**

In `GUI/launch_all_apps.py`, add to `AppLauncher`:

```python
# In __init__:
self.odmr_app = None

# New method:
def launch_odmr_app(self, x=100, y=50):
    """Launch ODMR magnetometry app."""
    import sys
    odmr_path = str(Path(__file__).parent / "odmr_app")
    if odmr_path not in sys.path:
        sys.path.insert(0, odmr_path)
    from odmr_app.odmr_app import main as odmr_main
    self.odmr_app = odmr_main(shared_state=self.shared_state)
    self.odmr_app.setGeometry(x, y, 1600, 1000)
    print("[Launcher] ODMR App launched")
```

Update `main()`:
```python
def main():
    launcher = AppLauncher()
    launcher.launch_laser_power_monitor(x=50, y=50)
    launcher.launch_pid_controller(x=550, y=50)
    launcher.launch_camera_app(x=1050, y=50)   # monitoring camera
    launcher.launch_odmr_app(x=100, y=50)       # ODMR app (separate monitor)
    launcher.run()
```

**Step 3: Test standalone ODMR app**
```bash
cd GUI
python odmr_app/odmr_app.py
```

**Step 4: Test via launcher (optional, requires all hardware or simulation)**
```bash
cd GUI
python launch_all_apps.py
```

**Step 5: Commit**
```bash
git add GUI/launch_all_apps.py GUI/legacy/launch_all_apps_2026-02-20_v1.py
git commit -m "feat(odmr-app): integrate ODMR app into launch_all_apps.py launcher"
```

---

## Phase 4 Complete — Final Integration Checklist

Run the full test suite one last time:
```bash
cd GUI/odmr_app
python -m pytest tests/ -v
```

Manual end-to-end test (simulation mode):

- [ ] Launch `python odmr_app/odmr_app.py`
- [ ] File > Load Config restores previous session state
- [ ] Settings tab shows correct perf_* values
- [ ] Camera tab: start/stop stream works
- [ ] RF panel: Connect RF (simulation or real)
- [ ] ODMR Sweep tab: run sweep (sim mode), spectrum updates, inflection table fills
- [ ] Send to Magnetometry: inflection table auto-populates in Magnetometry tab
- [ ] Load/save preset round-trip works
- [ ] Save/load inflection points to JSON works
- [ ] Start Measurement: progress bar updates, live preview updates
- [ ] Analysis tab: auto-populates after measurement, Reanalyze button works
- [ ] Sensitivity tab: Run Sensitivity Analysis and Run Allan Variance work
- [ ] Save All: saves files with correct naming convention
- [ ] File > Save Config; crash; File > Load Config restores full state
- [ ] Close app: config auto-saved

```bash
git log --oneline -15
```

**All four phases complete. The ODMR app is ready for hardware testing.**
