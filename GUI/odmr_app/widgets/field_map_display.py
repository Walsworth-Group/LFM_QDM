"""
FieldMapDisplayWidget — 3-panel magnetic field map display.

Panels: Raw (mean) | Denoised | Processed (Raw - Denoised)
All panels: RdBu_r colormap, pixel B-value on mouse hover.
Processed panel drives the shared colormap range (main result).
"""

import numpy as np
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel
from PySide6.QtCore import Qt
import pyqtgraph as pg


# RdBu_r colormap: blue=negative, white=zero, red=positive
def _make_rdbu_colormap():
    """Create a pyqtgraph ColorMap approximating matplotlib's RdBu_r."""
    colors = [
        (5,   48,  97,  255),   # dark blue
        (33,  102, 172, 255),
        (103, 169, 207, 255),
        (209, 229, 240, 255),
        (255, 255, 255, 255),   # white (zero)
        (253, 219, 199, 255),
        (239, 138, 98,  255),
        (178, 24,  43,  255),
        (103, 0,   31,  255),   # dark red
    ]
    pos = np.linspace(0, 1, len(colors))
    return pg.ColorMap(pos, colors)


class _FieldPanel(QWidget):
    """Single field map panel: ImageView + title + hover label."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(title_label)

        self._img_view = pg.ImageView(self)
        self._img_view.ui.roiBtn.hide()
        self._img_view.ui.menuBtn.hide()
        self._img_view.ui.histogram.hide()
        layout.addWidget(self._img_view, stretch=1)

        self._hover_label = QLabel("Hover for pixel value")
        self._hover_label.setAlignment(Qt.AlignCenter)
        self._hover_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(self._hover_label)

        self._data = None
        self._cmap = _make_rdbu_colormap()

        # Mouse hover
        self._img_view.scene.sigMouseMoved.connect(self._on_mouse_moved)

    def set_data(self, data: np.ndarray, vmin: float = None, vmax: float = None):
        """Display a 2D float array. vmin/vmax set the colormap range if provided."""
        self._data = data
        if data is None:
            self._img_view.clear()
            return
        levels = (vmin, vmax) if (vmin is not None and vmax is not None) else None
        self._img_view.setImage(
            data.T,          # pyqtgraph uses (x, y) = (col, row)
            autoLevels=(levels is None),
            levels=levels,
        )
        self._img_view.setColorMap(self._cmap)

    def clear(self):
        """Clear the display."""
        self._data = None
        self._img_view.clear()
        self._hover_label.setText("Hover for pixel value")

    def _on_mouse_moved(self, pos):
        if self._data is None:
            return
        try:
            scene_pos = self._img_view.getImageItem().mapFromScene(pos)
            col, row = int(scene_pos.x()), int(scene_pos.y())
            ny, nx = self._data.shape
            if 0 <= row < ny and 0 <= col < nx:
                val = self._data[row, col]
                self._hover_label.setText(f"x={col}, y={row},  B = {val:+.4f} G")
        except Exception:
            pass


class FieldMapDisplayWidget(QWidget):
    """
    Three-panel magnetic field map display for ODMR magnetometry results.

    Call update_from_result(result_dict) after analysis completes.

    Parameters
    ----------
    parent : QWidget, optional

    Expected result dict keys
    -------------------------
    field_map_gauss_raw : np.ndarray (ny, nx)
    field_map_gauss_denoised : np.ndarray (ny, nx)
    field_map_gauss_processed : np.ndarray (ny, nx)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._panel_raw  = _FieldPanel("Raw (mean)")
        self._panel_den  = _FieldPanel("Denoised")
        self._panel_proc = _FieldPanel("Processed (Raw \u2212 Denoised)")

        # Processed is the main result — give it more horizontal space
        layout.addWidget(self._panel_raw,  stretch=1)
        layout.addWidget(self._panel_den,  stretch=1)
        layout.addWidget(self._panel_proc, stretch=2)

        self._vmin = None
        self._vmax = None

    def update_from_result(self, result: dict):
        """
        Populate all three panels from an analysis result dict.

        Parameters
        ----------
        result : dict
            Must contain field_map_gauss_raw, field_map_gauss_denoised,
            field_map_gauss_processed (all 2D float arrays in Gauss).
        """
        raw       = result.get("field_map_gauss_raw")
        denoised  = result.get("field_map_gauss_denoised")
        processed = result.get("field_map_gauss_processed")

        # Colormap range driven by processed panel (symmetric around zero)
        if processed is not None:
            abs_max = max(abs(float(np.nanmin(processed))),
                          abs(float(np.nanmax(processed))))
            self._vmin, self._vmax = -abs_max, abs_max
        else:
            self._vmin, self._vmax = None, None

        self._panel_raw.set_data(raw)
        self._panel_den.set_data(denoised)
        self._panel_proc.set_data(processed, self._vmin, self._vmax)

    def clear(self):
        """Clear all three panels."""
        self._panel_raw.clear()
        self._panel_den.clear()
        self._panel_proc.clear()
        self._vmin = self._vmax = None

    def get_colormap_range(self):
        """
        Return the colormap range of the processed panel.

        Returns
        -------
        tuple of (vmin, vmax) floats, or (None, None) if no data.
        """
        return self._vmin, self._vmax
