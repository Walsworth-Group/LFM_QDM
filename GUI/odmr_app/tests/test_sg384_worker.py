"""Tests for SG384Worker using mocked hardware."""
import sys
import time
import threading
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication
app = QApplication.instance() or QApplication(sys.argv)

from state.odmr_state import ODMRAppState
from workers.sg384_worker import SG384Worker


def make_mock_controller():
    ctrl = MagicMock()
    ctrl.get_frequency.return_value = 2.87  # GHz
    return ctrl


def test_worker_emits_connected_signal():
    state = ODMRAppState()
    mock_ctrl = make_mock_controller()
    state.sg384_controller = mock_ctrl

    received = []
    worker = SG384Worker(state)
    worker.connected.connect(lambda d: received.append(d))
    worker.start()
    time.sleep(0.2)
    worker.stop()
    worker.wait(2000)

    assert len(received) == 1
    assert "address" in received[0]


def test_worker_polls_frequency():
    state = ODMRAppState()
    state.perf_rf_poll_interval_s = 0.05  # fast for testing
    mock_ctrl = make_mock_controller()
    state.sg384_controller = mock_ctrl

    received_freqs = []
    worker = SG384Worker(state)
    worker.frequency_polled.connect(lambda f: received_freqs.append(f))
    worker.start()
    time.sleep(0.3)
    worker.stop()
    worker.wait(2000)

    assert len(received_freqs) >= 2
    assert all(abs(f - 2.87) < 1e-9 for f in received_freqs)


def test_worker_backs_off_when_lock_held():
    """Polling must not call get_frequency while sg384_lock is held."""
    state = ODMRAppState()
    state.perf_rf_poll_interval_s = 0.02
    mock_ctrl = make_mock_controller()
    state.sg384_controller = mock_ctrl

    worker = SG384Worker(state)
    worker.start()
    time.sleep(0.05)  # let it poll a few times
    call_count_before = mock_ctrl.get_frequency.call_count

    # Hold the lock for 200ms
    with state.sg384_lock:
        time.sleep(0.2)

    call_count_during = mock_ctrl.get_frequency.call_count - call_count_before
    worker.stop()
    worker.wait(2000)

    assert call_count_during == 0  # no calls while lock held


def test_queue_command_set_frequency():
    state = ODMRAppState()
    mock_ctrl = make_mock_controller()
    state.sg384_controller = mock_ctrl

    success_events = []
    worker = SG384Worker(state)
    worker.parameter_set_success.connect(lambda p, v: success_events.append((p, v)))
    worker.start()
    time.sleep(0.1)
    worker.queue_command('set_frequency', 2.87)
    time.sleep(0.2)
    worker.stop()
    worker.wait(2000)

    mock_ctrl.set_frequency.assert_called_with(2.87, 'GHz')
    assert any(e[0] == 'set_frequency' for e in success_events)
