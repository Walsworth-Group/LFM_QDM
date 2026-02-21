"""
Central state object for the ODMR GUI application.

ODMRAppState is a QObject that holds all configuration and runtime state for the
ODMR magnetometry workflow.  All properties that affect the UI emit Qt signals so
that widgets can react without polling.

Typical usage::

    state = ODMRAppState(shared_state=experiment_state)
    state.rf_connection_changed.connect(my_slot)
    state.rf_is_connected = True   # triggers signal automatically
"""

from __future__ import annotations

import threading
from datetime import datetime
from enum import Enum

from PySide6.QtCore import QObject, Signal


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CameraMode(str, Enum):
    """Operating mode for the camera subsystem."""

    IDLE = "idle"
    STREAMING = "streaming"
    ACQUIRING = "acquiring"


# ---------------------------------------------------------------------------
# State class
# ---------------------------------------------------------------------------


class ODMRAppState(QObject):
    """
    Central state object for the ODMR GUI application.

    All mutable properties emit Qt signals when changed so that any widget
    subscribed to those signals is notified automatically.  Transient runtime
    objects (sg384_controller, camera_state, shared_state) are plain attributes
    with no associated signal.

    Parameters
    ----------
    shared_state : object, optional
        Reference to the application-wide ExperimentState (laser / PID state).
        Stored as ``self.shared_state``.
    parent : QObject, optional
        Qt parent object.
    """

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    # RF / microwave subsystem
    rf_connection_changed = Signal(bool)
    rf_frequency_changed = Signal(float)

    # Sweep subsystem
    sweep_running_changed = Signal(bool)
    sweep_progress = Signal(int, int)
    sweep_spectrum_updated = Signal(object, object, object, object, int)
    sweep_completed = Signal(dict)

    # Magnetometry subsystem
    mag_running_changed = Signal(bool)
    mag_progress = Signal(int, int)
    mag_sample_acquired = Signal(int, object)
    mag_completed = Signal(dict)

    # Analysis
    analysis_completed = Signal(dict)

    # Camera mode
    camera_mode_changed = Signal(str)

    # Camera settings pushed from sweep to magnetometry
    mag_camera_settings_pushed = Signal(int, int)   # (exposure_us, n_frames)

    # ------------------------------------------------------------------
    # Config keys (persisted via get_config / load_config)
    # ------------------------------------------------------------------

    _CONFIG_KEYS = [
        # RF
        "rf_is_connected",
        "rf_current_freq_ghz",
        "rf_amplitude_dbm",
        "rf_address",
        # Per-operation camera
        "sweep_exposure_time_us",
        "sweep_n_frames_per_point",
        "sweep_hw_bin_x",
        "sweep_hw_bin_y",
        "mag_exposure_time_us",
        "mag_n_frames_per_point",
        "mag_hw_bin_x",
        "mag_hw_bin_y",
        # Sweep
        "sweep_freq1_start_ghz",
        "sweep_freq1_end_ghz",
        "sweep_freq1_steps",
        "sweep_freq2_start_ghz",
        "sweep_freq2_end_ghz",
        "sweep_freq2_steps",
        "sweep_ref_freq_ghz",
        "sweep_num_sweeps",
        "sweep_n_lorentz",
        # Magnetometry
        "mag_num_samples",
        "mag_bin_x",
        "mag_bin_y",
        "mag_selected_indices",
        "mag_selected_parities",
        # Analysis
        "analysis_denoise_method",
        "analysis_gaussian_sigma",
        "analysis_outlier_sigma",
        "analysis_reference_mode",
        # Camera
        "odmr_camera_serial",
        # Save settings
        "save_base_path",
        "save_subfolder",
        "save_timestamp_enabled",
        "save_prefix_sweep",
        "save_prefix_magnetometry",
        "save_prefix_field_map",
        "save_prefix_sensitivity",
        # Performance settings
        "perf_rf_poll_interval_s",
        "perf_ui_plot_throttle_fps",
        "perf_mw_settling_time_s",
        "perf_n_frames_per_point",
        "perf_worker_loop_sleep_s",
        "perf_sweep_emit_every_n",
        "perf_live_avg_update_interval_samples",
        "perf_autosave_interval_samples",
        "perf_camera_exposure_time_us",
    ]

    # ------------------------------------------------------------------
    # Constructor
    # ------------------------------------------------------------------

    def __init__(self, shared_state=None, parent=None):
        super().__init__(parent)

        # Shared hardware references (no signals; set directly)
        self.shared_state = shared_state
        self.sg384_controller = None
        self.sg384_lock = threading.Lock()
        self.camera_state = None

        # ------------------------------------------------------------------
        # RF subsystem
        # ------------------------------------------------------------------
        self._rf_is_connected: bool = False
        self._rf_current_freq_ghz: float = 2.870  # NV zero-field resonance (GHz)
        self._rf_amplitude_dbm: float = -10.0
        self._rf_address: str = "192.168.1.100"

        # ------------------------------------------------------------------
        # Per-operation camera settings (sweep)
        self._sweep_exposure_time_us: int = 10000
        self._sweep_n_frames_per_point: int = 5
        self._sweep_hw_bin_x: int = 4   # hardware binning, X (columns); max=4 for acA1920
        self._sweep_hw_bin_y: int = 4   # hardware binning, Y (rows);    max=4 for acA1920

        # Per-operation camera settings (magnetometry)
        self._mag_exposure_time_us: int = 10000
        self._mag_n_frames_per_point: int = 5
        self._mag_hw_bin_x: int = 4     # hardware binning, X (columns); max=4 for acA1920
        self._mag_hw_bin_y: int = 4     # hardware binning, Y (rows);    max=4 for acA1920

        # ------------------------------------------------------------------
        # Sweep subsystem
        # ------------------------------------------------------------------
        self._sweep_freq1_start_ghz: float = 2.516
        self._sweep_freq1_end_ghz: float = 2.528
        self._sweep_freq1_steps: int = 201
        self._sweep_freq2_start_ghz: float = 3.210
        self._sweep_freq2_end_ghz: float = 3.220
        self._sweep_freq2_steps: int = 201
        self._sweep_ref_freq_ghz: float = 1.0
        self._sweep_num_sweeps: int = 1
        self._sweep_n_lorentz: int = 2
        self._sweep_is_running: bool = False
        self._sweep_current_sweep: int = 0
        self._sweep_spectrum1 = None
        self._sweep_spectrum2 = None
        self._sweep_freqlist1 = None
        self._sweep_freqlist2 = None
        self._sweep_inflection_result = None

        # ------------------------------------------------------------------
        # Magnetometry subsystem
        # ------------------------------------------------------------------
        self._mag_num_samples: int = 200
        self._mag_bin_x: int = 1
        self._mag_bin_y: int = 1
        self._mag_selected_indices: list = [1, 4, 0, 5, 8, 0]
        self._mag_selected_parities: list = [1, 1, 0, -1, -1, 0]
        self._mag_is_running: bool = False
        self._mag_current_sample: int = 0
        self._mag_stability_result = None

        # ------------------------------------------------------------------
        # Analysis subsystem
        # ------------------------------------------------------------------
        self._analysis_denoise_method: str = "gaussian"
        self._analysis_gaussian_sigma: float = 15.0
        self._analysis_outlier_sigma: float = 4.0
        self._analysis_reference_mode: str = "global_mean"
        self._analysis_field_map_result = None

        # ------------------------------------------------------------------
        # Camera mode
        # ------------------------------------------------------------------
        self._odmr_camera_mode: CameraMode = CameraMode.IDLE
        self._odmr_camera_serial: str = "25061217"  # Basler acA1920-155um (ODMR camera)

        # ------------------------------------------------------------------
        # Save settings
        # ------------------------------------------------------------------
        self._save_base_path: str = ""
        self._save_subfolder: str = ""
        self._save_timestamp_enabled: bool = True
        self._save_prefix_sweep: str = ""
        self._save_prefix_magnetometry: str = ""
        self._save_prefix_field_map: str = ""
        self._save_prefix_sensitivity: str = ""

        # ------------------------------------------------------------------
        # Performance settings
        # ------------------------------------------------------------------
        self._perf_rf_poll_interval_s: float = 0.5
        self._perf_ui_plot_throttle_fps: float = 10.0
        self._perf_mw_settling_time_s: float = 0.010
        self._perf_n_frames_per_point: int = 5
        self._perf_worker_loop_sleep_s: float = 0.005
        self._perf_sweep_emit_every_n: int = 1
        self._perf_live_avg_update_interval_samples: int = 10
        self._perf_autosave_interval_samples: int = 50
        self._perf_camera_exposure_time_us: int = 10000

    # ==================================================================
    # RF subsystem properties
    # ==================================================================

    @property
    def rf_is_connected(self) -> bool:
        """Whether the SG384 RF generator is connected."""
        return self._rf_is_connected

    @rf_is_connected.setter
    def rf_is_connected(self, value: bool):
        self._rf_is_connected = bool(value)
        self.rf_connection_changed.emit(self._rf_is_connected)

    @property
    def rf_current_freq_ghz(self) -> float:
        """Current RF output frequency in GHz."""
        return self._rf_current_freq_ghz

    @rf_current_freq_ghz.setter
    def rf_current_freq_ghz(self, value: float):
        self._rf_current_freq_ghz = float(value)
        self.rf_frequency_changed.emit(self._rf_current_freq_ghz)

    @property
    def rf_amplitude_dbm(self) -> float:
        """RF output amplitude in dBm."""
        return self._rf_amplitude_dbm

    @rf_amplitude_dbm.setter
    def rf_amplitude_dbm(self, value: float):
        self._rf_amplitude_dbm = float(value)

    @property
    def rf_address(self) -> str:
        """TCP/IP address of the SG384 signal generator."""
        return self._rf_address

    @rf_address.setter
    def rf_address(self, value: str):
        self._rf_address = str(value)

    # ==================================================================
    # Sweep subsystem properties
    # ==================================================================

    @property
    def sweep_freq1_start_ghz(self) -> float:
        """Start frequency of first (lower) ODMR transition sweep, in GHz."""
        return self._sweep_freq1_start_ghz

    @sweep_freq1_start_ghz.setter
    def sweep_freq1_start_ghz(self, value: float):
        self._sweep_freq1_start_ghz = float(value)

    @property
    def sweep_freq1_end_ghz(self) -> float:
        """End frequency of first (lower) ODMR transition sweep, in GHz."""
        return self._sweep_freq1_end_ghz

    @sweep_freq1_end_ghz.setter
    def sweep_freq1_end_ghz(self, value: float):
        self._sweep_freq1_end_ghz = float(value)

    @property
    def sweep_freq1_steps(self) -> int:
        """Number of frequency steps in the first sweep."""
        return self._sweep_freq1_steps

    @sweep_freq1_steps.setter
    def sweep_freq1_steps(self, value: int):
        self._sweep_freq1_steps = int(value)

    @property
    def sweep_freq2_start_ghz(self) -> float:
        """Start frequency of second (upper) ODMR transition sweep, in GHz."""
        return self._sweep_freq2_start_ghz

    @sweep_freq2_start_ghz.setter
    def sweep_freq2_start_ghz(self, value: float):
        self._sweep_freq2_start_ghz = float(value)

    @property
    def sweep_freq2_end_ghz(self) -> float:
        """End frequency of second (upper) ODMR transition sweep, in GHz."""
        return self._sweep_freq2_end_ghz

    @sweep_freq2_end_ghz.setter
    def sweep_freq2_end_ghz(self, value: float):
        self._sweep_freq2_end_ghz = float(value)

    @property
    def sweep_freq2_steps(self) -> int:
        """Number of frequency steps in the second sweep."""
        return self._sweep_freq2_steps

    @sweep_freq2_steps.setter
    def sweep_freq2_steps(self, value: int):
        self._sweep_freq2_steps = int(value)

    @property
    def sweep_ref_freq_ghz(self) -> float:
        """Reference frequency used during ODMR sweeps, in GHz."""
        return self._sweep_ref_freq_ghz

    @sweep_ref_freq_ghz.setter
    def sweep_ref_freq_ghz(self, value: float):
        self._sweep_ref_freq_ghz = float(value)

    @property
    def sweep_num_sweeps(self) -> int:
        """Number of sweep repetitions to average."""
        return self._sweep_num_sweeps

    @sweep_num_sweeps.setter
    def sweep_num_sweeps(self, value: int):
        self._sweep_num_sweeps = int(value)

    @property
    def sweep_n_lorentz(self) -> int:
        """Number of Lorentzian peaks to fit in each ODMR spectrum."""
        return self._sweep_n_lorentz

    @sweep_n_lorentz.setter
    def sweep_n_lorentz(self, value: int):
        self._sweep_n_lorentz = int(value)

    @property
    def sweep_is_running(self) -> bool:
        """Whether an ODMR sweep is currently in progress."""
        return self._sweep_is_running

    @sweep_is_running.setter
    def sweep_is_running(self, value: bool):
        self._sweep_is_running = bool(value)
        self.sweep_running_changed.emit(self._sweep_is_running)

    @property
    def sweep_current_sweep(self) -> int:
        """Index of the currently executing sweep repetition."""
        return self._sweep_current_sweep

    @sweep_current_sweep.setter
    def sweep_current_sweep(self, value: int):
        self._sweep_current_sweep = int(value)

    @property
    def sweep_spectrum1(self):
        """Accumulated PL spectrum from the first transition sweep."""
        return self._sweep_spectrum1

    @sweep_spectrum1.setter
    def sweep_spectrum1(self, value):
        self._sweep_spectrum1 = value

    @property
    def sweep_spectrum2(self):
        """Accumulated PL spectrum from the second transition sweep."""
        return self._sweep_spectrum2

    @sweep_spectrum2.setter
    def sweep_spectrum2(self, value):
        self._sweep_spectrum2 = value

    @property
    def sweep_freqlist1(self):
        """Frequency list for the first ODMR sweep."""
        return self._sweep_freqlist1

    @sweep_freqlist1.setter
    def sweep_freqlist1(self, value):
        self._sweep_freqlist1 = value

    @property
    def sweep_freqlist2(self):
        """Frequency list for the second ODMR sweep."""
        return self._sweep_freqlist2

    @sweep_freqlist2.setter
    def sweep_freqlist2(self, value):
        self._sweep_freqlist2 = value

    @property
    def sweep_inflection_result(self):
        """Result dict from identify_multi_transition_inflection_points (or binned)."""
        return self._sweep_inflection_result

    @sweep_inflection_result.setter
    def sweep_inflection_result(self, value):
        self._sweep_inflection_result = value

    # ==================================================================
    # Magnetometry subsystem properties
    # ==================================================================

    @property
    def mag_num_samples(self) -> int:
        """Number of samples to acquire in the magnetometry stability measurement."""
        return self._mag_num_samples

    @mag_num_samples.setter
    def mag_num_samples(self, value: int):
        self._mag_num_samples = int(value)

    @property
    def mag_bin_x(self) -> int:
        """Spatial binning factor along the camera X axis."""
        return self._mag_bin_x

    @mag_bin_x.setter
    def mag_bin_x(self, value: int):
        self._mag_bin_x = int(value)

    @property
    def mag_bin_y(self) -> int:
        """Spatial binning factor along the camera Y axis."""
        return self._mag_bin_y

    @mag_bin_y.setter
    def mag_bin_y(self, value: int):
        self._mag_bin_y = int(value)

    @property
    def mag_selected_indices(self) -> list:
        """
        Indices into the inflection_points array for the multi-point scheme.
        Use 0 to place reference frequency positions.
        """
        return self._mag_selected_indices

    @mag_selected_indices.setter
    def mag_selected_indices(self, value: list):
        self._mag_selected_indices = list(value)

    @property
    def mag_selected_parities(self) -> list:
        """
        Parities corresponding to mag_selected_indices.
        +1 for signal, -1 for inverted signal, 0 for reference.
        """
        return self._mag_selected_parities

    @mag_selected_parities.setter
    def mag_selected_parities(self, value: list):
        self._mag_selected_parities = list(value)

    @property
    def mag_is_running(self) -> bool:
        """Whether a magnetometry acquisition is currently running."""
        return self._mag_is_running

    @mag_is_running.setter
    def mag_is_running(self, value: bool):
        self._mag_is_running = bool(value)
        self.mag_running_changed.emit(self._mag_is_running)

    @property
    def mag_current_sample(self) -> int:
        """Index of the most recently acquired magnetometry sample."""
        return self._mag_current_sample

    @mag_current_sample.setter
    def mag_current_sample(self, value: int):
        self._mag_current_sample = int(value)

    @property
    def mag_stability_result(self):
        """Result dict from the most recent magnetometry stability measurement."""
        return self._mag_stability_result

    @mag_stability_result.setter
    def mag_stability_result(self, value):
        self._mag_stability_result = value

    # ==================================================================
    # Analysis subsystem properties
    # ==================================================================

    @property
    def analysis_denoise_method(self) -> str:
        """Denoising method for field map post-processing."""
        return self._analysis_denoise_method

    @analysis_denoise_method.setter
    def analysis_denoise_method(self, value: str):
        self._analysis_denoise_method = str(value)

    @property
    def analysis_gaussian_sigma(self) -> float:
        """Sigma (pixels) for Gaussian denoising filter."""
        return self._analysis_gaussian_sigma

    @analysis_gaussian_sigma.setter
    def analysis_gaussian_sigma(self, value: float):
        self._analysis_gaussian_sigma = float(value)

    @property
    def analysis_outlier_sigma(self) -> float:
        """Sigma threshold for outlier removal in field maps."""
        return self._analysis_outlier_sigma

    @analysis_outlier_sigma.setter
    def analysis_outlier_sigma(self, value: float):
        self._analysis_outlier_sigma = float(value)

    @property
    def analysis_reference_mode(self) -> str:
        """Reference mode for single-point magnetometry analysis."""
        return self._analysis_reference_mode

    @analysis_reference_mode.setter
    def analysis_reference_mode(self, value: str):
        self._analysis_reference_mode = str(value)

    @property
    def analysis_field_map_result(self):
        """Result dict from the most recent field map analysis."""
        return self._analysis_field_map_result

    @analysis_field_map_result.setter
    def analysis_field_map_result(self, value):
        self._analysis_field_map_result = value

    # ==================================================================
    # Camera mode properties
    # ==================================================================

    @property
    def odmr_camera_mode(self) -> CameraMode:
        """Current operating mode of the widefield camera."""
        return self._odmr_camera_mode

    @odmr_camera_mode.setter
    def odmr_camera_mode(self, value):
        if not isinstance(value, CameraMode):
            value = CameraMode(value)
        self._odmr_camera_mode = value
        self.camera_mode_changed.emit(value.value)   # emit "idle"/"streaming"/"acquiring"

    @property
    def odmr_camera_serial(self) -> str:
        """Serial number of the Basler camera to connect to."""
        return self._odmr_camera_serial

    @odmr_camera_serial.setter
    def odmr_camera_serial(self, value: str):
        self._odmr_camera_serial = str(value)

    # ==================================================================
    # Per-operation camera settings properties
    # ==================================================================

    @property
    def sweep_exposure_time_us(self) -> int:
        """Camera exposure time in microseconds for ODMR sweep acquisition."""
        return self._sweep_exposure_time_us

    @sweep_exposure_time_us.setter
    def sweep_exposure_time_us(self, value: int):
        self._sweep_exposure_time_us = int(value)

    @property
    def sweep_n_frames_per_point(self) -> int:
        """Number of camera frames averaged per frequency point during sweeps."""
        return self._sweep_n_frames_per_point

    @sweep_n_frames_per_point.setter
    def sweep_n_frames_per_point(self, value: int):
        self._sweep_n_frames_per_point = int(value)

    @property
    def sweep_hw_bin_x(self) -> int:
        """Hardware camera binning factor along X (columns) for ODMR sweeps."""
        return self._sweep_hw_bin_x

    @sweep_hw_bin_x.setter
    def sweep_hw_bin_x(self, value: int):
        self._sweep_hw_bin_x = int(value)

    @property
    def sweep_hw_bin_y(self) -> int:
        """Hardware camera binning factor along Y (rows) for ODMR sweeps."""
        return self._sweep_hw_bin_y

    @sweep_hw_bin_y.setter
    def sweep_hw_bin_y(self, value: int):
        self._sweep_hw_bin_y = int(value)

    @property
    def mag_exposure_time_us(self) -> int:
        """Camera exposure time in microseconds for magnetometry acquisition."""
        return self._mag_exposure_time_us

    @mag_exposure_time_us.setter
    def mag_exposure_time_us(self, value: int):
        self._mag_exposure_time_us = int(value)

    @property
    def mag_n_frames_per_point(self) -> int:
        """Number of camera frames averaged per point during magnetometry."""
        return self._mag_n_frames_per_point

    @mag_n_frames_per_point.setter
    def mag_n_frames_per_point(self, value: int):
        self._mag_n_frames_per_point = int(value)

    @property
    def mag_hw_bin_x(self) -> int:
        """Hardware camera binning factor along X (columns) for magnetometry."""
        return self._mag_hw_bin_x

    @mag_hw_bin_x.setter
    def mag_hw_bin_x(self, value: int):
        self._mag_hw_bin_x = int(value)

    @property
    def mag_hw_bin_y(self) -> int:
        """Hardware camera binning factor along Y (rows) for magnetometry."""
        return self._mag_hw_bin_y

    @mag_hw_bin_y.setter
    def mag_hw_bin_y(self, value: int):
        self._mag_hw_bin_y = int(value)

    # ==================================================================
    # Save settings properties
    # ==================================================================

    @property
    def save_base_path(self) -> str:
        """Base directory path for saving experimental data."""
        return self._save_base_path

    @save_base_path.setter
    def save_base_path(self, value: str):
        self._save_base_path = str(value)

    @property
    def save_subfolder(self) -> str:
        """Subfolder within save_base_path for organizing saved files."""
        return self._save_subfolder

    @save_subfolder.setter
    def save_subfolder(self, value: str):
        self._save_subfolder = str(value)

    @property
    def save_timestamp_enabled(self) -> bool:
        """Whether to append a timestamp to saved filenames."""
        return self._save_timestamp_enabled

    @save_timestamp_enabled.setter
    def save_timestamp_enabled(self, value: bool):
        self._save_timestamp_enabled = bool(value)

    @property
    def save_prefix_sweep(self) -> str:
        """Optional filename prefix for ODMR sweep saves."""
        return self._save_prefix_sweep

    @save_prefix_sweep.setter
    def save_prefix_sweep(self, value: str):
        self._save_prefix_sweep = str(value)

    @property
    def save_prefix_magnetometry(self) -> str:
        """Optional filename prefix for magnetometry stability saves."""
        return self._save_prefix_magnetometry

    @save_prefix_magnetometry.setter
    def save_prefix_magnetometry(self, value: str):
        self._save_prefix_magnetometry = str(value)

    @property
    def save_prefix_field_map(self) -> str:
        """Optional filename prefix for field map saves."""
        return self._save_prefix_field_map

    @save_prefix_field_map.setter
    def save_prefix_field_map(self, value: str):
        self._save_prefix_field_map = str(value)

    @property
    def save_prefix_sensitivity(self) -> str:
        """Optional filename prefix for sensitivity analysis saves."""
        return self._save_prefix_sensitivity

    @save_prefix_sensitivity.setter
    def save_prefix_sensitivity(self, value: str):
        self._save_prefix_sensitivity = str(value)

    # ==================================================================
    # Performance settings properties
    # ==================================================================

    @property
    def perf_rf_poll_interval_s(self) -> float:
        """Interval (s) at which the RF status is polled by the worker."""
        return self._perf_rf_poll_interval_s

    @perf_rf_poll_interval_s.setter
    def perf_rf_poll_interval_s(self, value: float):
        self._perf_rf_poll_interval_s = float(value)

    @property
    def perf_ui_plot_throttle_fps(self) -> float:
        """Maximum UI plot refresh rate in frames per second."""
        return self._perf_ui_plot_throttle_fps

    @perf_ui_plot_throttle_fps.setter
    def perf_ui_plot_throttle_fps(self, value: float):
        self._perf_ui_plot_throttle_fps = float(value)

    @property
    def perf_mw_settling_time_s(self) -> float:
        """Time (s) to wait after setting microwave frequency before acquiring."""
        return self._perf_mw_settling_time_s

    @perf_mw_settling_time_s.setter
    def perf_mw_settling_time_s(self, value: float):
        self._perf_mw_settling_time_s = float(value)

    @property
    def perf_n_frames_per_point(self) -> int:
        """Number of camera frames to average per frequency point."""
        return self._perf_n_frames_per_point

    @perf_n_frames_per_point.setter
    def perf_n_frames_per_point(self, value: int):
        self._perf_n_frames_per_point = int(value)

    @property
    def perf_worker_loop_sleep_s(self) -> float:
        """Sleep interval (s) in worker thread main loops to avoid busy-waiting."""
        return self._perf_worker_loop_sleep_s

    @perf_worker_loop_sleep_s.setter
    def perf_worker_loop_sleep_s(self, value: float):
        self._perf_worker_loop_sleep_s = float(value)

    @property
    def perf_sweep_emit_every_n(self) -> int:
        """Emit sweep_spectrum_updated signal every N frequency points."""
        return self._perf_sweep_emit_every_n

    @perf_sweep_emit_every_n.setter
    def perf_sweep_emit_every_n(self, value: int):
        self._perf_sweep_emit_every_n = int(value)

    @property
    def perf_live_avg_update_interval_samples(self) -> int:
        """Number of magnetometry samples between live-average plot updates."""
        return self._perf_live_avg_update_interval_samples

    @perf_live_avg_update_interval_samples.setter
    def perf_live_avg_update_interval_samples(self, value: int):
        self._perf_live_avg_update_interval_samples = int(value)

    @property
    def perf_autosave_interval_samples(self) -> int:
        """Autosave the stability cube every N magnetometry samples."""
        return self._perf_autosave_interval_samples

    @perf_autosave_interval_samples.setter
    def perf_autosave_interval_samples(self, value: int):
        self._perf_autosave_interval_samples = int(value)

    @property
    def perf_camera_exposure_time_us(self) -> int:
        """Camera exposure time in microseconds used during ODMR sweeps."""
        return self._perf_camera_exposure_time_us

    @perf_camera_exposure_time_us.setter
    def perf_camera_exposure_time_us(self, value: int):
        self._perf_camera_exposure_time_us = int(value)

    # ==================================================================
    # Business logic methods
    # ==================================================================

    def try_start_sweep(self) -> bool:
        """
        Return True if starting a sweep is allowed, False otherwise.

        A sweep cannot be started while a magnetometry acquisition is running.
        """
        return not self._mag_is_running

    def try_start_magnetometry(self) -> bool:
        """
        Return True if starting a magnetometry acquisition is allowed.

        Magnetometry cannot be started while a sweep is running.
        """
        return not self._sweep_is_running

    def build_save_filename(
        self,
        component_name: str,
        user_prefix: str = "",
        timestamp_str: str = None,
    ) -> str:
        """
        Build a filename stem for saving data.

        Pattern: ``{user_prefix}_{component_name}_{timestamp}``

        The user_prefix and timestamp are optional.  If
        ``save_timestamp_enabled`` is False the timestamp is omitted
        regardless of the ``timestamp_str`` argument.

        Parameters
        ----------
        component_name : str
            Descriptive name of the data component (e.g. "odmr_freq_sweep").
        user_prefix : str, optional
            Short label prepended by the user (e.g. "run1").  Empty string
            means no prefix.
        timestamp_str : str, optional
            Timestamp string in "YYYYMMDD_HHMMSS" format.  If None and
            timestamps are enabled, the current time is used.  Pass an
            explicit value to make results deterministic in tests.

        Returns
        -------
        str
            Filename stem without extension.
        """
        if timestamp_str is None and self._save_timestamp_enabled:
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

        parts = [p for p in [user_prefix, component_name] if p]
        if timestamp_str and self._save_timestamp_enabled:
            parts.append(timestamp_str)

        return "_".join(parts)

    def build_metadata(self) -> dict:
        """
        Assemble a metadata dict suitable for embedding in .npz save files.

        The dict contains all key experimental parameters at the time of the
        call so that saved data files are self-documenting.  If a
        ``shared_state`` with a ``laser_power_mw`` attribute is present its
        value is also included.

        Returns
        -------
        dict
            Flat key/value mapping of experimental metadata.
        """
        meta = {
            "sg384_address": self._rf_address,
            "sg384_amplitude_dbm": self._rf_amplitude_dbm,
            "odmr_camera_serial": self._odmr_camera_serial,
            "sweep_freq1_start_ghz": self._sweep_freq1_start_ghz,
            "sweep_freq1_end_ghz": self._sweep_freq1_end_ghz,
            "sweep_freq1_steps": self._sweep_freq1_steps,
            "sweep_freq2_start_ghz": self._sweep_freq2_start_ghz,
            "sweep_freq2_end_ghz": self._sweep_freq2_end_ghz,
            "sweep_freq2_steps": self._sweep_freq2_steps,
            "sweep_ref_freq_ghz": self._sweep_ref_freq_ghz,
            "sweep_num_sweeps": self._sweep_num_sweeps,
            "mag_num_samples": self._mag_num_samples,
            "mag_bin_x": self._mag_bin_x,
            "mag_bin_y": self._mag_bin_y,
            "mag_selected_indices": list(self._mag_selected_indices),
            "mag_selected_parities": list(self._mag_selected_parities),
            "perf_mw_settling_time_s": self._perf_mw_settling_time_s,
            "perf_n_frames_per_point": self._perf_n_frames_per_point,
        }

        if self._sweep_inflection_result:
            r = self._sweep_inflection_result
            meta["inflection_points_ghz"] = r.get("inflection_points", [])
            meta["inflection_slopes_ghz_inv"] = r.get("inflection_slopes", [])
            meta["inflection_contrasts"] = r.get("inflection_contrasts", [])

        if self.shared_state is not None:
            try:
                meta["laser_power_mw_at_capture"] = self.shared_state.laser_power_mw
            except AttributeError:
                pass

        return meta

    # ==================================================================
    # Config persistence
    # ==================================================================

    def get_config(self) -> dict:
        """
        Return a flat dict of all persistable configuration values.

        The returned dict can be serialised to JSON and later restored via
        :meth:`load_config`.

        Returns
        -------
        dict
            Mapping of property name → current value for every key in
            ``_CONFIG_KEYS``.
        """
        config = {}
        for key in self._CONFIG_KEYS:
            config[key] = getattr(self, key)
        return config

    def load_config(self, config: dict):
        """
        Restore configuration from a dict previously obtained via :meth:`get_config`.

        Unknown keys are silently ignored.  Any property setter that raises
        an exception (e.g. due to a type mismatch with an old config file) is
        also silently skipped.

        Parameters
        ----------
        config : dict
            Mapping of property name → value.
        """
        for key, value in config.items():
            if key in self._CONFIG_KEYS:
                try:
                    setattr(self, key, value)
                except Exception:
                    pass
