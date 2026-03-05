# Background Subtraction Tab Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a "Background Sub" tab to the ODMR GUI that lets users load two
field-map `.npz` files, run `qdm.analyze_background_subtraction()`, view the
1×3 comparison figure embedded in the tab, adjust color ranges, and save results.

**Architecture:** New tab follows the existing `TabHandler + QThread worker`
pattern identical to `AnalysisTabHandler` / `AnalysisWorker`. The matplotlib
`figure_comparison` (1×3) is embedded in a `FigureCanvasQTAgg`; the 2×3
analysis figure pops up as a separate matplotlib window. Color-range spinboxes
call `qdm.replot_background_subtraction()` to re-render without re-loading files.

**Tech Stack:** PySide6, matplotlib (FigureCanvasQTAgg), numpy, qdm_gen.py
(`analyze_background_subtraction`, `replot_background_subtraction`)

---

## Prerequisites / Key paths

```
ODMR code v2/
├── GUI/odmr_app/
│   ├── odmr_main_window.py          ← modify
│   ├── state/odmr_state.py          ← modify
│   ├── ui/ui_odmr_app_main.py       ← modify
│   ├── workers/
│   │   ├── analysis_worker.py       ← reference model
│   │   └── bg_subtraction_worker.py ← CREATE
│   ├── tabs/
│   │   ├── analysis_tab.py          ← reference model
│   │   └── bg_subtraction_tab.py   ← CREATE
│   └── ui/
│       ├── ui_odmr_analysis_tab.py  ← reference model
│       └── ui_odmr_bg_subtraction_tab.py ← CREATE
└── qdm_gen.py   (analyze_background_subtraction, replot_background_subtraction)
```

Run tests with:
```bash
cd "G:/Shared drives/PHYS - Walsworth Group/Experiment folders/Bioimaging/ODMR code/ODMR code v2"
python -m pytest GUI/odmr_app/tests/ -x -q
```

Smoke-test the app with:
```bash
python GUI/odmr_app/odmr_app.py
```

---

## Task 1: Back up files that will be modified and add state properties

**Files:**
- Modify: `GUI/odmr_app/state/odmr_state.py`

**Step 1: Back up odmr_state.py**

```bash
cp "GUI/odmr_app/state/odmr_state.py" \
   "legacy/odmr_state_2026-03-04_v1.py"
```

**Step 2: Add the signal to the Signals section**

In `odmr_state.py`, find the `# Analysis` signals block (around line 81-82):
```python
    # Analysis
    analysis_completed = Signal(dict)
```
Add after it:
```python
    # Background subtraction
    bg_sub_completed = Signal(dict)
```

**Step 3: Add plain attributes to `__init__`**

Find the constructor's init block (after magnetometry properties, around line 280+).
Add a new section at the end of `__init__`, before the property definitions:

```python
        # ------------------------------------------------------------------
        # Background subtraction subsystem
        # ------------------------------------------------------------------
        self.bg_sub_bg_file: str = ""
        self.bg_sub_sample_file: str = ""
        self.bg_sub_gaussian_sigma: float = 7.0
        self.bg_sub_result: dict | None = None
        # vrange: None = auto-scale; (float, float) = explicit (min, max) in Gauss
        self.bg_sub_vrange_raw: tuple | None = None
        self.bg_sub_vrange_denoised: tuple | None = None
        self.bg_sub_vrange_processed: tuple | None = None
        self.bg_sub_vrange_subtracted: tuple | None = None
```

Note: these are plain attributes (no Qt property/signal needed — the tab
handler reads them directly on demand rather than reacting to changes).

**Step 4: Run existing tests to confirm nothing is broken**

```bash
python -m pytest GUI/odmr_app/tests/ -x -q
```
Expected: all tests pass (same count as before).

**Step 5: Commit**

```bash
git add GUI/odmr_app/state/odmr_state.py legacy/odmr_state_2026-03-04_v1.py
git commit -m "feat: add bg_sub state properties and signal to ODMRAppState"
```

---

## Task 2: Create BgSubtractionWorker

**Files:**
- Create: `GUI/odmr_app/workers/bg_subtraction_worker.py`

**Step 1: Create the worker file**

```python
"""
BgSubtractionWorker — Background QThread for field-map background subtraction.

Runs ``qdm_gen.analyze_background_subtraction`` off the main thread so the
UI stays responsive while numpy/scipy/matplotlib work is executing.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QThread, Signal

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import qdm_gen as qdm


class BgSubtractionWorker(QThread):
    """
    Worker thread that executes ``qdm.analyze_background_subtraction``.

    Parameters
    ----------
    bg_file : str
        Full path to the background .npz file (measurement without sample).
    sample_file : str
        Full path to the sample .npz file (measurement with sample).
    gaussian_sigma : float
        Sigma (pixels) for Gaussian denoising (default 7.0).

    Signals
    -------
    completed : dict
        Emitted with the result dict on success.
    failed : str
        Emitted with the error message on exception.
    """

    completed = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        bg_file: str,
        sample_file: str,
        gaussian_sigma: float = 7.0,
        parent=None,
    ):
        """
        Initialise the worker.

        Parameters
        ----------
        bg_file : str
            Path to background .npz file.
        sample_file : str
            Path to sample .npz file.
        gaussian_sigma : float
            Gaussian denoising sigma in pixels.
        parent : QObject, optional
            Qt parent object.
        """
        super().__init__(parent)
        self._bg_file = bg_file
        self._sample_file = sample_file
        self._gaussian_sigma = gaussian_sigma

    def run(self):
        """Execute background subtraction in the worker thread."""
        try:
            result = qdm.analyze_background_subtraction(
                bg_file=self._bg_file,
                sample_file=self._sample_file,
                gaussian_sigma=self._gaussian_sigma,
                show_plot=False,
                save_fig=False,
                save_data=False,
            )
            self.completed.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
```

**Step 2: Run existing tests**

```bash
python -m pytest GUI/odmr_app/tests/ -x -q
```
Expected: all pass.

**Step 3: Commit**

```bash
git add GUI/odmr_app/workers/bg_subtraction_worker.py
git commit -m "feat: add BgSubtractionWorker QThread"
```

---

## Task 3: Create the UI definition

**Files:**
- Create: `GUI/odmr_app/ui/ui_odmr_bg_subtraction_tab.py`

**Step 1: Create the UI file**

This is a Python-only UI definition (no Qt Designer `.ui` file). Model it on
`ui_odmr_analysis_tab.py` but build it entirely in Python.

```python
# -*- coding: utf-8 -*-
"""
UI definition for the Background Subtraction tab.

Built in pure Python (no .ui file) to keep the workflow self-contained.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSizePolicy, QSpacerItem,
    QVBoxLayout, QWidget,
)


class Ui_bg_sub_tab_content:
    """UI layout for the Background Subtraction tab."""

    def setupUi(self, parent: QWidget):
        """Build and attach all widgets to *parent*."""
        root = QVBoxLayout(parent)
        root.setSpacing(6)
        root.setContentsMargins(8, 8, 8, 8)

        # ── Files ────────────────────────────────────────────────────────
        files_group = QGroupBox("Files")
        files_form = QFormLayout(files_group)

        self.bg_path_edit = QLineEdit()
        self.bg_path_edit.setPlaceholderText("Path to background .npz file (no sample)")
        self.bg_browse_btn = QPushButton("Browse…")
        bg_row = QHBoxLayout()
        bg_row.addWidget(self.bg_path_edit, stretch=1)
        bg_row.addWidget(self.bg_browse_btn)
        files_form.addRow("Background (.npz):", bg_row)

        self.sample_path_edit = QLineEdit()
        self.sample_path_edit.setPlaceholderText("Path to sample .npz file (with sample)")
        self.sample_browse_btn = QPushButton("Browse…")
        sample_row = QHBoxLayout()
        sample_row.addWidget(self.sample_path_edit, stretch=1)
        sample_row.addWidget(self.sample_browse_btn)
        files_form.addRow("Sample (.npz):", sample_row)

        root.addWidget(files_group)

        # ── Parameters ───────────────────────────────────────────────────
        params_group = QGroupBox("Parameters")
        params_hbox = QHBoxLayout(params_group)

        params_hbox.addWidget(QLabel("Gaussian sigma:"))
        self.sigma_spin = QDoubleSpinBox()
        self.sigma_spin.setRange(0.5, 100.0)
        self.sigma_spin.setSingleStep(0.5)
        self.sigma_spin.setValue(7.0)
        self.sigma_spin.setSuffix(" px")
        self.sigma_spin.setDecimals(1)
        params_hbox.addWidget(self.sigma_spin)

        params_hbox.addSpacerItem(
            QSpacerItem(20, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        self.run_btn = QPushButton("Run Background Subtraction")
        self.run_btn.setMinimumWidth(220)
        params_hbox.addWidget(self.run_btn)

        root.addWidget(params_group)

        # ── Color Range ──────────────────────────────────────────────────
        color_group = QGroupBox("Color Range (Gauss)")
        color_form = QFormLayout(color_group)

        self._vrange_rows: dict = {}  # key → (auto_chk, min_spin, max_spin)
        for key, label in [
            ("raw",        "Raw:"),
            ("denoised",   "Denoised:"),
            ("processed",  "Processed:"),
            ("subtracted", "Subtracted:"),
        ]:
            auto_chk = QCheckBox("Auto")
            auto_chk.setChecked(True)
            min_spin = QDoubleSpinBox()
            min_spin.setRange(-1000.0, 1000.0)
            min_spin.setDecimals(4)
            min_spin.setSingleStep(0.001)
            min_spin.setValue(-0.1)
            min_spin.setEnabled(False)
            max_spin = QDoubleSpinBox()
            max_spin.setRange(-1000.0, 1000.0)
            max_spin.setDecimals(4)
            max_spin.setSingleStep(0.001)
            max_spin.setValue(0.1)
            max_spin.setEnabled(False)

            row_widget = QHBoxLayout()
            row_widget.addWidget(auto_chk)
            row_widget.addWidget(QLabel("min"))
            row_widget.addWidget(min_spin)
            row_widget.addWidget(QLabel("max"))
            row_widget.addWidget(max_spin)
            row_widget.addStretch()

            color_form.addRow(label, row_widget)
            self._vrange_rows[key] = (auto_chk, min_spin, max_spin)

        self.replot_btn = QPushButton("Replot")
        self.replot_btn.setEnabled(False)
        color_form.addRow("", self.replot_btn)

        root.addWidget(color_group)

        # ── Stats label ───────────────────────────────────────────────────
        self.stats_label = QLabel("Stats: —")
        root.addWidget(self.stats_label)

        # ── Figure canvas placeholder ─────────────────────────────────────
        # The tab handler injects FigureCanvasQTAgg here at runtime.
        self.canvas_placeholder = QWidget()
        self.canvas_placeholder.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self.canvas_placeholder, stretch=1)

        # ── Save ──────────────────────────────────────────────────────────
        save_group = QGroupBox("Save")
        save_hbox = QHBoxLayout(save_group)
        save_hbox.addWidget(QLabel("Prefix:"))
        self.prefix_edit = QLineEdit()
        self.prefix_edit.setMaximumWidth(160)
        save_hbox.addWidget(self.prefix_edit)
        save_hbox.addSpacerItem(
            QSpacerItem(20, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        self.save_fig_btn = QPushButton("Save Fig")
        self.save_fig_btn.setEnabled(False)
        self.save_data_btn = QPushButton("Save Data")
        self.save_data_btn.setEnabled(False)
        save_hbox.addWidget(self.save_fig_btn)
        save_hbox.addWidget(self.save_data_btn)
        root.addWidget(save_group)
```

**Step 2: Verify it imports cleanly**

```bash
python -c "
import sys; sys.path.insert(0, 'GUI/odmr_app')
from ui.ui_odmr_bg_subtraction_tab import Ui_bg_sub_tab_content
print('OK')
"
```
Expected: `OK`

**Step 3: Commit**

```bash
git add GUI/odmr_app/ui/ui_odmr_bg_subtraction_tab.py
git commit -m "feat: add Ui_bg_sub_tab_content UI definition"
```

---

## Task 4: Create BgSubtractionTabHandler

**Files:**
- Create: `GUI/odmr_app/tabs/bg_subtraction_tab.py`

**Step 1: Create the tab handler**

```python
"""Background Subtraction tab handler."""

from __future__ import annotations

import sys
import numpy as np
from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QFileDialog, QMessageBox, QVBoxLayout, QWidget

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import qdm_gen as qdm
from state.odmr_state import ODMRAppState
from workers.bg_subtraction_worker import BgSubtractionWorker
from ui.ui_odmr_bg_subtraction_tab import Ui_bg_sub_tab_content


class BgSubtractionTabHandler:
    """
    Handles the Background Subtraction tab.

    Lets users browse to two saved field-map .npz files (background and
    sample), run ``qdm.analyze_background_subtraction`` in a background
    thread, display the 1×3 comparison figure embedded in the tab, adjust
    color ranges with ``qdm.replot_background_subtraction``, and save the
    result figure and data arrays.

    Parameters
    ----------
    tab_widget : QWidget
        The bare QWidget placeholder for the Background Sub tab.
    state : ODMRAppState
        Central application state.
    """

    def __init__(self, tab_widget: QWidget, state: ODMRAppState):
        self.state = state
        self.ui = Ui_bg_sub_tab_content()
        self.ui.setupUi(tab_widget)

        self._worker: BgSubtractionWorker | None = None
        self._canvas = None   # matplotlib FigureCanvasQTAgg, injected on first result
        self._current_fig = None  # the figure currently shown in the canvas

        self._connect_widgets()

    # ------------------------------------------------------------------
    # Internal wiring
    # ------------------------------------------------------------------

    def _connect_widgets(self):
        """Wire all UI signals."""
        ui = self.ui

        ui.bg_browse_btn.clicked.connect(self._browse_bg)
        ui.sample_browse_btn.clicked.connect(self._browse_sample)
        ui.run_btn.clicked.connect(self._on_run)
        ui.replot_btn.clicked.connect(self._on_replot)
        ui.save_fig_btn.clicked.connect(self._on_save_fig)
        ui.save_data_btn.clicked.connect(self._on_save_data)

        # Auto-checkbox toggles enable state of min/max spinboxes
        for key, (auto_chk, min_spin, max_spin) in ui._vrange_rows.items():
            auto_chk.toggled.connect(
                lambda checked, ms=min_spin, xs=max_spin: (
                    ms.setEnabled(not checked),
                    xs.setEnabled(not checked),
                )
            )

    # ------------------------------------------------------------------
    # Browse slots
    # ------------------------------------------------------------------

    @Slot()
    def _browse_bg(self):
        """Open file dialog for the background .npz file."""
        path, _ = QFileDialog.getOpenFileName(
            None, "Select Background Field Map", "", "NumPy files (*.npz)")
        if path:
            self.ui.bg_path_edit.setText(path)
            self.state.bg_sub_bg_file = path

    @Slot()
    def _browse_sample(self):
        """Open file dialog for the sample .npz file."""
        path, _ = QFileDialog.getOpenFileName(
            None, "Select Sample Field Map", "", "NumPy files (*.npz)")
        if path:
            self.ui.sample_path_edit.setText(path)
            self.state.bg_sub_sample_file = path

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    @Slot()
    def _on_run(self):
        """Validate inputs and start the BgSubtractionWorker."""
        bg = self.ui.bg_path_edit.text().strip()
        sample = self.ui.sample_path_edit.text().strip()

        if not bg:
            QMessageBox.critical(None, "Missing File", "Please select a background .npz file.")
            return
        if not sample:
            QMessageBox.critical(None, "Missing File", "Please select a sample .npz file.")
            return
        if not Path(bg).is_file():
            QMessageBox.critical(None, "File Not Found", f"Background file not found:\n{bg}")
            return
        if not Path(sample).is_file():
            QMessageBox.critical(None, "File Not Found", f"Sample file not found:\n{sample}")
            return

        sigma = self.ui.sigma_spin.value()
        self.state.bg_sub_bg_file = bg
        self.state.bg_sub_sample_file = sample
        self.state.bg_sub_gaussian_sigma = sigma

        self.ui.run_btn.setEnabled(False)
        self.state.status_message.emit("Running background subtraction…")

        worker = BgSubtractionWorker(bg, sample, sigma)
        worker.completed.connect(self._on_completed)
        worker.failed.connect(self._on_failed)
        self._worker = worker
        worker.start()

    @Slot(dict)
    def _on_completed(self, result: dict):
        """Handle successful worker completion."""
        self.ui.run_btn.setEnabled(True)
        self.state.bg_sub_result = result
        self.state.bg_sub_completed.emit(result)

        # Show 2×3 analysis figure as popup
        fig_analysis = result.get("figure_analysis")
        if fig_analysis is not None:
            fig_analysis.show()

        # Embed 1×3 comparison figure in the tab
        self._embed_figure(result.get("figure_comparison"))

        # Update stats label from subtracted map
        sub = result.get("subtracted")
        if sub is not None:
            self.ui.stats_label.setText(
                f"Subtracted — Mean: {np.nanmean(sub):+.4f} G    "
                f"Std: {np.nanstd(sub):.4f} G    "
                f"Range: [{np.nanmin(sub):.4f}, {np.nanmax(sub):.4f}] G"
            )

        # Enable post-run controls
        self.ui.replot_btn.setEnabled(True)
        self.ui.save_fig_btn.setEnabled(True)
        self.ui.save_data_btn.setEnabled(True)

        self.state.status_message.emit("Background subtraction complete.")

    @Slot(str)
    def _on_failed(self, error_msg: str):
        """Handle worker failure."""
        self.ui.run_btn.setEnabled(True)
        self.state.status_message.emit(f"Background subtraction error: {error_msg[:80]}")
        QMessageBox.critical(None, "Background Subtraction Error", error_msg)

    # ------------------------------------------------------------------
    # Replot
    # ------------------------------------------------------------------

    @Slot()
    def _on_replot(self):
        """Re-render the comparison figure with current color range settings."""
        result = self.state.bg_sub_result
        if result is None:
            return

        vranges = {}
        for key in ("raw", "denoised", "processed", "subtracted"):
            auto_chk, min_spin, max_spin = self.ui._vrange_rows[key]
            if auto_chk.isChecked():
                vranges[key] = None
            else:
                vmin = min_spin.value()
                vmax = max_spin.value()
                if vmin >= vmax:
                    vmax = vmin + 0.001
                    max_spin.setValue(vmax)
                vranges[key] = (vmin, vmax)

        try:
            figs = qdm.replot_background_subtraction(
                result,
                vrange_raw=vranges["raw"],
                vrange_denoised=vranges["denoised"],
                vrange_processed=vranges["processed"],
                vrange_subtracted=vranges["subtracted"],
                show_plot=False,
                save_fig=False,
            )
            # replot_background_subtraction returns a dict with
            # 'figure_analysis' and 'figure_comparison'
            self._embed_figure(figs.get("figure_comparison"))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(None, "Replot Error", str(exc))

    # ------------------------------------------------------------------
    # Canvas embedding
    # ------------------------------------------------------------------

    def _embed_figure(self, fig):
        """Replace the canvas placeholder content with *fig*."""
        if fig is None:
            return

        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

        placeholder = self.ui.canvas_placeholder

        # Remove old canvas if present
        old_layout = placeholder.layout()
        if old_layout is not None:
            while old_layout.count():
                item = old_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        else:
            layout = QVBoxLayout(placeholder)
            layout.setContentsMargins(0, 0, 0, 0)

        canvas = FigureCanvasQTAgg(fig)
        placeholder.layout().addWidget(canvas)
        canvas.draw()
        self._canvas = canvas
        self._current_fig = fig

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    @Slot()
    def _on_save_fig(self):
        """Save the comparison figure as a PNG file."""
        result = self.state.bg_sub_result
        if result is None or self._current_fig is None:
            return
        prefix = self.ui.prefix_edit.text().strip()
        stem = self.state.build_save_filename("bg_subtraction", user_prefix=prefix)
        save_dir = Path(self.state.save_base_path) / self.state.save_subfolder
        save_dir.mkdir(parents=True, exist_ok=True)
        path = save_dir / f"{stem}.png"
        self._current_fig.savefig(str(path), dpi=150, bbox_inches="tight")
        self.state.status_message.emit(f"Saved figure: {path.name}")

    @Slot()
    def _on_save_data(self):
        """Save subtracted, bg_processed, and sample_processed arrays as .npz."""
        result = self.state.bg_sub_result
        if result is None:
            return
        prefix = self.ui.prefix_edit.text().strip()
        stem = self.state.build_save_filename("bg_subtraction", user_prefix=prefix)
        save_dir = Path(self.state.save_base_path) / self.state.save_subfolder
        save_dir.mkdir(parents=True, exist_ok=True)
        path = save_dir / f"{stem}.npz"
        np.savez_compressed(
            path,
            subtracted=result["subtracted"],
            bg_processed=result["bg_processed"],
            sample_processed=result["sample_processed"],
            bg_raw=result["bg_raw"],
            sample_raw=result["sample_raw"],
            gaussian_sigma=np.array(result.get("gaussian_sigma", self.state.bg_sub_gaussian_sigma)),
            bg_file=str(result.get("bg_file", self.state.bg_sub_bg_file)),
            sample_file=str(result.get("sample_file", self.state.bg_sub_sample_file)),
        )
        self.state.status_message.emit(f"Saved data: {path.name}")
```

**Step 2: Verify it imports cleanly**

```bash
python -c "
import sys; sys.path.insert(0, 'GUI/odmr_app')
from tabs.bg_subtraction_tab import BgSubtractionTabHandler
print('OK')
"
```
Expected: `OK`

**Step 3: Commit**

```bash
git add GUI/odmr_app/tabs/bg_subtraction_tab.py
git commit -m "feat: add BgSubtractionTabHandler"
```

---

## Task 5: Wire the tab into the main window

**Files:**
- Modify: `GUI/odmr_app/ui/ui_odmr_app_main.py`
- Modify: `GUI/odmr_app/odmr_main_window.py`

**Step 1: Back up files**

```bash
cp "GUI/odmr_app/ui/ui_odmr_app_main.py" \
   "legacy/ui_odmr_app_main_2026-03-04_v1.py"
cp "GUI/odmr_app/odmr_main_window.py" \
   "legacy/odmr_main_window_2026-03-04_v1.py"
```

**Step 2: Add the tab placeholder in `ui_odmr_app_main.py`**

In `setupUi`, find the existing `self.settings_tab` block:
```python
        self.settings_tab = QWidget()
        self.settings_tab.setObjectName(u"settings_tab")
        self.tab_widget.addTab(self.settings_tab, "")
```
Add the new tab **before** `self.settings_tab`:
```python
        self.bg_sub_tab = QWidget()
        self.bg_sub_tab.setObjectName(u"bg_sub_tab")
        self.tab_widget.addTab(self.bg_sub_tab, "")
```

In `retranslateUi`, find the settings tab text line:
```python
        self.tab_widget.setTabText(self.tab_widget.indexOf(self.settings_tab), ...)
```
Add **before** it:
```python
        self.tab_widget.setTabText(self.tab_widget.indexOf(self.bg_sub_tab),
            QCoreApplication.translate("ODMRMainWindow", u"Background Sub", None))
```

**Step 3: Instantiate the tab handler in `odmr_main_window.py`**

In `__init__`, find the sensitivity handler instantiation:
```python
        from tabs.sensitivity_tab import SensitivityTabHandler
        self._sensitivity_handler = SensitivityTabHandler(
            self.ui.sensitivity_tab, self.state)
```
Add **after** it:
```python
        from tabs.bg_subtraction_tab import BgSubtractionTabHandler
        self._bg_sub_handler = BgSubtractionTabHandler(
            self.ui.bg_sub_tab, self.state)
```

**Step 4: Run existing tests**

```bash
python -m pytest GUI/odmr_app/tests/ -x -q
```
Expected: all tests pass.

**Step 5: Smoke test the app**

```bash
python GUI/odmr_app/odmr_app.py
```
Expected:
- App opens without errors
- A "Background Sub" tab appears between "Sensitivity" and "Settings"
- The tab shows: Files group, Parameters group, Color Range group, stats label, canvas placeholder, Save group
- Browse buttons open file dialogs
- Run button is clickable (will error if no valid files, which is expected)

**Step 6: Commit**

```bash
git add GUI/odmr_app/ui/ui_odmr_app_main.py \
        GUI/odmr_app/odmr_main_window.py \
        legacy/ui_odmr_app_main_2026-03-04_v1.py \
        legacy/odmr_main_window_2026-03-04_v1.py
git commit -m "feat: wire Background Sub tab into main window"
```

---

## Task 6: End-to-end smoke test with real .npz files

**Step 1: Launch the app**

```bash
python GUI/odmr_app/odmr_app.py
```

**Step 2: Manual test checklist**

- [ ] "Background Sub" tab visible and correctly positioned
- [ ] Browse buttons open `.npz` file dialogs
- [ ] Run with missing/invalid path → `QMessageBox.critical` appears
- [ ] Run with two valid field-map `.npz` files → 2×3 figure pops up in separate window, 1×3 comparison renders in tab
- [ ] Stats label updates with Mean / Std / Range
- [ ] Uncheck "Auto" on Subtracted, set vrange, click Replot → embedded figure updates
- [ ] Save Fig → PNG written to save_base_path/subfolder
- [ ] Save Data → .npz written with expected keys

**Step 3: Commit if any minor fixes were needed**

```bash
git add -A
git commit -m "fix: bg subtraction tab post-smoke-test adjustments"
```
