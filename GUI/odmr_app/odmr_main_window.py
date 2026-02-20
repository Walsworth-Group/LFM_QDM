"""
ODMRMainWindow — Main application window for CW ODMR magnetometry.

Composes all tabs (Camera, ODMR Sweep, Magnetometry, Analysis, Sensitivity,
Settings) and wires the global RF panel and save bar to ODMRAppState.

Typical usage::

    from odmr_main_window import ODMRMainWindow
    from state.odmr_state import ODMRAppState

    state = ODMRAppState()
    window = ODMRMainWindow(odmr_state=state)
    window.show()
"""

import sys
import json
from pathlib import Path
from datetime import datetime

from PySide6.QtWidgets import (
    QMainWindow, QVBoxLayout, QMessageBox, QFileDialog,
)
from PySide6.QtCore import Slot, QTimer
from PySide6.QtWidgets import QApplication

# ---------------------------------------------------------------------------
# Path setup — allow imports from GUI/ root and project root
# ---------------------------------------------------------------------------
_ODMR_APP_ROOT = Path(__file__).parent               # .../GUI/odmr_app/
_GUI_ROOT = Path(__file__).parent.parent              # .../GUI/
_PROJECT_ROOT = Path(__file__).parent.parent.parent   # .../ODMR code v2/

# Add odmr_app/ first, then project root.  GUI/ is intentionally NOT added at
# module level — it would cause GUI/state/ to shadow GUI/odmr_app/state/.
# GUI/ is added lazily when camera_app is imported inside _embed_camera_tab().
for _p in [str(_PROJECT_ROOT), str(_ODMR_APP_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Internal imports — use state.*/ui.*/workers.* directly because GUI/odmr_app/
# is the first entry in sys.path (added above), so 'state' resolves to
# GUI/odmr_app/state/ rather than the shared GUI/state/.
# ---------------------------------------------------------------------------
from ui.ui_odmr_app_main import Ui_ODMRMainWindow
from state.odmr_state import ODMRAppState, CameraMode
from workers.sg384_worker import SG384Worker

# CameraTabWidget is imported lazily inside _embed_camera_tab() to avoid its
# sys.path manipulation interfering with odmr_app's own 'state' package.

# SG384 controller — imported lazily in _connect_rf to avoid VISA import at
# module load time (allows headless/smoke-test imports without VISA installed).
try:
    import qdm_srs
    _QDM_SRS_AVAILABLE = True
except ImportError:
    _QDM_SRS_AVAILABLE = False

# ---------------------------------------------------------------------------
# Config file path
# ---------------------------------------------------------------------------
CONFIG_FILE = Path(__file__).parent / "config" / "odmr_app_config.json"


class ODMRMainWindow(QMainWindow):
    """
    Main window for the CW ODMR magnetometry GUI application.

    Hosts the RF panel, tab widget (Camera / ODMR Sweep / Magnetometry /
    Analysis / Sensitivity / Settings) and the global save bar.

    Parameters
    ----------
    odmr_state : ODMRAppState, optional
        Shared application state.  A new instance is created if not provided.
    shared_state : object, optional
        Optional ExperimentState (laser / PID) passed through to ODMRAppState.
    parent : QWidget, optional
        Qt parent widget.
    """

    def __init__(self, odmr_state=None, shared_state=None, parent=None):
        super().__init__(parent)

        # -- State ----------------------------------------------------------
        self.state = odmr_state or ODMRAppState(shared_state=shared_state)

        # -- RF worker (created on connect) ---------------------------------
        self.sg384_worker = None

        # -- Build UI -------------------------------------------------------
        self.ui = Ui_ODMRMainWindow()
        self.ui.setupUi(self)

        # -- Sub-components -------------------------------------------------
        self._embed_camera_tab()
        self._load_config()
        self._connect_rf_panel()
        self._connect_save_bar()
        self._connect_file_menu()
        self._connect_state_to_ui()
        self._sync_ui_from_state()

        # -- Settings tab (wired last so state is fully loaded) -------------
        from tabs.settings_tab import SettingsTabHandler
        self._settings_handler = SettingsTabHandler(self.ui.settings_tab, self.state)

    # ======================================================================
    # Camera tab embedding
    # ======================================================================

    def _embed_camera_tab(self):
        """Embed CameraTabWidget inside the Camera tab of the main tab widget."""
        # camera_app.py (in GUI/) imports 'from state.camera_state import ...'
        # and 'from workers.camera_worker import ...' at module level.
        # odmr_app's module-level imports have already cached 'state' and
        # 'workers' in sys.modules pointing to odmr_app/state/ and
        # odmr_app/workers/ respectively — neither of which has camera_state or
        # camera_worker.
        #
        # Solution: before importing camera_app, temporarily remove the odmr_app
        # package entries from sys.modules and insert GUI/ at the front of
        # sys.path so camera_app finds GUI/state/ and GUI/workers/.  Afterwards,
        # re-register the odmr_app packages under qualified names.

        # Packages that camera_app needs from GUI/, but odmr_app has already
        # cached from odmr_app/ — save and remove them.
        _conflicting_keys = [k for k in sys.modules if k == 'state'
                             or k.startswith('state.')
                             or k == 'workers'
                             or k.startswith('workers.')]
        _saved_modules = {k: sys.modules.pop(k) for k in _conflicting_keys}

        # Ensure GUI/ is first on sys.path so camera_app's imports resolve
        # to GUI/state/ and GUI/workers/.
        gui_root = str(_GUI_ROOT)
        if gui_root not in sys.path:
            sys.path.insert(0, gui_root)

        try:
            import camera_app as _cam_module  # noqa: PLC0415
        finally:
            # Restore odmr_app packages under their qualified names so that
            # any code in this module referencing ODMRAppState etc. still works.
            for _key, _mod in _saved_modules.items():
                qualified = f"odmr_app.{_key}"
                sys.modules.setdefault(qualified, _mod)

        CameraTabWidget = _cam_module.CameraTabWidget
        CameraState = _cam_module.CameraState

        camera_state = CameraState()

        # Propagate ODMR-side camera serial if set
        if self.state.odmr_camera_serial:
            camera_state.camera_serial_number = self.state.odmr_camera_serial

        self._camera_widget = CameraTabWidget(state=camera_state, parent=self)

        # Store reference so other parts of the app can reach it
        self.state.camera_state = camera_state

        # Embed into the Camera tab
        tab = self.ui.camera_tab
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._camera_widget)

        # React to ODMR-level camera mode changes
        self.state.camera_mode_changed.connect(self._on_camera_mode_changed)

        # React to camera streaming state so we can update ODMR state
        if hasattr(camera_state, 'camera_streaming_changed'):
            camera_state.camera_streaming_changed.connect(
                self._on_camera_streaming_changed
            )

    # ======================================================================
    # RF panel
    # ======================================================================

    def _connect_rf_panel(self):
        """Wire RF panel buttons and state signals."""
        ui = self.ui

        # Button clicks
        ui.rf_connect_btn.clicked.connect(self._on_rf_connect_clicked)
        ui.rf_set_btn.clicked.connect(self._on_rf_set_freq)

        # State → UI
        self.state.rf_connection_changed.connect(self._on_rf_connection_changed)
        self.state.rf_frequency_changed.connect(self._on_rf_frequency_changed)
        self.state.sweep_running_changed.connect(self._on_sweep_running_changed)
        self.state.mag_running_changed.connect(self._on_mag_running_changed)

    @Slot()
    def _on_rf_connect_clicked(self):
        """Toggle RF connection."""
        if self.sg384_worker is not None and self.sg384_worker.isRunning():
            self._disconnect_rf()
        else:
            self._connect_rf()

    def _connect_rf(self):
        """Open connection to SG384 and start the worker thread."""
        if not _QDM_SRS_AVAILABLE:
            QMessageBox.critical(
                self, "Import Error",
                "qdm_srs module could not be imported.  "
                "Ensure the project root is on PYTHONPATH."
            )
            return

        try:
            ctrl = qdm_srs.SG384Controller(self.state.rf_address)
            ctrl.open_connection()
            self.state.sg384_controller = ctrl
            self.state.rf_is_connected = True

            self.sg384_worker = SG384Worker(self.state, parent=self)
            self.sg384_worker.connected.connect(self._on_worker_connected)
            self.sg384_worker.connection_failed.connect(self._on_worker_connection_failed)
            self.sg384_worker.frequency_polled.connect(
                lambda freq: setattr(self.state, 'rf_current_freq_ghz', freq)
            )
            self.sg384_worker.start()

        except Exception as exc:
            QMessageBox.critical(
                self, "RF Connection Error",
                f"Could not connect to SG384 at {self.state.rf_address}:\n{exc}"
            )

    def _disconnect_rf(self):
        """Stop the SG384 worker and close the VISA connection."""
        if self.sg384_worker is not None:
            self.sg384_worker.stop()
            self.sg384_worker.wait(3000)
            self.sg384_worker = None

        if self.state.sg384_controller is not None:
            try:
                self.state.sg384_controller.close_connection()
            except Exception:
                pass
            self.state.sg384_controller = None

        self.state.rf_is_connected = False

    @Slot(dict)
    def _on_worker_connected(self, info):
        """Handle SG384Worker connected signal."""
        freq = info.get('freq_ghz', 0.0)
        self.state.rf_current_freq_ghz = freq
        self.statusBar().showMessage(
            f"RF connected: {info.get('address', '')}  ({freq:.6f} GHz)"
        )

    @Slot(str)
    def _on_worker_connection_failed(self, error_msg):
        """Handle SG384Worker connection_failed signal."""
        self.state.rf_is_connected = False
        self.sg384_worker = None
        QMessageBox.critical(self, "RF Worker Error", error_msg)

    @Slot(bool)
    def _on_rf_connection_changed(self, connected):
        """Update RF panel widgets when connection state changes."""
        ui = self.ui
        if connected:
            ui.rf_connect_btn.setText("Disconnect RF")
            ui.rf_status_label.setText("\u25cf Connected")
            ui.rf_status_label.setStyleSheet("color: green;")
        else:
            ui.rf_connect_btn.setText("Connect RF")
            ui.rf_status_label.setText("\u25cf Disconnected")
            ui.rf_status_label.setStyleSheet("color: red;")

        busy = self._is_busy()
        ui.rf_set_btn.setEnabled(connected and not busy)
        ui.rf_freq_spinbox.setEnabled(connected and not busy)

    @Slot(float)
    def _on_rf_frequency_changed(self, freq_ghz):
        """Update frequency label when RF frequency changes."""
        self.ui.rf_freq_label.setText(f"Freq: {freq_ghz:.6f} GHz")

    @Slot()
    def _on_rf_set_freq(self):
        """Queue a set_frequency command to the SG384 worker."""
        if self.sg384_worker is None or not self.sg384_worker.isRunning():
            return
        freq_ghz = self.ui.rf_freq_spinbox.value()
        self.sg384_worker.queue_command('set_frequency', freq_ghz)

    @Slot(bool)
    def _on_sweep_running_changed(self, running):
        """Disable RF controls while a sweep is running."""
        connected = self.state.rf_is_connected
        self.ui.rf_set_btn.setEnabled(connected and not running and not self.state.mag_is_running)
        self.ui.rf_freq_spinbox.setEnabled(connected and not running and not self.state.mag_is_running)

    @Slot(bool)
    def _on_mag_running_changed(self, running):
        """Disable RF set button while magnetometry is running."""
        connected = self.state.rf_is_connected
        self.ui.rf_set_btn.setEnabled(connected and not running and not self.state.sweep_is_running)
        self.ui.rf_freq_spinbox.setEnabled(connected and not running and not self.state.sweep_is_running)

    def _is_busy(self):
        """Return True if any acquisition is in progress."""
        return self.state.sweep_is_running or self.state.mag_is_running

    # ======================================================================
    # Camera mode
    # ======================================================================

    @Slot(str)
    def _on_camera_mode_changed(self, mode_str):
        """Respond to ODMR-level camera mode changes (e.g., ACQUIRING)."""
        mode = CameraMode(mode_str) if not isinstance(mode_str, CameraMode) else mode_str
        if mode == CameraMode.ACQUIRING:
            # Best-effort: disable start streaming button if available
            widget = self._camera_widget
            if hasattr(widget, 'start_button'):
                widget.start_button.setEnabled(False)

    @Slot(bool)
    def _on_camera_streaming_changed(self, is_streaming):
        """Keep ODMR camera mode in sync with camera streaming state."""
        if is_streaming:
            self.state.odmr_camera_mode = CameraMode.STREAMING
        else:
            # Only revert to IDLE; do not override ACQUIRING
            if self.state.odmr_camera_mode == CameraMode.STREAMING:
                self.state.odmr_camera_mode = CameraMode.IDLE

    def _stop_streaming_if_needed(self):
        """
        Stop camera streaming if it is currently active.

        Returns
        -------
        bool
            True if streaming was already stopped (acquisition can proceed),
            False if streaming was running and a stop was requested (caller
            should wait for the stream to finish).
        """
        camera_state = self.state.camera_state
        if camera_state is None:
            return True
        if getattr(camera_state, 'camera_is_streaming', False):
            widget = self._camera_widget
            if hasattr(widget, 'on_stop_streaming'):
                widget.on_stop_streaming()
            return False
        return True

    # ======================================================================
    # Save bar
    # ======================================================================

    def _connect_save_bar(self):
        """Wire save bar widgets to state."""
        ui = self.ui

        ui.save_browse_btn.clicked.connect(self._on_browse_save_path)
        ui.save_all_btn.clicked.connect(self._on_save_all)

        # Text edits → state
        ui.save_base_path_edit.textChanged.connect(
            lambda t: setattr(self.state, 'save_base_path', t)
        )
        ui.save_subfolder_edit.textChanged.connect(
            lambda t: setattr(self.state, 'save_subfolder', t)
        )

        # Checkbox → state
        ui.save_timestamp_chk.toggled.connect(
            lambda v: setattr(self.state, 'save_timestamp_enabled', v)
        )

    @Slot()
    def _on_browse_save_path(self):
        """Open directory chooser and update save path."""
        current = self.state.save_base_path or ""
        directory = QFileDialog.getExistingDirectory(
            self, "Select Base Save Directory", current
        )
        if directory:
            self.state.save_base_path = directory
            self.ui.save_base_path_edit.setText(directory)

    @Slot()
    def _on_save_all(self):
        """Placeholder: Save All triggered."""
        self.statusBar().showMessage("Save All triggered")

    # ======================================================================
    # File menu
    # ======================================================================

    def _connect_file_menu(self):
        """Wire File menu actions."""
        ui = self.ui
        ui.action_save_config.triggered.connect(self._save_config)
        ui.action_save_config_as.triggered.connect(self._save_config_as)
        ui.action_load_config.triggered.connect(self._load_config_dialog)
        ui.action_reset_defaults.triggered.connect(self._reset_defaults)

    def _save_config(self, path=None):
        """Save current state configuration to CONFIG_FILE (or given path)."""
        target = Path(path) if path else CONFIG_FILE
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, 'w') as fh:
                json.dump(self.state.get_config(), fh, indent=2)
            self.statusBar().showMessage(f"Config saved: {target}")
        except Exception as exc:
            QMessageBox.warning(self, "Save Config Error", str(exc))

    def _save_config_as(self):
        """Open save dialog and save config to chosen file."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Config As",
            str(CONFIG_FILE),
            "JSON files (*.json);;All files (*)"
        )
        if path:
            self._save_config(path=path)

    def _load_config_dialog(self):
        """Open load dialog and load config from chosen file."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Config",
            str(CONFIG_FILE.parent),
            "JSON files (*.json);;All files (*)"
        )
        if path:
            self._load_config(path=path)

    def _load_config(self, path=None):
        """Load config from path or from CONFIG_FILE if it exists.

        Parameters
        ----------
        path : str or Path, optional
            Path to JSON config file.  Defaults to CONFIG_FILE.
        """
        target = Path(path) if path else CONFIG_FILE
        if not target.exists():
            return
        try:
            with open(target, 'r') as fh:
                config = json.load(fh)
            self.state.load_config(config)
            self.statusBar().showMessage(f"Config loaded: {target}")
        except Exception as exc:
            QMessageBox.warning(self, "Load Config Error", str(exc))

    def _reset_defaults(self):
        """Confirm and reset all configurable state to defaults."""
        reply = QMessageBox.question(
            self,
            "Reset to Defaults",
            "Reset all settings to factory defaults?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.state.load_config({})
            self._sync_ui_from_state()
            self.statusBar().showMessage("Settings reset to defaults.")

    # ======================================================================
    # State ↔ UI synchronisation
    # ======================================================================

    def _connect_state_to_ui(self):
        """Phase 4: connect remaining state signals to tab UI (placeholder)."""
        pass  # Filled in by sweep / magnetometry / analysis tab handlers

    def _sync_ui_from_state(self):
        """Push current state values into save bar and RF panel widgets."""
        ui = self.ui

        # Save bar
        ui.save_base_path_edit.setText(self.state.save_base_path)
        ui.save_subfolder_edit.setText(self.state.save_subfolder)
        ui.save_timestamp_chk.setChecked(self.state.save_timestamp_enabled)

        # RF panel
        ui.rf_freq_spinbox.setValue(self.state.rf_current_freq_ghz or 2.870)

    # ======================================================================
    # Close event
    # ======================================================================

    def closeEvent(self, event):
        """Clean up all workers and connections on close."""
        # Stop SG384 worker
        if self.sg384_worker is not None and self.sg384_worker.isRunning():
            self.sg384_worker.stop()
            self.sg384_worker.wait(3000)
            self.sg384_worker = None

        # Close SG384 controller
        if self.state.sg384_controller is not None:
            try:
                self.state.sg384_controller.close_connection()
            except Exception:
                pass
            self.state.sg384_controller = None

        # Clean up camera widget
        if hasattr(self, '_camera_widget'):
            self._camera_widget.cleanup()

        # Persist config
        self._save_config()

        event.accept()
