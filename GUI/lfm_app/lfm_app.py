"""
LFM App Entry Point.

Run standalone::

    python lfm_app.py

Or import for use with the launcher::

    from lfm_app.lfm_app import main as lfm_main
    window = lfm_main(shared_state=experiment_state)
"""

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup — allow imports from lfm_app/, GUI/, and project root
# ---------------------------------------------------------------------------
_LFM_APP_ROOT = Path(__file__).parent                # .../GUI/lfm_app/
_GUI_ROOT = Path(__file__).parent.parent              # .../GUI/
_PROJECT_ROOT = Path(__file__).parent.parent.parent   # .../LFM software/

for _p in [str(_PROJECT_ROOT), str(_LFM_APP_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PySide6.QtWidgets import QApplication

from lfm_main_window import LFMMainWindow
from state.lfm_state import LFMAppState


def main(shared_state=None):
    """
    Create and show the LFM main window.

    Parameters
    ----------
    shared_state : object, optional
        ExperimentState for cross-app communication.

    Returns
    -------
    LFMMainWindow
        The main window instance.
    """
    lfm_state = LFMAppState(shared_state=shared_state)
    window = LFMMainWindow(lfm_state=lfm_state, shared_state=shared_state)
    window.show()
    return window


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    win = main()
    sys.exit(app.exec())
