# LFM Microscopy GUI App

PySide6 application for light field microscopy (LFM) 3D reconstruction. Implements the full LFM workflow: camera acquisition, calibration (lenslet detection + PSF computation), iterative deconvolution, and 3D volume visualization. Uses the [pyolaf](https://github.com/pvjosue/pyolaf) library for the reconstruction pipeline.

---

## Launching

| Method | Command / File |
|---|---|
| Standalone (with console) | `cd GUI && python lfm_app/lfm_app.py` |
| All apps together | `cd GUI && python launch_all_apps.py` |

The standalone launcher creates its own `QApplication`. The multi-app launcher shares a single `QApplication` and `ExperimentState` across all windows (laser power, PID, camera, ODMR, LFM).

---

## Prerequisites

### Python packages

```
pip install PySide6 pyqtgraph pypylon tifffile pyyaml scipy scikit-image tqdm
pip install -e pyolaf-main/   # Install pyolaf in editable mode
```

**Note:** PySide6 6.7.3 is known to work with the Anaconda Python 3.11.4 on this machine. PySide6 6.10.x causes DLL load failures with this Python version.

### Optional (GPU acceleration)

```
pip install cupy-cuda11x   # or cupy-cuda12x depending on your CUDA version
```

CuPy enables GPU-accelerated reconstruction (up to 20x speedup). The app falls back to NumPy/SciPy automatically if CuPy is not installed.

### Sample data

Download the fly muscle demo data from the [Google Drive link](https://drive.google.com/drive/folders/1clAUjal3P0a2owQrwGvdpUAoCHYwSecb?usp=share_link) referenced in `pyolaf-main/examples/deconvolve_image.py`. Place the files in:

```
pyolaf-main/examples/fly-muscles-GFP/
    config.yaml       # LFM optical configuration
    calib.tif          # White calibration image (lenslet array illumination)
    example_fly.tif    # Raw LFM image of fly muscles (GFP)
```

The default config (`GUI/lfm_app/config/lfm_app_config.json`) points to this location.

---

## Architecture

The app follows a three-layer pattern: **State -> Workers -> UI**

```
LFMAppState (QObject)               <- central source of truth; Qt signals on every change
    |-- CalibrationWorker (QThread)  <- pyolaf geometry + PSF computation
    +-- ReconstructionWorker (QThread) <- iterative deconvolution
```

Camera hardware access is handled by the embedded `CameraTabWidget` (reused from the standalone camera app) with its own `CameraState`, `CameraWorker`, and `CameraConsumer`.

### File structure

```
GUI/lfm_app/
|-- lfm_app.py              Entry point (standalone + launcher)
|-- lfm_main_window.py      QMainWindow: tabs, menu, status bar, camera embedding
|-- state/
|   +-- lfm_state.py        LFMAppState -- all signals, properties, config I/O
|-- workers/
|   |-- calibration_worker.py   CalibrationWorker -- pyolaf calibration pipeline
|   +-- reconstruction_worker.py ReconstructionWorker -- iterative deconvolution
|-- tabs/
|   |-- calibration_tab.py      CalibrationTabHandler -- file inputs, parameters, overlay
|   |-- reconstruction_tab.py   ReconstructionTabHandler -- input selection, deconv controls
|   |-- volume_viewer_tab.py    VolumeViewerTabHandler -- depth slider, export
|   +-- settings_tab.py         SettingsTabHandler -- camera, save, display, GPU info
|-- widgets/
|   |-- volume_slicer.py        VolumeSlicerWidget -- pyqtgraph depth slice viewer
|   +-- lenslet_overlay.py      LensletOverlayWidget -- white image + detected centers
|-- config/
|   |-- lfm_app_config.json     Auto-saved settings (created on first run)
|   +-- lfm_camera_config.json  Camera-specific settings (separate from standalone app)
+-- tests/
    +-- test_lfm_state.py
```

---

## Tab overview

### Camera tab

Embedded from `GUI/camera_app.py` using the same `sys.modules` isolation pattern as the ODMR app. Provides live camera streaming, exposure/binning controls, and frame saving.

Two additional buttons are added at the bottom:
- **Capture as White Image** -- grabs the current averaged frame and stores it in `state.white_image` for use in the Calibration tab.
- **Capture as Raw LFM Image** -- grabs the current averaged frame and stores it in `state.recon_raw_image` for use in the Reconstruction tab.

### Calibration tab

Configures and runs the pyolaf calibration pipeline. This is the most time-consuming step and only needs to be done once per optical configuration.

**Left panel (controls):**
| Control | Description |
|---|---|
| Config YAML | Path to the LFM optics configuration file (`.yaml`) |
| White Image | Path to the white calibration TIFF, or use the camera capture |
| Depth range min/max | Reconstruction depth range in micrometers (default: -300 to 300) |
| Depth step | Distance between depth planes in micrometers (default: 150) |
| Lenslet spacing | Downsampled lenslet spacing in pixels (default: 15) |
| Super-res factor | Super-resolution multiplier relative to lenslet resolution (default: 5) |
| Lanczos window | Window size for the anti-aliasing filter (default: 4) |
| Run Calibration | Start the 5-stage calibration pipeline |
| Abort | Cancel a running calibration at the next checkpoint |
| Save/Load Calibration | Save/load the H and Ht matrices to `.npz` to avoid recomputation |

**Right panel (visualization):**
Displays the white calibration image with detected lenslet centers overlaid as red dots, plus a summary of the calibration results (number of depth planes, etc.).

**Calibration pipeline stages:**

| Stage | Function | Duration |
|---|---|---|
| 1 | `LFM_setCameraParams()` -- load YAML config | Fast (<1s) |
| 2 | Load white image from file or camera | Fast (<1s) |
| 3 | `LFM_computeGeometryParameters()` -- detect lenslets, compute depth planes | Moderate (seconds) |
| 4 | `LFM_computeLFMatrixOperators()` -- compute forward/backward PSF matrices | **Slow** (minutes) |
| 5 | `LFM_retrieveTransformation()` + anti-aliasing kernels | Fast (<1s) |

**Tip:** Save the calibration after it completes. Loading a saved calibration skips the slow PSF computation entirely.

### Reconstruction tab

Runs iterative Richardson-Lucy deconvolution on a raw LFM image using the calibrated forward/backward projection operators.

**Input selection:**
- **From File** -- browse for a raw LFM `.tif` image
- **From Camera** -- use the most recent frame captured via the Camera tab's "Capture as Raw LFM Image" button

**Parameters:**
| Parameter | Default | Description |
|---|---|---|
| Iterations | 1 | Number of deconvolution iterations. More iterations improve resolution but take longer. |
| Anti-aliasing filter | On | Apply depth-adaptive Lanczos filtering per iteration to suppress aliasing artifacts. |

After reconstruction completes, the middle depth slice is shown as a preview. Click "View in Volume Viewer" to browse all depth slices.

### Volume Viewer tab

Interactive 3D volume browser.

**Controls:**
| Control | Description |
|---|---|
| Depth slider | Drag to browse through depth slices |
| Depth spinbox | Type a specific depth index |
| Depth label | Shows the physical depth in micrometers (from calibration) |
| Colormap | Choose from viridis, gray, hot, plasma, inferno, magma |
| Auto levels | Automatically scale display to data range |
| Export Slice | Save the current depth slice as TIFF or NumPy `.npy` |
| Export Volume | Save the full 3D volume as compressed NumPy `.npz` or multi-page TIFF |

### Settings tab

Global configuration that persists across sessions.

| Setting | Description |
|---|---|
| Camera serial | Basler camera serial number (for auto-connect) |
| Base save path | Root directory for all saved data |
| Subfolder | Subfolder within the base path |
| Timestamps | Append timestamps to saved filenames |
| Default colormap | Default colormap for the Volume Viewer |
| Auto levels | Default auto-levels behavior |
| GPU info | Displays CuPy availability, CUDA device, and memory pool info |

---

## Typical workflow

### Using sample data (no camera)

1. **Launch:** `cd GUI && python lfm_app/lfm_app.py`
2. **Calibration tab:**
   - Config YAML and white image paths should be pre-filled (pointing to `pyolaf-main/examples/fly-muscles-GFP/`)
   - Click **Run Calibration** and wait for completion (progress bar shows 5 stages)
   - Verify lenslet centers appear as red dots on the white image
3. **Reconstruction tab:**
   - Select **From File**, click **Browse**, and select `pyolaf-main/examples/fly-muscles-GFP/example_fly.tif`
   - Leave iterations at 1 for a quick test
   - Click **Reconstruct** and wait for completion
   - Verify the middle slice preview appears
4. **Volume Viewer tab:**
   - Click **View in Volume Viewer** (or switch to the tab manually)
   - Drag the depth slider to browse through slices
   - Try different colormaps
   - Export slices or the full volume as needed

### Using the Basler camera

1. **Camera tab:**
   - Connect the camera (it should auto-detect the Basler acA1920-155um)
   - Start streaming and adjust exposure/binning as needed
   - Insert the white calibration target and click **Capture as White Image**
   - Insert the sample and click **Capture as Raw LFM Image**
2. **Calibration tab:**
   - Set the Config YAML path to your LFM optical configuration
   - The white image will already be loaded from the camera capture
   - Adjust depth range and other parameters as needed
   - Click **Run Calibration**
3. **Reconstruction tab:**
   - Select **From Camera** and click **Use Current Camera Frame** (or it will use the last capture)
   - Click **Reconstruct**
4. **Volume Viewer tab:**
   - Browse and export results

---

## Configuration

Settings are automatically saved to `GUI/lfm_app/config/lfm_app_config.json` when the app closes, and restored on next launch. Use File > Save/Load/Reset Configuration to manage configs manually.

### Config file format

```json
{
  "config_yaml_path": "path/to/config.yaml",
  "white_image_path": "path/to/calib.tif",
  "depth_range_min": -300.0,
  "depth_range_max": 300.0,
  "depth_step": 150.0,
  "new_spacing_px": 15,
  "super_res_factor": 5,
  "lanczos_window_size": 4,
  "filter_flag": true,
  "num_iterations": 1,
  "lfm_camera_serial": "",
  "display_colormap": "viridis",
  "display_auto_levels": true,
  "save_base_path": "",
  "save_subfolder": "lfm_data",
  "save_timestamp_enabled": true
}
```

---

## State object reference (LFMAppState)

The `LFMAppState` class in `state/lfm_state.py` is the single source of truth. All properties that affect the UI emit Qt signals so widgets update automatically.

### Calibration stage progression

```
UNCONFIGURED --> CONFIG_LOADED --> WHITE_LOADED --> GEOMETRY_READY --> OPERATORS_READY
```

The stage advances as the calibration pipeline completes each step. `can_start_reconstruction()` returns `True` only when the stage is `OPERATORS_READY` and a raw image is loaded.

### Signals

| Signal | Parameters | Emitted when |
|---|---|---|
| `calibration_stage_changed` | `str` | Calibration stage advances |
| `calibration_progress` | `str, int, int` | Worker reports progress (stage, current, total) |
| `calibration_completed` | `dict` | Calibration finishes successfully |
| `calibration_failed` | `str` | Calibration encounters an error |
| `recon_running_changed` | `bool` | Reconstruction starts or stops |
| `recon_progress` | `int, int` | Deconvolution iteration completes (current, total) |
| `recon_completed` | `object` | Reconstruction finishes (3D numpy array) |
| `recon_failed` | `str` | Reconstruction encounters an error |
| `current_depth_changed` | `int` | User navigates to a different depth slice |
| `volume_loaded` | `int, int, int` | New volume stored (ny, nx, n_depths) |
| `camera_mode_changed` | `str` | Camera switches mode (idle/streaming/acquiring) |
| `status_message` | `str` | Status message for the status bar |

---

## Key pyolaf functions used

The calibration and reconstruction workers wrap these pyolaf functions:

| Function | Module | Purpose |
|---|---|---|
| `LFM_setCameraParams(config, spacing)` | `pyolaf.geometry` | Load camera/optics config from YAML |
| `LFM_computeGeometryParameters(...)` | `pyolaf.geometry` | Detect lenslets, compute depth planes and resolution |
| `LFM_computeLFMatrixOperators(...)` | `pyolaf.lf` | Build forward (H) and backward (Ht) projection matrices |
| `LFM_retrieveTransformation(...)` | `pyolaf.transform` | Compute grid alignment transformation |
| `transform_img(img, trans, offset)` | `pyolaf.transform` | Apply transformation to a raw image |
| `LFM_forwardProject(H, volume, ...)` | `pyolaf.project` | Project 3D volume to 2D light field |
| `LFM_backwardProject(Ht, image, ...)` | `pyolaf.project` | Project 2D light field to 3D volume |
| `lanczosfft(volumeSize, widths, window)` | `pyolaf.aliasing` | Precompute anti-aliasing filter kernels |
| `LFM_computeDepthAdaptiveWidth(...)` | `pyolaf.aliasing` | Compute depth-adaptive filter widths |

The reconstruction uses an iterative Richardson-Lucy algorithm:
```
for each iteration:
    LFimageGuess = forwardProject(H, reconVolume)
    error = measured / LFimageGuess * onesForward
    errorBack = backwardProject(Ht, error) / onesBack
    reconVolume = reconVolume * errorBack
    [optional] apply anti-aliasing filter per depth
```

---

## LFM YAML configuration reference

The pyolaf `config.yaml` file describes the optical system. Example (fly muscle demo):

```yaml
gridType: 'reg'         # Lenslet grid type: 'reg' (regular square)
focus: 'single'          # Focus type: 'single' (single focal length MLA)
plenoptic: 1             # Plenoptic camera type (1 = focused)
uLensMask: 1             # Microlens mask flag
M: 10                    # Total magnification
NA: 0.3000               # Numerical aperture
ftl: 200000              # Tube lens focal length (um)
fm: 1875                 # Microlens focal length (um)
tube2mla: 200000         # Distance from tube lens to MLA (um)
mla2sensor: 0            # Distance from MLA to sensor (um)
lensPitch: 125           # Microlens pitch (um)
pixelPitch: 6.5000       # Camera pixel pitch (um)
WaveLength: 0.5250       # Illumination wavelength (um)
n: 1                     # Refractive index of medium
```

---

## Adding new features

The app follows the same extensibility patterns as the ODMR app:

### Adding a new tab
1. Create a new handler class in `tabs/` (e.g., `my_new_tab.py`)
2. Add a placeholder `QWidget` to the tab widget in `lfm_main_window.py`
3. Instantiate the handler in the constructor, passing state and utility functions

### Adding a new worker
1. Create a new `QThread` subclass in `workers/`
2. Define `stage_progress`, `completed`, and `failed` signals
3. Implement `run()` with checkpoint-based abort support
4. Create and start the worker from the appropriate tab handler

### Adding new state properties
1. Add the property name to `_CONFIG_KEYS` if it should be persisted
2. Add a private backing field in `__init__`
3. Add `@property` getter and setter (setter emits signal if UI needs to react)
4. Add corresponding signal declaration if needed

### Modifying pyolaf parameters
All pyolaf parameters are stored as properties on `LFMAppState` and exposed in the Calibration tab. To add a new parameter:
1. Add the property to `LFMAppState` with a default value
2. Add a UI control in `CalibrationTabHandler._build_ui()`
3. Connect the control to the state property
4. Pass the value to `CalibrationWorker` in its constructor

---

## Integration with other apps

The LFM app integrates with the multi-app launcher via `GUI/launch_all_apps.py`:

```python
launcher = AppLauncher()
launcher.launch_lfm_app(x=100, y=50)
launcher.run()
```

The `shared_state` (ExperimentState) is passed through but not currently used by the LFM app. Future integration could include:
- Monitoring laser power during acquisition
- Coordinating stage movements with the camera
- Cross-app logging

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `ImportError: DLL load failed` for PySide6 | Install PySide6 6.7.3 specifically: `pip install PySide6==6.7.3` |
| Calibration fails at stage 3 | Check that the white image is a proper calibration image showing the lenslet array pattern |
| Calibration is very slow | Stage 4 (PSF computation) is inherently slow. Save the calibration result to `.npz` after first run and load it next time. |
| Reconstruction produces blank volume | Ensure the raw image was captured with the same optical configuration used for calibration |
| Out of memory during reconstruction | Reduce `super_res_factor` or `depth_range`, or install CuPy for GPU acceleration |
| Camera not detected | Check that pypylon is installed and the Basler camera is connected via USB |
| Config not saving | Ensure `GUI/lfm_app/config/` directory exists (created automatically on first save) |
