"""
PID Controller Worker Thread

Handles non-blocking hardware communication with SIM960 PID controller.
"""

import sys
import time
from pathlib import Path
from PySide6.QtCore import QThread, Signal, Slot

# Add parent directory to path to import qdm modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from qdm_srs_sim900 import SIM900Controller, SIM960Controller


class PIDWorker(QThread):
    """
    Worker thread for PID controller hardware communication.

    Runs hardware I/O in a separate thread to avoid blocking the UI.
    Communicates with main thread via signals.
    """

    # Signals for hardware responses
    connection_established = Signal(dict)  # Initial status dict
    connection_failed = Signal(str)  # Error message
    status_updated = Signal(dict)  # Status dict from hardware
    parameter_set_success = Signal(str, object)  # (parameter_name, value)
    parameter_set_failed = Signal(str, str)  # (parameter_name, error_message)
    monitoring_data = Signal(float, float, float, float)  # (timestamp, output, error, setpoint)

    def __init__(self, state):
        """
        Initialize PID worker.

        Parameters
        ----------
        state : ExperimentState
            Shared experiment state
        """
        super().__init__()
        self.state = state
        self.sim900 = None
        self.sim960 = None

        self._is_running = False
        self._is_monitoring = False
        self._command_queue = []  # Queue of (command, args) tuples

    def run(self):
        """Main worker thread loop."""
        self._is_running = True

        try:
            # Connect to hardware
            self._connect_hardware()

            # Process commands while running
            while self._is_running:
                # Process any queued commands
                if self._command_queue:
                    command, args = self._command_queue.pop(0)
                    self._execute_command(command, args)

                # Monitoring update if enabled
                if self._is_monitoring and self.sim960:
                    self._do_monitoring_update()

                # Sleep briefly to avoid busy-waiting
                time.sleep(0.05)

        except Exception as e:
            self.connection_failed.emit(f"Worker error: {e}")

        finally:
            self._disconnect_hardware()

    def stop(self):
        """Stop the worker thread."""
        self._is_running = False
        self._is_monitoring = False

    def start_monitoring(self, interval):
        """Enable periodic monitoring updates."""
        self.state.pid_monitor_interval = interval
        self._is_monitoring = True

    def stop_monitoring(self):
        """Disable periodic monitoring updates."""
        self._is_monitoring = False

    def queue_command(self, command, *args):
        """
        Queue a command for execution in the worker thread.

        Parameters
        ----------
        command : str
            Command name (e.g., 'set_setpoint', 'set_p_gain', etc.)
        *args
            Arguments for the command
        """
        self._command_queue.append((command, args))

    # === Hardware Communication Methods ===

    def _connect_hardware(self):
        """Connect to SIM900/SIM960 hardware."""
        try:
            # Connect to SIM900
            self.sim900 = SIM900Controller(
                address=self.state.pid_com_port,
                verbose=False
            )

            if not self.sim900.open_connection():
                raise ConnectionError("Failed to connect to SIM900")

            # Connect to SIM960
            self.sim960 = SIM960Controller(
                self.sim900,
                port=self.state.pid_sim900_port,
                verbose=False
            )

            # Read initial status
            status = self.sim960.get_status()
            self.connection_established.emit(status)

        except Exception as e:
            self.connection_failed.emit(str(e))
            raise

    def _disconnect_hardware(self):
        """Disconnect from hardware."""
        if self.sim900:
            self.sim900.close_connection()
            self.sim900 = None
            self.sim960 = None

    def _execute_command(self, command, args):
        """Execute a queued hardware command."""
        if not self.sim960:
            self.parameter_set_failed.emit(command, "Not connected to hardware")
            return

        try:
            if command == 'set_setpoint':
                value = args[0]
                self.sim960.set_setpoint(value)
                self.parameter_set_success.emit('setpoint', value)

            elif command == 'set_offset':
                value = args[0]
                self.sim960.set_offset(value)
                self.parameter_set_success.emit('offset', value)

            elif command == 'set_p_gain':
                value = args[0]
                self.sim960.set_proportional_gain(value)
                self.parameter_set_success.emit('p_gain', value)

            elif command == 'set_i_time':
                value = args[0]
                self.sim960.set_integral_time(value)
                self.parameter_set_success.emit('i_time', value)

            elif command == 'set_d_time':
                value = args[0]
                self.sim960.set_derivative_time(value)
                self.parameter_set_success.emit('d_time', value)

            elif command == 'set_upper_limit':
                value = args[0]
                self.sim960.set_upper_limit(value)
                self.parameter_set_success.emit('upper_limit', value)

            elif command == 'set_lower_limit':
                value = args[0]
                self.sim960.set_lower_limit(value)
                self.parameter_set_success.emit('lower_limit', value)

            elif command == 'set_manual_mode':
                value = args[0]
                self.sim960.set_manual_mode(value)
                self.parameter_set_success.emit('manual_mode', value)

            elif command == 'set_manual_output':
                value = args[0]
                self.sim960.set_manual_output(value)
                self.parameter_set_success.emit('manual_output', value)

            elif command == 'set_p_control':
                value = args[0]
                self.sim960.set_p_control(value)
                self.parameter_set_success.emit('p_control', value)

            elif command == 'set_i_control':
                value = args[0]
                self.sim960.set_i_control(value)
                self.parameter_set_success.emit('i_control', value)

            elif command == 'set_d_control':
                value = args[0]
                self.sim960.set_d_control(value)
                self.parameter_set_success.emit('d_control', value)

            elif command == 'refresh_status':
                status = self.sim960.get_status()
                self.status_updated.emit(status)

            else:
                self.parameter_set_failed.emit(command, f"Unknown command: {command}")

        except Exception as e:
            self.parameter_set_failed.emit(command, str(e))

    def _do_monitoring_update(self):
        """Perform a monitoring update (read current values)."""
        if not self.sim960:
            return

        try:
            # Query current values
            output = self.sim960.get_output()
            setpoint = self.sim960.get_setpoint()
            offset = self.sim960.get_offset()

            # Calculate error (approximate)
            if all(v is not None for v in [output, setpoint, offset]):
                error = setpoint - (output - offset)
                timestamp = time.time()

                # Emit monitoring data
                self.monitoring_data.emit(timestamp, output, error, setpoint)

        except Exception as e:
            # Silently ignore monitoring errors to avoid spam
            pass

        # Sleep for the monitoring interval
        time.sleep(self.state.pid_monitor_interval)
