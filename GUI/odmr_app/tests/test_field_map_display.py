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
