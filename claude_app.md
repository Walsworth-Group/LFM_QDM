# Experimental Control App Architecture

## Installation

```bash
pip install PySide6 pyqtgraph
```

---

## Version Control Guidelines

**IMPORTANT:** Before making substantial edits to any `.py` or `.ipynb` file, create a versioned backup in the `/legacy/` subfolder.

### Backup Naming Convention

```
<filename>_YYYY-MM-DD_v#.<ext>
```

**Examples:**
- `qdm_gen_2026-02-04_v1.py`
- `Camera ODMR-new_2026-02-10_v1.ipynb`
- `pid_control_app_2026-02-10_v2.py` (if multiple backups same day)

### When to Create Backups

- **Substantial refactoring** (changing architecture, adding worker threads, etc.)
- **Major feature additions** that modify core functionality
- **Breaking changes** to APIs or interfaces
- **Before debugging complex issues** (to have a known-good state)

### How to Create Backups

```python
# In your code/script
import shutil
from datetime import datetime
from pathlib import Path

def backup_to_legacy(filepath):
    """Create versioned backup in /legacy/ folder."""
    file_path = Path(filepath)
    legacy_dir = file_path.parent / "legacy"
    legacy_dir.mkdir(exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    version = 1

    # Find next available version number for today
    while True:
        backup_name = f"{file_path.stem}_{date_str}_v{version}{file_path.suffix}"
        backup_path = legacy_dir / backup_name
        if not backup_path.exists():
            break
        version += 1

    shutil.copy2(filepath, backup_path)
    print(f"Backup created: {backup_path}")
```

**Command line (manual):**
```bash
mkdir -p legacy
cp myfile.py "legacy/myfile_$(date +%Y-%m-%d)_v1.py"
```

---

## Core Pattern
1. **experiment_state.py** - Shared state with signals (source of truth)
2. **main_control.py** - User controls, modifies state
3. **monitoring_window.py** - Observes state, displays data
4. **worker_thread.py** - Non-blocking hardware I/O (NEW - see below)
5. **script_executor.py** - Command objects + executor
6. **script_manager.py** - Script generation & execution
7. **app_main.py** - Wire everything together

---

## Worker Thread Pattern (CRITICAL for Multi-App Operation)

**RULE:** All blocking hardware I/O MUST run in worker threads to prevent UI freezing and allow multiple apps to run simultaneously without blocking each other.

### When to Use Worker Threads

✅ **Always use worker threads for:**
- Hardware communication (VISA, serial, USB, DAQ, etc.)
- File I/O operations that might be slow
- Network requests
- Any operation that takes >16ms (to maintain 60 FPS UI)
- Continuous data acquisition loops
- Polling hardware for status updates

❌ **Don't use worker threads for:**
- Quick calculations (<16ms)
- UI updates (MUST be in main thread)
- Signal emissions (handled automatically by Qt)

### Worker Thread Template

```python
from PySide6.QtCore import QThread, Signal

class HardwareWorker(QThread):
    """
    Worker thread for non-blocking hardware communication.

    Signals for communicating with main thread:
    - All hardware responses should emit signals
    - UI updates happen in main thread via signal handlers
    """

    # Define signals for results
    connection_established = Signal(dict)  # Initial status
    connection_failed = Signal(str)  # Error message
    data_acquired = Signal(float, float, float)  # Example: (timestamp, value1, value2)
    parameter_set_success = Signal(str, object)  # (param_name, value)
    parameter_set_failed = Signal(str, str)  # (param_name, error_msg)

    def __init__(self, state):
        super().__init__()
        self.state = state
        self.hardware = None
        self._is_running = False
        self._command_queue = []  # Queue of (command, args) tuples

    def run(self):
        """Main worker thread loop."""
        self._is_running = True

        try:
            # Connect to hardware
            self._connect_hardware()

            # Process commands while running
            while self._is_running:
                # Process queued commands
                if self._command_queue:
                    command, args = self._command_queue.pop(0)
                    self._execute_command(command, args)

                # Continuous data acquisition if enabled
                if self.state.is_acquiring:
                    self._acquire_data()

                # Small sleep to avoid busy-waiting
                time.sleep(0.01)

        except Exception as e:
            self.connection_failed.emit(str(e))

        finally:
            self._disconnect_hardware()

    def stop(self):
        """Stop the worker thread."""
        self._is_running = False

    def queue_command(self, command, *args):
        """Queue a command for execution in worker thread."""
        self._command_queue.append((command, args))

    def _connect_hardware(self):
        """Connect to hardware (runs in worker thread)."""
        # Connect to instrument
        self.hardware = connect_to_instrument()
        initial_status = self.hardware.get_status()
        self.connection_established.emit(initial_status)

    def _disconnect_hardware(self):
        """Disconnect from hardware."""
        if self.hardware:
            self.hardware.close()

    def _execute_command(self, command, args):
        """Execute a hardware command (runs in worker thread)."""
        try:
            if command == 'set_parameter':
                param_name, value = args
                self.hardware.set_parameter(param_name, value)
                self.parameter_set_success.emit(param_name, value)

            elif command == 'read_status':
                status = self.hardware.get_status()
                self.connection_established.emit(status)

            # Add more commands as needed...

        except Exception as e:
            self.parameter_set_failed.emit(command, str(e))

    def _acquire_data(self):
        """Acquire data from hardware (runs in worker thread)."""
        timestamp, value1, value2 = self.hardware.read_data()
        self.data_acquired.emit(timestamp, value1, value2)
        time.sleep(self.state.sample_interval)
```

### Using Workers in Main Window

```python
class MainControlWindow(QWidget):
    def __init__(self, state: ExperimentState):
        super().__init__()
        self.state = state
        self.worker = None
        self.init_ui()

    def on_connect(self):
        """Connect to hardware using worker thread."""
        if self.worker is not None and self.worker.isRunning():
            return

        # Create worker
        self.worker = HardwareWorker(self.state)

        # Connect worker signals to handlers
        self.worker.connection_established.connect(self.on_connected)
        self.worker.connection_failed.connect(self.on_connection_error)
        self.worker.data_acquired.connect(self.on_data)
        self.worker.parameter_set_success.connect(self.on_param_set)

        # Start worker
        self.worker.start()

    def on_disconnect(self):
        """Disconnect from hardware."""
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait()  # Wait for thread to finish
            self.worker = None

    def on_set_parameter(self):
        """Set a parameter (queued in worker thread)."""
        if not self.worker or not self.worker.isRunning():
            self.log("Not connected")
            return

        value = self.parameter_input.value()
        self.worker.queue_command('set_parameter', 'gain', value)
        self.log(f"Setting gain to {value}...")

    @Slot(dict)
    def on_connected(self, status):
        """Handle connection established (runs in main thread)."""
        self.state.update_from_hardware(status)
        self.log("Connected successfully")

    @Slot(str)
    def on_connection_error(self, error):
        """Handle connection error (runs in main thread)."""
        self.log(f"Error: {error}")

    @Slot(float, float, float)
    def on_data(self, timestamp, value1, value2):
        """Handle acquired data (runs in main thread)."""
        self.state.update_data(timestamp, value1, value2)

    @Slot(str, object)
    def on_param_set(self, param_name, value):
        """Handle successful parameter set (runs in main thread)."""
        self.log(f"{param_name} set to {value}")

    def closeEvent(self, event):
        """Clean up when window closes."""
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait()
        event.accept()
```

### Key Worker Thread Principles

1. **Hardware I/O in worker thread ONLY**
   - Never call `self.hardware.command()` from UI code
   - Always use `self.worker.queue_command()`

2. **UI updates in main thread ONLY**
   - Worker emits signals
   - Main thread handlers update UI
   - Qt automatically thread-marshals signals

3. **State updates via signals**
   - Worker queries hardware
   - Worker emits signal with result
   - Main thread handler updates state
   - State change triggers UI updates via signals

4. **Command queue pattern**
   - UI queues commands via `queue_command()`
   - Worker processes queue in its thread
   - Results returned via signals

5. **Proper cleanup**
   - Always call `worker.stop()` before closing
   - Use `worker.wait()` to ensure thread finishes
   - Disconnect hardware in worker thread

### Multi-App Benefits

When using worker threads properly:

✅ **No blocking** - Apps update independently
✅ **Responsive UI** - Even during slow hardware operations
✅ **Parallel operation** - Multiple apps can run simultaneously
✅ **Thread-safe** - Qt handles synchronization automatically

### Common Mistake to Avoid

❌ **BAD - Blocking UI thread:**
```python
def on_button_click(self):
    self.hardware.set_value(123)  # Blocks entire event loop!
    time.sleep(2)  # Freezes ALL apps!
    result = self.hardware.read_value()  # Blocks again!
```

✅ **GOOD - Non-blocking worker:**
```python
def on_button_click(self):
    self.worker.queue_command('set_value', 123)  # Returns immediately
    # Result will arrive via signal handler
```

---

## ExperimentState Template

```python
from PySide6.QtCore import QObject, Signal

class ExperimentState(QObject):
    parameter_changed = Signal(float)
    measurement_started = Signal()
    measurement_stopped = Signal()
    
    def __init__(self):
        super().__init__()
        self._parameter = 0.0
    
    @property
    def parameter(self):
        return self._parameter
    
    @parameter.setter
    def parameter(self, value):
        self._parameter = value
        self.parameter_changed.emit(value)
```

**Rule:** One signal/property per parameter that changes.

---

## Main Control Window Template

```python
class MainControlWindow(QWidget):
    def __init__(self, state: ExperimentState):
        self.state = state
        self.init_ui()
    
    def on_button_click(self):
        # Modify state (this triggers signals to monitoring windows)
        self.state.parameter = float(self.parameter_input.text())
        # Call hardware if needed
```

**Rule:** Modify state when user interacts; monitoring windows auto-update.

---

## Monitoring Window Template

```python
class MonitoringWindow(QWidget):
    def __init__(self, state: ExperimentState):
        self.state = state
        self.connect_signals()
    
    def connect_signals(self):
        self.state.parameter_changed.connect(self.on_parameter_changed)
    
    def on_parameter_changed(self, value):
        self.value_label.setText(f"{value:.2f}")
```

**Rule:** Listen to signals; never modify state.

---

## Script Commands Template

```python
class ScriptCommand:
    def execute(self, executor):
        raise NotImplementedError

class ClickButtonCommand(ScriptCommand):
    def __init__(self, button_name):
        self.button_name = button_name
    
    def execute(self, executor):
        if self.button_name == "start":
            executor.main_window.on_start()
        print(f"[Script] Clicked {self.button_name}")

class SetParameterCommand(ScriptCommand):
    def __init__(self, parameter_name, value):
        self.parameter_name = parameter_name
        self.value = value
    
    def execute(self, executor):
        executor.main_window.parameter_input.setText(str(self.value))

class WaitCommand(ScriptCommand):
    def __init__(self, duration):
        self.duration = duration
    
    def execute(self, executor):
        import time
        time.sleep(self.duration)

class ReadParameterCommand(ScriptCommand):
    def __init__(self, parameter_name):
        self.parameter_name = parameter_name
    
    def execute(self, executor):
        return getattr(executor.state, self.parameter_name)

class LoopCommand(ScriptCommand):
    def __init__(self, count, commands):
        self.count = count
        self.commands = commands
    
    def execute(self, executor):
        for i in range(self.count):
            for cmd in self.commands:
                cmd.execute(executor)

class ConditionalCommand(ScriptCommand):
    def __init__(self, condition_func, true_commands, false_commands=None):
        self.condition_func = condition_func
        self.true_commands = true_commands
        self.false_commands = false_commands or []
    
    def execute(self, executor):
        if self.condition_func(executor):
            for cmd in self.true_commands:
                cmd.execute(executor)
        else:
            for cmd in self.false_commands:
                cmd.execute(executor)
```

**Rule:** Add one command class per atomic action.

---

## Script Executor Template

```python
class ScriptExecutor:
    def __init__(self, main_window, monitoring_windows, state):
        self.main_window = main_window
        self.monitoring_windows = monitoring_windows
        self.state = state
        self.is_running = False
    
    def execute_script(self, commands):
        self.is_running = True
        try:
            for cmd in commands:
                if not self.is_running:
                    break
                cmd.execute(self)
        finally:
            self.is_running = False
    
    def stop_script(self):
        self.is_running = False
```

---

## Script Manager Template

```python
class ScriptManagerWindow(QWidget):
    def __init__(self, executor: ScriptExecutor, state: ExperimentState):
        self.executor = executor
        self.state = state
        self.current_script_commands = None
        self.init_ui()
    
    def on_generate_script(self):
        # TODO: Call Claude Code to generate commands
        user_input = self.natural_language_input.toPlainText()
        # Generated code should create: commands = [cmd1, cmd2, ...]
        # Then: self.current_script_commands = commands
    
    def on_execute_script(self):
        if self.current_script_commands:
            self.executor.execute_script(self.current_script_commands)
```

---

## Real-Time Plotting Standard (PyQtGraph)

Default for scientific data visualization. Install with: `pip install pyqtgraph`

**ALWAYS use the standardized `RealTimeGraph` class from `real_time_graph.py` for monitoring plots.**

### Import and Use

```python
from real_time_graph import RealTimeGraph

# Create graph instance
graph = RealTimeGraph(
    state,
    title="Laser Power",
    y_label="Power (W)",
    time_window=60  # Initial time window in seconds
)
```

### Standard Features (Built-in)

- ✅ **Enable/Disable Rolling Window** - Checkbox to toggle between rolling window and manual control
- ✅ **Adjustable Time Window** - Spinbox (5 seconds to unlimited)
- ✅ **Y-Axis Auto-Scale** - Automatically scales to fit data
- ✅ **X-Axis Modes**:
  - Rolling window mode: Auto-pans to show last N seconds
  - Manual mode: Full PyQtGraph control (zoom, pan, right-click options)
- ✅ **No SI Prefix Auto-Scaling** - Prevents confusing "×0.001" axis labels
- ✅ **Info Display** - Current value, window size, point count
- ✅ **Right-Click Context Menu** - Auto Scale, View All, Manual Range, etc.
- ✅ **Clear Data Method** - `graph.clear_data()`
- ✅ **Light Background** - White background with dark text/axes

### Key Methods

```python
# Update Y-axis label (e.g., when switching units)
graph.set_y_label("Power (mW)")

# Clear all data
graph.clear_data()

# Programmatically set time window
graph.set_time_window(120)  # seconds

# Get current data
x_data, y_data = graph.get_current_data()

# Export to CSV
graph.export_csv("data.csv")
```

### Architecture Integration

The `RealTimeGraph` automatically connects to `ExperimentState.data_point_recorded` signal:

```python
# In ExperimentState
class ExperimentState(QObject):
    data_point_recorded = Signal(dict)  # Must emit {'timestamp': float, 'value': float}

    def update_measurement(self, timestamp, value):
        # Emit data for RealTimeGraph
        self.data_point_recorded.emit({'timestamp': timestamp, 'value': value})
```

### Unit Conversion Pattern

When displaying values in different units (e.g., W vs mW), intercept the signal and convert before passing to graph:

```python
# In your control window
def create_graph(self):
    self.graph = RealTimeGraph(self.state, title="Laser Power", y_label="Power (W)")

    # Disconnect default and use custom handler for unit conversion
    self.state.data_point_recorded.disconnect(self.graph.on_new_data)
    self.state.data_point_recorded.connect(self.on_graph_data)

def on_graph_data(self, data):
    """Convert units before sending to graph"""
    value_watts = data['value']
    value_display = value_watts * 1000 if self.use_mw else value_watts
    self.graph.on_new_data({'timestamp': data['timestamp'], 'value': value_display})

def on_unit_changed(self):
    """When user switches units, update label and rescale existing data"""
    unit = 'mW' if self.use_mw else 'W'
    self.graph.set_y_label(f"Power ({unit})")

    # Rescale existing data
    if self.graph.data_y:
        scale = 1000 if (not was_mw and self.use_mw) else 1/1000
        self.graph.data_y = [y * scale for y in self.graph.data_y]
        self.graph.plot_line.setData(self.graph.data_x, self.graph.data_y)
```

### Multiple Graphs Example

```python
# Different graphs for different measurements
power_graph = RealTimeGraph(state, title="Laser Power", y_label="Power (W)", time_window=60)
temp_graph = RealTimeGraph(state, title="Temperature", y_label="Temp (K)", time_window=300)
```

### DO NOT Create Custom Plots

Always use `RealTimeGraph` for consistency. Do not create custom PyQtGraph widgets unless there's a specific requirement that RealTimeGraph cannot fulfill.

---

## App Entry Point Template

```python
def main():
    app = QApplication(sys.argv)
    state = ExperimentState()
    
    main_window = MainControlWindow(state)
    monitoring_1 = MonitoringWindow(state)
    graph = RealTimeGraph(state, "Temperature")
    
    executor = ScriptExecutor(main_window, [monitoring_1], state)
    script_manager = ScriptManagerWindow(executor, state)
    
    main_window.show()
    monitoring_1.show()
    graph.show()
    script_manager.show()
    
    sys.exit(app.exec())
```

---

## Key Principles

1. **One shared state** - All windows reference same ExperimentState instance
2. **Signal-based updates** - State changes emit signals; windows listen
3. **Separation of concerns** - Control modifies, monitoring observes
4. **Command pattern** - Scripts are lists of command objects
5. **No business logic in UI** - Put logic in state or commands

---

## Common Tasks

### Add a new parameter
1. Add to ExperimentState: `parameter_changed = Signal(float)` + property
2. Add to MainControlWindow: input field + button handler
3. Add to MonitoringWindow: connect signal + update display
4. Monitoring windows auto-update (no extra work needed)

### Add a new script command
1. Subclass ScriptCommand
2. Implement execute() method
3. Use in scripts via `MyCommand(args)`

### Add a monitoring window
```python
mon = MonitoringWindow(state)
mon.show()
executor.monitoring_windows.append(mon)
```

### Generate script with Claude
1. User enters natural language
2. Claude generates: `commands = [ClickButtonCommand("start"), WaitCommand(5), ...]`
3. Preview shows command list
4. User clicks Execute

---

## Hardware Integration

**IMPORTANT:** Always use worker threads for hardware communication.

### Hardware Interface Class

```python
class HardwareInterface:
    """Hardware abstraction layer - used by worker thread."""
    def connect(self): pass
    def disconnect(self): pass
    def set_parameter(self, value): pass
    def read_sensor(self): pass
    def get_status(self): pass
```

### Worker Thread Integration

```python
class HardwareWorker(QThread):
    data_acquired = Signal(float, float)
    parameter_set = Signal(str, object)

    def __init__(self, state):
        super().__init__()
        self.state = state
        self.hardware = HardwareInterface()
        self._is_running = False
        self._command_queue = []

    def run(self):
        self._is_running = True
        self.hardware.connect()

        while self._is_running:
            if self._command_queue:
                cmd, args = self._command_queue.pop(0)
                self._execute_command(cmd, args)
            time.sleep(0.01)

        self.hardware.disconnect()

    def queue_command(self, command, *args):
        self._command_queue.append((command, args))

    def _execute_command(self, command, args):
        if command == 'set_parameter':
            param, value = args
            self.hardware.set_parameter(param, value)
            self.parameter_set.emit(param, value)
```

### Main Window Integration

```python
# In MainControlWindow:
def __init__(self, state):
    super().__init__()
    self.state = state
    self.worker = None

def on_connect(self):
    self.worker = HardwareWorker(self.state)
    self.worker.parameter_set.connect(self.on_param_set)
    self.worker.start()

def on_set_parameter(self):
    value = float(self.parameter_input.text())
    self.worker.queue_command('set_parameter', 'gain', value)

@Slot(str, object)
def on_param_set(self, param, value):
    # Update state (runs in main thread)
    self.state.parameter = value
```

---

## Debugging

- Check state changes print to console
- Verify signals are emitted (`print(f"[Signal] {param_name} changed")`)
- Test commands individually in script executor
- Watch monitoring windows update when state changes
- Use script executor's print statements for automation tracking

---

## Running Multiple Apps Simultaneously

### Single QApplication, Multiple Windows

Qt allows only **one QApplication per process**. To run multiple control apps:

```python
# launcher.py
from PySide6.QtWidgets import QApplication
from experiment_state import ExperimentState
from laser_power_app import LaserPowerMonitor
from pid_control_app import PIDControlApp

app = QApplication([])

# Create SINGLE shared state
state = ExperimentState()

# Create multiple apps with shared state
laser_app = LaserPowerMonitor(state=state)
pid_app = PIDControlApp(state=state)

# Position windows side-by-side
laser_app.setGeometry(50, 50, 480, 800)
pid_app.setGeometry(550, 50, 480, 800)

laser_app.show()
pid_app.show()

app.exec()
```

### Shared State Pattern

All apps should accept optional `state` parameter:

```python
class MyControlApp(QMainWindow):
    def __init__(self, state=None):
        super().__init__()
        # Use provided state or create new one
        self.state = state if state is not None else ExperimentState()
        # ...
```

This allows:
- **Standalone mode**: `app = MyControlApp()` (creates its own state)
- **Shared mode**: `app = MyControlApp(state=shared_state)` (uses shared state)

### Cross-App Communication

Apps communicate via shared state signals:

```python
# In launcher or connection code
state.pid_output_changed.connect(laser_app.on_pid_output_changed)
state.laser_power_updated.connect(pid_app.on_laser_power_changed)
```

### State Naming Convention

When multiple subsystems share one state:

- **Laser power**: `laser_power`, `laser_acquisition_started`, etc.
- **PID controller**: `pid_setpoint`, `pid_output`, `pid_connection_changed`, etc.
- **ODMR**: `odmr_frequency`, `odmr_data_updated`, etc.

Prefix properties/signals with subsystem name to avoid conflicts.

---

## When to Use This

When Claude Code builds a new experimental control app:

1. **Follow these templates** - Consistent architecture across all apps
2. **Use worker threads** - ALWAYS for hardware I/O (prevents blocking)
3. **Accept state parameter** - Enable shared state for multi-app operation
4. **Adapt command classes** - Customize for your hardware
5. **Keep ExperimentState minimal** - Only shared data, not business logic
6. **Let signals drive updates** - UI reacts to state changes
7. **Create versioned backups** - Before substantial changes, backup to `/legacy/`
8. **Generate scripts via natural language** - If script automation needed

### Checklist for New Apps

- [ ] ExperimentState with proper signals
- [ ] Worker thread for all hardware I/O
- [ ] Main control window accepts optional `state` parameter
- [ ] Monitoring windows observe state via signals
- [ ] No blocking operations in UI thread
- [ ] Proper cleanup in `closeEvent()`
- [ ] Config save/load functionality
- [ ] RealTimeGraph for live plotting
- [ ] Versioned backup before major refactoring

This ensures consistency, performance, and compatibility across lab applications.

---

## Quick Reference

### App Startup Checklist

1. ✅ Create `ExperimentState` subclass with subsystem-prefixed properties
2. ✅ Create `Worker` subclass for hardware I/O
3. ✅ Create main window accepting optional `state` parameter
4. ✅ Connect worker signals to UI update handlers
5. ✅ Use `worker.queue_command()` for all hardware operations
6. ✅ Test standalone: `python my_app.py`
7. ✅ Test with launcher: Both apps run without blocking each other
8. ✅ Backup original files to `/legacy/` before major changes

### Common Issues

**Problem:** UI freezes when setting parameters
- **Cause:** Hardware I/O in main thread
- **Fix:** Move to worker thread, use command queue

**Problem:** Multiple apps block each other
- **Cause:** Hardware I/O in main thread
- **Fix:** Each app needs its own worker thread

**Problem:** State changes don't update UI
- **Cause:** Missing signal connections
- **Fix:** Check `connect_signals()` method

**Problem:** Worker thread doesn't stop on close
- **Cause:** Missing cleanup in `closeEvent()`
- **Fix:** Add `worker.stop()` and `worker.wait()`
