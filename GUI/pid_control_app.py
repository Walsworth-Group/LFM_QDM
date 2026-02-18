"""
SIM960 PID Controller Application

GUI application for controlling SRS SIM960 Analog PID Controller.
Follows the architecture defined in claude_app.md.
"""

import sys
import time
import json
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QLineEdit, QPushButton, QGroupBox,
    QGridLayout, QCheckBox, QTextEdit, QSpinBox, QDoubleSpinBox,
    QAbstractSpinBox
)
from PySide6.QtCore import Qt, Slot, QTimer
from PySide6.QtGui import QFont
import pyqtgraph as pg

# Add parent directory to path to import qdm modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from state.experiment_state import ExperimentState
from workers.pid_worker import PIDWorker
from widgets.real_time_graph import RealTimeGraph

# Configuration file path
CONFIG_FILE = Path(__file__).parent / "config" / "pid_control_config.json"


class PIDControlApp(QMainWindow):
    """
    Main window for SIM960 PID controller application.

    Architecture:
    - PIDState: single source of truth
    - Control tab: main PID control interface
    - Monitor tab: real-time plots
    - Settings tab: connection configuration
    - Hardware interface: SIM900/SIM960 controllers
    """

    def __init__(self, state=None):
        super().__init__()
        # Use provided state or create new one
        self.state = state if state is not None else ExperimentState()

        # Worker thread for hardware communication
        self.worker = None

        # Initialize UI first (creates message_log widget)
        self.init_ui()
        self.connect_signals()
        self.connect_auto_apply()

        # Load saved configuration (after UI is ready)
        self.load_config()

        # Set light background for pyqtgraph
        pg.setConfigOption('background', 'w')
        pg.setConfigOption('foreground', 'k')

    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("SIM960 PID Controller")
        self.setGeometry(100, 100, 480, 800)

        # Create central widget with tab structure
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout()
        central_widget.setLayout(layout)

        # Create tab widget
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Create tabs
        self.control_tab = self.create_control_tab()
        self.monitor_tab = self.create_monitor_tab()
        self.settings_tab = self.create_settings_tab()

        self.tabs.addTab(self.control_tab, "Control")
        self.tabs.addTab(self.monitor_tab, "Monitor")
        self.tabs.addTab(self.settings_tab, "Settings")

        # Message log at bottom
        self.message_log = QTextEdit()
        self.message_log.setReadOnly(True)
        self.message_log.setMaximumHeight(120)
        self.message_log.setPlaceholderText("Status messages will appear here...")
        layout.addWidget(QLabel("Message Log:"))
        layout.addWidget(self.message_log)

    def create_control_tab(self):
        """Create the main PID control tab."""
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)

        # === Connection Status ===
        conn_group = QGroupBox("Connection")
        conn_layout = QHBoxLayout()
        conn_group.setLayout(conn_layout)

        self.connection_status_label = QLabel("Disconnected")
        self.connection_status_label.setStyleSheet("font-weight: bold; color: red;")
        conn_layout.addWidget(QLabel("Status:"))
        conn_layout.addWidget(self.connection_status_label)
        conn_layout.addStretch()

        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.on_connect)
        conn_layout.addWidget(self.connect_button)

        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.clicked.connect(self.on_disconnect)
        self.disconnect_button.setEnabled(False)
        conn_layout.addWidget(self.disconnect_button)

        self.refresh_button = QPushButton("Refresh Status")
        self.refresh_button.clicked.connect(self.on_refresh_status)
        self.refresh_button.setEnabled(False)
        conn_layout.addWidget(self.refresh_button)

        layout.addWidget(conn_group)

        # === Main Display Values ===
        display_group = QGroupBox("Current Values")
        display_layout = QGridLayout()
        display_group.setLayout(display_layout)

        # Large display font
        display_font = QFont()
        display_font.setPointSize(14)
        display_font.setBold(True)

        # Setpoint
        display_layout.addWidget(QLabel("Setpoint:"), 0, 0)
        self.setpoint_display = QLabel("0.000 V")
        self.setpoint_display.setFont(display_font)
        display_layout.addWidget(self.setpoint_display, 0, 1)

        # Output
        display_layout.addWidget(QLabel("Output:"), 0, 2)
        self.output_display = QLabel("0.000 V")
        self.output_display.setFont(display_font)
        self.output_display.setStyleSheet("color: blue;")
        display_layout.addWidget(self.output_display, 0, 3)

        # Error
        display_layout.addWidget(QLabel("Error:"), 1, 0)
        self.error_display = QLabel("0.000 V")
        self.error_display.setFont(display_font)
        self.error_display.setStyleSheet("color: red;")
        display_layout.addWidget(self.error_display, 1, 1)

        # Offset
        display_layout.addWidget(QLabel("Offset:"), 1, 2)
        self.offset_display = QLabel("0.000 V")
        self.offset_display.setFont(display_font)
        display_layout.addWidget(self.offset_display, 1, 3)

        layout.addWidget(display_group)

        # === Mode Control ===
        mode_group = QGroupBox("Mode Control")
        mode_layout = QGridLayout()
        mode_group.setLayout(mode_layout)

        self.manual_mode_checkbox = QCheckBox("Manual Mode")
        self.manual_mode_checkbox.setStyleSheet("font-weight: bold;")
        self.manual_mode_checkbox.clicked.connect(self.on_manual_mode_changed)
        mode_layout.addWidget(self.manual_mode_checkbox, 0, 0, 1, 2)

        mode_layout.addWidget(QLabel("(Unchecked = PID Control Mode)"), 0, 2, 1, 2)

        # Auto-apply checkbox
        self.auto_apply_checkbox = QCheckBox("Auto-Apply Changes")
        self.auto_apply_checkbox.setChecked(False)
        self.auto_apply_checkbox.setToolTip("When enabled, parameters are applied immediately when values change")
        self.auto_apply_checkbox.setStyleSheet("font-weight: bold; color: blue;")
        mode_layout.addWidget(self.auto_apply_checkbox, 1, 0, 1, 4)

        layout.addWidget(mode_group)

        # === PID Parameters ===
        pid_group = QGroupBox("PID Parameters")
        pid_layout = QGridLayout()
        pid_group.setLayout(pid_layout)

        # Setpoint control
        pid_layout.addWidget(QLabel("Setpoint (V):"), 0, 0)
        self.setpoint_input = QDoubleSpinBox()
        self.setpoint_input.setRange(-10.0, 10.0)
        self.setpoint_input.setDecimals(4)
        self.setpoint_input.setSingleStep(0.1)
        self.setpoint_input.setValue(0.0)
        self.setpoint_input.setStepType(QAbstractSpinBox.AdaptiveDecimalStepType)
        pid_layout.addWidget(self.setpoint_input, 0, 1)
        self.set_setpoint_button = QPushButton("Set Setpoint")
        self.set_setpoint_button.clicked.connect(self.on_set_setpoint)
        pid_layout.addWidget(self.set_setpoint_button, 0, 2)

        # Offset control
        pid_layout.addWidget(QLabel("Offset (V):"), 1, 0)
        self.offset_input = QDoubleSpinBox()
        self.offset_input.setRange(-10.0, 10.0)
        self.offset_input.setDecimals(4)
        self.offset_input.setSingleStep(0.1)
        self.offset_input.setValue(0.0)
        self.offset_input.setStepType(QAbstractSpinBox.AdaptiveDecimalStepType)
        pid_layout.addWidget(self.offset_input, 1, 1)
        self.set_offset_button = QPushButton("Set Offset")
        self.set_offset_button.clicked.connect(self.on_set_offset)
        pid_layout.addWidget(self.set_offset_button, 1, 2)

        # P gain
        pid_layout.addWidget(QLabel("P Gain:"), 2, 0)
        self.p_gain_input = QDoubleSpinBox()
        self.p_gain_input.setRange(0.0, 1000.0)
        self.p_gain_input.setDecimals(3)
        self.p_gain_input.setSingleStep(0.1)
        self.p_gain_input.setValue(1.0)
        self.p_gain_input.setStepType(QAbstractSpinBox.AdaptiveDecimalStepType)
        pid_layout.addWidget(self.p_gain_input, 2, 1)
        self.set_p_gain_button = QPushButton("Set P Gain")
        self.set_p_gain_button.clicked.connect(self.on_set_p_gain)
        pid_layout.addWidget(self.set_p_gain_button, 2, 2)

        self.p_control_checkbox = QCheckBox("P Enable")
        self.p_control_checkbox.setChecked(True)
        self.p_control_checkbox.clicked.connect(self.on_p_control_changed)
        pid_layout.addWidget(self.p_control_checkbox, 2, 3)

        # I time
        pid_layout.addWidget(QLabel("I Time (s):"), 3, 0)
        self.i_time_input = QDoubleSpinBox()
        self.i_time_input.setRange(0.0, 1000.0)
        self.i_time_input.setDecimals(3)
        self.i_time_input.setSingleStep(0.1)
        self.i_time_input.setValue(1.0)
        self.i_time_input.setStepType(QAbstractSpinBox.AdaptiveDecimalStepType)
        pid_layout.addWidget(self.i_time_input, 3, 1)
        self.set_i_time_button = QPushButton("Set I Time")
        self.set_i_time_button.clicked.connect(self.on_set_i_time)
        pid_layout.addWidget(self.set_i_time_button, 3, 2)

        self.i_control_checkbox = QCheckBox("I Enable")
        self.i_control_checkbox.setChecked(True)
        self.i_control_checkbox.clicked.connect(self.on_i_control_changed)
        pid_layout.addWidget(self.i_control_checkbox, 3, 3)

        # D time
        pid_layout.addWidget(QLabel("D Time (s):"), 4, 0)
        self.d_time_input = QDoubleSpinBox()
        self.d_time_input.setRange(0.0, 1000.0)
        self.d_time_input.setDecimals(3)
        self.d_time_input.setSingleStep(0.01)
        self.d_time_input.setValue(0.0)
        self.d_time_input.setStepType(QAbstractSpinBox.AdaptiveDecimalStepType)
        pid_layout.addWidget(self.d_time_input, 4, 1)
        self.set_d_time_button = QPushButton("Set D Time")
        self.set_d_time_button.clicked.connect(self.on_set_d_time)
        pid_layout.addWidget(self.set_d_time_button, 4, 2)

        self.d_control_checkbox = QCheckBox("D Enable")
        self.d_control_checkbox.setChecked(False)
        self.d_control_checkbox.clicked.connect(self.on_d_control_changed)
        pid_layout.addWidget(self.d_control_checkbox, 4, 3)

        # Upper limit
        pid_layout.addWidget(QLabel("Upper Limit (V):"), 5, 0)
        self.upper_limit_input = QDoubleSpinBox()
        self.upper_limit_input.setRange(-10.0, 10.0)
        self.upper_limit_input.setDecimals(3)
        self.upper_limit_input.setSingleStep(0.1)
        self.upper_limit_input.setValue(10.0)
        self.upper_limit_input.setStepType(QAbstractSpinBox.AdaptiveDecimalStepType)
        pid_layout.addWidget(self.upper_limit_input, 5, 1)
        self.set_upper_limit_button = QPushButton("Set Upper Limit")
        self.set_upper_limit_button.clicked.connect(self.on_set_upper_limit)
        pid_layout.addWidget(self.set_upper_limit_button, 5, 2)

        # Lower limit
        pid_layout.addWidget(QLabel("Lower Limit (V):"), 6, 0)
        self.lower_limit_input = QDoubleSpinBox()
        self.lower_limit_input.setRange(-10.0, 10.0)
        self.lower_limit_input.setDecimals(3)
        self.lower_limit_input.setSingleStep(0.1)
        self.lower_limit_input.setValue(-10.0)
        self.lower_limit_input.setStepType(QAbstractSpinBox.AdaptiveDecimalStepType)
        pid_layout.addWidget(self.lower_limit_input, 6, 1)
        self.set_lower_limit_button = QPushButton("Set Lower Limit")
        self.set_lower_limit_button.clicked.connect(self.on_set_lower_limit)
        pid_layout.addWidget(self.set_lower_limit_button, 6, 2)

        layout.addWidget(pid_group)

        # === Manual Output Control ===
        manual_group = QGroupBox("Manual Output Control")
        manual_layout = QGridLayout()
        manual_group.setLayout(manual_layout)

        manual_layout.addWidget(QLabel("Manual Output (V):"), 0, 0)
        self.manual_output_input = QDoubleSpinBox()
        self.manual_output_input.setRange(-10.0, 10.0)
        self.manual_output_input.setDecimals(4)
        self.manual_output_input.setSingleStep(0.1)
        self.manual_output_input.setValue(0.0)
        self.manual_output_input.setStepType(QAbstractSpinBox.AdaptiveDecimalStepType)
        manual_layout.addWidget(self.manual_output_input, 0, 1)
        self.set_manual_output_button = QPushButton("Set Manual Output")
        self.set_manual_output_button.clicked.connect(self.on_set_manual_output)
        self.set_manual_output_button.setEnabled(False)
        manual_layout.addWidget(self.set_manual_output_button, 0, 2)

        manual_layout.addWidget(QLabel("(Only active in Manual Mode)"), 1, 0, 1, 3)

        layout.addWidget(manual_group)

        layout.addStretch()

        return tab

    def create_monitor_tab(self):
        """Create the monitoring tab with real-time plots."""
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)

        # === Monitoring Control ===
        monitor_ctrl_group = QGroupBox("Monitoring Control")
        monitor_ctrl_layout = QHBoxLayout()
        monitor_ctrl_group.setLayout(monitor_ctrl_layout)

        self.start_monitor_button = QPushButton("Start Monitoring")
        self.start_monitor_button.clicked.connect(self.on_start_monitoring)
        monitor_ctrl_layout.addWidget(self.start_monitor_button)

        self.stop_monitor_button = QPushButton("Stop Monitoring")
        self.stop_monitor_button.clicked.connect(self.on_stop_monitoring)
        self.stop_monitor_button.setEnabled(False)
        monitor_ctrl_layout.addWidget(self.stop_monitor_button)

        monitor_ctrl_layout.addWidget(QLabel("Update Interval (s):"))
        self.monitor_interval_input = QDoubleSpinBox()
        self.monitor_interval_input.setRange(0.1, 10.0)
        self.monitor_interval_input.setDecimals(1)
        self.monitor_interval_input.setSingleStep(0.1)
        self.monitor_interval_input.setValue(0.5)
        self.monitor_interval_input.setStepType(QAbstractSpinBox.AdaptiveDecimalStepType)
        self.monitor_interval_input.setMaximumWidth(80)
        monitor_ctrl_layout.addWidget(self.monitor_interval_input)

        monitor_ctrl_layout.addStretch()

        layout.addWidget(monitor_ctrl_group)

        # === Real-Time Graphs ===
        # Output graph
        self.output_graph = RealTimeGraph(
            self.state,
            title="Output Voltage vs Time",
            y_label="Output (V)",
            time_window=60
        )
        # Disconnect default and use custom handler
        self.state.data_point_recorded.disconnect(self.output_graph.on_new_data)

        # Error graph
        self.error_graph = RealTimeGraph(
            self.state,
            title="Error Signal vs Time",
            y_label="Error (V)",
            time_window=60
        )
        # Disconnect default
        self.state.data_point_recorded.disconnect(self.error_graph.on_new_data)

        layout.addWidget(self.output_graph)
        layout.addWidget(self.error_graph)

        return tab

    def create_settings_tab(self):
        """Create the settings tab."""
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)

        # === Connection Settings ===
        conn_group = QGroupBox("Connection Settings")
        conn_layout = QGridLayout()
        conn_group.setLayout(conn_layout)

        conn_layout.addWidget(QLabel("COM Port:"), 0, 0)
        self.com_port_input = QLineEdit(self.state.pid_com_port)
        self.com_port_input.setToolTip("VISA resource string (e.g., ASRL3::INSTR or COM3)")
        conn_layout.addWidget(self.com_port_input, 0, 1)

        conn_layout.addWidget(QLabel("SIM900 Module Port (1-8):"), 1, 0)
        self.sim900_port_input = QSpinBox()
        self.sim900_port_input.setRange(1, 8)
        self.sim900_port_input.setValue(self.state.pid_sim900_port)
        self.sim900_port_input.setToolTip("Physical port number where SIM960 is installed")
        conn_layout.addWidget(self.sim900_port_input, 1, 1)

        conn_layout.setColumnStretch(2, 1)

        layout.addWidget(conn_group)

        # === Save Configuration Button ===
        save_config_button = QPushButton("Save Configuration as Default")
        save_config_button.clicked.connect(self.save_config)
        layout.addWidget(save_config_button)

        # === About ===
        about_group = QGroupBox("About")
        about_layout = QVBoxLayout()
        about_group.setLayout(about_layout)

        about_text = QLabel(
            "SIM960 PID Controller Application\n\n"
            "Controls SRS SIM960 Analog PID Controller in SIM900 Mainframe.\n"
            "For laser power stabilization and other control applications.\n\n"
            "Walsworth Group - Harvard University"
        )
        about_text.setWordWrap(True)
        about_layout.addWidget(about_text)

        layout.addWidget(about_group)

        layout.addStretch()

        return tab

    def connect_signals(self):
        """Connect state signals to UI update methods."""
        # Connection state
        self.state.pid_connection_changed.connect(self.on_connection_changed)

        # Parameter updates
        self.state.pid_setpoint_changed.connect(self.on_setpoint_updated)
        self.state.pid_output_changed.connect(self.on_output_updated)
        self.state.pid_error_changed.connect(self.on_error_updated)
        self.state.pid_offset_changed.connect(self.on_offset_updated)

        self.state.pid_p_gain_changed.connect(self.on_p_gain_updated)
        self.state.pid_i_time_changed.connect(self.on_i_time_updated)
        self.state.pid_d_time_changed.connect(self.on_d_time_updated)

        self.state.pid_manual_mode_changed.connect(self.on_manual_mode_updated)

        self.state.pid_upper_limit_changed.connect(self.on_upper_limit_updated)
        self.state.pid_lower_limit_changed.connect(self.on_lower_limit_updated)

        # Status messages
        self.state.pid_status_message.connect(self.on_status_message)

    def connect_auto_apply(self):
        """Connect spinbox value changes to auto-apply functions."""
        # Connect all parameter spinboxes to auto-apply
        self.setpoint_input.valueChanged.connect(self.auto_apply_setpoint)
        self.offset_input.valueChanged.connect(self.auto_apply_offset)
        self.p_gain_input.valueChanged.connect(self.auto_apply_p_gain)
        self.i_time_input.valueChanged.connect(self.auto_apply_i_time)
        self.d_time_input.valueChanged.connect(self.auto_apply_d_time)
        self.upper_limit_input.valueChanged.connect(self.auto_apply_upper_limit)
        self.lower_limit_input.valueChanged.connect(self.auto_apply_lower_limit)
        self.manual_output_input.valueChanged.connect(self.auto_apply_manual_output)

    # === Connection Methods ===

    @Slot()
    def on_connect(self):
        """Connect to SIM900/SIM960 hardware."""
        if self.worker is not None and self.worker.isRunning():
            self.log_message("Already connected")
            return

        try:
            # Apply settings from UI
            self.state.pid_com_port = self.com_port_input.text()
            self.state.pid_sim900_port = self.sim900_port_input.value()

            self.log_message("Connecting to SIM900...")

            # Create and start worker thread
            self.worker = PIDWorker(self.state)
            self.worker.connection_established.connect(self.on_connection_established)
            self.worker.connection_failed.connect(self.on_connection_failed)
            self.worker.status_updated.connect(self.on_status_updated)
            self.worker.parameter_set_success.connect(self.on_parameter_set_success)
            self.worker.parameter_set_failed.connect(self.on_parameter_set_failed)
            self.worker.monitoring_data.connect(self.on_monitoring_data)

            self.worker.start()

        except Exception as e:
            self.log_message(f"Connection failed: {e}")

    @Slot()
    def on_disconnect(self):
        """Disconnect from hardware."""
        # Stop monitoring if active
        if self.state.pid_is_monitoring:
            self.on_stop_monitoring()

        if self.worker is not None:
            self.worker.stop()
            self.worker.wait()  # Wait for thread to finish
            self.worker = None

        self.state.pid_is_connected = False
        self.log_message("Disconnected")

    @Slot()
    def on_refresh_status(self):
        """Refresh status from hardware."""
        if not self.worker or not self.worker.isRunning():
            self.log_message("Not connected")
            return

        self.worker.queue_command('refresh_status')
        self.log_message("Refreshing status...")

    # === PID Parameter Control Methods ===

    @Slot()
    def on_set_setpoint(self):
        """Set setpoint on hardware."""
        if not self.worker or not self.worker.isRunning():
            self.log_message("Not connected to hardware")
            return

        value = self.setpoint_input.value()
        self.worker.queue_command('set_setpoint', value)
        self.log_message(f"Setting setpoint to {value:.4f} V...")

    @Slot()
    def on_set_offset(self):
        """Set offset on hardware."""
        if not self.worker or not self.worker.isRunning():
            self.log_message("Not connected to hardware")
            return

        value = self.offset_input.value()
        self.worker.queue_command('set_offset', value)
        self.log_message(f"Setting offset to {value:.4f} V...")

    @Slot()
    def on_set_p_gain(self):
        """Set proportional gain on hardware."""
        if not self.worker or not self.worker.isRunning():
            self.log_message("Not connected to hardware")
            return

        value = self.p_gain_input.value()
        self.worker.queue_command('set_p_gain', value)
        self.log_message(f"Setting P gain to {value:.3f}...")

    @Slot()
    def on_set_i_time(self):
        """Set integral time on hardware."""
        if not self.worker or not self.worker.isRunning():
            self.log_message("Not connected to hardware")
            return

        value = self.i_time_input.value()
        self.worker.queue_command('set_i_time', value)
        self.log_message(f"Setting I time to {value:.3f} s...")

    @Slot()
    def on_set_d_time(self):
        """Set derivative time on hardware."""
        if not self.worker or not self.worker.isRunning():
            self.log_message("Not connected to hardware")
            return

        value = self.d_time_input.value()
        self.worker.queue_command('set_d_time', value)
        self.log_message(f"Setting D time to {value:.3f} s...")

    @Slot()
    def on_set_upper_limit(self):
        """Set upper output limit on hardware."""
        if not self.worker or not self.worker.isRunning():
            self.log_message("Not connected to hardware")
            return

        value = self.upper_limit_input.value()
        self.worker.queue_command('set_upper_limit', value)
        self.log_message(f"Setting upper limit to {value:.3f} V...")

    @Slot()
    def on_set_lower_limit(self):
        """Set lower output limit on hardware."""
        if not self.worker or not self.worker.isRunning():
            self.log_message("Not connected to hardware")
            return

        value = self.lower_limit_input.value()
        self.worker.queue_command('set_lower_limit', value)
        self.log_message(f"Setting lower limit to {value:.3f} V...")

    @Slot()
    def on_manual_mode_changed(self):
        """Toggle manual/PID mode."""
        if not self.worker or not self.worker.isRunning():
            self.log_message("Not connected to hardware")
            self.manual_mode_checkbox.setChecked(self.state.pid_manual_mode)  # Revert
            return

        value = self.manual_mode_checkbox.isChecked()
        self.worker.queue_command('set_manual_mode', value)
        mode_str = "MANUAL" if value else "PID"
        self.log_message(f"Setting mode to {mode_str}...")

        # Enable/disable manual output button
        self.set_manual_output_button.setEnabled(value)

    @Slot()
    def on_p_control_changed(self):
        """Toggle P control enable."""
        if not self.worker or not self.worker.isRunning():
            self.log_message("Not connected to hardware")
            return

        value = self.p_control_checkbox.isChecked()
        self.worker.queue_command('set_p_control', value)
        self.log_message(f"{'Enabling' if value else 'Disabling'} P control...")

    @Slot()
    def on_i_control_changed(self):
        """Toggle I control enable."""
        if not self.worker or not self.worker.isRunning():
            self.log_message("Not connected to hardware")
            return

        value = self.i_control_checkbox.isChecked()
        self.worker.queue_command('set_i_control', value)
        self.log_message(f"{'Enabling' if value else 'Disabling'} I control...")

    @Slot()
    def on_d_control_changed(self):
        """Toggle D control enable."""
        if not self.worker or not self.worker.isRunning():
            self.log_message("Not connected to hardware")
            return

        value = self.d_control_checkbox.isChecked()
        self.worker.queue_command('set_d_control', value)
        self.log_message(f"{'Enabling' if value else 'Disabling'} D control...")

    @Slot()
    def on_set_manual_output(self):
        """Set manual output voltage."""
        if not self.worker or not self.worker.isRunning():
            self.log_message("Not connected to hardware")
            return

        if not self.state.pid_manual_mode:
            self.log_message("Manual output only available in Manual Mode")
            return

        value = self.manual_output_input.value()
        self.worker.queue_command('set_manual_output', value)
        self.log_message(f"Setting manual output to {value:.4f} V...")

    # === Auto-Apply Methods ===

    @Slot(float)
    def auto_apply_setpoint(self, value):
        """Auto-apply setpoint if checkbox is enabled."""
        if self.auto_apply_checkbox.isChecked():
            if self.worker and self.worker.isRunning():
                self.worker.queue_command('set_setpoint', value)
                self.log_message(f"Auto-applying setpoint: {value:.4f} V")

    @Slot(float)
    def auto_apply_offset(self, value):
        """Auto-apply offset if checkbox is enabled."""
        if self.auto_apply_checkbox.isChecked():
            if self.worker and self.worker.isRunning():
                self.worker.queue_command('set_offset', value)
                self.log_message(f"Auto-applying offset: {value:.4f} V")

    @Slot(float)
    def auto_apply_p_gain(self, value):
        """Auto-apply P gain if checkbox is enabled."""
        if self.auto_apply_checkbox.isChecked():
            if self.worker and self.worker.isRunning():
                self.worker.queue_command('set_p_gain', value)
                self.log_message(f"Auto-applying P gain: {value:.3f}")

    @Slot(float)
    def auto_apply_i_time(self, value):
        """Auto-apply I time if checkbox is enabled."""
        if self.auto_apply_checkbox.isChecked():
            if self.worker and self.worker.isRunning():
                self.worker.queue_command('set_i_time', value)
                self.log_message(f"Auto-applying I time: {value:.3f} s")

    @Slot(float)
    def auto_apply_d_time(self, value):
        """Auto-apply D time if checkbox is enabled."""
        if self.auto_apply_checkbox.isChecked():
            if self.worker and self.worker.isRunning():
                self.worker.queue_command('set_d_time', value)
                self.log_message(f"Auto-applying D time: {value:.3f} s")

    @Slot(float)
    def auto_apply_upper_limit(self, value):
        """Auto-apply upper limit if checkbox is enabled."""
        if self.auto_apply_checkbox.isChecked():
            if self.worker and self.worker.isRunning():
                self.worker.queue_command('set_upper_limit', value)
                self.log_message(f"Auto-applying upper limit: {value:.3f} V")

    @Slot(float)
    def auto_apply_lower_limit(self, value):
        """Auto-apply lower limit if checkbox is enabled."""
        if self.auto_apply_checkbox.isChecked():
            if self.worker and self.worker.isRunning():
                self.worker.queue_command('set_lower_limit', value)
                self.log_message(f"Auto-applying lower limit: {value:.3f} V")

    @Slot(float)
    def auto_apply_manual_output(self, value):
        """Auto-apply manual output if checkbox is enabled and in manual mode."""
        if self.auto_apply_checkbox.isChecked():
            if self.worker and self.worker.isRunning() and self.state.pid_manual_mode:
                self.worker.queue_command('set_manual_output', value)
                self.log_message(f"Auto-applying manual output: {value:.4f} V")

    # === Monitoring Methods ===

    @Slot()
    def on_start_monitoring(self):
        """Start periodic monitoring."""
        if not self.worker or not self.worker.isRunning():
            self.log_message("Not connected to hardware")
            return

        interval = self.monitor_interval_input.value()
        self.worker.start_monitoring(interval)
        self.state.pid_is_monitoring = True

        self.start_monitor_button.setEnabled(False)
        self.stop_monitor_button.setEnabled(True)

        self.log_message(f"Monitoring started (interval: {interval:.1f}s)")

    @Slot()
    def on_stop_monitoring(self):
        """Stop periodic monitoring."""
        if self.worker:
            self.worker.stop_monitoring()

        self.state.pid_is_monitoring = False

        self.start_monitor_button.setEnabled(True)
        self.stop_monitor_button.setEnabled(False)

        self.log_message("Monitoring stopped")

    # === Worker Thread Signal Handlers ===

    @Slot(dict)
    def on_connection_established(self, status_dict):
        """Handle successful hardware connection."""
        self.state.update_pid_from_hardware(status_dict)

        # Calculate initial error
        self.state.pid_error = self.state.pid_setpoint - (self.state.pid_output - self.state.pid_offset)

        self.state.pid_is_connected = True
        self.log_message(f"Connected to SIM960 on port {self.state.pid_sim900_port}")

    @Slot(str)
    def on_connection_failed(self, error_msg):
        """Handle connection failure."""
        self.state.pid_is_connected = False
        self.log_message(f"Connection failed: {error_msg}")

    @Slot(dict)
    def on_status_updated(self, status_dict):
        """Handle status update from hardware."""
        self.state.update_pid_from_hardware(status_dict)

        # Update error
        self.state.pid_error = self.state.pid_setpoint - (self.state.pid_output - self.state.pid_offset)

        self.log_message("Status refreshed")

    @Slot(str, object)
    def on_parameter_set_success(self, param_name, value):
        """Handle successful parameter set."""
        # Update state based on which parameter was set
        if param_name == 'setpoint':
            self.state.pid_setpoint = value
        elif param_name == 'offset':
            self.state.pid_offset = value
        elif param_name == 'p_gain':
            self.state.pid_p_gain = value
        elif param_name == 'i_time':
            self.state.pid_i_time = value
        elif param_name == 'd_time':
            self.state.pid_d_time = value
        elif param_name == 'upper_limit':
            self.state.pid_upper_limit = value
        elif param_name == 'lower_limit':
            self.state.pid_lower_limit = value
        elif param_name == 'manual_mode':
            self.state.pid_manual_mode = value

        self.log_message(f"{param_name} set to {value}")

    @Slot(str, str)
    def on_parameter_set_failed(self, param_name, error_msg):
        """Handle parameter set failure."""
        self.log_message(f"Error setting {param_name}: {error_msg}")

    @Slot(float, float, float, float)
    def on_monitoring_data(self, timestamp, output, error, setpoint):
        """Handle monitoring data from worker thread."""
        # Update state
        self.state.pid_output = output
        self.state.pid_error = error
        self.state.pid_setpoint = setpoint

        # Update graphs
        self.output_graph.on_new_data({'timestamp': timestamp, 'value': output})
        self.error_graph.on_new_data({'timestamp': timestamp, 'value': error})

    # === UI Update Signal Handlers ===

    @Slot(bool)
    def on_connection_changed(self, connected):
        """Update UI based on connection status."""
        if connected:
            self.connection_status_label.setText("Connected")
            self.connection_status_label.setStyleSheet("font-weight: bold; color: green;")
            self.connect_button.setEnabled(False)
            self.disconnect_button.setEnabled(True)
            self.refresh_button.setEnabled(True)
        else:
            self.connection_status_label.setText("Disconnected")
            self.connection_status_label.setStyleSheet("font-weight: bold; color: red;")
            self.connect_button.setEnabled(True)
            self.disconnect_button.setEnabled(False)
            self.refresh_button.setEnabled(False)

    @Slot(str)
    def on_connection_error(self, error_msg):
        """Handle connection errors."""
        self.log_message(f"Connection error: {error_msg}")

    @Slot(float)
    def on_setpoint_updated(self, value):
        """Update setpoint display."""
        self.setpoint_display.setText(f"{value:.4f} V")
        self.setpoint_input.setValue(value)

    @Slot(float)
    def on_output_updated(self, value):
        """Update output display."""
        self.output_display.setText(f"{value:.4f} V")

    @Slot(float)
    def on_error_updated(self, value):
        """Update error display."""
        self.error_display.setText(f"{value:.4f} V")

    @Slot(float)
    def on_offset_updated(self, value):
        """Update offset display."""
        self.offset_display.setText(f"{value:.4f} V")
        self.offset_input.setValue(value)

    @Slot(float)
    def on_p_gain_updated(self, value):
        """Update P gain display."""
        self.p_gain_input.setValue(value)

    @Slot(float)
    def on_i_time_updated(self, value):
        """Update I time display."""
        self.i_time_input.setValue(value)

    @Slot(float)
    def on_d_time_updated(self, value):
        """Update D time display."""
        self.d_time_input.setValue(value)

    @Slot(bool)
    def on_manual_mode_updated(self, value):
        """Update manual mode checkbox."""
        self.manual_mode_checkbox.setChecked(value)
        self.set_manual_output_button.setEnabled(value)

    @Slot(bool)
    def on_p_control_updated(self, value):
        """Update P control checkbox."""
        self.p_control_checkbox.setChecked(value)

    @Slot(bool)
    def on_i_control_updated(self, value):
        """Update I control checkbox."""
        self.i_control_checkbox.setChecked(value)

    @Slot(bool)
    def on_d_control_updated(self, value):
        """Update D control checkbox."""
        self.d_control_checkbox.setChecked(value)

    @Slot(float)
    def on_upper_limit_updated(self, value):
        """Update upper limit display."""
        self.upper_limit_input.setValue(value)

    @Slot(float)
    def on_lower_limit_updated(self, value):
        """Update lower limit display."""
        self.lower_limit_input.setValue(value)

    @Slot(str)
    def on_status_message(self, message):
        """Display status message in log."""
        self.log_message(message)

    # === Configuration Methods ===

    def save_config(self):
        """Save current configuration as default."""
        try:
            config = {
                'com_port': self.com_port_input.text(),
                'sim900_port': self.sim900_port_input.value(),
                'monitor_interval': self.monitor_interval_input.value()
            }

            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)

            self.log_message(f"Configuration saved to {CONFIG_FILE}")

        except Exception as e:
            self.log_message(f"Error saving configuration: {e}")

    def load_config(self):
        """Load configuration from file."""
        if not CONFIG_FILE.exists():
            self.log_message("No saved configuration found, using defaults")
            return

        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)

            # Update state
            self.state.pid_com_port = config.get('com_port', 'ASRL3::INSTR')
            self.state.pid_sim900_port = config.get('sim900_port', 1)
            self.state.pid_monitor_interval = config.get('monitor_interval', 0.5)

            # Update UI widgets with loaded values
            self.com_port_input.setText(self.state.pid_com_port)
            self.sim900_port_input.setValue(self.state.pid_sim900_port)
            self.monitor_interval_input.setValue(self.state.pid_monitor_interval)

            self.log_message(f"Configuration loaded from {CONFIG_FILE}")

        except Exception as e:
            self.log_message(f"Error loading configuration: {e}")

    # === Utility Methods ===

    def log_message(self, message):
        """Add message to log display."""
        timestamp = time.strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {message}"
        self.message_log.append(formatted_message)

    def closeEvent(self, event):
        """Clean up when window is closed."""
        # Stop monitoring
        if self.state.pid_is_monitoring:
            self.on_stop_monitoring()

        # Disconnect hardware
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait()

        event.accept()


def main():
    """Application entry point."""
    app = QApplication(sys.argv)

    # Set application style
    app.setStyle('Fusion')

    window = PIDControlApp()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
