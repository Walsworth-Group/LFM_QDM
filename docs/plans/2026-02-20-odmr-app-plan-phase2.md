# ODMR App — Phase 2: Camera Refactor & Custom Widgets

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor `camera_app.py` to expose a reusable `CameraTabWidget`, and create the two custom widgets needed by the ODMR app: `InflectionTableWidget` and `FieldMapDisplayWidget`.

**Architecture:** CameraTabWidget is the main camera UI extracted from BaslerCameraApp so it can be embedded in the ODMR app's Camera tab and still used standalone. InflectionTableWidget wraps a QTableWidget with preset/point-file save-load logic. FieldMapDisplayWidget shows three pyqtgraph panels (raw/denoised/processed) with hover readout.

**Tech Stack:** PySide6, pyqtgraph, numpy, json

**Prerequisites:** Phase 1 complete.

---

## Task 6: Refactor camera_app.py → CameraTabWidget

**Files:**
- Backup: `GUI/legacy/camera_app_YYYY-MM-DD_v1.py`
- Modify: `GUI/camera_app.py`

**Context:** `BaslerCameraApp` currently is both the main window AND contains all camera UI logic in one class. We need to extract the content widget so it can be embedded as a tab in the ODMR app. The standalone app behavior must be unchanged.

**Step 1: Backup**
```bash
cp "GUI/camera_app.py" "GUI/legacy/camera_app_2026-02-20_v1.py"
```

**Step 2: Read the full camera_app.py**
Read `GUI/camera_app.py` completely before making any changes. Understand what `__init__` sets up, what methods exist, and what layout is created.

**Step 3: Extract CameraTabWidget**

In `camera_app.py`, add a new class `CameraTabWidget(QWidget)` that contains all the UI and logic currently in `BaslerCameraApp`, but as a plain `QWidget` (not `QMainWindow`). Then make `BaslerCameraApp` a thin `QMainWindow` wrapper:

```python
class CameraTabWidget(QWidget):
    """
    Camera streaming UI as an embeddable widget.

    Can be placed inside a QMainWindow, a QTabWidget tab, or any QWidget.
    All camera logic, worker management, and signal connections live here.
    Constructor accepts an optional CameraState; if None, creates its own.
    """

    def __init__(self, state=None, config_file=None, parent=None):
        super().__init__(parent)
        self.state = state if state is not None else CameraState()
        self._config_file = config_file or CONFIG_FILE
        self.worker = None
        self.consumer = None
        self.frame_queue = None
        self.last_live_update = 0
        self.last_status_update = 0
        self.current_live_frame = None
        self.current_averaged_frame = None

        self._load_config()
        self._init_ui()
        self._connect_signals()
        self._apply_config()

    # --- move all existing UI/logic methods here, unchanged ---
    # init_ui → _init_ui
    # connect_signals → _connect_signals
    # etc.

    def save_config(self):  # same as before
        ...

    def load_config(self):  # rename to _load_config internally
        ...

    # closeEvent is NOT here (belongs to QMainWindow)
    # Add cleanup method instead:
    def cleanup(self):
        """Stop workers. Call from parent window's closeEvent."""
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(3000)
        if self.consumer and self.consumer.isRunning():
            self.consumer.stop()
            self.consumer.wait(3000)


class BaslerCameraApp(QMainWindow):
    """
    Standalone camera app. Thin wrapper around CameraTabWidget.
    Preserves existing external interface (state= param, geometry, etc.).
    """

    def __init__(self, state=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Basler Camera")
        self._camera_widget = CameraTabWidget(state=state, parent=self)
        self.setCentralWidget(self._camera_widget)

        # Keep .state property for backward compat with launch_all_apps.py
        self.state = self._camera_widget.state

    def closeEvent(self, event):
        self._camera_widget.cleanup()
        self._camera_widget.save_config()
        event.accept()
```

**Step 4: Verify standalone still works**

Launch standalone and confirm nothing changed visually:
```bash
cd GUI
python camera_app.py
```
Expected: App opens, camera controls present, connect/disconnect works.

**Step 5: Verify the widget is importable**
```python
# Quick smoke test
cd GUI
python -c "
import sys
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
from camera_app import CameraTabWidget
from state.camera_state import CameraState
state = CameraState()
w = CameraTabWidget(state=state)
w.show()
print('CameraTabWidget OK')
app.quit()
"
```

**Step 6: Commit**
```bash
git add GUI/camera_app.py GUI/legacy/camera_app_2026-02-20_v1.py
git commit -m "refactor(camera-app): extract CameraTabWidget for embedding in ODMR app"
```

---

## Task 7: Create InflectionTableWidget

**Files:**
- Create: `GUI/odmr_app/widgets/inflection_table.py`
- Create: `GUI/odmr_app/tests/test_inflection_table.py`

**Purpose:** 8-row table showing inflection point data with per-row controls.
Each row: `#` | `Freq (GHz)` *(editable)* | `Slope (GHz⁻¹)` | `Use?` *(checkbox)* | `Parity` *(+1/-1/ref dropdown)* | `Role` *(computed label)*.

Also manages preset files and point-export files.

**Step 1: Write tests**

Create `GUI/odmr_app/tests/test_inflection_table.py`:
```python
"""Tests for InflectionTableWidget."""
import sys
import json
import numpy as np
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

from widgets.inflection_table import InflectionTableWidget


FAKE_INFLECTION = {
    "inflection_points": np.array([2.519, 2.522, 2.516, 2.525,
                                   3.212, 3.215, 3.210, 3.218]),
    "inflection_slopes": np.array([-15.5, +15.5, -15.3, +15.3,
                                   +14.9, -14.9, +14.7, -14.7]),
    "inflection_contrasts": np.ones(8) * 0.988,
}


def test_table_populates_from_result():
    w = InflectionTableWidget()
    w.populate_from_sweep_result(FAKE_INFLECTION)
    assert w.row_count() == 8
    freq = w.get_freq(0)
    assert abs(freq - 2.519) < 1e-6


def test_table_get_selection():
    w = InflectionTableWidget()
    w.populate_from_sweep_result(FAKE_INFLECTION)
    # Default: no rows selected
    sel = w.get_selection()
    assert "indices" in sel
    assert "parities" in sel
    assert "freq_list" in sel


def test_table_set_selection_from_preset():
    w = InflectionTableWidget()
    w.populate_from_sweep_result(FAKE_INFLECTION)
    preset = {
        "name": "test",
        "selected_indices": [1, 4, 0, 5, 8, 0],
        "selected_parities": [1, 1, 0, -1, -1, 0],
        "ref_freq_ghz": 1.0,
    }
    w.apply_preset(preset)
    sel = w.get_selection()
    assert sel["indices"] == [1, 4, 0, 5, 8, 0]
    assert sel["parities"] == [1, 1, 0, -1, -1, 0]


def test_freq_editable(tmp_path):
    w = InflectionTableWidget()
    w.populate_from_sweep_result(FAKE_INFLECTION)
    w.set_freq(0, 2.519999)
    assert abs(w.get_freq(0) - 2.519999) < 1e-6


def test_preset_save_load(tmp_path):
    w = InflectionTableWidget()
    w.populate_from_sweep_result(FAKE_INFLECTION)
    preset = {
        "name": "mypreset",
        "selected_indices": [1, 4, 0, 5, 8, 0],
        "selected_parities": [1, 1, 0, -1, -1, 0],
        "ref_freq_ghz": 1.0,
        "description": "test preset",
    }
    path = tmp_path / "mypreset.json"
    w.save_preset_to_file(preset, path)
    loaded = w.load_preset_from_file(path)
    assert loaded["name"] == "mypreset"
    assert loaded["selected_indices"] == [1, 4, 0, 5, 8, 0]


def test_point_export_roundtrip(tmp_path):
    w = InflectionTableWidget()
    w.populate_from_sweep_result(FAKE_INFLECTION)
    path = tmp_path / "inflection_points.json"
    w.save_points_to_file(path)
    w2 = InflectionTableWidget()
    w2.load_points_from_file(path)
    assert abs(w2.get_freq(0) - 2.519) < 1e-6
```

**Step 2: Run to verify failure**
```bash
python -m pytest tests/test_inflection_table.py -v 2>&1 | head -20
```

**Step 3: Implement `GUI/odmr_app/widgets/inflection_table.py`**

```python
"""
InflectionTableWidget — Displays and edits the 8 ODMR inflection points.

Columns: #, Freq (GHz) [editable], Slope (GHz⁻¹), Use?, Parity, Role
Handles: preset save/load (JSON), point-file export/import (JSON).
"""

import json
import numpy as np
from pathlib import Path
from typing import Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QCheckBox, QComboBox, QLabel, QHeaderView, QAbstractItemView,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont


PARITY_OPTIONS = ["+1 (signal)", "-1 (signal)", "0 (reference)"]
PARITY_VALUES = [1, -1, 0]


class InflectionTableWidget(QWidget):
    """
    Table of 8 ODMR inflection points with per-row selection and parity controls.

    Signals:
        selection_changed: emitted whenever user changes a checkbox or parity.
    """

    selection_changed = Signal()

    N_ROWS = 8
    COL_IDX     = 0
    COL_FREQ    = 1
    COL_SLOPE   = 2
    COL_USE     = 3
    COL_PARITY  = 4
    COL_ROLE    = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._inflection_data = None   # dict from sweep result
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._table = QTableWidget(self.N_ROWS, 6, self)
        self._table.setHorizontalHeaderLabels(
            ["#", "Freq (GHz)", "Slope (GHz⁻¹)", "Use?", "Parity", "Role"])
        self._table.setSelectionMode(QAbstractItemView.NoSelection)
        self._table.setEditTriggers(QAbstractItemView.DoubleClicked |
                                    QAbstractItemView.EditKeyPressed)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setAlternatingRowColors(True)

        # Pre-populate rows with empty data
        for row in range(self.N_ROWS):
            self._table.setItem(row, self.COL_IDX,
                                self._make_readonly_item(str(row + 1)))
            self._table.setItem(row, self.COL_FREQ,
                                QTableWidgetItem("—"))
            self._table.setItem(row, self.COL_SLOPE,
                                self._make_readonly_item("—"))
            # Checkbox cell
            chk_widget = self._make_checkbox_cell(row)
            self._table.setCellWidget(row, self.COL_USE, chk_widget)
            # Parity dropdown
            combo = self._make_parity_combo(row)
            self._table.setCellWidget(row, self.COL_PARITY, combo)
            self._table.setItem(row, self.COL_ROLE,
                                self._make_readonly_item("—"))

        layout.addWidget(self._table)

    def _make_readonly_item(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        return item

    def _make_checkbox_cell(self, row: int) -> QWidget:
        container = QWidget()
        hl = QHBoxLayout(container)
        hl.setContentsMargins(4, 0, 4, 0)
        hl.setAlignment(Qt.AlignCenter)
        chk = QCheckBox()
        chk.stateChanged.connect(lambda: self._on_selection_changed(row))
        hl.addWidget(chk)
        return container

    def _make_parity_combo(self, row: int) -> QComboBox:
        combo = QComboBox()
        combo.addItems(PARITY_OPTIONS)
        combo.setCurrentIndex(2)  # default: reference
        combo.currentIndexChanged.connect(lambda: self._on_selection_changed(row))
        return combo

    def _on_selection_changed(self, row: int):
        self._update_role_label(row)
        self.selection_changed.emit()

    def _update_role_label(self, row: int):
        chk = self._get_checkbox(row)
        combo = self._table.cellWidget(row, self.COL_PARITY)
        if not chk.isChecked():
            role = "—"
        else:
            parity = PARITY_VALUES[combo.currentIndex()]
            role = "Signal" if parity != 0 else "Reference"
        item = self._table.item(row, self.COL_ROLE)
        if item:
            item.setText(role)

    def _get_checkbox(self, row: int) -> QCheckBox:
        container = self._table.cellWidget(row, self.COL_USE)
        return container.layout().itemAt(0).widget()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def row_count(self) -> int:
        return self.N_ROWS

    def populate_from_sweep_result(self, result: dict):
        """Fill table from sweep result dict (inflection_points, slopes, contrasts)."""
        self._inflection_data = result
        pts = result["inflection_points"]
        slopes = result["inflection_slopes"]

        for row in range(self.N_ROWS):
            freq = pts[row] if row < len(pts) else 0.0
            slope = slopes[row] if row < len(slopes) else 0.0
            freq_item = QTableWidgetItem(f"{freq:.6f}")
            self._table.setItem(row, self.COL_FREQ, freq_item)
            self._table.setItem(row, self.COL_SLOPE,
                                self._make_readonly_item(f"{slope:+.4f}"))
            self._update_role_label(row)

    def get_freq(self, row: int) -> float:
        item = self._table.item(row, self.COL_FREQ)
        try:
            return float(item.text())
        except (ValueError, AttributeError):
            return 0.0

    def set_freq(self, row: int, freq: float):
        self._table.item(row, self.COL_FREQ).setText(f"{freq:.6f}")

    def get_selection(self) -> dict:
        """
        Return current selection as dict with indices, parities, freq_list,
        slope_list, baseline_list for direct use in format_multi_point_frequencies.
        """
        indices, parities = [], []
        freq_list, slope_list, baseline_list = [], [], []

        for row in range(self.N_ROWS):
            chk = self._get_checkbox(row)
            combo = self._table.cellWidget(row, self.COL_PARITY)
            parity = PARITY_VALUES[combo.currentIndex()]

            if chk.isChecked():
                indices.append(row + 1)
                parities.append(parity)
                freq_list.append(self.get_freq(row))
                # Slope from inflection data (or 0 if not loaded)
                if (self._inflection_data and
                        row < len(self._inflection_data["inflection_slopes"])):
                    slope_list.append(self._inflection_data["inflection_slopes"][row])
                    baseline_list.append(
                        self._inflection_data["inflection_contrasts"][row])
                else:
                    slope_list.append(0.0)
                    baseline_list.append(1.0)

        return {
            "indices": indices,
            "parities": parities,
            "freq_list": freq_list,
            "slope_list": slope_list,
            "baseline_list": baseline_list,
        }

    def apply_preset(self, preset: dict):
        """
        Apply a preset dict to the table checkboxes and parity dropdowns.
        preset keys: selected_indices, selected_parities, ref_freq_ghz
        """
        indices = preset.get("selected_indices", [])
        parities = preset.get("selected_parities", [])

        # Reset all rows
        for row in range(self.N_ROWS):
            self._get_checkbox(row).setChecked(False)
            self._table.cellWidget(row, self.COL_PARITY).setCurrentIndex(2)

        # Apply selected rows
        for idx, parity in zip(indices, parities):
            if idx == 0:
                continue  # 0 = reference position marker, skip
            row = idx - 1
            if 0 <= row < self.N_ROWS:
                self._get_checkbox(row).setChecked(True)
                parity_combo_idx = PARITY_VALUES.index(parity) if parity in PARITY_VALUES else 2
                self._table.cellWidget(row, self.COL_PARITY).setCurrentIndex(parity_combo_idx)

        self.selection_changed.emit()

    # ------------------------------------------------------------------
    # Preset file I/O
    # ------------------------------------------------------------------

    def save_preset_to_file(self, preset: dict, path: Path):
        """Save preset dict to JSON file."""
        with open(path, 'w') as f:
            json.dump(preset, f, indent=2)

    def load_preset_from_file(self, path: Path) -> dict:
        """Load preset dict from JSON file."""
        with open(path) as f:
            return json.load(f)

    def get_current_as_preset(self, name: str, description: str = "",
                              ref_freq_ghz: float = 1.0) -> dict:
        """Package current table state as a preset dict."""
        sel = self.get_selection()
        return {
            "name": name,
            "description": description,
            "selected_indices": sel["indices"],
            "selected_parities": sel["parities"],
            "ref_freq_ghz": ref_freq_ghz,
        }

    # ------------------------------------------------------------------
    # Point file I/O (save/restore full inflection point arrays)
    # ------------------------------------------------------------------

    def save_points_to_file(self, path: Path):
        """Export full 8-point inflection data to JSON for session restore."""
        if self._inflection_data is None:
            raise RuntimeError("No inflection data loaded. Run sweep first.")
        data = {
            "inflection_points": self._inflection_data["inflection_points"].tolist(),
            "inflection_slopes": self._inflection_data["inflection_slopes"].tolist(),
            "inflection_contrasts": self._inflection_data["inflection_contrasts"].tolist(),
        }
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    def load_points_from_file(self, path: Path):
        """Load inflection points from JSON and repopulate table."""
        with open(path) as f:
            data = json.load(f)
        result = {
            "inflection_points": np.array(data["inflection_points"]),
            "inflection_slopes": np.array(data["inflection_slopes"]),
            "inflection_contrasts": np.array(data["inflection_contrasts"]),
        }
        self.populate_from_sweep_result(result)
```

**Step 4: Run tests**
```bash
python -m pytest tests/test_inflection_table.py -v
```
Expected: All pass.

**Step 5: Commit**
```bash
git add GUI/odmr_app/widgets/inflection_table.py \
        GUI/odmr_app/tests/test_inflection_table.py
git commit -m "feat(odmr-app): add InflectionTableWidget with preset and point-file I/O"
```

---

## Task 8: Create FieldMapDisplayWidget

**Files:**
- Create: `GUI/odmr_app/widgets/field_map_display.py`
- Create: `GUI/odmr_app/tests/test_field_map_display.py`

**Purpose:** Three-panel pyqtgraph display: Raw | Denoised | Processed (Raw − Denoised).
RdBu_r colormap, shared color range on Processed panel, pixel value on hover.

**Step 1: Write tests**

Create `GUI/odmr_app/tests/test_field_map_display.py`:
```python
"""Tests for FieldMapDisplayWidget."""
import sys
import numpy as np
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

from widgets.field_map_display import FieldMapDisplayWidget


def fake_result():
    ny, nx = 20, 30
    raw = np.random.normal(0, 0.01, (ny, nx)).astype(np.float32)
    denoised = np.zeros((ny, nx), dtype=np.float32)
    processed = raw - denoised
    return {
        "field_map_gauss_raw": raw,
        "field_map_gauss_denoised": denoised,
        "field_map_gauss_processed": processed,
    }


def test_widget_creates():
    w = FieldMapDisplayWidget()
    assert w is not None


def test_widget_updates_from_result():
    w = FieldMapDisplayWidget()
    result = fake_result()
    w.update_from_result(result)
    # No exception = pass


def test_widget_clears():
    w = FieldMapDisplayWidget()
    w.update_from_result(fake_result())
    w.clear()  # Should not raise


def test_get_colormap_range():
    w = FieldMapDisplayWidget()
    result = fake_result()
    w.update_from_result(result)
    vmin, vmax = w.get_colormap_range()
    assert vmax > vmin
```

**Step 2: Run to verify failure**
```bash
python -m pytest tests/test_field_map_display.py -v 2>&1 | head -20
```

**Step 3: Implement `GUI/odmr_app/widgets/field_map_display.py`**

```python
"""
FieldMapDisplayWidget — 3-panel magnetic field map display.

Panels: Raw (mean) | Denoised | Processed (Raw − Denoised)
All panels: RdBu_r colormap, colorbar, pixel B-value on mouse hover.
Processed panel drives the shared colormap range (main result).
"""

import numpy as np
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel
from PySide6.QtCore import Qt
import pyqtgraph as pg


# RdBu_r colormap: blue=negative, white=zero, red=positive
def _make_rdbu_colormap():
    colors = [
        (0.019, 0.188, 0.380, 1.0),   # dark blue
        (0.129, 0.400, 0.674, 1.0),
        (0.416, 0.678, 0.820, 1.0),
        (0.776, 0.902, 0.941, 1.0),
        (1.000, 1.000, 1.000, 1.0),   # white (zero)
        (0.992, 0.859, 0.780, 1.0),
        (0.957, 0.647, 0.510, 1.0),
        (0.839, 0.188, 0.122, 1.0),
        (0.404, 0.000, 0.122, 1.0),   # dark red
    ]
    pos = np.linspace(0, 1, len(colors))
    cmap = pg.ColorMap(pos, [tuple(int(c*255) for c in rgb) for rgb in colors])
    return cmap


class _FieldPanel(QWidget):
    """Single field map panel: ImageView + title + hover label."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self._title = QLabel(title, alignment=Qt.AlignCenter)
        self._title.setStyleSheet("font-weight: bold;")
        layout.addWidget(self._title)

        self._img_view = pg.ImageView(self)
        self._img_view.ui.roiBtn.hide()
        self._img_view.ui.menuBtn.hide()
        layout.addWidget(self._img_view, stretch=1)

        self._hover_label = QLabel("Hover for pixel value", alignment=Qt.AlignCenter)
        self._hover_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(self._hover_label)

        self._data = None
        self._cmap = _make_rdbu_colormap()

        # Mouse hover
        self._img_view.scene.sigMouseMoved.connect(self._on_mouse_moved)

    def set_data(self, data: np.ndarray, vmin: float = None, vmax: float = None):
        """Display a 2D float array. vmin/vmax set the colormap range."""
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
                self._hover_label.setText(
                    f"x={col}, y={row},  B = {val:+.4f} G")
        except Exception:
            pass


class FieldMapDisplayWidget(QWidget):
    """
    Three-panel magnetic field map display.

    Call update_from_result(result_dict) after analysis completes.
    result_dict keys: field_map_gauss_raw, field_map_gauss_denoised,
                      field_map_gauss_processed
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._panel_raw  = _FieldPanel("Raw (mean)")
        self._panel_den  = _FieldPanel("Denoised")
        self._panel_proc = _FieldPanel("Processed (Raw − Denoised)")

        # Processed is the main result — give it more space
        layout.addWidget(self._panel_raw,  stretch=1)
        layout.addWidget(self._panel_den,  stretch=1)
        layout.addWidget(self._panel_proc, stretch=2)

        self._vmin = None
        self._vmax = None

    def update_from_result(self, result: dict):
        """Populate all three panels from an analyze_multi_point_magnetometry result dict."""
        raw       = result.get("field_map_gauss_raw")
        denoised  = result.get("field_map_gauss_denoised")
        processed = result.get("field_map_gauss_processed")

        # Colormap range driven by processed panel (symmetric around zero)
        if processed is not None:
            abs_max = max(abs(np.nanmin(processed)), abs(np.nanmax(processed)))
            self._vmin, self._vmax = -abs_max, abs_max
        else:
            self._vmin, self._vmax = None, None

        self._panel_raw.set_data(raw)
        self._panel_den.set_data(denoised)
        self._panel_proc.set_data(processed, self._vmin, self._vmax)

    def clear(self):
        """Clear all panels."""
        self._panel_raw.clear()
        self._panel_den.clear()
        self._panel_proc.clear()
        self._vmin = self._vmax = None

    def get_colormap_range(self):
        """Return (vmin, vmax) of the processed panel."""
        return self._vmin, self._vmax
```

**Step 4: Run tests**
```bash
python -m pytest tests/test_field_map_display.py -v
```
Expected: All pass.

**Step 5: Commit**
```bash
git add GUI/odmr_app/widgets/field_map_display.py \
        GUI/odmr_app/tests/test_field_map_display.py
git commit -m "feat(odmr-app): add FieldMapDisplayWidget with 3-panel RdBu_r display"
```

---

## Phase 2 Complete

Run the full suite:
```bash
cd GUI/odmr_app
python -m pytest tests/ -v
```
Expected: All Phase 1 + Phase 2 tests pass.

```bash
git log --oneline -8
```

**Proceed to Phase 3:** `docs/plans/2026-02-20-odmr-app-plan-phase3.md`
— Qt Designer `.ui` files, main window shell, RF panel, tab wiring.
