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
