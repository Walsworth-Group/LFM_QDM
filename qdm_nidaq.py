# NI-DAQ functions for QDM experiments
# Provides interface to NI USB-6361 DAQ devices for analog input acquisition

import nidaqmx
from nidaqmx.constants import TerminalConfiguration, AcquisitionType
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from IPython import display
from datetime import datetime
from pathlib import Path
from scipy.fft import fft, fftfreq
from typing import Optional, Callable, Tuple
from tqdm.notebook import tqdm


def read_analog_voltage(
    device: str = "Dev3",
    channel: str = "ai0",
    n_samples: int = 1,
    sample_rate: float = 1000.0,
    voltage_range: Tuple[float, float] = (-10.0, 10.0),
    terminal_config: TerminalConfiguration = TerminalConfiguration.DEFAULT
) -> np.ndarray:
    """
    Read analog voltage from a single DAQ channel.

    Parameters
    ----------
    device : str
        DAQ device name (e.g., "Dev3").
    channel : str
        Analog input channel (e.g., "ai0").
    n_samples : int
        Number of samples to acquire.
    sample_rate : float
        Sampling rate in Hz.
    voltage_range : tuple
        (min_voltage, max_voltage) for the channel.
    terminal_config : TerminalConfiguration
        Terminal configuration (DEFAULT, RSE, NRSE, DIFF).

    Returns
    -------
    np.ndarray
        Array of voltage readings.
    """
    with nidaqmx.Task() as task:
        task.ai_channels.add_ai_voltage_chan(
            f"{device}/{channel}",
            terminal_config=terminal_config,
            min_val=voltage_range[0],
            max_val=voltage_range[1]
        )

        if n_samples == 1:
            return np.array([task.read()])
        else:
            task.timing.cfg_samp_clk_timing(
                rate=sample_rate,
                sample_mode=AcquisitionType.FINITE,
                samps_per_chan=n_samples
            )
            return np.array(task.read(number_of_samples_per_channel=n_samples))


def acquire_continuous(
    duration_seconds: float,
    device: str = "Dev3",
    channel: str = "ai0",
    sample_rate: float = 2.0,
    voltage_range: Tuple[float, float] = (-10.0, 10.0),
    conversion: Optional[Tuple[float, float]] = None,
    live_plot: bool = True,
    plot_ylabel: str = "Voltage (V)",
    logger: Optional[Callable[[str], None]] = None
) -> dict:
    """
    Acquire continuous analog data for a specified duration.

    Parameters
    ----------
    duration_seconds : float
        Total acquisition time in seconds.
    device : str
        DAQ device name.
    channel : str
        Analog input channel.
    sample_rate : float
        Samples per second (Hz).
    voltage_range : tuple
        (min_voltage, max_voltage) for the channel.
    conversion : tuple or None
        If provided, (slope, intercept) to convert voltage to physical units.
        converted_value = voltage * slope + intercept
    live_plot : bool
        If True, display a live updating plot during acquisition.
    plot_ylabel : str
        Y-axis label for the plot.
    logger : callable or None
        Optional logging function (e.g., tqdm.write).

    Returns
    -------
    dict
        Dictionary containing:
        - 'time': np.ndarray of time points (seconds)
        - 'voltage': np.ndarray of raw voltage readings
        - 'converted': np.ndarray of converted values (if conversion provided)
        - 'sample_rate': actual sample rate used
    """
    def _log(msg):
        if logger:
            logger(msg)
        else:
            print(msg)

    samples_per_chunk = max(1, int(sample_rate))
    total_chunks = int(duration_seconds)

    all_voltage = []
    all_converted = []
    time_axis = []

    # Setup live plot if requested
    fig_live, ax_live = None, None
    if live_plot:
        plt.rcParams["figure.figsize"] = (12, 5)
        fig_live, ax_live = plt.subplots()
        line_live, = ax_live.plot([], [], color='forestgreen', linewidth=0.7)
        ax_live.set_title(f"Live Acquisition: {device}/{channel}")
        ax_live.set_xlabel("Time (s)")
        ax_live.set_ylabel(plot_ylabel)
        ax_live.grid(True, alpha=0.3)

    try:
        with nidaqmx.Task() as task:
            task.ai_channels.add_ai_voltage_chan(
                f"{device}/{channel}",
                terminal_config=TerminalConfiguration.DEFAULT,
                min_val=voltage_range[0],
                max_val=voltage_range[1]
            )

            task.timing.cfg_samp_clk_timing(
                rate=sample_rate,
                sample_mode=AcquisitionType.CONTINUOUS
            )

            task.start()

            with tqdm(total=total_chunks, desc="Acquiring", unit="s") as pbar:
                for i in range(total_chunks):
                    chunk = task.read(number_of_samples_per_channel=samples_per_chunk)
                    all_voltage.extend(chunk)

                    # Apply conversion if provided
                    if conversion:
                        converted_chunk = np.array(chunk) * conversion[0] + conversion[1]
                        all_converted.extend(converted_chunk)

                    # Update time axis
                    current_times = np.linspace(i, i + 1, samples_per_chunk)
                    time_axis.extend(current_times)

                    # Update live plot
                    if live_plot and fig_live is not None:
                        plot_data = all_converted if conversion else all_voltage
                        line_live.set_data(time_axis, plot_data)
                        ax_live.set_xlim(0, duration_seconds)
                        if plot_data:
                            margin = 0.05 * (max(plot_data) - min(plot_data) + 0.01)
                            ax_live.set_ylim(min(plot_data) - margin, max(plot_data) + margin)
                        display.clear_output(wait=True)
                        display.display(fig_live)

                    pbar.update(1)

            task.stop()

    except Exception as e:
        _log(f"DAQ Error: {e}")
        raise

    finally:
        if live_plot and fig_live is not None:
            plt.close(fig_live)

    result = {
        'time': np.array(time_axis),
        'voltage': np.array(all_voltage),
        'sample_rate': sample_rate
    }

    if conversion:
        result['converted'] = np.array(all_converted)

    return result


def analyze_and_plot_stability(
    data: dict,
    title: str = "Stability Analysis",
    ylabel: str = "Value",
    use_converted: bool = True
) -> plt.Figure:
    """
    Create a summary plot with time series and FFT of acquired data.

    Parameters
    ----------
    data : dict
        Output from acquire_continuous().
    title : str
        Plot title.
    ylabel : str
        Y-axis label for time series.
    use_converted : bool
        If True and 'converted' exists in data, plot converted values.

    Returns
    -------
    plt.Figure
        Matplotlib figure with time series and FFT subplots.
    """
    time_axis = data['time']
    sample_rate = data['sample_rate']

    if use_converted and 'converted' in data:
        y_data = data['converted']
    else:
        y_data = data['voltage']
        ylabel = "Voltage (V)"

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
    plt.subplots_adjust(hspace=0.3)

    # Time domain
    ax1.plot(time_axis, y_data, color='forestgreen', lw=0.5)
    ax1.set_title(title)
    ax1.set_xlabel("Time (s)")
    ax1.set_ylabel(ylabel)
    ax1.grid(True, alpha=0.3)

    # Add statistics annotation
    mean_val = np.mean(y_data)
    std_val = np.std(y_data)
    ptp_val = np.ptp(y_data)
    stats_text = f"Mean: {mean_val:.4f}\nStd: {std_val:.4f}\nPk-Pk: {ptp_val:.4f}"
    ax1.text(0.02, 0.98, stats_text, transform=ax1.transAxes,
             verticalalignment='top', fontsize=9, family='monospace',
             bbox=dict(facecolor='white', alpha=0.8))

    # Frequency domain (FFT)
    yf = fft(y_data)
    xf = fftfreq(len(y_data), 1 / sample_rate)
    pos_mask = xf > 0
    ax2.semilogy(xf[pos_mask], 2.0 / len(y_data) * np.abs(yf[pos_mask]), color='crimson')
    ax2.set_title("Noise Frequency Spectrum")
    ax2.set_xlabel("Frequency (Hz)")
    ax2.set_ylabel("Amplitude")
    ax2.grid(True, which="both", alpha=0.3)

    plt.tight_layout()
    return fig


def save_daq_data(
    data: dict,
    base_filename: str = "daq_data",
    save_dir: str = r"E:\MTB project\CW ODMR",
    subfolder: str = "",
    save_csv: bool = True,
    save_plot: bool = True,
    fig: Optional[plt.Figure] = None
) -> dict:
    """
    Save DAQ acquisition data to CSV and/or plot to PNG.

    Parameters
    ----------
    data : dict
        Output from acquire_continuous().
    base_filename : str
        Base name for output files (timestamp will be appended).
    save_dir : str
        Base directory for saving files.
    subfolder : str
        Optional subfolder within save_dir.
    save_csv : bool
        If True, save data to CSV.
    save_plot : bool
        If True, save figure to PNG.
    fig : plt.Figure or None
        Figure to save. If None and save_plot=True, will create one.

    Returns
    -------
    dict
        Dictionary with 'csv_path' and 'png_path' if saved.
    """
    save_path = Path(save_dir) / subfolder
    save_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result = {}

    if save_csv:
        csv_path = save_path / f"{base_filename}_{timestamp}.csv"
        df_dict = {
            'Time_s': data['time'],
            'Voltage_V': data['voltage']
        }
        if 'converted' in data:
            df_dict['Converted'] = data['converted']
        df = pd.DataFrame(df_dict)
        df.to_csv(csv_path, index=False)
        result['csv_path'] = str(csv_path)
        print(f"CSV saved: {csv_path}")

    if save_plot:
        if fig is None:
            fig = analyze_and_plot_stability(data)
        png_path = save_path / f"{base_filename}_{timestamp}.png"
        fig.savefig(png_path, dpi=300, bbox_inches='tight')
        result['png_path'] = str(png_path)
        print(f"Plot saved: {png_path}")

    return result


def monitor_laser_power(
    duration_seconds: float,
    device: str = "Dev3",
    channel: str = "ai0",
    sample_rate: float = 2.0,
    conversion: Tuple[float, float] = (0.9527, 0.0036),
    live_plot: bool = True,
    save_data: bool = True,
    save_dir: str = r"E:\MTB project\CW ODMR",
    subfolder: str = ""
) -> dict:
    """
    High-level function to monitor laser power via photodiode.

    This is a convenience wrapper that combines acquisition, analysis,
    and saving for the common laser power monitoring task.

    Parameters
    ----------
    duration_seconds : float
        Total monitoring time in seconds.
    device : str
        DAQ device name (default "Dev3").
    channel : str
        Analog input channel (default "ai0" for laser PD).
    sample_rate : float
        Samples per second.
    conversion : tuple
        (slope, intercept) to convert voltage to power.
        Default values calibrated for current setup.
    live_plot : bool
        Show live plot during acquisition.
    save_data : bool
        Save CSV and plot after acquisition.
    save_dir : str
        Base directory for saving.
    subfolder : str
        Subfolder within save_dir.

    Returns
    -------
    dict
        Dictionary containing:
        - 'data': raw acquisition data dict
        - 'figure': matplotlib Figure with analysis
        - 'files': dict with saved file paths (if save_data=True)
    """
    # Acquire data
    data = acquire_continuous(
        duration_seconds=duration_seconds,
        device=device,
        channel=channel,
        sample_rate=sample_rate,
        conversion=conversion,
        live_plot=live_plot,
        plot_ylabel="Power (W)"
    )

    # Create analysis plot
    fig = analyze_and_plot_stability(
        data,
        title=f"Laser Power Stability ({duration_seconds}s)",
        ylabel="Power (W)",
        use_converted=True
    )

    result = {
        'data': data,
        'figure': fig
    }

    # Save if requested
    if save_data:
        files = save_daq_data(
            data,
            base_filename="Laser_Power",
            save_dir=save_dir,
            subfolder=subfolder,
            fig=fig
        )
        result['files'] = files

    plt.show()
    return result
