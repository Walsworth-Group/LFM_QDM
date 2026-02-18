"""
PID Controller State Management

Shared state for SIM960 PID Controller application.
Follows architecture defined in claude_app.md.
"""

from PySide6.QtCore import QObject, Signal


class PIDState(QObject):
    """
    Centralized state for SIM960 PID controller.

    All parameter changes emit signals for UI synchronization.
    """

    # Connection state signals
    connection_changed = Signal(bool)  # True = connected, False = disconnected
    connection_error = Signal(str)  # Error message

    # PID parameter signals
    setpoint_changed = Signal(float)
    output_changed = Signal(float)
    error_signal_changed = Signal(float)
    input_value_changed = Signal(float)
    offset_changed = Signal(float)

    # PID gains signals
    p_gain_changed = Signal(float)
    i_time_changed = Signal(float)
    d_time_changed = Signal(float)

    # Control enable signals
    manual_mode_changed = Signal(bool)
    p_control_changed = Signal(bool)
    i_control_changed = Signal(bool)
    d_control_changed = Signal(bool)

    # Limits signals
    upper_limit_changed = Signal(float)

    # Monitoring signals
    data_point_recorded = Signal(dict)  # For RealTimeGraph: {'timestamp': t, 'value': v}
    status_message = Signal(str)  # For message log

    # Settings signals
    settings_changed = Signal()

    def __init__(self):
        super().__init__()

        # Connection settings
        self._com_port = 'ASRL3::INSTR'  # Default
        self._sim900_port = 1  # SIM960 module port
        self._is_connected = False

        # PID parameters
        self._setpoint = 0.0
        self._output = 0.0
        self._error = 0.0
        self._input_value = 0.0
        self._offset = 0.0

        # PID gains
        self._p_gain = 1.0
        self._i_time = 1.0
        self._d_time = 0.0

        # Control enables
        self._manual_mode = False
        self._p_control = True
        self._i_control = True
        self._d_control = False

        # Limits
        self._upper_limit = 10.0

        # Monitoring
        self._is_monitoring = False
        self._monitor_interval = 0.5  # seconds

    # === Connection Properties ===

    @property
    def com_port(self):
        return self._com_port

    @com_port.setter
    def com_port(self, value):
        self._com_port = value
        self.settings_changed.emit()

    @property
    def sim900_port(self):
        return self._sim900_port

    @sim900_port.setter
    def sim900_port(self, value):
        self._sim900_port = int(value)
        self.settings_changed.emit()

    @property
    def is_connected(self):
        return self._is_connected

    @is_connected.setter
    def is_connected(self, value):
        self._is_connected = value
        self.connection_changed.emit(value)

    # === PID Parameter Properties ===

    @property
    def setpoint(self):
        return self._setpoint

    @setpoint.setter
    def setpoint(self, value):
        self._setpoint = float(value)
        self.setpoint_changed.emit(self._setpoint)

    @property
    def output(self):
        return self._output

    @output.setter
    def output(self, value):
        self._output = float(value)
        self.output_changed.emit(self._output)

    @property
    def error(self):
        return self._error

    @error.setter
    def error(self, value):
        self._error = float(value)
        self.error_signal_changed.emit(self._error)

    @property
    def input_value(self):
        return self._input_value

    @input_value.setter
    def input_value(self, value):
        self._input_value = float(value)
        self.input_value_changed.emit(self._input_value)

    @property
    def offset(self):
        return self._offset

    @offset.setter
    def offset(self, value):
        self._offset = float(value)
        self.offset_changed.emit(self._offset)

    # === PID Gain Properties ===

    @property
    def p_gain(self):
        return self._p_gain

    @p_gain.setter
    def p_gain(self, value):
        self._p_gain = float(value)
        self.p_gain_changed.emit(self._p_gain)

    @property
    def i_time(self):
        return self._i_time

    @i_time.setter
    def i_time(self, value):
        self._i_time = float(value)
        self.i_time_changed.emit(self._i_time)

    @property
    def d_time(self):
        return self._d_time

    @d_time.setter
    def d_time(self, value):
        self._d_time = float(value)
        self.d_time_changed.emit(self._d_time)

    # === Control Enable Properties ===

    @property
    def manual_mode(self):
        return self._manual_mode

    @manual_mode.setter
    def manual_mode(self, value):
        self._manual_mode = bool(value)
        self.manual_mode_changed.emit(self._manual_mode)

    @property
    def p_control(self):
        return self._p_control

    @p_control.setter
    def p_control(self, value):
        self._p_control = bool(value)
        self.p_control_changed.emit(self._p_control)

    @property
    def i_control(self):
        return self._i_control

    @i_control.setter
    def i_control(self, value):
        self._i_control = bool(value)
        self.i_control_changed.emit(self._i_control)

    @property
    def d_control(self):
        return self._d_control

    @d_control.setter
    def d_control(self, value):
        self._d_control = bool(value)
        self.d_control_changed.emit(self._d_control)

    # === Limit Properties ===

    @property
    def upper_limit(self):
        return self._upper_limit

    @upper_limit.setter
    def upper_limit(self, value):
        self._upper_limit = float(value)
        self.upper_limit_changed.emit(self._upper_limit)

    # === Monitoring Properties ===

    @property
    def is_monitoring(self):
        return self._is_monitoring

    @is_monitoring.setter
    def is_monitoring(self, value):
        self._is_monitoring = bool(value)

    @property
    def monitor_interval(self):
        return self._monitor_interval

    @monitor_interval.setter
    def monitor_interval(self, value):
        self._monitor_interval = float(value)

    # === Utility Methods ===

    def update_all_from_hardware(self, status_dict):
        """
        Update all state values from hardware status dictionary.

        Parameters
        ----------
        status_dict : dict
            Dictionary from SIM960Controller.get_status()
        """
        # Update parameters (this will emit signals)
        if 'manual_mode' in status_dict and status_dict['manual_mode'] is not None:
            self.manual_mode = status_dict['manual_mode']

        if 'setpoint' in status_dict and status_dict['setpoint'] is not None:
            self.setpoint = status_dict['setpoint']

        if 'output_voltage' in status_dict and status_dict['output_voltage'] is not None:
            self.output = status_dict['output_voltage']

        if 'offset' in status_dict and status_dict['offset'] is not None:
            self.offset = status_dict['offset']

        if 'proportional_gain' in status_dict and status_dict['proportional_gain'] is not None:
            self.p_gain = status_dict['proportional_gain']

        if 'integral_time' in status_dict and status_dict['integral_time'] is not None:
            self.i_time = status_dict['integral_time']

        if 'derivative_time' in status_dict and status_dict['derivative_time'] is not None:
            self.d_time = status_dict['derivative_time']

        if 'upper_limit' in status_dict and status_dict['upper_limit'] is not None:
            self.upper_limit = status_dict['upper_limit']

        if 'p_control_enable' in status_dict and status_dict['p_control_enable'] is not None:
            self.p_control = status_dict['p_control_enable']

        if 'i_control_enable' in status_dict and status_dict['i_control_enable'] is not None:
            self.i_control = status_dict['i_control_enable']

        if 'd_control_enable' in status_dict and status_dict['d_control_enable'] is not None:
            self.d_control = status_dict['d_control_enable']

    def log_message(self, message):
        """Emit a status message for the log display."""
        self.status_message.emit(message)
