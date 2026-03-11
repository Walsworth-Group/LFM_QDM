"""
SettingsTabHandler -- Wires the Settings tab to LFMAppState.

Provides controls for camera serial, default save paths, default pyolaf
parameters, GPU info, and display defaults.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QDoubleSpinBox, QSpinBox,
    QComboBox, QCheckBox, QFileDialog,
)
from PySide6.QtCore import Slot

from state.lfm_state import LFMAppState


class SettingsTabHandler:
    """
    Handles the Settings tab: camera serial, save paths, default parameters,
    and display preferences.

    Parameters
    ----------
    tab_widget : QWidget
        The bare QWidget placeholder from the main tab widget.
    state : LFMAppState
        Central application state.
    """

    def __init__(self, tab_widget: QWidget, state: LFMAppState):
        self.state = state
        self._build_ui(tab_widget)
        self._connect_signals()
        self._sync_from_state()

    def _build_ui(self, parent: QWidget):
        """Build the settings tab UI."""
        layout = QVBoxLayout(parent)

        # Camera group
        cam_group = QGroupBox("Camera")
        cam_grid = QGridLayout(cam_group)
        cam_grid.addWidget(QLabel("Basler serial number:"), 0, 0)
        self._serial_edit = QLineEdit()
        cam_grid.addWidget(self._serial_edit, 0, 1)
        layout.addWidget(cam_group)

        # Save settings group
        save_group = QGroupBox("Data Saving")
        save_grid = QGridLayout(save_group)

        save_grid.addWidget(QLabel("Base path:"), 0, 0)
        self._save_path_edit = QLineEdit()
        save_grid.addWidget(self._save_path_edit, 0, 1)
        self._btn_browse_save = QPushButton("Browse...")
        save_grid.addWidget(self._btn_browse_save, 0, 2)

        save_grid.addWidget(QLabel("Subfolder:"), 1, 0)
        self._subfolder_edit = QLineEdit()
        save_grid.addWidget(self._subfolder_edit, 1, 1)

        self._timestamp_check = QCheckBox("Append timestamp to filenames")
        save_grid.addWidget(self._timestamp_check, 2, 0, 1, 3)

        layout.addWidget(save_group)

        # Display group
        display_group = QGroupBox("Display Defaults")
        display_grid = QGridLayout(display_group)

        display_grid.addWidget(QLabel("Default colormap:"), 0, 0)
        self._cmap_combo = QComboBox()
        self._cmap_combo.addItems(["viridis", "gray", "hot", "plasma",
                                    "inferno", "magma"])
        display_grid.addWidget(self._cmap_combo, 0, 1)

        self._auto_levels_check = QCheckBox("Auto levels by default")
        display_grid.addWidget(self._auto_levels_check, 1, 0, 1, 2)

        layout.addWidget(display_group)

        # GPU info group
        gpu_group = QGroupBox("GPU Acceleration")
        gpu_layout = QVBoxLayout(gpu_group)
        try:
            import cupy
            gpu_info = (
                f"CuPy available (version {cupy.__version__})\n"
                f"Device: {cupy.cuda.Device().attributes}")
            pool = cupy.get_default_memory_pool()
            gpu_info += f"\nMemory pool limit: {pool.get_limit() / 2**30:.1f} GB"
        except ImportError:
            gpu_info = ("CuPy not available. Reconstruction will use CPU "
                        "(NumPy/SciPy). Install cupy for GPU acceleration.")
        except Exception as exc:
            gpu_info = f"CuPy import error: {exc}"

        self._gpu_label = QLabel(gpu_info)
        self._gpu_label.setWordWrap(True)
        gpu_layout.addWidget(self._gpu_label)
        layout.addWidget(gpu_group)

        layout.addStretch()

    def _connect_signals(self):
        """Wire UI widgets to state."""
        self._serial_edit.editingFinished.connect(
            lambda: setattr(self.state, 'lfm_camera_serial',
                            self._serial_edit.text()))
        self._save_path_edit.editingFinished.connect(
            lambda: setattr(self.state, 'save_base_path',
                            self._save_path_edit.text()))
        self._subfolder_edit.editingFinished.connect(
            lambda: setattr(self.state, 'save_subfolder',
                            self._subfolder_edit.text()))
        self._timestamp_check.toggled.connect(
            lambda v: setattr(self.state, 'save_timestamp_enabled', v))
        self._cmap_combo.currentTextChanged.connect(
            lambda v: setattr(self.state, 'display_colormap', v))
        self._auto_levels_check.toggled.connect(
            lambda v: setattr(self.state, 'display_auto_levels', v))
        self._btn_browse_save.clicked.connect(self._on_browse_save)

    def _sync_from_state(self):
        """Push current state values into UI widgets."""
        self._serial_edit.setText(self.state.lfm_camera_serial)
        self._save_path_edit.setText(self.state.save_base_path)
        self._subfolder_edit.setText(self.state.save_subfolder)
        self._timestamp_check.setChecked(self.state.save_timestamp_enabled)
        idx = self._cmap_combo.findText(self.state.display_colormap)
        if idx >= 0:
            self._cmap_combo.setCurrentIndex(idx)
        self._auto_levels_check.setChecked(self.state.display_auto_levels)

    @Slot()
    def _on_browse_save(self):
        path = QFileDialog.getExistingDirectory(
            None, "Select Save Directory", self.state.save_base_path)
        if path:
            self._save_path_edit.setText(path)
            self.state.save_base_path = path
