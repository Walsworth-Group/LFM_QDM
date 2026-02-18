from pypylon import pylon
import numpy as np
import sys
from typing import Callable, Optional

class basler:
    """
    A context manager class for controlling a Basler camera using pypylon.

    New:
      - logger: callable like print or tqdm.write
      - verbose: controls whether informational messages are emitted
    """

    def __init__(
        self,
        choice=None,
        exposure_time_us=10000,
        pixel_format=None,
        logger: Optional[Callable[[str], None]] = None,
        verbose: bool = True,
    ):
        self._choice = choice
        self._exposure_time_us = exposure_time_us
        self._pixel_format = pixel_format

        self._logger = logger
        self._verbose = verbose

        self._device_info = None
        self._camera = None

    def _log(self, msg: str, *, stderr: bool = False):
        if not self._verbose:
            return
        if self._logger is None:
            if stderr:
                print(msg, file=sys.stderr)
            else:
                print(msg)
        else:
            # tqdm.write() is fine for both normal and "stderr-like" messages in notebooks
            self._logger(msg)

    def __enter__(self):
        if self._camera is None:
            self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def is_connected(self):
        return self._camera is not None and self._camera.IsOpen()

    def connect(self):
        try:
            self._device_info = self._get_selected_camera_device(choice=self._choice)
            if self._device_info is None:
                return False

            self._open_camera(self._device_info)
            return True

        except (RuntimeError, ValueError) as e:
            self._log(f"Connection Failed: {e}", stderr=True)
            self._camera = None
            self._device_info = None
            return False

    def close(self):
        if self._camera:
            if self._camera.IsGrabbing():
                self._camera.StopGrabbing()
            if self._camera.IsOpen():
                self._camera.Close()

            self._log("Camera closed.")
            self._camera = None
            self._device_info = None

    def grab_frames(self, n_frames=100, quiet: bool = True):
        """
        Grabs n_frames from the open camera, returns averaged image.

        quiet=True suppresses routine messages even if verbose=True.
        """
        if not self.is_connected():
            self._log("Error: Camera is not connected. Call .connect() first.")
            return None

        camera = self._camera

        if not camera.IsGrabbing():
            camera.StartGrabbing(pylon.GrabStrategy_LatestImages, pylon.GrabLoop_ProvidedByUser)
            if not quiet:
                self._log("Basler: grabbing started.")

        accumulator = None
        grabbed_count = 0
        img = None

        try:
            while grabbed_count < n_frames:
                grab_result = camera.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
                if grab_result.GrabSucceeded():
                    img = grab_result.Array
                    if accumulator is None:
                        accumulator = np.zeros_like(img, dtype=np.float64)
                        if not quiet:
                            self._log(f"Basler: first frame {img.shape}, dtype {img.dtype}")
                    accumulator += img
                    grabbed_count += 1
                grab_result.Release()

        except pylon.TimeoutException as e:
            self._log(f"Basler: grab timeout: {e}")
            return None

        if grabbed_count == 0 or img is None:
            self._log("Basler: no frames were successfully grabbed.")
            return None

        avg_image = (accumulator / grabbed_count).astype(img.dtype)
        if not quiet:
            self._log(f"Basler: averaged {grabbed_count} frames.")
        return avg_image

    def flush_buffer(self):
        """Stops grabbing so that any frames buffered during a delay are discarded.
        grab_frames() will restart grabbing automatically on the next call."""
        if self._camera and self._camera.IsGrabbing():
            self._camera.StopGrabbing()

    # ---------------- private helpers ----------------

    def _list_available_cameras(self):
        factory = pylon.TlFactory.GetInstance()
        devices = factory.EnumerateDevices()
        if len(devices) == 0:
            raise RuntimeError("No Basler cameras detected.")

        self._log("Detected Basler cameras:")
        self._log("-" * 60)
        for i, dev in enumerate(devices):
            self._log(
                f"[{i}] Serial: {dev.GetSerialNumber():>12} | Model: {dev.GetModelName():<20} | "
                f"DeviceClass: {dev.GetDeviceClass()}"
            )
        self._log("-" * 60)
        return devices

    def _select_camera(self, devices, choice):
        if choice is None:
            choice = input("Enter index or serial number of desired camera: ").strip()

        choice_str = str(choice).strip()

        for dev in devices:
            if dev.GetSerialNumber().strip() == choice_str:
                return dev

        if choice_str.isdigit():
            idx = int(choice_str)
            if 0 <= idx < len(devices):
                return devices[idx]

        valid_indices = f"0 to {len(devices) - 1}" if len(devices) > 0 else "None"
        raise ValueError(
            f"Camera with serial '{choice_str}' not found. "
            f"'{choice}' is also not a valid index ({valid_indices})."
        )

    def _get_selected_camera_device(self, choice=None):
        try:
            devices = self._list_available_cameras()
            selected_device = self._select_camera(devices, choice=choice)

            self._log(
                f"Successfully connected to camera:\n"
                f"  Serial: {selected_device.GetSerialNumber()}\n"
                f"  Model: {selected_device.GetModelName()}"
            )
            return selected_device

        except RuntimeError as e:
            self._log(f"Error: {e}")
            return None
        except ValueError as e:
            self._log(f"Selection Error: {e}")
            return None

    def _open_camera(self, camera_device):
        camera = pylon.InstantCamera(pylon.TlFactory.GetInstance().CreateDevice(camera_device))
        camera.Open()

        camera.ExposureAuto = 'Off'
        camera.GainAuto = 'Off'

        if self._pixel_format:
            camera.PixelFormat = self._pixel_format
        else:
            pf_value = camera.PixelFormat.GetValue()
            if pf_value in ['Mono12', 'Mono12p', 'Mono10', 'Mono10p', 'Mono16']:
                camera.PixelFormat = 'Mono12'
            else:
                camera.PixelFormat = 'Mono8'

        camera.ExposureTime = self._exposure_time_us

        self._log("--- Camera Initialized ---")
        self._log(f"Camera {camera.DeviceSerialNumber()} opened.")
        self._log(f"ExposureTime = {camera.ExposureTime.GetValue()} µs | PixelFormat = {camera.PixelFormat.GetValue()}")
        self._log("--------------------------")

        self._camera = camera

    # ---------------- static helpers ----------------

    @staticmethod
    def connect_and_open(choice=None, exposure_time_us=10000, pixel_format=None, logger=None, verbose=True):
        cam = basler(
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
    def close_instance(cam_instance):
        if cam_instance:
            cam_instance.close()


# ============ Additional Helper Functions ============
# Added 2026-02-14 for camera_app.py GUI application


def get_current_settings(basler_instance):
    """
    Get current camera settings as dict.

    Parameters
    ----------
    basler_instance : basler
        Connected basler camera instance

    Returns
    -------
    dict
        Dictionary with keys: exposure_us, pixel_format, binning_x, binning_y,
        width, height, serial_number, model_name
    """
    if not basler_instance.is_connected():
        raise RuntimeError("Camera is not connected")

    camera = basler_instance._camera

    # Try to get binning values, default to 1 if not available
    try:
        binning_x = camera.BinningHorizontal.GetValue()
    except:
        binning_x = 1

    try:
        binning_y = camera.BinningVertical.GetValue()
    except:
        binning_y = 1

    return {
        'exposure_us': camera.ExposureTime.GetValue(),
        'pixel_format': camera.PixelFormat.GetValue(),
        'binning_x': binning_x,
        'binning_y': binning_y,
        'width': camera.Width.GetValue(),
        'height': camera.Height.GetValue(),
        'serial_number': camera.DeviceSerialNumber.GetValue(),
        'model_name': camera.DeviceModelName.GetValue()
    }


def set_exposure_time(basler_instance, exposure_us):
    """
    Set camera exposure time in microseconds.

    Parameters
    ----------
    basler_instance : basler
        Connected basler camera instance
    exposure_us : float
        Exposure time in microseconds
    """
    if not basler_instance.is_connected():
        raise RuntimeError("Camera is not connected")

    basler_instance._camera.ExposureTime.SetValue(float(exposure_us))


def set_pixel_format(basler_instance, pixel_format):
    """
    Set camera pixel format.

    Parameters
    ----------
    basler_instance : basler
        Connected basler camera instance
    pixel_format : str
        Pixel format ('Mono8', 'Mono12', 'Mono12p', etc.)
    """
    if not basler_instance.is_connected():
        raise RuntimeError("Camera is not connected")

    basler_instance._camera.PixelFormat.SetValue(pixel_format)


def set_binning(basler_instance, binning_x, binning_y, mode='Average'):
    """
    Set camera binning.

    Parameters
    ----------
    basler_instance : basler
        Connected basler camera instance
    binning_x, binning_y : int
        Binning values (1-4 typically)
    mode : str, optional
        'Average' or 'Sum' (default: 'Average')
    """
    if not basler_instance.is_connected():
        raise RuntimeError("Camera is not connected")

    camera = basler_instance._camera

    # Set binning mode if available (GetAccessMode() == 4 means writable)
    try:
        if camera.BinningHorizontalMode.GetAccessMode() == 4:
            camera.BinningHorizontalMode.SetValue(mode)
    except:
        pass  # Binning mode not available on this camera

    try:
        if camera.BinningVerticalMode.GetAccessMode() == 4:
            camera.BinningVerticalMode.SetValue(mode)
    except:
        pass

    # Set binning values
    camera.BinningHorizontal.SetValue(int(binning_x))
    camera.BinningVertical.SetValue(int(binning_y))


def get_saturation_threshold(pixel_format):
    """
    Get saturation threshold for pixel format.

    Parameters
    ----------
    pixel_format : str
        Pixel format ('Mono8', 'Mono12', etc.)

    Returns
    -------
    int
        Maximum pixel value for the format
    """
    thresholds = {
        'Mono8': 255,
        'Mono12': 4095,
        'Mono12p': 4095,
        'Mono10': 1023,
        'Mono10p': 1023,
        'Mono16': 65535
    }
    return thresholds.get(pixel_format, 255)
