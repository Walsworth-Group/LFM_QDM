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


def test_init_handles_includes_bin_x_bin_y():
    """_init_handles must pass bin_x and bin_y in the camera config dict.

    Previously these were missing, causing a KeyError: 'bin_x' from
    initialize_system when starting a hardware magnetometry run.
    """
    from unittest.mock import patch, MagicMock
    state = make_state()
    state.mag_bin_x = 2
    state.mag_bin_y = 4

    captured = {}

    def fake_init(simulation_mode, settings, logger=None):
        captured.update(settings)
        return {}

    worker = MagnetometryWorker(state, simulation_mode=False)
    with patch("qdm_gen.initialize_system", side_effect=fake_init):
        try:
            worker._init_handles()
        except Exception:
            pass  # may fail after init_system returns {} — that's fine

    cam_cfg = captured.get("camera", {})
    assert "bin_x" in cam_cfg, "camera config missing bin_x"
    assert "bin_y" in cam_cfg, "camera config missing bin_y"
    assert cam_cfg["bin_x"] == 2
    assert cam_cfg["bin_y"] == 4
