"""
Background worker thread for continuous DAQ acquisition.
Prevents UI blocking during data acquisition.
"""

import sys
from pathlib import Path
import time
import numpy as np
from PySide6.QtCore import QThread, Signal

# Add parent directory to path to import qdm modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    import nidaqmx
    from nidaqmx.constants import TerminalConfiguration, AcquisitionType
    NIDAQMX_AVAILABLE = True
except ImportError:
    NIDAQMX_AVAILABLE = False
    print("Warning: nidaqmx not available, using simulation mode")


class DAQWorker(QThread):
    """
    Worker thread for continuous DAQ acquisition.

    Emits data_acquired signal with each measurement point.
    Can be paused/resumed/stopped via control methods.
    """

    # Signals
    data_acquired = Signal(float, float, float)  # (timestamp, voltage, converted_value)
    acquisition_error = Signal(str)
    acquisition_finished = Signal()

    def __init__(self, state):
        """
        Parameters
        ----------
        state : ExperimentState
            Shared experiment state object.
        """
        super().__init__()
        self.state = state
        self._is_running = False
        self._is_paused = False
        self._stop_requested = False

        # Track acquisition start time
        self._start_time = None

        # For simulation mode
        self._simulation_mode = not NIDAQMX_AVAILABLE

    def run(self):
        """Main acquisition loop."""
        self._is_running = True
        self._stop_requested = False
        self._start_time = time.time()

        if self._simulation_mode:
            self._run_simulation()
        else:
            self._run_hardware()

        self._is_running = False
        self.acquisition_finished.emit()

    def _run_simulation(self):
        """Simulation mode for testing without hardware."""
        config = self.state.get_daq_config()
        sample_rate = config['sample_rate']
        batch_size = config['batch_size']
        conversion = config['conversion']

        try:
            # Calculate read interval based on batch size
            read_interval = batch_size / sample_rate

            while not self._stop_requested:
                if not self._is_paused:
                    # Generate batch of simulated samples
                    current_time = time.time()
                    elapsed = current_time - self._start_time

                    for i in range(batch_size):
                        # Simulate voltage with some drift and noise
                        t = elapsed - (batch_size - i - 1) / sample_rate
                        base_voltage = 10.0 + 0.1 * np.sin(2 * np.pi * 0.05 * t)
                        noise = np.random.normal(0, 0.01)
                        voltage = base_voltage + noise

                        # Convert to power
                        slope, intercept = conversion
                        power = voltage * slope + intercept

                        # Emit signal
                        self.data_acquired.emit(t, voltage, power)

                    # Sleep for the read interval
                    time.sleep(read_interval)
                else:
                    time.sleep(0.1)

        except Exception as e:
            self.acquisition_error.emit(f"Simulation error: {str(e)}")

    def _run_hardware(self):
        """Hardware acquisition using NI-DAQ."""
        config = self.state.get_daq_config()
        device = config['device']
        channel = config['channel']
        sample_rate = config['sample_rate']
        batch_size = config['batch_size']
        voltage_range = config['voltage_range']
        conversion = config['conversion']

        try:
            with nidaqmx.Task() as task:
                # Configure analog input channel
                task.ai_channels.add_ai_voltage_chan(
                    f"{device}/{channel}",
                    terminal_config=TerminalConfiguration.DEFAULT,
                    min_val=voltage_range[0],
                    max_val=voltage_range[1]
                )

                # Configure continuous sampling
                task.timing.cfg_samp_clk_timing(
                    rate=sample_rate,
                    sample_mode=AcquisitionType.CONTINUOUS
                )

                task.start()

                # Calculate read interval based on batch size and sample rate
                # read_interval = batch_size / sample_rate
                samples_per_read = max(1, batch_size)
                read_interval = samples_per_read / sample_rate

                while not self._stop_requested:
                    if not self._is_paused:
                        # Read data chunk
                        data = task.read(number_of_samples_per_channel=samples_per_read)

                        # Process each sample
                        current_time = time.time()
                        elapsed = current_time - self._start_time

                        if isinstance(data, list):
                            # Multiple samples
                            for i, voltage in enumerate(data):
                                t = elapsed - (len(data) - i - 1) / sample_rate
                                slope, intercept = conversion
                                power = voltage * slope + intercept
                                self.data_acquired.emit(t, voltage, power)
                        else:
                            # Single sample
                            voltage = data
                            slope, intercept = conversion
                            power = voltage * slope + intercept
                            self.data_acquired.emit(elapsed, voltage, power)

                        time.sleep(read_interval)
                    else:
                        time.sleep(0.1)

                task.stop()

        except Exception as e:
            self.acquisition_error.emit(f"DAQ error: {str(e)}")

    def pause(self):
        """Pause acquisition (can be resumed)."""
        self._is_paused = True

    def resume(self):
        """Resume acquisition after pause."""
        self._is_paused = False

    def stop(self):
        """Stop acquisition (cannot be resumed)."""
        self._stop_requested = True

    @property
    def is_running(self):
        return self._is_running

    @property
    def is_paused(self):
        return self._is_paused
