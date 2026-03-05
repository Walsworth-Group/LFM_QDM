"""
SG384Worker — Background thread for SRS SG384 MW generator.

Handles:
- Idle frequency polling (backs off when sg384_lock is held by sweep/mag workers)
- Manual frequency/amplitude commands from the UI command queue

During ODMR sweeps and magnetometry, the sweep/magnetometry workers hold
state.sg384_lock and call state.sg384_controller directly for zero latency.
"""

import sys
import time
from pathlib import Path
from PySide6.QtCore import QThread, Signal, QCoreApplication

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


class SG384Worker(QThread):
    """
    Worker thread for SRS SG384 signal generator idle monitoring and manual control.

    Does NOT own the VISA connection — that is managed externally and stored
    in state.sg384_controller. This worker only polls and accepts commands.

    Signals
    -------
    connected : dict
        Emitted once on startup with ``{'address': str, 'freq_ghz': float}``.
    connection_failed : str
        Emitted if the controller is not set or raises on startup.
    frequency_polled : float
        Emitted each successful idle frequency poll (GHz).
    parameter_set_success : (str, object)
        Emitted after a queued command succeeds: ``('set_frequency', 2.87)``.
    parameter_set_failed : (str, str)
        Emitted after a queued command fails: ``('set_frequency', error_msg)``.
    error : str
        Emitted on non-fatal polling errors.
    """

    connected = Signal(dict)                      # {'address': str, 'freq_ghz': float}
    connection_failed = Signal(str)
    frequency_polled = Signal(float)              # GHz — for internal use + RF panel
    parameter_set_success = Signal(str, object)   # ('set_frequency', 2.87)
    parameter_set_failed = Signal(str, str)       # ('set_frequency', error_msg)
    error = Signal(str)

    def __init__(self, state, parent=None):
        """
        Initialise the worker.

        Parameters
        ----------
        state : ODMRAppState
            Shared application state.  Must have ``sg384_controller``,
            ``sg384_lock``, ``rf_address``, ``perf_rf_poll_interval_s``, and
            ``perf_worker_loop_sleep_s`` attributes.
        parent : QObject, optional
            Qt parent object.
        """
        super().__init__(parent)
        self.state = state
        self._is_running = False
        self._command_queue = []

    def run(self):
        """Main worker loop. Polls frequency and processes commands."""
        self._is_running = True

        # Announce connected (controller already open)
        try:
            ctrl = self.state.sg384_controller
            if ctrl is None:
                self.connection_failed.emit("sg384_controller not set in state")
                return
            initial_freq = self._safe_get_frequency()
            initial_amp = self._safe_get_amplitude()
            self.connected.emit({
                "address": self.state.rf_address,
                "freq_ghz": initial_freq or 0.0,
                "amp_dbm": initial_amp,
            })
        except Exception as e:
            self.connection_failed.emit(str(e))
            return

        last_poll = 0.0

        while self._is_running:
            # Process any queued commands first (acquire lock)
            if self._command_queue:
                cmd, args = self._command_queue.pop(0)
                self._execute_command(cmd, args)

            # Poll frequency on interval — skip if lock unavailable
            now = time.monotonic()
            if now - last_poll >= self.state.perf_rf_poll_interval_s:
                freq = self._safe_get_frequency()
                if freq is not None:
                    self.frequency_polled.emit(freq)
                last_poll = now

            time.sleep(self.state.perf_worker_loop_sleep_s)

    def stop(self):
        """Signal the worker loop to exit cleanly."""
        self._is_running = False

    def wait(self, msecs: int = -1) -> bool:
        """
        Wait for the worker thread to finish, then flush the Qt event queue.

        Overrides ``QThread.wait()`` to call
        ``QCoreApplication.processEvents()`` after the thread exits.  This
        ensures that any Qt signals emitted from the worker thread (which are
        delivered via Qt's queued-connection mechanism into the calling
        thread's event queue) are processed before control returns to the
        caller.  Without this flush, tests that check signal receipts
        immediately after ``wait()`` would see empty lists.

        Parameters
        ----------
        msecs : int, optional
            Timeout in milliseconds.  ``-1`` (default) means wait forever.
            Passed directly to ``QThread.wait()``.

        Returns
        -------
        bool
            ``True`` if the thread finished within the timeout,
            ``False`` if the timeout expired.
        """
        if msecs == -1:
            result = super().wait()
        else:
            result = super().wait(msecs)
        QCoreApplication.processEvents()
        return result

    def queue_command(self, command: str, *args):
        """
        Thread-safe: enqueue a command for execution in the worker thread.

        Commands are processed in FIFO order on the next iteration of the
        worker loop.  Python's GIL ensures list.append/pop(0) are safe for
        single-producer/single-consumer usage without an explicit lock.

        Parameters
        ----------
        command : str
            Command name.  Supported values: ``'set_frequency'``,
            ``'set_amplitude'``.
        *args :
            Arguments for the command.  For ``'set_frequency'``, pass the
            frequency in GHz.  For ``'set_amplitude'``, pass the level in dBm.
        """
        self._command_queue.append((command, args))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _safe_get_frequency(self):
        """
        Poll the RF generator frequency only if the lock is immediately available.

        Returns the frequency in GHz, or ``None`` if the lock is held (e.g.
        by a sweep or magnetometry worker) or if an error occurs.

        Returns
        -------
        float or None
        """
        acquired = self.state.sg384_lock.acquire(blocking=False)
        if not acquired:
            return None  # sweep/mag worker holds the lock — skip this poll
        try:
            return self.state.sg384_controller.get_frequency()  # GHz assumed
        except Exception as e:
            self.error.emit(f"Frequency poll error: {e}")
            return None
        finally:
            self.state.sg384_lock.release()

    def _safe_get_amplitude(self):
        """
        Query the RF generator amplitude only if the lock is immediately available.

        Returns the amplitude in dBm, or ``None`` if the lock is held or an
        error occurs.

        Returns
        -------
        float or None
        """
        acquired = self.state.sg384_lock.acquire(blocking=False)
        if not acquired:
            return None
        try:
            return self.state.sg384_controller.get_amplitude()
        except Exception as e:
            self.error.emit(f"Amplitude query error: {e}")
            return None
        finally:
            self.state.sg384_lock.release()

    def _execute_command(self, command: str, args: tuple):
        """
        Execute a hardware command, acquiring the lock exclusively.

        Emits ``parameter_set_success`` on success or ``parameter_set_failed``
        on error.

        Parameters
        ----------
        command : str
            Command name (``'set_frequency'`` or ``'set_amplitude'``).
        args : tuple
            Positional arguments for the command.
        """
        try:
            with self.state.sg384_lock:
                ctrl = self.state.sg384_controller
                if command == 'set_frequency':
                    freq_ghz = args[0]
                    ctrl.set_frequency(freq_ghz, 'GHz')
                    # Emit polled freq immediately so the display updates without
                    # waiting for the next scheduled poll cycle.
                    self.frequency_polled.emit(freq_ghz)
                    self.parameter_set_success.emit('set_frequency', freq_ghz)
                elif command == 'set_amplitude':
                    dbm = args[0]
                    ctrl.set_amplitude(dbm)
                    self.parameter_set_success.emit('set_amplitude', dbm)
                else:
                    self.error.emit(f"Unknown command: {command}")
        except Exception as e:
            self.parameter_set_failed.emit(command, str(e))
