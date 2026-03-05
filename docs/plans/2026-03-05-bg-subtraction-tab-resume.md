# Background Subtraction Tab — Resume Document

**Plan file:** `docs/plans/2026-03-04-bg-subtraction-tab.md`
**Date:** 2026-03-05

---

## Progress Summary

| Task | Status | Commit |
|------|--------|--------|
| 1: Add bg_sub state properties + signal to `odmr_state.py` | ✅ Done | `a844a8f` |
| 2: Create `BgSubtractionWorker` QThread | ✅ Done | `29173dd` |
| 3: Create `Ui_bg_sub_tab_content` UI definition | ✅ Done | `1fc581f` |
| 4: Create `BgSubtractionTabHandler` | ❌ Not started |  |
| 5: Wire tab into main window | ❌ Not started |  |
| 6: End-to-end smoke test | ❌ Not started |  |

---

## Files created / modified so far

| File | Change |
|------|--------|
| `GUI/odmr_app/state/odmr_state.py` | Added `bg_sub_completed = Signal(dict)` signal; added 8 plain `bg_sub_*` attributes to `__init__`; added `"bg_sub_gaussian_sigma"` to `_CONFIG_KEYS` |
| `GUI/odmr_app/workers/bg_subtraction_worker.py` | NEW — `BgSubtractionWorker(QThread)` |
| `GUI/odmr_app/ui/ui_odmr_bg_subtraction_tab.py` | NEW — `Ui_bg_sub_tab_content` pure-Python UI |
| `legacy/odmr_state_2026-03-04_v1.py` | Backup of odmr_state.py |

---

## Task 4: Create `BgSubtractionTabHandler`

**File to create:** `GUI/odmr_app/tabs/bg_subtraction_tab.py`

Reference model: `GUI/odmr_app/tabs/analysis_tab.py`

### Key design points
- Follows `TabHandler + QThread worker` pattern identical to `AnalysisTabHandler`
- The matplotlib `figure_comparison` (1×3) is embedded in a `FigureCanvasQTAgg` inside `canvas_placeholder`
- The `figure_analysis` (2×3) is shown as a popup (`fig.show()`)
- Color-range spinboxes call `qdm.replot_background_subtraction()` — returns `{'figure_analysis': ..., 'figure_comparison': ...}`
- Save functions use `self.state.build_save_filename(...)` and `self.state.save_base_path` / `self.state.save_subfolder`

### Full file content

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

### Verification steps after creating the file
```bash
python -c "
import sys, os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, 'GUI/odmr_app')
sys.path.insert(0, '.')
from tabs.bg_subtraction_tab import BgSubtractionTabHandler
print('OK')
"
python -m pytest GUI/odmr_app/tests/ -x -q
```

### Commit
```bash
git add "GUI/odmr_app/tabs/bg_subtraction_tab.py"
git commit -m "feat: add BgSubtractionTabHandler"
```

---

## Task 5: Wire tab into main window

**Files to modify:**
- `GUI/odmr_app/ui/ui_odmr_app_main.py`
- `GUI/odmr_app/odmr_main_window.py`

**Backups required first:**
```bash
cp "GUI/odmr_app/ui/ui_odmr_app_main.py" "legacy/ui_odmr_app_main_2026-03-04_v1.py"
cp "GUI/odmr_app/odmr_main_window.py" "legacy/odmr_main_window_2026-03-04_v1.py"
```

### Change 1: `ui_odmr_app_main.py` — add tab placeholder

In `setupUi`, find the `self.settings_tab` block:
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

In `retranslateUi`, find the settings tab text:
```python
        self.tab_widget.setTabText(self.tab_widget.indexOf(self.settings_tab), ...)
```
Add **before** it:
```python
        self.tab_widget.setTabText(self.tab_widget.indexOf(self.bg_sub_tab),
            QCoreApplication.translate("ODMRMainWindow", u"Background Sub", None))
```

### Change 2: `odmr_main_window.py` — instantiate handler

In `__init__`, find:
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

### Verification + commit
```bash
python -m pytest GUI/odmr_app/tests/ -x -q
git add "GUI/odmr_app/ui/ui_odmr_app_main.py" \
        "GUI/odmr_app/odmr_main_window.py" \
        "legacy/ui_odmr_app_main_2026-03-04_v1.py" \
        "legacy/odmr_main_window_2026-03-04_v1.py"
git commit -m "feat: wire Background Sub tab into main window"
```

---

## Task 6: End-to-end smoke test

```bash
python GUI/odmr_app/odmr_app.py
```

**Manual checklist:**
- [ ] "Background Sub" tab visible, positioned between Sensitivity and Settings
- [ ] Browse buttons open `.npz` file dialogs
- [ ] Run with missing path → `QMessageBox.critical` appears
- [ ] Stats label, replot, save buttons enable after successful run
- [ ] Uncheck "Auto" on a vrange row → min/max spinboxes enable
- [ ] Click Replot → embedded 1×3 figure updates
- [ ] Save Fig → PNG written to save_base_path/subfolder
- [ ] Save Data → .npz written with expected keys

---

## How to resume

In a new session, tell Claude:

> "Resume implementing the background subtraction tab. Tasks 1–3 are complete (commits a844a8f, 29173dd, 1fc581f). Tasks 4–6 remain. Full details in `docs/plans/2026-03-05-bg-subtraction-tab-resume.md`. Use subagent-driven development."
