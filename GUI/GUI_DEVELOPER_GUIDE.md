# GUI Developer Guide

Reference document for understanding, modifying, and extending the QDM instrument control GUI apps.
Last updated: 2026-02-17.

---

## Table of Contents

1. [Directory Structure](#1-directory-structure)
2. [Architecture Overview](#2-architecture-overview)
3. [App: Laser Power Monitor](#3-app-laser-power-monitor)
4. [App: PID Controller](#4-app-pid-controller)
5. [App: Basler Camera](#5-app-basler-camera)
6. [Multi-App Launcher](#6-multi-app-launcher)
7. [State Objects](#7-state-objects)
8. [Worker Threads](#8-worker-threads)
9. [Reusable Widgets](#9-reusable-widgets)
10. [Config Files](#10-config-files)
11. [How to Add a New App](#11-how-to-add-a-new-app)
12. [How to Add a New Feature to an Existing App](#12-how-to-add-a-new-feature-to-an-existing-app)
13. [Common Pitfalls](#13-common-pitfalls)

---

## 1. Directory Structure

```
GUI/
├── laser_power_app.py        ← NI-DAQ laser power monitor
├── pid_control_app.py        ← SRS SIM960 PID controller
├── camera_app.py             ← Basler camera streaming
├── launch_all_apps.py        ← Launches all three with shared state
├── simple_app.py             ← Minimal sandbox/example
│
├── launch_laser_power.bat    ← Double-click launcher (with console)
├── launch_pid_control.bat
├── launch_camera.bat
├── launch_all.bat
├── launch_laser_power_silent.vbs  ← Double-click launcher (no console)
├── launch_pid_control_silent.vbs
├── launch_camera_silent.vbs
├── launch_all_silent.vbs
│
├── state/                    ← Qt state objects (QObject + Signal)
│   ├── experiment_state.py   ← Shared state for laser power + PID apps
│   ├── camera_state.py       ← State for camera app
│   └── pid_state.py          ← Deprecated original PID state (reference only)
│
├── workers/                  ← QThread workers for non-blocking hardware I/O
│   ├── daq_worker.py         ← Continuous NI-DAQ acquisition
│   ├── pid_worker.py         ← SIM900/SIM960 PID hardware comms
│   ├── camera_worker.py      ← Basler camera frame producer
│   └── camera_consumer.py    ← Frame averaging and saving (consumer)
│
├── widgets/                  ← Reusable UI components
│   └── real_time_graph.py    ← Rolling-window time-series plot widget
│
├── config/                   ← JSON config files (auto-saved by apps)
│   ├── laser_power_config.json
│   ├── pid_control_config.json    (created on first save)
│   └── basler_camera_config.json  (created on first save)
│
└── docs/                     ← Documentation and reference assets
    ├── REFACTOR_SUMMARY.md
    ├── CAMERA_APP_README.md
    ├── LAUNCHER_README.txt
    ├── SIM960m.pdf
    └── ideal_default_size.png
```

### Import conventions

All apps are run from the `GUI/` root, so imports reference subfolders as packages:

```python
# In app entry points (GUI/*.py):
from state.experiment_state import ExperimentState
from workers.daq_worker import DAQWorker
from widgets.real_time_graph import RealTimeGraph

# In workers (GUI/workers/*.py), reaching ODMR code v2/ root:
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from qdm_basler import basler  # now findable

# In apps (GUI/*.py), reaching ODMR code v2/ root:
sys.path.insert(0, str(Path(__file__).parent.parent))
```

---

## 2. Architecture Overview

Every app follows the same three-layer pattern:

```
AppMainWindow (QMainWindow)
    │  reads/writes
    ▼
State (QObject + Signal)   ← single source of truth
    ▲  emits signals
    │
Worker (QThread)           ← hardware I/O, never touches UI directly
```

**Rules:**
- The **State** object owns all data. UI and Workers never communicate directly with each other.
- **Workers** read config from state, emit signals when data arrives. They never call Qt widget methods.
- **App windows** connect to state signals for UI updates, and call worker methods to trigger hardware actions.
- All hardware I/O is in workers. **Never put blocking calls in the main thread.**

### Threading model

```
Main Qt thread
├── App UI (event loop)
├── DAQWorker (QThread)          ← laser power acquisition
├── PIDWorker (QThread)          ← PID hardware polling
└── Camera producer-consumer:
    ├── CameraWorker (QThread)   ← frame grabbing
    └── CameraConsumer (QThread) ← averaging + saving
```

Threads communicate only via Qt signals/slots, which are thread-safe by default.

---

## 3. App: Laser Power Monitor

**File:** `laser_power_app.py`
**Class:** `LaserPowerMonitor(QMainWindow)`
**State:** `ExperimentState` (from `state/experiment_state.py`)
**Worker:** `DAQWorker` (from `workers/daq_worker.py`)
**Config:** `config/laser_power_config.json`

### What it does

Continuously reads voltage from an NI-DAQ analog input (Dev3/ai0 by default), converts it to laser power in Watts using a linear calibration (P = V × slope + intercept), and plots it in real time. Supports pause/resume, unit switching (W/mW), running statistics, and CSV data saving.

### UI layout

- **Monitor tab**
  - Current status panel: live power/voltage readout, mean, std, peak-to-peak, unit selector (W/mW), refresh rate control
  - `RealTimeGraph` widget: rolling-window time series plot
  - Data saving panel: directory, subfolder, filename suffix, timestamp toggle, Save button
  - Control buttons: Start / Pause / Stop / Clear Data

- **Configuration tab**
  - DAQ settings: device, channel, sample rate, batch size, voltage range min/max
  - Conversion settings: slope and intercept for V→W calibration
  - "Save Configuration as Default" button

### Key methods

| Method | Purpose |
|--------|---------|
| `on_start()` | Applies config, creates `DAQWorker`, starts acquisition |
| `on_pause()` / `on_stop()` | Pauses/stops the worker thread |
| `on_data_acquired(t, V, P)` | Slot receiving each data point from worker; updates state and buffers |
| `on_graph_data(data)` | Intercepts `data_point_recorded` signal and applies unit conversion before passing to graph |
| `apply_config()` | Pushes all UI config fields into state before starting acquisition |
| `update_statistics()` | Recomputes mean/std/ptp from accumulated `all_power_values` buffer |
| `save_config()` / `load_config()` | Persist settings to/from `config/laser_power_config.json` |

### Signal flow

```
DAQWorker.data_acquired(t, V, P)
    → LaserPowerMonitor.on_data_acquired()
        → state.update_laser_power(t, P)
            → state.laser_power_updated(t, P)  → on_power_updated() [updates label]
            → state.data_point_recorded(dict)  → on_graph_data()    [unit convert → graph]
```

### Calibration defaults

The default calibration in `ExperimentState` is:
- **slope** = 0.9527 W/V
- **intercept** = 0.0036 W

These are set for the current photodiode setup. Update them in the Configuration tab and click "Save Configuration as Default" to persist.

---

## 4. App: PID Controller

**File:** `pid_control_app.py`
**Class:** `PIDControlApp(QMainWindow)`
**State:** `ExperimentState` (from `state/experiment_state.py`)
**Worker:** `PIDWorker` (from `workers/pid_worker.py`)
**Config:** `config/pid_control_config.json`

### What it does

Controls the SRS SIM960 Analog PID Controller housed in a SIM900 Mainframe chassis, connected via USB/COM port (VISA resource string). Used to stabilize laser power by feeding back through the AOM.

### UI layout

- **Control tab**
  - Connection status + Connect / Disconnect / Refresh buttons
  - Current values display: Setpoint, Output, Error, Offset (large numeric labels)
  - Mode control: Manual Mode checkbox, Auto-Apply Changes checkbox
  - PID Parameters: Setpoint, Offset, P Gain (+ P Enable), I Time (+ I Enable), D Time (+ D Enable), Upper Limit, Lower Limit — each with a "Set" button
  - Manual Output Control: only active when in Manual Mode

- **Monitor tab**
  - Start/Stop Monitoring buttons + update interval spinner
  - Two `RealTimeGraph` widgets: Output Voltage vs Time, Error Signal vs Time

- **Settings tab**
  - COM port (VISA resource string, e.g. `ASRL3::INSTR`)
  - SIM900 module port (1–8, the physical slot the SIM960 occupies)
  - "Save Configuration as Default" button

- **Message log** (always visible at bottom): timestamped status messages

### Key methods

| Method | Purpose |
|--------|---------|
| `on_connect()` | Creates `PIDWorker`, starts thread (connects hardware inside worker) |
| `on_disconnect()` | Stops worker thread, cleans up |
| `on_set_setpoint()` etc. | Queues a hardware command in the worker via `worker.queue_command()` |
| `on_monitoring_data(t, out, err, sp)` | Slot receiving live monitoring values; feeds graphs directly |
| `connect_auto_apply()` | Wires all spinbox `valueChanged` signals to auto-apply handlers |
| `on_connection_established(status)` | Updates state from hardware status dict on first connect |
| `log_message(msg)` | Appends timestamped message to the message log |
| `save_config()` / `load_config()` | Persist COM port + port + monitor interval to JSON |

### Command queue pattern

All hardware interactions go through a command queue in `PIDWorker`. The app never calls hardware directly:

```python
# App queues a command:
self.worker.queue_command('set_setpoint', 1.05)

# Worker executes it in its thread:
# command == 'set_setpoint' → self.sim960.set_setpoint(1.05)
# → emits parameter_set_success('setpoint', 1.05)

# App receives confirmation:
# on_parameter_set_success() → state.pid_setpoint = 1.05
```

### Auto-Apply mode

When "Auto-Apply Changes" is checked, every spinbox `valueChanged` immediately queues the corresponding hardware command. When unchecked, parameters are only sent when the "Set X" button is clicked. This is useful for making rapid adjustments without clicking buttons repeatedly.

### PID state properties (all in `ExperimentState`)

| Property | Type | Description |
|----------|------|-------------|
| `pid_com_port` | str | VISA address, e.g. `'ASRL3::INSTR'` |
| `pid_sim900_port` | int | Physical port (1–8) of SIM960 in SIM900 |
| `pid_is_connected` | bool | Hardware connection status |
| `pid_setpoint` | float | PID setpoint voltage (V) |
| `pid_output` | float | Current output voltage (V) |
| `pid_error` | float | Setpoint − (output − offset) (V) |
| `pid_offset` | float | DC offset added to output (V) |
| `pid_p_gain` | float | Proportional gain |
| `pid_i_time` | float | Integral time constant (s) |
| `pid_d_time` | float | Derivative time constant (s) |
| `pid_manual_mode` | bool | True = manual output, False = PID control |
| `pid_upper_limit` | float | Output upper clamp (V) |
| `pid_lower_limit` | float | Output lower clamp (V) |
| `pid_is_monitoring` | bool | Whether monitoring loop is active |
| `pid_monitor_interval` | float | Polling period (s) |

---

## 5. App: Basler Camera

**File:** `camera_app.py`
**Class:** `BaslerCameraApp(QMainWindow)`
**State:** `CameraState` (from `state/camera_state.py`)
**Workers:** `CameraWorker` + `CameraConsumer` (from `workers/`)
**Config:** `config/basler_camera_config.json`

### What it does

Live streaming, frame averaging, and batch saving from a Basler acA1920-155um camera via pypylon. Uses a producer-consumer pattern: `CameraWorker` grabs frames into a queue, `CameraConsumer` reads from the queue to accumulate averages and handle saving.

### UI layout

- **Top half:** two side-by-side image panels
  - *Live Image*: real-time stream (throttled to ≤30 fps display), saturation warning, pixel coordinates on hover, "Save App Configuration" button
  - *Averaged Image*: updated each time N frames are accumulated; frames-to-average spinbox; "Enable Live Averaging" checkbox

- **Bottom left — Camera Controls panel**
  - Serial number input + "Connect to Camera" / "Disconnect" button
  - Start Streaming / Stop Streaming buttons
  - Exposure spinbox (0–100,000 µs) + logarithmic slider (piecewise linear 0–100 µs, log above)
  - Binning X/Y combos (1–4) + Binning Mode (Average/Sum) + Pixel Format (Mono8/Mono12/Mono12p)
  - Sum binning warning label (shown only in Sum mode)

- **Bottom right — Data Saving panel**
  - Save directory + Browse button
  - Subfolder, filename suffix, timestamp checkbox
  - File format combo (.npy / .tiff 16-bit / .jpg 8-bit)
  - Number of images to save + "Begin Saving" button

- **Status bar** at bottom

### Key methods

| Method | Purpose |
|--------|---------|
| `on_connect_camera()` | Creates `CameraWorker` + `CameraConsumer`, starts both threads |
| `on_disconnect_camera()` | Stops streaming, stops both threads |
| `on_start_streaming()` / `on_stop_streaming()` | Calls `worker.start_grabbing()` / `stop_grabbing()` |
| `on_frame_ready(frame, t, count)` | Receives live frames; throttles display to ≤30 fps |
| `on_averaged_frame_ready(avg, count)` | Receives averaged frames from consumer |
| `on_begin_saving()` | Calls `consumer.start_saving(N)` |
| `on_saturation(is_sat, max_val)` | Shows/hides red saturation warning |
| `eventFilter()` | Captures mouse hover over both image panels for pixel coordinate display |
| `_slider_to_exposure()` / `_exposure_to_slider()` | Piecewise linear/log conversion for exposure slider |
| `_calculate_fps()` | Rolling 10-frame window FPS estimate |
| `save_config()` / `load_config()` | Persist all state properties to JSON via `state.get_config()` / `state.load_config()` |

### Producer-consumer pattern

```
CameraWorker (producer)
    │  camera.RetrieveResult() → frame
    ├──→ frame_queue.put_nowait(frame)   ← consumed by CameraConsumer
    └──→ frame_ready.emit(frame)         ← display in app (throttled)

CameraConsumer (consumer)
    │  frame_queue.get(timeout=0.1) → accumulate
    │  when N frames accumulated:
    ├──→ averaged_frame_ready.emit(avg)  ← display in app
    └──→ _save_to_disk() if saving
```

Queue size is capped at 30 frames. If the consumer falls behind, frames are dropped silently (never blocks the producer).

### Exposure slider mapping

The slider range 0–400 maps to 0–100,000 µs via piecewise function:
- Slider 0–100 → exposure 0–100 µs (linear, 1:1)
- Slider 100–400 → exposure 100–100,000 µs (log: `exposure = 10^((slider+100)/100)`)

Key points: slider=200 → 1,000 µs; slider=300 → 10,000 µs; slider=400 → 100,000 µs.

### Saturation detection

In **Average** binning mode: saturation threshold is the nominal max for the pixel format (4095 for Mono12, 255 for Mono8). Warning fires when `max_pixel >= threshold * 0.98`.

In **Sum** binning mode: the camera outputs uint16 regardless of pixel format (values can exceed the nominal bit-depth), so the threshold uses `np.iinfo(frame.dtype).max` (65535 for uint16).

### Camera state properties (key ones)

| Property | Default | Description |
|----------|---------|-------------|
| `camera_serial_number` | `"23049069"` | Basler serial number |
| `camera_exposure_us` | `10000.0` | Exposure in microseconds |
| `camera_binning_x/y` | `1` | Hardware binning factor |
| `camera_binning_mode` | `"Average"` | `"Average"` or `"Sum"` |
| `camera_pixel_format` | `"Mono12"` | `"Mono8"`, `"Mono12"`, `"Mono12p"` |
| `camera_num_frames_to_average` | `100` | Frames per averaged image |
| `camera_save_dir` | `E:\MTB project\CW ODMR` | Root save directory |
| `camera_save_format` | `"npy"` | `"npy"`, `"tiff"`, `"jpg"` |

---

## 6. Multi-App Launcher

**File:** `launch_all_apps.py`
**Class:** `AppLauncher`

Launches all three apps under a **single `QApplication`** instance (required by Qt — only one `QApplication` can exist per process). The laser power monitor and PID controller share one `ExperimentState` instance; the camera app gets its own `CameraState`.

### Shared state

```python
self.shared_state = ExperimentState()
self.laser_power_app = LaserPowerMonitor(state=self.shared_state)
self.pid_control_app = PIDControlApp(state=self.shared_state)
# Camera uses separate CameraState — different hardware, different signals
```

### Cross-app communication (optional)

`AppLauncher.connect_apps()` is defined but not called by default. Uncomment the call in `main()` to enable it. Example connections already defined:
- `state.laser_power_updated` → `pid_control_app.log_message()`
- `state.output_changed` → (stub, no action)

To add your own cross-app connection, add signal/slot connections inside `connect_apps()`.

### Window positions (default)

| App | x | y | w | h |
|-----|---|---|---|---|
| Laser Power | 50 | 50 | 480 | 800 |
| PID Control | 550 | 50 | 480 | 800 |
| Camera | 1050 | 50 | 1400 | 900 |

Change the `setGeometry()` calls in `AppLauncher.launch_*()` methods to adjust.

---

## 7. State Objects

### ExperimentState (`state/experiment_state.py`)

Shared by `laser_power_app` and `pid_control_app`. Contains two groups of properties:

**Laser / DAQ properties** — used by `LaserPowerMonitor` and `DAQWorker`:

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `daq_device` | str | `"Dev3"` | NI-DAQ device name |
| `daq_channel` | str | `"ai0"` | Analog input channel |
| `sample_rate` | float | `2.0` | Acquisition rate (Hz) |
| `batch_size` | int | `1` | Samples per read call |
| `voltage_range` | tuple | `(-10, 10)` | DAQ input range (V) |
| `conversion_slope` | float | `0.9527` | V→W slope |
| `conversion_intercept` | float | `0.0036` | V→W intercept |
| `is_acquiring` | bool | `False` | Acquisition running |
| `is_paused` | bool | `False` | Acquisition paused |
| `save_data` | bool | `False` | Auto-save on stop |
| `save_dir` | str | `E:\MTB...` | Save directory |

**Key signals (laser)**:

| Signal | Args | Emitted when |
|--------|------|-------------|
| `laser_power_updated` | `(float, float)` | New power measurement |
| `data_point_recorded` | `(dict)` | Same; used by `RealTimeGraph` |
| `laser_acquisition_started` | — | `is_acquiring` set True |
| `laser_acquisition_stopped` | — | `is_acquiring` set False |
| `daq_config_changed` | `(dict)` | Any DAQ setting changes |

**PID properties and signals** — listed in full in [Section 4](#4-app-pid-controller).

### CameraState (`state/camera_state.py`)

Used exclusively by `camera_app`, `camera_worker`, and `camera_consumer`. See [Section 5](#5-app-basler-camera) for property table.

**Key signals**:

| Signal | Args | Emitted when |
|--------|------|-------------|
| `camera_connection_changed` | `(bool, str)` | Camera connected/disconnected |
| `camera_streaming_changed` | `(bool)` | Streaming started/stopped |
| `camera_frame_acquired` | `(ndarray, int)` | New raw frame (not used by app, available for extension) |
| `camera_averaged_frame_ready` | `(ndarray, int)` | New averaged frame |
| `camera_saturation_detected` | `(bool, float)` | Saturation state changed |
| `camera_save_progress` | `(int, int)` | Save progress update |
| `camera_save_completed` | `(str)` | Save finished |

### PIDState (`state/pid_state.py`)

**Deprecated** — kept for reference only. PID parameters were consolidated into `ExperimentState` (with `pid_` prefix) to allow sharing with the laser power app. Do not use `PIDState` in new code.

---

## 8. Worker Threads

All workers are `QThread` subclasses. Key rules:
- **Never** call UI methods from a worker — only emit signals.
- **Never** create Qt widgets in a worker thread.
- Hardware calls go in `run()` or methods called from `run()`.

### DAQWorker (`workers/daq_worker.py`)

Reads from a single NI-DAQ analog input channel continuously. Falls back to simulation (sine wave + noise) if `nidaqmx` is not installed.

```
__init__(state)         ← takes ExperimentState
run()                   ← calls _run_hardware() or _run_simulation()
pause() / resume()      ← non-blocking, checked in acquisition loop
stop()                  ← sets _stop_requested = True
```

**Emits:**
- `data_acquired(float, float, float)` — (timestamp, voltage, power)
- `acquisition_error(str)`
- `acquisition_finished()`

### PIDWorker (`workers/pid_worker.py`)

Connects to SIM900 → SIM960, processes a command queue, optionally polls monitoring data.

```
__init__(state)                    ← takes ExperimentState
run()                              ← connects hardware, enters command loop
queue_command(command, *args)      ← thread-safe command submission
start_monitoring(interval)
stop_monitoring()
stop()
```

**Supported commands** (passed as strings to `queue_command()`):

| Command | Arg | Hardware call |
|---------|-----|---------------|
| `'set_setpoint'` | float | `sim960.set_setpoint()` |
| `'set_offset'` | float | `sim960.set_offset()` |
| `'set_p_gain'` | float | `sim960.set_proportional_gain()` |
| `'set_i_time'` | float | `sim960.set_integral_time()` |
| `'set_d_time'` | float | `sim960.set_derivative_time()` |
| `'set_upper_limit'` | float | `sim960.set_upper_limit()` |
| `'set_lower_limit'` | float | `sim960.set_lower_limit()` |
| `'set_manual_mode'` | bool | `sim960.set_manual_mode()` |
| `'set_manual_output'` | float | `sim960.set_manual_output()` |
| `'set_p_control'` | bool | `sim960.set_p_control()` |
| `'set_i_control'` | bool | `sim960.set_i_control()` |
| `'set_d_control'` | bool | `sim960.set_d_control()` |
| `'refresh_status'` | — | `sim960.get_status()` |

**Emits:**
- `connection_established(dict)` — initial hardware status dict
- `connection_failed(str)` — error message
- `status_updated(dict)` — from `refresh_status`
- `parameter_set_success(str, object)` — (param_name, value)
- `parameter_set_failed(str, str)` — (param_name, error_msg)
- `monitoring_data(float, float, float, float)` — (timestamp, output, error, setpoint)

### CameraWorker (`workers/camera_worker.py`)

Producer thread. Grabs frames from Basler camera via pypylon and puts them in a `queue.Queue`. Also accepts parameter-change commands via its own queue.

```
__init__(state, frame_queue)
run()                          ← connects camera, enters grab loop
start_grabbing()               ← sets _is_grabbing = True
stop_grabbing()                ← stops pypylon grabbing
queue_command(command, *args)  ← for exposure/binning/format changes
stop()
```

**Supported commands:**

| Command | Args | Effect |
|---------|------|--------|
| `'set_exposure'` | float (µs) | `set_exposure_time(camera, us)` |
| `'set_binning'` | int, int, str | `set_binning(camera, x, y, mode)` |
| `'set_pixel_format'` | str | `set_pixel_format(camera, fmt)` |

**Emits:**
- `frame_ready(ndarray, float, int)` — (frame, timestamp, count)
- `connection_established(dict)` — camera settings dict
- `connection_failed(str)`
- `parameter_set_success(str, object)`
- `parameter_set_failed(str, str)`
- `saturation_detected(bool, float)` — (is_saturated, max_pixel_value)

### CameraConsumer (`workers/camera_consumer.py`)

Consumer thread. Reads frames from the shared queue, accumulates N frames, emits averaged result, and handles disk saving.

```
__init__(state, frame_queue)
run()                      ← accumulation loop
start_saving(num_images)   ← triggers save after next N averaged frames
stop_saving()              ← saves partial batch immediately
stop()
```

**Emits:**
- `averaged_frame_ready(ndarray, int)` — (avg_frame, total_avg_count)
- `save_progress(int, int)` — (current, total)
- `save_completed(str)` — completion message with filepath
- `error_occurred(str)`

**Save formats:**
- `.npy` — `np.save()`, lossless, preserves full dtype
- `.tiff` — 16-bit via Pillow (`PIL.Image`) or imageio fallback
- `.jpg` — 8-bit, auto-scaled 0–255, lossy; use only for preview images

---

## 9. Reusable Widgets

### RealTimeGraph (`widgets/real_time_graph.py`)

A drop-in `QWidget` that auto-connects to any `ExperimentState` (or compatible state with `data_point_recorded` signal) and plots incoming values in real time.

**Usage:**
```python
from widgets.real_time_graph import RealTimeGraph

graph = RealTimeGraph(
    state,
    title="Laser Power vs Time",
    y_label="Power (W)",
    time_window=60      # seconds shown in rolling window
)
layout.addWidget(graph)
```

The graph automatically connects to `state.data_point_recorded(dict)` and expects dicts of the form `{'timestamp': float, 'value': float}`.

**If you need to intercept the data** (e.g., for unit conversion), disconnect the auto-connection and connect your own handler:

```python
self.state.data_point_recorded.disconnect(self.graph.on_new_data)
self.state.data_point_recorded.connect(self.my_custom_handler)

def my_custom_handler(self, data):
    converted = {'timestamp': data['timestamp'], 'value': data['value'] * 1000}
    self.graph.on_new_data(converted)
```

**Key methods:**

| Method | Description |
|--------|-------------|
| `clear_data()` | Clears all data and resets start time |
| `set_time_window(seconds)` | Programmatically set rolling window width |
| `set_y_label(label)` | Update Y-axis label text |
| `get_current_data()` | Returns `(x_list, y_list)` copies |
| `export_csv(filename)` | Write current data to CSV |

**Features built in:**
- Enable/disable rolling window checkbox
- Time window spinbox (5 s to 999,999 s)
- Y-axis auto-scale
- X-axis rolling window or auto-range
- No SI prefix auto-scaling (prevents "×0.001" labels)
- Right-click pyqtgraph context menu

---

## 10. Config Files

Config files are plain JSON, stored in `config/`. They are:
- Loaded automatically at app startup (if present)
- Written when the user clicks "Save Configuration as Default"
- Not version-controlled (they hold machine-specific settings)

### `laser_power_config.json` fields

```json
{
  "daq_device": "Dev3",
  "daq_channel": "ai0",
  "sample_rate": 2.0,
  "batch_size": 1,
  "voltage_range_min": -10.0,
  "voltage_range_max": 10.0,
  "conversion_slope": 0.9527,
  "conversion_intercept": 0.0036,
  "save_dir": "E:\\MTB project\\CW ODMR",
  "save_subfolder": "",
  "auto_save": false,
  "append_timestamp": true,
  "max_refresh_rate": 10.0
}
```

### `pid_control_config.json` fields

```json
{
  "com_port": "ASRL3::INSTR",
  "sim900_port": 1,
  "monitor_interval": 0.5
}
```

### `basler_camera_config.json` fields

All fields from `CameraState.get_config()` — see `state/camera_state.py` for the full list. Key ones:

```json
{
  "camera_serial_number": "23049069",
  "camera_exposure_us": 10000.0,
  "camera_binning_x": 1,
  "camera_binning_y": 1,
  "camera_binning_mode": "Average",
  "camera_pixel_format": "Mono12",
  "camera_num_frames_to_average": 100,
  "camera_save_dir": "E:\\MTB project\\CW ODMR",
  "camera_save_format": "npy"
}
```

---

## 11. How to Add a New App

Follow this checklist to add a new instrument control app that integrates cleanly with the existing framework.

### Step 1: Create a state class in `state/`

```python
# state/my_instrument_state.py
from PySide6.QtCore import QObject, Signal

class MyInstrumentState(QObject):
    some_value_changed = Signal(float)

    def __init__(self):
        super().__init__()
        self._some_value = 0.0

    @property
    def some_value(self):
        return self._some_value

    @some_value.setter
    def some_value(self, v):
        self._some_value = float(v)
        self.some_value_changed.emit(self._some_value)
```

### Step 2: Create a worker in `workers/`

```python
# workers/my_instrument_worker.py
import sys
from pathlib import Path
from PySide6.QtCore import QThread, Signal

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
# now you can import qdm_* modules

class MyInstrumentWorker(QThread):
    data_ready = Signal(float)
    error_occurred = Signal(str)

    def __init__(self, state):
        super().__init__()
        self.state = state
        self._running = False

    def run(self):
        self._running = True
        while self._running:
            # ... hardware I/O ...
            self.data_ready.emit(value)

    def stop(self):
        self._running = False
```

### Step 3: Create the app in `GUI/` root

```python
# my_instrument_app.py
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMainWindow
sys.path.insert(0, str(Path(__file__).parent.parent))

from state.my_instrument_state import MyInstrumentState
from workers.my_instrument_worker import MyInstrumentWorker

CONFIG_FILE = Path(__file__).parent / "config" / "my_instrument_config.json"

class MyInstrumentApp(QMainWindow):
    def __init__(self, state=None):
        super().__init__()
        self.state = state if state is not None else MyInstrumentState()
        self.worker = None
        self.init_ui()
        self.connect_signals()
        self.load_config()

    # ... tabs, signals, slots, save/load config ...

    def closeEvent(self, event):
        if self.worker:
            self.worker.stop()
            self.worker.wait()
        event.accept()

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = MyInstrumentApp()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
```

### Step 4: Add launchers

```batch
@echo off
cd /d "%~dp0"
python my_instrument_app.py
if %ERRORLEVEL% NEQ 0 ( echo ERROR: %ERRORLEVEL% & pause )
```

```vbs
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c cd /d """ & CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName) & """ && python my_instrument_app.py", 0, False
```

### Step 5: Add to `launch_all_apps.py` (optional)

Add your app to `AppLauncher.__init__()` and create a `launch_my_instrument()` method following the same pattern as the existing ones. Call it from `main()`.

---

## 12. How to Add a New Feature to an Existing App

### Adding a new parameter to the PID app

1. Add a property + signal to `ExperimentState` following the existing `pid_*` pattern
2. Add a UI widget (spinbox etc.) in `PIDControlApp.create_control_tab()`
3. Add a slot handler `on_set_my_param()` that calls `self.worker.queue_command('set_my_param', value)`
4. Add the command handler in `PIDWorker._execute_command()`: `elif command == 'set_my_param': ...`
5. Add UI update slot `on_my_param_updated(value)` and connect it in `connect_signals()`
6. Optionally add it to auto-apply in `connect_auto_apply()`

### Adding a new camera parameter

1. Add property + signal to `CameraState`
2. Add UI control in `BaslerCameraApp.create_camera_controls()`
3. Add slot that calls `self.worker.queue_command('set_my_param', value)`
4. Add command handler in `CameraWorker._process_commands()`
5. Add to `CameraState.get_config()` and `load_config()` for persistence

### Adding a new plot to any app

```python
from widgets.real_time_graph import RealTimeGraph

# In __init__ or tab creation:
self.my_graph = RealTimeGraph(self.state, title="My Data", y_label="Units", time_window=120)
layout.addWidget(self.my_graph)

# To feed data manually (bypassing data_point_recorded):
self.my_graph.on_new_data({'timestamp': t, 'value': v})
```

---

## 13. Common Pitfalls

### "RuntimeError: super().__init__ not called from QThread.run()"
You called a Qt UI method from a worker thread. Workers must only emit signals — never call `.setText()`, `.append()`, etc. directly.

### App freezes when connecting to hardware
Hardware I/O (serial, network, DAQ) is happening in the main thread. Move it to a worker. The connection should happen inside `worker.run()`, not before `worker.start()`.

### Config file not found on first run
That is expected — `load_config()` checks `CONFIG_FILE.exists()` and silently uses defaults. The file is created the first time the user clicks "Save Configuration as Default".

### Imports failing when running from wrong directory
All apps must be run from `GUI/`. The `.bat` launchers handle this with `cd /d "%~dp0"`. If running from a terminal, `cd` to `GUI/` first.

### `from state.X` fails inside a worker
Workers live in `GUI/workers/`, one level deeper. They use `sys.path.insert(0, str(Path(__file__).parent.parent.parent))` to reach `ODMR code v2/`, and import qdm modules from there. They do **not** import state/widget modules — state is passed in via `__init__(self, state)`.

### Circular signal connection
`RealTimeGraph` auto-connects to `state.data_point_recorded` in its `__init__`. If you want to intercept and transform the data before it reaches the graph (e.g., unit conversion), disconnect the default connection immediately after constructing the graph:
```python
self.state.data_point_recorded.disconnect(self.graph.on_new_data)
self.state.data_point_recorded.connect(self.my_handler)
```

### Adding a PID monitor interval change doesn't take effect immediately
`PIDWorker._do_monitoring_update()` sleeps for `self.state.pid_monitor_interval` at the end of each poll. A change to the state value takes effect on the next iteration — there is no need to restart the worker.
