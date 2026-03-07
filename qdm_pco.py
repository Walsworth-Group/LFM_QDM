"""
PCO camera library for CW ODMR experiments.

Provides the same public interface as qdm_basler.py but for PCO edge cameras,
using the pco Python library (pip install pco).

The pco.Camera class is used internally. Key differences from Basler:
  - No serial-number-based camera selection (pco opens the first available)
  - Always 16-bit output (pixel_format parameter is accepted but ignored)
  - Binning mode (Average/Sum) is not configurable; PCO always sums hardware bins
  - No "ring buffer LatestImageOnly" concept; start_continuous_grab() is a no-op
    for ODMR sweep use (each grab_frames() call uses sequence mode)
  - Ring buffer mode IS used for live display via grab_latest_frame()

The choice / pixel_format parameters are kept in all method signatures for
drop-in compatibility with code written for qdm_basler.
"""

import sys
import time
import numpy as np
from typing import Callable, Optional

try:
    import pco as _pco_lib
    PCO_AVAILABLE = True
except ImportError:
    PCO_AVAILABLE = False


class pco_camera:
    """
    Context manager class for controlling a PCO camera using the pco library.

    Provides the same interface as the basler class in qdm_basler.py so that
    all ODMR sweep and GUI code can use either camera without modification.

    Parameters
    ----------
    choice : str or int or None
        Not used for PCO cameras (kept for API compatibility with basler).
    exposure_time_us : float
        Initial exposure time in microseconds.
    pixel_format : str or None
        Not used for PCO cameras (always 16-bit); kept for API compatibility.
    logger : callable or None
        Optional logging function (e.g., tqdm.write or print).
    verbose : bool
        If False, suppress informational messages.
    """

    def __init__(
        self,
        choice=None,
        exposure_time_us=10000,
        pixel_format=None,
        logger: Optional[Callable[[str], None]] = None,
        verbose: bool = True,
    ):
        self._choice = choice         # unused, kept for API compatibility
        self._exposure_time_us = float(exposure_time_us)
        self._pixel_format = pixel_format  # unused, PCO always outputs 16-bit

        self._logger = logger
        self._verbose = verbose

        self._cam = None        # pco.Camera instance
        self._is_connected = False
        self._is_live = False   # True when ring buffer mode is active

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log(self, msg: str, *, stderr: bool = False):
        if not self._verbose:
            return
        if self._logger is None:
            if stderr:
                print(msg, file=sys.stderr)
            else:
                print(msg)
        else:
            self._logger(msg)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self):
        if not self._is_connected:
            self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Return True if the camera is open and ready."""
        return self._cam is not None and self._is_connected

    def connect(self) -> bool:
        """
        Open a connection to the first available PCO camera.

        Returns
        -------
        bool
            True on success, False on failure.
        """
        if not PCO_AVAILABLE:
            self._log(
                "Error: pco library not installed. Install with: pip install pco",
                stderr=True,
            )
            return False

        try:
            self._cam = _pco_lib.Camera()
            self._cam.set_exposure_time(self._exposure_time_us * 1e-6)

            try:
                cam_type = self._cam.sdk.get_camera_type()
            except Exception:
                cam_type = {}

            self._is_connected = True
            self._log("--- PCO Camera Initialized ---")
            self._log(f"  Type:     {cam_type.get('camera type', 'PCO camera')}")
            self._log(f"  Serial:   {cam_type.get('serial', 'unknown')}")
            self._log(f"  Exposure: {self._exposure_time_us:.1f} µs")
            self._log("------------------------------")
            return True

        except Exception as e:
            self._log(f"PCO connection failed: {e}", stderr=True)
            self._cam = None
            self._is_connected = False
            return False

    def close(self):
        """Close the camera connection and release resources."""
        if self._cam is not None:
            try:
                if self._is_live:
                    self._cam.stop()
                    self._is_live = False
                self._cam.close()
            except Exception:
                pass
            self._cam = None
            self._is_connected = False
            self._log("PCO camera closed.")

    # ------------------------------------------------------------------
    # Frame acquisition — ODMR sweep interface
    # ------------------------------------------------------------------

    def start_continuous_grab(self):
        """
        No-op for PCO cameras.

        Basler uses this to switch to LatestImageOnly (single-slot buffer)
        mode for low-latency ODMR sweeps.  PCO grab_frames() uses sequence
        mode directly, so no persistent grab session needs to be started
        beforehand.  This method is kept for drop-in compatibility.
        """
        pass  # PCO grab_frames() uses sequence mode each call

    def flush_buffer(self):
        """
        No-op for PCO cameras.

        Basler uses this to discard buffered frames between frequency steps.
        PCO grab_frames() always captures fresh frames in sequence mode,
        so no buffer flushing is needed.
        """
        pass

    def grab_frames(self, n_frames: int = 100, quiet: bool = True) -> Optional[np.ndarray]:
        """
        Capture n_frames and return the averaged image.

        Uses PCO sequence mode: arms the camera, collects exactly n_frames,
        averages them, and returns the result.  Any ongoing ring-buffer
        live grab is stopped first and restarted afterwards.

        Parameters
        ----------
        n_frames : int
            Number of frames to capture and average.
        quiet : bool
            Suppress per-call log messages when True.

        Returns
        -------
        np.ndarray or None
            2-D averaged image array, or None on failure.
        """
        if not self.is_connected():
            self._log("Error: Camera is not connected. Call .connect() first.", stderr=True)
            return None

        was_live = self._is_live
        try:
            # Stop ring buffer mode if active
            if self._is_live:
                self._cam.stop()
                self._is_live = False

            # Acquire n_frames in sequence mode
            self._cam.record(number_of_images=n_frames, mode='sequence')
            images, _ = self._cam.images()

            if not images:
                self._log("PCO: no frames returned from record.", stderr=True)
                return None

            stack = np.stack(images, axis=0).astype(np.float64)
            avg = stack.mean(axis=0).astype(images[0].dtype)

            if not quiet:
                self._log(
                    f"PCO: averaged {len(images)} frames, "
                    f"shape {avg.shape}, dtype {avg.dtype}"
                )
            return avg

        except Exception as e:
            self._log(f"PCO grab_frames error: {e}", stderr=True)
            return None

        finally:
            # Restore ring buffer mode if it was active before this call
            if was_live:
                try:
                    self._cam.record(number_of_images=100, mode='ring buffer')
                    self._is_live = True
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Frame acquisition — live display interface (used by CameraWorker)
    # ------------------------------------------------------------------

    def start_live_grab(self):
        """
        Start ring-buffer recording for continuous live display.

        Idempotent — subsequent calls are no-ops once ring buffer is active.
        """
        if not self.is_connected():
            return
        if self._is_live:
            return
        try:
            self._cam.record(number_of_images=100, mode='ring buffer')
            self._is_live = True
        except Exception as e:
            self._log(f"PCO start_live_grab error: {e}", stderr=True)

    def stop_live_grab(self):
        """Stop ring-buffer / continuous grabbing."""
        if self._cam is not None and self._is_live:
            try:
                self._cam.stop()
            except Exception:
                pass
            self._is_live = False

    def is_live_grab_active(self) -> bool:
        """Return True when ring buffer mode is active."""
        return self._is_live

    def grab_latest_frame(self, timeout_ms: int = 100) -> Optional[np.ndarray]:
        """
        Return the most recently captured frame from ring buffer mode.

        Called by CameraWorker for live display.  Returns None if no frame
        is available or if not in live grab mode.

        Parameters
        ----------
        timeout_ms : int
            Unused; kept for interface compatibility with future implementations.

        Returns
        -------
        np.ndarray or None
        """
        if not self.is_connected() or not self._is_live:
            return None
        try:
            image, _ = self._cam.image()
            return image
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def set_exposure_time_us(self, exposure_us: float):
        """
        Set exposure time in microseconds.

        Stops any active grab session, applies the new exposure, and
        restores the grab session state afterwards.
        """
        if not self.is_connected():
            return
        was_live = self._is_live
        try:
            if self._is_live:
                self._cam.stop()
                self._is_live = False
            self._cam.set_exposure_time(exposure_us * 1e-6)
            self._exposure_time_us = exposure_us
        except Exception as e:
            self._log(f"PCO set_exposure error: {e}", stderr=True)
        finally:
            if was_live:
                try:
                    self._cam.record(number_of_images=100, mode='ring buffer')
                    self._is_live = True
                except Exception:
                    pass

    def set_binning(self, bin_x: int, bin_y: int, mode: str = 'Average'):
        """
        Set hardware binning.

        The mode parameter is accepted for API compatibility with basler but
        is ignored: PCO cameras always sum hardware-binned pixels.

        Stops any active grab session before applying, as the PCO SDK
        requires the camera to be idle when changing binning.
        """
        if not self.is_connected():
            return
        was_live = self._is_live
        try:
            if self._is_live:
                self._cam.stop()
                self._is_live = False
            self._cam.sdk.set_binning(int(bin_x), int(bin_y))
        except Exception as e:
            self._log(f"PCO set_binning error: {e}", stderr=True)
        finally:
            if was_live:
                try:
                    self._cam.record(number_of_images=100, mode='ring buffer')
                    self._is_live = True
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def connect_and_open(
        choice=None,
        exposure_time_us: float = 10000,
        pixel_format=None,
        logger=None,
        verbose: bool = True,
    ) -> Optional['pco_camera']:
        """
        Convenience factory: create, connect, and return a pco_camera instance.

        Returns None if connection fails.
        """
        cam = pco_camera(
            choice=choice,
            exposure_time_us=exposure_time_us,
            pixel_format=pixel_format,
            logger=logger,
            verbose=verbose,
        )
        if cam.connect():
            return cam
        return None

    @staticmethod
    def close_instance(cam_instance: Optional['pco_camera']):
        """Close a pco_camera instance if it is not None."""
        if cam_instance is not None:
            cam_instance.close()


# ============================================================
# Module-level helper functions
# (Same signatures as qdm_basler module-level helpers.)
# ============================================================


def get_current_settings(pco_instance: pco_camera) -> dict:
    """
    Get current camera settings as a dict.

    Returns the same keys as qdm_basler.get_current_settings() so that
    CameraState.update_from_camera_settings() works without modification.

    Returns
    -------
    dict
        Keys: exposure_us, pixel_format, binning_x, binning_y,
        width, height, serial_number, model_name
    """
    if not pco_instance.is_connected():
        raise RuntimeError("Camera is not connected")

    cam = pco_instance._cam

    # Camera type / serial
    try:
        cam_type = cam.sdk.get_camera_type()
        serial = str(cam_type.get('serial', 'unknown'))
        model = str(cam_type.get('camera type', 'PCO camera'))
    except Exception:
        serial = 'unknown'
        model = 'PCO camera'

    # Sensor dimensions
    try:
        desc = cam.sdk.get_camera_description()
        width = desc.get('max. horizontal resolution in pixels', 0)
        height = desc.get('max. vertical resolution in pixels', 0)
    except Exception:
        width = height = 0

    # Binning
    try:
        binning = cam.sdk.get_binning()
        bin_x = binning.get('binning x', 1)
        bin_y = binning.get('binning y', 1)
    except Exception:
        bin_x = bin_y = 1

    return {
        'exposure_us': pco_instance._exposure_time_us,
        'pixel_format': 'Mono16',   # PCO edge always outputs 16-bit
        'binning_x': bin_x,
        'binning_y': bin_y,
        'width': width,
        'height': height,
        'serial_number': serial,
        'model_name': model,
    }


def set_exposure_time(pco_instance: pco_camera, exposure_us: float):
    """
    Set camera exposure time in microseconds.

    Parameters
    ----------
    pco_instance : pco_camera
        Connected pco_camera instance.
    exposure_us : float
        Exposure time in microseconds.
    """
    if not pco_instance.is_connected():
        raise RuntimeError("Camera is not connected")
    pco_instance.set_exposure_time_us(float(exposure_us))


def set_pixel_format(pco_instance: pco_camera, pixel_format: str):
    """
    No-op for PCO cameras (always 16-bit output).

    Accepted for API compatibility with qdm_basler.set_pixel_format().
    """
    pass  # PCO edge cameras output 16-bit regardless of this setting


def set_binning(
    pco_instance: pco_camera,
    binning_x: int,
    binning_y: int,
    mode: str = 'Average',
):
    """
    Set camera hardware binning.

    Parameters
    ----------
    pco_instance : pco_camera
        Connected pco_camera instance.
    binning_x, binning_y : int
        Binning values (1 or 2 for most PCO edge models).
    mode : str, optional
        Accepted for API compatibility; ignored for PCO cameras.
    """
    if not pco_instance.is_connected():
        raise RuntimeError("Camera is not connected")
    pco_instance.set_binning(int(binning_x), int(binning_y), mode)


def get_saturation_threshold(pixel_format: str) -> int:
    """
    Get the saturation threshold for a given pixel format.

    PCO cameras always output Mono16 (16-bit), so the threshold is always
    65535 regardless of the pixel_format argument.

    Parameters
    ----------
    pixel_format : str
        Pixel format string (e.g., 'Mono16', 'Mono12'). For PCO cameras
        this should always be 'Mono16'.

    Returns
    -------
    int
        Maximum pixel value for the format.
    """
    thresholds = {
        'Mono8': 255,
        'Mono10': 1023,
        'Mono10p': 1023,
        'Mono12': 4095,
        'Mono12p': 4095,
        'Mono16': 65535,
    }
    return thresholds.get(pixel_format, 65535)  # default to 16-bit for PCO
