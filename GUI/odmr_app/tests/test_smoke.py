"""
Smoke tests — verify that all key classes import and instantiate without crashing.

These tests catch the class of bugs that are immediately visible when the app
is launched but that unit tests miss: import errors, missing methods called in
__init__, wrong signal emission types, etc.  They require no hardware and run
in < 2 seconds.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def test_odmr_state_instantiates():
    """ODMRAppState must construct without raising."""
    from state.odmr_state import ODMRAppState, CameraMode
    state = ODMRAppState()
    # Basic sanity on key attributes
    assert state.sg384_controller is None
    assert state.sg384_lock is not None
    assert state.sweep_is_running is False
    assert state.mag_is_running is False
    assert state.odmr_camera_mode == CameraMode.IDLE


def test_camera_mode_signal_carries_string():
    """camera_mode_changed must emit the string value of the enum, not the enum itself.

    Previously a bug caused CameraMode enum to be emitted directly, which
    caused ValueError when the receiver called CameraMode(value) on it.
    """
    from state.odmr_state import ODMRAppState, CameraMode
    state = ODMRAppState()
    received = []
    state.camera_mode_changed.connect(lambda v: received.append(v))
    state.odmr_camera_mode = CameraMode.STREAMING
    assert received == ["streaming"], (
        "camera_mode_changed must emit the string 'streaming', not the enum"
    )


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

def test_sweep_worker_instantiates():
    """ODMRSweepWorker must construct without raising."""
    from state.odmr_state import ODMRAppState
    from workers.odmr_sweep_worker import ODMRSweepWorker
    state = ODMRAppState()
    state.sg384_controller = MagicMock()
    worker = ODMRSweepWorker(state, simulation_mode=True)
    assert worker is not None
    assert not worker.isRunning()


def test_magnetometry_worker_instantiates():
    """MagnetometryWorker must construct without raising."""
    from state.odmr_state import ODMRAppState
    from workers.magnetometry_worker import MagnetometryWorker
    state = ODMRAppState()
    state.sg384_controller = MagicMock()
    state.sweep_inflection_result = {
        'inflection_points': [2.87] * 8,
        'inflection_slopes': [50.0] * 8,
        'inflection_contrasts': [0.97] * 8,
    }
    worker = MagnetometryWorker(state, simulation_mode=True)
    assert worker is not None
    assert not worker.isRunning()


def test_sg384_worker_instantiates():
    """SG384Worker must construct without raising."""
    from state.odmr_state import ODMRAppState
    from workers.sg384_worker import SG384Worker
    state = ODMRAppState()
    worker = SG384Worker(state)
    assert worker is not None
    assert not worker.isRunning()


# ---------------------------------------------------------------------------
# Tab handlers (instantiate with a bare QWidget placeholder)
# ---------------------------------------------------------------------------

def test_settings_tab_handler_instantiates():
    """SettingsTabHandler must wire up without raising."""
    from PySide6.QtWidgets import QWidget
    from state.odmr_state import ODMRAppState
    from tabs.settings_tab import SettingsTabHandler
    state = ODMRAppState()
    placeholder = QWidget()
    handler = SettingsTabHandler(placeholder, state)
    assert handler is not None
    # Flush frames widget must be hidden (it's vestigial)
    assert not handler.ui_settings.perf_flush_frames_spin.isVisible()


def test_sweep_tab_handler_instantiates():
    """SweepTabHandler must wire up without raising."""
    from PySide6.QtWidgets import QWidget
    from state.odmr_state import ODMRAppState
    from tabs.sweep_tab import SweepTabHandler
    state = ODMRAppState()
    placeholder = QWidget()
    handler = SweepTabHandler(
        placeholder, state,
        stop_streaming_fn=lambda: True,
        set_camera_mode_fn=lambda m: None,
    )
    assert handler is not None


def test_magnetometry_tab_handler_instantiates():
    """MagnetometryTabHandler must wire up without raising."""
    from PySide6.QtWidgets import QWidget
    from state.odmr_state import ODMRAppState
    from tabs.magnetometry_tab import MagnetometryTabHandler
    state = ODMRAppState()
    placeholder = QWidget()
    handler = MagnetometryTabHandler(
        placeholder, state,
        stop_streaming_fn=lambda: True,
        set_camera_mode_fn=lambda m: None,
    )
    assert handler is not None


# ---------------------------------------------------------------------------
# ODMRMainWindow (full app startup smoke test)
# ---------------------------------------------------------------------------

def test_odmr_main_window_instantiates():
    """ODMRMainWindow must open in simulation mode without raising.

    This is the most comprehensive smoke test — it exercises all __init__
    code paths: UI setup, tab handler construction, config load, sys.path
    management for the embedded camera tab, etc.
    """
    from state.odmr_state import ODMRAppState
    from odmr_main_window import ODMRMainWindow
    state = ODMRAppState()
    state._simulation_mode = True
    win = ODMRMainWindow(odmr_state=state)
    # Window constructed; all tab handlers created
    assert win._sweep_handler is not None
    assert win._mag_handler is not None
    assert win._settings_handler is not None
    assert win._analysis_handler is not None
    assert win._sensitivity_handler is not None
    win.close()
