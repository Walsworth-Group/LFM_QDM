"""
FieldMapDisplayWidget — 3-panel magnetic field map display.

Panels: Raw (mean) | Denoised | Processed (Raw - Denoised)
All panels: RdBu_r colormap, adjustable colorbar, pixel B-value on mouse hover.
"""

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QDoubleSpinBox, QPushButton,
    QSizePolicy,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QLinearGradient, QColor, QBrush, QPainter
import pyqtgraph as pg


# ---------------------------------------------------------------------------
# RdBu_r colormap
# ---------------------------------------------------------------------------

def _make_rdbu_colormap():
    """Create a pyqtgraph ColorMap approximating matplotlib's RdBu_r."""
    colors = [
        (5,   48,  97,  255),   # dark blue  (vmin)
        (33,  102, 172, 255),
        (103, 169, 207, 255),
        (209, 229, 240, 255),
        (255, 255, 255, 255),   # white (zero)
        (253, 219, 199, 255),
        (239, 138, 98,  255),
        (178, 24,  43,  255),
        (103, 0,   31,  255),   # dark red   (vmax)
    ]
    pos = np.linspace(0, 1, len(colors))
    return pg.ColorMap(pos, colors)


_RDBU_COLORS = [
    (5,   48,  97,  255),
    (33,  102, 172, 255),
    (103, 169, 207, 255),
    (209, 229, 240, 255),
    (255, 255, 255, 255),
    (253, 219, 199, 255),
    (239, 138, 98,  255),
    (178, 24,  43,  255),
    (103, 0,   31,  255),
]


# ---------------------------------------------------------------------------
# Gradient strip widget
# ---------------------------------------------------------------------------

class _GradientStrip(QWidget):
    """Thin vertical widget that paints the RdBu_r gradient (top=vmax, bottom=vmin)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(18)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        gradient = QLinearGradient(0, self.height(), 0, 0)  # bottom → top
        n = len(_RDBU_COLORS)
        for i, (r, g, b, a) in enumerate(_RDBU_COLORS):
            gradient.setColorAt(i / (n - 1), QColor(r, g, b, a))
        painter.fillRect(0, 0, self.width(), self.height(), QBrush(gradient))


# ---------------------------------------------------------------------------
# Colorbar side-panel
# ---------------------------------------------------------------------------

class _ColormapSideBar(QWidget):
    """
    Vertical colorbar: vmax spinbox → gradient strip → vmin spinbox → Auto button.

    Connects to an pg.ImageView to control / read back its level range.
    """

    def __init__(self, img_view: pg.ImageView, parent=None):
        super().__init__(parent)
        self._img_view = img_view
        self.setFixedWidth(72)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(2)

        # vmax spinbox (top = hot / red end)
        self._vmax_spin = QDoubleSpinBox()
        self._vmax_spin.setRange(-1e9, 1e9)
        self._vmax_spin.setDecimals(4)
        self._vmax_spin.setValue(1.0)
        self._vmax_spin.setSingleStep(0.01)
        self._vmax_spin.setFixedWidth(68)
        self._vmax_spin.setToolTip("Colormap maximum (Gauss)")
        layout.addWidget(self._vmax_spin)

        # Gradient strip
        layout.addWidget(_GradientStrip(), stretch=1)

        # vmin spinbox (bottom = cold / blue end)
        self._vmin_spin = QDoubleSpinBox()
        self._vmin_spin.setRange(-1e9, 1e9)
        self._vmin_spin.setDecimals(4)
        self._vmin_spin.setValue(-1.0)
        self._vmin_spin.setSingleStep(0.01)
        self._vmin_spin.setFixedWidth(68)
        self._vmin_spin.setToolTip("Colormap minimum (Gauss)")
        layout.addWidget(self._vmin_spin)

        # Auto button
        auto_btn = QPushButton("Auto")
        auto_btn.setFixedWidth(68)
        auto_btn.setToolTip("Auto-scale colormap range to data")
        layout.addWidget(auto_btn)

        # Connect spinbox edits → image levels
        self._vmax_spin.valueChanged.connect(self._apply_range)
        self._vmin_spin.valueChanged.connect(self._apply_range)
        auto_btn.clicked.connect(self.auto_range)

    def _apply_range(self):
        vmin = self._vmin_spin.value()
        vmax = self._vmax_spin.value()
        if vmax > vmin:
            self._img_view.setLevels(vmin, vmax)

    def auto_range(self):
        """Reset levels to the data min/max and update spinboxes."""
        img_item = self._img_view.getImageItem()
        if img_item is None or img_item.image is None:
            return
        data = img_item.image
        finite = data[np.isfinite(data)]
        if len(finite) == 0:
            return
        vmin, vmax = float(finite.min()), float(finite.max())
        if vmin == vmax:
            vmin -= 1.0
            vmax += 1.0
        # Block signals while updating spinboxes to avoid recursive calls
        self._vmin_spin.blockSignals(True)
        self._vmax_spin.blockSignals(True)
        self._vmin_spin.setValue(vmin)
        self._vmax_spin.setValue(vmax)
        self._vmin_spin.blockSignals(False)
        self._vmax_spin.blockSignals(False)
        self._img_view.setLevels(vmin, vmax)

    def set_range(self, vmin: float, vmax: float):
        """Programmatically set the range and update spinboxes."""
        self._vmin_spin.blockSignals(True)
        self._vmax_spin.blockSignals(True)
        self._vmin_spin.setValue(vmin)
        self._vmax_spin.setValue(vmax)
        self._vmin_spin.blockSignals(False)
        self._vmax_spin.blockSignals(False)
        if vmax > vmin:
            self._img_view.setLevels(vmin, vmax)


# ---------------------------------------------------------------------------
# Single field map panel
# ---------------------------------------------------------------------------

class _FieldPanel(QWidget):
    """Single field map panel: title + ImageView + colorbar sidebar + hover label."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(2)

        # Title
        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-weight: bold;")
        outer.addWidget(title_label)

        # Image + colorbar side by side
        image_row = QHBoxLayout()
        image_row.setSpacing(2)
        image_row.setContentsMargins(0, 0, 0, 0)

        self._img_view = pg.ImageView(self)
        self._img_view.ui.roiBtn.hide()
        self._img_view.ui.menuBtn.hide()
        self._img_view.ui.histogram.hide()
        image_row.addWidget(self._img_view, stretch=1)

        self._colorbar = _ColormapSideBar(self._img_view)
        image_row.addWidget(self._colorbar)

        outer.addLayout(image_row, stretch=1)

        # Hover label
        self._hover_label = QLabel("Hover for pixel value")
        self._hover_label.setAlignment(Qt.AlignCenter)
        self._hover_label.setStyleSheet("color: gray; font-size: 10px;")
        outer.addWidget(self._hover_label)

        self._data = None
        self._cmap = _make_rdbu_colormap()

        self._img_view.scene.sigMouseMoved.connect(self._on_mouse_moved)

    def set_data(self, data: np.ndarray, vmin: float = None, vmax: float = None):
        """
        Display a 2D float array.

        If vmin/vmax are provided they are applied as the initial colormap range
        and the spinboxes are updated.  If not provided, autoLevels is used.
        """
        self._data = data
        if data is None:
            self._img_view.clear()
            return

        finite = data[np.isfinite(data)]
        if len(finite) == 0:
            self._img_view.clear()
            return

        # Determine initial levels
        if vmin is not None and vmax is not None and np.isfinite(vmin) and np.isfinite(vmax) and vmax > vmin:
            auto = False
            levels = (vmin, vmax)
        else:
            auto = True
            levels = None

        self._img_view.setImage(
            data.T,
            autoLevels=auto,
            levels=levels,
        )
        self._img_view.setColorMap(self._cmap)

        # Sync colorbar spinboxes to actual levels
        if auto:
            d_min = float(finite.min())
            d_max = float(finite.max())
            self._colorbar.set_range(d_min, d_max)
            # Re-apply levels explicitly after setColorMap (which may reset them)
            self._img_view.setLevels(d_min, d_max)
        else:
            self._colorbar.set_range(vmin, vmax)

    def auto_range(self):
        """Delegate auto-range to the colorbar."""
        self._colorbar.auto_range()

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


# ---------------------------------------------------------------------------
# Three-panel display widget
# ---------------------------------------------------------------------------

class FieldMapDisplayWidget(QWidget):
    """
    Three-panel magnetic field map display for ODMR magnetometry results.

    Panels: Raw (mean) | Denoised | Processed (Raw - Denoised)
    Each panel has an adjustable colorbar with min/max spinboxes and Auto button.

    Call ``update_from_result(result_dict)`` after analysis completes.
    Call ``auto_range_all()`` to reset all three panels to their data ranges.

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

        layout.addWidget(self._panel_raw,  stretch=1)
        layout.addWidget(self._panel_den,  stretch=1)
        layout.addWidget(self._panel_proc, stretch=2)

    def update_from_result(self, result: dict):
        """
        Populate all three panels from an analysis result dict.

        Uses autoLevels for raw and denoised.  For processed, uses a symmetric
        range centred on zero (driven by the max absolute value in the data).

        Parameters
        ----------
        result : dict
            Must contain field_map_gauss_raw, field_map_gauss_denoised,
            field_map_gauss_processed (all 2D float arrays in Gauss).
        """
        raw       = result.get("field_map_gauss_raw")
        denoised  = result.get("field_map_gauss_denoised")
        processed = result.get("field_map_gauss_processed")

        self._panel_raw.set_data(raw)
        self._panel_den.set_data(denoised)

        # For processed: symmetric range around zero
        if processed is not None:
            finite = processed[np.isfinite(processed)]
            if len(finite) > 0:
                abs_max = max(abs(float(finite.min())), abs(float(finite.max())))
                if abs_max > 0:
                    self._panel_proc.set_data(processed, -abs_max, abs_max)
                else:
                    self._panel_proc.set_data(processed)
            else:
                self._panel_proc.set_data(None)
        else:
            self._panel_proc.set_data(None)

    def auto_range_all(self):
        """Reset all three panels to their data auto-range."""
        self._panel_raw.auto_range()
        self._panel_den.auto_range()
        self._panel_proc.auto_range()

    def get_colormap_range(self):
        """
        Return the current colormap range of the processed panel.

        Returns
        -------
        tuple of (vmin, vmax) floats.
        """
        bar = self._panel_proc._colorbar
        return bar._vmin_spin.value(), bar._vmax_spin.value()

    def clear(self):
        """Clear all three panels."""
        self._panel_raw.clear()
        self._panel_den.clear()
        self._panel_proc.clear()
