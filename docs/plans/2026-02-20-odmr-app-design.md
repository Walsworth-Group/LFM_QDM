# ODMR App Design Document
**Date:** 2026-02-20
**Status:** Approved
**Scope:** PySide6 GUI for CW ODMR widefield magnetometry (4-point multi-inflection point)

---

## Overview

A modular PySide6 application (`GUI/odmr_app/`) that converts the 4-point differential
magnetometry workflow from `Camera ODMR-new.ipynb` into a full GUI. This app is the
template for future instrument control apps in this lab.

The app runs alongside the existing `laser_power_app.py` and `pid_control_app.py` via the
shared `launch_all_apps.py` launcher, sharing `ExperimentState` for cross-app laser/PID
data. It can also run fully standalone.

---

## 1. Directory Structure

```
GUI/odmr_app/
├── odmr_app.py                  # Entry point: python odmr_app.py
├── odmr_main_window.py          # Main QMainWindow logic, menu bar, persistent panels
│
├── state/
│   └── odmr_state.py            # ODMRAppState (QObject + signals)
│
├── workers/
│   ├── sg384_worker.py          # MW generator: idle polling, manual control
│   ├── odmr_sweep_worker.py     # Two-transition ODMR sweep, per-sweep emission
│   └── magnetometry_worker.py   # Multi-point stability loop, per-sample progress
│
├── widgets/
│   ├── inflection_table.py      # Custom QTableWidget: 8 rows × (freq, slope, ✓, parity)
│   └── field_map_display.py     # 3-panel field map widget (raw/denoised/processed)
│
├── ui/                          # Qt Designer source files (committed to git)
│   ├── odmr_app_main.ui         # QMainWindow shell + QTabWidget + persistent panels
│   ├── camera_tab.ui
│   ├── odmr_sweep_tab.ui
│   ├── magnetometry_tab.ui
│   ├── analysis_tab.ui
│   ├── sensitivity_tab.ui
│   └── settings_tab.ui
│
├── config/
│   ├── odmr_app_config.json     # Full app state (auto-saved, File > Save Config)
│   └── presets/
│       └── default.json         # Default index/parity preset
│
└── docs/
    └── ODMR_APP_README.md
```

### Import conventions
- App/widgets: `from state.odmr_state import ODMRAppState`, `from workers.sg384_worker import SG384Worker`
- Workers reach project root: `sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))`
- App reaches project root: `sys.path.insert(0, str(Path(__file__).parent.parent.parent))`

### Qt Designer workflow
- `ui/*.ui` files are the source of truth for layout (committed to git)
- Generate Python: `pyside6-uic ui/odmr_sweep_tab.ui -o ui_odmr_sweep_tab.py` (never edit generated files)
- `odmr_main_window.py` and tab classes own all callbacks — safe from regeneration
- One `.ui` file per tab + one for the main window shell

---

## 2. Tab Layout

Six tabs in a `QTabWidget`:

| Tab | Purpose |
|-----|---------|
| **Camera** | Optical-only mode — embeds existing CameraWorker/CameraConsumer/CameraState unchanged |
| **ODMR Sweep** | Frequency ranges, steps, sweeps; live per-sweep spectrum; Lorentzian fit; inflection summary |
| **Magnetometry** | Index/parity table + presets; spatial binning; N samples; live cumulative field map |
| **Analysis** | 3-panel field map (raw/denoised/processed); reanalysis controls; save |
| **Sensitivity** | Sensitivity map + Allan deviation; inputs for time/slope overrides |
| **Settings** | Instrument addresses, camera serial, amplitude; performance/timing parameters |

---

## 3. Persistent Elements (outside tab widget)

### RF Control Panel (top bar, always visible)
```
[ SG384 ● Connected ]  Freq: 2.870 000 GHz  [ 2.870000 ▲▼ GHz ] [Set]  Amp: -10.0 dBm
```
- Green/red connection indicator
- Live frequency readout — updates from `rf_frequency_changed` signal:
  - When idle: SG384Worker polls every `perf_rf_poll_interval_s` (default 0.5 s), no extra VISA calls
  - During sweep/measurement: sweep worker emits `rf_frequency_changed` at each step (zero extra cost)
- Direct frequency input + [Set] button — **disabled** when `sweep_is_running` or `mag_is_running`
- Amplitude shown as read-only label (set in Settings tab)

### Persistent Save Bar (bottom, always visible)
```
Base path: [ E:\MTB project\CW ODMR            ] [Browse]
Subfolder: [ 2026-02-20_bacteria               ]   [✓] Timestamp on files
[ Save All Plots & Data ]
```
"Save All" triggers each tab's individual save buttons in sequence using each tab's own prefix.
Base path and subfolder are persisted in app config.

### File Menu
```
File
  Save Config          Ctrl+S   → full app state to odmr_app_config.json
  Save Config As…               → save to user-specified .json file
  Load Config…                  → restore full app state from .json
  ─────────────────
  Reset to Defaults
```
Config covers: all `perf_*` settings, instrument addresses, save path/subfolder, current
inflection table state (frequencies, slopes, contrasts, selected indices/parities, preset
name), binning values, tab-specific save prefixes. Sufficient to fully restore after a crash.

---

## 4. State Architecture — `ODMRAppState`

Central QObject, single source of truth. Holds a reference to `ExperimentState` (shared
with laser/PID apps) rather than inheriting from it.

```python
class ODMRAppState(QObject):

    # --- RF / MW generator ---
    rf_is_connected: bool
    rf_current_freq_ghz: float        # live readout
    rf_amplitude_dbm: float
    rf_address: str                   # VISA/TCP address (from Settings)

    # --- ODMR sweep parameters & results ---
    sweep_freq1_start_ghz: float
    sweep_freq1_end_ghz: float
    sweep_freq1_steps: int
    sweep_freq2_start_ghz: float
    sweep_freq2_end_ghz: float
    sweep_freq2_steps: int
    sweep_ref_freq_ghz: float
    sweep_num_sweeps: int
    sweep_n_lorentz: int              # peaks per transition (default 2)
    sweep_is_running: bool
    sweep_current_sweep: int          # progress counter
    sweep_spectrum1: np.ndarray       # updated after each sweep
    sweep_spectrum2: np.ndarray
    sweep_freqlist1: np.ndarray
    sweep_freqlist2: np.ndarray
    sweep_inflection_result: dict     # full result from identify_multi_transition...

    # --- Magnetometry parameters & results ---
    mag_num_samples: int
    mag_bin_x: int                    # default 1 (no additional software binning)
    mag_bin_y: int                    # default 1
    mag_selected_indices: list
    mag_selected_parities: list
    mag_is_running: bool
    mag_current_sample: int
    mag_stability_result: dict        # stability_cube + full metadata

    # --- Analysis parameters ---
    analysis_denoise_method: str      # 'gaussian', 'tv', 'wavelet', etc.
    analysis_gaussian_sigma: float
    analysis_outlier_sigma: float
    analysis_reference_mode: str      # 'global_mean'
    analysis_field_map_result: dict   # output of analyze_multi_point_magnetometry

    # --- Camera mode (mutual exclusion) ---
    odmr_camera_mode: CameraMode      # IDLE / STREAMING / ACQUIRING
    odmr_camera_serial: str           # serial number for ODMR camera

    # --- Save settings ---
    save_base_path: str
    save_subfolder: str
    save_timestamp_enabled: bool
    save_prefix_sweep: str            # default '' (filename: odmr_freq_sweep_[ts].npz)
    save_prefix_magnetometry: str     # default ''
    save_prefix_field_map: str        # default ''
    save_prefix_sensitivity: str      # default ''

    # --- Performance / timing ---
    perf_rf_poll_interval_s: float    # default 0.5
    perf_ui_plot_throttle_fps: float  # default 10
    perf_mw_settling_time_s: float    # default 0.010
    perf_camera_flush_frames: int     # default 1
    perf_n_frames_per_point: int      # default 5
    perf_worker_loop_sleep_s: float   # default 0.005
    perf_sweep_emit_every_n: int      # default 1
    perf_live_avg_update_interval_samples: int  # default 10

    # --- Shared hardware (lock-protected) ---
    sg384_controller: SG384Controller | None
    sg384_lock: threading.Lock

    # --- Reference to shared cross-app state ---
    shared_state: ExperimentState | None

    # --- CameraState (private to ODMR app) ---
    camera_state: CameraState
```

### Key signals

```python
# RF
rf_connection_changed = Signal(bool)
rf_frequency_changed = Signal(float)       # GHz

# Sweep
sweep_running_changed = Signal(bool)       # disables RF direct-control
sweep_progress = Signal(int, int)          # (current_sweep, total_sweeps)
sweep_spectrum_updated = Signal(           # per-sweep live plot update
    np.ndarray, np.ndarray,               # freqlist1, spectrum1
    np.ndarray, np.ndarray,               # freqlist2, spectrum2
    int)                                  # sweep_num
sweep_completed = Signal(dict)             # inflection result dict

# Magnetometry
mag_running_changed = Signal(bool)
mag_progress = Signal(int, int)            # (current_sample, total_samples)
mag_sample_acquired = Signal(int, np.ndarray)  # (sample_idx, cumulative_avg_gauss)
mag_completed = Signal(dict)               # stability result dict + metadata

# Analysis
analysis_completed = Signal(dict)          # field map result dict

# Camera mode
camera_mode_changed = Signal(str)          # 'idle' / 'streaming' / 'acquiring'
```

---

## 5. Worker Architecture

### Architecture principle
`ODMRSweepWorker` and `MagnetometryWorker` call `sg384_controller` and camera methods
**directly** (not via command queue) for zero-overhead hardware control — identical
throughput to the notebook. `SG384Worker` is paused during acquisitions via a
`threading.Event` flag to avoid bus contention. No extra VISA latency on the critical path.

### `SG384Worker`
- Owns idle monitoring: polls `sg384_controller.get_frequency()` every `perf_rf_poll_interval_s`
- Accepts queued commands for manual control: `'set_frequency'`, `'set_amplitude'`
- Pauses polling when `sg384_lock` is held by sweep/magnetometry worker
- Wraps existing `SG384Controller` from `qdm_srs.py` — no new VISA logic
- Signals: `connected(dict)`, `connection_failed(str)`, `frequency_changed(float)`,
  `parameter_set_success(str, object)`, `error(str)`

### `ODMRSweepWorker`
- Acquires `sg384_lock` at start (pauses SG384Worker polling)
- Calls existing `qdm_gen` internals (`run_hardware_sweep`, `measure_odmr_point`) directly
- Emits `spectrum_updated(...)` after every `perf_sweep_emit_every_n` complete sweeps
- Emits `rf_frequency_changed(freq)` at each frequency step (drives persistent RF display)
- On `stop()`: finishes current frequency point cleanly, then exits
- Releases `sg384_lock` on completion or error → SG384Worker polling resumes
- Signals: `sweep_progress(int,int)`, `spectrum_updated(...)`, `sweep_completed(dict)`,
  `sweep_failed(str)`

### `MagnetometryWorker`
- Acquires `sg384_lock` at start
- Calls `measure_multi_point()` from `qdm_gen.py` each iteration
- Maintains running sum array; every `perf_live_avg_update_interval_samples` samples
  emits `mag_sample_acquired(n, cumulative_avg_gauss)` for live preview
- Autosaves partial stability cube every `perf_autosave_interval_samples` samples
  (prevents data loss on crash/interrupt)
- On `stop()`: completes current sample, saves partial results, emits `mag_completed`
  with whatever was acquired (partial data is useful)
- All metadata bundled into result dict and saved to `.npz` alongside the cube
- Signals: `mag_progress(int,int)`, `mag_sample_acquired(int, ndarray)`,
  `mag_completed(dict)`, `mag_failed(str)`

### Worker coordination
```
SG384Worker     always running when RF connected (sg384_lock free)
     │
     ├─ paused ──► ODMRSweepWorker    (holds sg384_lock for entire sweep)
     │                   └── uses camera directly (streaming already stopped)
     │
     └─ paused ──► MagnetometryWorker (holds sg384_lock for entire measurement)
                         └── uses camera directly
```

---

## 6. Camera Integration

### Mutual exclusion (within ODMR app)
```python
class CameraMode(str, Enum):
    IDLE       = "idle"
    STREAMING  = "streaming"   # Camera tab live stream active
    ACQUIRING  = "acquiring"   # Sweep or magnetometry worker owns camera
```

When "Start Sweep" or "Start Measurement" clicked:
1. If `odmr_camera_mode == STREAMING`: call `stop_streaming()`, show status message,
   wait for `camera_streaming_changed(False)` signal
2. Set `odmr_camera_mode = ACQUIRING`, start worker
3. On completion: set `odmr_camera_mode = IDLE`, re-enable streaming button

Camera tab "Start Stream" button is disabled when `odmr_camera_mode == ACQUIRING`.

### Two-camera isolation
- ODMR app Settings: `odmr_camera_serial` (ODMR camera, e.g. `25061217`)
- Standalone `camera_app.py`: separate serial number (monitoring camera)
- Each `CameraWorker` binds to its own serial at construction — Basler SDK handles both
  simultaneously without conflict
- `CameraState` instances are fully private to their respective apps; not shared via
  `ExperimentState`

### Camera tab implementation
`camera_app.py` is refactored to expose a `CameraTabWidget` class (its main content
widget). Both the standalone `camera_app.py` and the ODMR app's Camera tab instantiate
this class. No functional changes to camera behaviour.

---

## 7. Tab-by-Tab UI Details

### ODMR Sweep Tab
**Left panel (~30%):** Transition 1 (start, end, steps), Transition 2 (start, end, steps),
ref freq, num sweeps, peaks/transition, Start/Stop buttons, progress bar + time estimate.

**Right panel (~70%):** Two pyqtgraph plots side-by-side (one per transition), updating
after every `perf_sweep_emit_every_n` sweeps. Fitted Lorentzians overlaid when complete.
Inflection points marked with vertical lines.

**Bottom:** Read-only inflection point summary table (8 rows × freq/slope/contrast columns).
"Send to Magnetometry →" button (enabled after sweep completes).

**Save row:**
```
User prefix: [ run1           ]  odmr_freq_sweep_[timestamp]   [ Save .npz ]  [ Save .png ]
```
Saves: `freqlist1/2`, `spectrum1/2`, fit params, inflection points, full metadata.

---

### Magnetometry Tab
**Left panel (~35%):**

*Inflection point selection table (8 rows):*
| # | Freq (GHz) | Slope (GHz⁻¹) | Use? | Parity | Role |
|---|-----------|--------------|------|--------|------|
| 1 | 2.519520 *(editable)* | -15.5899 | ☑ | +1 ▼ | Signal |
| … | … | … | … | … | … |

Freq column is directly editable (user can override sweep result).

*Preset controls:*
```
Preset:  [ default_4pt ▼ ] [Load] [Save As…] [Delete]
Points:  [ Load from file… ]  [ Save points to file… ]
```
Presets store: selected indices, parities, ref_freq, description string.
Point files store: full 8-point arrays (freq, slope, contrast) for session restore.

*Measurement parameters:*
```
Ref freq: [1.0] GHz
Spatial binning (software): bin_x [1] bin_y [1]   (1 = no extra binning)
Samples (N): [200]
Live preview every: [10] samples
[ Start Measurement ]  [ Stop ]
████████░░░░░░ 120/200 samples   Est. remaining: 0h 4m 12s
```

**Right panel (~65%):** Live pyqtgraph ImageView showing cumulative average field map
(Gauss, RdBu_r colormap), updating every `perf_live_avg_update_interval_samples` samples.
Pixel value on hover.

**Save row:**
```
User prefix: [ run1           ]  multipoint_stability_[timestamp]   [ Save .npz ]  [ Save .png ]
```

---

### Analysis Tab
**Top:** Three pyqtgraph ImageView panels side-by-side:
`[Raw (mean)]` · `[Denoised]` · `[Processed (Raw − Denoised)]`
Each: RdBu_r colormap, colorbar, pixel B-value on hover.
Main result is Processed; Raw and Denoised are smaller flanking panels.

**Bottom:**
```
Denoise method: [ gaussian ▼ ]   σ: [15.0]    Outlier: [4.0] σ    Ref: [global_mean ▼]
[ Reanalyze ]

Stats:  Mean: +0.0012 G    Std: 0.0087 G    Range: [−0.031, +0.031] G
```
```
User prefix: [ run1           ]  field_map_[timestamp]   [ Save .npz ]  [ Save .png ]
```

---

### Sensitivity Tab
**Top two panels:** Sensitivity map (µT/√Hz, ImageView) + Allan deviation plot
(pyqtgraph PlotWidget, measured OADEV vs. shot-noise limit).

**Bottom:**
```
Time/point override: [auto] s    Slope override: [auto] GHz⁻¹
[ Run Sensitivity Analysis ]    [ Run Allan Variance ]
Mean sensitivity: 87 µT/√Hz    Shot-noise limit: 42 µT/√Hz
```
```
User prefix: [ run1           ]  sensitivity_[timestamp]   [ Save .npz ]  [ Save .png ]
```

---

### Settings Tab
```
┌─ Instrument ────────────────────────────────────────────────┐
│ SG384 VISA/TCP address:  [ 192.168.1.100               ]    │
│ ODMR camera serial:      [ 25061217                    ]    │
│ SG384 amplitude (dBm):   [ -10.0                       ]    │
└─────────────────────────────────────────────────────────────┘

┌─ Performance / Timing  ▼ (collapsible) ─────────────────────┐
│ RF poll interval (idle):          [0.5  ] s                 │
│ MW settling time per freq step:   [0.010] s                 │
│ Camera flush frames after step:   [1    ]                   │
│ Frames averaged per meas. point:  [5    ]                   │
│ Worker loop sleep:                [0.005] s                 │
│ Spectrum plot emit every N sweeps:[1    ]                   │
│ Live avg update every N samples:  [10   ]                   │
│ Autosave stability cube every N:  [50   ] samples           │
└─────────────────────────────────────────────────────────────┘

[ Reset to Defaults ]
```
Config save/load is in the File menu, not here.

---

## 8. Data Saving Conventions

### Filename pattern
```
{user_prefix}_{component_name}_{YYYYMMDD_HHMMSS}.ext
```
- User prefix is optional (blank → component name only)
- Component names: `odmr_freq_sweep`, `multipoint_stability`, `field_map`, `sensitivity`
- Example: `run1_odmr_freq_sweep_20260220_143022.npz`
- Files from the same run sort together in Windows Explorer when prefix is consistent

### Metadata dict (included in all `.npz` saves)
```python
metadata = {
    # Instrument
    'sg384_address': str,
    'sg384_amplitude_dbm': float,
    'camera_serial': str,
    'camera_exposure_us': float,
    'camera_hw_binning': int,
    # Sweep parameters
    'sweep_freq1_start_ghz': float, 'sweep_freq1_end_ghz': float,
    'sweep_freq1_steps': int,
    'sweep_freq2_start_ghz': float, 'sweep_freq2_end_ghz': float,
    'sweep_freq2_steps': int,
    'sweep_ref_freq_ghz': float,
    'sweep_num_sweeps': int,
    # Inflection points (always saved with magnetometry data)
    'inflection_points_ghz': list,   # 8 frequencies
    'inflection_slopes_ghz_inv': list,
    'inflection_contrasts': list,
    'selected_indices': list,
    'selected_parities': list,
    'preset_name': str,
    # Magnetometry
    'num_samples': int,
    'mag_bin_x': int, 'mag_bin_y': int,
    'freq_list_ghz': list,
    'slope_list_ghz_inv': list,
    'baseline_list': list,
    # Performance at time of acquisition
    'perf_mw_settling_time_s': float,
    'perf_n_frames_per_point': int,
    'perf_camera_flush_frames': int,
    # Timestamps
    'sweep_timestamp': str,
    'measurement_timestamp': str,
    # Optional (if shared_state connected)
    'laser_power_mw_at_start': float,
}
```

### Preset files (`config/presets/*.json`)
```json
{
  "name": "default_4pt",
  "description": "Outer four inflection points, alternating parity",
  "selected_indices": [1, 4, 0, 5, 8, 0],
  "selected_parities": [1, 1, 0, -1, -1, 0],
  "ref_freq_ghz": 1.0
}
```

### Inflection point export files
Full 8-point arrays (freq, slope, contrast) saved as `.json` for session restore without re-running sweep.

---

## 9. Integration with `launch_all_apps.py`

```python
# Extended launcher — existing apps unchanged, ODMR app added
shared_state = ExperimentState()        # laser/PID shared state
odmr_state = ODMRAppState(shared_state=shared_state)

laser_app = LaserPowerMonitor(state=shared_state)
pid_app = PIDControlApp(state=shared_state)
odmr_app = ODMRMainWindow(odmr_state=odmr_state)

# odmr_app reads shared_state.laser_power_mw and logs to metadata automatically
```

`ODMRMainWindow` accepts `odmr_state=None` to auto-create its own state → runs standalone:
```bash
python GUI/odmr_app/odmr_app.py
```

---

## 10. Existing Code Reuse

All existing functions are called without modification:

| Existing function | Called by |
|------------------|-----------|
| `qdm_gen.run_hardware_sweep()` | `ODMRSweepWorker` |
| `qdm_gen.measure_odmr_point()` | `ODMRSweepWorker` |
| `qdm_gen.fit_global_odmr()` | `ODMRSweepWorker` (post-sweep fit) |
| `qdm_gen.format_multi_point_frequencies()` | Magnetometry tab logic |
| `qdm_gen.measure_multi_point()` | `MagnetometryWorker` |
| `qdm_gen.analyze_multi_point_magnetometry()` | Analysis tab logic |
| `qdm_gen.analyze_stability_data()` | Sensitivity tab logic |
| `qdm_gen.analyze_allan_variance()` | Sensitivity tab logic |
| `qdm_srs.SG384Controller` | `SG384Worker` + sweep/mag workers (shared instance) |
| `qdm_basler.basler` | `CameraWorker` (unchanged) |
| `GUI/workers/camera_worker.py` | Camera tab (unchanged) |
| `GUI/workers/camera_consumer.py` | Camera tab (unchanged) |
| `GUI/state/camera_state.py` | Camera tab (unchanged) |

---

## 11. Decisions Not Made Here (for implementation planning)

- Exact pyqtgraph widget configuration (colormaps, axis labels, range defaults)
- Error dialog / status bar message formatting details
- Exact `.ui` file widget hierarchy (handled in Qt Designer during implementation)
- Unit tests strategy
- Whether to add a background subtraction workflow (`analyze_background_subtraction`)
  to the Analysis tab in a future iteration
