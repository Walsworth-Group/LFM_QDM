# ODMR Magnetometry GUI App

PySide6 application for CW ODMR widefield magnetometry with NV centers. Implements the full 4-point differential magnetometry workflow (ODMR frequency sweep → inflection point identification → multi-point stability measurement → field map analysis → sensitivity/Allan variance).

---

## Launching

| Method | Command / File |
|---|---|
| Standalone (with console) | `cd GUI && python odmr_app/odmr_app.py` |
| Standalone (no console) | Double-click `GUI/launch_odmr_silent.vbs` |
| All apps together | `cd GUI && python launch_all_apps.py` |
| All apps (no console) | Double-click `GUI/launch_all_silent.vbs` |

---

## Architecture

The app follows a three-layer pattern: **State → Workers → UI**

```
ODMRAppState (QObject)           ← central source of truth; Qt signals on every change
    ├── SG384Worker (QThread)    ← polls RF frequency; accepts queued commands
    ├── ODMRSweepWorker (QThread)← runs both-transition ODMR sweep; fits Lorentzians
    └── MagnetometryWorker (QThread) ← runs multi-point stability measurement
```

All hardware access is serialized via `state.sg384_lock` (threading.Lock). Workers acquire the lock before touching the SG384 controller; the RF polling worker backs off non-blockingly when the lock is held.

### File structure

```
GUI/odmr_app/
├── odmr_app.py              Entry point (standalone + launcher)
├── odmr_main_window.py      QMainWindow: RF panel, tabs, save bar, file menu
├── state/
│   └── odmr_state.py        ODMRAppState — all signals, properties, config I/O
├── workers/
│   ├── sg384_worker.py      SG384Worker — RF polling and command queue
│   ├── odmr_sweep_worker.py ODMRSweepWorker — two-transition ODMR sweep
│   ├── magnetometry_worker.py MagnetometryWorker — multi-point acquisition
│   └── analysis_worker.py   AnalysisWorker — background field-map analysis (non-blocking)
├── tabs/
│   ├── settings_tab.py      SettingsTabHandler — instrument + perf parameters
│   ├── sweep_tab.py         SweepTabHandler — live spectra, inflection table
│   ├── magnetometry_tab.py  MagnetometryTabHandler — presets, live field preview
│   ├── analysis_tab.py      AnalysisTabHandler — 3-panel field map + reanalysis
│   └── sensitivity_tab.py   SensitivityTabHandler — sensitivity map + Allan dev
├── widgets/
│   ├── inflection_table.py  InflectionTableWidget — 8-row editable inflection table
│   └── field_map_display.py FieldMapDisplayWidget — 3-panel pyqtgraph RdBu_r display
├── ui/
│   ├── odmr_app_main.ui + ui_odmr_app_main.py
│   ├── odmr_sweep_tab.ui + ui_odmr_sweep_tab.py
│   ├── odmr_magnetometry_tab.ui + ui_odmr_magnetometry_tab.py
│   ├── odmr_analysis_tab.ui + ui_odmr_analysis_tab.py
│   ├── odmr_sensitivity_tab.ui + ui_odmr_sensitivity_tab.py
│   └── odmr_settings_tab.ui + ui_odmr_settings_tab.py
├── config/
│   ├── odmr_app_config.json     Auto-saved settings (created on first run)
│   └── presets/
│       └── default_4pt.json     Built-in 4-point differential preset
└── tests/
    ├── test_odmr_state.py
    ├── test_sg384_worker.py
    ├── test_odmr_sweep_worker.py
    ├── test_magnetometry_worker.py
    ├── test_inflection_table.py
    ├── test_field_map_display.py
    ├── test_smoke.py              Startup/import smoke tests (no hardware, <2s)
    ├── test_gui_integration.py   pytest-qt button-click tests
    └── run_sweep_and_mag.py      Hardware integration test (requires connected hardware)
```

---

## Tab overview

### Camera tab
Embeds the existing `CameraTabWidget` (from `camera_app.py`) for live Basler camera streaming. Camera streaming is automatically stopped when a sweep or magnetometry run begins, and re-enabled when the run ends.

### ODMR Sweep tab
Runs a two-transition ODMR frequency sweep (`identify_multi_transition_inflection_points` equivalent):
- Configurable frequency range for each NV transition (lower m=0→−1, upper m=0→+1)
- **Sweep-specific camera settings**: exposure time (µs) and frames per point, separate from magnetometry
- Progress bar shows per-frequency-step progress with elapsed and estimated remaining time; Stop button takes effect within one step
- Live spectrum update during acquisition (dark purple dots, black Lorentzian fit overlay)
- After completion: Lorentzian fitting, 8 inflection point extraction, table populated
- "Send to Magnetometry" button: copies sweep camera settings → magnetometry tab and triggers auto-population of inflection table
- Save: `.npz` (raw spectra + inflection data) and `.png` (spectrum plots)

### Magnetometry tab
Runs multi-point differential magnetometry (`run_multi_point_stability_measurement` equivalent):
- **Magnetometry-specific camera settings**: exposure time (µs) and frames per point, independent of sweep settings
- **InflectionTableWidget**: shows all 8 inflection points; user selects which to use and their parity (+1 signal, −1 signal, 0 reference)
- **Preset management**: save/load/delete named presets in `config/presets/*.json`; `default_4pt.json` is included (outer 4 points, alternating parity)
- **Point file I/O**: export/import inflection point data to JSON for session restore
- **Live field map preview** with display mode selector (Raw / Denoised / Processed — all update live every N samples; gaussian_filter on 300×480 array is ~30 ms)
- **Colorbar** with adjustable min/max spinboxes and Auto button on the live preview panel
- **Sw Bin X/Y** displayed as a compact single row (`X / Y`)
- Progress bar shows elapsed and estimated remaining time
- Autosave partial data every N samples to `_magnetometry_partial_autosave.npz`
- Save: `.npz` (stability cube, freq/slope/parity/baseline lists, metadata) and `.png` (preview)

### Analysis tab
Post-processes the stability cube into a magnetic field map (`analyze_multi_point_magnetometry`):
- Auto-runs when magnetometry completes; analysis runs in `AnalysisWorker` (background QThread) — UI stays responsive
- Controls: denoising method (none/gaussian/tv/wavelet/nlm/bilateral), Gaussian sigma, outlier sigma, reference mode (global_mean/roi)
- Three-panel `FieldMapDisplayWidget`: raw | denoised | processed (RdBu_r colormap, symmetric range)
- **Colorbars** on each panel: adjustable min/max spinboxes + Auto button; "Auto Range (All Panels)" button resets all three
- Stats label: mean, std, range of the processed field map
- Save: `.npz` (all three field maps) and `.png` (matplotlib figure)

### Sensitivity tab
Computes magnetometer sensitivity (`analyze_stability_data`) and Allan deviation (`analyze_allan_variance`):
- Optional manual overrides for time-per-point and slope (0.0 = Auto)
- Sensitivity map displayed in µT/√Hz units
- Allan deviation on log-log scale; measured + shot-noise-limit curves
- Save: `.npz` (sensitivity arrays) and `.png` (map + Allan plot)

### Settings tab
Configures instrument and performance parameters:
- SG384 TCP/IP address, RF amplitude
- Camera serial number (ODMR camera)
- Performance: RF poll interval, MW settling time, global frames per point (legacy), worker loop sleep, sweep emit interval, live update interval, autosave interval
- **Note**: Per-operation camera settings (exposure time, frames per point) are now on the Sweep and Magnetometry tabs directly — not in Settings

---

## Workflow (end-to-end)

1. **Connect RF** — Click "Connect RF" in the RF panel; enter SG384 address in Settings first if needed.
2. **ODMR Sweep** — Go to ODMR Sweep tab, set frequency ranges for both NV transitions, click "Start Sweep". Live spectra update; inflection points identified automatically after completion.
3. **Select inflection points** — Switch to Magnetometry tab; inflection table auto-populated. Check rows to use, set parity. Or load a preset.
4. **Run magnetometry** — Click "Start" in Magnetometry tab. Live field map preview updates. Click "Stop" at any time.
5. **Analyze** — Switch to Analysis tab; field map auto-displayed. Adjust denoising, click "Reanalyze" as needed.
6. **Sensitivity** — Switch to Sensitivity tab, click "Compute Sensitivity" then "Allan Deviation".
7. **Save** — Use individual "Save" buttons per tab, or click "Save All" in the bottom bar to save all tabs at once.

---

## File naming convention

All saved files follow the pattern: `{user_prefix}_{component_name}_{YYYYMMDD_HHMMSS}.ext`

- `user_prefix`: optional text entered in each tab's Prefix field
- `component_name`: `odmr_freq_sweep` | `multipoint_stability` | `field_map` | `sensitivity`
- Timestamp can be disabled in the save bar

Files are saved to `{Save Base Path}/{Subfolder}/`.

---

## Simulation mode

When hardware is unavailable, the app generates synthetic NV ODMR data:
- Set `simulation_mode=True` when constructing workers (set internally via `state._simulation_mode`)
- Standalone testing: `state._simulation_mode = True` before starting any worker

---

## Configuration persistence

The app auto-saves all settings to `config/odmr_app_config.json` on close. This file is loaded on startup. Use **File → Save Config As** to save to a different location, or **File → Load Config** to restore a saved session.

---

## ODMRAppState property reference

`state/odmr_state.py` — `ODMRAppState(QObject)`

### Plain attributes (no signal, set directly)

| Attribute | Type | Purpose |
|---|---|---|
| `sg384_controller` | `SG384Controller \| None` | Hardware handle; set to `MagicMock()` in tests |
| `sg384_lock` | `threading.Lock` | Serialize access across RF polling + acquisition workers |
| `camera_state` | `CameraState \| None` | Set by `_embed_camera_tab()` at startup |
| `shared_state` | `ExperimentState \| None` | Shared laser/PID state from launcher |
| `_simulation_mode` | `bool` | Set `True` before starting any worker to use synthetic data |

### Signals

| Signal | Args | Emitted when |
|---|---|---|
| `rf_connection_changed` | `bool` | `rf_is_connected` changes |
| `rf_frequency_changed` | `float` | `rf_current_freq_ghz` changes |
| `sweep_running_changed` | `bool` | `sweep_is_running` changes |
| `sweep_progress` | `int, int` | Each frequency step completes (current, total) |
| `sweep_spectrum_updated` | `object, object, object, object, int` | Live spectrum data (fl1, sp1, fl2, sp2, sweep_num) |
| `sweep_completed` | `dict` | Sweep finishes; dict has `inflection_points`, `inflection_slopes`, `inflection_contrasts`, sweep data |
| `mag_running_changed` | `bool` | `mag_is_running` changes |
| `mag_progress` | `int, int` | Each magnetometry sample (current, total) |
| `mag_sample_acquired` | `int, object` | Live sample (sample_idx, field_map_gauss) |
| `mag_completed` | `dict` | Magnetometry finishes; dict has `stability_cube`, `freq_list`, `slope_list`, etc. |
| `analysis_completed` | `dict` | Field map analysis finishes |
| `camera_mode_changed` | `str` | Camera mode changes; value is `"idle"`, `"streaming"`, or `"acquiring"` — **a string, not a `CameraMode` enum** |
| `mag_camera_settings_pushed` | `int, int` | "Send to Magnetometry" clicked (exposure_us, n_frames) |
| `status_message` | `str` | Any tab emits a short one-line activity message; displayed in the Qt status bar |

### Properties with signals (configurable, persisted in JSON)

**RF**

| Property | Type | Default | Signal |
|---|---|---|---|
| `rf_is_connected` | `bool` | `False` | `rf_connection_changed` |
| `rf_current_freq_ghz` | `float` | `2.870` | `rf_frequency_changed` |
| `rf_amplitude_dbm` | `float` | `-10.0` | — |
| `rf_address` | `str` | `"192.168.1.100"` | — |

**Camera (per-operation)**

| Property | Type | Default |
|---|---|---|
| `sweep_exposure_time_us` | `int` | `10000` |
| `sweep_n_frames_per_point` | `int` | `5` |
| `mag_exposure_time_us` | `int` | `10000` |
| `mag_n_frames_per_point` | `int` | `5` |

**Sweep**

| Property | Type | Default |
|---|---|---|
| `sweep_freq1_start_ghz` | `float` | `2.516` |
| `sweep_freq1_end_ghz` | `float` | `2.528` |
| `sweep_freq1_steps` | `int` | `201` |
| `sweep_freq2_start_ghz` | `float` | `3.210` |
| `sweep_freq2_end_ghz` | `float` | `3.220` |
| `sweep_freq2_steps` | `int` | `201` |
| `sweep_ref_freq_ghz` | `float` | `1.0` |
| `sweep_num_sweeps` | `int` | `1` |
| `sweep_n_lorentz` | `int` | `2` |
| `sweep_is_running` | `bool` | `False` | ← emits `sweep_running_changed` |
| `sweep_inflection_result` | `dict \| None` | `None` | Result from sweep; has `inflection_points` (8,), `inflection_slopes` (8,), `inflection_contrasts` (8,) |

**Magnetometry**

| Property | Type | Default |
|---|---|---|
| `mag_num_samples` | `int` | `200` |
| `mag_bin_x` | `int` | `1` |
| `mag_bin_y` | `int` | `1` |
| `mag_selected_indices` | `list[int]` | `[1,4,0,5,8,0]` | Inflection point indices; 0 = reference |
| `mag_selected_parities` | `list[int]` | `[1,1,0,-1,-1,0]` | +1 signal / -1 inverted / 0 reference |
| `mag_is_running` | `bool` | `False` | ← emits `mag_running_changed` |
| `mag_stability_result` | `dict \| None` | `None` | Result dict from last magnetometry run |

**Analysis**

| Property | Type | Default |
|---|---|---|
| `analysis_denoise_method` | `str` | `"gaussian"` | Options: `"none"`, `"gaussian"`, `"tv"`, `"wavelet"`, `"nlm"`, `"bilateral"` |
| `analysis_gaussian_sigma` | `float` | `15.0` |
| `analysis_outlier_sigma` | `float` | `4.0` |
| `analysis_reference_mode` | `str` | `"global_mean"` |

**Camera mode (ODMR app)**

| Property | Type | Default |
|---|---|---|
| `odmr_camera_mode` | `CameraMode` | `CameraMode.IDLE` | Accepts `CameraMode` enum or string; emits `camera_mode_changed(str)` |
| `odmr_camera_serial` | `str` | `""` |

### Business logic methods

| Method | Returns | Purpose |
|---|---|---|
| `try_start_sweep()` | `bool` | `True` if mag is not running (mutually exclusive) |
| `try_start_magnetometry()` | `bool` | `True` if sweep is not running |
| `build_save_filename(component, prefix, ts)` | `str` | `"{prefix}_{component}_{timestamp}"` filename stem |
| `build_metadata()` | `dict` | All experimental parameters as flat dict for embedding in .npz |
| `get_config()` | `dict` | All persistable properties (for JSON save) |
| `load_config(dict)` | — | Restore from JSON; unknown keys silently ignored |

---

## Running tests

```bash
cd GUI/odmr_app
python -m pytest tests/ -v
```

50 tests across three layers:

| File | Layer | What it covers |
|---|---|---|
| `test_odmr_state.py` | Unit | State signals, config roundtrip, mutual exclusion |
| `test_sg384_worker.py` | Unit | RF polling, lock backoff, command queue |
| `test_odmr_sweep_worker.py` | Unit | Per-step progress, early stop mid-T1, lock acquisition |
| `test_magnetometry_worker.py` | Unit | Progress, partial save on stop, metadata |
| `test_inflection_table.py` | Unit | Table population, selection, preset save/load |
| `test_field_map_display.py` | Unit | Widget create/update/clear, colormap range |
| `test_smoke.py` | Smoke | Import and instantiate all key classes; catches startup crashes |
| `test_gui_integration.py` | Integration | Button clicks → state signals; full sweep in simulation |

All tests use `simulation_mode=True` and `MagicMock` — no hardware contact. Requires `pytest` and `pytest-qt`.

---

## Dependencies

- PySide6 (Qt6 Python bindings)
- pyqtgraph (live plots and image views)
- numpy, scipy (numerical processing)
- qdm_gen, qdm_srs, qdm_basler (project libraries)
- allantools (optional, required for Allan deviation)

---

## Development notes

- **UI files**: `.ui` files in `ui/` are Qt Designer XML sources. Regenerate Python bindings with: `pyside6-uic -g python odmr_sweep_tab.ui -o ui_odmr_sweep_tab.py` (run from `ui/`). Never edit `ui_*.py` files by hand **except** to work around a known `pyside6-uic` bug: if the generated file calls `setContentsMargins(4)` with a single integer, change it to `setContentsMargins(4, 4, 4, 4)` — the single-argument form is not accepted by current PySide6 Python bindings.
- **Adding a new tab**: create a `*TabHandler` class in `tabs/`, add a new tab to `odmr_app_main.ui`, instantiate the handler in `ODMRMainWindow.__init__`, add `save_data()` call in `_on_save_all`.
- **Background workers**: computationally intensive operations (ODMR fitting, field-map analysis) run in `QThread` subclasses so the UI stays responsive. See `AnalysisWorker` for the pattern.
- **Camera tab isolation**: `odmr_main_window.py` uses `sys.modules` management to prevent the `odmr_app/state/` and `odmr_app/workers/` packages from shadowing `GUI/state/` and `GUI/workers/` when importing `camera_app.py`.
