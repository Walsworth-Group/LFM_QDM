# Background Subtraction Tab — Design

**Date:** 2026-03-04
**Feature:** Add a "Background Sub" tab to the ODMR GUI app (`odmr_app.py`)
**Notebook reference:** Cells 43–46 of `Camera ODMR-new.ipynb`

---

## Summary

Add a new top-level tab to the CW ODMR Magnetometry GUI that wraps the
`qdm.analyze_background_subtraction()` workflow. Users browse to two saved
`.npz` field-map files (background = no sample, sample = with sample), set
a Gaussian sigma, run the subtraction, view the 1×3 comparison figure
embedded in the tab, optionally adjust color ranges and replot, and save
results.

---

## Architecture

Follows the same pattern as every other tab in the app:

| New file | Role |
|---|---|
| `GUI/odmr_app/workers/bg_subtraction_worker.py` | `BgSubtractionWorker(QThread)` — runs `qdm.analyze_background_subtraction()` off the main thread; emits `completed(dict)` or `failed(str)` |
| `GUI/odmr_app/tabs/bg_subtraction_tab.py` | `BgSubtractionTabHandler` — wires UI, spawns worker, embeds matplotlib FigureCanvas |
| `GUI/odmr_app/ui/ui_odmr_bg_subtraction_tab.py` | Python-only UI definition (no `.ui` file needed) |

Modified files:
- `GUI/odmr_app/state/odmr_state.py` — new bg-sub properties and `bg_sub_completed` signal
- `GUI/odmr_app/ui/ui_odmr_app_main.py` — add `bg_sub_tab` placeholder to `QTabWidget`
- `GUI/odmr_app/odmr_main_window.py` — instantiate `BgSubtractionTabHandler`

---

## UI Layout

```
┌─ Background Subtraction tab ──────────────────────────────────────────┐
│ ┌─ Files ────────────────────────────────────────────────────────────┐ │
│ │ Background (.npz): [____________________________] [Browse]         │ │
│ │ Sample (.npz):     [____________________________] [Browse]         │ │
│ └────────────────────────────────────────────────────────────────────┘ │
│ ┌─ Parameters ───────────────────────────────────────────────────────┐ │
│ │ Gaussian sigma: [7.0] px          [Run Background Subtraction]     │ │
│ └────────────────────────────────────────────────────────────────────┘ │
│ ┌─ Color Range (Gauss) ──────────────────────────────────────────────┐ │
│ │ Raw:        [✓ Auto]  min [_____]  max [_____]                     │ │
│ │ Denoised:   [✓ Auto]  min [_____]  max [_____]                     │ │
│ │ Processed:  [✓ Auto]  min [_____]  max [_____]                     │ │
│ │ Subtracted: [✓ Auto]  min [_____]  max [_____]    [Replot]         │ │
│ └────────────────────────────────────────────────────────────────────┘ │
│  Stats: Mean: — G   Std: — G   Range: [—, —] G                        │
│ ┌─ Figure canvas (1×3: bg_processed | sample_processed | subtracted) ┐ │
│ │                        (stretches to fill)                         │ │
│ └────────────────────────────────────────────────────────────────────┘ │
│ ┌─ Save ─────────────────────────────────────────────────────────────┐ │
│ │ Prefix: [________]   [Save Fig]  [Save Data]                       │ │
│ └────────────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────┘
```

- Auto checkbox ticked → min/max spinboxes disabled (auto-scaling)
- Auto checkbox unticked → min/max spinboxes enabled; Replot re-renders canvas
- Replot and Save buttons disabled until a successful run has completed

---

## State Properties (odmr_state.py)

```python
bg_sub_bg_file: str = ""            # path to background .npz
bg_sub_sample_file: str = ""        # path to sample .npz
bg_sub_gaussian_sigma: float = 7.0
bg_sub_result: dict | None = None   # last result dict from analyze_background_subtraction
bg_sub_vrange_raw: tuple | None = None        # (min, max) in Gauss, or None = auto
bg_sub_vrange_denoised: tuple | None = None
bg_sub_vrange_processed: tuple | None = None
bg_sub_vrange_subtracted: tuple | None = None
bg_sub_completed = Signal(dict)     # emitted when tab updates state with a new result
```

---

## Data Flow

1. User browses → file paths stored in state
2. **Run** → `BgSubtractionWorker` calls:
   ```python
   qdm.analyze_background_subtraction(
       bg_file=..., sample_file=..., gaussian_sigma=...,
       show_plot=False, save_fig=False, save_data=False
   )
   ```
   Emits `completed(result_dict)` on success, `failed(str)` on error.
3. Tab handler receives result:
   - Stores in `state.bg_sub_result`
   - Renders `result['figure_comparison']` (1×3) into the embedded `FigureCanvas`
   - Calls `result['figure_analysis'].show()` to pop up the 2×3 detail figure
   - Updates stats label from `result['subtracted']`
   - Enables Replot / Save buttons
4. **Replot** → reads vrange spinboxes → calls:
   ```python
   qdm.replot_background_subtraction(bg_sub_result, vrange_raw=..., ...)
   ```
   Re-renders the returned comparison figure into the same canvas.
5. **Save Fig** → saves `figure_comparison` as PNG via `state.build_save_filename()`
6. **Save Data** → saves `subtracted`, `bg_processed`, `sample_processed`,
   `gaussian_sigma`, `bg_file`, `sample_file` as `.npz`

---

## Error Handling

| Condition | Behaviour |
|---|---|
| Either file path empty or missing | `QMessageBox.critical` before starting worker |
| `.npz` missing `field_map_gauss_raw` key | Worker catches `KeyError`, emits `failed(str)` → error dialog |
| Worker already running | Run button disabled while active |
| Replot / Save with no result | Buttons disabled until result available |
| Color range min >= max | Min spinbox clamped to max - 0.001 on value change |

---

## Display

- **Embedded**: `figure_comparison` (1×3: bg_processed, sample_processed, subtracted)
  rendered into a `matplotlib.backends.backend_qtagg.FigureCanvasQTAgg` that
  stretches to fill the available space in the tab.
- **Popup**: `figure_analysis` (2×3: raw/denoised/processed for BG and sample)
  opened via `fig.show()` as a separate matplotlib window — better for the
  larger multi-panel figure.
