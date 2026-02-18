"""
SRS SIM900 Mainframe Control Module

Functions to connect to and control the SRS SIM900 Mainframe chassis and
SIM960 Analog PID Controller for laser power stabilization.

The SIM900 communicates via RS-232 serial (typically through USB-to-DB9 adapter).
Commands to modules use the format: SNDT <port>,<command>
Responses retrieved with: GETN? <port>,<bytes>

Author: Walsworth Group
Date: 2026-02-10
"""

import pyvisa
from pyvisa.errors import VisaIOError
from typing import Optional, Callable, List, Dict, Union
import time
import re


def parse_sim900_response(response: str) -> str:
    """
    Parse SIM900 GETN? response format.

    The SIM900 returns data in format: #NXXX<data>
    where N is the number of digits in XXX, and XXX is the data length.
    Example: "#3052Stanford_Research_Systems,SIM960,..." means 52 bytes follow.

    Parameters
    ----------
    response : str
        Raw response from GETN? command.

    Returns
    -------
    str
        Parsed data string with header removed.
    """
    if not response or not response.strip():
        return ""

    # Match pattern #N<length><data>
    match = re.match(r'#(\d)(\d+)', response)
    if match:
        n_digits = int(match.group(1))
        length = int(match.group(2))
        # Data starts after #, N digit, and length digits
        data_start = 1 + 1 + n_digits
        return response[data_start:].strip()

    # If no header found, return as-is
    return response.strip()


def list_serial_ports(logger: Optional[Callable[[str], None]] = None) -> List[str]:
    """
    List all available serial (ASRL/COM) ports visible to PyVISA.

    Parameters
    ----------
    logger : callable, optional
        Function to use for logging messages (e.g., print or tqdm.write).
        If None, uses print.

    Returns
    -------
    list of str
        List of VISA resource strings for serial ports (e.g., 'ASRL3::INSTR').
    """
    _log = logger if logger is not None else print

    try:
        rm = pyvisa.ResourceManager()
        resources = rm.list_resources()
        serial_ports = [r for r in resources if 'ASRL' in r or 'COM' in r]

        if serial_ports:
            _log(f"Found {len(serial_ports)} serial port(s):")
            for port in serial_ports:
                _log(f"  - {port}")
        else:
            _log("No serial ports found.")

        rm.close()
        return serial_ports

    except Exception as e:
        _log(f"Error listing serial ports: {e}")
        return []


class SIM900Controller:
    """
    Controller class for SRS SIM900 Mainframe chassis.

    The SIM900 is a mainframe that can host up to 8 SIM modules in ports 1-8.
    This class handles connection, module detection, and communication with
    installed modules (particularly the SIM960 PID controller).

    Parameters
    ----------
    address : str
        VISA resource string for the serial port (e.g., 'ASRL3::INSTR' or 'COM3').
        If not specified, will attempt auto-detection.
    baud_rate : int, optional
        Serial baud rate. Default is 9600 (SIM900 default).
    logger : callable, optional
        Function for logging messages (e.g., print or tqdm.write).
    verbose : bool, optional
        If True, print status messages. Default is True.
    """

    def __init__(
        self,
        address: Optional[str] = None,
        baud_rate: int = 9600,
        logger: Optional[Callable[[str], None]] = None,
        verbose: bool = True,
    ):
        self.address = address
        self.baud_rate = baud_rate
        self.rm = None
        self.instrument = None
        self.modules = {}  # dict mapping port number to module type

        self._logger = logger
        self._verbose = verbose

    def _log(self, msg: str):
        """Internal logging method."""
        if not self._verbose:
            return
        if self._logger is None:
            print(msg)
        else:
            self._logger(msg)

    def open_connection(self, auto_detect: bool = True) -> bool:
        """
        Open serial connection to the SIM900 Mainframe.

        Parameters
        ----------
        auto_detect : bool, optional
            If True and address is None, attempts to auto-detect the SIM900
            by trying all available serial ports. Default is True.

        Returns
        -------
        bool
            True if connection successful, False otherwise.
        """
        try:
            self.rm = pyvisa.ResourceManager()

            # Auto-detect if no address specified
            if self.address is None and auto_detect:
                self._log("No address specified. Attempting auto-detection...")
                serial_ports = [r for r in self.rm.list_resources()
                               if 'ASRL' in r or 'COM' in r]

                for port in serial_ports:
                    self._log(f"Trying {port}...")
                    if self._try_connect(port):
                        self.address = port
                        return True

                self._log("[ERROR] Auto-detection failed. No SIM900 found.")
                self.close_connection()
                return False

            # Use specified address
            elif self.address is not None:
                return self._try_connect(self.address)

            else:
                self._log("[ERROR] No address specified and auto_detect=False.")
                return False

        except Exception as e:
            self._log(f"[ERROR] CONNECTION FAILED: {e}")
            self.close_connection()
            return False

    def _try_connect(self, address: str) -> bool:
        """
        Attempt to connect to a specific serial port.

        Parameters
        ----------
        address : str
            VISA resource string for serial port.

        Returns
        -------
        bool
            True if connection and ID verification successful, False otherwise.
        """
        try:
            self.instrument = self.rm.open_resource(address)

            # Configure serial parameters
            self.instrument.baud_rate = self.baud_rate
            self.instrument.data_bits = 8
            self.instrument.parity = pyvisa.constants.Parity.none
            self.instrument.stop_bits = pyvisa.constants.StopBits.one
            self.instrument.flow_control = pyvisa.constants.VI_ASRL_FLOW_NONE

            # Set termination characters (SIM900 uses CR+LF)
            self.instrument.read_termination = '\n'
            self.instrument.write_termination = '\n'
            self.instrument.timeout = 5000  # 5 second timeout

            # Clear any pending data
            try:
                self.instrument.read()
            except:
                pass

            # Verify it's a SIM900
            idn = self.instrument.query('*IDN?')

            if 'SIM900' in idn:
                self._log(f"[OK] Connection Open: {address}")
                self._log(f"   ID: {idn.strip()}")
                return True
            else:
                self._log(f"Device at {address} is not a SIM900: {idn.strip()}")
                self.instrument.close()
                self.instrument = None
                return False

        except (VisaIOError, Exception) as e:
            if self.instrument:
                self.instrument.close()
                self.instrument = None
            return False

    def close_connection(self):
        """Close the connection to the SIM900."""
        if self.instrument:
            self._log("Closing SIM900 connection.")
            self.instrument.close()
            self.instrument = None
        if self.rm:
            self.rm.close()
            self.rm = None
        self._log("Connection closed.")

    def scan_modules(self) -> Dict[int, str]:
        """
        Scan all 8 ports to detect installed modules.

        Returns
        -------
        dict
            Dictionary mapping port number (1-8) to module ID string.
            Empty ports are not included in the dictionary.
        """
        if not self.instrument:
            self._log("[ERROR] Connection not open. Cannot scan modules.")
            return {}

        self._log("Scanning for installed modules...")
        self.modules = {}

        for port in range(1, 9):
            try:
                # Query module identification
                # Format: SNDT port,"*IDN?" then GETN? port,length
                self.instrument.write(f'SNDT {port},"*IDN?"')
                time.sleep(0.1)  # Small delay for module to respond

                # Get response (request up to 100 bytes)
                response = self.instrument.query(f'GETN? {port},100')

                if response and response.strip():
                    # Parse the SIM900 response format
                    module_id = parse_sim900_response(response)

                    if module_id and 'Stanford' in module_id:
                        self.modules[port] = module_id
                        self._log(f"  Port {port}: {module_id}")

            except (VisaIOError, Exception):
                # No module in this port or communication error
                pass

        if not self.modules:
            self._log("  No modules detected.")

        return self.modules

    def send_command(self, port: int, command: str) -> bool:
        """
        Send a command to a module in a specific port.

        Parameters
        ----------
        port : int
            Port number (1-8) where the module is installed.
        command : str
            Command string to send to the module.

        Returns
        -------
        bool
            True if command sent successfully, False otherwise.
        """
        if not self.instrument:
            self._log("[ERROR] Connection not open. Cannot send command.")
            return False

        try:
            self.instrument.write(f'SNDT {port},"{command}"')
            return True
        except VisaIOError as e:
            self._log(f"[ERROR] Sending command to port {port}: {e}")
            return False

    def query_module(self, port: int, command: str, max_bytes: int = 100) -> Optional[str]:
        """
        Send a query to a module and retrieve the response.

        Parameters
        ----------
        port : int
            Port number (1-8) where the module is installed.
        command : str
            Query command to send to the module.
        max_bytes : int, optional
            Maximum number of bytes to retrieve. Default is 100.

        Returns
        -------
        str or None
            Response string from the module, or None if error.
        """
        if not self.instrument:
            self._log("[ERROR] Connection not open. Cannot query module.")
            return None

        try:
            # Call NUMQ? to clear/reset buffer state (ignore result)
            try:
                self.instrument.query(f'NUMQ? {port}')
            except:
                pass

            # Send query
            self.instrument.write(f'SNDT {port},"{command}"')
            time.sleep(0.3)  # Delay for module to process

            # Get response
            response = self.instrument.query(f'GETN? {port},{max_bytes}')

            # Parse response to remove SIM900 header
            return parse_sim900_response(response)

        except VisaIOError as e:
            self._log(f"[ERROR] Querying port {port}: {e}")
            return None

    def __enter__(self):
        """Context manager entry."""
        self.open_connection()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close_connection()


class SIM960Controller:
    """
    Controller class for SRS SIM960 Analog PID Controller.

    The SIM960 is a PID controller module that fits inside the SIM900 mainframe.
    This class provides methods to control PID parameters, enable/disable the
    controller, and monitor the output voltage.

    Parameters
    ----------
    sim900 : SIM900Controller
        Connected SIM900Controller instance.
    port : int
        Port number (1-8) where the SIM960 is installed.
    logger : callable, optional
        Function for logging messages.
    verbose : bool, optional
        If True, print status messages. Default is True.
    """

    def __init__(
        self,
        sim900: SIM900Controller,
        port: int = 1,
        logger: Optional[Callable[[str], None]] = None,
        verbose: bool = True,
    ):
        self.sim900 = sim900
        self.port = port
        self._logger = logger
        self._verbose = verbose

        # Verify it's actually a SIM960
        if sim900.instrument:
            idn = sim900.query_module(port, '*IDN?')
            if idn and 'SIM960' not in idn:
                self._log(f"[WARN] Port {port} may not be a SIM960: {idn}")

    def _log(self, msg: str):
        """Internal logging method."""
        if not self._verbose:
            return
        if self._logger is None:
            print(msg)
        else:
            self._logger(msg)

    def query(self, command: str) -> Optional[str]:
        """
        Send a query to the SIM960 and return the response.

        Parameters
        ----------
        command : str
            Command string to send.

        Returns
        -------
        str or None
            Response from the SIM960, or None if error.
        """
        return self.sim900.query_module(self.port, command)

    def write(self, command: str) -> bool:
        """
        Send a command to the SIM960.

        Parameters
        ----------
        command : str
            Command string to send.

        Returns
        -------
        bool
            True if successful, False otherwise.
        """
        return self.sim900.send_command(self.port, command)

    def get_status(self) -> Dict[str, Union[str, float, bool, int]]:
        """
        Get comprehensive status of the PID controller.

        Returns
        -------
        dict
            Dictionary containing PID parameters, output, and control enables.
        """
        status = {}
        status['manual_mode'] = self.get_manual_mode()
        status['setpoint'] = self.get_setpoint()
        status['output_voltage'] = self.get_output()
        status['offset'] = self.get_offset()
        status['proportional_gain'] = self.get_proportional_gain()
        status['integral_time'] = self.get_integral_time()
        status['derivative_time'] = self.get_derivative_time()
        status['upper_limit'] = self.get_upper_limit()
        status['lower_limit'] = self.get_lower_limit()
        status['p_control_enable'] = self.get_p_control()
        status['i_control_enable'] = self.get_i_control()
        status['d_control_enable'] = self.get_d_control()

        return status

    def print_status(self):
        """Print formatted status information."""
        status = self.get_status()
        self._log("=" * 50)
        self._log("SIM960 PID Controller Status")
        self._log("=" * 50)

        mode = status.get('manual_mode')
        self._log(f"Mode:              {'MANUAL' if mode else 'PID' if mode is not None else 'ERROR'}")

        # Output and parameters
        for key, label, unit in [
            ('setpoint', 'Setpoint', ' V'),
            ('output_voltage', 'Output', ' V'),
            ('offset', 'Offset', ' V'),
            ('proportional_gain', 'P Gain', ''),
            ('integral_time', 'I Time', ' s'),
            ('derivative_time', 'D Time', ' s'),
            ('upper_limit', 'Upper Limit', ' V'),
            ('lower_limit', 'Lower Limit', ' V'),
        ]:
            val = status.get(key)
            if val is not None:
                self._log(f"{label:18} {val:+.6f}{unit}")
            else:
                self._log(f"{label:18} [Query Failed]")

        # Control enables
        self._log("")
        p_en = status.get('p_control_enable')
        i_en = status.get('i_control_enable')
        d_en = status.get('d_control_enable')
        self._log(f"P Control:         {'ON' if p_en else 'OFF' if p_en is not None else 'ERROR'}")
        self._log(f"I Control:         {'ON' if i_en else 'OFF' if i_en is not None else 'ERROR'}")
        self._log(f"D Control:         {'ON' if d_en else 'OFF' if d_en is not None else 'ERROR'}")

        self._log("=" * 50)

    # Mode control
    def set_manual_mode(self, enable: bool = True):
        """
        Set PID to manual mode (enable=True) or auto mode (enable=False).

        In manual mode, output voltage is set directly.
        In auto mode, PID loop controls the output.

        Parameters
        ----------
        enable : bool
            True for manual mode, False for auto (PID) mode.
        """
        # NOTE: AMAN polarity is inverted - AMAN 0 activates manual mode, AMAN 1 activates PID mode
        cmd = f'AMAN {0 if enable else 1}'
        if self.write(cmd):
            mode = "MANUAL" if enable else "PID"
            self._log(f"Mode set to {mode}")

    def get_manual_mode(self) -> Optional[bool]:
        """Get whether manual mode is enabled. Returns True if manual, False if PID."""
        resp = self.query('AMAN?')
        if resp:
            # NOTE: AMAN polarity is inverted - AMAN 0 = manual, AMAN 1 = PID/auto
            return resp.strip() == '0'
        return None

    # Setpoint control
    def set_setpoint(self, voltage: float):
        """
        Set the PID setpoint voltage.

        In PID mode, the controller will adjust the output to maintain
        the input at this setpoint value. This is the proper way to
        change the target laser power while PID is locked.

        Parameters
        ----------
        voltage : float
            Setpoint voltage in volts.
        """
        cmd = f'SETP {voltage:.6f}'
        if self.write(cmd):
            self._log(f"Setpoint set to {voltage:.6f} V")

    def get_setpoint(self) -> Optional[float]:
        """Get the current setpoint voltage."""
        resp = self.query('SETP?')
        if resp:
            try:
                return float(resp)
            except ValueError:
                return None
        return None

    # Output control
    def set_manual_output(self, voltage: float):
        """
        Set the output voltage directly (manual mode only).

        Parameters
        ----------
        voltage : float
            Output voltage in volts (-10 to +10 V).
        """
        cmd = f'MOUT {voltage:.6f}'
        if self.write(cmd):
            self._log(f"Manual output set to {voltage:.6f} V")

    def get_output(self) -> Optional[float]:
        """Get the current output voltage (OMON = output monitor)."""
        resp = self.query('OMON?')
        if resp:
            try:
                return float(resp)
            except ValueError:
                return None
        return None

    def set_offset(self, voltage: float):
        """
        Set the offset voltage.

        Parameters
        ----------
        voltage : float
            Offset voltage in volts.
        """
        cmd = f'OFST {voltage:.6f}'
        if self.write(cmd):
            self._log(f"Offset set to {voltage:.6f} V")

    def get_offset(self) -> Optional[float]:
        """Get the current offset voltage."""
        resp = self.query('OFST?')
        if resp:
            try:
                return float(resp)
            except ValueError:
                return None
        return None

    # PID parameters
    def set_proportional_gain(self, gain: float):
        """
        Set proportional gain.

        Parameters
        ----------
        gain : float
            Proportional gain value (dimensionless).
        """
        cmd = f'GAIN {gain:.6f}'
        if self.write(cmd):
            self._log(f"Proportional gain set to {gain:.6f}")

    def get_proportional_gain(self) -> Optional[float]:
        """Get the proportional gain (GAIN)."""
        resp = self.query('GAIN?')
        if resp:
            try:
                return float(resp)
            except ValueError:
                return None
        return None

    def set_integral_time(self, time_constant: float):
        """
        Set integral time constant.

        Parameters
        ----------
        time_constant : float
            Integral time constant in seconds.
        """
        cmd = f'INTG {time_constant:.6f}'
        if self.write(cmd):
            self._log(f"Integral time set to {time_constant:.6f} s")

    def get_integral_time(self) -> Optional[float]:
        """Get the integral time constant (INTG)."""
        resp = self.query('INTG?')
        if resp:
            try:
                return float(resp)
            except ValueError:
                return None
        return None

    def set_derivative_time(self, time_constant: float):
        """
        Set derivative time constant.

        Parameters
        ----------
        time_constant : float
            Derivative time constant in seconds.
        """
        cmd = f'DERV {time_constant:.6f}'
        if self.write(cmd):
            self._log(f"Derivative time set to {time_constant:.6f} s")

    def get_derivative_time(self) -> Optional[float]:
        """Get the derivative time constant (DERV)."""
        resp = self.query('DERV?')
        if resp:
            try:
                return float(resp)
            except ValueError:
                return None
        return None

    # Control enables
    def set_p_control(self, enable: bool):
        """Enable/disable proportional control."""
        cmd = f'PCTL {1 if enable else 0}'
        if self.write(cmd):
            self._log(f"P control {'enabled' if enable else 'disabled'}")

    def get_p_control(self) -> Optional[bool]:
        """Get P control enable status."""
        resp = self.query('PCTL?')
        if resp:
            return resp.strip() == '1' or resp.strip() == '+1'
        return None

    def set_i_control(self, enable: bool):
        """Enable/disable integral control."""
        cmd = f'ICTL {1 if enable else 0}'
        if self.write(cmd):
            self._log(f"I control {'enabled' if enable else 'disabled'}")

    def get_i_control(self) -> Optional[bool]:
        """Get I control enable status."""
        resp = self.query('ICTL?')
        if resp:
            return resp.strip() == '1' or resp.strip() == '+1'
        return None

    def set_d_control(self, enable: bool):
        """Enable/disable derivative control."""
        cmd = f'DCTL {1 if enable else 0}'
        if self.write(cmd):
            self._log(f"D control {'enabled' if enable else 'disabled'}")

    def get_d_control(self) -> Optional[bool]:
        """Get D control enable status."""
        resp = self.query('DCTL?')
        if resp:
            return resp.strip() == '1' or resp.strip() == '+1'
        return None

    # Output limits
    def set_upper_limit(self, voltage: float):
        """
        Set upper output voltage limit.

        Parameters
        ----------
        voltage : float
            Upper limit in volts (-10 to +10 V).
        """
        cmd = f'ULIM {voltage:.6f}'
        if self.write(cmd):
            self._log(f"Upper limit set to {voltage:.6f} V")

    def get_upper_limit(self) -> Optional[float]:
        """Get the upper output voltage limit."""
        resp = self.query('ULIM?')
        if resp:
            try:
                return float(resp)
            except ValueError:
                return None
        return None

    def set_lower_limit(self, voltage: float):
        """
        Set lower output voltage limit.

        Parameters
        ----------
        voltage : float
            Lower limit in volts (-10 to +10 V).
        """
        cmd = f'LLIM {voltage:.6f}'
        if self.write(cmd):
            self._log(f"Lower limit set to {voltage:.6f} V")

    def get_lower_limit(self) -> Optional[float]:
        """Get the lower output voltage limit."""
        resp = self.query('LLIM?')
        if resp:
            try:
                return float(resp)
            except ValueError:
                return None
        return None


def check_sim900_connection(
    address: Optional[str] = None,
    scan_modules: bool = True,
    logger: Optional[Callable[[str], None]] = None
) -> bool:
    """
    Quick connection test for SRS SIM900 Mainframe.

    This convenience function attempts to connect to the SIM900,
    optionally scans for installed modules, and reports the results.

    Parameters
    ----------
    address : str, optional
        VISA resource string for serial port. If None, attempts auto-detection.
    scan_modules : bool, optional
        If True, scans all 8 ports for installed modules. Default is True.
    logger : callable, optional
        Function for logging messages.

    Returns
    -------
    bool
        True if connection successful, False otherwise.

    Examples
    --------
    >>> # Auto-detect and scan modules
    >>> check_sim900_connection()

    >>> # Connect to specific port
    >>> check_sim900_connection(address='ASRL3::INSTR')
    """
    _log = logger if logger is not None else print

    _log("=" * 60)
    _log("SRS SIM900 Mainframe Connection Test")
    _log("=" * 60)

    with SIM900Controller(address=address, logger=logger) as sim900:
        if sim900.instrument is None:
            _log("\n[ERROR] CONNECTION FAILED")
            _log("=" * 60)
            return False

        _log("\n[OK] CONNECTION SUCCESSFUL")
        _log(f"   Address: {sim900.address}")

        if scan_modules:
            _log("")
            modules = sim900.scan_modules()

            if modules:
                _log(f"\n[OK] Found {len(modules)} module(s)")

                # Check specifically for SIM960 PID controller
                sim960_ports = [p for p, m in modules.items() if 'SIM960' in m]
                if sim960_ports:
                    _log(f"   [*] SIM960 PID Controller detected on port(s): {sim960_ports}")
            else:
                _log("\n[WARN] No modules detected in mainframe")

        _log("=" * 60)
        return True


# Quick test when running this module directly
if __name__ == "__main__":
    print("\nRunning SIM900 connection test...\n")
    check_sim900_connection()
