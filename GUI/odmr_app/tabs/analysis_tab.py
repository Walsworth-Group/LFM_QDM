"""Analysis tab handler — field map display and reanalysis controls."""

import sys
import numpy as np
from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QWidget, QVBoxLayout, QMessageBox
import pyqtgraph.exporters  # noqa: F401 — ensure exporters registered

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from state.odmr_state import ODMRAppState
from widgets.field_map_display import FieldMapDisplayWidget
from ui.ui_odmr_analysis_tab import Ui_analysis_tab_content

import qdm_gen as qdm


class AnalysisTabHandler:
    """Handles Analysis tab: 3-panel display, reanalysis, stats, save."""

    def __init__(self, tab_widget: QWidget, state: ODMRAppState):
        """
        Initialise the analysis tab handler.

        Parameters
        ----------
        tab_widget : QWidget
            The bare QWidget placeholder for the Analysis tab.
        state : ODMRAppState
            Central application state.
        """
        self.state = state

        self.ui = Ui_analysis_tab_content()
        self.ui.setupUi(tab_widget)

        # Populate combo boxes
        self.ui.analysis_denoise_combo.addItems(
            ['none', 'gaussian', 'tv', 'wavelet', 'nlm', 'bilateral'])
        self.ui.analysis_reference_combo.addItems(['global_mean', 'roi'])

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
        """Connect UI widgets to state attributes and slot methods."""
        s = self.state
        ui = self.ui

        ui.analysis_denoise_combo.currentTextChanged.connect(
            lambda t: setattr(s, 'analysis_denoise_method', t))
        ui.analysis_sigma_spin.valueChanged.connect(
            lambda v: setattr(s, 'analysis_gaussian_sigma', v))
        ui.analysis_outlier_spin.valueChanged.connect(
            lambda v: setattr(s, 'analysis_outlier_sigma', v))
        ui.analysis_reference_combo.currentTextChanged.connect(
            lambda t: setattr(s, 'analysis_reference_mode', t))

        ui.analysis_reanalyze_btn.clicked.connect(self._on_reanalyze)
        ui.analysis_save_npz_btn.clicked.connect(self._on_save_npz)
        ui.analysis_save_png_btn.clicked.connect(self._on_save_png)

        s.analysis_completed.connect(self._on_analysis_completed)

    def _sync_from_state(self):
        """Push current state values into the analysis tab widgets."""
        s = self.state
        ui = self.ui

        idx = ui.analysis_denoise_combo.findText(s.analysis_denoise_method)
        if idx >= 0:
            ui.analysis_denoise_combo.setCurrentIndex(idx)
        else:
            ui.analysis_denoise_combo.addItem(s.analysis_denoise_method)
            ui.analysis_denoise_combo.setCurrentText(s.analysis_denoise_method)

        ui.analysis_sigma_spin.setValue(s.analysis_gaussian_sigma)
        ui.analysis_outlier_spin.setValue(s.analysis_outlier_sigma)

        idx2 = ui.analysis_reference_combo.findText(s.analysis_reference_mode)
        if idx2 >= 0:
            ui.analysis_reference_combo.setCurrentIndex(idx2)
        else:
            ui.analysis_reference_combo.addItem(s.analysis_reference_mode)
            ui.analysis_reference_combo.setCurrentText(s.analysis_reference_mode)

    @Slot(dict)
    def _on_mag_completed(self, result):
        """Auto-run analysis when new magnetometry data arrives."""
        self._run_analysis(result["stability_cube"])

    @Slot()
    def _on_reanalyze(self):
        """Re-run analysis with current settings on stored magnetometry data."""
        result = self.state.mag_stability_result
        if result is None:
            QMessageBox.information(None, "No Data", "Run a measurement first.")
            return
        self._run_analysis(result["stability_cube"])

    def _run_analysis(self, stability_cube: np.ndarray):
        """
        Run analyze_multi_point_magnetometry on the given stability cube.

        Parameters
        ----------
        stability_cube : np.ndarray
            The stability cube in GHz units, shape (num_samples, ny, nx).
        """
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
        """Update field map display and stats label when analysis finishes."""
        self._field_display.update_from_result(result)

        proc = result.get("field_map_gauss_processed")
        if proc is not None:
            self.ui.analysis_stats_label.setText(
                f"Mean: {np.nanmean(proc):+.4f} G    "
                f"Std: {np.nanstd(proc):.4f} G    "
                f"Range: [{np.nanmin(proc):.4f}, {np.nanmax(proc):.4f}] G")

    def save_data(self):
        """Called by Save All. Returns True if data was saved."""
        result = self.state.analysis_field_map_result
        if result is None:
            return False
        self._on_save_npz()
        self._on_save_png()
        return True

    @Slot()
    def _on_save_npz(self):
        """Save field map analysis result to a compressed .npz file."""
        result = self.state.analysis_field_map_result
        if result is None:
            QMessageBox.information(None, "No Data", "Run analysis first.")
            return
        stem = self.state.build_save_filename(
            "field_map", user_prefix=self.ui.analysis_prefix_edit.text())
        save_dir = Path(self.state.save_base_path) / self.state.save_subfolder
        save_dir.mkdir(parents=True, exist_ok=True)
        save_dict = {}
        for k in ("field_map_gauss_raw", "field_map_gauss_denoised",
                  "field_map_gauss_processed"):
            v = result.get(k)
            if v is not None:
                save_dict[k] = v
        save_dict["metadata"] = str(self.state.build_metadata())
        np.savez_compressed(save_dir / f"{stem}.npz", **save_dict)

    @Slot()
    def _on_save_png(self):
        """Save the analysis figure as a PNG file."""
        result = self.state.analysis_field_map_result
        if result is None:
            return
        stem = self.state.build_save_filename(
            "field_map", user_prefix=self.ui.analysis_prefix_edit.text())
        save_dir = Path(self.state.save_base_path) / self.state.save_subfolder
        save_dir.mkdir(parents=True, exist_ok=True)
        fig = result.get("figure")
        if fig is not None:
            fig.savefig(str(save_dir / f"{stem}.png"), dpi=150, bbox_inches='tight')
