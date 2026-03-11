"""
VolumeViewerTabHandler -- Wires the Volume Viewer tab to LFMAppState.

Provides a depth-slice browser for 3D reconstructed volumes with
colormap selection, depth slider, and export controls.
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QSpinBox, QComboBox, QCheckBox, QFileDialog,
    QMessageBox, QGroupBox,
)
from PySide6.QtCore import Slot, Qt

from state.lfm_state import LFMAppState


class VolumeViewerTabHandler:
    """
    Handles the Volume Viewer tab: depth-slice browsing, colormap selection,
    and volume/slice export.

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

    def _build_ui(self, parent: QWidget):
        """Build the volume viewer tab UI."""
        layout = QVBoxLayout(parent)

        # Main image display
        from widgets.volume_slicer import VolumeSlicerWidget
        self._slicer = VolumeSlicerWidget()
        layout.addWidget(self._slicer, stretch=1)

        # Bottom controls
        controls = QHBoxLayout()

        # Depth slider
        controls.addWidget(QLabel("Depth:"))
        self._depth_slider = QSlider(Qt.Horizontal)
        self._depth_slider.setRange(0, 0)
        self._depth_slider.setValue(0)
        controls.addWidget(self._depth_slider, stretch=1)

        self._depth_spin = QSpinBox()
        self._depth_spin.setRange(0, 0)
        controls.addWidget(self._depth_spin)

        self._depth_label = QLabel("z = -- um")
        self._depth_label.setMinimumWidth(120)
        controls.addWidget(self._depth_label)

        # Colormap
        controls.addWidget(QLabel("Colormap:"))
        self._cmap_combo = QComboBox()
        self._cmap_combo.addItems(["viridis", "gray", "hot", "plasma",
                                    "inferno", "magma"])
        controls.addWidget(self._cmap_combo)

        # Auto levels
        self._auto_levels_check = QCheckBox("Auto levels")
        self._auto_levels_check.setChecked(True)
        controls.addWidget(self._auto_levels_check)

        layout.addLayout(controls)

        # Export buttons
        export_layout = QHBoxLayout()
        self._btn_export_slice = QPushButton("Export Current Slice...")
        self._btn_export_volume = QPushButton("Export Volume...")
        export_layout.addWidget(self._btn_export_slice)
        export_layout.addWidget(self._btn_export_volume)
        export_layout.addStretch()
        layout.addLayout(export_layout)

        # Info label
        self._info_label = QLabel("No volume loaded.")
        layout.addWidget(self._info_label)

    def _connect_signals(self):
        """Wire UI widgets to state."""
        # Depth controls
        self._depth_slider.valueChanged.connect(self._on_depth_slider_changed)
        self._depth_spin.valueChanged.connect(self._on_depth_spin_changed)

        # Colormap
        self._cmap_combo.currentTextChanged.connect(self._on_cmap_changed)

        # Auto levels
        self._auto_levels_check.toggled.connect(
            lambda v: setattr(self.state, 'display_auto_levels', v))

        # Export
        self._btn_export_slice.clicked.connect(self._on_export_slice)
        self._btn_export_volume.clicked.connect(self._on_export_volume)

        # State signals
        self.state.volume_loaded.connect(self._on_volume_loaded)
        self.state.current_depth_changed.connect(self._on_depth_changed)

    # ------------------------------------------------------------------
    # Volume loaded
    # ------------------------------------------------------------------

    @Slot(int, int, int)
    def _on_volume_loaded(self, ny: int, nx: int, n_depths: int):
        """Configure slider and display for new volume dimensions."""
        self._depth_slider.setRange(0, n_depths - 1)
        self._depth_spin.setRange(0, n_depths - 1)

        mid = n_depths // 2
        self._depth_slider.setValue(mid)
        self._depth_spin.setValue(mid)

        self._info_label.setText(
            f"Volume: {nx} x {ny} x {n_depths} "
            f"(W x H x Depth)")
        self._update_display(mid)

    # ------------------------------------------------------------------
    # Depth navigation
    # ------------------------------------------------------------------

    @Slot(int)
    def _on_depth_slider_changed(self, idx: int):
        self._depth_spin.blockSignals(True)
        self._depth_spin.setValue(idx)
        self._depth_spin.blockSignals(False)
        self.state.current_depth_index = idx
        self._update_display(idx)

    @Slot(int)
    def _on_depth_spin_changed(self, idx: int):
        self._depth_slider.blockSignals(True)
        self._depth_slider.setValue(idx)
        self._depth_slider.blockSignals(False)
        self.state.current_depth_index = idx
        self._update_display(idx)

    @Slot(int)
    def _on_depth_changed(self, idx: int):
        """Handle programmatic depth changes from state."""
        self._depth_slider.blockSignals(True)
        self._depth_spin.blockSignals(True)
        self._depth_slider.setValue(idx)
        self._depth_spin.setValue(idx)
        self._depth_slider.blockSignals(False)
        self._depth_spin.blockSignals(False)
        self._update_display(idx)

    def _update_display(self, idx: int):
        """Update the displayed slice."""
        vol = self.state.recon_volume
        if vol is None or idx < 0 or idx >= vol.shape[2]:
            return

        slice_2d = vol[:, :, idx]
        auto = self.state.display_auto_levels
        self._slicer.set_slice(slice_2d, auto_levels=auto)

        # Update depth label
        if self.state.resolution is not None:
            depths = self.state.resolution.get('depths', [])
            if idx < len(depths):
                self._depth_label.setText(f"z = {depths[idx]:.1f} um")
                return
        self._depth_label.setText(f"z = slice {idx}")

    # ------------------------------------------------------------------
    # Colormap
    # ------------------------------------------------------------------

    @Slot(str)
    def _on_cmap_changed(self, cmap_name: str):
        self.state.display_colormap = cmap_name
        self._slicer.set_colormap(cmap_name)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    @Slot()
    def _on_export_slice(self):
        """Export the current depth slice as TIFF."""
        vol = self.state.recon_volume
        if vol is None:
            QMessageBox.warning(None, "No Volume", "No volume to export.")
            return

        idx = self.state.current_depth_index
        slice_2d = vol[:, :, idx]

        path, _ = QFileDialog.getSaveFileName(
            None, "Export Slice",
            f"lfm_slice_z{idx}.tiff",
            "TIFF files (*.tiff *.tif);;NumPy files (*.npy)")
        if not path:
            return

        try:
            if path.endswith('.npy'):
                np.save(path, slice_2d)
            else:
                import tifffile
                tifffile.imwrite(path, slice_2d.astype(np.float32))
            self.state.status_message.emit(f"Slice exported to {path}")
        except Exception as exc:
            QMessageBox.warning(
                None, "Export Error", f"Could not export slice:\n{exc}")

    @Slot()
    def _on_export_volume(self):
        """Export the full reconstructed volume."""
        vol = self.state.recon_volume
        if vol is None:
            QMessageBox.warning(None, "No Volume", "No volume to export.")
            return

        path, _ = QFileDialog.getSaveFileName(
            None, "Export Volume",
            f"lfm_volume_{datetime.now().strftime('%Y%m%d_%H%M%S')}.npz",
            "NumPy files (*.npz);;TIFF files (*.tiff *.tif)")
        if not path:
            return

        try:
            if path.endswith(('.tiff', '.tif')):
                import tifffile
                # Save as multi-page TIFF (depth along first axis)
                vol_out = np.transpose(vol, (2, 0, 1)).astype(np.float32)
                tifffile.imwrite(path, vol_out, imagej=True)
            else:
                np.savez_compressed(path, volume=vol)
                if self.state.resolution is not None:
                    depths = self.state.resolution.get('depths', [])
                    np.savez_compressed(
                        path, volume=vol, depths=np.array(depths))

            self.state.status_message.emit(f"Volume exported to {path}")
        except Exception as exc:
            QMessageBox.warning(
                None, "Export Error", f"Could not export volume:\n{exc}")
