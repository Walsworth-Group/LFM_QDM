"""
CalibrationWorker -- QThread for computing LFM geometry and matrix operators.

Runs the pyolaf calibration pipeline:
1. LFM_setCameraParams (fast)
2. Load white calibration image (fast)
3. LFM_computeGeometryParameters (moderate: lenslet detection)
4. LFM_computeLFMatrixOperators (slow: PSF computation)
5. LFM_retrieveTransformation + anti-aliasing kernels (fast)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PySide6.QtCore import QThread, Signal

# ---------------------------------------------------------------------------
# Path setup to reach pyolaf
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_PYOLAF_ROOT = _PROJECT_ROOT / "pyolaf-main"

for _p in [str(_PROJECT_ROOT), str(_PYOLAF_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


class CalibrationWorker(QThread):
    """
    Background thread that runs the full LFM calibration pipeline.

    Parameters
    ----------
    config_yaml_path : str
        Path to the LFM YAML configuration file.
    white_image_path : str
        Path to the white calibration TIFF image.
    white_image_array : np.ndarray or None
        Pre-loaded white image (e.g. from camera capture). If provided,
        takes priority over white_image_path.
    depth_range : tuple of (float, float)
        Depth range (min, max) in micrometers.
    depth_step : float
        Depth step in micrometers.
    new_spacing_px : int
        Lenslet spacing in pixels for downsampling.
    super_res_factor : int
        Super-resolution factor.
    lanczos_window_size : int
        Window size for anti-aliasing filter.
    """

    stage_progress = Signal(str, int, int)
    completed = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        config_yaml_path: str,
        white_image_path: str,
        white_image_array: np.ndarray | None = None,
        depth_range: tuple = (-300.0, 300.0),
        depth_step: float = 150.0,
        new_spacing_px: int = 15,
        super_res_factor: int = 5,
        lanczos_window_size: int = 4,
        parent=None,
    ):
        super().__init__(parent)
        self._config_yaml_path = config_yaml_path
        self._white_image_path = white_image_path
        self._white_image_array = white_image_array
        self._depth_range = list(depth_range)
        self._depth_step = depth_step
        self._new_spacing_px = new_spacing_px
        self._super_res_factor = super_res_factor
        self._lanczos_window_size = lanczos_window_size
        self._abort = False

    def abort(self):
        """Request the worker to stop at the next checkpoint."""
        self._abort = True

    def run(self):
        """Execute the full calibration pipeline."""
        try:
            from pyolaf.geometry import (
                LFM_computeGeometryParameters, LFM_setCameraParams,
            )
            from pyolaf.lf import LFM_computeLFMatrixOperators
            from pyolaf.transform import (
                LFM_retrieveTransformation, format_transform,
                get_transformed_shape,
            )
            from pyolaf.aliasing import lanczosfft, LFM_computeDepthAdaptiveWidth

            # Stage 1: Camera params
            self.stage_progress.emit("Loading camera config...", 0, 5)
            Camera = LFM_setCameraParams(
                self._config_yaml_path, self._new_spacing_px)
            if self._abort:
                return

            # Stage 2: Load white image
            self.stage_progress.emit("Loading white image...", 1, 5)
            if self._white_image_array is not None:
                WhiteImage = self._white_image_array
            else:
                import tifffile
                WhiteImage = tifffile.imread(self._white_image_path)
            if self._abort:
                return

            # Stage 3: Geometry
            self.stage_progress.emit(
                "Computing geometry parameters...", 2, 5)
            (LensletCenters, Resolution,
             LensletGridModel, NewLensletGridModel) = \
                LFM_computeGeometryParameters(
                    Camera, WhiteImage,
                    self._depth_range, self._depth_step,
                    self._super_res_factor, False)
            if self._abort:
                return

            # Stage 4: Matrix operators (slowest)
            self.stage_progress.emit(
                "Computing PSF & matrix operators...", 3, 5)
            H, Ht = LFM_computeLFMatrixOperators(
                Camera, Resolution, LensletCenters)
            if self._abort:
                return

            # Stage 5: Transformation + anti-aliasing
            self.stage_progress.emit(
                "Computing transformation & filters...", 4, 5)
            FixAll = LFM_retrieveTransformation(
                LensletGridModel, NewLensletGridModel)
            trans = format_transform(FixAll)
            imgSize = get_transformed_shape(WhiteImage.shape, trans)
            imgSize = imgSize + (1 - np.remainder(imgSize, 2))

            texSize = np.ceil(
                np.multiply(imgSize, Resolution['texScaleFactor'])
            ).astype('int32')
            texSize = texSize + (1 - np.remainder(texSize, 2))

            ndepths = len(Resolution['depths'])
            volumeSize = np.append(texSize, ndepths).astype('int32')

            widths = LFM_computeDepthAdaptiveWidth(Camera, Resolution)
            kernelFFT = lanczosfft(
                volumeSize, widths, self._lanczos_window_size)

            self.stage_progress.emit("Calibration complete.", 5, 5)

            result = {
                "Camera": Camera,
                "WhiteImage": WhiteImage,
                "LensletCenters": LensletCenters,
                "Resolution": Resolution,
                "LensletGridModel": LensletGridModel,
                "NewLensletGridModel": NewLensletGridModel,
                "H": H,
                "Ht": Ht,
                "FixAll": FixAll,
                "trans": trans,
                "imgSize": imgSize,
                "texSize": texSize,
                "volumeSize": volumeSize,
                "kernelFFT": kernelFFT,
            }
            self.completed.emit(result)

        except Exception as exc:
            import traceback
            self.failed.emit(f"{exc}\n\n{traceback.format_exc()}")
