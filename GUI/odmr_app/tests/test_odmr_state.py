"""
Tests for ODMRAppState.

Run from project root:
    python -m pytest GUI/odmr_app/tests/test_odmr_state.py -v
"""

import sys
import threading
from pathlib import Path

# Ensure QApplication exists before importing any Qt objects
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

# Path setup: project root and odmr_app root
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))  # project root
sys.path.insert(0, str(Path(__file__).parent.parent))                # odmr_app root

from state.odmr_state import ODMRAppState, CameraMode  # noqa: E402


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_camera_mode_enum():
    """CameraMode enum values must match the documented string literals."""
    assert CameraMode.IDLE == "idle"
    assert CameraMode.STREAMING == "streaming"
    assert CameraMode.ACQUIRING == "acquiring"


def test_state_default_values():
    """Verify key default values on a freshly constructed ODMRAppState."""
    state = ODMRAppState()

    assert state.mag_bin_x == 1
    assert state.mag_bin_y == 1
    assert state.perf_rf_poll_interval_s == 0.5
    assert state.perf_mw_settling_time_s == 0.010
    assert state.perf_n_frames_per_point == 5
    assert state.perf_worker_loop_sleep_s == 0.005
    assert state.sg384_controller is None
    assert isinstance(state.sg384_lock, type(threading.Lock()))


def test_sweep_running_signal_emitted():
    """sweep_running_changed signal must fire when sweep_is_running is toggled."""
    state = ODMRAppState()
    received = []
    state.sweep_running_changed.connect(lambda v: received.append(v))

    state.sweep_is_running = True
    state.sweep_is_running = False

    assert received == [True, False]


def test_camera_mode_signal_emitted():
    """camera_mode_changed signal must fire when odmr_camera_mode is set."""
    state = ODMRAppState()
    received = []
    state.camera_mode_changed.connect(lambda v: received.append(v))

    state.odmr_camera_mode = CameraMode.STREAMING

    assert len(received) == 1
    assert received[0] == CameraMode.STREAMING.value   # "streaming"


def test_rf_frequency_signal_emitted():
    """rf_frequency_changed signal must fire with the new frequency value."""
    state = ODMRAppState()
    received = []
    state.rf_frequency_changed.connect(lambda v: received.append(v))

    state.rf_current_freq_ghz = 2.87

    assert len(received) == 1
    assert received[0] == 2.87


def test_get_config_roundtrip():
    """get_config / load_config must preserve values across two state instances."""
    state1 = ODMRAppState()
    state1.sweep_freq1_start_ghz = 2.520
    state1.mag_num_samples = 500
    state1.analysis_gaussian_sigma = 20.0
    state1.save_subfolder = "test_run"

    config = state1.get_config()

    state2 = ODMRAppState()
    state2.load_config(config)

    assert state2.sweep_freq1_start_ghz == 2.520
    assert state2.mag_num_samples == 500
    assert state2.analysis_gaussian_sigma == 20.0
    assert state2.save_subfolder == "test_run"


def test_mag_is_running_blocks_sweep():
    """try_start_sweep() must return False when mag_is_running is True."""
    state = ODMRAppState()
    state.mag_is_running = True
    result = state.try_start_sweep()
    assert result is False


def test_build_save_filename():
    """build_save_filename must construct the expected filename stem."""
    state = ODMRAppState()
    state.save_timestamp_enabled = True

    fixed_ts = "20260220_143022"

    # With user prefix
    name_with_prefix = state.build_save_filename(
        component_name="odmr_freq_sweep",
        user_prefix="run1",
        timestamp_str=fixed_ts,
    )
    assert name_with_prefix == "run1_odmr_freq_sweep_20260220_143022"

    # Without user prefix
    name_no_prefix = state.build_save_filename(
        component_name="odmr_freq_sweep",
        user_prefix="",
        timestamp_str=fixed_ts,
    )
    assert name_no_prefix == "odmr_freq_sweep_20260220_143022"
