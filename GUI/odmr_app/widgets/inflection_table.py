"""
InflectionTableWidget — Displays and edits the 8 ODMR inflection points.

Columns: #, Freq (GHz) [editable], Slope (GHz⁻¹), Use?, Parity, Role
Handles: preset save/load (JSON), point-file export/import (JSON).

The widget supports two selection modes:
1. Interactive: user checks rows and sets parity via table controls.
2. Preset-driven: apply_preset() stores the full indices/parities list
   (including reference-marker 0s) and returns them verbatim from
   get_selection(), preserving the format expected by
   format_multi_point_frequencies().
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

    Signals
    -------
    selection_changed : emitted whenever the user changes a checkbox or parity,
        or when a preset is applied.

    Notes
    -----
    When a preset is applied via ``apply_preset()``, the indices/parities
    stored in the preset (including reference-marker ``0`` entries) are
    cached and returned verbatim by ``get_selection()``.  This preserves
    the format expected by ``format_multi_point_frequencies()``.

    When the user interacts directly with the table controls (no preset
    applied or after ``clear_preset()``), ``get_selection()`` builds the
    indices/parities list from the checked rows only (no 0-markers).
    """

    selection_changed = Signal()

    N_ROWS = 8
    COL_IDX    = 0
    COL_FREQ   = 1
    COL_SLOPE  = 2
    COL_USE    = 3
    COL_PARITY = 4
    COL_ROLE   = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._inflection_data = None   # dict from sweep result
        # Preset-mode cache: when set, get_selection() returns these directly.
        self._preset_indices = None    # list[int] | None
        self._preset_parities = None   # list[int] | None
        self._init_ui()

    # ------------------------------------------------------------------
    # Private helpers — UI construction
    # ------------------------------------------------------------------

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._table = QTableWidget(self.N_ROWS, 6, self)
        self._table.setHorizontalHeaderLabels(
            ["#", "Freq (GHz)", "Slope (GHz\u207b\u00b9)", "Use?", "Parity", "Role"])
        self._table.setSelectionMode(QAbstractItemView.NoSelection)
        self._table.setEditTriggers(QAbstractItemView.DoubleClicked |
                                    QAbstractItemView.EditKeyPressed)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setAlternatingRowColors(True)

        # Pre-populate rows with empty placeholders
        for row in range(self.N_ROWS):
            self._table.setItem(row, self.COL_IDX,
                                self._make_readonly_item(str(row + 1)))
            self._table.setItem(row, self.COL_FREQ,
                                QTableWidgetItem("\u2014"))
            self._table.setItem(row, self.COL_SLOPE,
                                self._make_readonly_item("\u2014"))
            # Checkbox cell
            chk_widget = self._make_checkbox_cell(row)
            self._table.setCellWidget(row, self.COL_USE, chk_widget)
            # Parity dropdown
            combo = self._make_parity_combo(row)
            self._table.setCellWidget(row, self.COL_PARITY, combo)
            self._table.setItem(row, self.COL_ROLE,
                                self._make_readonly_item("\u2014"))

        layout.addWidget(self._table)

    def _make_readonly_item(self, text: str) -> QTableWidgetItem:
        """Return a non-editable QTableWidgetItem."""
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        return item

    def _make_checkbox_cell(self, row: int) -> QWidget:
        """Return a centred checkbox wrapped in a container widget."""
        container = QWidget()
        hl = QHBoxLayout(container)
        hl.setContentsMargins(4, 0, 4, 0)
        hl.setAlignment(Qt.AlignCenter)
        chk = QCheckBox()
        chk.stateChanged.connect(lambda _state, r=row: self._on_selection_changed(r))
        hl.addWidget(chk)
        return container

    def _make_parity_combo(self, row: int) -> QComboBox:
        """Return a parity QComboBox defaulting to 'reference'."""
        combo = QComboBox()
        combo.addItems(PARITY_OPTIONS)
        combo.setCurrentIndex(2)  # default: 0 (reference)
        combo.currentIndexChanged.connect(lambda _idx, r=row: self._on_selection_changed(r))
        return combo

    def _on_selection_changed(self, row: int):
        """Called when any interactive control changes; clears preset cache."""
        self._preset_indices = None
        self._preset_parities = None
        self._update_role_label(row)
        self.selection_changed.emit()

    def _update_role_label(self, row: int):
        """Update the Role column text for the given row."""
        chk = self._get_checkbox(row)
        combo = self._table.cellWidget(row, self.COL_PARITY)
        if not chk.isChecked():
            role = "\u2014"
        else:
            parity = PARITY_VALUES[combo.currentIndex()]
            role = "Signal" if parity != 0 else "Reference"
        item = self._table.item(row, self.COL_ROLE)
        if item:
            item.setText(role)

    def _get_checkbox(self, row: int) -> QCheckBox:
        """Return the QCheckBox inside the Use? cell for the given row."""
        container = self._table.cellWidget(row, self.COL_USE)
        return container.layout().itemAt(0).widget()

    # ------------------------------------------------------------------
    # Public API — data population
    # ------------------------------------------------------------------

    def row_count(self) -> int:
        """Return the number of rows (always 8)."""
        return self.N_ROWS

    def populate_from_sweep_result(self, result: dict):
        """
        Fill table from a sweep-result dict.

        Parameters
        ----------
        result : dict
            Expected keys: ``inflection_points`` (array, length 8),
            ``inflection_slopes`` (array, length 8),
            ``inflection_contrasts`` (array, length 8).
        """
        self._inflection_data = result
        pts = result["inflection_points"]
        slopes = result["inflection_slopes"]

        for row in range(self.N_ROWS):
            freq = float(pts[row]) if row < len(pts) else 0.0
            slope = float(slopes[row]) if row < len(slopes) else 0.0
            freq_item = QTableWidgetItem(f"{freq:.6f}")
            self._table.setItem(row, self.COL_FREQ, freq_item)
            self._table.setItem(row, self.COL_SLOPE,
                                self._make_readonly_item(f"{slope:+.4f}"))
            self._update_role_label(row)

    def get_freq(self, row: int) -> float:
        """Return the frequency value (GHz) for a given row."""
        item = self._table.item(row, self.COL_FREQ)
        try:
            return float(item.text())
        except (ValueError, AttributeError):
            return 0.0

    def set_freq(self, row: int, freq: float):
        """Set the frequency value (GHz) for a given row."""
        item = self._table.item(row, self.COL_FREQ)
        if item is None:
            item = QTableWidgetItem()
            self._table.setItem(row, self.COL_FREQ, item)
        item.setText(f"{freq:.6f}")

    # ------------------------------------------------------------------
    # Public API — selection
    # ------------------------------------------------------------------

    def get_selection(self) -> dict:
        """
        Return current selection as a dict for use with
        ``format_multi_point_frequencies``.

        If a preset was applied (and no interactive changes made since),
        the preset's raw ``selected_indices`` and ``selected_parities``
        lists (including reference-marker ``0`` entries) are returned
        verbatim.

        Otherwise, the selection is built from the checked table rows.

        Returns
        -------
        dict with keys:
            ``indices`` : list[int]
            ``parities`` : list[int]
            ``freq_list`` : list[float]
            ``slope_list`` : list[float]
            ``baseline_list`` : list[float]
        """
        if self._preset_indices is not None:
            # Preset mode: return cached indices/parities as-is.
            freq_list, slope_list, baseline_list = [], [], []
            for idx in self._preset_indices:
                if idx == 0:
                    # Reference marker — use a neutral placeholder.
                    freq_list.append(0.0)
                    slope_list.append(0.0)
                    baseline_list.append(1.0)
                else:
                    row = idx - 1
                    freq_list.append(self.get_freq(row))
                    if (self._inflection_data and
                            row < len(self._inflection_data["inflection_slopes"])):
                        slope_list.append(
                            float(self._inflection_data["inflection_slopes"][row]))
                        baseline_list.append(
                            float(self._inflection_data["inflection_contrasts"][row]))
                    else:
                        slope_list.append(0.0)
                        baseline_list.append(1.0)
            return {
                "indices": list(self._preset_indices),
                "parities": list(self._preset_parities),
                "freq_list": freq_list,
                "slope_list": slope_list,
                "baseline_list": baseline_list,
            }

        # Interactive mode: build from checked rows.
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
                if (self._inflection_data and
                        row < len(self._inflection_data["inflection_slopes"])):
                    slope_list.append(
                        float(self._inflection_data["inflection_slopes"][row]))
                    baseline_list.append(
                        float(self._inflection_data["inflection_contrasts"][row]))
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

    def clear_preset(self):
        """
        Clear the preset cache so that ``get_selection()`` reverts to
        reading from the interactive table controls.
        """
        self._preset_indices = None
        self._preset_parities = None

    # ------------------------------------------------------------------
    # Public API — preset apply
    # ------------------------------------------------------------------

    def apply_preset(self, preset: dict):
        """
        Apply a preset dict to the table.

        Stores the preset's ``selected_indices`` and ``selected_parities``
        verbatim (including reference-marker ``0`` entries) so that
        ``get_selection()`` can return them in the format expected by
        ``format_multi_point_frequencies()``.

        Also updates the visual checkbox/parity state for non-zero indices.

        Parameters
        ----------
        preset : dict
            Keys: ``selected_indices`` (list[int]),
            ``selected_parities`` (list[int]),
            ``ref_freq_ghz`` (float, optional).
        """
        indices = preset.get("selected_indices", [])
        parities = preset.get("selected_parities", [])

        # Cache raw preset lists (preserving 0-markers).
        self._preset_indices = list(indices)
        self._preset_parities = list(parities)

        # Reset all table rows visually.
        for row in range(self.N_ROWS):
            # Disconnect temporarily to avoid clearing preset cache.
            chk = self._get_checkbox(row)
            chk.blockSignals(True)
            chk.setChecked(False)
            chk.blockSignals(False)
            combo = self._table.cellWidget(row, self.COL_PARITY)
            combo.blockSignals(True)
            combo.setCurrentIndex(2)  # default: reference
            combo.blockSignals(False)
            self._update_role_label(row)

        # Apply non-zero selected rows visually.
        for idx, parity in zip(indices, parities):
            if idx == 0:
                continue  # reference-placement marker, no table row to update
            row = idx - 1
            if 0 <= row < self.N_ROWS:
                chk = self._get_checkbox(row)
                chk.blockSignals(True)
                chk.setChecked(True)
                chk.blockSignals(False)
                combo = self._table.cellWidget(row, self.COL_PARITY)
                combo.blockSignals(True)
                combo_idx = (PARITY_VALUES.index(parity)
                             if parity in PARITY_VALUES else 2)
                combo.setCurrentIndex(combo_idx)
                combo.blockSignals(False)
                self._update_role_label(row)

        self.selection_changed.emit()

    # ------------------------------------------------------------------
    # Public API — preset file I/O
    # ------------------------------------------------------------------

    def save_preset_to_file(self, preset: dict, path: Path):
        """
        Save a preset dict to a JSON file.

        Parameters
        ----------
        preset : dict
            Preset data (e.g. from ``get_current_as_preset()``).
        path : Path
            Destination file path.
        """
        with open(path, "w") as f:
            json.dump(preset, f, indent=2)

    def load_preset_from_file(self, path: Path) -> dict:
        """
        Load a preset dict from a JSON file.

        Parameters
        ----------
        path : Path
            Source file path.

        Returns
        -------
        dict
            The loaded preset.
        """
        with open(path) as f:
            return json.load(f)

    def get_current_as_preset(self, name: str, description: str = "",
                              ref_freq_ghz: float = 1.0) -> dict:
        """
        Package current table state as a preset dict.

        Parameters
        ----------
        name : str
            Preset name.
        description : str
            Optional human-readable description.
        ref_freq_ghz : float
            Reference frequency in GHz.

        Returns
        -------
        dict
        """
        sel = self.get_selection()
        return {
            "name": name,
            "description": description,
            "selected_indices": sel["indices"],
            "selected_parities": sel["parities"],
            "ref_freq_ghz": ref_freq_ghz,
        }

    # ------------------------------------------------------------------
    # Public API — point file I/O
    # ------------------------------------------------------------------

    def save_points_to_file(self, path: Path):
        """
        Export full 8-point inflection data to a JSON file for session restore.

        Parameters
        ----------
        path : Path
            Destination file path.

        Raises
        ------
        RuntimeError
            If no inflection data has been loaded yet.
        """
        if self._inflection_data is None:
            raise RuntimeError(
                "No inflection data loaded. Run sweep first.")
        data = {
            "inflection_points": (
                self._inflection_data["inflection_points"].tolist()),
            "inflection_slopes": (
                self._inflection_data["inflection_slopes"].tolist()),
            "inflection_contrasts": (
                self._inflection_data["inflection_contrasts"].tolist()),
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def load_points_from_file(self, path: Path):
        """
        Load inflection points from a JSON file and repopulate the table.

        Parameters
        ----------
        path : Path
            Source file path (created by ``save_points_to_file()``).
        """
        with open(path) as f:
            data = json.load(f)
        result = {
            "inflection_points": np.array(data["inflection_points"]),
            "inflection_slopes": np.array(data["inflection_slopes"]),
            "inflection_contrasts": np.array(data["inflection_contrasts"]),
        }
        self.populate_from_sweep_result(result)
