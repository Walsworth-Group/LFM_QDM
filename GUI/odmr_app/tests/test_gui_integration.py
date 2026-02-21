"""
pytest-qt GUI integration tests.

These tests click real buttons and wait for real signals, catching bugs that
unit tests and smoke tests miss: wrong button wiring, missing state transitions,
slots that crash on first invocation, etc.

Requirements: pytest-qt   (pip install pytest-qt)

Run with:
    pytest tests/test_gui_integration.py -v
"""
import sys
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

from state.odmr_state import ODMRAppState, CameraMode
from odmr_main_window import ODMRMainWindow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_sim_window():
    """Return an ODMRMainWindow with simulation mode enabled."""
    state = ODMRAppState()
    state._simulation_mode = True
    # Small freq grid so the sweep finishes fast in tests
    state.sweep_freq1_steps = 5
    state.sweep_freq2_steps = 5
    state.sweep_num_sweeps = 1
    win = ODMRMainWindow(odmr_state=state)
    return win


# ---------------------------------------------------------------------------
# Window lifecycle
# ---------------------------------------------------------------------------

def test_main_window_is_visible(qtbot):
    """ODMRMainWindow shows itself without crashing."""
    win = make_sim_window()
    qtbot.addWidget(win)
    win.show()
    assert win.isVisible()
    win.close()


def test_close_while_idle(qtbot):
    """Closing the window while no workers are running must not raise."""
    win = make_sim_window()
    qtbot.addWidget(win)
    win.show()
    win.close()


# ---------------------------------------------------------------------------
# Sweep tab: Start / Stop
# ---------------------------------------------------------------------------

def test_start_sweep_button_sets_running(qtbot):
    """Clicking Start Sweep must emit sweep_running_changed(True)."""
    win = make_sim_window()
    qtbot.addWidget(win)
    win.show()

    handler = win._sweep_handler
    received = []
    win.state.sweep_running_changed.connect(received.append)

    # Click start — worker starts asynchronously
    handler.ui.sweep_start_btn.click()

    # Wait up to 2 s for the running=True signal
    deadline = time.monotonic() + 2.0
    while not received and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)

    assert True in received, "sweep_running_changed(True) was never emitted"
    win.close()


def test_stop_sweep_terminates_worker(qtbot):
    """Clicking Stop Sweep must cause sweep_running_changed(False) after True."""
    win = make_sim_window()
    qtbot.addWidget(win)
    win.show()

    handler = win._sweep_handler
    received = []
    win.state.sweep_running_changed.connect(received.append)

    handler.ui.sweep_start_btn.click()

    # Wait until running
    deadline = time.monotonic() + 2.0
    while True not in received and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)

    assert True in received, "Worker never started"

    # Now stop
    handler.ui.sweep_stop_btn.click()

    deadline = time.monotonic() + 5.0
    while received[-1] is not False and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.05)

    assert received[-1] is False, "sweep_running_changed(False) was never emitted after stop"
    win.close()


def test_sweep_completes_in_simulation(qtbot):
    """A full sweep in simulation mode must emit sweep_completed without error."""
    win = make_sim_window()
    qtbot.addWidget(win)
    win.show()

    completed = []
    failed = []

    handler = win._sweep_handler
    # Connect directly to the worker signals via the handler (worker created on click)
    # We intercept via state: sweep_running_changed(False) after True = finished

    running_events = []
    win.state.sweep_running_changed.connect(running_events.append)

    handler.ui.sweep_start_btn.click()

    # Wait for the sweep to finish (running=True then running=False)
    deadline = time.monotonic() + 30.0
    while not (True in running_events and running_events and running_events[-1] is False):
        if time.monotonic() > deadline:
            break
        app.processEvents()
        time.sleep(0.05)

    assert True in running_events, "Sweep never started"
    assert running_events[-1] is False, "Sweep never finished within 30 s"

    # Inflection table should now be populated
    table = handler.ui.sweep_inflection_table
    assert table.rowCount() > 0, "Inflection table empty after completed sweep"
    win.close()


# ---------------------------------------------------------------------------
# Camera mode transitions
# ---------------------------------------------------------------------------

def test_sweep_sets_acquiring_mode(qtbot):
    """Starting a sweep must set odmr_camera_mode to ACQUIRING."""
    win = make_sim_window()
    qtbot.addWidget(win)
    win.show()

    mode_events = []
    win.state.camera_mode_changed.connect(mode_events.append)

    handler = win._sweep_handler
    handler.ui.sweep_start_btn.click()

    deadline = time.monotonic() + 2.0
    while CameraMode.ACQUIRING.value not in mode_events and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)

    assert CameraMode.ACQUIRING.value in mode_events, (
        f"Camera mode never went to ACQUIRING; got: {mode_events}"
    )
    win.close()


def test_sweep_restores_idle_mode(qtbot):
    """After a sweep completes, odmr_camera_mode must return to IDLE."""
    win = make_sim_window()
    qtbot.addWidget(win)
    win.show()

    mode_events = []
    win.state.camera_mode_changed.connect(mode_events.append)
    running_events = []
    win.state.sweep_running_changed.connect(running_events.append)

    handler = win._sweep_handler
    handler.ui.sweep_start_btn.click()

    deadline = time.monotonic() + 30.0
    while not (True in running_events and running_events and running_events[-1] is False):
        if time.monotonic() > deadline:
            break
        app.processEvents()
        time.sleep(0.05)

    assert CameraMode.IDLE.value in mode_events, (
        f"Camera mode never returned to IDLE after sweep; got: {mode_events}"
    )
    win.close()
