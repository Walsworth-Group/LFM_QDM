"""
AnalysisWorker — Background QThread for field-map analysis.

Runs ``qdm_gen.analyze_multi_point_magnetometry`` in a worker thread so the
main UI stays responsive during computationally intensive numpy/scipy operations
(outlier removal, Gaussian filtering, etc.).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PySide6.QtCore import QThread, Signal

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import qdm_gen as qdm


class AnalysisWorker(QThread):
    """
    Worker thread that executes ``qdm.analyze_multi_point_magnetometry``.

    Parameters
    ----------
    stability_cube : np.ndarray
        3-D float array (n_samples, ny, nx) in GHz frequency units.
    outlier_sigma : float
        Outlier removal threshold (number of standard deviations).
    reference_mode : str
        ``'global_mean'`` or ``'roi'``.
    denoise_method : str
        Denoising method (``'gaussian'``, ``'tv'``, ``'none'``, …).
    gaussian_sigma : float
        Sigma for Gaussian denoising in pixels.

    Signals
    -------
    analysis_completed : dict
        Emitted with the result dict when analysis finishes successfully.
    analysis_failed : str
        Emitted with the error message on exception.
    """

    analysis_completed = Signal(dict)
    analysis_failed = Signal(str)

    def __init__(
        self,
        stability_cube: np.ndarray,
        outlier_sigma: float,
        reference_mode: str,
        denoise_method: str,
        gaussian_sigma: float,
        parent=None,
    ):
        """
        Initialise the analysis worker.

        Parameters
        ----------
        stability_cube : np.ndarray
            3-D frequency-shift data (n_samples, ny, nx) in GHz.
        outlier_sigma : float
            Outlier removal threshold.
        reference_mode : str
            Reference mode for zero-field subtraction.
        denoise_method : str
            Denoising method name.
        gaussian_sigma : float
            Gaussian sigma in pixels (used when denoise_method='gaussian').
        parent : QObject, optional
            Qt parent object.
        """
        super().__init__(parent)
        self._cube = stability_cube
        self._kwargs = dict(
            outlier_sigma=outlier_sigma,
            reference_mode=reference_mode,
            denoise_method=denoise_method,
            gaussian_sigma=gaussian_sigma,
            show_plot=False,
            save_fig=False,
        )

    def run(self):
        """Execute the analysis in the worker thread."""
        try:
            result = qdm.analyze_multi_point_magnetometry(
                self._cube, **self._kwargs
            )
            self.analysis_completed.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.analysis_failed.emit(str(exc))
