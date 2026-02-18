"""
Shared experiment state for QDM application.
Serves as single source of truth for all experimental parameters and measurements.
"""

from PySide6.QtCore import QObject, Signal


class ExperimentState(QObject):
    """
    Central state management for QDM experiments.

    All windows reference this shared state. Control windows modify it,
    monitoring windows observe it via signals.
    """

    # Laser power monitoring signals
    laser_power_updated = Signal(float, float)  # (timestamp, power_watts)
    data_point_recorded = Signal(dict)  # Standard signal for RealTimeGraph
    laser_acquisition_started = Signal()
    laser_acquisition_stopped = Signal()
    laser_acquisition_paused = Signal()

    # DAQ configuration signals
    daq_config_changed = Signal(dict)  # {device, channel, sample_rate, ...}
    conversion_config_changed = Signal(float, float)  # (slope, intercept)

    # PID controller signals
    pid_connection_changed = Signal(bool)  # True = connected, False = disconnected
    pid_setpoint_changed = Signal(float)
    pid_output_changed = Signal(float)
    pid_error_changed = Signal(float)
    pid_offset_changed = Signal(float)
    pid_p_gain_changed = Signal(float)
    pid_i_time_changed = Signal(float)
    pid_d_time_changed = Signal(float)
    pid_manual_mode_changed = Signal(bool)
    pid_upper_limit_changed = Signal(float)
    pid_lower_limit_changed = Signal(float)
    pid_status_message = Signal(str)  # Status/error messages from PID system

    def __init__(self):
        super().__init__()

        # Current laser power measurement
        self._current_laser_power = 0.0
        self._last_update_time = 0.0

        # Acquisition state
        self._is_acquiring = False
        self._is_paused = False

        # DAQ configuration
        self._daq_device = "Dev3"
        self._daq_channel = "ai0"
        self._sample_rate = 2.0
        self._batch_size = 1  # Number of samples to accumulate before processing
        self._voltage_range_min = -10.0
        self._voltage_range_max = 10.0

        # Conversion configuration (voltage to power)
        # power = voltage * slope + intercept
        self._conversion_slope = 0.9527
        self._conversion_intercept = 0.0036

        # Data saving configuration
        self._save_data = False
        self._save_dir = r"E:\MTB project\CW ODMR"
        self._save_subfolder = ""

        # PID controller configuration
        self._pid_com_port = 'ASRL3::INSTR'
        self._pid_sim900_port = 1
        self._pid_is_connected = False

        # PID parameters
        self._pid_setpoint = 0.0
        self._pid_output = 0.0
        self._pid_error = 0.0
        self._pid_offset = 0.0
        self._pid_p_gain = 1.0
        self._pid_i_time = 1.0
        self._pid_d_time = 0.0
        self._pid_manual_mode = False
        self._pid_upper_limit = 10.0
        self._pid_lower_limit = -10.0

        # PID monitoring
        self._pid_is_monitoring = False
        self._pid_monitor_interval = 0.5

    # === Laser Power Properties ===

    @property
    def current_laser_power(self):
        """Current laser power in watts."""
        return self._current_laser_power

    def update_laser_power(self, timestamp: float, power: float):
        """Update laser power measurement and emit signal."""
        self._current_laser_power = power
        self._last_update_time = timestamp
        self.laser_power_updated.emit(timestamp, power)
        # Also emit standard data_point_recorded for RealTimeGraph
        self.data_point_recorded.emit({'timestamp': timestamp, 'value': power})

    @property
    def last_update_time(self):
        """Timestamp of last laser power update."""
        return self._last_update_time

    # === Acquisition State Properties ===

    @property
    def is_acquiring(self):
        """Whether laser power acquisition is running."""
        return self._is_acquiring

    @is_acquiring.setter
    def is_acquiring(self, value: bool):
        self._is_acquiring = value
        if value:
            self.laser_acquisition_started.emit()
        else:
            self.laser_acquisition_stopped.emit()

    @property
    def is_paused(self):
        """Whether laser power acquisition is paused."""
        return self._is_paused

    @is_paused.setter
    def is_paused(self, value: bool):
        self._is_paused = value
        if value:
            self.laser_acquisition_paused.emit()

    # === DAQ Configuration Properties ===

    @property
    def daq_device(self):
        return self._daq_device

    @daq_device.setter
    def daq_device(self, value: str):
        self._daq_device = value
        self._emit_daq_config()

    @property
    def daq_channel(self):
        return self._daq_channel

    @daq_channel.setter
    def daq_channel(self, value: str):
        self._daq_channel = value
        self._emit_daq_config()

    @property
    def sample_rate(self):
        return self._sample_rate

    @sample_rate.setter
    def sample_rate(self, value: float):
        self._sample_rate = value
        self._emit_daq_config()

    @property
    def batch_size(self):
        return self._batch_size

    @batch_size.setter
    def batch_size(self, value: int):
        self._batch_size = max(1, int(value))  # Ensure at least 1
        self._emit_daq_config()

    @property
    def voltage_range(self):
        return (self._voltage_range_min, self._voltage_range_max)

    @voltage_range.setter
    def voltage_range(self, value: tuple):
        self._voltage_range_min, self._voltage_range_max = value
        self._emit_daq_config()

    def _emit_daq_config(self):
        """Emit DAQ configuration changed signal."""
        config = {
            'device': self._daq_device,
            'channel': self._daq_channel,
            'sample_rate': self._sample_rate,
            'batch_size': self._batch_size,
            'voltage_range': (self._voltage_range_min, self._voltage_range_max)
        }
        self.daq_config_changed.emit(config)

    # === Conversion Configuration Properties ===

    @property
    def conversion_slope(self):
        return self._conversion_slope

    @conversion_slope.setter
    def conversion_slope(self, value: float):
        self._conversion_slope = value
        self.conversion_config_changed.emit(self._conversion_slope, self._conversion_intercept)

    @property
    def conversion_intercept(self):
        return self._conversion_intercept

    @conversion_intercept.setter
    def conversion_intercept(self, value: float):
        self._conversion_intercept = value
        self.conversion_config_changed.emit(self._conversion_slope, self._conversion_intercept)

    def set_conversion(self, slope: float, intercept: float):
        """Set both conversion parameters at once."""
        self._conversion_slope = slope
        self._conversion_intercept = intercept
        self.conversion_config_changed.emit(slope, intercept)

    # === Data Saving Configuration ===

    @property
    def save_data(self):
        return self._save_data

    @save_data.setter
    def save_data(self, value: bool):
        self._save_data = value

    @property
    def save_dir(self):
        return self._save_dir

    @save_dir.setter
    def save_dir(self, value: str):
        self._save_dir = value

    @property
    def save_subfolder(self):
        return self._save_subfolder

    @save_subfolder.setter
    def save_subfolder(self, value: str):
        self._save_subfolder = value

    # === Helper Methods ===

    def get_daq_config(self):
        """Get all DAQ configuration as a dictionary."""
        return {
            'device': self._daq_device,
            'channel': self._daq_channel,
            'sample_rate': self._sample_rate,
            'batch_size': self._batch_size,
            'voltage_range': (self._voltage_range_min, self._voltage_range_max),
            'conversion': (self._conversion_slope, self._conversion_intercept)
        }

    def get_save_config(self):
        """Get data saving configuration."""
        return {
            'save_data': self._save_data,
            'save_dir': self._save_dir,
            'subfolder': self._save_subfolder
        }

    # === PID Controller Properties ===

    @property
    def pid_com_port(self):
        return self._pid_com_port

    @pid_com_port.setter
    def pid_com_port(self, value: str):
        self._pid_com_port = value

    @property
    def pid_sim900_port(self):
        return self._pid_sim900_port

    @pid_sim900_port.setter
    def pid_sim900_port(self, value: int):
        self._pid_sim900_port = int(value)

    @property
    def pid_is_connected(self):
        return self._pid_is_connected

    @pid_is_connected.setter
    def pid_is_connected(self, value: bool):
        self._pid_is_connected = value
        self.pid_connection_changed.emit(value)

    @property
    def pid_setpoint(self):
        return self._pid_setpoint

    @pid_setpoint.setter
    def pid_setpoint(self, value: float):
        self._pid_setpoint = float(value)
        self.pid_setpoint_changed.emit(self._pid_setpoint)

    @property
    def pid_output(self):
        return self._pid_output

    @pid_output.setter
    def pid_output(self, value: float):
        self._pid_output = float(value)
        self.pid_output_changed.emit(self._pid_output)

    @property
    def pid_error(self):
        return self._pid_error

    @pid_error.setter
    def pid_error(self, value: float):
        self._pid_error = float(value)
        self.pid_error_changed.emit(self._pid_error)

    @property
    def pid_offset(self):
        return self._pid_offset

    @pid_offset.setter
    def pid_offset(self, value: float):
        self._pid_offset = float(value)
        self.pid_offset_changed.emit(self._pid_offset)

    @property
    def pid_p_gain(self):
        return self._pid_p_gain

    @pid_p_gain.setter
    def pid_p_gain(self, value: float):
        self._pid_p_gain = float(value)
        self.pid_p_gain_changed.emit(self._pid_p_gain)

    @property
    def pid_i_time(self):
        return self._pid_i_time

    @pid_i_time.setter
    def pid_i_time(self, value: float):
        self._pid_i_time = float(value)
        self.pid_i_time_changed.emit(self._pid_i_time)

    @property
    def pid_d_time(self):
        return self._pid_d_time

    @pid_d_time.setter
    def pid_d_time(self, value: float):
        self._pid_d_time = float(value)
        self.pid_d_time_changed.emit(self._pid_d_time)

    @property
    def pid_manual_mode(self):
        return self._pid_manual_mode

    @pid_manual_mode.setter
    def pid_manual_mode(self, value: bool):
        self._pid_manual_mode = bool(value)
        self.pid_manual_mode_changed.emit(self._pid_manual_mode)

    @property
    def pid_upper_limit(self):
        return self._pid_upper_limit

    @pid_upper_limit.setter
    def pid_upper_limit(self, value: float):
        self._pid_upper_limit = float(value)
        self.pid_upper_limit_changed.emit(self._pid_upper_limit)

    @property
    def pid_lower_limit(self):
        return self._pid_lower_limit

    @pid_lower_limit.setter
    def pid_lower_limit(self, value: float):
        self._pid_lower_limit = float(value)
        self.pid_lower_limit_changed.emit(self._pid_lower_limit)

    @property
    def pid_is_monitoring(self):
        return self._pid_is_monitoring

    @pid_is_monitoring.setter
    def pid_is_monitoring(self, value: bool):
        self._pid_is_monitoring = bool(value)

    @property
    def pid_monitor_interval(self):
        return self._pid_monitor_interval

    @pid_monitor_interval.setter
    def pid_monitor_interval(self, value: float):
        self._pid_monitor_interval = float(value)

    def update_pid_from_hardware(self, status_dict):
        """
        Update PID state from hardware status dictionary.

        Parameters
        ----------
        status_dict : dict
            Dictionary from SIM960Controller.get_status()
        """
        if 'manual_mode' in status_dict and status_dict['manual_mode'] is not None:
            self.pid_manual_mode = status_dict['manual_mode']

        if 'setpoint' in status_dict and status_dict['setpoint'] is not None:
            self.pid_setpoint = status_dict['setpoint']

        if 'output_voltage' in status_dict and status_dict['output_voltage'] is not None:
            self.pid_output = status_dict['output_voltage']

        if 'offset' in status_dict and status_dict['offset'] is not None:
            self.pid_offset = status_dict['offset']

        if 'proportional_gain' in status_dict and status_dict['proportional_gain'] is not None:
            self.pid_p_gain = status_dict['proportional_gain']

        if 'integral_time' in status_dict and status_dict['integral_time'] is not None:
            self.pid_i_time = status_dict['integral_time']

        if 'derivative_time' in status_dict and status_dict['derivative_time'] is not None:
            self.pid_d_time = status_dict['derivative_time']

        if 'upper_limit' in status_dict and status_dict['upper_limit'] is not None:
            self.pid_upper_limit = status_dict['upper_limit']

        if 'lower_limit' in status_dict and status_dict['lower_limit'] is not None:
            self.pid_lower_limit = status_dict['lower_limit']
