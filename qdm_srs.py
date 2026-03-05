import pyvisa
from pyvisa.errors import VisaIOError
from typing import Union, Callable, Optional
SG384_ADDRESS = 'TCPIP::192.168.1.100::INSTR'
# -------------------------------------------------------------

class SG384Controller:
    """
    A compact suite of functions to manage connection and quick control
    of the SRS SG384 Signal Generator via PyVISA.

    New:
      - logger: callable like print or tqdm.write
      - verbose: controls whether informational messages are emitted
    """

    def __init__(
        self,
        address: str,
        logger: Optional[Callable[[str], None]] = None,
        verbose: bool = True,
        verify_on_set: bool = False,   # avoid extra query per point unless needed
    ):
        self.address = address
        self.rm = None
        self.instrument = None

        self._logger = logger
        self._verbose = verbose
        self._verify_on_set = verify_on_set

    def _log(self, msg: str):
        if not self._verbose:
            return
        if self._logger is None:
            print(msg)
        else:
            self._logger(msg)

    def open_connection(self) -> bool:
        """Opens the VISA connection to the SG384 with explicit termination."""
        try:
            self._log(f"Connecting to {self.address}...")
            self.rm = pyvisa.ResourceManager()
            self.instrument = self.rm.open_resource(self.address)

            self.instrument.read_termination = '\n'
            self.instrument.write_termination = '\n'
            self.instrument.timeout = 10000

            # Confirm communication
            idn = self.instrument.query('*IDN?')
            self._log(f"✅ Connection Open. ID: {idn.strip()}")
            return True

        except VisaIOError as e:
            self._log(f"❌ CONNECTION FAILED: {e}")
            self.close_connection()
            return False

    def close_connection(self):
        if self.instrument:
            self._log("Closing instrument connection.")
            self.instrument.close()
            self.instrument = None
        if self.rm:
            self.rm.close()
            self.rm = None
        self._log("Connection Closed.")

    def set_frequency(self, frequency: Union[int, float], unit: str = 'MHz'):
        if not self.instrument:
            self._log("❌ ERROR: Connection not open. Cannot set frequency.")
            return

        command = f'FREQ {frequency} {unit}'
        try:
            self.instrument.write(command)

            # Verification query is expensive during sweeps; keep off by default.
            if self._verify_on_set and self._verbose:
                readback = self.instrument.query('FREQ?')
                self._log(f"   Frequency set to: {readback.strip()} Hz")

        except VisaIOError as e:
            self._log(f"   ❌ ERROR communicating with SG384: {e}")

    def get_amplitude(self) -> float:
        """
        Query the current RF output amplitude.

        Returns
        -------
        float
            Amplitude in dBm, or 0.0 if not connected or query fails.
        """
        if not self.instrument:
            return 0.0
        try:
            response = self.instrument.query('AMPR?')
            return float(response.strip())
        except Exception as e:
            self._log(f"   ❌ ERROR reading amplitude: {e}")
            return 0.0

    def get_frequency(self) -> float:
        """
        Query the current RF output frequency.

        Returns
        -------
        float
            Frequency in GHz, or 0.0 if not connected or query fails.
        """
        if not self.instrument:
            return 0.0
        try:
            response = self.instrument.query('FREQ?')
            return float(response.strip()) / 1e9   # SG384 returns Hz
        except Exception as e:
            self._log(f"   ❌ ERROR reading frequency: {e}")
            return 0.0

    def set_amplitude(self, level: Union[int, float]):
        if not self.instrument:
            self._log("❌ ERROR: Connection not open. Cannot set amplitude.")
            return

        command = f'AMPR {level} dBm'
        try:
            self.instrument.write(command)
            if self._verify_on_set and self._verbose:
                readback = self.instrument.query('AMPR?')
                self._log(f"   Amplitude set to: {readback.strip()} dBm")

        except VisaIOError as e:
            self._log(f"   ❌ ERROR communicating with SG384: {e}")
