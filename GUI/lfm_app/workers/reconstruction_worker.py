"""
ReconstructionWorker -- QThread for LFM image deconvolution.

Takes a raw LFM image and calibration results, runs iterative
Richardson-Lucy-style deconvolution using pyolaf forward/backward projections.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PySide6.QtCore import QThread, Signal

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_PYOLAF_ROOT = _PROJECT_ROOT / "pyolaf-main"

for _p in [str(_PROJECT_ROOT), str(_PYOLAF_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# CuPy / NumPy fallback
try:
    import cupy
    from cupy.fft import fftshift, ifft2, fft2
    _has_cupy = True
except ImportError:
    cupy = np
    from numpy.fft import fftshift, ifft2, fft2
    _has_cupy = False

if _has_cupy:
    _mempool = cupy.get_default_memory_pool()
    # Set GPU memory limit to 7.5 GB (same as pyolaf example)
    _mempool.set_limit(int(7.5 * 2**30))


class ReconstructionWorker(QThread):
    """
    Background thread for LFM iterative deconvolution.

    Parameters
    ----------
    raw_image : np.ndarray
        2D raw light-field microscope image.
    calibration : dict
        Full calibration result dict from CalibrationWorker. Must contain:
        Camera, H, Ht, LensletCenters, Resolution, trans, imgSize,
        texSize, volumeSize, kernelFFT.
    num_iterations : int
        Number of deconvolution iterations.
    filter_flag : bool
        Whether to apply anti-aliasing filtering per iteration.
    """

    iteration_completed = Signal(int, int)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        raw_image: np.ndarray,
        calibration: dict,
        num_iterations: int = 1,
        filter_flag: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self._raw_image = raw_image
        self._calib = calibration
        self._num_iters = num_iterations
        self._filter_flag = filter_flag
        self._abort = False

    def abort(self):
        """Request the worker to stop at the next checkpoint."""
        self._abort = True

    def run(self):
        """Execute the iterative deconvolution pipeline."""
        try:
            from pyolaf.transform import transform_img
            from pyolaf.project import (
                LFM_forwardProject, LFM_backwardProject,
            )

            c = self._calib
            Camera = c["Camera"]
            H, Ht = c["H"], c["Ht"]
            LensletCenters = c["LensletCenters"]
            Resolution = c["Resolution"]
            trans = c["trans"]
            imgSize = c["imgSize"]
            texSize = c["texSize"]
            volumeSize = c["volumeSize"]
            kernelFFT = c["kernelFFT"]
            crange = Camera["range"]

            # Transform raw image to aligned grid
            img_arr = cupy.array(self._raw_image, dtype='float32')
            new = transform_img(img_arr, trans, LensletCenters['offset'])
            nmin = float(cupy.min(new)) if _has_cupy else float(np.min(new))
            nmax = float(cupy.max(new)) if _has_cupy else float(np.max(new))
            if nmax - nmin > 0:
                newnorm = (new - nmin) / (nmax - nmin)
            else:
                newnorm = new
            LFimage = newnorm

            # Initialize volume
            initVolume = np.ones(volumeSize, dtype='float32')

            if self._abort:
                return

            # Precompute normalization projections
            onesForward = LFM_forwardProject(
                H, initVolume, LensletCenters, Resolution,
                imgSize, crange, step=8)
            onesBack = LFM_backwardProject(
                Ht, onesForward, LensletCenters, Resolution,
                texSize, crange, step=8)

            if self._abort:
                return

            # Iterative deconvolution
            LFimage_gpu = cupy.asarray(LFimage) if _has_cupy else LFimage
            reconVolume = cupy.asarray(np.copy(initVolume)) if _has_cupy \
                else np.copy(initVolume)

            for i in range(self._num_iters):
                if self._abort:
                    return

                if i == 0:
                    LFimageGuess = onesForward
                else:
                    LFimageGuess = LFM_forwardProject(
                        H, reconVolume, LensletCenters, Resolution,
                        imgSize, crange, step=10)

                if _has_cupy:
                    _mempool.free_all_blocks()

                errorLFimage = LFimage_gpu / LFimageGuess * onesForward
                errorLFimage[~cupy.isfinite(errorLFimage)] = 0

                errorBack = LFM_backwardProject(
                    Ht, errorLFimage, LensletCenters, Resolution,
                    texSize, crange, step=10)

                if _has_cupy:
                    _mempool.free_all_blocks()

                errorBack = errorBack / onesBack
                errorBack[~cupy.isfinite(errorBack)] = 0

                # Multiplicative update
                reconVolume = reconVolume * errorBack

                # Anti-aliasing filter
                if self._filter_flag:
                    for j in range(errorBack.shape[2]):
                        reconVolume[:, :, j] = cupy.abs(
                            fftshift(ifft2(
                                kernelFFT[:, :, j]
                                * fft2(reconVolume[:, :, j])
                            ))
                        )

                reconVolume[~cupy.isfinite(reconVolume)] = 0

                if _has_cupy:
                    _mempool.free_all_blocks()

                self.iteration_completed.emit(i + 1, self._num_iters)

            # Convert result to numpy
            if _has_cupy:
                result = cupy.asnumpy(reconVolume)
            else:
                result = np.asarray(reconVolume)

            self.completed.emit(result)

        except Exception as exc:
            import traceback
            self.failed.emit(f"{exc}\n\n{traceback.format_exc()}")
