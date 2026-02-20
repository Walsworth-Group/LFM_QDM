"""ODMR Sweep tab handler."""

import sys
import time
import numpy as np
from pathlib import Path

from PySide6.QtCore import Slot, QTimer, Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout, QMessageBox, QTableWidgetItem
import pyqtgraph as pg

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from state.odmr_state import ODMRAppState, CameraMode
from workers.odmr_sweep_worker import ODMRSweepWorker
from ui.ui_odmr_sweep_tab import Ui_sweep_tab_content


class SweepTabHandler:
    """Handles ODMR Sweep tab: controls, live plots, inflection table, save."""

    def __init__(self, tab_widget: QWidget, state: ODMRAppState,
                 stop_streaming_fn, set_camera_mode_fn):
        """
        Initialise the sweep tab handler.

        Parameters
        ----------
        tab_widget : QWidget
            The bare QWidget placeholder for the Sweep tab.
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
        self._last_plot_update = 0.0

        self.ui = Ui_sweep_tab_content()
        self.ui.setupUi(tab_widget)

        # Inject pyqtgraph plot widgets
        self._plot1 = pg.PlotWidget(title="Transition 1 (m=0\u2192\u22121)")
        self._plot2 = pg.PlotWidget(title="Transition 2 (m=0\u2192+1)")
        for plot in (self._plot1, self._plot2):
            plot.setLabel('left', 'Contrast (PL_sig/PL_ref)')
            plot.setLabel('bottom', 'Frequency (GHz)')
        plot_layout = QHBoxLayout(self.ui.sweep_plot_widget)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.addWidget(self._plot1)
        plot_layout.addWidget(self._plot2)

        self._curve1 = self._plot1.plot(pen='c', symbol=None)
        self._curve2 = self._plot2.plot(pen='y', symbol=None)
        self._fit_curve1 = self._plot1.plot(pen=pg.mkPen('r', width=2))
        self._fit_curve2 = self._plot2.plot(pen=pg.mkPen('r', width=2))

        # Inflection point vertical lines (4 per plot)
        dash_pen1 = pg.mkPen('g', style=Qt.PenStyle.DashLine)
        dash_pen2 = pg.mkPen('g', style=Qt.PenStyle.DashLine)
        self._inf_lines1 = [pg.InfiniteLine(angle=90, movable=False, pen=dash_pen1)
                            for _ in range(4)]
        self._inf_lines2 = [pg.InfiniteLine(angle=90, movable=False, pen=dash_pen2)
                            for _ in range(4)]
        for line in self._inf_lines1:
            self._plot1.addItem(line)
            line.setVisible(False)
        for line in self._inf_lines2:
            self._plot2.addItem(line)
            line.setVisible(False)

        # Configure inflection summary table columns
        self.ui.sweep_inflection_table.setColumnCount(4)
        self.ui.sweep_inflection_table.setHorizontalHeaderLabels(
            ["#", "Freq (GHz)", "Slope (GHz\u207b\u00b9)", "Contrast"])
        self.ui.sweep_inflection_table.setEditTriggers(
            self.ui.sweep_inflection_table.EditTrigger.NoEditTriggers)

        self._connect_widgets()
        self._sync_from_state()

    def _connect_widgets(self):
        """Connect UI widgets to state attributes and slot methods."""
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

        # State → UI (only sweep_running_changed comes through state)
        s.sweep_running_changed.connect(self._on_running_changed)

    def _sync_from_state(self):
        """Push current state values into the sweep tab widgets."""
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
        """Handle Start Sweep button click."""
        if not self.state.try_start_sweep():
            QMessageBox.warning(None, "Busy",
                "Magnetometry measurement is running. Stop it first.")
            return
        safe = self._stop_streaming()
        if not safe:
            self.state.camera_state.camera_streaming_changed.connect(
                self._on_streaming_stopped_then_sweep)
            return
        self._start_sweep_worker()

    @Slot(bool)
    def _on_streaming_stopped_then_sweep(self, is_streaming):
        """Start sweep once camera streaming has stopped."""
        if not is_streaming:
            try:
                self.state.camera_state.camera_streaming_changed.disconnect(
                    self._on_streaming_stopped_then_sweep)
            except RuntimeError:
                pass
            self._start_sweep_worker()

    def _start_sweep_worker(self):
        """Create and start the ODMRSweepWorker thread."""
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
        """Request the sweep worker to stop."""
        if self._worker and self._worker.isRunning():
            self._worker.stop()

    @Slot(bool)
    def _on_running_changed(self, running):
        """Update button states when sweep running state changes."""
        self.ui.sweep_start_btn.setEnabled(not running)
        self.ui.sweep_stop_btn.setEnabled(running)
        if not running:
            self._set_camera_mode(CameraMode.IDLE)

    @Slot(int, int)
    def _on_progress(self, current, total):
        """Update progress bar and time label."""
        self.ui.sweep_progress_bar.setMaximum(total)
        self.ui.sweep_progress_bar.setValue(current)
        self.ui.sweep_time_label.setText(f"{current}/{total} sweeps")

    @Slot(object, object, object, object, int)
    def _on_spectrum_updated(self, fl1, sp1, fl2, sp2, sweep_num):
        """Update live spectrum plots with throttling."""
        now = time.monotonic()
        min_interval = 1.0 / self.state.perf_ui_plot_throttle_fps
        if now - self._last_plot_update < min_interval:
            return
        self._last_plot_update = now
        self._curve1.setData(np.asarray(fl1), np.asarray(sp1))
        self._curve2.setData(np.asarray(fl2), np.asarray(sp2))

    @Slot(dict)
    def _on_sweep_completed(self, result):
        """Handle sweep completion: update state, plots, table, and buttons."""
        # Store in state and emit state-level signal for other tabs
        self.state.sweep_inflection_result = result
        self.state.sweep_completed.emit(result)

        # Update plots with final averaged spectra (already 1D)
        self._on_spectrum_updated(
            result["freqlist1"], result["spectrum1"],
            result["freqlist2"], result["spectrum2"],
            self.state.sweep_num_sweeps)

        # Show inflection point markers
        pts = result["inflection_points"]
        for i, line in enumerate(self._inf_lines1):
            if i < len(pts):
                line.setValue(pts[i])
                line.setVisible(True)
        for i, line in enumerate(self._inf_lines2):
            if i + 4 < len(pts):
                line.setValue(pts[i + 4])
                line.setVisible(True)

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
            table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            table.setItem(i, 1, QTableWidgetItem(f"{f:.6f}"))
            table.setItem(i, 2, QTableWidgetItem(f"{sl:+.4f}"))
            table.setItem(i, 3, QTableWidgetItem(f"{co:.6f}"))

    @Slot()
    def _on_send_to_mag(self):
        """Visually acknowledge that sweep result was sent to Magnetometry tab."""
        self.ui.sweep_send_to_mag_btn.setText("\u2713 Sent to Magnetometry")
        QTimer.singleShot(2000,
            lambda: self.ui.sweep_send_to_mag_btn.setText("Send to Magnetometry"))

    @Slot(str)
    def _on_sweep_failed(self, msg):
        """Handle sweep failure by resetting camera mode and showing error."""
        self._set_camera_mode(CameraMode.IDLE)
        QMessageBox.critical(None, "Sweep Failed", msg)

    def save_data(self):
        """Called by Save All. Returns True if data was saved."""
        if self.state.sweep_inflection_result is None:
            return False
        self._on_save_npz()
        self._on_save_png()
        return True

    @Slot()
    def _on_save_npz(self):
        """Save sweep result to a compressed .npz file."""
        result = self.state.sweep_inflection_result
        if result is None:
            QMessageBox.information(None, "No Data", "Run a sweep first.")
            return
        stem = self.state.build_save_filename(
            "odmr_freq_sweep",
            user_prefix=self.ui.sweep_prefix_edit.text())
        save_dir = Path(self.state.save_base_path) / self.state.save_subfolder
        save_dir.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            save_dir / f"{stem}.npz",
            freqlist1=result["freqlist1"],
            spectrum1=result["spectrum1"],
            freqlist2=result["freqlist2"],
            spectrum2=result["spectrum2"],
            inflection_points=np.array(result["inflection_points"]),
            inflection_slopes=np.array(result["inflection_slopes"]),
            inflection_contrasts=np.array(result["inflection_contrasts"]),
            metadata=str(self.state.build_metadata()),
        )

    @Slot()
    def _on_save_png(self):
        """Export sweep plots as PNG images."""
        result = self.state.sweep_inflection_result
        if result is None:
            return
        stem = self.state.build_save_filename(
            "odmr_freq_sweep",
            user_prefix=self.ui.sweep_prefix_edit.text())
        save_dir = Path(self.state.save_base_path) / self.state.save_subfolder
        save_dir.mkdir(parents=True, exist_ok=True)
        exporter1 = pg.exporters.ImageExporter(self._plot1.plotItem)
        exporter1.export(str(save_dir / f"{stem}_t1.png"))
        exporter2 = pg.exporters.ImageExporter(self._plot2.plotItem)
        exporter2.export(str(save_dir / f"{stem}_t2.png"))
