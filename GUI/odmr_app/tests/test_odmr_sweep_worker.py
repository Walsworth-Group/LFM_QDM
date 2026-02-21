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


def test_sweep_progress_emitted_per_step():
    """Progress must be emitted once per frequency step, not once per sweep pass.

    With 11 steps per transition and num_sweeps=1, we expect exactly 22 progress
    events — one for every call to _measure_step in both transitions.
    Fewer events would mean the stop button is coarser-grained than per-step.
    """
    state = make_state_for_sweep()  # 11 + 11 steps, 1 sweep
    progress_events = []

    worker = ODMRSweepWorker(state, simulation_mode=True)
    worker.sweep_progress.connect(lambda c, t: progress_events.append((c, t)))
    worker.start()
    worker.wait(15000)

    expected = state.sweep_freq1_steps + state.sweep_freq2_steps
    assert len(progress_events) == expected, (
        f"Expected {expected} progress events (one per step), "
        f"got {len(progress_events)}"
    )
    # Values must be strictly increasing
    counts = [c for c, _ in progress_events]
    assert counts == list(range(1, expected + 1))


def test_sweep_stop_during_t1_prevents_t2():
    """Stopping during Transition 1 must prevent Transition 2 from running.

    Uses 30 steps per transition (0.005 s each → 150 ms total per transition).
    Stop is requested after 0.06 s, which lands mid-T1 (~12 steps in).
    The result must have been acquired but sweeps2_done must be 0 — confirmed
    by checking that the number of progress events is well below n_steps1+n_steps2.
    """
    state = ODMRAppState()
    state.sweep_freq1_start_ghz = 2.855
    state.sweep_freq1_end_ghz = 2.885
    state.sweep_freq1_steps = 30   # 30 * 5 ms = 150 ms for T1
    state.sweep_freq2_start_ghz = 3.208
    state.sweep_freq2_end_ghz = 3.238
    state.sweep_freq2_steps = 30
    state.sweep_ref_freq_ghz = 1.0
    state.sweep_num_sweeps = 1
    state.sweep_n_lorentz = 2
    state.sg384_controller = MagicMock()

    progress_events = []
    completed_events = []

    worker = ODMRSweepWorker(state, simulation_mode=True)
    worker.sweep_progress.connect(lambda c, t: progress_events.append((c, t)))
    worker.sweep_completed.connect(lambda d: completed_events.append(d))
    worker.start()

    time.sleep(0.06)   # stop mid-T1 (~12 steps done, T1 not yet complete)
    worker.stop()
    worker.wait(10000)

    assert len(completed_events) == 1          # always emits even on early stop
    n_done = len(progress_events)
    assert n_done < state.sweep_freq1_steps, (
        f"Expected to stop before T1 finished ({state.sweep_freq1_steps} steps), "
        f"but got {n_done} progress events"
    )


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
