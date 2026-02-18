# Basler Camera Streaming Application

A PySide6 application for live camera streaming, image averaging, and data saving with Basler cameras.

## Features

- **Live Camera Streaming**: Real-time display with enable/disable toggle
- **Frame Averaging**: Configurable N-frame averaging (1-10000 frames)
- **Producer-Consumer Architecture**: Non-blocking frame acquisition and processing
- **Real-time Parameter Control**: Adjust exposure, binning, and pixel format while streaming
- **Saturation Detection**: Visual warning when pixels reach format maximum
- **Batch Saving**: Save multiple averaged images with automatic numbering
- **Configuration Persistence**: Save and load camera settings

## Architecture

### Files Created

1. **camera_state.py** - State management with Qt signals
2. **camera_worker.py** - Producer thread for continuous frame acquisition
3. **camera_consumer.py** - Consumer thread for averaging and saving
4. **camera_app.py** - Main GUI application
5. **Extensions to qdm_basler.py** - 5 new helper functions

### Producer-Consumer Pattern

```
CameraWorker (Producer)
    ↓ Grab frames from camera
    ↓ Put in queue.Queue(maxsize=30)
    ↓ Emit for live display

CameraConsumer (Consumer)
    ↓ Get frames from queue
    ↓ Accumulate N frames
    ↓ Emit averaged frame
    ↓ Save if enabled

Main Thread (Qt Event Loop)
    ↓ Update pyqtgraph ImageViews
    ↓ Handle user interactions
```

## Usage

### Launching the App

```bash
cd "G:\Shared drives\PHYS - Walsworth Group\Experiment folders\Bioimaging\ODMR code\ODMR code v2\GUI"
python camera_app.py
```

### Basic Workflow

1. **Connect to Camera**
   - Enter serial number (default: 23049069)
   - Click "Connect to Camera"
   - Wait for connection confirmation

2. **Start Streaming**
   - Click "Start Streaming"
   - Live image appears if "Enable Live Display" is checked

3. **Adjust Parameters** (while streaming)
   - Exposure time: 100-100000 µs (spinbox or slider)
   - Binning: 1x1, 2x2, 3x3, or 4x4
   - Binning mode: Average or Sum
   - Pixel format: Mono8, Mono12, Mono12p

4. **Frame Averaging**
   - Set "Frames to Average" (e.g., 100)
   - Check "Enable Live Averaging" to see updates
   - Averaged image updates every N frames

5. **Save Averaged Images**
   - Set save directory and subfolder
   - Set number of images to save (e.g., 10)
   - Click "Begin Saving"
   - Button shows progress: "Saving... (3/10)"
   - Files saved as: `camera_averaged_YYYYMMDD_HHMMSS_0001.npy`

6. **Stop and Disconnect**
   - Click "Stop Streaming" to pause acquisition (keeps connection)
   - Click "Disconnect" to close camera

### Saving Configuration

Click "Save Configuration" to save current settings to `basler_camera_config.json`. Settings are automatically loaded on next launch.

## Camera Controls

### Exposure Time
- Range: 100 - 100000 µs
- Use spinbox for precise values or slider for quick adjustments
- Changes apply immediately while streaming

### Binning
- Binning X/Y: 1, 2, 3, or 4
- Mode: Average (default) or Sum
- Reduces image resolution but increases SNR
- Example: 1920x1200 → 960x600 with 2x2 binning

### Pixel Format
- **Mono8**: 8-bit grayscale (0-255)
- **Mono12**: 12-bit grayscale (0-4095), recommended for high dynamic range
- **Mono12p**: 12-bit packed (saves bandwidth)

### Saturation Warning
- Red warning appears when any pixel ≥ 95% of format maximum
- Mono8: triggers at 242/255
- Mono12: triggers at 3890/4095
- Reduce exposure time to eliminate saturation

## Display Controls

### Live Image
- **Enable Live Display**: Toggle to reduce CPU usage when not needed
- Status bar shows: pixel dimensions, stream count
- Updates throttled to ~30 fps for smooth display

### Averaged Image
- **Enable Live Averaging**: Show averaged images as they're computed
- Can be disabled to save CPU while still computing for saving
- Auto-levels applied for optimal contrast

## Data Saving

### File Format
- **.npy files**: NumPy binary format, preserves full bit depth
- Load in Python: `data = np.load('filename.npy')`

### Filename Structure
```
{base}_{suffix}_{timestamp}_{index}.npy

Examples:
camera_averaged_20260214_153045_0001.npy
camera_averaged_test_20260214_153045_0002.npy
```

### Save Modes
1. **Live averaging ON**: Displays and saves averaged images
2. **Live averaging OFF**: Computes and saves without display (saves CPU)

## Helper Functions Added to qdm_basler.py

```python
# Get current camera settings
settings = get_current_settings(cam)
# Returns: {exposure_us, pixel_format, binning_x, binning_y, width, height, serial_number, model_name}

# Set parameters
set_exposure_time(cam, 15000)  # microseconds
set_binning(cam, 2, 2, 'Average')  # binning_x, binning_y, mode
set_pixel_format(cam, 'Mono12')  # 'Mono8', 'Mono12', 'Mono12p'

# Get saturation threshold for format
threshold = get_saturation_threshold('Mono12')  # Returns 4095
```

## Threading and Performance

### Non-Blocking Design
- All camera I/O runs in worker thread (never blocks UI)
- Frame queue (maxsize=30) buffers frames between threads
- UI remains responsive even during high-speed acquisition

### Performance Tips
- Disable live display when not needed (reduces CPU ~20%)
- Use larger binning for higher frame rates
- Mono8 format uses less bandwidth than Mono12

## Troubleshooting

### Camera Not Found
- Check USB connection
- Verify serial number is correct
- Close other applications using the camera (including other Pylon viewers)

### Frames Dropping
- Increase queue size in camera_worker.py (currently maxsize=30)
- Reduce frame rate by increasing exposure time
- Use binning to reduce data throughput

### Saturation Warning Persistent
- Reduce exposure time
- Add neutral density filter to optical path
- Check that light source isn't too intense

### Averaged Images Not Updating
- Check "Enable Live Averaging" checkbox
- Verify "Frames to Average" is reasonable (try 10 for testing)
- Ensure streaming is active (not just connected)

### Save Fails
- Check directory exists and is writable
- Verify sufficient disk space
- Check permissions for save directory

## Configuration File

Location: `GUI/basler_camera_config.json`

Example:
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
  "camera_save_subfolder": "camera_data",
  "camera_save_append_timestamp": true
}
```

## Integration with Other Apps

The app follows the multi-app architecture in `claude_app.md`:

```python
# Standalone mode
app = QApplication([])
window = BaslerCameraApp()
window.show()
app.exec()

# Shared state mode (for multi-app launcher)
shared_state = CameraState()
camera_app = BaslerCameraApp(state=shared_state)
laser_app = LaserPowerMonitor(state=shared_state)
```

## Testing

### Unit Tests
```python
# Test state signals
from camera_state import CameraState
state = CameraState()
state.camera_exposure_us = 15000
# Signal camera_exposure_changed emitted

# Test helper functions
from qdm_basler import basler, get_current_settings
cam = basler(choice='23049069')
cam.connect()
settings = get_current_settings(cam)
cam.close()
```

### Integration Test
1. Launch app
2. Connect to camera SN 23049069
3. Start streaming - verify live image
4. Change exposure to 20000 µs - verify brightness changes
5. Set averaging to 20 frames - verify averaged image updates
6. Save 3 images - verify files created
7. Stop and disconnect - verify no errors

## Known Limitations

- Maximum queue size of 30 frames (~1 second buffer at 30 fps)
- Live display throttled to 30 fps (can be adjusted in on_frame_ready)
- Saturation detection checks entire frame (may be slow for large images)
- Configuration doesn't save window size/position

## Future Enhancements

Potential improvements:
- ROI selection for partial frame readout
- Histogram display with adjustable levels
- Frame rate indicator
- Export to TIFF format
- Dark frame subtraction
- Flat field correction
- Video recording (AVI/MP4)

## Contact

For questions or issues:
- Check CLAUDE.md for project overview
- Review claude_app.md for architecture details
- Raise issues on the project repository

---

Created: 2026-02-14
Updated: 2026-02-14
Version: 1.0
