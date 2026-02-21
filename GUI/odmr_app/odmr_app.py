"""
ODMR App Entry Point.

Run standalone: python odmr_app.py
"""

import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).parent))              # odmr_app/ root
sys.path.insert(0, str(Path(__file__).parent.parent))       # GUI/ root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))  # project root

from odmr_main_window import ODMRMainWindow
from state.odmr_state import ODMRAppState


def main(shared_state=None):
    """Launch the ODMR app. Returns window instance."""
    odmr_state = ODMRAppState(shared_state=shared_state)
    window = ODMRMainWindow(odmr_state=odmr_state, shared_state=shared_state)
    window.setGeometry(100, 50, 1600, 1000)
    window.show()
    return window


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    win = main()
    sys.exit(app.exec())
