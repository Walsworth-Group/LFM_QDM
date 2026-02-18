"""
Standardized Real-Time Graph for Experimental Control Applications

Drop this file into your project and use:
    from real_time_graph import RealTimeGraph

    graph = RealTimeGraph(state, title="Laser Power", y_label="Power (W)", time_window=60)
    graph.show()

All instances automatically have:
- Enable/disable rolling window checkbox
- Adjustable time window (spinbox, 5s to unlimited)
- Y-axis auto-scale
- X-axis rolling window (when enabled) or manual control (when disabled)
- No SI prefix auto-scaling (prevents "x0.001" labels)
- Info display
- Right-click context menus
"""

import pyqtgraph as pg
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QCheckBox
from PySide6.QtCore import Slot

try:
    from state.experiment_state import ExperimentState
except ImportError:
    from experiment_state import ExperimentState


class RealTimeGraph(QWidget):
    """Standardized real-time plot with adjustable time window

    Features:
    - Enable/disable rolling window checkbox
    - Adjustable time window spinbox (5 seconds to unlimited)
    - Y-axis auto-scales to data
    - X-axis rolling window (when enabled) or manual control (when disabled)
    - No SI prefix auto-scaling on axes (prevents "x0.001" labels)
    - Info display showing current value and window size
    - Right-click controls (Manual, Auto Scale, View All, etc.)
    - Clear data method for reset

    Usage:
        state = ExperimentState()
        graph = RealTimeGraph(state,
                             title="Temperature Monitor",
                             y_label="Temperature (K)",
                             time_window=60)
        graph.show()
    """

    def __init__(self, state: ExperimentState, title: str = "Real-Time Data",
                 y_label: str = "Value", time_window: int = 60):
        """
        Initialize RealTimeGraph

        Args:
            state: ExperimentState instance (provides data_point_recorded signal)
            title: Graph title displayed at top
            y_label: Label for Y-axis
            time_window: Initial time window in seconds (default: 60)
        """
        super().__init__()
        self.state = state
        self.data_x = []
        self.data_y = []
        self.max_points = 10000  # Maximum points to keep in memory
        self.t_start = None
        self.time_window = time_window  # seconds
        self.rolling_window_enabled = True  # Enable rolling window by default
        self.y_label = y_label
        self.init_ui(title)

        # Connect to state data updates
        self.state.data_point_recorded.connect(self.on_new_data)

    def init_ui(self, title):
        """Initialize user interface"""
        layout = QVBoxLayout()

        # ===== Time Window Control =====
        control_layout = QHBoxLayout()

        # Rolling window checkbox
        self.rolling_window_checkbox = QCheckBox("Enable Rolling Window")
        self.rolling_window_checkbox.setChecked(self.rolling_window_enabled)
        self.rolling_window_checkbox.toggled.connect(self.on_rolling_window_toggled)
        control_layout.addWidget(self.rolling_window_checkbox)

        control_layout.addWidget(QLabel("Time Window (s):"))

        self.time_window_spinbox = QSpinBox()
        self.time_window_spinbox.setValue(self.time_window)
        self.time_window_spinbox.setMinimum(5)
        self.time_window_spinbox.setMaximum(999999)  # Essentially unlimited
        self.time_window_spinbox.setSuffix(" s")
        self.time_window_spinbox.valueChanged.connect(self.on_time_window_changed)
        control_layout.addWidget(self.time_window_spinbox)

        control_layout.addStretch()
        layout.addLayout(control_layout)

        # ===== Info Display =====
        self.info_label = QLabel("Ready")
        layout.addWidget(self.info_label)

        # ===== Plot Widget =====
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel('left', self.y_label, units='')
        self.plot_widget.setLabel('bottom', 'Time', units='s')
        self.plot_widget.setTitle(title)

        # Disable SI prefix auto-scaling on Y-axis (prevents "x0.001" labels)
        self.plot_widget.getAxis('left').enableAutoSIPrefix(False)
        self.plot_widget.getAxis('bottom').enableAutoSIPrefix(False)

        # Enable Y-axis auto-scale
        self.plot_widget.enableAutoRange('y', enable=True)

        # Show grid for readability
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)

        # Create line plot
        self.plot_line = self.plot_widget.plot(pen=pg.mkPen('b', width=2))
        layout.addWidget(self.plot_widget)

        self.setLayout(layout)

    def on_time_window_changed(self, value):
        """Handle time window spinbox changes"""
        self.time_window = value

    def on_rolling_window_toggled(self, checked):
        """Handle rolling window checkbox toggle"""
        self.rolling_window_enabled = checked

        if not checked:
            # Disable rolling window - enable auto-range on X
            self.plot_widget.enableAutoRange('x', enable=True)
        else:
            # Re-enable rolling window
            self.plot_widget.enableAutoRange('x', enable=False)

    def on_new_data(self, data):
        """Update plot when new data point arrives

        Args:
            data: Dictionary with 'value' and 'timestamp' keys
                  (from ExperimentState.data_point_recorded signal)
        """
        # Extract value and timestamp from data dict
        value = data.get('value', 0)
        timestamp = data.get('timestamp', 0)

        # Initialize start time on first data point
        if self.t_start is None:
            self.t_start = timestamp

        # Store data point
        self.data_y.append(value)
        self.data_x.append(timestamp - self.t_start)

        # Keep rolling buffer (don't store infinite data)
        if len(self.data_x) > self.max_points:
            self.data_x.pop(0)
            self.data_y.pop(0)

        # Update plot
        self.plot_line.setData(self.data_x, self.data_y)

        # Set X-axis range to show last N seconds (only if rolling window enabled)
        if self.rolling_window_enabled and self.data_x:
            t_max = self.data_x[-1]
            t_min = max(0, t_max - self.time_window)
            self.plot_widget.setXRange(t_min, t_max, padding=0.02)

        # Update info display
        if self.data_y:
            window_status = f"{self.time_window}s" if self.rolling_window_enabled else "Auto"
            self.info_label.setText(
                f"Current: {self.data_y[-1]:.2f} | "
                f"Window: {window_status} | "
                f"Points: {len(self.data_x)}"
            )

    def clear_data(self):
        """Clear all data from plot and reset"""
        self.data_x.clear()
        self.data_y.clear()
        self.t_start = None
        self.plot_line.setData([], [])
        self.info_label.setText("Data cleared")

    def set_time_window(self, seconds):
        """Programmatically set time window

        Args:
            seconds: Time window in seconds (5-3600)
        """
        if 5 <= seconds <= 3600:
            self.time_window_spinbox.setValue(seconds)
            self.time_window = seconds

    def get_current_data(self):
        """Return current data as tuple of (x_list, y_list)"""
        return (self.data_x.copy(), self.data_y.copy())

    def set_y_label(self, label):
        """Update Y-axis label

        Args:
            label: New Y-axis label text
        """
        self.y_label = label
        self.plot_widget.setLabel('left', label, units='')

    def export_csv(self, filename):
        """Export plot data to CSV file

        Args:
            filename: Output CSV filename
        """
        import csv

        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Time (s)', self.y_label])
            for x, y in zip(self.data_x, self.data_y):
                writer.writerow([f'{x:.3f}', f'{y:.6f}'])
