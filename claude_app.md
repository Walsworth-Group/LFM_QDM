# Experimental Control App Architecture Guide

PySide6 + pyqtgraph reference for building lab instrument control GUIs.

---

## Installation

```bash
pip install PySide6 pyqtgraph
```

---

## Version Control

**Before making substantial edits to any `.py` or `.ipynb` file**, create a versioned backup:

```
legacy/<filename>_YYYY-MM-DD_v#.<ext>
```

For directory-level changes: `legacy/<dirname>_YYYY-MM-DD_v1/`

When to create backups: substantial refactoring, major feature additions, breaking API changes, before debugging complex issues.

---

## Core Architecture: State → Workers → UI

The fundamental pattern for all lab control apps:

```
AppState (QObject)            ← central source of truth; Qt signals on every change
    ├── HardwareWorkerA (QThread)  ← non-blocking hardware I/O
    ├── HardwareWorkerB (QThread)  ← non-blocking hardware I/O
    └── AcquisitionWorker (QThread) ← data collection loop
```

**Key rule**: Hardware I/O ALWAYS in worker threads. UI ALWAYS in main thread. State is the bridge.

---

## State Object

### Template

```python
from PySide6.QtCore import QObject, Signal

class AppState(QObject):
    """Central state. All mutable properties emit Qt signals."""

    # One signal per parameter that needs to notify the UI
    temperature_changed = Signal(float)
    measurement_running_changed = Signal(bool)
    data_point_recorded = Signal(dict)  # {'timestamp': float, 'value': float}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._temperature = 0.0
        self._is_running = False

    @property
    def temperature(self) -> float:
        return self._temperature

    @temperature.setter
    def temperature(self, value: float):
        self._temperature = float(value)
        self.temperature_changed.emit(self._temperature)

    @property
    def is_running(self) -> bool:
        return self._is_running

    @is_running.setter
    def is_running(self, value: bool):
        self._is_running = bool(value)
        self.measurement_running_changed.emit(self._is_running)
```

### State Design Rules

- **One signal per property** that the UI needs to react to
- **Prefix subsystem names** to avoid conflicts: `sweep_freq_ghz`, `mag_num_samples`, `rf_is_connected`
- **Business logic methods** belong in state (e.g., `try_start_sweep()` that checks mutually exclusive conditions)
- **Config persistence**: implement `get_config()` / `load_config()` for JSON serialization of all user-adjustable properties
- **Do NOT** store live hardware objects (camera, SG384) as state properties with signals — they're plain attributes
- **Separate transient runtime state** (results, current measurement index) from configuration (freq ranges, num sweeps)

### Config Persistence Pattern

```python
_CONFIG_KEYS = ["freq_start_ghz", "freq_end_ghz", "num_sweeps", ...]

def get_config(self) -> dict:
    return {key: getattr(self, key) for key in self._CONFIG_KEYS}

def load_config(self, config: dict):
    for key, value in config.items():
        if key in self._CONFIG_KEYS:
            try:
                setattr(self, key, value)
            except Exception:
                pass  # silently skip unknown/incompatible keys
```

---

## Worker Threads

### When to Use Workers

✅ Always use workers for:
- Hardware communication (VISA, serial, USB, DAQ, camera)
- Operations that take >16 ms
- Continuous acquisition/polling loops
- File I/O that might be slow

❌ Never use workers for:
- UI updates (must be main thread)
- Quick calculations (<16 ms)

### Short-Lived Task Worker (One Measurement Run)

Use for operations that have a defined start and end (ODMR sweep, magnetometry stability measurement):

```python
from PySide6.QtCore import QThread, Signal

class AcquisitionWorker(QThread):
    progress = Signal(int, int)       # (current_step, total_steps)
    data_acquired = Signal(object)    # intermediate data for live preview
    completed = Signal(dict)          # final result dict
    failed = Signal(str)              # error message

    def __init__(self, state, simulation_mode=False, parent=None):
        super().__init__(parent)
        self.state = state
        self.simulation_mode = simulation_mode
        self._stop_requested = False

    def run(self):
        """Entry point — sets running flag, calls _run_measurement, clears flag."""
        self.state.is_running = True
        try:
            result = self._run_measurement()
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.state.is_running = False

    def stop(self):
        """Request early termination after current step completes."""
        self._stop_requested = True

    def _run_measurement(self) -> dict:
        results = []
        total = self.state.num_steps
        for i in range(total):
            if self._stop_requested:
                break
            data = self._acquire_one_step(i)
            results.append(data)
            self.progress.emit(i + 1, total)
            if (i + 1) % self.state.live_update_interval == 0:
                self.data_acquired.emit(self._compute_preview(results))
        return {"data": results, "n_acquired": len(results)}
```

**Critical pattern**: Check `_stop_requested` **inside the innermost loop** (per frequency step, not per sweep repetition) so Stop takes effect quickly.

**Averaging on early stop**: Track `completed_passes` separately from `total_passes` and divide by `completed_passes` when computing averages — never divide by the total if stopped early.

### Long-Running Polling Worker (RF status, laser power)

Use for workers that run continuously while the app is open:

```python
class PollingWorker(QThread):
    status_updated = Signal(dict)
    command_completed = Signal(str, object)  # (command_name, result)

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self._running = False
        self._commands = []  # list of (name, args) tuples

    def run(self):
        self._running = True
        self._connect_hardware()
        while self._running:
            # Process any queued commands first
            if self._commands:
                name, args = self._commands.pop(0)
                self._execute(name, args)
            else:
                # Idle polling
                self._poll_status()
            import time; time.sleep(self.state.poll_interval_s)
        self._disconnect_hardware()

    def stop(self):
        self._running = False

    def queue_command(self, name: str, *args):
        self._commands.append((name, args))
```

**SG384 lock pattern**: When multiple workers share hardware (e.g., a polling worker + an acquisition worker both using the SG384), use a `threading.Lock` on the state:

```python
# In state __init__:
self.sg384_lock = threading.Lock()

# In polling worker: non-blocking try
if state.sg384_lock.acquire(blocking=False):
    try:
        self._poll_rf_status()
    finally:
        state.sg384_lock.release()

# In acquisition worker: blocking acquire for entire measurement
with state.sg384_lock:
    for step in measurement_steps:
        ...  # exclusive access guaranteed
```

### Wiring Workers to UI

```python
class MainWindow(QMainWindow):
    def _start_measurement(self):
        self._worker = AcquisitionWorker(self.state, simulation_mode=...)
        self._worker.progress.connect(self._on_progress)
        self._worker.data_acquired.connect(self._on_data)
        self._worker.completed.connect(self._on_completed)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _stop_measurement(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()

    @Slot(int, int)
    def _on_progress(self, current, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.step_label.setText(f"Step {current}/{total}")  # "Step N/Total" not "Sweep N/Total"

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait()
        event.accept()
```

---

## UI Structure: Tab-Based Apps

For complex multi-step workflows, use a `QTabWidget` with one `TabHandler` class per tab:

### Tab Handler Pattern

```python
class SweepTabHandler:
    """Handles Sweep tab: connects UI widgets to state, manages worker lifecycle."""

    def __init__(self, tab_widget: QWidget, state: AppState,
                 stop_streaming_fn, set_mode_fn):
        self.state = state
        self._stop_streaming = stop_streaming_fn
        self._set_mode = set_mode_fn
        self._worker = None

        # Load Qt Designer UI into the placeholder widget
        self.ui = Ui_sweep_tab_content()
        self.ui.setupUi(tab_widget)

        # Add widgets that can't easily be done in Qt Designer
        self._add_programmatic_widgets()
        self._connect_widgets()
        self._sync_from_state()

    def _add_programmatic_widgets(self):
        """Inject pyqtgraph plots, complex widgets, etc. into placeholder containers."""
        self._plot = pg.PlotWidget()
        layout = QVBoxLayout(self.ui.plot_placeholder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._plot)

    def _connect_widgets(self):
        """Wire UI widgets ↔ state attributes and slot methods."""
        s = self.state
        ui = self.ui
        # Spinboxes → state (one-way, no feedback loop)
        ui.freq_start_spin.valueChanged.connect(lambda v: setattr(s, 'freq_start_ghz', v))
        # State signals → UI updates
        s.sweep_running_changed.connect(self._on_running_changed)
        # Buttons
        ui.start_btn.clicked.connect(self._on_start)
        ui.stop_btn.clicked.connect(self._on_stop)

    def _sync_from_state(self):
        """Push current state values → widgets (call once at init, after load_config)."""
        ui = self.ui
        s = self.state
        ui.freq_start_spin.setValue(s.freq_start_ghz)
        ui.stop_btn.setEnabled(False)
```

### Programmatic Widget Addition to Qt Designer Forms

When adding spinboxes or labels to an existing Qt Designer form layout:

```python
# In __init__, AFTER setupUi:
form = self.ui.my_form_layout   # access the QFormLayout by name
lbl = QLabel("Exposure time (µs):")
self._exposure_spin = QSpinBox()
self._exposure_spin.setMinimum(100)
self._exposure_spin.setMaximum(500000)
self._exposure_spin.setSingleStep(1000)
form.addRow(lbl, self._exposure_spin)
# Then connect and sync as normal
```

---

## pyqtgraph Usage

### Live Spectrum Plot (ODMR sweep)

```python
import pyqtgraph as pg
import numpy as np

# In _add_programmatic_widgets:
self._plot = pg.PlotWidget()
self._plot.setLabel('left', 'Contrast')
self._plot.setLabel('bottom', 'Frequency (GHz)')

# Data series — dark purple dots, no connecting line
_purple = (80, 0, 120)
self._data_curve = self._plot.plot(
    pen=None, symbol='o',
    symbolBrush=pg.mkBrush(_purple),
    symbolPen=pg.mkPen(None),
    symbolSize=5
)
# Fit curve — solid black line
self._fit_curve = self._plot.plot(pen=pg.mkPen('k', width=2))

# Update during acquisition:
self._data_curve.setData(freqs, contrasts)

# Update after completion (Lorentzian fit overlay):
if result.get("x_fit") is not None:
    self._fit_curve.setData(np.asarray(result["x_fit"]),
                            np.asarray(result["y_fit"]))
```

### Live Image View (field map preview)

```python
self._preview = pg.ImageView()
self._preview.ui.roiBtn.hide()
self._preview.ui.menuBtn.hide()
layout = QVBoxLayout(self.ui.preview_placeholder)
layout.setContentsMargins(0, 0, 0, 0)
layout.addWidget(self._preview)

# Update:
self._preview.setImage(field_gauss.T, autoLevels=True)
```

### RealTimeGraph (rolling-window monitoring)

For continuous time-series monitoring (laser power, PID output), use the existing `RealTimeGraph` widget from `GUI/widgets/real_time_graph.py`:

```python
from widgets.real_time_graph import RealTimeGraph

graph = RealTimeGraph(state, title="Laser Power", y_label="Power (mW)", time_window=60)
# Automatically connects to state.data_point_recorded Signal(dict)
# dict must have keys: 'timestamp' (float) and 'value' (float)
```

---

## Qt Designer / UI Files

- `.ui` files in `ui/` are Qt Designer XML. **Never edit `ui_*.py` by hand.**
- Regenerate Python bindings after editing a .ui file: `pyside6-uic -g python my_tab.ui -o ui_my_tab.py` (run from `ui/`)
- Inject complex widgets (pyqtgraph, custom tables) programmatically after `setupUi`; put placeholder `QWidget` containers in Qt Designer
- Use `formLayout.addRow(label, widget)` to add rows programmatically to existing form layouts

---

## Multi-App Launcher Pattern

Qt allows only one `QApplication` per process. To run multiple apps together:

```python
# launch_all_apps.py
from PySide6.QtWidgets import QApplication
import sys
from state.experiment_state import ExperimentState
from laser_power_app import LaserPowerApp
from pid_control_app import PIDControlApp

app = QApplication(sys.argv)
state = ExperimentState()   # single shared state

laser = LaserPowerApp(state=state)
pid = PIDControlApp(state=state)

laser.show()
pid.show()
sys.exit(app.exec())
```

Each app must accept an optional `state` parameter:

```python
class MyApp(QMainWindow):
    def __init__(self, state=None, parent=None):
        super().__init__(parent)
        self.state = state if state is not None else AppState()
```

### sys.path Management for Embedded Apps

When one app (e.g., `odmr_app`) embeds another app (e.g., `camera_app`) as a tab, and both have `state/` and `workers/` subpackages with the same names, use `sys.modules` to prevent import collisions:

```python
# Before importing camera_app:
import sys
_saved = {k: sys.modules.pop(k) for k in list(sys.modules)
          if k.startswith(('state.', 'workers.', 'state', 'workers'))}
from camera_app import CameraApp
sys.modules.update(_saved)  # restore odmr_app's state/workers
```

---

## Config Save/Load

```python
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config" / "app_config.json"

def save_config(state):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, 'w') as f:
        json.dump(state.get_config(), f, indent=2, default=str)

def load_config(state):
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            state.load_config(json.load(f))
```

Call `load_config` at app startup (after creating state but before showing UI), `save_config` in `closeEvent`.

---

## Common Pitfalls and Lessons Learned

### Hardware / Workers

**Stop button doesn't work mid-sweep**
- Root cause: `_stop_requested` only checked between outer loop iterations (sweep repetitions), not inner iterations (frequency steps)
- Fix: Check `_stop_requested` inside the innermost loop that drives hardware steps

**Progress bar never updates**
- Root cause: Progress signal emitted only once per full sweep pass, not per frequency step
- Fix: Call `self.progress.emit(steps_done, total_steps)` after every `measure_odmr_point()` call

**Averaging wrong on early stop**
- Root cause: Final result divided by `num_passes` regardless of how many completed
- Fix: Track `passes_done` counter; increment only when a full pass completes; divide by `max(1, passes_done)`

**Camera exclusive access**
- Root cause: Camera opened by streaming worker AND by acquisition worker simultaneously
- Fix: Stop streaming before starting acquisition; use a `CameraMode` enum (`IDLE / STREAMING / ACQUIRING`) and enforce transitions

**sys.path import order**
- Root cause: `odmr_app/` directory contains `state/` and `workers/` subpackages; if `GUI/` is on sys.path first, these shadow the standalone `GUI/state/` and `GUI/workers/`
- Fix: Use `sys.path.insert(0, ...)` to put the app-specific root FIRST, not last

**SG384 `get_frequency()` not implemented**
- Root cause: Polling worker called `get_frequency()` which was never implemented in `SG384Controller`
- Fix: Add the method, or check `hasattr` before calling

### UI

**Signal feedback loops**
- Root cause: Syncing state → widget triggers widget's `valueChanged` → sets state again → infinite loop
- Fix: Wrap `_sync_from_state` widget updates with `widget.blockSignals(True) ... widget.blockSignals(False)`

**CameraMode ValueError**
- Root cause: State emitted `CameraMode` enum object; subscriber tried `CameraMode(enum_obj)` which raises ValueError
- Fix: Emit `.value` (the string), not the enum: `self.camera_mode_changed.emit(value.value)`

**File menu not showing**
- Root cause: Menu bar created but not added to the correct parent (must be `QMainWindow.menuBar()`)
- Fix: Use `self.menuBar().addMenu(...)` not `QMenuBar(); self.layout().addWidget(menubar)`

**Plot fit curves never appear**
- Root cause: `_fit_curve` created in `__init__` but never populated (forgot to call `setData` in the completion slot)
- Fix: In `_on_sweep_completed`, check `result.get("x_fit")` and call `self._fit_curve.setData(...)`

**Camera config path collision**
- Root cause: `camera_app.py` saves/loads config from a fixed relative path, but when embedded in odmr_app, cwd is different
- Fix: Use `Path(__file__).parent` anchored paths for all config files

### State Design

**Vestigial settings**
- A setting that exists in state and the Settings UI but is never actually read by any worker is confusing
- Example: `perf_camera_flush_frames` — `flush_buffer()` is called unconditionally in `qdm_gen`, so the setting has no effect
- Fix: Remove from state, `_CONFIG_KEYS`, and the UI binding; hide the widget programmatically if you can't edit the .ui file

**Per-operation vs global settings**
- If two operations (sweep, magnetometry) both use a camera but with different optimal settings (exposure time, frames), give each its own property in state
- Don't share a single global `perf_camera_exposure_time_us`; use `sweep_exposure_time_us` and `mag_exposure_time_us`

**Cross-tab communication via state signals**
- When "Send to Magnetometry" in Sweep tab should update Magnetometry tab spinboxes, the cleanest approach is:
  1. Sweep tab sets `state.mag_exposure_time_us = ...` and emits `state.mag_camera_settings_pushed.emit(exp_us, n_frames)`
  2. Magnetometry tab listens to `state.mag_camera_settings_pushed` and updates its spinboxes
- This keeps state as the single source of truth without the tabs knowing about each other

---

## Device Abstraction (Multi-Device Apps)

For apps that need to support multiple hardware configurations (different labs, different hardware setups), use an abstraction layer:

```python
from abc import ABC, abstractmethod
from PySide6.QtWidgets import QWidget

class AbstractDevice(ABC):
    @abstractmethod
    def get_name(self) -> str: ...
    @abstractmethod
    def get_control_widget(self) -> QWidget: ...
    @abstractmethod
    def is_connected(self) -> bool: ...
    @abstractmethod
    def get_worker(self) -> 'AbstractDeviceWorker': ...

class DeviceRegistry:
    """Auto-discovers available devices at startup."""
    def __init__(self):
        self.devices = {}
        self.available_device_classes = []  # register AbstractDevice subclasses here

    def discover_devices(self):
        for cls in self.available_device_classes:
            try:
                dev = cls()
                if dev.is_connected():
                    self.devices[dev.get_name()] = dev
            except Exception as e:
                print(f"Could not initialize {cls.__name__}: {e}")
```

**When to use**: Different labs with different hardware, hardware swapping needed, team shares code across setups.
**When NOT to use**: Single fixed hardware setup — the abstraction adds complexity without benefit.

---

## Testing

### Install

```bash
pip install pytest pytest-qt
```

### Three layers of tests (write all three)

**1. Unit tests** — test one class in isolation with `MagicMock` for hardware:
```python
from unittest.mock import MagicMock
state.sg384_controller = MagicMock()
worker = AcquisitionWorker(state, simulation_mode=True)
worker.start(); worker.wait(15000)
```

**2. Smoke tests** (`tests/test_smoke.py`) — import and instantiate every key class; no logic:
```python
def test_state_instantiates():
    state = AppState()
    assert state.is_running is False

def test_main_window_instantiates():
    state = AppState()
    state._simulation_mode = True
    win = MainWindow(app_state=state)
    assert win._sweep_handler is not None
    win.close()
```
Smoke tests catch the class of bugs visible at app startup: import errors, missing methods called in `__init__`, wrong signal types. They take <2 s and require no hardware.

**3. GUI integration tests** (`tests/test_gui_integration.py`) — use `qtbot` to click buttons and wait for signals:
```python
def test_start_button_sets_running(qtbot):
    win = make_sim_window()
    qtbot.addWidget(win)
    win.show()
    received = []
    win.state.measurement_running_changed.connect(received.append)
    win._tab_handler.ui.start_btn.click()
    deadline = time.monotonic() + 2.0
    while not received and time.monotonic() < deadline:
        app.processEvents(); time.sleep(0.02)
    assert True in received
    win.close()
```
Integration tests catch: wrong button wiring, missing state transitions, slots that crash on first invocation, camera mode not restored after sweep.

### The simulation/hardware code path rule

**Simulation and hardware MUST share the same measurement loop.** If they diverge, tests in simulation mode will not catch hardware bugs.

**Wrong pattern** (diverged paths):
```python
def _run_measurement(self):
    if self.simulation_mode:
        data = vectorized_sim()      # one-shot, no per-step loop
        for i in range(n): time.sleep(0.01); self.progress.emit(i, n)
    else:
        for i, freq in enumerate(freqs):
            if self._stop_requested: break
            measure_step(sg384, camera, freq, ...)
            self.progress.emit(i + 1, n)
```

**Right pattern** (unified loop with `_measure_step`):
```python
def _run_measurement(self):
    if self.simulation_mode:
        _precomputed = run_simulation(freqs, ...)   # compute once before loop
    for i, freq in enumerate(freqs):
        if self._stop_requested: break
        self._measure_step(i, _precomputed, sg384, camera, freq, ...)
        self.progress.emit(i + 1, total)

def _measure_step(self, idx, sim_data, sg384, camera, freq, ...):
    if self.simulation_mode:
        self._cube[idx] += sim_data[idx]
        time.sleep(0.005)           # hold lock briefly for lock tests
    else:
        measure_odmr_point(sg384, camera, freq, ...)
```

With the unified loop: stop checks, progress granularity, and lock acquisition are all exercised identically in tests and production.

### Key smoke test patterns

**Signal carries the right type** (catches CameraMode ValueError class of bug):
```python
def test_mode_signal_carries_string():
    state = AppState()
    received = []
    state.mode_changed.connect(lambda v: received.append(v))
    state.mode = Mode.STREAMING
    assert received == ["streaming"]   # not the enum object
```

**Hidden vestigial widgets**:
```python
def test_settings_tab_handler():
    handler = SettingsTabHandler(QWidget(), state)
    assert not handler.ui.deprecated_spin.isVisible()
```

### Run all tests

```bash
cd GUI/odmr_app
python -m pytest tests/ -v
```

---

## Checklist for New Apps

- [ ] `AppState` (QObject) with subsystem-prefixed properties and signals
- [ ] `_CONFIG_KEYS` list + `get_config()` / `load_config()` for JSON persistence
- [ ] Worker thread(s) for ALL hardware I/O; no blocking in main thread
- [ ] Short-lived workers: `_stop_requested` checked **per innermost step**
- [ ] Simulation and hardware share the same per-step measurement loop (`_measure_step` pattern)
- [ ] Polling workers: non-blocking `sg384_lock.acquire(blocking=False)`
- [ ] Tab handlers: `_add_programmatic_widgets()` → `_connect_widgets()` → `_sync_from_state()`
- [ ] `blockSignals(True/False)` in `_sync_from_state` to avoid feedback loops
- [ ] `closeEvent`: stop all workers, `worker.wait()`, save config
- [ ] Accept optional `state` param for multi-app launcher
- [ ] Simulation mode for testing without hardware (`simulation_mode=True`)
- [ ] Tests: unit tests + smoke tests (`test_smoke.py`) + GUI integration tests (`test_gui_integration.py`)
- [ ] Backup to `legacy/` before major refactoring

---

## Quick Reference: Common Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| Stop button ineffective | `_stop_requested` checked only between passes | Check inside innermost frequency loop |
| Progress bar stuck | Signal emitted once per pass, not per step | Emit after every `measure_point()` call |
| Wrong average on stop | Divides by `total_passes` regardless | Track `passes_done`, divide by that |
| UI freezes | Hardware I/O in main thread | Move to worker thread |
| Signal feedback loop | `_sync_from_state` triggers `valueChanged` | Wrap with `blockSignals(True/False)` |
| CameraMode ValueError | Emitting enum object instead of string | Emit `value.value` (the string) |
| Import collision | Two packages with same name on sys.path | Insert app-specific root at position 0 |
| Config path wrong | Relative path breaks when cwd changes | Use `Path(__file__).parent`-anchored paths |
