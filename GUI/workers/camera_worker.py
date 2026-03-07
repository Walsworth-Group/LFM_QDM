"""
Camera worker thread for continuous frame acquisition.

Producer thread in producer-consumer architecture.
Grabs frames from PCO camera and puts them in queue for consumer.
"""

import sys
import time
import queue
import numpy as np
from pathlib import Path
from PySide6.QtCore import QThread, Signal

# Add parent directory to path to import qdm modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from qdm_pco import (
    pco_camera as basler,
    get_current_settings,
    set_exposure_time,
    set_binning,
    set_pixel_format,
    get_saturation_threshold,
)

# PCO cameras always output 16-bit; saturation threshold is fixed.
_PCO_SATURATION_THRESHOLD = get_saturation_threshold('Mono16')


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
    connection_established = Signal(dict)          # camera settings
    connection_failed = Signal(str)                # error message
    parameter_set_success = Signal(str, object)    # (param_name, value)
    parameter_set_failed = Signal(str, str)        # (param_name, error_msg)
    saturation_detected = Signal(bool, float)      # (is_saturated, max_pixel_value)

    def __init__(self, state, frame_queue):
        """
        Initialize camera worker.

        Parameters
        ----------
        state : CameraState
            Shared state object.
        frame_queue : queue.Queue
            Thread-safe queue for passing frames to consumer.
        """
        super().__init__()
        self.state = state
        self.frame_queue = frame_queue
        self.camera = None
        self._is_running = False
        self._is_grabbing = False
        self._command_queue = []   # [(command, args), ...]
        self._frame_count = 0
        self._saturation_state = False

    def run(self):
        """Main worker thread loop."""
        self._is_running = True
        self._frame_count = 0

        try:
            self._connect_camera()

            while self._is_running:
                self._process_commands()

                if self._is_grabbing:
                    self._acquire_frame()
                else:
                    time.sleep(0.01)

        except Exception as e:
            self.connection_failed.emit(f"Worker error: {str(e)}")

        finally:
            self._disconnect_camera()

    def _connect_camera(self):
        """Connect to PCO camera (runs in worker thread)."""
        try:
            self.camera = basler(
                choice=self.state.camera_serial_number,   # unused for PCO
                exposure_time_us=self.state.camera_exposure_us,
                pixel_format=self.state.camera_pixel_format,  # unused for PCO
                logger=None,
                verbose=False,
            )

            if not self.camera.connect():
                self.connection_failed.emit("Could not connect to PCO camera")
                return

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
            except Exception:
                pass
            self.camera = None

    def _acquire_frame(self):
        """Acquire single frame (producer) using PCO ring-buffer live grab."""
        if not self.camera or not self.camera.is_connected():
            return

        try:
            # Start ring-buffer grab if not already active
            if not self.camera.is_live_grab_active():
                self.camera.start_live_grab()
                # Brief pause to allow first frame to be captured
                time.sleep(0.05)

            frame = self.camera.grab_latest_frame(timeout_ms=100)

            if frame is None:
                # No frame ready yet — yield briefly and retry
                time.sleep(0.01)
                return

            timestamp = time.time()
            self._frame_count += 1

            # Saturation check (PCO always 16-bit)
            max_val = np.max(frame)
            is_saturated = max_val >= _PCO_SATURATION_THRESHOLD * 0.98

            if is_saturated != self._saturation_state:
                self._saturation_state = is_saturated
                self.saturation_detected.emit(is_saturated, float(max_val))

            # Put frame in queue for consumer (non-blocking)
            try:
                self.frame_queue.put_nowait((frame, timestamp, self._frame_count))
            except queue.Full:
                pass  # Consumer is slow; drop this frame

            self.frame_ready.emit(frame, timestamp, self._frame_count)

        except Exception as e:
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

            except Exception as e:
                self.parameter_set_failed.emit(command, str(e))

    # === Public Methods (called from main thread) ===

    def start_grabbing(self):
        """Signal worker to begin frame acquisition."""
        self._is_grabbing = True

    def stop_grabbing(self):
        """Signal worker to stop frame acquisition (keep connection)."""
        self._is_grabbing = False
        if self.camera and self.camera.is_connected():
            self.camera.stop_live_grab()

    def queue_command(self, command, *args):
        """
        Queue a command for execution in worker thread.

        Parameters
        ----------
        command : str
            Command name ('set_exposure', 'set_binning', 'set_pixel_format').
        *args : tuple
            Command arguments.
        """
        self._command_queue.append((command, args))

    def stop(self):
        """Stop the worker thread."""
        self._is_running = False
        self._is_grabbing = False
