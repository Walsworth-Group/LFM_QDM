"""
Central state object for the LFM GUI application.

LFMAppState is a QObject that holds all configuration and runtime state for the
light field microscopy workflow.  All properties that affect the UI emit Qt
signals so that widgets can react without polling.

Typical usage::

    state = LFMAppState()
    state.calibration_stage_changed.connect(my_slot)
    state.calibration_stage = CalibrationStage.CONFIG_LOADED  # emits signal
"""

from __future__ import annotations

from enum import Enum

import numpy as np
from PySide6.QtCore import QObject, Signal


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CalibrationStage(str, Enum):
    """Progress stages of the LFM calibration pipeline."""

    UNCONFIGURED = "unconfigured"
    CONFIG_LOADED = "config_loaded"
    WHITE_LOADED = "white_loaded"
    GEOMETRY_READY = "geometry_ready"
    OPERATORS_READY = "operators_ready"


class CameraMode(str, Enum):
    """Operating mode for the camera subsystem."""

    IDLE = "idle"
    STREAMING = "streaming"
    ACQUIRING = "acquiring"


# ---------------------------------------------------------------------------
# State class
# ---------------------------------------------------------------------------


class LFMAppState(QObject):
    """
    Central state object for the LFM GUI application.

    All mutable properties emit Qt signals when changed so that any widget
    subscribed to those signals is notified automatically.  Transient runtime
    objects (calibration arrays, camera_state) are plain attributes with no
    associated signal unless noted.

    Parameters
    ----------
    shared_state : object, optional
        Reference to the application-wide ExperimentState.
    parent : QObject, optional
        Qt parent object.
    """

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    # Calibration
    calibration_stage_changed = Signal(str)
    calibration_progress = Signal(str, int, int)   # (stage_name, current, total)
    calibration_completed = Signal(dict)
    calibration_failed = Signal(str)

    # Reconstruction
    recon_running_changed = Signal(bool)
    recon_progress = Signal(int, int)              # (current_iter, total_iters)
    recon_completed = Signal(object)               # 3D numpy volume
    recon_failed = Signal(str)

    # Volume display
    current_depth_changed = Signal(int)
    volume_loaded = Signal(int, int, int)          # (ny, nx, n_depths)

    # Camera mode
    camera_mode_changed = Signal(str)

    # UI status
    status_message = Signal(str)

    # ------------------------------------------------------------------
    # Config keys (persisted via get_config / load_config)
    # ------------------------------------------------------------------

    _CONFIG_KEYS = [
        # pyolaf parameters
        "config_yaml_path",
        "white_image_path",
        "depth_range_min",
        "depth_range_max",
        "depth_step",
        "new_spacing_px",
        "super_res_factor",
        "lanczos_window_size",
        "filter_flag",
        "num_iterations",
        # Camera
        "lfm_camera_serial",
        # Display
        "display_colormap",
        "display_auto_levels",
        # Save
        "save_base_path",
        "save_subfolder",
        "save_timestamp_enabled",
    ]

    # ------------------------------------------------------------------
    # Constructor
    # ------------------------------------------------------------------

    def __init__(self, shared_state=None, parent=None):
        super().__init__(parent)

        # Shared references (no signals)
        self.shared_state = shared_state
        self.camera_state = None   # set by main window when embedding camera tab

        # ------------------------------------------------------------------
        # pyolaf configuration (persisted)
        # ------------------------------------------------------------------
        self._config_yaml_path: str = ""
        self._white_image_path: str = ""
        self._depth_range_min: float = -300.0
        self._depth_range_max: float = 300.0
        self._depth_step: float = 150.0
        self._new_spacing_px: int = 15
        self._super_res_factor: int = 5
        self._lanczos_window_size: int = 4
        self._filter_flag: bool = True
        self._num_iterations: int = 1

        # ------------------------------------------------------------------
        # Calibration results (not persisted — computed at runtime)
        # ------------------------------------------------------------------
        self._calibration_stage: CalibrationStage = CalibrationStage.UNCONFIGURED
        self.camera_dict: dict | None = None
        self.white_image: np.ndarray | None = None
        self.lenslet_centers: dict | None = None
        self.resolution: dict | None = None
        self.lenslet_grid_model: dict | None = None
        self.new_lenslet_grid_model: dict | None = None
        self.H = None
        self.Ht = None
        self.fix_all = None
        self.trans = None
        self.img_size = None
        self.tex_size = None
        self.volume_size = None
        self.kernel_fft = None

        # ------------------------------------------------------------------
        # Reconstruction state (not persisted)
        # ------------------------------------------------------------------
        self._recon_is_running: bool = False
        self._recon_volume: np.ndarray | None = None
        self.recon_raw_image: np.ndarray | None = None

        # ------------------------------------------------------------------
        # Display state
        # ------------------------------------------------------------------
        self._current_depth_index: int = 0
        self._display_colormap: str = "viridis"
        self._display_auto_levels: bool = True

        # ------------------------------------------------------------------
        # Camera
        # ------------------------------------------------------------------
        self._lfm_camera_serial: str = ""
        self._lfm_camera_mode: CameraMode = CameraMode.IDLE

        # ------------------------------------------------------------------
        # Save settings
        # ------------------------------------------------------------------
        self._save_base_path: str = ""
        self._save_subfolder: str = "lfm_data"
        self._save_timestamp_enabled: bool = True

    # ==================================================================
    # pyolaf configuration properties
    # ==================================================================

    @property
    def config_yaml_path(self) -> str:
        """Path to the LFM YAML configuration file."""
        return self._config_yaml_path

    @config_yaml_path.setter
    def config_yaml_path(self, value: str):
        self._config_yaml_path = str(value)

    @property
    def white_image_path(self) -> str:
        """Path to the white calibration image."""
        return self._white_image_path

    @white_image_path.setter
    def white_image_path(self, value: str):
        self._white_image_path = str(value)

    @property
    def depth_range_min(self) -> float:
        """Minimum depth for reconstruction (micrometers)."""
        return self._depth_range_min

    @depth_range_min.setter
    def depth_range_min(self, value: float):
        self._depth_range_min = float(value)

    @property
    def depth_range_max(self) -> float:
        """Maximum depth for reconstruction (micrometers)."""
        return self._depth_range_max

    @depth_range_max.setter
    def depth_range_max(self, value: float):
        self._depth_range_max = float(value)

    @property
    def depth_step(self) -> float:
        """Depth step size (micrometers)."""
        return self._depth_step

    @depth_step.setter
    def depth_step(self, value: float):
        self._depth_step = float(value)

    @property
    def new_spacing_px(self) -> int:
        """Lenslet spacing in pixels for downsampling."""
        return self._new_spacing_px

    @new_spacing_px.setter
    def new_spacing_px(self, value: int):
        self._new_spacing_px = int(value)

    @property
    def super_res_factor(self) -> int:
        """Super-resolution factor (multiple of lenslet resolution)."""
        return self._super_res_factor

    @super_res_factor.setter
    def super_res_factor(self, value: int):
        self._super_res_factor = int(value)

    @property
    def lanczos_window_size(self) -> int:
        """Window size for anti-aliasing Lanczos filter."""
        return self._lanczos_window_size

    @lanczos_window_size.setter
    def lanczos_window_size(self, value: int):
        self._lanczos_window_size = int(value)

    @property
    def filter_flag(self) -> bool:
        """Whether to apply anti-aliasing filtering during deconvolution."""
        return self._filter_flag

    @filter_flag.setter
    def filter_flag(self, value: bool):
        self._filter_flag = bool(value)

    @property
    def num_iterations(self) -> int:
        """Number of deconvolution iterations."""
        return self._num_iterations

    @num_iterations.setter
    def num_iterations(self, value: int):
        self._num_iterations = int(value)

    # ==================================================================
    # Calibration properties
    # ==================================================================

    @property
    def calibration_stage(self) -> CalibrationStage:
        """Current calibration pipeline stage."""
        return self._calibration_stage

    @calibration_stage.setter
    def calibration_stage(self, value):
        if not isinstance(value, CalibrationStage):
            value = CalibrationStage(value)
        self._calibration_stage = value
        self.calibration_stage_changed.emit(value.value)

    # ==================================================================
    # Reconstruction properties
    # ==================================================================

    @property
    def recon_is_running(self) -> bool:
        """Whether a reconstruction is currently in progress."""
        return self._recon_is_running

    @recon_is_running.setter
    def recon_is_running(self, value: bool):
        self._recon_is_running = bool(value)
        self.recon_running_changed.emit(self._recon_is_running)

    @property
    def recon_volume(self) -> np.ndarray | None:
        """3D reconstructed volume (ny, nx, n_depths)."""
        return self._recon_volume

    @recon_volume.setter
    def recon_volume(self, value):
        self._recon_volume = value
        if value is not None:
            ny, nx, nd = value.shape
            self.volume_loaded.emit(ny, nx, nd)

    # ==================================================================
    # Display properties
    # ==================================================================

    @property
    def current_depth_index(self) -> int:
        """Currently displayed depth slice index."""
        return self._current_depth_index

    @current_depth_index.setter
    def current_depth_index(self, value: int):
        self._current_depth_index = int(value)
        self.current_depth_changed.emit(self._current_depth_index)

    @property
    def display_colormap(self) -> str:
        """Colormap name for volume display."""
        return self._display_colormap

    @display_colormap.setter
    def display_colormap(self, value: str):
        self._display_colormap = str(value)

    @property
    def display_auto_levels(self) -> bool:
        """Whether to auto-scale display levels."""
        return self._display_auto_levels

    @display_auto_levels.setter
    def display_auto_levels(self, value: bool):
        self._display_auto_levels = bool(value)

    # ==================================================================
    # Camera properties
    # ==================================================================

    @property
    def lfm_camera_serial(self) -> str:
        """Serial number of the Basler camera for LFM."""
        return self._lfm_camera_serial

    @lfm_camera_serial.setter
    def lfm_camera_serial(self, value: str):
        self._lfm_camera_serial = str(value)

    @property
    def lfm_camera_mode(self) -> CameraMode:
        """Current camera operating mode."""
        return self._lfm_camera_mode

    @lfm_camera_mode.setter
    def lfm_camera_mode(self, value):
        if not isinstance(value, CameraMode):
            value = CameraMode(value)
        self._lfm_camera_mode = value
        self.camera_mode_changed.emit(value.value)

    # ==================================================================
    # Save properties
    # ==================================================================

    @property
    def save_base_path(self) -> str:
        """Base directory for saving data."""
        return self._save_base_path

    @save_base_path.setter
    def save_base_path(self, value: str):
        self._save_base_path = str(value)

    @property
    def save_subfolder(self) -> str:
        """Subfolder within save_base_path."""
        return self._save_subfolder

    @save_subfolder.setter
    def save_subfolder(self, value: str):
        self._save_subfolder = str(value)

    @property
    def save_timestamp_enabled(self) -> bool:
        """Whether to append timestamps to saved filenames."""
        return self._save_timestamp_enabled

    @save_timestamp_enabled.setter
    def save_timestamp_enabled(self, value: bool):
        self._save_timestamp_enabled = bool(value)

    # ==================================================================
    # Business logic
    # ==================================================================

    def can_start_calibration(self) -> bool:
        """Return True if minimum inputs exist to run calibration."""
        return bool(self._config_yaml_path and self._white_image_path)

    def can_start_reconstruction(self) -> bool:
        """Return True if calibration is complete and a raw image is available."""
        return (
            self._calibration_stage == CalibrationStage.OPERATORS_READY
            and self.recon_raw_image is not None
            and not self._recon_is_running
        )

    def store_calibration_result(self, result: dict):
        """
        Store all calibration results from CalibrationWorker into state.

        Parameters
        ----------
        result : dict
            Dict with keys: Camera, WhiteImage, LensletCenters, Resolution,
            LensletGridModel, NewLensletGridModel, H, Ht, FixAll, trans,
            imgSize, texSize, volumeSize, kernelFFT.
        """
        self.camera_dict = result["Camera"]
        self.white_image = result["WhiteImage"]
        self.lenslet_centers = result["LensletCenters"]
        self.resolution = result["Resolution"]
        self.lenslet_grid_model = result["LensletGridModel"]
        self.new_lenslet_grid_model = result["NewLensletGridModel"]
        self.H = result["H"]
        self.Ht = result["Ht"]
        self.fix_all = result["FixAll"]
        self.trans = result["trans"]
        self.img_size = result["imgSize"]
        self.tex_size = result["texSize"]
        self.volume_size = result["volumeSize"]
        self.kernel_fft = result["kernelFFT"]
        self.calibration_stage = CalibrationStage.OPERATORS_READY

    def clear_calibration(self):
        """Reset all calibration state."""
        self.camera_dict = None
        self.white_image = None
        self.lenslet_centers = None
        self.resolution = None
        self.lenslet_grid_model = None
        self.new_lenslet_grid_model = None
        self.H = None
        self.Ht = None
        self.fix_all = None
        self.trans = None
        self.img_size = None
        self.tex_size = None
        self.volume_size = None
        self.kernel_fft = None
        self.calibration_stage = CalibrationStage.UNCONFIGURED

    # ==================================================================
    # Config persistence
    # ==================================================================

    def get_config(self) -> dict:
        """
        Return a flat dict of all persistable configuration values.

        Returns
        -------
        dict
            Mapping of property name -> current value for every key in
            ``_CONFIG_KEYS``.
        """
        config = {}
        for key in self._CONFIG_KEYS:
            config[key] = getattr(self, key)
        return config

    def load_config(self, config: dict):
        """
        Restore configuration from a dict previously obtained via
        :meth:`get_config`.

        Unknown keys are silently ignored.

        Parameters
        ----------
        config : dict
            Mapping of property name -> value.
        """
        for key, value in config.items():
            if key in self._CONFIG_KEYS:
                try:
                    setattr(self, key, value)
                except Exception:
                    pass
