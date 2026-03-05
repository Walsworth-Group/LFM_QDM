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