"""
Camera state management for Basler camera streaming application.

Extends ExperimentState with camera-specific signals and properties.
"""

from PySide6.QtCore import QObject, Signal
import numpy as np


class CameraState(QObject):
    """
    State management for Basler camera streaming.

    Follows the ExperimentState pattern for multi-app compatibility.
    All camera-related properties emit signals when changed.
    """

    # Frame streaming signals
    camera_frame_acquired = Signal(np.ndarray, int)  # (frame, frame_count)
    camera_averaged_frame_ready = Signal(np.ndarray, int)  # (avg_frame, avg_count)
    camera_saturation_detected = Signal(bool, float)  # (is_saturated, max_pixel_value)

    # Camera connection/control signals
    camera_connection_changed = Signal(bool, str)  # (connected, serial_number)
    camera_streaming_changed = Signal(bool)  # is_streaming
    camera_exposure_changed = Signal(float)  # microseconds
    camera_binning_changed = Signal(int, int)  # (binX, binY)
    camera_pixel_format_changed = Signal(str)  # pixel_format

    # Display control signals
    camera_live_display_enabled_changed = Signal(bool)
    camera_averaged_display_enabled_changed = Signal(bool)
    camera_flip_changed = Signal(bool, bool)  # (flip_horizontal, flip_vertical)

    # Save operation signals
    camera_save_progress = Signal(int, int)  # (current, total)
    camera_save_completed = Signal(str)  # filepath
    camera_status_message = Signal(str)  # status/error messages

    def __init__(self):
        super().__init__()

        # Camera configuration
        self._camera_serial_number = "23049069"
        self._camera_exposure_us = 10000.0
        self._camera_binning_x = 1
        self._camera_binning_y = 1
        self._camera_binning_mode = "Average"  # or "Sum"
        self._camera_pixel_format = "Mono12"  # Mono8/Mono12/Mono12p

        # Streaming state
        self._camera_is_connected = False
        self._camera_is_streaming = False
        self._camera_live_display_enabled = True
        self._camera_averaged_display_enabled = True

        # Image orientation
        self._camera_flip_horizontal = False
        self._camera_flip_vertical = False

        # Averaging configuration
        self._camera_num_frames_to_average = 100
        self._camera_live_averaging_enabled = True

        # Save configuration
        self._camera_save_dir = r"E:\MTB project\CW ODMR"
        self._camera_save_subfolder = "camera_data"
        self._camera_save_filename_suffix = ""
        self._camera_save_append_timestamp = True
        self._camera_save_format = "npy"  # "npy", "tiff", or "jpg"
        self._camera_num_images_to_save = 10
        self._camera_is_saving = False

    # === Camera Configuration Properties ===

    @property
    def camera_serial_number(self):
        return self._camera_serial_number

    @camera_serial_number.setter
    def camera_serial_number(self, value: str):
        self._camera_serial_number = str(value)

    @property
    def camera_exposure_us(self):
        return self._camera_exposure_us

    @camera_exposure_us.setter
    def camera_exposure_us(self, value: float):
        self._camera_exposure_us = float(value)
        self.camera_exposure_changed.emit(self._camera_exposure_us)

    @property
    def camera_binning_x(self):
        return self._camera_binning_x

    @camera_binning_x.setter
    def camera_binning_x(self, value: int):
        self._camera_binning_x = int(value)
        self.camera_binning_changed.emit(self._camera_binning_x, self._camera_binning_y)

    @property
    def camera_binning_y(self):
        return self._camera_binning_y

    @camera_binning_y.setter
    def camera_binning_y(self, value: int):
        self._camera_binning_y = int(value)
        self.camera_binning_changed.emit(self._camera_binning_x, self._camera_binning_y)

    def set_camera_binning(self, binning_x: int, binning_y: int):
        """Set both binning values at once (single signal emission)."""
        self._camera_binning_x = int(binning_x)
        self._camera_binning_y = int(binning_y)
        self.camera_binning_changed.emit(self._camera_binning_x, self._camera_binning_y)

    @property
    def camera_binning_mode(self):
        return self._camera_binning_mode

    @camera_binning_mode.setter
    def camera_binning_mode(self, value: str):
        self._camera_binning_mode = str(value)

    @property
    def camera_pixel_format(self):
        return self._camera_pixel_format

    @camera_pixel_format.setter
    def camera_pixel_format(self, value: str):
        self._camera_pixel_format = str(value)
        self.camera_pixel_format_changed.emit(self._camera_pixel_format)

    # === Streaming State Properties ===

    @property
    def camera_is_connected(self):
        return self._camera_is_connected

    @camera_is_connected.setter
    def camera_is_connected(self, value: bool):
        self._camera_is_connected = bool(value)
        self.camera_connection_changed.emit(self._camera_is_connected, self._camera_serial_number)

    @property
    def camera_is_streaming(self):
        return self._camera_is_streaming

    @camera_is_streaming.setter
    def camera_is_streaming(self, value: bool):
        self._camera_is_streaming = bool(value)
        self.camera_streaming_changed.emit(self._camera_is_streaming)

    @property
    def camera_live_display_enabled(self):
        return self._camera_live_display_enabled

    @camera_live_display_enabled.setter
    def camera_live_display_enabled(self, value: bool):
        self._camera_live_display_enabled = bool(value)
        self.camera_live_display_enabled_changed.emit(self._camera_live_display_enabled)

    @property
    def camera_averaged_display_enabled(self):
        return self._camera_averaged_display_enabled

    @camera_averaged_display_enabled.setter
    def camera_averaged_display_enabled(self, value: bool):
        self._camera_averaged_display_enabled = bool(value)
        self.camera_averaged_display_enabled_changed.emit(self._camera_averaged_display_enabled)

    @property
    def camera_flip_horizontal(self):
        return self._camera_flip_horizontal

    @camera_flip_horizontal.setter
    def camera_flip_horizontal(self, value: bool):
        self._camera_flip_horizontal = bool(value)
        self.camera_flip_changed.emit(self._camera_flip_horizontal, self._camera_flip_vertical)

    @property
    def camera_flip_vertical(self):
        return self._camera_flip_vertical

    @camera_flip_vertical.setter
    def camera_flip_vertical(self, value: bool):
        self._camera_flip_vertical = bool(value)
        self.camera_flip_changed.emit(self._camera_flip_horizontal, self._camera_flip_vertical)

    # === Averaging Configuration Properties ===

    @property
    def camera_num_frames_to_average(self):
        return self._camera_num_frames_to_average

    @camera_num_frames_to_average.setter
    def camera_num_frames_to_average(self, value: int):
        self._camera_num_frames_to_average = max(1, int(value))  # Ensure at least 1

    @property
    def camera_live_averaging_enabled(self):
        return self._camera_live_averaging_enabled

    @camera_live_averaging_enabled.setter
    def camera_live_averaging_enabled(self, value: bool):
        self._camera_live_averaging_enabled = bool(value)

    # === Save Configuration Properties ===

    @property
    def camera_save_dir(self):
        return self._camera_save_dir

    @camera_save_dir.setter
    def camera_save_dir(self, value: str):
        self._camera_save_dir = str(value)

    @property
    def camera_save_subfolder(self):
        return self._camera_save_subfolder

    @camera_save_subfolder.setter
    def camera_save_subfolder(self, value: str):
        self._camera_save_subfolder = str(value)

    @property
    def camera_save_filename_suffix(self):
        return self._camera_save_filename_suffix

    @camera_save_filename_suffix.setter
    def camera_save_filename_suffix(self, value: str):
        self._camera_save_filename_suffix = str(value)

    @property
    def camera_save_append_timestamp(self):
        return self._camera_save_append_timestamp

    @camera_save_append_timestamp.setter
    def camera_save_append_timestamp(self, value: bool):
        self._camera_save_append_timestamp = bool(value)

    @property
    def camera_save_format(self):
        return self._camera_save_format

    @camera_save_format.setter
    def camera_save_format(self, value: str):
        if value in ['npy', 'tiff', 'jpg']:
            self._camera_save_format = str(value)
        else:
            self._camera_save_format = 'npy'

    @property
    def camera_num_images_to_save(self):
        return self._camera_num_images_to_save

    @camera_num_images_to_save.setter
    def camera_num_images_to_save(self, value: int):
        self._camera_num_images_to_save = max(1, int(value))

    @property
    def camera_is_saving(self):
        return self._camera_is_saving

    @camera_is_saving.setter
    def camera_is_saving(self, value: bool):
        self._camera_is_saving = bool(value)

    # === Helper Methods ===

    def update_from_camera_settings(self, settings_dict):
        """
        Update state from camera settings dictionary.

        Parameters
        ----------
        settings_dict : dict
            Dictionary from get_current_settings() in qdm_basler.py
        """
        if 'exposure_us' in settings_dict:
            self._camera_exposure_us = settings_dict['exposure_us']
            self.camera_exposure_changed.emit(self._camera_exposure_us)

        if 'pixel_format' in settings_dict:
            self._camera_pixel_format = settings_dict['pixel_format']
            self.camera_pixel_format_changed.emit(self._camera_pixel_format)

        if 'binning_x' in settings_dict and 'binning_y' in settings_dict:
            self._camera_binning_x = settings_dict['binning_x']
            self._camera_binning_y = settings_dict['binning_y']
            self.camera_binning_changed.emit(self._camera_binning_x, self._camera_binning_y)

    def get_config(self):
        """Get all camera configuration as dictionary for saving."""
        return {
            'camera_serial_number': self._camera_serial_number,
            'camera_exposure_us': self._camera_exposure_us,
            'camera_binning_x': self._camera_binning_x,
            'camera_binning_y': self._camera_binning_y,
            'camera_binning_mode': self._camera_binning_mode,
            'camera_pixel_format': self._camera_pixel_format,
            'camera_num_frames_to_average': self._camera_num_frames_to_average,
            'camera_live_display_enabled': self._camera_live_display_enabled,
            'camera_averaged_display_enabled': self._camera_averaged_display_enabled,
            'camera_live_averaging_enabled': self._camera_live_averaging_enabled,
            'camera_flip_horizontal': self._camera_flip_horizontal,
            'camera_flip_vertical': self._camera_flip_vertical,
            'camera_save_dir': self._camera_save_dir,
            'camera_save_subfolder': self._camera_save_subfolder,
            'camera_save_filename_suffix': self._camera_save_filename_suffix,
            'camera_save_append_timestamp': self._camera_save_append_timestamp,
            'camera_save_format': self._camera_save_format,
            'camera_num_images_to_save': self._camera_num_images_to_save
        }

    def load_config(self, config_dict):
        """Load configuration from dictionary."""
        for key, value in config_dict.items():
            if hasattr(self, key):
                setattr(self, key, value)
