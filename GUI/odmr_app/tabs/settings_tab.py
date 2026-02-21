"""
Settings tab handler — wires settings_tab.ui widgets to ODMRAppState.

This module provides ``SettingsTabHandler``, which is instantiated by
``ODMRMainWindow`` to wire the Settings tab UI to the central application
state object.
"""

import sys
from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QWidget

# Reach GUI/ root so that ui.* package imports work
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from ui.ui_odmr_settings_tab import Ui_settings_tab_content


class SettingsTabHandler:
    """
    Handler for the Settings tab.

    Instantiated by ODMRMainWindow to wire the settings tab UI to state.

    Parameters
    ----------
    tab_widget : QWidget
        The bare QWidget that represents the Settings tab in the main tab
        widget.  ``Ui_settings_tab_content.setupUi()`` will populate it.
    state : ODMRAppState
        Central application state object.
    """

    def __init__(self, tab_widget: QWidget, state):
        self.state = state
        self.ui_settings = Ui_settings_tab_content()
        self.ui_settings.setupUi(tab_widget)
        # perf_flush_frames_spin is vestigial: flush_buffer() is called
        # unconditionally in qdm_gen, so this setting has no effect.
        self.ui_settings.perf_flush_frames_spin.hide()
        self.ui_settings.label5.hide()
        self._connect_widgets()
        self._sync_from_state()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect_widgets(self):
        """Connect each settings widget to the corresponding state attribute."""
        s = self.state
        ui = self.ui_settings

        # Instrument settings
        ui.settings_sg384_address_edit.textChanged.connect(
            lambda t: setattr(s, 'rf_address', t)
        )
        ui.settings_camera_serial_edit.textChanged.connect(
            lambda t: setattr(s, 'odmr_camera_serial', t)
        )
        ui.settings_sg384_amplitude_spin.valueChanged.connect(
            lambda v: setattr(s, 'rf_amplitude_dbm', v)
        )

        # Performance / timing spinboxes
        perf_bindings = [
            (ui.perf_rf_poll_spin,    'perf_rf_poll_interval_s'),
            (ui.perf_settling_spin,   'perf_mw_settling_time_s'),
            (ui.perf_n_frames_spin,   'perf_n_frames_per_point'),
            (ui.perf_loop_sleep_spin, 'perf_worker_loop_sleep_s'),
            (ui.perf_emit_every_spin, 'perf_sweep_emit_every_n'),
            (ui.perf_live_avg_spin,   'perf_live_avg_update_interval_samples'),
            (ui.perf_autosave_spin,   'perf_autosave_interval_samples'),
        ]
        for widget, attr in perf_bindings:
            widget.valueChanged.connect(lambda v, a=attr: setattr(s, a, v))

        # Reset button
        ui.settings_reset_btn.clicked.connect(self._on_reset)

    def _sync_from_state(self):
        """Push current state values into the settings widgets (no signal loops)."""
        s = self.state
        ui = self.ui_settings

        # Instrument settings — block signals while syncing to avoid
        # writing the same value back to state and triggering extra updates
        ui.settings_sg384_address_edit.blockSignals(True)
        ui.settings_sg384_address_edit.setText(str(s.rf_address))
        ui.settings_sg384_address_edit.blockSignals(False)

        ui.settings_camera_serial_edit.blockSignals(True)
        ui.settings_camera_serial_edit.setText(str(s.odmr_camera_serial))
        ui.settings_camera_serial_edit.blockSignals(False)

        ui.settings_sg384_amplitude_spin.blockSignals(True)
        ui.settings_sg384_amplitude_spin.setValue(s.rf_amplitude_dbm)
        ui.settings_sg384_amplitude_spin.blockSignals(False)

        # Performance spinboxes
        _perf_sync = [
            (ui.perf_rf_poll_spin,    s.perf_rf_poll_interval_s),
            (ui.perf_settling_spin,   s.perf_mw_settling_time_s),
            (ui.perf_n_frames_spin,   s.perf_n_frames_per_point),
            (ui.perf_loop_sleep_spin, s.perf_worker_loop_sleep_s),
            (ui.perf_emit_every_spin, s.perf_sweep_emit_every_n),
            (ui.perf_live_avg_spin,   s.perf_live_avg_update_interval_samples),
            (ui.perf_autosave_spin,   s.perf_autosave_interval_samples),
        ]
        for widget, value in _perf_sync:
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)

    @Slot()
    def _on_reset(self):
        """Reset all perf_* state attributes to factory defaults."""
        default = type(self.state)()
        for key in self.state._CONFIG_KEYS:
            if key.startswith('perf_'):
                setattr(self.state, key, getattr(default, key))
        self._sync_from_state()
