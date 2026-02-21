"""Tests for MagnetometryWorker."""
import sys
import time
import numpy as np
import pytest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

from state.odmr_state import ODMRAppState
from workers.magnetometry_worker import MagnetometryWorker


def make_state():
    state = ODMRAppState()
    state.mag_num_samples = 5
    state.mag_bin_x = 1
    state.mag_bin_y = 1
    state.perf_live_avg_update_interval_samples = 2
    state.mag_selected_indices = [1, 4, 0, 5, 8, 0]
    state.mag_selected_parities = [1, 1, 0, -1, -1, 0]
    state.sg384_controller = MagicMock()
    # Minimal inflection result
    state.sweep_inflection_result = {
        "inflection_points": np.linspace(2.51, 2.53, 8),
        "inflection_slopes": np.array([-15]*4 + [15]*4, dtype=float),
        "inflection_contrasts": np.ones(8) * 0.988,
    }
    return state


def test_mag_emits_progress():
    state = make_state()
    progress = []
    completed = []

    worker = MagnetometryWorker(state, simulation_mode=True)
    worker.mag_progress.connect(lambda c, t: progress.append((c, t)))
    worker.mag_completed.connect(lambda d: completed.append(d))
    worker.start()
    worker.wait(10000)

    assert len(progress) == state.mag_num_samples
    assert len(completed) == 1
    assert progress[-1] == (state.mag_num_samples, state.mag_num_samples)


def test_mag_emits_live_preview():
    state = make_state()
    previews = []

    worker = MagnetometryWorker(state, simulation_mode=True)
    worker.mag_sample_acquired.connect(lambda n, arr: previews.append(n))
    worker.start()
    worker.wait(10000)

    # With 5 samples and interval=2, expect at least 2 previews
    assert len(previews) >= 2


def test_mag_result_has_stability_cube():
    state = make_state()
    completed = []

    worker = MagnetometryWorker(state, simulation_mode=True)
    worker.mag_completed.connect(lambda d: completed.append(d))
    worker.start()
    worker.wait(10000)

    result = completed[0]
    assert "stability_cube" in result
    cube = result["stability_cube"]
    assert cube.shape[0] == state.mag_num_samples


def test_mag_stop_saves_partial():
    """Stopping mid-run should still emit mag_completed with partial data."""
    state = make_state()
    state.mag_num_samples = 20
    completed = []

    worker = MagnetometryWorker(state, simulation_mode=True)
    worker.mag_completed.connect(lambda d: completed.append(d))
    worker.start()
    time.sleep(0.3)  # let a few samples accumulate
    worker.stop()
    worker.wait(5000)

    assert len(completed) == 1
    assert completed[0]["stability_cube"].shape[0] > 0  # at least 1 sample


def test_mag_result_contains_metadata():
    state = make_state()
    completed = []

    worker = MagnetometryWorker(state, simulation_mode=True)
    worker.mag_completed.connect(lambda d: completed.append(d))
    worker.start()
    worker.wait(10000)

    meta = completed[0].get("metadata", {})
    assert "mag_num_samples" in meta
    assert "mag_selected_indices" in meta


def test_init_handles_applies_hw_binning():
    """_init_handles must apply state.mag_hw_bin_x/y as hardware camera binning.

    Previously the wrong state attributes (software binning mag_bin_x/y) were
    used; now _init_handles reads mag_hw_bin_x/y and calls
    BinningHorizontal.SetValue / BinningVertical.SetValue directly on the camera.
    """
    from unittest.mock import patch, MagicMock, call
    state = make_state()
    state.mag_hw_bin_x = 2
    state.mag_hw_bin_y = 4

    # Build a mock camera chain: basler.connect_and_open → camera_instance._camera
    mock_raw_cam = MagicMock()
    mock_raw_cam.BinningHorizontal = MagicMock()
    mock_raw_cam.BinningVertical = MagicMock()
    mock_raw_cam.BinningHorizontalMode = MagicMock()
    mock_raw_cam.BinningVerticalMode = MagicMock()

    mock_cam_instance = MagicMock()
    mock_cam_instance._camera = mock_raw_cam
    # grab_frames returns a 2D array so ny/nx can be read
    mock_cam_instance.grab_frames.return_value = np.zeros((300, 480))

    worker = MagnetometryWorker(state, simulation_mode=False)
    with patch("qdm_basler.basler.connect_and_open", return_value=mock_cam_instance):
        handles = worker._init_handles()

    mock_raw_cam.BinningHorizontal.SetValue.assert_called_once_with(2)
    mock_raw_cam.BinningVertical.SetValue.assert_called_once_with(4)
    assert handles['ny'] == 300
    assert handles['nx'] == 480
