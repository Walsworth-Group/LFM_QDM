"""Tests for ODMRSweepWorker using simulation mode."""
import sys
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

from state.odmr_state import ODMRAppState
from workers.odmr_sweep_worker import ODMRSweepWorker


def make_state_for_sweep():
    state = ODMRAppState()
    state.sweep_freq1_start_ghz = 2.855
    state.sweep_freq1_end_ghz = 2.885
    state.sweep_freq1_steps = 11          # small for speed
    state.sweep_freq2_start_ghz = 3.208
    state.sweep_freq2_end_ghz = 3.238
    state.sweep_freq2_steps = 11
    state.sweep_ref_freq_ghz = 1.0
    state.sweep_num_sweeps = 1
    state.sweep_n_lorentz = 2
    state.sg384_controller = MagicMock()
    return state


def test_sweep_emits_progress():
    state = make_state_for_sweep()
    progress_events = []
    completed_events = []

    worker = ODMRSweepWorker(state, simulation_mode=True)
    worker.sweep_progress.connect(lambda c, t: progress_events.append((c, t)))
    worker.sweep_completed.connect(lambda d: completed_events.append(d))
    worker.start()
    worker.wait(15000)  # max 15s

    assert len(progress_events) >= 1
    assert len(completed_events) == 1


def test_sweep_completed_has_inflection_points():
    state = make_state_for_sweep()
    completed = []

    worker = ODMRSweepWorker(state, simulation_mode=True)
    worker.sweep_completed.connect(lambda d: completed.append(d))
    worker.start()
    worker.wait(15000)

    result = completed[0]
    assert "inflection_points" in result
    assert len(result["inflection_points"]) == 8


def test_sweep_acquires_lock():
    """Sweep worker must hold sg384_lock for its duration."""
    state = make_state_for_sweep()
    lock_was_held = []

    worker = ODMRSweepWorker(state, simulation_mode=True)
    worker.start()
    time.sleep(0.1)
    lock_was_held.append(state.sg384_lock.locked())
    worker.wait(15000)
    assert any(lock_was_held)


def test_sweep_sets_running_state():
    state = make_state_for_sweep()
    running_events = []
    state.sweep_running_changed.connect(lambda v: running_events.append(v))

    worker = ODMRSweepWorker(state, simulation_mode=True)
    worker.start()
    worker.wait(15000)

    assert True in running_events   # started
    assert False in running_events  # finished
    assert running_events[-1] is False
