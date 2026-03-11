"""
VolumeSlicerWidget -- Single-panel image display for volume slices with
adjustable colormap and mouse-hover pixel info.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt


# Pre-built colormaps using pyqtgraph's lookup tables
_COLORMAPS = {
    "viridis": "viridis",
    "gray": "grey",
    "hot": "hot",
    "plasma": "plasma",
    "inferno": "inferno",
    "magma": "magma",
}


class VolumeSlicerWidget(QWidget):
    """
    Single-panel image display for volume depth slices.

    Features:
    - pyqtgraph ImageItem with configurable colormap
    - Mouse hover shows pixel coordinates and value
    - Auto-levels support

    Parameters
    ----------
    parent : QWidget, optional
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_data = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._graphics_widget = pg.GraphicsLayoutWidget()
        self._view_box = self._graphics_widget.addViewBox()
        self._view_box.setAspectLocked(True)

        self._image_item = pg.ImageItem()
        self._view_box.addItem(self._image_item)

        # Color bar
        self._colorbar = pg.ColorBarItem(
            interactive=True,
            orientation='right',
            colorMap='viridis',
        )
        self._colorbar.setImageItem(self._image_item,
                                     insert_in=self._graphics_widget.ci)

        layout.addWidget(self._graphics_widget, stretch=1)

        # Status bar for hover info
        self._status_label = QLabel("")
        self._status_label.setMaximumHeight(20)
        layout.addWidget(self._status_label)

        # Mouse tracking
        self._image_item.hoverEvent = self._on_hover

    def set_slice(self, data_2d: np.ndarray, auto_levels: bool = True):
        """
        Display a 2D slice.

        Parameters
        ----------
        data_2d : np.ndarray
            2D array (height, width).
        auto_levels : bool
            Whether to auto-scale display levels.
        """
        self._current_data = data_2d
        self._image_item.setImage(data_2d.T.astype(float),
                                   autoLevels=auto_levels)

    def set_colormap(self, cmap_name: str):
        """
        Switch colormap.

        Parameters
        ----------
        cmap_name : str
            One of: viridis, gray, hot, plasma, inferno, magma.
        """
        pg_name = _COLORMAPS.get(cmap_name, cmap_name)
        try:
            cmap = pg.colormap.get(pg_name)
            self._image_item.setColorMap(cmap)
            self._colorbar.setColorMap(cmap)
        except Exception:
            pass  # Fall back to current colormap

    def auto_range(self):
        """Reset levels to data min/max."""
        if self._current_data is not None:
            vmin = float(np.nanmin(self._current_data))
            vmax = float(np.nanmax(self._current_data))
            self._image_item.setLevels([vmin, vmax])

    def _on_hover(self, event):
        """Show pixel coordinates and value on hover."""
        if event.isExit():
            self._status_label.setText("")
            return

        pos = event.pos()
        # ImageItem displays data.T, so swap x/y for original coordinates
        ix = int(pos.x())
        iy = int(pos.y())

        if self._current_data is not None:
            h, w = self._current_data.shape
            # pos is in transposed coordinates
            if 0 <= iy < h and 0 <= ix < w:
                val = self._current_data[iy, ix]
                self._status_label.setText(
                    f"X: {ix}  Y: {iy}  Value: {val:.4g}")
            else:
                self._status_label.setText(f"X: {ix}  Y: {iy}")
        else:
            self._status_label.setText(f"X: {ix}  Y: {iy}")
