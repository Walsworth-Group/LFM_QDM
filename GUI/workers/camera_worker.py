"""
Camera worker thread for continuous frame acquisition.

Producer thread in producer-consumer architecture.
Grabs frames from Basler camera and puts them in queue for consumer.
"""

import sys
import time
import queue
import numpy as np
from pathlib import Path
from PySide6.QtCore import QThread, Signal

# Add parent directory to path to import qdm modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from qdm_basler import basler, get_current_settings, set_exposure_time, set_binning, set_pixel_format, get_saturation_threshold
from pypylon import pylon


class CameraWorker(QThread):
    """
    Worker thread for non-blocking camera frame acquisition.

    Implements producer in producer-consumer pattern:
    - Continuously grabs frames from camera
    - Puts frames in queue for consumer thread
    - Emits frames for live display
    - Handles parameter changes via command queue
    """

    # Signals
    frame_ready = Signal(np.ndarray, float, int)  # (frame, timestamp, frame_count)
    connection_established = Signal(dict)  # camera settings
    connection_failed = Signal(str)  # error message
    parameter_set_success = Signal(str, object)  # (param_name, value)
    parameter_set_failed = Signal(str, str)  # (param_name, error_msg)
    saturation_detected = Signal(bool, float)  # (is_saturated, max_pixel_value)

    def __init__(self, state, frame_queue):
        """
        Initialize camera worker.

        Parameters
        ----------
        state : CameraState
            Shared state object
        frame_queue : queue.Queue
            Thread-safe queue for passing frames to consumer
        """
        super().__init__()
        self.state = state
        self.frame_queue = frame_queue
        self.camera = None
        self._is_running = False
        self._is_grabbing = False
        self._command_queue = []  # [(command, args), ...]
        self._frame_count = 0
        self._saturation_state = False  # Track saturation to avoid excessive signals

    def run(self):
        """Main worker thread loop."""
        self._is_running = True
        self._frame_count = 0

        try:
            # Connect to camera
            self._connect_camera()

            # Main loop - process commands and grab frames
            while self._is_running:
                # Process queued commands (non-blocking)
                self._process_commands()

                # Grab frames if enabled
                if self._is_grabbing:
                    self._acquire_frame()
                else:
                    # Not grabbing - just sleep briefly
                    time.sleep(0.01)

        except Exception as e:
            self.connection_failed.emit(f"Worker error: {str(e)}")

        finally:
            self._disconnect_camera()

    def _connect_camera(self):
        """Connect to camera (runs in worker thread)."""
        try:
            self.camera = basler(
                choice=self.state.camera_serial_number,
                exposure_time_us=self.state.camera_exposure_us,
                pixel_format=self.state.camera_pixel_format,
                logger=None,
                verbose=False
            )

            if not self.camera.connect():
                self.connection_failed.emit(f"Could not connect to camera SN {self.state.camera_serial_number}")
                return

            # Get initial settings from camera
            settings = get_current_settings(self.camera)
            self.connection_established.emit(settings)

        except Exception as e:
            self.connection_failed.emit(f"Connection error: {str(e)}")
            self.camera = None

    def _disconnect_camera(self):
        """Disconnect from camera."""
        if self.camera:
            try:
                self.camera.close()
            except:
                pass
            self.camera = None

    def _acquire_frame(self):
        """Acquire single frame (producer)."""
        if not self.camera or not self.camera.is_connected():
            return

        try:
            # Ensure grabbing is started
            if not self.camera._camera.IsGrabbing():
                self.camera._camera.StartGrabbing(
                    pylon.GrabStrategy_LatestImages,
                    pylon.GrabLoop_ProvidedByUser
                )

            # Retrieve frame with timeout
            grab_result = self.camera._camera.RetrieveResult(
                100,  # 100ms timeout
                pylon.TimeoutHandling_Return
            )

            if grab_result.GrabSucceeded():
                frame = grab_result.Array
                timestamp = time.time()
                self._frame_count += 1

                # Check saturation
                # In Sum binning mode the camera outputs uint16 regardless of
                # pixel format (values can exceed nominal bit-depth), so use
                # the actual dtype max as the ceiling.
                max_val = np.max(frame)
                if self.state.camera_binning_mode == 'Sum':
                    # Sum mode: capacity is determined by frame dtype
                    threshold = float(np.iinfo(frame.dtype).max)
                else:
                    threshold = get_saturation_threshold(self.state.camera_pixel_format)
                is_saturated = max_val >= threshold * 0.98

                # Emit saturation signal (only on state change to avoid spam)
                if is_saturated != self._saturation_state:
                    self._saturation_state = is_saturated
                    self.saturation_detected.emit(is_saturated, float(max_val))

                # Put frame in queue for consumer (non-blocking)
                try:
                    self.frame_queue.put_nowait((frame, timestamp, self._frame_count))
                except queue.Full:
                    # Queue full - skip this frame (consumer is slow)
                    pass

                # Emit for live display
                self.frame_ready.emit(frame, timestamp, self._frame_count)

            grab_result.Release()

        except pylon.TimeoutException:
            # No frame available within timeout - continue
            pass
        except Exception as e:
            # Log error but don't crash
            self.parameter_set_failed.emit('frame_acquisition', str(e))

    def _process_commands(self):
        """Process queued parameter changes."""
        while self._command_queue and self.camera and self.camera.is_connected():
            command, args = self._command_queue.pop(0)

            try:
                if command == 'set_exposure':
                    set_exposure_time(self.camera, args[0])
                    self.parameter_set_success.emit('exposure', args[0])

                elif command == 'set_binning':
                    set_binning(self.camera, args[0], args[1], args[2])
                    self.parameter_set_success.emit('binning', (args[0], args[1]))

                elif command == 'set_pixel_format':
                    set_pixel_format(self.camera, args[0])
                    self.parameter_set_success.emit('pixel_format', args[0])

                    # Pixel format change may affect saturation threshold
                    self._saturation_state = False  # Reset to re-check

            except Exception as e:
                self.parameter_set_failed.emit(command, str(e))

    # === Public Methods (called from main thread) ===

    def start_grabbing(self):
        """Signal worker to begin frame acquisition."""
        self._is_grabbing = True

    def stop_grabbing(self):
        """Signal worker to stop frame acquisition (keep connection)."""
        self._is_grabbing = False
        # Stop grabbing if active
        if self.camera and self.camera.is_connected():
            if self.camera._camera.IsGrabbing():
                try:
                    self.camera._camera.StopGrabbing()
                except:
                    pass

    def queue_command(self, command, *args):
        """
        Queue a command for execution in worker thread.

        Parameters
        ----------
        command : str
            Command name ('set_exposure', 'set_binning', 'set_pixel_format')
        *args : tuple
            Command arguments
        """
        self._command_queue.append((command, args))

    def stop(self):
        """Stop the worker thread."""
        self._is_running = False
        self._is_grabbing = False
