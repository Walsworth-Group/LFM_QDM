"""
LFMMainWindow -- Main application window for light field microscopy.

Composes all tabs (Camera, Calibration, Reconstruction, Volume Viewer,
Settings) and wires them to LFMAppState.

Typical usage::

    from lfm_main_window import LFMMainWindow
    from state.lfm_state import LFMAppState

    state = LFMAppState()
    window = LFMMainWindow(lfm_state=state)
    window.show()
"""

import sys
import json
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QMessageBox, QFileDialog, QMenuBar, QMenu, QPushButton,
    QLabel, QStatusBar,
)
from PySide6.QtCore import Slot, Qt
from PySide6.QtWidgets import QApplication

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_LFM_APP_ROOT = Path(__file__).parent                # .../GUI/lfm_app/
_GUI_ROOT = Path(__file__).parent.parent              # .../GUI/
_PROJECT_ROOT = Path(__file__).parent.parent.parent   # .../LFM software/

for _p in [str(_PROJECT_ROOT), str(_LFM_APP_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Internal imports
# ---------------------------------------------------------------------------
from state.lfm_state import LFMAppState, CameraMode

# ---------------------------------------------------------------------------
# Config file path
# ---------------------------------------------------------------------------
CONFIG_FILE = _LFM_APP_ROOT / "config" / "lfm_app_config.json"


class LFMMainWindow(QMainWindow):
    """
    Main window for the Light Field Microscopy GUI application.

    Hosts a QTabWidget with tabs for Camera, Calibration, Reconstruction,
    Volume Viewer, and Settings.

    Parameters
    ----------
    lfm_state : LFMAppState, optional
        Shared application state.  A new instance is created if not provided.
    shared_state : object, optional
        Optional ExperimentState for cross-app communication.
    parent : QWidget, optional
        Qt parent widget.
    """

    def __init__(self, lfm_state=None, shared_state=None, parent=None):
        super().__init__(parent)

        # -- State ----------------------------------------------------------
        self.state = lfm_state or LFMAppState(shared_state=shared_state)

        # -- Camera reconnect tracking --------------------------------------
        self._camera_was_connected = False

        # -- Build UI -------------------------------------------------------
        self.setWindowTitle("LFM Control")
        self.resize(1600, 1000)

        # Central tab widget
        self._tab_widget = QTabWidget()
        self.setCentralWidget(self._tab_widget)

        # Create placeholder tabs
        self._camera_tab = QWidget()
        self._calibration_tab = QWidget()
        self._reconstruction_tab = QWidget()
        self._volume_viewer_tab = QWidget()
        self._settings_tab = QWidget()

        self._tab_widget.addTab(self._camera_tab, "Camera")
        self._tab_widget.addTab(self._calibration_tab, "Calibration")
        self._tab_widget.addTab(self._reconstruction_tab, "Reconstruction")
        self._tab_widget.addTab(self._volume_viewer_tab, "Volume Viewer")
        self._tab_widget.addTab(self._settings_tab, "Settings")

        # -- Menu bar -------------------------------------------------------
        self._build_menu_bar()

        # -- Status bar -----------------------------------------------------
        self.setStatusBar(QStatusBar())

        # -- Embed camera tab -----------------------------------------------
        self._camera_widget = None
        self._embed_camera_tab()

        # -- Load config ----------------------------------------------------
        self._load_config()

        # -- Tab handlers ---------------------------------------------------
        from tabs.calibration_tab import CalibrationTabHandler
        self._calibration_handler = CalibrationTabHandler(
            self._calibration_tab, self.state,
            stop_streaming_fn=self._stop_streaming_if_needed,
            set_camera_mode_fn=lambda mode: setattr(
                self.state, 'lfm_camera_mode', mode),
        )

        from tabs.reconstruction_tab import ReconstructionTabHandler
        self._reconstruction_handler = ReconstructionTabHandler(
            self._reconstruction_tab, self.state,
            stop_streaming_fn=self._stop_streaming_if_needed,
            set_camera_mode_fn=lambda mode: setattr(
                self.state, 'lfm_camera_mode', mode),
        )

        from tabs.volume_viewer_tab import VolumeViewerTabHandler
        self._volume_handler = VolumeViewerTabHandler(
            self._volume_viewer_tab, self.state)

        from tabs.settings_tab import SettingsTabHandler
        self._settings_handler = SettingsTabHandler(
            self._settings_tab, self.state)

        # -- Wire global signals -------------------------------------------
        self.state.status_message.connect(self._on_status_message)

    # ======================================================================
    # Menu bar
    # ======================================================================

    def _build_menu_bar(self):
        """Create File menu with Save/Load/Reset config actions."""
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&File")

        save_action = file_menu.addAction("&Save Configuration")
        save_action.triggered.connect(self._save_config)

        load_action = file_menu.addAction("&Load Configuration...")
        load_action.triggered.connect(self._on_load_config)

        file_menu.addSeparator()

        reset_action = file_menu.addAction("&Reset to Defaults")
        reset_action.triggered.connect(self._on_reset_defaults)

    # ======================================================================
    # Camera tab embedding
    # ======================================================================

    def _embed_camera_tab(self):
        """Embed CameraTabWidget inside the Camera tab."""
        # Same sys.modules isolation pattern as odmr_main_window.py.
        # camera_app.py imports 'from state.camera_state import ...' etc.
        # We need to temporarily swap sys.modules so camera_app finds
        # GUI/state/ and GUI/workers/ instead of lfm_app/state/.

        _conflicting_keys = [
            k for k in sys.modules
            if k == 'state' or k.startswith('state.')
            or k == 'workers' or k.startswith('workers.')
        ]
        _saved_modules = {k: sys.modules.pop(k) for k in _conflicting_keys}

        gui_root = str(_GUI_ROOT)
        _saved_path = sys.path[:]
        sys.path.insert(0, gui_root)

        try:
            import camera_app as _cam_module  # noqa: PLC0415
        finally:
            sys.path[:] = _saved_path
            for _k in list(sys.modules.keys()):
                if (_k in ('state', 'workers')
                        or _k.startswith('state.')
                        or _k.startswith('workers.')):
                    sys.modules.pop(_k, None)
            for _key, _mod in _saved_modules.items():
                qualified = f"lfm_app.{_key}"
                sys.modules.setdefault(qualified, _mod)

        CameraTabWidget = _cam_module.CameraTabWidget
        CameraState = _cam_module.CameraState

        camera_state = CameraState()

        if self.state.lfm_camera_serial:
            camera_state.camera_serial_number = self.state.lfm_camera_serial

        _lfm_cam_cfg = _LFM_APP_ROOT / "config" / "lfm_camera_config.json"
        self._camera_widget = CameraTabWidget(
            state=camera_state, config_file=_lfm_cam_cfg, parent=self)

        self.state.camera_state = camera_state

        # Build camera tab layout with capture buttons at bottom
        layout = QVBoxLayout(self._camera_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._camera_widget, stretch=1)

        # Capture buttons
        btn_layout = QHBoxLayout()
        self._btn_capture_white = QPushButton("Capture as White Image")
        self._btn_capture_raw = QPushButton("Capture as Raw LFM Image")
        self._btn_capture_white.setMinimumHeight(36)
        self._btn_capture_raw.setMinimumHeight(36)
        btn_layout.addWidget(self._btn_capture_white)
        btn_layout.addWidget(self._btn_capture_raw)
        layout.addLayout(btn_layout)

        self._btn_capture_white.clicked.connect(self._on_capture_white)
        self._btn_capture_raw.clicked.connect(self._on_capture_raw)

        # React to camera mode changes
        self.state.camera_mode_changed.connect(self._on_camera_mode_changed)

    @Slot()
    def _on_capture_white(self):
        """Grab current averaged frame as white calibration image."""
        frame = self._get_current_frame()
        if frame is None:
            return
        self.state.white_image = frame.copy()
        self.state.white_image_path = "(from camera)"
        if self.state.calibration_stage.value == "unconfigured" and self.state.config_yaml_path:
            self.state.calibration_stage = "white_loaded"
        self.state.status_message.emit(
            f"White image captured: {frame.shape[1]}x{frame.shape[0]}")

    @Slot()
    def _on_capture_raw(self):
        """Grab current averaged frame as raw LFM image for reconstruction."""
        frame = self._get_current_frame()
        if frame is None:
            return
        self.state.recon_raw_image = frame.copy()
        self.state.status_message.emit(
            f"Raw LFM image captured: {frame.shape[1]}x{frame.shape[0]}")

    def _get_current_frame(self):
        """Get the most recent frame from the camera widget."""
        if self._camera_widget is None:
            QMessageBox.warning(self, "No Camera", "Camera is not connected.")
            return None
        # CameraTabWidget stores the most recent averaged frame
        frame = getattr(self._camera_widget, 'current_averaged_frame', None)
        if frame is None:
            # Fall back to live frame
            frame = getattr(self._camera_widget, 'current_live_frame', None)
        if frame is None:
            QMessageBox.warning(
                self, "No Frame",
                "No frame available. Start camera streaming first.")
            return None
        return frame

    # ======================================================================
    # Camera mode management
    # ======================================================================

    def _stop_streaming_if_needed(self):
        """Stop camera streaming before acquisition tasks."""
        if self._camera_widget is not None:
            cs = self.state.camera_state
            if cs is not None and cs.camera_is_streaming:
                self._camera_was_connected = True
                self._camera_widget.stop_streaming()

    @Slot(str)
    def _on_camera_mode_changed(self, mode: str):
        """Re-enable streaming when acquisition finishes."""
        if mode == CameraMode.IDLE.value and self._camera_was_connected:
            self._camera_was_connected = False

    # ======================================================================
    # Config persistence
    # ======================================================================

    def _load_config(self, path=None):
        """Load configuration from JSON file."""
        cfg_path = Path(path) if path else CONFIG_FILE
        if not cfg_path.exists():
            return
        try:
            with open(cfg_path, 'r') as f:
                config = json.load(f)
            self.state.load_config(config)
        except Exception as exc:
            print(f"[LFM] Warning: could not load config: {exc}")

    def _save_config(self):
        """Save current configuration to JSON file."""
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self.state.get_config(), f, indent=2)
            self.state.status_message.emit("Configuration saved.")
        except Exception as exc:
            QMessageBox.warning(
                self, "Save Error", f"Could not save config:\n{exc}")

    @Slot()
    def _on_load_config(self):
        """Browse for a config file and load it."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Configuration",
            str(CONFIG_FILE.parent),
            "JSON files (*.json)")
        if path:
            self._load_config(path)
            self.state.status_message.emit(f"Config loaded from {path}")

    @Slot()
    def _on_reset_defaults(self):
        """Reset state to defaults by creating a fresh LFMAppState."""
        reply = QMessageBox.question(
            self, "Reset to Defaults",
            "Reset all settings to default values?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            fresh = LFMAppState(shared_state=self.state.shared_state)
            self.state.load_config(fresh.get_config())
            self.state.status_message.emit("Settings reset to defaults.")

    # ======================================================================
    # Status bar
    # ======================================================================

    @Slot(str)
    def _on_status_message(self, msg: str):
        """Display a status message in the Qt status bar."""
        self.statusBar().showMessage(msg)

    # ======================================================================
    # Cleanup
    # ======================================================================

    def closeEvent(self, event):
        """Save config and clean up workers on close."""
        self._save_config()

        # Stop any running calibration/reconstruction workers
        if hasattr(self, '_calibration_handler'):
            self._calibration_handler.abort_if_running()
        if hasattr(self, '_reconstruction_handler'):
            self._reconstruction_handler.abort_if_running()

        # Clean up camera
        if self._camera_widget is not None:
            self._camera_widget.close()

        # Release large calibration arrays
        self.state.clear_calibration()
        self.state.recon_volume = None
        self.state.recon_raw_image = None

        super().closeEvent(event)
