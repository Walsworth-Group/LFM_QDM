"""
Laser Power Monitoring Application

Single-window tabbed interface for monitoring laser power using NI-DAQ.
Follows the architecture defined in claude_app.md.
"""

import sys
import time
from pathlib import Path
from collections import deque
import json
from datetime import datetime
import numpy as np
import pandas as pd
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QLineEdit, QPushButton, QGroupBox,
    QGridLayout, QCheckBox, QFileDialog, QRadioButton, QButtonGroup
)
from PySide6.QtCore import Qt, Slot
import pyqtgraph as pg

# Add parent directory to path to import qdm modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from state.experiment_state import ExperimentState
from workers.daq_worker import DAQWorker
from widgets.real_time_graph import RealTimeGraph

# Configuration file path
CONFIG_FILE = Path(__file__).parent / "config" / "laser_power_config.json"


class LaserPowerMonitor(QMainWindow):
    """
    Main window for laser power monitoring application.

    Architecture:
    - ExperimentState: single source of truth
    - Monitor tab: observes state, displays live data
    - Configuration tab: modifies state settings
    - DAQWorker: runs in background, updates state
    """

    def __init__(self, state=None):
        super().__init__()
        # Use provided state or create new one
        self.state = state if state is not None else ExperimentState()
        self.worker = None

        # Data buffers for statistics (RealTimeGraph handles plotting)
        self.power_data = deque(maxlen=2000)
        self.voltage_data = deque(maxlen=2000)
        self.all_power_values = []

        # Unit conversion (W or mW)
        self.use_mw = False  # Default to Watts

        # Refresh rate control
        self.max_refresh_rate = 10.0  # Hz
        self.last_update_time = 0.0

        # Load saved configuration
        self.load_config()

        self.init_ui()
        self.connect_signals()

    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("Laser Power Monitor")
        self.setGeometry(1700, 100, 480, 800)

        # Create central widget with tab structure
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout()
        central_widget.setLayout(layout)

        # Create tab widget
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Create tabs
        self.monitor_tab = self.create_monitor_tab()
        self.config_tab = self.create_config_tab()

        self.tabs.addTab(self.monitor_tab, "Monitor")
        self.tabs.addTab(self.config_tab, "Configuration")

    def create_monitor_tab(self):
        """Create the main monitoring tab with live chart and controls."""
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)

        # === Status Display ===
        status_group = QGroupBox("Current Status")
        status_layout = QGridLayout()
        status_group.setLayout(status_layout)

        # Unit selection
        status_layout.addWidget(QLabel("Units:"), 0, 0)
        unit_layout = QHBoxLayout()
        self.unit_button_group = QButtonGroup()
        self.unit_w_radio = QRadioButton("W")
        self.unit_mw_radio = QRadioButton("mW")
        self.unit_w_radio.setChecked(True)
        self.unit_button_group.addButton(self.unit_w_radio)
        self.unit_button_group.addButton(self.unit_mw_radio)
        self.unit_w_radio.toggled.connect(self.on_unit_changed)
        unit_layout.addWidget(self.unit_w_radio)
        unit_layout.addWidget(self.unit_mw_radio)
        unit_layout.addStretch()
        status_layout.addLayout(unit_layout, 0, 1, 1, 2)

        status_layout.addWidget(QLabel("Laser Power:"), 1, 0)
        self.power_label = QLabel("0.000 W")
        self.power_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        status_layout.addWidget(self.power_label, 1, 1)

        status_layout.addWidget(QLabel("Voltage:"), 1, 2)
        self.voltage_label = QLabel("0.000 V")
        status_layout.addWidget(self.voltage_label, 1, 3)

        status_layout.addWidget(QLabel("Mean:"), 2, 0)
        self.mean_label = QLabel("0.000 W")
        status_layout.addWidget(self.mean_label, 2, 1)

        status_layout.addWidget(QLabel("Std Dev:"), 2, 2)
        self.std_label = QLabel("0.000 W")
        status_layout.addWidget(self.std_label, 2, 3)

        status_layout.addWidget(QLabel("Peak-Peak:"), 3, 0)
        self.ptp_label = QLabel("0.000 W")
        status_layout.addWidget(self.ptp_label, 3, 1)

        status_layout.addWidget(QLabel("Max Refresh Rate (Hz):"), 4, 0)
        self.refresh_rate_input = QLineEdit(str(self.max_refresh_rate))
        self.refresh_rate_input.setMaximumWidth(80)
        self.refresh_rate_input.textChanged.connect(self.on_refresh_rate_changed)
        status_layout.addWidget(self.refresh_rate_input, 4, 1)

        layout.addWidget(status_group)

        # === Live Chart ===
        # Set light background for pyqtgraph
        pg.setConfigOption('background', 'w')
        pg.setConfigOption('foreground', 'k')

        # Create RealTimeGraph instance
        self.graph = RealTimeGraph(
            self.state,
            title="Laser Power vs Time",
            y_label="Power (W)",
            time_window=60
        )

        # Disconnect default connection and use custom handler for unit conversion
        self.state.data_point_recorded.disconnect(self.graph.on_new_data)
        self.state.data_point_recorded.connect(self.on_graph_data)

        layout.addWidget(self.graph)

        # === Data Saving ===
        save_group = QGroupBox("Data Saving")
        save_layout = QGridLayout()
        save_group.setLayout(save_layout)

        self.auto_save_checkbox = QCheckBox("Automatically save data after stopping acquisition")
        self.auto_save_checkbox.setChecked(self.state.save_data)
        save_layout.addWidget(self.auto_save_checkbox, 0, 0, 1, 3)

        save_layout.addWidget(QLabel("Directory:"), 1, 0)
        self.save_dir_input = QLineEdit(self.state.save_dir)
        save_layout.addWidget(self.save_dir_input, 1, 1)
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self.on_browse_dir)
        save_layout.addWidget(browse_button, 1, 2)

        save_layout.addWidget(QLabel("Subfolder:"), 2, 0)
        self.subfolder_input = QLineEdit(self.state.save_subfolder)
        save_layout.addWidget(self.subfolder_input, 2, 1, 1, 2)

        save_layout.addWidget(QLabel("Filename suffix:"), 3, 0)
        self.filename_suffix_input = QLineEdit("")
        save_layout.addWidget(self.filename_suffix_input, 3, 1, 1, 2)

        self.timestamp_checkbox = QCheckBox("Append timestamp")
        self.timestamp_checkbox.setChecked(True)
        save_layout.addWidget(self.timestamp_checkbox, 4, 0, 1, 3)

        save_button_layout = QHBoxLayout()
        self.save_now_button = QPushButton("Save")
        self.save_now_button.setMaximumWidth(100)
        self.save_now_button.clicked.connect(self.on_save_data)
        save_button_layout.addWidget(self.save_now_button)
        save_button_layout.addStretch()
        save_layout.addLayout(save_button_layout, 5, 0, 1, 3)

        layout.addWidget(save_group)

        # === Control Buttons ===
        button_layout = QHBoxLayout()

        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self.on_start)
        button_layout.addWidget(self.start_button)

        self.pause_button = QPushButton("Pause")
        self.pause_button.setEnabled(False)
        self.pause_button.clicked.connect(self.on_pause)
        button_layout.addWidget(self.pause_button)

        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.setStyleSheet("color: red;")
        self.stop_button.clicked.connect(self.on_stop)
        button_layout.addWidget(self.stop_button)

        self.clear_button = QPushButton("Clear Data")
        self.clear_button.clicked.connect(self.on_clear)
        button_layout.addWidget(self.clear_button)

        layout.addLayout(button_layout)

        return tab

    def create_config_tab(self):
        """Create the configuration tab with DAQ and conversion settings."""
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)

        # === DAQ Configuration ===
        daq_group = QGroupBox("DAQ Configuration")
        daq_layout = QGridLayout()
        daq_group.setLayout(daq_layout)

        daq_layout.addWidget(QLabel("Device:"), 0, 0)
        self.device_input = QLineEdit(self.state.daq_device)
        self.device_input.setMaximumWidth(120)
        daq_layout.addWidget(self.device_input, 0, 1)
        daq_layout.setColumnStretch(2, 1)

        daq_layout.addWidget(QLabel("Channel:"), 1, 0)
        self.channel_input = QLineEdit(self.state.daq_channel)
        self.channel_input.setMaximumWidth(120)
        daq_layout.addWidget(self.channel_input, 1, 1)

        daq_layout.addWidget(QLabel("Sample Rate (Hz):"), 2, 0)
        self.sample_rate_input = QLineEdit(str(self.state.sample_rate))
        self.sample_rate_input.setMaximumWidth(120)
        daq_layout.addWidget(self.sample_rate_input, 2, 1)

        daq_layout.addWidget(QLabel("Batch Size (samples):"), 3, 0)
        self.batch_size_input = QLineEdit(str(self.state.batch_size))
        self.batch_size_input.setMaximumWidth(120)
        self.batch_size_input.setToolTip("Number of samples to accumulate before processing.\n1 = real-time (default), >1 = batched for high-speed acquisition")
        daq_layout.addWidget(self.batch_size_input, 3, 1)

        daq_layout.addWidget(QLabel("Voltage Range Min (V):"), 4, 0)
        self.vrange_min_input = QLineEdit(str(self.state.voltage_range[0]))
        self.vrange_min_input.setMaximumWidth(120)
        daq_layout.addWidget(self.vrange_min_input, 4, 1)

        daq_layout.addWidget(QLabel("Voltage Range Max (V):"), 5, 0)
        self.vrange_max_input = QLineEdit(str(self.state.voltage_range[1]))
        self.vrange_max_input.setMaximumWidth(120)
        daq_layout.addWidget(self.vrange_max_input, 5, 1)

        layout.addWidget(daq_group)

        # === Conversion Configuration ===
        conversion_group = QGroupBox("Voltage to Power Conversion (Power = Voltage × Slope + Intercept)")
        conversion_layout = QGridLayout()
        conversion_group.setLayout(conversion_layout)

        conversion_layout.addWidget(QLabel("Slope:"), 0, 0)
        self.slope_input = QLineEdit(str(self.state.conversion_slope))
        self.slope_input.setMaximumWidth(120)
        conversion_layout.addWidget(self.slope_input, 0, 1)
        conversion_layout.setColumnStretch(2, 1)

        conversion_layout.addWidget(QLabel("Intercept:"), 1, 0)
        self.intercept_input = QLineEdit(str(self.state.conversion_intercept))
        self.intercept_input.setMaximumWidth(120)
        conversion_layout.addWidget(self.intercept_input, 1, 1)

        layout.addWidget(conversion_group)

        # === Save Configuration Button ===
        save_config_button = QPushButton("Save Configuration as Default")
        save_config_button.clicked.connect(self.save_config)
        layout.addWidget(save_config_button)

        layout.addStretch()

        return tab

    def connect_signals(self):
        """Connect state signals to UI update methods."""
        self.state.laser_power_updated.connect(self.on_power_updated)
        self.state.laser_acquisition_started.connect(self.on_acquisition_started)
        self.state.laser_acquisition_stopped.connect(self.on_acquisition_stopped)

    # === Control Methods ===

    @Slot()
    def on_start(self):
        """Start data acquisition."""
        if self.worker is not None and self.worker.is_running:
            if self.worker.is_paused:
                # Resume paused acquisition
                self.worker.resume()
                self.state.is_paused = False
                self.pause_button.setText("Pause")
            return

        # Auto-clear data before starting new acquisition
        self.on_clear()

        # Auto-apply configuration changes
        self.apply_config()

        # Create and start worker thread
        self.worker = DAQWorker(self.state)
        self.worker.data_acquired.connect(self.on_data_acquired)
        self.worker.acquisition_error.connect(self.on_acquisition_error)
        self.worker.acquisition_finished.connect(self.on_acquisition_finished)

        self.state.is_acquiring = True
        self.worker.start()

    @Slot()
    def on_pause(self):
        """Pause/resume data acquisition."""
        if self.worker is None:
            return

        if self.worker.is_paused:
            self.worker.resume()
            self.state.is_paused = False
            self.pause_button.setText("Pause")
        else:
            self.worker.pause()
            self.state.is_paused = True
            self.pause_button.setText("Resume")

    @Slot()
    def on_stop(self):
        """Stop data acquisition."""
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait()  # Wait for thread to finish
            self.state.is_acquiring = False

            # Auto-save if enabled
            if self.auto_save_checkbox.isChecked():
                self.on_save_data()

    @Slot()
    def on_clear(self):
        """Clear all acquired data."""
        self.power_data.clear()
        self.voltage_data.clear()
        self.all_power_values.clear()
        self.graph.clear_data()
        self.update_statistics()

    def apply_config(self):
        """Apply configuration changes from the config tab to state."""
        try:
            # Update DAQ config
            self.state.daq_device = self.device_input.text()
            self.state.daq_channel = self.channel_input.text()
            self.state.sample_rate = float(self.sample_rate_input.text())
            self.state.batch_size = int(self.batch_size_input.text())
            self.state.voltage_range = (
                float(self.vrange_min_input.text()),
                float(self.vrange_max_input.text())
            )

            # Update conversion config
            self.state.set_conversion(
                float(self.slope_input.text()),
                float(self.intercept_input.text())
            )

            # Update save config
            self.state.save_data = self.auto_save_checkbox.isChecked()
            self.state.save_dir = self.save_dir_input.text()
            self.state.save_subfolder = self.subfolder_input.text()

        except ValueError as e:
            print(f"[Config] Error applying configuration: {e}")

    @Slot()
    def on_unit_changed(self):
        """Handle unit toggle between W and mW."""
        was_mw = self.use_mw
        self.use_mw = self.unit_mw_radio.isChecked()

        # Update graph y-axis label
        unit = 'mW' if self.use_mw else 'W'
        self.graph.set_y_label(f"Power ({unit})")

        # Rescale existing graph data
        if self.graph.data_y:
            if was_mw and not self.use_mw:
                # Converting mW -> W: divide by 1000
                self.graph.data_y = [y / 1000.0 for y in self.graph.data_y]
            elif not was_mw and self.use_mw:
                # Converting W -> mW: multiply by 1000
                self.graph.data_y = [y * 1000.0 for y in self.graph.data_y]

            # Redraw plot with rescaled data
            self.graph.plot_line.setData(self.graph.data_x, self.graph.data_y)

        # Update all displayed values
        self.update_statistics()
        if self.power_data:
            self.power_label.setText(f"{self.get_power_in_current_unit(self.power_data[-1]):.4g} {unit}")

    @Slot()
    def on_refresh_rate_changed(self):
        """Handle refresh rate change."""
        try:
            new_rate = float(self.refresh_rate_input.text())
            if new_rate > 0:
                self.max_refresh_rate = new_rate
        except ValueError:
            pass  # Ignore invalid input

    @Slot()
    def on_save_data(self):
        """Save current data to file."""
        # Get data from graph
        time_data, power_data_display = self.graph.get_current_data()

        if not time_data or not self.power_data:
            print("[Save] No data to save")
            return

        try:
            # Prepare filename
            base_name = "Laser_Power"
            suffix = self.filename_suffix_input.text()
            if suffix:
                base_name = f"{base_name}_{suffix}"

            if self.timestamp_checkbox.isChecked():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{base_name}_{timestamp}.csv"
            else:
                filename = f"{base_name}.csv"

            # Prepare directory
            save_path = Path(self.save_dir_input.text())
            if self.subfolder_input.text():
                save_path = save_path / self.subfolder_input.text()
            save_path.mkdir(parents=True, exist_ok=True)

            # Save data
            filepath = save_path / filename
            unit = 'mW' if self.use_mw else 'W'

            # Note: power_data_display is already in display units from the graph
            # voltage_data should have same length as power_data (raw buffer)
            data_to_save = {
                'Time_s': time_data,
                'Voltage_V': list(self.voltage_data)[-len(time_data):],  # Match length
                f'Power_{unit}': power_data_display
            }

            df = pd.DataFrame(data_to_save)
            df.to_csv(filepath, index=False)

            print(f"[Save] Data saved to {filepath}")

        except Exception as e:
            print(f"[Save] Error saving data: {e}")

    def get_power_in_current_unit(self, power_watts):
        """Convert power to current display unit."""
        if self.use_mw:
            return power_watts * 1000.0
        return power_watts

    @Slot()
    def save_config(self):
        """Save current configuration as default."""
        try:
            config = {
                'daq_device': self.device_input.text(),
                'daq_channel': self.channel_input.text(),
                'sample_rate': float(self.sample_rate_input.text()),
                'batch_size': int(self.batch_size_input.text()),
                'voltage_range_min': float(self.vrange_min_input.text()),
                'voltage_range_max': float(self.vrange_max_input.text()),
                'conversion_slope': float(self.slope_input.text()),
                'conversion_intercept': float(self.intercept_input.text()),
                'save_dir': self.save_dir_input.text(),
                'save_subfolder': self.subfolder_input.text(),
                'auto_save': self.auto_save_checkbox.isChecked(),
                'append_timestamp': self.timestamp_checkbox.isChecked(),
                'max_refresh_rate': float(self.refresh_rate_input.text())
            }

            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)

            print(f"[Config] Configuration saved to {CONFIG_FILE}")

        except Exception as e:
            print(f"[Config] Error saving configuration: {e}")

    def load_config(self):
        """Load configuration from file."""
        if not CONFIG_FILE.exists():
            print("[Config] No saved configuration found, using defaults")
            return

        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)

            # Apply to state
            self.state.daq_device = config.get('daq_device', 'Dev3')
            self.state.daq_channel = config.get('daq_channel', 'ai0')
            self.state.sample_rate = config.get('sample_rate', 2.0)
            self.state.batch_size = config.get('batch_size', 1)
            self.state.voltage_range = (
                config.get('voltage_range_min', -10.0),
                config.get('voltage_range_max', 10.0)
            )
            self.state.set_conversion(
                config.get('conversion_slope', 0.9527),
                config.get('conversion_intercept', 0.0036)
            )
            self.state.save_dir = config.get('save_dir', r"E:\MTB project\CW ODMR")
            self.state.save_subfolder = config.get('save_subfolder', '')
            self.state.save_data = config.get('auto_save', False)

            # Load refresh rate
            self.max_refresh_rate = config.get('max_refresh_rate', 10.0)

            print(f"[Config] Configuration loaded from {CONFIG_FILE}")

        except Exception as e:
            print(f"[Config] Error loading configuration: {e}")

    @Slot()
    def on_browse_dir(self):
        """Open directory browser for save directory."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Save Directory",
            self.save_dir_input.text()
        )
        if directory:
            self.save_dir_input.setText(directory)

    # === Signal Handlers ===

    @Slot(float, float, float)
    def on_data_acquired(self, timestamp, voltage, power):
        """Handle new data point from worker thread."""
        # Update state (RealTimeGraph will handle plotting automatically)
        self.state.update_laser_power(timestamp, power)

        # Update buffers for statistics
        self.power_data.append(power)
        self.voltage_data.append(voltage)
        self.all_power_values.append(power)

        # Check if enough time has passed based on max refresh rate
        current_time = time.time()
        min_update_interval = 1.0 / self.max_refresh_rate if self.max_refresh_rate > 0 else 0.1

        if (current_time - self.last_update_time) >= min_update_interval:
            self.update_statistics()
            self.last_update_time = current_time

    @Slot(dict)
    def on_graph_data(self, data):
        """Handle data for graph with unit conversion."""
        # Convert power to current display units
        power_watts = data['value']
        power_display = self.get_power_in_current_unit(power_watts)

        # Create new data dict with converted value
        converted_data = {
            'timestamp': data['timestamp'],
            'value': power_display
        }

        # Pass to graph
        self.graph.on_new_data(converted_data)

    @Slot(float, float)
    def on_power_updated(self, timestamp, power):
        """React to laser power update from state."""
        unit = 'mW' if self.use_mw else 'W'
        power_display = self.get_power_in_current_unit(power)
        self.power_label.setText(f"{power_display:.4g} {unit}")
        if self.voltage_data:
            self.voltage_label.setText(f"{self.voltage_data[-1]:.4g} V")

    @Slot(str)
    def on_acquisition_error(self, error_msg):
        """Handle acquisition errors."""
        print(f"[Error] {error_msg}")
        self.state.is_acquiring = False

    @Slot()
    def on_acquisition_started(self):
        """Update UI when acquisition starts."""
        self.start_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        print("[Acquisition] Started")

    @Slot()
    def on_acquisition_stopped(self):
        """Update UI when acquisition stops."""
        self.start_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.pause_button.setText("Pause")
        self.stop_button.setEnabled(False)
        print("[Acquisition] Stopped")

    @Slot()
    def on_acquisition_finished(self):
        """Handle acquisition completion."""
        print("[Acquisition] Finished")
        self.update_statistics()

    def update_statistics(self):
        """Update statistical display labels."""
        unit = 'mW' if self.use_mw else 'W'

        if not self.all_power_values:
            self.mean_label.setText(f"0 {unit}")
            self.std_label.setText(f"0 {unit}")
            self.ptp_label.setText(f"0 {unit}")
            return

        power_array = np.array(self.all_power_values)
        mean_val = self.get_power_in_current_unit(np.mean(power_array))
        std_val = self.get_power_in_current_unit(np.std(power_array))
        ptp_val = self.get_power_in_current_unit(np.ptp(power_array))

        self.mean_label.setText(f"{mean_val:.4g} {unit}")
        self.std_label.setText(f"{std_val:.4g} {unit}")
        self.ptp_label.setText(f"{ptp_val:.4g} {unit}")

    def closeEvent(self, event):
        """Clean up when window is closed."""
        if self.worker is not None and self.worker.is_running:
            self.worker.stop()
            self.worker.wait()
        event.accept()


def main():
    """Application entry point."""
    app = QApplication(sys.argv)

    # Set application style
    app.setStyle('Fusion')

    window = LaserPowerMonitor()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
