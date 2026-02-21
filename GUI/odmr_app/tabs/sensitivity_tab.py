"""Sensitivity tab handler."""

import sys
import numpy as np
from pathlib import Path

from PySide6.QtCore import Slot, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QMessageBox
import pyqtgraph as pg

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from state.odmr_state import ODMRAppState
from ui.ui_odmr_sensitivity_tab import Ui_sensitivity_tab_content

import qdm_gen as qdm


class SensitivityTabHandler:
    """Handles Sensitivity tab: sensitivity map, Allan deviation, save."""

    def __init__(self, tab_widget: QWidget, state: ODMRAppState):
        """
        Initialise the sensitivity tab handler.

        Parameters
        ----------
        tab_widget : QWidget
            The bare QWidget placeholder for the Sensitivity tab.
        state : ODMRAppState
            Central application state.
        """
        self.state = state
        self._sensitivity_result = None
        self._allan_result = None

        self.ui = Ui_sensitivity_tab_content()
        self.ui.setupUi(tab_widget)

        # Inject sensitivity map ImageView
        self._sens_view = pg.ImageView()
        self._sens_view.ui.roiBtn.hide()
        self._sens_view.ui.menuBtn.hide()
        self._sens_view.ui.histogram.hide()
        sens_layout = QVBoxLayout(self.ui.sensitivity_map_widget)
        sens_layout.setContentsMargins(0, 0, 0, 0)
        sens_layout.addWidget(self._sens_view)

        # Inject Allan deviation PlotWidget
        self._allan_plot = pg.PlotWidget(title="Allan Deviation")
        self._allan_plot.setLabel('left', 'OADEV (T/\u221aHz)')
        self._allan_plot.setLabel('bottom', 'Averaging time \u03c4 (s)')
        self._allan_plot.setLogMode(True, True)
        allan_layout = QVBoxLayout(self.ui.sensitivity_allan_widget)
        allan_layout.setContentsMargins(0, 0, 0, 0)
        allan_layout.addWidget(self._allan_plot)

        self._connect_widgets()

    def _connect_widgets(self):
        """Connect UI buttons to slot methods."""
        ui = self.ui
        ui.sensitivity_run_btn.clicked.connect(self._on_run_sensitivity)
        ui.sensitivity_allan_btn.clicked.connect(self._on_run_allan)
        ui.sensitivity_save_npz_btn.clicked.connect(self._on_save_npz)
        ui.sensitivity_save_png_btn.clicked.connect(self._on_save_png)

    @Slot()
    def _on_run_sensitivity(self):
        """Compute sensitivity from the stored magnetometry stability result."""
        mag_result = self.state.mag_stability_result
        if mag_result is None:
            QMessageBox.information(None, "No Data",
                "Run a magnetometry measurement first.")
            return
        sweep_result = self.state.sweep_inflection_result
        peak_params = []
        if sweep_result:
            peak_params = (sweep_result.get("peak_params1", []) +
                           sweep_result.get("peak_params2", []))

        time_override_val = self.ui.sensitivity_time_override_spin.value()
        slope_override_val = self.ui.sensitivity_slope_override_spin.value()
        # 0.0 is the "Auto" sentinel (per the UI spin box specialValueText)
        time_override = time_override_val if time_override_val > 0.0 else None
        slope_override = slope_override_val if slope_override_val > 0.0 else None

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
        """Update sensitivity map image and stats label from result."""
        result = self._sensitivity_result
        if result is None:
            return
        sens_map = result.get("sensitivity_map_T_sqrtHz")
        if sens_map is not None:
            self._sens_view.setImage(sens_map.T * 1e6, autoLevels=True)

        stats_parts = []
        mean_sens = result.get("mean_sensitivity_nT_sqrtHz")
        shot_noise = result.get("shot_noise_limit_nT_sqrtHz")
        if mean_sens is not None:
            stats_parts.append(f"Mean: {mean_sens:.1f} nT/\u221aHz")
        if shot_noise is not None:
            stats_parts.append(f"Shot-noise limit: {shot_noise:.1f} nT/\u221aHz")
        self.ui.sensitivity_stats_label.setText("   ".join(stats_parts))

    @Slot()
    def _on_run_allan(self):
        """Compute and plot Allan deviation from the sensitivity result."""
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
                self._allan_plot.plot(
                    taus, shot_adevs,
                    pen=pg.mkPen('r', style=Qt.PenStyle.DashLine),
                    name='Shot noise limit')
        except Exception as e:
            QMessageBox.critical(None, "Allan Variance Error", str(e))

    def save_data(self, global_prefix=""):
        """Called by Save All. Returns True if data was saved."""
        if self._sensitivity_result is None:
            return False
        self._on_save_npz(global_prefix=global_prefix)
        self._on_save_png(global_prefix=global_prefix)
        return True

    @Slot()
    def _on_save_npz(self, global_prefix=""):
        """Save sensitivity result arrays to a compressed .npz file."""
        if self._sensitivity_result is None:
            return
        tab_prefix = self.ui.sensitivity_prefix_edit.text().strip()
        combined = "_".join(p for p in [global_prefix, tab_prefix] if p)
        stem = self.state.build_save_filename("sensitivity", user_prefix=combined)
        save_dir = Path(self.state.save_base_path) / self.state.save_subfolder
        save_dir.mkdir(parents=True, exist_ok=True)
        save_dict = {"metadata": str(self.state.build_metadata())}
        for k, v in self._sensitivity_result.items():
            if isinstance(v, np.ndarray):
                save_dict[k] = v
        np.savez_compressed(save_dir / f"{stem}.npz", **save_dict)

    @Slot()
    def _on_save_png(self, global_prefix=""):
        """Export the sensitivity map and Allan deviation plot as PNG images."""
        tab_prefix = self.ui.sensitivity_prefix_edit.text().strip()
        combined = "_".join(p for p in [global_prefix, tab_prefix] if p)
        stem = self.state.build_save_filename("sensitivity", user_prefix=combined)
        save_dir = Path(self.state.save_base_path) / self.state.save_subfolder
        save_dir.mkdir(parents=True, exist_ok=True)
        exporter = pg.exporters.ImageExporter(self._sens_view.imageItem)
        exporter.export(str(save_dir / f"{stem}_map.png"))
        exporter2 = pg.exporters.ImageExporter(self._allan_plot.plotItem)
        exporter2.export(str(save_dir / f"{stem}_allan.png"))
