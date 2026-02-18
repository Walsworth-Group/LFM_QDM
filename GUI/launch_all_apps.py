"""
Launch Multiple GUI Applications

Launches multiple experimental control apps in a single QApplication instance.
Windows can communicate via signal/slot connections.
"""

import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Slot

# Import all applications
from laser_power_app import LaserPowerMonitor
from pid_control_app import PIDControlApp
from camera_app import BaslerCameraApp


class AppLauncher:
    """
    Manages multiple application windows.

    All windows share the same QApplication instance and event loop,
    but each has its own state. Windows can communicate via signals.
    """

    def __init__(self):
        # Create single QApplication instance
        self.app = QApplication(sys.argv)
        self.app.setStyle('Fusion')

        # Import shared state
        from state.experiment_state import ExperimentState

        # Create single shared state
        self.shared_state = ExperimentState()

        # Create application windows
        self.laser_power_app = None
        self.pid_control_app = None
        self.camera_app = None

    def launch_laser_power_monitor(self, x=50, y=50):
        """Launch laser power monitoring app with shared state."""
        self.laser_power_app = LaserPowerMonitor(state=self.shared_state)
        self.laser_power_app.setGeometry(x, y, 480, 800)
        self.laser_power_app.show()
        print("[Launcher] Laser Power Monitor launched")

    def launch_pid_controller(self, x=550, y=50):
        """Launch PID controller app with shared state."""
        self.pid_control_app = PIDControlApp(state=self.shared_state)
        self.pid_control_app.setGeometry(x, y, 480, 800)
        self.pid_control_app.show()
        print("[Launcher] PID Controller launched")

    def launch_camera_app(self, x=1050, y=50):
        """Launch Basler camera streaming app with shared state."""
        from state.camera_state import CameraState
        # Camera app uses its own state (CameraState) rather than shared ExperimentState
        camera_state = CameraState()
        self.camera_app = BaslerCameraApp(state=camera_state)
        self.camera_app.setGeometry(x, y, 1400, 900)
        self.camera_app.show()
        print("[Launcher] Basler Camera App launched")

    def connect_apps(self):
        """
        Connect signals between apps for inter-app communication.

        Example: When laser power changes significantly, you might want
        to log it in the PID controller, or vice versa.
        """
        if self.laser_power_app and self.pid_control_app:
            # Example: Connect laser power updates to PID app's message log
            self.laser_power_app.state.laser_power_updated.connect(
                self.on_laser_power_changed
            )

            # Example: Connect PID output changes to laser power app's message log
            self.pid_control_app.state.output_changed.connect(
                self.on_pid_output_changed
            )

            print("[Launcher] Apps connected for inter-communication")

    @Slot(float, float)
    def on_laser_power_changed(self, timestamp, power):
        """Handle laser power changes."""
        # You can log this in the PID app or take other actions
        if self.pid_control_app:
            self.pid_control_app.log_message(f"Laser power: {power:.4f} W")

    @Slot(float)
    def on_pid_output_changed(self, output):
        """Handle PID output changes."""
        # You can log this in the laser power app or take other actions
        pass  # Uncomment below to enable cross-app logging
        # if self.laser_power_app:
        #     # Note: laser_power_app doesn't have log_message, would need to add it
        #     print(f"[Cross-app] PID output: {output:.4f} V")

    def run(self):
        """Start the Qt event loop."""
        return sys.exit(self.app.exec())


def main():
    """Launch all applications."""
    launcher = AppLauncher()

    # Launch all three apps
    launcher.launch_laser_power_monitor(x=50, y=50)
    launcher.launch_pid_controller(x=550, y=50)
    launcher.launch_camera_app(x=1050, y=50)

    # Optionally connect apps for communication
    # Uncomment the line below to enable cross-app messaging
    # launcher.connect_apps()

    # Start Qt event loop (blocks until all windows closed)
    launcher.run()


if __name__ == "__main__":
    main()
