# ODMR App — Phase 3: UI Shell (Qt Designer Files + Main Window)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create all `.ui` files for the main window and each tab, generate the Python bindings, wire the main window skeleton (File menu, RF panel, persistent save bar, tab widget), and connect the Camera tab and RF control to their workers.

**Architecture:** Each tab is a separate `.ui` file compiled with `pyside6-uic`. The main window Python file (`odmr_main_window.py`) owns all callbacks. The generated `ui_*.py` files are never edited by hand.

**Tech Stack:** PySide6, pyside6-uic, pyqtgraph, existing workers from Phase 1, CameraTabWidget from Phase 2.

**Prerequisites:** Phases 1 and 2 complete.

---

## Task 9: Create Qt Designer `.ui` Files

**Files to create (all in `GUI/odmr_app/ui/`):**
- `odmr_app_main.ui` — QMainWindow shell: menu bar, RF panel, QTabWidget, save bar
- `camera_tab.ui` — placeholder (CameraTabWidget injected at runtime)
- `odmr_sweep_tab.ui` — sweep controls + spectrum area + inflection summary
- `magnetometry_tab.ui` — inflection table area + measurement controls + preview area
- `analysis_tab.ui` — 3-panel display area + reanalysis controls + stats
- `sensitivity_tab.ui` — sensitivity map + Allan plot + controls
- `settings_tab.ui` — instrument settings + performance section

**Step 1: Create `odmr_app_main.ui`**

This is the top-level shell. The QTabWidget is the central widget. The RF panel and save bar are docked above/below it as QGroupBoxes inside a QVBoxLayout.

Create `GUI/odmr_app/ui/odmr_app_main.ui`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<ui version="4.0">
 <class>ODMRMainWindow</class>
 <widget class="QMainWindow" name="ODMRMainWindow">
  <property name="windowTitle"><string>CW ODMR Magnetometry</string></property>
  <property name="geometry"><rect><x>0</x><y>0</y><width>1600</width><height>1000</height></rect></property>
  <widget class="QWidget" name="centralwidget">
   <layout class="QVBoxLayout" name="main_vbox">
    <property name="spacing"><number>4</number></property>
    <property name="contentsMargins"><number>4</number><number>4</number><number>4</number><number>4</number></property>

    <!-- RF Control Panel -->
    <item>
     <widget class="QGroupBox" name="rf_group">
      <property name="title"><string>MW Generator (SRS SG384)</string></property>
      <property name="maximumHeight"><number>80</number></property>
      <layout class="QHBoxLayout" name="rf_hbox">
       <item><widget class="QLabel" name="rf_status_label"><property name="text"><string>● Disconnected</string></property></widget></item>
       <item><widget class="QLabel" name="rf_freq_label"><property name="text"><string>Freq: — GHz</string></property></widget></item>
       <item><widget class="QDoubleSpinBox" name="rf_freq_spinbox">
        <property name="decimals"><number>6</number></property>
        <property name="minimum"><double>0.0</double></property>
        <property name="maximum"><double>8.0</double></property>
        <property name="value"><double>2.87</double></property>
        <property name="suffix"><string> GHz</string></property>
       </widget></item>
       <item><widget class="QPushButton" name="rf_set_btn"><property name="text"><string>Set Freq</string></property></widget></item>
       <item><widget class="QLabel" name="rf_amp_label"><property name="text"><string>Amp: — dBm</string></property></widget></item>
       <item><widget class="QPushButton" name="rf_connect_btn"><property name="text"><string>Connect RF</string></property></widget></item>
       <item><spacer><property name="orientation"><enum>Qt::Horizontal</enum></property></spacer></item>
      </layout>
     </widget>
    </item>

    <!-- Tab Widget -->
    <item>
     <widget class="QTabWidget" name="tab_widget">
      <widget class="QWidget" name="camera_tab"><attribute name="title"><string>Camera</string></attribute></widget>
      <widget class="QWidget" name="sweep_tab"><attribute name="title"><string>ODMR Sweep</string></attribute></widget>
      <widget class="QWidget" name="magnetometry_tab"><attribute name="title"><string>Magnetometry</string></attribute></widget>
      <widget class="QWidget" name="analysis_tab"><attribute name="title"><string>Analysis</string></attribute></widget>
      <widget class="QWidget" name="sensitivity_tab"><attribute name="title"><string>Sensitivity</string></attribute></widget>
      <widget class="QWidget" name="settings_tab"><attribute name="title"><string>Settings</string></attribute></widget>
     </widget>
    </item>

    <!-- Persistent Save Bar -->
    <item>
     <widget class="QGroupBox" name="save_bar_group">
      <property name="title"><string>Save</string></property>
      <property name="maximumHeight"><number>70</number></property>
      <layout class="QHBoxLayout" name="save_hbox">
       <item><widget class="QLabel"><property name="text"><string>Base path:</string></property></widget></item>
       <item><widget class="QLineEdit" name="save_base_path_edit"/></item>
       <item><widget class="QPushButton" name="save_browse_btn"><property name="text"><string>Browse</string></property></widget></item>
       <item><widget class="QLabel"><property name="text"><string>Subfolder:</string></property></widget></item>
       <item><widget class="QLineEdit" name="save_subfolder_edit"/></item>
       <item><widget class="QCheckBox" name="save_timestamp_chk"><property name="text"><string>Timestamp</string></property><property name="checked"><bool>true</bool></property></widget></item>
       <item><widget class="QPushButton" name="save_all_btn"><property name="text"><string>Save All Plots &amp; Data</string></property></widget></item>
      </layout>
     </widget>
    </item>

   </layout>
  </widget>

  <!-- Status bar -->
  <widget class="QStatusBar" name="statusbar"/>

  <!-- Menu bar -->
  <widget class="QMenuBar" name="menubar">
   <widget class="QMenu" name="menu_file"><property name="title"><string>File</string></property>
    <addaction name="action_save_config"/>
    <addaction name="action_save_config_as"/>
    <addaction name="action_load_config"/>
    <addaction name="separator"/>
    <addaction name="action_reset_defaults"/>
   </widget>
  </widget>
  <action name="action_save_config"><property name="text"><string>Save Config</string></property><property name="shortcut"><string>Ctrl+S</string></property></action>
  <action name="action_save_config_as"><property name="text"><string>Save Config As…</string></property></action>
  <action name="action_load_config"><property name="text"><string>Load Config…</string></property></action>
  <action name="action_reset_defaults"><property name="text"><string>Reset to Defaults</string></property></action>
 </widget>
</ui>
```

**Step 2: Create `odmr_sweep_tab.ui`**

Key widget names (used in Python callbacks):
- `sweep_freq1_start`, `sweep_freq1_end`, `sweep_freq1_steps` — QDoubleSpinBox / QSpinBox
- `sweep_freq2_start`, `sweep_freq2_end`, `sweep_freq2_steps`
- `sweep_ref_freq`, `sweep_num_sweeps`, `sweep_n_lorentz`
- `sweep_start_btn`, `sweep_stop_btn`
- `sweep_progress_bar`, `sweep_time_label`
- `sweep_plot_widget` — QWidget placeholder (pyqtgraph inserted at runtime)
- `sweep_inflection_table` — QTableWidget (8 rows, read-only summary)
- `sweep_send_to_mag_btn`
- `sweep_prefix_edit`, `sweep_save_npz_btn`, `sweep_save_png_btn`

Create `GUI/odmr_app/ui/odmr_sweep_tab.ui` as a QWidget with a QSplitter
(left: controls ~30%, right: plot + inflection table ~70%). Use QGroupBoxes to
organize control sections. Implement in Qt Designer or write XML directly using
the widget names above.

**Step 3: Create `magnetometry_tab.ui`**

Key widget names:
- `mag_preset_combo`, `mag_preset_load_btn`, `mag_preset_save_btn`, `mag_preset_delete_btn`
- `mag_points_load_btn`, `mag_points_save_btn`
- `mag_inflection_table_placeholder` — QWidget (InflectionTableWidget inserted at runtime)
- `mag_ref_freq_spin`, `mag_bin_x_spin`, `mag_bin_y_spin`
- `mag_num_samples_spin`, `mag_live_interval_spin`
- `mag_start_btn`, `mag_stop_btn`
- `mag_progress_bar`, `mag_time_label`
- `mag_preview_widget` — QWidget placeholder (pyqtgraph ImageView inserted)
- `mag_prefix_edit`, `mag_save_npz_btn`, `mag_save_png_btn`

**Step 4: Create `analysis_tab.ui`**

Key widget names:
- `analysis_display_placeholder` — QWidget (FieldMapDisplayWidget inserted at runtime)
- `analysis_denoise_combo`, `analysis_sigma_spin`, `analysis_outlier_spin`
- `analysis_reference_combo`
- `analysis_reanalyze_btn`
- `analysis_stats_label`
- `analysis_prefix_edit`, `analysis_save_npz_btn`, `analysis_save_png_btn`

**Step 5: Create `sensitivity_tab.ui`**

Key widget names:
- `sensitivity_map_widget` — QWidget placeholder
- `sensitivity_allan_widget` — QWidget placeholder
- `sensitivity_time_override_spin`, `sensitivity_slope_override_spin`
- `sensitivity_run_btn`, `sensitivity_allan_btn`
- `sensitivity_stats_label`
- `sensitivity_prefix_edit`, `sensitivity_save_npz_btn`, `sensitivity_save_png_btn`

**Step 6: Create `settings_tab.ui`**

Key widget names:
- `settings_sg384_address_edit`, `settings_camera_serial_edit`
- `settings_sg384_amplitude_spin`
- `settings_perf_group` — QGroupBox (collapsible via checkbox)
- `perf_rf_poll_spin`, `perf_settling_spin`, `perf_flush_frames_spin`
- `perf_n_frames_spin`, `perf_loop_sleep_spin`
- `perf_emit_every_spin`, `perf_live_avg_spin`, `perf_autosave_spin`
- `settings_reset_btn`

**Step 7: Generate Python bindings**

Run from `GUI/odmr_app/`:
```bash
for f in ui/*.ui; do
    base=$(basename "$f" .ui)
    pyside6-uic "$f" -o "ui/ui_${base}.py"
    echo "Generated ui/ui_${base}.py"
done
```

Verify all `ui_*.py` files were created:
```bash
ls ui/ui_*.py
```

**Step 8: Commit**
```bash
git add GUI/odmr_app/ui/
git commit -m "feat(odmr-app): add Qt Designer .ui files and generated ui_*.py bindings"
```

---

## Task 10: Create ODMRMainWindow Skeleton

**Files:**
- Create: `GUI/odmr_app/odmr_main_window.py`
- Create: `GUI/odmr_app/odmr_app.py`

**Step 1: Implement `odmr_main_window.py`**

This wires the main window UI to state and workers. Tab-specific logic is added in Phase 4. Here we build the skeleton: load UI, set up File menu, wire the RF panel, wire the save bar, and embed CameraTabWidget.

```python
"""
ODMRMainWindow — Main application window for CW ODMR magnetometry.

Wires ODMRAppState to all tabs and persistent panels.
Tab-specific logic is split into mixin classes loaded at bottom of file.
"""

import sys
import json
from pathlib import Path
from datetime import datetime

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QFileDialog,
    QMessageBox, QApplication
)
from PySide6.QtCore import Qt, Slot, QTimer

# Add project root and GUI root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

# Generated UI
from ui.ui_odmr_app_main import Ui_ODMRMainWindow

# State and workers
from state.odmr_state import ODMRAppState, CameraMode
from workers.sg384_worker import SG384Worker

# Widgets
from camera_app import CameraTabWidget   # from GUI/ root

# Project imports
import qdm_srs

CONFIG_FILE = Path(__file__).parent / "config" / "odmr_app_config.json"


class ODMRMainWindow(QMainWindow):
    """
    Main ODMR application window.

    Accepts an optional odmr_state and shared_state to integrate with
    launch_all_apps.py. If not provided, creates its own state (standalone mode).
    """

    def __init__(self, odmr_state: ODMRAppState = None,
                 shared_state=None, parent=None):
        super().__init__(parent)

        # State
        self.state = odmr_state if odmr_state is not None else ODMRAppState(
            shared_state=shared_state)

        # Workers
        self.sg384_worker = None

        # Setup UI
        self.ui = Ui_ODMRMainWindow()
        self.ui.setupUi(self)

        # Embed Camera tab
        self._embed_camera_tab()

        # Load config
        self._load_config()

        # Connect signals
        self._connect_rf_panel()
        self._connect_save_bar()
        self._connect_file_menu()
        self._connect_state_to_ui()

        # Apply state to UI
        self._sync_ui_from_state()

    # ------------------------------------------------------------------
    # Camera tab embedding
    # ------------------------------------------------------------------

    def _embed_camera_tab(self):
        """Replace empty camera_tab placeholder with CameraTabWidget."""
        from state.camera_state import CameraState
        camera_state = CameraState()
        camera_state.camera_serial_number = self.state.odmr_camera_serial

        self._camera_widget = CameraTabWidget(state=camera_state, parent=self)
        self.state.camera_state = camera_state

        # Insert into the camera_tab QWidget
        tab = self.ui.camera_tab
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._camera_widget)

        # Wire camera mode mutual exclusion
        self.state.camera_mode_changed.connect(self._on_camera_mode_changed)
        camera_state.camera_streaming_changed.connect(self._on_camera_streaming_changed)

    # ------------------------------------------------------------------
    # RF Panel
    # ------------------------------------------------------------------

    def _connect_rf_panel(self):
        self.ui.rf_connect_btn.clicked.connect(self._on_rf_connect_clicked)
        self.ui.rf_set_btn.clicked.connect(self._on_rf_set_freq)
        self.state.rf_connection_changed.connect(self._on_rf_connection_changed)
        self.state.rf_frequency_changed.connect(self._on_rf_frequency_changed)
        self.state.sweep_running_changed.connect(self._on_sweep_running_changed)
        self.state.mag_running_changed.connect(self._on_mag_running_changed)

    @Slot()
    def _on_rf_connect_clicked(self):
        if self.sg384_worker and self.sg384_worker.isRunning():
            self._disconnect_rf()
            return
        self._connect_rf()

    def _connect_rf(self):
        try:
            ctrl = qdm_srs.SG384Controller(self.state.rf_address)
            ctrl.open_connection()
            self.state.sg384_controller = ctrl
            self.state.rf_is_connected = True

            self.sg384_worker = SG384Worker(self.state)
            self.sg384_worker.connected.connect(self._on_sg384_connected)
            self.sg384_worker.connection_failed.connect(self._on_sg384_failed)
            self.sg384_worker.frequency_polled.connect(
                lambda f: setattr(self.state, 'rf_current_freq_ghz', f))
            self.sg384_worker.start()
        except Exception as e:
            QMessageBox.critical(self, "RF Connection Error", str(e))

    def _disconnect_rf(self):
        if self.sg384_worker:
            self.sg384_worker.stop()
            self.sg384_worker.wait(3000)
            self.sg384_worker = None
        if self.state.sg384_controller:
            try:
                self.state.sg384_controller.close_connection()
            except Exception:
                pass
            self.state.sg384_controller = None
        self.state.rf_is_connected = False

    @Slot(dict)
    def _on_sg384_connected(self, info):
        self.ui.rf_connect_btn.setText("Disconnect RF")
        self.statusBar().showMessage(f"RF connected: {info.get('address')}", 3000)

    @Slot(str)
    def _on_sg384_failed(self, msg):
        QMessageBox.critical(self, "RF Connection Failed", msg)
        self.state.rf_is_connected = False

    @Slot(bool)
    def _on_rf_connection_changed(self, connected):
        color = "green" if connected else "red"
        symbol = "●"
        self.ui.rf_status_label.setText(
            f'<span style="color:{color}">{symbol}</span> '
            f'{"Connected" if connected else "Disconnected"}')
        self.ui.rf_set_btn.setEnabled(connected and not self._is_busy())
        self.ui.rf_connect_btn.setText(
            "Disconnect RF" if connected else "Connect RF")

    @Slot(float)
    def _on_rf_frequency_changed(self, freq_ghz):
        self.ui.rf_freq_label.setText(f"Freq: {freq_ghz:.6f} GHz")

    @Slot()
    def _on_rf_set_freq(self):
        if self.sg384_worker and self.sg384_worker.isRunning():
            freq = self.ui.rf_freq_spinbox.value()
            self.sg384_worker.queue_command('set_frequency', freq)

    @Slot(bool)
    def _on_sweep_running_changed(self, running):
        self.ui.rf_set_btn.setEnabled(not running and not self.state.mag_is_running
                                      and self.state.rf_is_connected)
        self.ui.rf_freq_spinbox.setEnabled(not running)

    @Slot(bool)
    def _on_mag_running_changed(self, running):
        self.ui.rf_set_btn.setEnabled(not running and not self.state.sweep_is_running
                                      and self.state.rf_is_connected)

    def _is_busy(self):
        return self.state.sweep_is_running or self.state.mag_is_running

    # ------------------------------------------------------------------
    # Camera mode mutual exclusion
    # ------------------------------------------------------------------

    @Slot(str)
    def _on_camera_mode_changed(self, mode):
        is_acquiring = (mode == CameraMode.ACQUIRING)
        # Disable streaming button while acquiring
        if hasattr(self._camera_widget, 'connect_btn'):
            self._camera_widget.connect_btn.setEnabled(not is_acquiring)

    @Slot(bool)
    def _on_camera_streaming_changed(self, is_streaming):
        if is_streaming:
            self.state.odmr_camera_mode = CameraMode.STREAMING
        else:
            if self.state.odmr_camera_mode == CameraMode.STREAMING:
                self.state.odmr_camera_mode = CameraMode.IDLE

    def _stop_streaming_if_needed(self) -> bool:
        """
        Stop camera streaming before starting a sweep/measurement.
        Returns True when safe to proceed (streaming stopped or was not active).
        Caller should wait for camera_mode_changed(IDLE) before proceeding if
        this returns False (streaming was active and stop was requested).
        """
        if self.state.odmr_camera_mode == CameraMode.STREAMING:
            self.statusBar().showMessage("Stopping camera stream…", 2000)
            if hasattr(self._camera_widget, 'stop_streaming'):
                self._camera_widget.stop_streaming()
            return False  # caller should wait for streaming_changed signal
        return True

    # ------------------------------------------------------------------
    # Persistent save bar
    # ------------------------------------------------------------------

    def _connect_save_bar(self):
        self.ui.save_browse_btn.clicked.connect(self._on_browse_save_path)
        self.ui.save_all_btn.clicked.connect(self._on_save_all)
        self.ui.save_base_path_edit.textChanged.connect(
            lambda t: setattr(self.state, 'save_base_path', t))
        self.ui.save_subfolder_edit.textChanged.connect(
            lambda t: setattr(self.state, 'save_subfolder', t))
        self.ui.save_timestamp_chk.toggled.connect(
            lambda v: setattr(self.state, 'save_timestamp_enabled', v))

    @Slot()
    def _on_browse_save_path(self):
        path = QFileDialog.getExistingDirectory(self, "Select Save Directory")
        if path:
            self.state.save_base_path = path
            self.ui.save_base_path_edit.setText(path)

    @Slot()
    def _on_save_all(self):
        """Trigger save on each tab that has data."""
        # Phase 4 will connect each tab's save method here
        self.statusBar().showMessage("Save All triggered", 2000)

    # ------------------------------------------------------------------
    # File menu
    # ------------------------------------------------------------------

    def _connect_file_menu(self):
        self.ui.action_save_config.triggered.connect(self._save_config)
        self.ui.action_save_config_as.triggered.connect(self._save_config_as)
        self.ui.action_load_config.triggered.connect(self._load_config_dialog)
        self.ui.action_reset_defaults.triggered.connect(self._reset_defaults)

    @Slot()
    def _save_config(self):
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.state.get_config(), f, indent=2, default=str)
        self.statusBar().showMessage(f"Config saved to {CONFIG_FILE}", 3000)

    @Slot()
    def _save_config_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Config As", str(CONFIG_FILE.parent),
            "JSON Files (*.json)")
        if path:
            with open(path, 'w') as f:
                json.dump(self.state.get_config(), f, indent=2, default=str)

    @Slot()
    def _load_config_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Config", str(CONFIG_FILE.parent),
            "JSON Files (*.json)")
        if path:
            self._load_config(Path(path))

    def _load_config(self, path: Path = None):
        p = path or CONFIG_FILE
        if p.exists():
            try:
                with open(p) as f:
                    self.state.load_config(json.load(f))
            except Exception as e:
                self.statusBar().showMessage(f"Config load error: {e}", 5000)

    @Slot()
    def _reset_defaults(self):
        reply = QMessageBox.question(
            self, "Reset Defaults",
            "Reset all settings to defaults? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.state.load_config({})  # empty config → all defaults
            self._sync_ui_from_state()

    # ------------------------------------------------------------------
    # State → UI sync
    # ------------------------------------------------------------------

    def _connect_state_to_ui(self):
        """Connect state signals to UI elements (save bar, etc.)"""
        pass  # Tab-specific connections added in Phase 4 mixins

    def _sync_ui_from_state(self):
        """Push current state values into UI widgets (called after config load)."""
        s = self.state
        self.ui.save_base_path_edit.setText(s.save_base_path)
        self.ui.save_subfolder_edit.setText(s.save_subfolder)
        self.ui.save_timestamp_chk.setChecked(s.save_timestamp_enabled)
        self.ui.rf_freq_spinbox.setValue(s.rf_current_freq_ghz or 2.87)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        # Stop all workers
        if self.sg384_worker and self.sg384_worker.isRunning():
            self.sg384_worker.stop()
            self.sg384_worker.wait(3000)
        if self.state.sg384_controller:
            try:
                self.state.sg384_controller.close_connection()
            except Exception:
                pass
        # Camera cleanup
        self._camera_widget.cleanup()
        # Save config
        self._save_config()
        event.accept()
```

**Step 2: Implement `odmr_app.py` entry point**

Create `GUI/odmr_app/odmr_app.py`:
```python
"""
ODMR App Entry Point

Run standalone:   python odmr_app.py
Run via launcher: import and call main(shared_state=...)
"""

import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).parent.parent))  # GUI/ root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))  # project root

from odmr_main_window import ODMRMainWindow
from state.odmr_state import ODMRAppState


def main(shared_state=None):
    """
    Launch the ODMR app.

    Args:
        shared_state: Optional ExperimentState from launch_all_apps.py.
                      If None, app creates its own (standalone mode).
    Returns:
        ODMRMainWindow instance (for use by launcher).
    """
    odmr_state = ODMRAppState(shared_state=shared_state)
    window = ODMRMainWindow(odmr_state=odmr_state, shared_state=shared_state)
    window.setGeometry(100, 50, 1600, 1000)
    window.show()
    return window


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    win = main()
    sys.exit(app.exec())
```

**Step 3: Verify app launches**
```bash
cd GUI
python odmr_app/odmr_app.py
```
Expected: Main window opens with RF panel at top, tab widget with 6 tabs, save bar at bottom. Camera tab shows CameraTabWidget. File menu has Save/Load Config items. No errors in console.

**Step 4: Commit**
```bash
git add GUI/odmr_app/odmr_main_window.py GUI/odmr_app/odmr_app.py
git commit -m "feat(odmr-app): add ODMRMainWindow skeleton with RF panel, save bar, file menu"
```

---

## Task 11: Wire Settings Tab

**Files:**
- Create: `GUI/odmr_app/tabs/settings_tab.py` (tab logic mixin/handler)

The Settings tab logic reads/writes `perf_*` and instrument properties in state.
Create a helper class that the main window instantiates.

**Step 1: Implement `GUI/odmr_app/tabs/settings_tab.py`**

```python
"""Settings tab handler — wires settings_tab.ui widgets to ODMRAppState."""

import sys
from pathlib import Path
from PySide6.QtCore import Slot
from PySide6.QtWidgets import QWidget, QVBoxLayout

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

# Generated UI for settings tab
from ui.ui_odmr_settings_tab import Ui_settings_tab_content


class SettingsTabHandler:
    """
    Mixin/handler for the Settings tab.

    Instantiated by ODMRMainWindow. Wires the settings tab UI to state.
    Usage in ODMRMainWindow.__init__:
        self._settings_handler = SettingsTabHandler(self.ui.settings_tab, self.state)
    """

    def __init__(self, tab_widget: QWidget, state):
        self.state = state
        self.ui_settings = Ui_settings_tab_content()
        self.ui_settings.setupUi(tab_widget)
        self._connect_widgets()
        self._sync_from_state()

    def _connect_widgets(self):
        s = self.state
        ui = self.ui_settings

        # Instrument settings
        ui.settings_sg384_address_edit.textChanged.connect(
            lambda t: setattr(s, 'rf_address', t))
        ui.settings_camera_serial_edit.textChanged.connect(
            lambda t: setattr(s, 'odmr_camera_serial', t))
        ui.settings_sg384_amplitude_spin.valueChanged.connect(
            lambda v: setattr(s, 'rf_amplitude_dbm', v))

        # Performance spinboxes → state perf_* properties
        perf_bindings = [
            (ui.perf_rf_poll_spin,      'perf_rf_poll_interval_s'),
            (ui.perf_settling_spin,     'perf_mw_settling_time_s'),
            (ui.perf_flush_frames_spin, 'perf_camera_flush_frames'),
            (ui.perf_n_frames_spin,     'perf_n_frames_per_point'),
            (ui.perf_loop_sleep_spin,   'perf_worker_loop_sleep_s'),
            (ui.perf_emit_every_spin,   'perf_sweep_emit_every_n'),
            (ui.perf_live_avg_spin,     'perf_live_avg_update_interval_samples'),
            (ui.perf_autosave_spin,     'perf_autosave_interval_samples'),
        ]
        for widget, attr in perf_bindings:
            widget.valueChanged.connect(lambda v, a=attr: setattr(s, a, v))

        ui.settings_reset_btn.clicked.connect(self._on_reset)

    def _sync_from_state(self):
        s = self.state
        ui = self.ui_settings
        ui.settings_sg384_address_edit.setText(s.rf_address)
        ui.settings_camera_serial_edit.setText(s.odmr_camera_serial)
        ui.settings_sg384_amplitude_spin.setValue(s.rf_amplitude_dbm)
        ui.perf_rf_poll_spin.setValue(s.perf_rf_poll_interval_s)
        ui.perf_settling_spin.setValue(s.perf_mw_settling_time_s)
        ui.perf_flush_frames_spin.setValue(s.perf_camera_flush_frames)
        ui.perf_n_frames_spin.setValue(s.perf_n_frames_per_point)
        ui.perf_loop_sleep_spin.setValue(s.perf_worker_loop_sleep_s)
        ui.perf_emit_every_spin.setValue(s.perf_sweep_emit_every_n)
        ui.perf_live_avg_spin.setValue(s.perf_live_avg_update_interval_samples)
        ui.perf_autosave_spin.setValue(s.perf_autosave_interval_samples)

    @Slot()
    def _on_reset(self):
        # Reset perf_* to defaults by loading empty config
        default_state_temp = type(self.state)()
        for key in self.state._CONFIG_KEYS:
            if key.startswith('perf_'):
                setattr(self.state, key, getattr(default_state_temp, key))
        self._sync_from_state()
```

Create `GUI/odmr_app/tabs/__init__.py` (empty).

**Step 2: Instantiate in ODMRMainWindow**

In `odmr_main_window.py`, add to `__init__` after `_sync_ui_from_state()`:
```python
from tabs.settings_tab import SettingsTabHandler
self._settings_handler = SettingsTabHandler(self.ui.settings_tab, self.state)
```

**Step 3: Manual test**

Launch the app, open Settings tab. Change RF poll interval. Close and reopen — value should be persisted in config (File > Save Config on close).

**Step 4: Commit**
```bash
git add GUI/odmr_app/tabs/ GUI/odmr_app/odmr_main_window.py
git commit -m "feat(odmr-app): wire Settings tab to ODMRAppState perf_* properties"
```

---

## Phase 3 Complete

```bash
cd GUI
python odmr_app/odmr_app.py
```

Verify:
- [ ] App launches without errors
- [ ] RF panel shows ● Disconnected
- [ ] All 6 tabs visible
- [ ] Camera tab shows CameraTabWidget controls
- [ ] Settings tab shows all perf_* spinboxes
- [ ] File > Save Config writes `config/odmr_app_config.json`
- [ ] File > Load Config restores values
- [ ] Save bar Browse button opens directory dialog

```bash
git log --oneline -10
```

**Proceed to Phase 4:** `docs/plans/2026-02-20-odmr-app-plan-phase4.md`
— Tab logic for ODMR Sweep, Magnetometry, Analysis, Sensitivity; Save functionality; launch_all_apps.py integration.
