"""
Camera consumer thread for frame averaging and saving.

Consumer thread in producer-consumer architecture.
Gets frames from queue, averages them, and handles saving.
"""

import time
import queue
import numpy as np
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import QThread, Signal

try:
    from PIL import Image as PILImage
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False


class CameraConsumer(QThread):
    """
    Consumer thread for frame averaging and saving.

    Implements consumer in producer-consumer pattern:
    - Gets frames from queue
    - Accumulates N frames for averaging
    - Emits averaged frames
    - Handles batch saving of averaged images
    """

    # Signals
    averaged_frame_ready = Signal(np.ndarray, int)  # (avg_frame, avg_count)
    save_progress = Signal(int, int)  # (current, total)
    save_completed = Signal(str)  # filepath
    error_occurred = Signal(str)  # error message

    def __init__(self, state, frame_queue):
        """
        Initialize camera consumer.

        Parameters
        ----------
        state : CameraState
            Shared state object
        frame_queue : queue.Queue
            Thread-safe queue for receiving frames from producer
        """
        super().__init__()
        self.state = state
        self.frame_queue = frame_queue
        self._is_running = False

        # Accumulator for averaging
        self.accumulator = None
        self.frames_accumulated = 0
        self.target_frames = 1
        self.current_dtype = None

        # Save state
        self.is_saving = False
        self.save_count = 0
        self.save_target = 0
        self.saved_frames = []

        # Counter for total averaged frames produced
        self.total_averaged_count = 0

    def run(self):
        """Main consumer loop - accumulates and averages frames."""
        self._is_running = True

        while self._is_running:
            try:
                # Get frame from queue (blocking with timeout)
                frame, timestamp, frame_count = self.frame_queue.get(timeout=0.1)

                # Get current averaging target (may change dynamically)
                self.target_frames = self.state.camera_num_frames_to_average

                # Initialize or reset accumulator if needed
                if (self.accumulator is None or
                    self.accumulator.shape != frame.shape or
                    self.frames_accumulated >= self.target_frames or
                    self.current_dtype != frame.dtype):

                    self.accumulator = np.zeros_like(frame, dtype=np.float64)
                    self.frames_accumulated = 0
                    self.current_dtype = frame.dtype

                # Accumulate frame
                self.accumulator += frame
                self.frames_accumulated += 1

                # Check if averaging complete
                if self.frames_accumulated >= self.target_frames:
                    # Compute average
                    avg_frame = (self.accumulator / self.frames_accumulated).astype(self.current_dtype)

                    # Increment total averaged frame counter
                    self.total_averaged_count += 1

                    # Emit averaged frame with total count
                    self.averaged_frame_ready.emit(avg_frame, self.total_averaged_count)

                    # Handle saving
                    if self.is_saving:
                        self.saved_frames.append(avg_frame.copy())
                        self.save_count += 1
                        self.save_progress.emit(self.save_count, self.save_target)

                        if self.save_count >= self.save_target:
                            # Save complete - write to disk
                            self._save_to_disk()
                            self.is_saving = False

                    # Reset accumulator for next batch
                    self.accumulator = None
                    self.frames_accumulated = 0

            except queue.Empty:
                # No frames available - continue waiting
                continue
            except Exception as e:
                self.error_occurred.emit(f"Consumer error: {str(e)}")

    def start_saving(self, num_images):
        """
        Start saving averaged images.

        Parameters
        ----------
        num_images : int
            Number of averaged images to save
        """
        self.is_saving = True
        self.save_count = 0
        self.save_target = num_images
        self.saved_frames = []

    def stop_saving(self):
        """Stop saving (may result in partial save)."""
        if self.is_saving and self.saved_frames:
            # Save what we have
            self._save_to_disk()
        self.is_saving = False

    def _save_to_disk(self):
        """Save accumulated frames to disk."""
        try:
            # Prepare directory
            save_path = Path(self.state.camera_save_dir)
            if self.state.camera_save_subfolder:
                save_path = save_path / self.state.camera_save_subfolder
            save_path.mkdir(parents=True, exist_ok=True)

            # Prepare base filename
            base_name = "camera_averaged"
            if self.state.camera_save_filename_suffix:
                base_name = f"{base_name}_{self.state.camera_save_filename_suffix}"

            if self.state.camera_save_append_timestamp:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                base_name = f"{base_name}_{timestamp}"

            # Get file format from state
            file_format = self.state.camera_save_format

            # Save each frame in the selected format.
            # Image formats (.tiff, .jpg) are transposed so the saved file
            # matches the on-screen orientation (pyqtgraph displays frame.T).
            # .npy keeps the raw (height, width) array for data analysis.
            # Flip settings from state are applied before saving so that the
            # saved file matches the orientation shown on screen.
            flip_h = getattr(self.state, 'camera_flip_horizontal', False)
            flip_v = getattr(self.state, 'camera_flip_vertical', False)

            for i, frame in enumerate(self.saved_frames):
                # Apply orientation flips to match the displayed image
                if flip_h:
                    frame = np.fliplr(frame)
                if flip_v:
                    frame = np.flipud(frame)

                if file_format == 'npy':
                    filename = f"{base_name}_{i+1:04d}.npy"
                    filepath = save_path / filename
                    np.save(filepath, frame)

                elif file_format == 'tiff':
                    filename = f"{base_name}_{i+1:04d}.tiff"
                    filepath = save_path / filename
                    self._save_as_tiff(filepath, frame.T)

                elif file_format == 'jpg':
                    filename = f"{base_name}_{i+1:04d}.jpg"
                    filepath = save_path / filename
                    self._save_as_jpg(filepath, frame.T)

            # Emit completion message
            num_saved = len(self.saved_frames)
            completion_msg = f"Saved {num_saved} averaged images to {save_path}"
            if num_saved < self.save_target:
                completion_msg = f"Partial save: {num_saved}/{self.save_target} images saved to {save_path}"

            self.save_completed.emit(completion_msg)

            # Clear saved frames
            self.saved_frames = []

        except Exception as e:
            self.error_occurred.emit(f"Save error: {str(e)}")

    def _save_as_tiff(self, filepath, frame):
        """
        Save frame as 16-bit TIFF scaled to fill the full uint16 range.

        Basler Mono12/Mono12p data is 12-bit (0-4095) packed into uint16.
        Raw values saved without scaling appear very dark (6% brightness) in
        standard TIFF viewers that expect 0-65535.  This method scales by the
        appropriate bit-shift so viewers display the image at full contrast:
          Mono12/Mono12p → shift left 4 bits (×16), filling 0-65535
          Mono8           → shift left 8 bits (×256), filling 0-65535

        Uses tifffile (preferred) for reliable uint16 TIFF output.
        Falls back to Pillow or imageio if tifffile is not installed.

        Parameters
        ----------
        filepath : Path
            Destination file path
        frame : np.ndarray
            2D image array (any integer dtype)
        """
        # Determine bit-depth shift from pixel format so the saved TIFF fills
        # the full 0-65535 range and appears correctly in standard viewers.
        pixel_format = getattr(self.state, 'camera_pixel_format', 'Mono12')
        if pixel_format == 'Mono8':
            shift = 8   # 8-bit → 16-bit: ×256
        else:
            shift = 4   # Mono12 / Mono12p: 12-bit → 16-bit: ×16

        img_16 = (frame.astype(np.uint32) << shift).clip(0, 65535).astype(np.uint16)

        # tifffile writes proper uint16 TIFFs that all viewers handle correctly
        try:
            import tifffile
            tifffile.imwrite(str(filepath), img_16)
            return
        except ImportError:
            pass

        # Fallback: Pillow (quirky with 16-bit, but works for basic cases)
        if _PIL_AVAILABLE:
            pil_img = PILImage.fromarray(img_16)
            pil_img.save(str(filepath))
            return

        # Last resort: imageio
        try:
            import imageio
            imageio.imwrite(str(filepath), img_16)
        except ImportError:
            raise RuntimeError(
                "Cannot save TIFF: none of tifffile, Pillow, or imageio is installed. "
                "Run: pip install tifffile"
            )

    def _save_as_jpg(self, filepath, frame):
        """
        Save frame as 8-bit JPEG (lossy), with auto-scaling to 0-255.

        Note: JPEG is lossy and limited to 8-bit. Scientific data should use
        .npy or .tiff formats to preserve full dynamic range.

        Parameters
        ----------
        filepath : Path
            Destination file path
        frame : np.ndarray
            2D image array (any dtype)
        """
        if not _PIL_AVAILABLE:
            try:
                import imageio
                frame_min, frame_max = frame.min(), frame.max()
                if frame_max > frame_min:
                    scaled = ((frame - frame_min) / (frame_max - frame_min) * 255).astype(np.uint8)
                else:
                    scaled = np.zeros_like(frame, dtype=np.uint8)
                imageio.imwrite(str(filepath), scaled, quality=95)
                return
            except ImportError:
                raise RuntimeError(
                    "Cannot save JPEG: neither Pillow nor imageio is installed. "
                    "Run: pip install Pillow"
                )

        # Scale to 8-bit for JPEG
        frame_min, frame_max = frame.min(), frame.max()
        if frame_max > frame_min:
            scaled = ((frame - frame_min) / (frame_max - frame_min) * 255).astype(np.uint8)
        else:
            scaled = np.zeros_like(frame, dtype=np.uint8)

        pil_img = PILImage.fromarray(scaled, mode='L')
        pil_img.save(str(filepath), quality=95)

    def stop(self):
        """Stop the consumer thread."""
        self._is_running = False
