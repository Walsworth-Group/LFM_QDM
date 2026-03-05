"""
BgSubtractionWorker — Background QThread for field-map background subtraction.

Runs ``qdm_gen.analyze_background_subtraction`` off the main thread so the
UI stays responsive while numpy/scipy/matplotlib work is executing.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QThread, Signal

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import qdm_gen as qdm


class BgSubtractionWorker(QThread):
    """
    Worker thread that executes ``qdm.analyze_background_subtraction``.

    Parameters
    ----------
    bg_file : str
        Full path to the background .npz file (measurement without sample).
    sample_file : str
        Full path to the sample .npz file (measurement with sample).
    gaussian_sigma : float
        Sigma (pixels) for Gaussian denoising (default 7.0).

    Signals
    -------
    completed : dict
        Emitted with the result dict on success.
    failed : str
        Emitted with the error message on exception.
    """

    completed = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        bg_file: str,
        sample_file: str,
        gaussian_sigma: float = 7.0,
        parent=None,
    ):
        """
        Initialise the worker.

        Parameters
        ----------
        bg_file : str
            Path to background .npz file.
        sample_file : str
            Path to sample .npz file.
        gaussian_sigma : float
            Gaussian denoising sigma in pixels.
        parent : QObject, optional
            Qt parent object.
        """
        super().__init__(parent)
        self._bg_file = bg_file
        self._sample_file = sample_file
        self._gaussian_sigma = gaussian_sigma

    def run(self):
        """Execute background subtraction in the worker thread."""
        try:
            result = qdm.analyze_background_subtraction(
                bg_file=self._bg_file,
                sample_file=self._sample_file,
                gaussian_sigma=self._gaussian_sigma,
                show_plot=False,
                save_fig=False,
                save_data=False,
            )
            self.completed.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
