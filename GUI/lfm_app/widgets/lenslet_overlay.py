"""
LensletOverlayWidget -- Displays a white calibration image with detected
lenslet centers overlaid as scatter points.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QWidget, QVBoxLayout


class LensletOverlayWidget(QWidget):
    """
    Display a white image with lenslet center markers overlaid.

    Uses pyqtgraph ImageItem for the image and ScatterPlotItem for the
    detected lenslet centers.

    Parameters
    ----------
    parent : QWidget, optional
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._graphics_widget = pg.GraphicsLayoutWidget()
        self._view_box = self._graphics_widget.addViewBox()
        self._view_box.setAspectLocked(True)

        self._image_item = pg.ImageItem()
        self._view_box.addItem(self._image_item)

        self._scatter = pg.ScatterPlotItem(
            pen=pg.mkPen('r', width=1),
            brush=pg.mkBrush(255, 0, 0, 80),
            size=5,
        )
        self._view_box.addItem(self._scatter)

        layout.addWidget(self._graphics_widget)

    def set_white_image(self, img: np.ndarray):
        """
        Display the white calibration image.

        Parameters
        ----------
        img : np.ndarray
            2D array (height, width).
        """
        self._image_item.setImage(img.T.astype(float))

    def set_lenslet_centers(self, centers_px: np.ndarray):
        """
        Overlay lenslet centers on the image.

        Parameters
        ----------
        centers_px : np.ndarray
            Array of lenslet center positions in pixel coordinates.
            Shape can be (nV, nU, 2) or (N, 2).
        """
        if centers_px.ndim == 3:
            flat = centers_px.reshape(-1, 2)
        else:
            flat = centers_px
        self._scatter.setData(flat[:, 0], flat[:, 1])

    def clear(self):
        """Clear both image and overlay."""
        self._image_item.clear()
        self._scatter.clear()
