# ODMR App — Phase 1: Foundation & Workers

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create the directory skeleton, ODMRAppState, and all three hardware workers.

**Architecture:** Separate-worker-per-role pattern. ODMRAppState is the single source of truth (QObject + signals). SG384Worker handles idle polling; ODMRSweepWorker and MagnetometryWorker acquire `sg384_lock` and call `sg384_controller` directly for zero-overhead hardware access.

**Tech Stack:** PySide6, threading.Lock, threading.Event, existing `qdm_srs.SG384Controller`, existing `qdm_gen` functions, Python 3.x

**Design doc:** `docs/plans/2026-02-20-odmr-app-design.md` — read this first.

**Prerequisites:** Phases 2–4 depend on this phase being complete.

---

## Task 1: Create Directory Structure

**Files to create:**
- `GUI/odmr_app/` (directory)
- `GUI/odmr_app/state/__init__.py`
- `GUI/odmr_app/workers/__init__.py`
- `GUI/odmr_app/widgets/__init__.py`
- `GUI/odmr_app/ui/` (directory, files added in Phase 3)
- `GUI/odmr_app/config/presets/` (directory)
- `GUI/odmr_app/docs/` (directory)
- `GUI/odmr_app/tests/__init__.py`

**Step 1: Create directories**
```bash
cd "GUI"
mkdir -p odmr_app/state odmr_app/workers odmr_app/widgets odmr_app/ui
mkdir -p odmr_app/config/presets odmr_app/docs odmr_app/tests
```

**Step 2: Create `__init__.py` files**
```bash
touch odmr_app/__init__.py
touch odmr_app/state/__init__.py
touch odmr_app/workers/__init__.py
touch odmr_app/widgets/__init__.py
touch odmr_app/tests/__init__.py
```

**Step 3: Create default preset**

Create `GUI/odmr_app/config/presets/default_4pt.json`:
```json
{
  "name": "default_4pt",
  "description": "Outer four inflection points, alternating parity (standard 4-point scheme)",
  "selected_indices": [1, 4, 0, 5, 8, 0],
  "selected_parities": [1, 1, 0, -1, -1, 0],
  "ref_freq_ghz": 1.0
}
```

**Step 4: Verify structure**
```bash
find odmr_app -type f | sort
```
Expected output: 5 `__init__.py` files + `config/presets/default_4pt.json`

**Step 5: Commit**
```bash
git add GUI/odmr_app/
git commit -m "feat(odmr-app): create directory skeleton and default preset"
```

---

## Task 2: Create ODMRAppState

**Files:**
- Create: `GUI/odmr_app/state/odmr_state.py`
- Create: `GUI/odmr_app/tests/test_odmr_state.py`

**Step 1: Write failing tests**

Create `GUI/odmr_app/tests/test_odmr_state.py`:
```python
"""Tests for ODMRAppState."""
import sys
import threading
import pytest
from pathlib import Path

# Allow running tests from project root
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

from state.odmr_state import ODMRAppState, CameraMode


def test_camera_mode_enum():
    assert CameraMode.IDLE == "idle"
    assert CameraMode.STREAMING == "streaming"
    assert CameraMode.ACQUIRING == "acquiring"


def test_state_default_values():
    state = ODMRAppState()
    assert state.odmr_camera_mode == CameraMode.IDLE
    assert state.mag_bin_x == 1
    assert state.mag_bin_y == 1
    assert state.perf_rf_poll_interval_s == 0.5
    assert state.perf_mw_settling_time_s == 0.010
    assert state.perf_n_frames_per_point == 5
    assert state.perf_worker_loop_sleep_s == 0.005
    assert state.perf_sweep_emit_every_n == 1
    assert state.perf_live_avg_update_interval_samples == 10
    assert state.perf_autosave_interval_samples == 50
    assert state.sg384_controller is None
    assert isinstance(state.sg384_lock, type(threading.Lock()))


def test_sweep_running_signal_emitted():
    state = ODMRAppState()
    received = []
    state.sweep_running_changed.connect(lambda v: received.append(v))
    state.sweep_is_running = True
    assert received == [True]
    state.sweep_is_running = False
    assert received == [True, False]


def test_camera_mode_signal_emitted():
    state = ODMRAppState()
    received = []
    state.camera_mode_changed.connect(lambda v: received.append(v))
    state.odmr_camera_mode = CameraMode.STREAMING
    assert received == [CameraMode.STREAMING]


def test_rf_frequency_signal_emitted():
    state = ODMRAppState()
    received = []
    state.rf_frequency_changed.connect(lambda v: received.append(v))
    state.rf_current_freq_ghz = 2.87
    assert abs(received[0] - 2.87) < 1e-9


def test_get_config_roundtrip():
    state = ODMRAppState()
    state.perf_rf_poll_interval_s = 1.0
    state.sweep_freq1_start_ghz = 2.516
    state.save_base_path = "E:\\test"
    config = state.get_config()
    assert config["perf_rf_poll_interval_s"] == 1.0
    assert config["sweep_freq1_start_ghz"] == 2.516
    assert config["save_base_path"] == "E:\\test"

    state2 = ODMRAppState()
    state2.load_config(config)
    assert state2.perf_rf_poll_interval_s == 1.0
    assert state2.sweep_freq1_start_ghz == 2.516


def test_mag_is_running_blocks_sweep():
    """When mag is running, sweep_is_running should not be settable."""
    state = ODMRAppState()
    state.mag_is_running = True
    # Attempt to start sweep while magnetometry running
    result = state.try_start_sweep()
    assert result is False  # blocked


def test_build_save_filename():
    state = ODMRAppState()
    state.save_timestamp_enabled = True
    name = state.build_save_filename("odmr_freq_sweep", user_prefix="run1",
                                     timestamp_str="20260220_143022")
    assert name == "run1_odmr_freq_sweep_20260220_143022"

    name_no_prefix = state.build_save_filename("odmr_freq_sweep", user_prefix="",
                                               timestamp_str="20260220_143022")
    assert name_no_prefix == "odmr_freq_sweep_20260220_143022"
```

**Step 2: Run tests to verify they fail**
```bash
cd GUI/odmr_app
python -m pytest tests/test_odmr_state.py -v 2>&1 | head -30
```
Expected: ImportError (odmr_state module not found)

**Step 3: Implement `GUI/odmr_app/state/odmr_state.py`**

```python
"""
ODMRAppState — Central state for the ODMR magnetometry app.

Single source of truth. All tabs and workers read/write via this object.
Properties emit Qt signals on change. Never access hardware directly.
"""

import threading
from datetime import datetime
from enum import Enum
from typing import Optional
import numpy as np
from PySide6.QtCore import QObject, Signal


class CameraMode(str, Enum):
    """Mutual exclusion state for the ODMR camera."""
    IDLE       = "idle"
    STREAMING  = "streaming"   # Camera tab live stream active
    ACQUIRING  = "acquiring"   # Sweep or magnetometry worker owns camera


class ODMRAppState(QObject):
    """
    Central state object for the ODMR GUI application.

    All properties emit a corresponding signal when changed.
    Workers and UI tabs connect to these signals rather than polling.

    Subsystem prefixes:
        rf_*        MW generator (SRS SG384)
        sweep_*     ODMR frequency sweep parameters and results
        mag_*       Multi-point magnetometry parameters and results
        analysis_*  Post-acquisition analysis parameters and results
        save_*      File saving configuration
        perf_*      Performance and timing parameters
    """

    # --- RF signals ---
    rf_connection_changed = Signal(bool)
    rf_frequency_changed = Signal(float)        # GHz

    # --- Sweep signals ---
    sweep_running_changed = Signal(bool)
    sweep_progress = Signal(int, int)           # (current_sweep, total_sweeps)
    sweep_spectrum_updated = Signal(
        object, object, object, object, int)    # (fl1, sp1, fl2, sp2, sweep_num)
    sweep_completed = Signal(dict)

    # --- Magnetometry signals ---
    mag_running_changed = Signal(bool)
    mag_progress = Signal(int, int)             # (current_sample, total_samples)
    mag_sample_acquired = Signal(int, object)   # (sample_idx, cumulative_avg_gauss ndarray)
    mag_completed = Signal(dict)

    # --- Analysis signals ---
    analysis_completed = Signal(dict)

    # --- Camera mode ---
    camera_mode_changed = Signal(str)

    def __init__(self, shared_state=None, parent=None):
        super().__init__(parent)

        # Reference to shared ExperimentState (laser/PID), may be None
        self.shared_state = shared_state

        # Shared hardware — set when RF connected, lock-protected
        self._sg384_controller = None
        self.sg384_lock = threading.Lock()

        # CameraState — set externally after construction
        self.camera_state = None

        # --- RF ---
        self._rf_is_connected = False
        self._rf_current_freq_ghz = 0.0
        self._rf_amplitude_dbm = -10.0
        self._rf_address = "192.168.1.100"

        # --- Sweep ---
        self._sweep_freq1_start_ghz = 2.516
        self._sweep_freq1_end_ghz = 2.528
        self._sweep_freq1_steps = 201
        self._sweep_freq2_start_ghz = 3.210
        self._sweep_freq2_end_ghz = 3.220
        self._sweep_freq2_steps = 201
        self._sweep_ref_freq_ghz = 1.0
        self._sweep_num_sweeps = 1
        self._sweep_n_lorentz = 2
        self._sweep_is_running = False
        self._sweep_current_sweep = 0
        self._sweep_spectrum1 = None
        self._sweep_spectrum2 = None
        self._sweep_freqlist1 = None
        self._sweep_freqlist2 = None
        self._sweep_inflection_result = None

        # --- Magnetometry ---
        self._mag_num_samples = 200
        self._mag_bin_x = 1
        self._mag_bin_y = 1
        self._mag_selected_indices = [1, 4, 0, 5, 8, 0]
        self._mag_selected_parities = [1, 1, 0, -1, -1, 0]
        self._mag_is_running = False
        self._mag_current_sample = 0
        self._mag_stability_result = None

        # --- Analysis ---
        self._analysis_denoise_method = "gaussian"
        self._analysis_gaussian_sigma = 15.0
        self._analysis_outlier_sigma = 4.0
        self._analysis_reference_mode = "global_mean"
        self._analysis_field_map_result = None

        # --- Camera mode ---
        self._odmr_camera_mode = CameraMode.IDLE
        self._odmr_camera_serial = ""

        # --- Save ---
        self._save_base_path = ""
        self._save_subfolder = ""
        self._save_timestamp_enabled = True
        self._save_prefix_sweep = ""
        self._save_prefix_magnetometry = ""
        self._save_prefix_field_map = ""
        self._save_prefix_sensitivity = ""

        # --- Performance / timing ---
        self._perf_rf_poll_interval_s = 0.5
        self._perf_ui_plot_throttle_fps = 10.0
        self._perf_mw_settling_time_s = 0.010
        self._perf_camera_flush_frames = 1
        self._perf_n_frames_per_point = 5
        self._perf_worker_loop_sleep_s = 0.005
        self._perf_sweep_emit_every_n = 1
        self._perf_live_avg_update_interval_samples = 10
        self._perf_autosave_interval_samples = 50

    # ------------------------------------------------------------------
    # Property helpers — DRY macro for emit-on-set
    # ------------------------------------------------------------------
    def _make_prop(attr, signal_name=None):
        """Generate a property that emits signal_name on set."""
        def getter(self):
            return getattr(self, attr)
        def setter(self, value):
            setattr(self, attr, value)
            if signal_name:
                getattr(self, signal_name).emit(value)
        return property(getter, setter)

    # RF properties
    rf_is_connected      = _make_prop('_rf_is_connected', 'rf_connection_changed')
    rf_current_freq_ghz  = _make_prop('_rf_current_freq_ghz', 'rf_frequency_changed')
    rf_amplitude_dbm     = _make_prop('_rf_amplitude_dbm')
    rf_address           = _make_prop('_rf_address')

    # Sweep properties
    sweep_freq1_start_ghz  = _make_prop('_sweep_freq1_start_ghz')
    sweep_freq1_end_ghz    = _make_prop('_sweep_freq1_end_ghz')
    sweep_freq1_steps      = _make_prop('_sweep_freq1_steps')
    sweep_freq2_start_ghz  = _make_prop('_sweep_freq2_start_ghz')
    sweep_freq2_end_ghz    = _make_prop('_sweep_freq2_end_ghz')
    sweep_freq2_steps      = _make_prop('_sweep_freq2_steps')
    sweep_ref_freq_ghz     = _make_prop('_sweep_ref_freq_ghz')
    sweep_num_sweeps       = _make_prop('_sweep_num_sweeps')
    sweep_n_lorentz        = _make_prop('_sweep_n_lorentz')
    sweep_is_running       = _make_prop('_sweep_is_running', 'sweep_running_changed')
    sweep_current_sweep    = _make_prop('_sweep_current_sweep')
    sweep_spectrum1        = _make_prop('_sweep_spectrum1')
    sweep_spectrum2        = _make_prop('_sweep_spectrum2')
    sweep_freqlist1        = _make_prop('_sweep_freqlist1')
    sweep_freqlist2        = _make_prop('_sweep_freqlist2')
    sweep_inflection_result = _make_prop('_sweep_inflection_result')

    # Magnetometry properties
    mag_num_samples        = _make_prop('_mag_num_samples')
    mag_bin_x              = _make_prop('_mag_bin_x')
    mag_bin_y              = _make_prop('_mag_bin_y')
    mag_selected_indices   = _make_prop('_mag_selected_indices')
    mag_selected_parities  = _make_prop('_mag_selected_parities')
    mag_is_running         = _make_prop('_mag_is_running', 'mag_running_changed')
    mag_current_sample     = _make_prop('_mag_current_sample')
    mag_stability_result   = _make_prop('_mag_stability_result')

    # Analysis properties
    analysis_denoise_method   = _make_prop('_analysis_denoise_method')
    analysis_gaussian_sigma   = _make_prop('_analysis_gaussian_sigma')
    analysis_outlier_sigma    = _make_prop('_analysis_outlier_sigma')
    analysis_reference_mode   = _make_prop('_analysis_reference_mode')
    analysis_field_map_result = _make_prop('_analysis_field_map_result')

    # Camera mode
    odmr_camera_serial = _make_prop('_odmr_camera_serial')

    @property
    def odmr_camera_mode(self):
        return self._odmr_camera_mode

    @odmr_camera_mode.setter
    def odmr_camera_mode(self, value):
        self._odmr_camera_mode = CameraMode(value)
        self.camera_mode_changed.emit(str(value))

    # Shared hardware
    @property
    def sg384_controller(self):
        return self._sg384_controller

    @sg384_controller.setter
    def sg384_controller(self, value):
        self._sg384_controller = value

    # Save properties
    save_base_path          = _make_prop('_save_base_path')
    save_subfolder          = _make_prop('_save_subfolder')
    save_timestamp_enabled  = _make_prop('_save_timestamp_enabled')
    save_prefix_sweep       = _make_prop('_save_prefix_sweep')
    save_prefix_magnetometry = _make_prop('_save_prefix_magnetometry')
    save_prefix_field_map   = _make_prop('_save_prefix_field_map')
    save_prefix_sensitivity = _make_prop('_save_prefix_sensitivity')

    # Performance properties
    perf_rf_poll_interval_s              = _make_prop('_perf_rf_poll_interval_s')
    perf_ui_plot_throttle_fps            = _make_prop('_perf_ui_plot_throttle_fps')
    perf_mw_settling_time_s              = _make_prop('_perf_mw_settling_time_s')
    perf_camera_flush_frames             = _make_prop('_perf_camera_flush_frames')
    perf_n_frames_per_point              = _make_prop('_perf_n_frames_per_point')
    perf_worker_loop_sleep_s             = _make_prop('_perf_worker_loop_sleep_s')
    perf_sweep_emit_every_n              = _make_prop('_perf_sweep_emit_every_n')
    perf_live_avg_update_interval_samples = _make_prop('_perf_live_avg_update_interval_samples')
    perf_autosave_interval_samples       = _make_prop('_perf_autosave_interval_samples')

    # ------------------------------------------------------------------
    # Business logic helpers
    # ------------------------------------------------------------------

    def try_start_sweep(self) -> bool:
        """Return False if sweep cannot start (e.g. magnetometry running)."""
        if self._mag_is_running:
            return False
        return True

    def try_start_magnetometry(self) -> bool:
        """Return False if measurement cannot start (e.g. sweep running)."""
        if self._sweep_is_running:
            return False
        return True

    def build_save_filename(self, component_name: str, user_prefix: str = "",
                            timestamp_str: str = None) -> str:
        """
        Build filename stem (no extension) following project convention:
            {user_prefix}_{component_name}_{timestamp}
        user_prefix is optional. timestamp_str injected for testability.
        """
        if timestamp_str is None:
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        parts = [p for p in [user_prefix, component_name] if p]
        if self._save_timestamp_enabled:
            parts.append(timestamp_str)
        return "_".join(parts)

    def build_metadata(self) -> dict:
        """
        Assemble full metadata dict for .npz saves.
        Call just before saving to capture current state.
        """
        meta = {
            # Instrument
            "sg384_address": self._rf_address,
            "sg384_amplitude_dbm": self._rf_amplitude_dbm,
            "odmr_camera_serial": self._odmr_camera_serial,
            # Sweep parameters
            "sweep_freq1_start_ghz": self._sweep_freq1_start_ghz,
            "sweep_freq1_end_ghz": self._sweep_freq1_end_ghz,
            "sweep_freq1_steps": self._sweep_freq1_steps,
            "sweep_freq2_start_ghz": self._sweep_freq2_start_ghz,
            "sweep_freq2_end_ghz": self._sweep_freq2_end_ghz,
            "sweep_freq2_steps": self._sweep_freq2_steps,
            "sweep_ref_freq_ghz": self._sweep_ref_freq_ghz,
            "sweep_num_sweeps": self._sweep_num_sweeps,
            # Magnetometry
            "mag_num_samples": self._mag_num_samples,
            "mag_bin_x": self._mag_bin_x,
            "mag_bin_y": self._mag_bin_y,
            "mag_selected_indices": list(self._mag_selected_indices),
            "mag_selected_parities": list(self._mag_selected_parities),
            # Performance
            "perf_mw_settling_time_s": self._perf_mw_settling_time_s,
            "perf_n_frames_per_point": self._perf_n_frames_per_point,
            "perf_camera_flush_frames": self._perf_camera_flush_frames,
        }
        # Include inflection results if available
        if self._sweep_inflection_result:
            r = self._sweep_inflection_result
            meta["inflection_points_ghz"] = r.get("inflection_points", [])
            meta["inflection_slopes_ghz_inv"] = r.get("inflection_slopes", [])
            meta["inflection_contrasts"] = r.get("inflection_contrasts", [])
        # Include laser power if shared state connected
        if self.shared_state is not None:
            try:
                meta["laser_power_mw_at_capture"] = self.shared_state.laser_power_mw
            except AttributeError:
                pass
        return meta

    # ------------------------------------------------------------------
    # Config persistence
    # ------------------------------------------------------------------

    # Keys to persist (add new perf_* here when introduced)
    _CONFIG_KEYS = [
        "rf_address", "rf_amplitude_dbm", "odmr_camera_serial",
        "sweep_freq1_start_ghz", "sweep_freq1_end_ghz", "sweep_freq1_steps",
        "sweep_freq2_start_ghz", "sweep_freq2_end_ghz", "sweep_freq2_steps",
        "sweep_ref_freq_ghz", "sweep_num_sweeps", "sweep_n_lorentz",
        "mag_num_samples", "mag_bin_x", "mag_bin_y",
        "mag_selected_indices", "mag_selected_parities",
        "analysis_denoise_method", "analysis_gaussian_sigma",
        "analysis_outlier_sigma", "analysis_reference_mode",
        "save_base_path", "save_subfolder", "save_timestamp_enabled",
        "save_prefix_sweep", "save_prefix_magnetometry",
        "save_prefix_field_map", "save_prefix_sensitivity",
        "perf_rf_poll_interval_s", "perf_ui_plot_throttle_fps",
        "perf_mw_settling_time_s", "perf_camera_flush_frames",
        "perf_n_frames_per_point", "perf_worker_loop_sleep_s",
        "perf_sweep_emit_every_n", "perf_live_avg_update_interval_samples",
        "perf_autosave_interval_samples",
    ]

    def get_config(self) -> dict:
        """Return all persistable state as a plain dict."""
        config = {}
        for key in self._CONFIG_KEYS:
            config[key] = getattr(self, key)
        return config

    def load_config(self, config: dict):
        """Restore state from a config dict. Unknown keys are ignored."""
        for key, value in config.items():
            if key in self._CONFIG_KEYS:
                try:
                    setattr(self, key, value)
                except Exception:
                    pass  # Skip keys whose setter has extra validation
```

**Step 4: Run tests**
```bash
cd GUI/odmr_app
python -m pytest tests/test_odmr_state.py -v
```
Expected: All tests pass. If `_make_prop` causes metaclass issues with PySide6, replace with explicit `@property` definitions for each attribute (same pattern, just verbose).

**Step 5: Commit**
```bash
git add GUI/odmr_app/state/odmr_state.py GUI/odmr_app/tests/test_odmr_state.py
git commit -m "feat(odmr-app): add ODMRAppState with signals and config persistence"
```

---

## Task 3: Create SG384Worker

**Files:**
- Create: `GUI/odmr_app/workers/sg384_worker.py`
- Create: `GUI/odmr_app/tests/test_sg384_worker.py`

**Context:** `SG384Controller` lives in `qdm_srs.py` at the project root. Key methods:
- `open_connection()` — opens PyVISA connection
- `close_connection()`
- `set_frequency(frequency, unit='MHz')` — note: unit param, use `'GHz'`
- `set_amplitude(level)` — dBm

SG384Worker handles idle polling only. During sweep/measurement, workers acquire
`state.sg384_lock` and call `state.sg384_controller` directly — SG384Worker's polling
loop backs off automatically because it cannot acquire the lock.

**Step 1: Write failing test**

Create `GUI/odmr_app/tests/test_sg384_worker.py`:
```python
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
```

**Step 2: Run tests to verify failure**
```bash
python -m pytest tests/test_sg384_worker.py -v 2>&1 | head -20
```
Expected: ImportError for `sg384_worker`

**Step 3: Implement `GUI/odmr_app/workers/sg384_worker.py`**

```python
"""
SG384Worker — Background thread for SRS SG384 MW generator.

Handles:
- Idle frequency polling (backs off when sg384_lock is held by sweep/mag workers)
- Manual frequency/amplitude commands from the UI command queue

During ODMR sweeps and magnetometry, the sweep/magnetometry workers hold
state.sg384_lock and call state.sg384_controller directly for zero latency.
"""

import sys
import time
from pathlib import Path
from PySide6.QtCore import QThread, Signal

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


class SG384Worker(QThread):
    """
    Worker thread for SRS SG384 signal generator idle monitoring and manual control.

    Does NOT own the VISA connection — that is managed externally and stored
    in state.sg384_controller. This worker only polls and accepts commands.
    """

    connected = Signal(dict)                      # {'address': str, 'freq_ghz': float}
    connection_failed = Signal(str)
    frequency_polled = Signal(float)              # GHz — for internal use + RF panel
    parameter_set_success = Signal(str, object)   # ('set_frequency', 2.87)
    parameter_set_failed = Signal(str, str)       # ('set_frequency', error_msg)
    error = Signal(str)

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self._is_running = False
        self._command_queue = []

    def run(self):
        """Main worker loop. Polls frequency and processes commands."""
        self._is_running = True

        # Announce connected (controller already open)
        try:
            ctrl = self.state.sg384_controller
            if ctrl is None:
                self.connection_failed.emit("sg384_controller not set in state")
                return
            initial_freq = self._safe_get_frequency()
            self.connected.emit({
                "address": self.state.rf_address,
                "freq_ghz": initial_freq or 0.0,
            })
        except Exception as e:
            self.connection_failed.emit(str(e))
            return

        last_poll = 0.0

        while self._is_running:
            # Process any queued commands first (acquire lock)
            if self._command_queue:
                cmd, args = self._command_queue.pop(0)
                self._execute_command(cmd, args)

            # Poll frequency on interval — skip if lock unavailable
            now = time.monotonic()
            if now - last_poll >= self.state.perf_rf_poll_interval_s:
                freq = self._safe_get_frequency()
                if freq is not None:
                    self.frequency_polled.emit(freq)
                last_poll = now

            time.sleep(self.state.perf_worker_loop_sleep_s)

    def stop(self):
        """Signal the worker loop to exit cleanly."""
        self._is_running = False

    def queue_command(self, command: str, *args):
        """Thread-safe: enqueue a command for execution in worker thread."""
        self._command_queue.append((command, args))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _safe_get_frequency(self):
        """Poll frequency only if lock is immediately available."""
        acquired = self.state.sg384_lock.acquire(blocking=False)
        if not acquired:
            return None  # sweep/mag worker holds the lock — skip this poll
        try:
            return self.state.sg384_controller.get_frequency()  # GHz assumed
        except Exception as e:
            self.error.emit(f"Frequency poll error: {e}")
            return None
        finally:
            self.state.sg384_lock.release()

    def _execute_command(self, command: str, args: tuple):
        """Execute a hardware command, acquiring the lock."""
        try:
            with self.state.sg384_lock:
                ctrl = self.state.sg384_controller
                if command == 'set_frequency':
                    freq_ghz = args[0]
                    ctrl.set_frequency(freq_ghz, 'GHz')
                    self.parameter_set_success.emit('set_frequency', freq_ghz)
                elif command == 'set_amplitude':
                    dbm = args[0]
                    ctrl.set_amplitude(dbm)
                    self.parameter_set_success.emit('set_amplitude', dbm)
                else:
                    self.error.emit(f"Unknown command: {command}")
        except Exception as e:
            self.parameter_set_failed.emit(command, str(e))
```

**Step 4: Run tests**
```bash
python -m pytest tests/test_sg384_worker.py -v
```
Expected: All pass. `test_worker_backs_off_when_lock_held` is the critical one.

**Step 5: Commit**
```bash
git add GUI/odmr_app/workers/sg384_worker.py GUI/odmr_app/tests/test_sg384_worker.py
git commit -m "feat(odmr-app): add SG384Worker with lock-aware polling"
```

---

## Task 4: Create ODMRSweepWorker

**Files:**
- Create: `GUI/odmr_app/workers/odmr_sweep_worker.py`
- Create: `GUI/odmr_app/tests/test_odmr_sweep_worker.py`

**Context:** Uses `simulation_mode=True` for tests (no hardware needed).
Key qdm_gen functions called directly:
- `run_hardware_sweep(freqlist, ref_freq, settings, handles, odmr_data_cube, pbar, sweep_num, live_plot_ctx)`
- `fit_global_odmr(odmr_data_cube, freqlist, n_lorentz)`
- `identify_multi_transition_inflection_points(...)` — or call its internals

The worker acquires `state.sg384_lock` for the entire sweep duration.

**Step 1: Write failing test**

Create `GUI/odmr_app/tests/test_odmr_sweep_worker.py`:
```python
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
    state.sweep_freq2_start_ghz = 2.855
    state.sweep_freq2_end_ghz = 2.885
    state.sweep_freq2_steps = 11
    state.sweep_ref_freq_ghz = 1.0
    state.sweep_num_sweeps = 1
    state.sweep_n_lorentz = 2
    state.sg384_controller = MagicMock()
    return state


def test_sweep_emits_progress(tmp_path):
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


def test_sweep_completed_has_inflection_points(tmp_path):
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

    original_run = ODMRSweepWorker.run
    def patched_run(self):
        lock_was_held.append(state.sg384_lock.locked())
        original_run(self)
    # Just verify lock is acquired at start
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
```

**Step 2: Run to verify failure**
```bash
python -m pytest tests/test_odmr_sweep_worker.py -v 2>&1 | head -20
```

**Step 3: Implement `GUI/odmr_app/workers/odmr_sweep_worker.py`**

```python
"""
ODMRSweepWorker — Runs two-transition ODMR frequency sweep.

Acquires state.sg384_lock for the entire sweep (pauses SG384Worker polling).
Calls qdm_gen functions directly — same speed as notebook.
Emits per-sweep spectrum updates and final inflection point result.
"""

import sys
import time
import numpy as np
from pathlib import Path
from PySide6.QtCore import QThread, Signal

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import qdm_gen as qdm


class ODMRSweepWorker(QThread):
    """
    Worker for two-transition CW ODMR frequency sweep.

    Runs identify_multi_transition_inflection_points equivalent internally,
    emitting per-sweep progress and a final result dict with all 8 inflection
    points, slopes, and baseline contrasts.
    """

    sweep_progress = Signal(int, int)          # (current_sweep, total_sweeps)
    spectrum_updated = Signal(                 # per-sweep live update
        object, object, object, object, int)   # (fl1,sp1,fl2,sp2,sweep_num)
    sweep_completed = Signal(dict)
    sweep_failed = Signal(str)

    def __init__(self, state, simulation_mode: bool = False, parent=None):
        super().__init__(parent)
        self.state = state
        self.simulation_mode = simulation_mode
        self._is_running = False
        self._stop_requested = False

    def run(self):
        self._is_running = True
        self._stop_requested = False
        self.state.sweep_is_running = True

        try:
            result = self._run_sweep()
            if not self._stop_requested:
                self.state.sweep_inflection_result = result
                self.sweep_completed.emit(result)
        except Exception as e:
            self.sweep_failed.emit(str(e))
        finally:
            self.state.sweep_is_running = False
            self._is_running = False

    def stop(self):
        """Request stop after current frequency point completes."""
        self._stop_requested = True
        self._is_running = False

    def _run_sweep(self) -> dict:
        """Run both transitions and return full inflection result."""
        s = self.state

        # Build settings dict matching qdm_gen expectations
        settings = self._build_settings()

        # Initialize camera handle (or simulation)
        handles = self._init_handles(settings)

        try:
            with s.sg384_lock:
                result = self._sweep_with_lock(settings, handles)
        finally:
            self._close_handles(handles)

        return result

    def _sweep_with_lock(self, settings, handles) -> dict:
        """Run sweeps while holding sg384_lock. Called inside `with sg384_lock`."""
        s = self.state
        num_sweeps = s.sweep_num_sweeps

        # Allocate data cubes for both transitions
        fl1 = qdm.gen_freqs(s.sweep_freq1_start_ghz, s.sweep_freq1_end_ghz,
                            s.sweep_freq1_steps)
        fl2 = qdm.gen_freqs(s.sweep_freq2_start_ghz, s.sweep_freq2_end_ghz,
                            s.sweep_freq2_steps)

        ny, nx = settings.get('ny', 1), settings.get('nx', 1)
        cube1 = np.zeros((len(fl1), ny, nx), dtype=np.float32)
        cube2 = np.zeros((len(fl2), ny, nx), dtype=np.float32)

        for sweep_num in range(1, num_sweeps + 1):
            if self._stop_requested:
                break

            self.sweep_progress.emit(sweep_num, num_sweeps)

            # Run one sweep per transition
            qdm.run_hardware_sweep(
                fl1, s.sweep_ref_freq_ghz, settings, handles,
                cube1, None, sweep_num, None)
            qdm.run_hardware_sweep(
                fl2, s.sweep_ref_freq_ghz, settings, handles,
                cube2, None, sweep_num, None)

            # Emit live spectrum every perf_sweep_emit_every_n sweeps
            if sweep_num % s.perf_sweep_emit_every_n == 0:
                sp1 = cube1.mean(axis=(1, 2)) / sweep_num
                sp2 = cube2.mean(axis=(1, 2)) / sweep_num
                self.spectrum_updated.emit(fl1, sp1, fl2, sp2, sweep_num)

                # Also update RF display with last used frequency
                # (done inside run_hardware_sweep via measure_odmr_point)

        # Fit both transitions
        cube1_avg = cube1 / max(num_sweeps, 1)
        cube2_avg = cube2 / max(num_sweeps, 1)

        fit1 = qdm.fit_global_odmr(cube1_avg, fl1, n_lorentz=s.sweep_n_lorentz)
        fit2 = qdm.fit_global_odmr(cube2_avg, fl2, n_lorentz=s.sweep_n_lorentz)

        # Extract inflection points from both transitions (4 peaks each)
        inflection_points, inflection_slopes, inflection_contrasts = \
            self._extract_all_inflection_points(fit1, fit2)

        return {
            "inflection_points": inflection_points,
            "inflection_slopes": inflection_slopes,
            "inflection_contrasts": inflection_contrasts,
            "freqlist1": fl1, "spectrum1": cube1_avg,
            "freqlist2": fl2, "spectrum2": cube2_avg,
            "peak_params1": fit1.get("peak_params", []),
            "peak_params2": fit2.get("peak_params", []),
        }

    def _extract_all_inflection_points(self, fit1: dict, fit2: dict):
        """
        Combine inflection points from both transitions into 8-element arrays.
        Ordering: for each transition, left-then-right for each peak.
        """
        pts, slopes, contrasts = [], [], []
        for fit in (fit1, fit2):
            for peak in fit.get("peak_params", []):
                f_low, f_high = peak["inflection_pts"]
                c_low, c_high = peak["inflection_contrasts"]
                slope_mag = peak["max_slope"]
                pts   += [f_low,  f_high]
                slopes += [-slope_mag, +slope_mag]  # negative left, positive right
                contrasts += [c_low, c_high]
        return (np.array(pts[:8]), np.array(slopes[:8]), np.array(contrasts[:8]))

    def _build_settings(self) -> dict:
        """Build settings dict compatible with qdm_gen hardware functions."""
        s = self.state
        return {
            "settling_time": s.perf_mw_settling_time_s,
            "n_frames": s.perf_n_frames_per_point,
            "camera_flush_frames": s.perf_camera_flush_frames,
            "simulation_mode": self.simulation_mode,
        }

    def _init_handles(self, settings) -> dict:
        """Initialize camera (and optionally SG384) handles."""
        if self.simulation_mode:
            return {"camera_instance": None, "sg384": None,
                    "ny": 10, "nx": 10}
        return qdm.initialize_system(self.simulation_mode, settings, logger=None)

    def _close_handles(self, handles):
        if not self.simulation_mode and handles.get("camera_instance"):
            try:
                handles["camera_instance"].close()
            except Exception:
                pass
```

**Step 4: Run tests**
```bash
python -m pytest tests/test_odmr_sweep_worker.py -v
```
Expected: All pass. The simulation_mode path exercises the signal flow.

**Step 5: Commit**
```bash
git add GUI/odmr_app/workers/odmr_sweep_worker.py \
        GUI/odmr_app/tests/test_odmr_sweep_worker.py
git commit -m "feat(odmr-app): add ODMRSweepWorker with lock acquisition and per-sweep emission"
```

---

## Task 5: Create MagnetometryWorker

**Files:**
- Create: `GUI/odmr_app/workers/magnetometry_worker.py`
- Create: `GUI/odmr_app/tests/test_magnetometry_worker.py`

**Step 1: Write failing test**

Create `GUI/odmr_app/tests/test_magnetometry_worker.py`:
```python
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

    # With 5 samples and interval=2, expect ~2 previews
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
```

**Step 2: Run to verify failure**
```bash
python -m pytest tests/test_magnetometry_worker.py -v 2>&1 | head -20
```

**Step 3: Implement `GUI/odmr_app/workers/magnetometry_worker.py`**

```python
"""
MagnetometryWorker — Runs multi-point inflection magnetometry measurement loop.

Acquires state.sg384_lock for full measurement duration.
Calls qdm_gen.measure_multi_point() each iteration.
Emits live cumulative average every perf_live_avg_update_interval_samples.
Autosaves partial data every perf_autosave_interval_samples.
On stop(): completes current sample, emits mag_completed with partial data.
"""

import sys
import time
import numpy as np
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import QThread, Signal

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import qdm_gen as qdm


class MagnetometryWorker(QThread):
    """
    Worker for multi-point inflection point magnetometry.

    Holds sg384_lock for duration, calls measure_multi_point directly.
    """

    mag_progress = Signal(int, int)              # (current_sample, total_samples)
    mag_sample_acquired = Signal(int, object)    # (sample_idx, cumulative_avg_gauss ndarray)
    mag_completed = Signal(dict)
    mag_failed = Signal(str)

    def __init__(self, state, simulation_mode: bool = False, parent=None):
        super().__init__(parent)
        self.state = state
        self.simulation_mode = simulation_mode
        self._is_running = False
        self._stop_requested = False

    def run(self):
        self._is_running = True
        self._stop_requested = False
        self.state.mag_is_running = True

        try:
            result = self._run_measurement()
            self.mag_completed.emit(result)
        except Exception as e:
            self.mag_failed.emit(str(e))
        finally:
            self.state.mag_is_running = False
            self._is_running = False

    def stop(self):
        """Request stop. Current sample finishes before exit."""
        self._stop_requested = True
        self._is_running = False

    def _run_measurement(self) -> dict:
        s = self.state
        num_samples = s.mag_num_samples

        # Format frequency list from current inflection result + selected indices
        freq_list, slope_list, parity_list, baseline_list = \
            self._get_freq_config()

        # Determine output shape (use simulation or real camera)
        ny, nx = self._get_image_shape()

        # Allocate stability cube and running sum
        stability_cube = np.zeros((num_samples, ny, nx), dtype=np.float32)
        running_sum = np.zeros((ny, nx), dtype=np.float64)
        samples_done = 0

        handles = self._init_handles()
        try:
            with s.sg384_lock:
                for i in range(num_samples):
                    if self._stop_requested:
                        break

                    # Acquire one sample
                    frame = self._acquire_sample(
                        handles, freq_list, slope_list, parity_list, baseline_list)
                    stability_cube[i] = frame
                    running_sum += frame
                    samples_done = i + 1

                    s.mag_current_sample = samples_done
                    self.mag_progress.emit(samples_done, num_samples)

                    # Live cumulative average
                    interval = s.perf_live_avg_update_interval_samples
                    if samples_done % interval == 0 or samples_done == num_samples:
                        cumulative_avg = (running_sum / samples_done).astype(np.float32)
                        # Convert freq shift (GHz) to Gauss
                        gamma_e = 0.0028024  # GHz/Gauss
                        field_gauss = cumulative_avg / gamma_e
                        self.mag_sample_acquired.emit(samples_done, field_gauss)

                    # Autosave partial data
                    autosave_interval = s.perf_autosave_interval_samples
                    if samples_done % autosave_interval == 0:
                        self._autosave_partial(stability_cube[:samples_done])

        finally:
            self._close_handles(handles)

        # Trim cube to actual samples acquired
        actual_cube = stability_cube[:samples_done]

        return {
            "stability_cube": actual_cube,
            "freq_list": freq_list,
            "slope_list": slope_list,
            "parity_list": parity_list,
            "baseline_list": baseline_list,
            "num_samples_acquired": samples_done,
            "timestamp": datetime.now().isoformat(),
            "metadata": s.build_metadata(),
        }

    def _get_freq_config(self):
        """Format freq/slope/parity/baseline lists from current state."""
        s = self.state
        result = s.sweep_inflection_result
        if result is None:
            raise RuntimeError("No sweep result available. Run ODMR sweep first.")

        return qdm.format_multi_point_frequencies(
            inflection_points=result["inflection_points"],
            inflection_slopes=result["inflection_slopes"],
            indices=s.mag_selected_indices,
            parities=s.mag_selected_parities,
            ref_freq=s.sweep_ref_freq_ghz,
            inflection_contrasts=result["inflection_contrasts"],
        )

    def _get_image_shape(self):
        if self.simulation_mode:
            return 10, 10
        # Read from camera state if available
        if self.state.camera_state is not None:
            # Approximate from hardware binning setting
            pass
        return 480, 270  # default Basler acA1920 with 4x4 hw binning

    def _acquire_sample(self, handles, freq_list, slope_list, parity_list, baseline_list):
        """One measurement cycle across all frequencies."""
        s = self.state
        if self.simulation_mode:
            # Return synthetic noise frame
            return np.random.normal(0, 1e-4, self._get_image_shape()).astype(np.float32)

        return qdm.measure_multi_point(
            sg384=s.sg384_controller,
            camera=handles["camera_instance"],
            freq_list=freq_list,
            slope_list=slope_list,
            parity_list=parity_list,
            settling_time=s.perf_mw_settling_time_s,
            n_frames=s.perf_n_frames_per_point,
            baseline_list=baseline_list,
        )

    def _init_handles(self) -> dict:
        if self.simulation_mode:
            return {}
        s = self.state
        settings = {
            "settling_time": s.perf_mw_settling_time_s,
            "n_frames": s.perf_n_frames_per_point,
            "simulation_mode": False,
        }
        return qdm.initialize_system(False, settings, logger=None)

    def _close_handles(self, handles):
        if not self.simulation_mode and handles.get("camera_instance"):
            try:
                handles["camera_instance"].close()
            except Exception:
                pass

    def _autosave_partial(self, partial_cube: np.ndarray):
        """Save partial stability cube to temp file (overwritten each time)."""
        s = self.state
        if not s.save_base_path:
            return
        save_dir = Path(s.save_base_path) / s.save_subfolder
        save_dir.mkdir(parents=True, exist_ok=True)
        path = save_dir / "_magnetometry_partial_autosave.npz"
        try:
            np.savez_compressed(path, stability_cube=partial_cube,
                                metadata=str(s.build_metadata()))
        except Exception:
            pass  # Don't let autosave failures abort the measurement
```

**Step 4: Run tests**
```bash
python -m pytest tests/test_magnetometry_worker.py -v
```
Expected: All pass.

**Step 5: Commit**
```bash
git add GUI/odmr_app/workers/magnetometry_worker.py \
        GUI/odmr_app/tests/test_magnetometry_worker.py
git commit -m "feat(odmr-app): add MagnetometryWorker with live preview and autosave"
```

---

## Phase 1 Complete

Run the full test suite to confirm nothing regressed:
```bash
cd GUI/odmr_app
python -m pytest tests/ -v
```
Expected: All tests pass.

```bash
git log --oneline -5
```

**Proceed to Phase 2:** `docs/plans/2026-02-20-odmr-app-plan-phase2.md`
— Camera tab refactor and custom widgets (InflectionTableWidget, FieldMapDisplayWidget).
