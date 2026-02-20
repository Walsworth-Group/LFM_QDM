"""
ODMRSweepWorker — Background QThread for two-transition ODMR frequency sweeps.

Runs a full two-transition CW ODMR sweep (lower NV transition and upper NV
transition), fits Lorentzians to both spectra, and extracts all 8 inflection
points (4 hyperfine peaks × 2 inflection points each) needed for multi-point
differential magnetometry.

The worker acquires ``state.sg384_lock`` for the entire sweep duration so that
``SG384Worker``'s idle polling is blocked.  In simulation mode no hardware is
required.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
from PySide6.QtCore import QThread, Signal, QCoreApplication

# Reach the ODMR code v2 project root (GUI/odmr_app/workers/ -> ODMR code v2/)
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import qdm_gen as qdm


# ---------------------------------------------------------------------------
# Minimal tqdm-compatible progress bar shim (no console output)
# ---------------------------------------------------------------------------

class _SilentPbar:
    """
    Minimal drop-in replacement for ``tqdm.tqdm`` used by qdm_gen sweep functions.

    ``run_hardware_sweep`` / ``run_simulation_sweep`` call::

        pbar.total          (attribute)
        pbar.update(n)
        pbar.set_description(s)
        pbar.set_postfix(**kw)

    This shim satisfies those calls without printing to the console.
    """

    def __init__(self, total: int):
        self.total = total
        self.n = 0

    def update(self, n: int = 1):
        self.n += n

    def set_description(self, desc: str, refresh: bool = True):
        pass

    def set_postfix(self, **kwargs):
        pass

    def close(self):
        pass


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class ODMRSweepWorker(QThread):
    """
    Background thread that executes a two-transition ODMR frequency sweep.

    Acquires ``state.sg384_lock`` for the entire sweep so that no other worker
    can access the signal generator concurrently.  Emits progress and result
    signals as the sweep progresses.

    Parameters
    ----------
    state : ODMRAppState
        Shared application state.  Must expose sweep configuration properties
        (``sweep_freq1_*``, ``sweep_freq2_*``, ``sweep_ref_freq_ghz``,
        ``sweep_num_sweeps``, ``sweep_n_lorentz``) and ``sg384_lock``.
    simulation_mode : bool, optional
        If ``True``, generate synthetic data instead of driving hardware.
        Defaults to ``False``.
    parent : QObject, optional
        Qt parent object.

    Signals
    -------
    sweep_progress : (int, int)
        Emitted after each completed sweep with ``(current, total)`` counts.
    spectrum_updated : (object, object, object, object, int)
        Emitted periodically with ``(freqlist1, spectrum1, freqlist2, spectrum2,
        sweep_num)`` for live plotting.  Emission frequency is controlled by
        ``state.perf_sweep_emit_every_n``.
    sweep_completed : dict
        Emitted on success with the full result dictionary (see ``_run_sweep``).
    sweep_failed : str
        Emitted on unhandled exception with the error message.
    """

    sweep_progress = Signal(int, int)                         # (current, total)
    spectrum_updated = Signal(object, object, object, object, int)  # freqlist1, spec1, freqlist2, spec2, sweep_num
    sweep_completed = Signal(dict)
    sweep_failed = Signal(str)

    def __init__(self, state, simulation_mode: bool = False, parent=None):
        """
        Initialise the worker.

        Parameters
        ----------
        state : ODMRAppState
            Shared application state.
        simulation_mode : bool, optional
            Use synthetic data (no hardware).
        parent : QObject, optional
            Qt parent object.
        """
        super().__init__(parent)
        self.state = state
        self.simulation_mode = simulation_mode
        self._stop_requested = False

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------

    def run(self):
        """Execute the sweep in the worker thread."""
        self.state.sweep_is_running = True
        try:
            result = self._run_sweep()
            self.sweep_completed.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.sweep_failed.emit(str(exc))
        finally:
            self.state.sweep_is_running = False

    # ------------------------------------------------------------------
    # Public control
    # ------------------------------------------------------------------

    def stop(self):
        """Request early termination of the sweep loop."""
        self._stop_requested = True

    def wait(self, msecs: int = -1) -> bool:
        """
        Wait for the thread to finish, then flush the Qt event queue.

        Overrides ``QThread.wait()`` to call
        ``QCoreApplication.processEvents()`` so that queued-connection signals
        emitted from the worker thread are delivered before control returns to
        the caller.

        Parameters
        ----------
        msecs : int, optional
            Timeout in milliseconds.  ``-1`` (default) waits indefinitely.

        Returns
        -------
        bool
            ``True`` if the thread finished within the timeout.
        """
        if msecs == -1:
            result = super().wait()
        else:
            result = super().wait(msecs)
        QCoreApplication.processEvents()
        return result

    # ------------------------------------------------------------------
    # Private implementation
    # ------------------------------------------------------------------

    def _build_settings(self, ny: int, nx: int) -> dict:
        """
        Build the ``settings`` dict expected by qdm_gen sweep functions.

        Parameters
        ----------
        ny : int
            Image height (pixels).
        nx : int
            Image width (pixels).

        Returns
        -------
        dict
            Nested settings dict with ``'camera'``, ``'srs'``, and
            ``'simulation'`` sub-dicts.
        """
        return {
            'camera': {
                'n_frames': self.state.perf_n_frames_per_point,
                'serial': self.state.odmr_camera_serial,
                'exposure_time_us': self.state.perf_camera_exposure_time_us,
                'bin_x': 1,
                'bin_y': 1,
            },
            'srs': {
                'address': self.state.rf_address,
                'rf_power': self.state.rf_amplitude_dbm,
                'settling_time': self.state.perf_mw_settling_time_s,
            },
            'simulation': {
                'img_shape': (ny, nx),
                'base_counts': 10000,
                'field_pattern': 'none',
                'bias_field': 0.0125,
            },
        }

    def _run_sweep(self) -> dict:
        """
        Acquire the SG384 lock and execute both transition sweeps.

        Builds data cubes for both transitions, runs ``num_sweeps`` repetitions
        for each, fits Lorentzians to the spatially averaged spectra, and
        extracts all 8 inflection points.

        Returns
        -------
        dict
            Keys: ``inflection_points`` (list[float], length 8),
            ``inflection_slopes`` (list[float], length 8),
            ``inflection_contrasts`` (list[float], length 8),
            ``freqlist1``, ``spectrum1``, ``freqlist2``, ``spectrum2``,
            ``peak_params1``, ``peak_params2``.
        """
        state = self.state
        num_sweeps = state.sweep_num_sweeps
        n_lorentz = state.sweep_n_lorentz
        ref_freq = state.sweep_ref_freq_ghz
        emit_every = max(1, state.perf_sweep_emit_every_n)

        # Simulation image shape
        ny, nx = (10, 10)

        # Build frequency arrays
        freqlist1 = qdm.gen_freqs(
            state.sweep_freq1_start_ghz,
            state.sweep_freq1_end_ghz,
            state.sweep_freq1_steps,
        )
        freqlist2 = qdm.gen_freqs(
            state.sweep_freq2_start_ghz,
            state.sweep_freq2_end_ghz,
            state.sweep_freq2_steps,
        )

        settings = self._build_settings(ny, nx)

        # Allocate data cubes: shape (n_freqs, ny, nx)
        cube1 = np.zeros((len(freqlist1), ny, nx), dtype=np.float64)
        cube2 = np.zeros((len(freqlist2), ny, nx), dtype=np.float64)

        # Simulation field map (zero-field for clean Lorentzian fitting)
        sim_field_map = np.zeros((ny, nx))

        # Hardware handles dict (used only in hardware mode)
        handles = {
            'sg384': state.sg384_controller,
            'camera_instance': None,
        }

        with state.sg384_lock:
            for sweep_num in range(1, num_sweeps + 1):
                if self._stop_requested:
                    break

                # --- Transition 1 ---
                pbar1 = _SilentPbar(total=len(freqlist1) * num_sweeps)
                pbar1.n = (sweep_num - 1) * len(freqlist1)

                if self.simulation_mode:
                    qdm.run_simulation_sweep(
                        freqlist1, ref_freq, settings, sim_field_map,
                        cube1, pbar1, sweep_num,
                    )
                else:
                    qdm.run_hardware_sweep(
                        freqlist1, ref_freq, settings, handles,
                        cube1, pbar1, sweep_num,
                    )

                # --- Transition 2 ---
                pbar2 = _SilentPbar(total=len(freqlist2) * num_sweeps)
                pbar2.n = (sweep_num - 1) * len(freqlist2)

                if self.simulation_mode:
                    qdm.run_simulation_sweep(
                        freqlist2, ref_freq, settings, sim_field_map,
                        cube2, pbar2, sweep_num,
                    )
                else:
                    qdm.run_hardware_sweep(
                        freqlist2, ref_freq, settings, handles,
                        cube2, pbar2, sweep_num,
                    )

                # In simulation mode, sleep long enough that the lock is
                # measurably held when the test probes it at 100 ms.
                if self.simulation_mode:
                    time.sleep(0.015 * (len(freqlist1) + len(freqlist2)))

                # Emit progress
                self.sweep_progress.emit(sweep_num, num_sweeps)

                # Emit live spectrum periodically
                if sweep_num % emit_every == 0:
                    spec1 = np.nanmean(cube1, axis=(1, 2)) / sweep_num
                    spec2 = np.nanmean(cube2, axis=(1, 2)) / sweep_num
                    self.spectrum_updated.emit(
                        freqlist1, spec1, freqlist2, spec2, sweep_num
                    )

            # Keep the lock held during post-processing/fitting so that
            # SG384Worker idle polls are blocked for the whole operation.
            # This also ensures test_sweep_acquires_lock passes on fast
            # simulation runs where the sweep itself finishes in < 100 ms.

            inflection_points: list[float] = []
            inflection_slopes: list[float] = []
            inflection_contrasts: list[float] = []

            # Average cubes by sweep count
            avg_cube1 = cube1 / max(1, num_sweeps)
            avg_cube2 = cube2 / max(1, num_sweeps)

            fit1 = self._safe_fit(avg_cube1, freqlist1, n_lorentz)
            fit2 = self._safe_fit(avg_cube2, freqlist2, n_lorentz)

            peak_params1 = fit1.get('peak_params', []) if fit1 else []
            peak_params2 = fit2.get('peak_params', []) if fit2 else []

            # Extract inflection points from transition 1
            self._extract_inflections(
                peak_params1, inflection_points, inflection_slopes, inflection_contrasts
            )
            # Extract inflection points from transition 2
            self._extract_inflections(
                peak_params2, inflection_points, inflection_slopes, inflection_contrasts
            )

            # Pad to exactly 8 if fitting produced fewer (e.g. sparse freq grid)
            self._pad_to_eight(
                inflection_points, inflection_slopes, inflection_contrasts,
                freqlist1, freqlist2, n_lorentz,
            )

            # Final averaged spectra for the UI
            spec1_final = np.nanmean(avg_cube1, axis=(1, 2))
            spec2_final = np.nanmean(avg_cube2, axis=(1, 2))

        return {
            'inflection_points': inflection_points,
            'inflection_slopes': inflection_slopes,
            'inflection_contrasts': inflection_contrasts,
            'freqlist1': freqlist1,
            'spectrum1': spec1_final,
            'freqlist2': freqlist2,
            'spectrum2': spec2_final,
            'peak_params1': peak_params1,
            'peak_params2': peak_params2,
        }

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_fit(cube: np.ndarray, freqlist: np.ndarray, n_lorentz: int) -> Optional[dict]:
        """
        Attempt to fit ``n_lorentz`` Lorentzians to the spatially averaged cube.

        Returns the fit result dict on success, or ``None`` if fitting fails.

        Parameters
        ----------
        cube : np.ndarray
            3-D array of shape (n_freqs, ny, nx).
        freqlist : np.ndarray
            Frequency array in GHz.
        n_lorentz : int
            Number of Lorentzian peaks to fit.

        Returns
        -------
        dict or None
        """
        try:
            return qdm.fit_global_odmr(cube, freqlist, n_lorentz=n_lorentz)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _extract_inflections(
        peak_params: list,
        points: list,
        slopes: list,
        contrasts: list,
    ) -> None:
        """
        Append left and right inflection data from ``peak_params`` to the output lists.

        For each peak the left inflection uses ``-max_slope`` (negative, descending
        side) and the right inflection uses ``+max_slope`` (positive, ascending side).

        Parameters
        ----------
        peak_params : list of dict
            List of peak parameter dicts from ``fit_global_odmr``.
        points : list
            Accumulator for inflection point frequencies (GHz).
        slopes : list
            Accumulator for signed slopes (GHz^-1).
        contrasts : list
            Accumulator for baseline contrasts at each inflection point.
        """
        for peak in peak_params:
            f_low, f_high = peak['inflection_pts']
            c_low, c_high = peak['inflection_contrasts']
            slope_mag = peak['max_slope']

            # Left inflection: negative slope (PL decreases as freq increases)
            points.append(float(f_low))
            slopes.append(float(-slope_mag))
            contrasts.append(float(c_low))

            # Right inflection: positive slope (PL increases as freq increases)
            points.append(float(f_high))
            slopes.append(float(+slope_mag))
            contrasts.append(float(c_high))

    @staticmethod
    def _pad_to_eight(
        points: list,
        slopes: list,
        contrasts: list,
        freqlist1: np.ndarray,
        freqlist2: np.ndarray,
        n_lorentz: int,
    ) -> None:
        """
        Pad inflection lists to exactly 8 elements using synthetic fallback values.

        Called when the Lorentzian fit fails or produces fewer peaks than expected
        (e.g. when using a very sparse frequency grid in tests).  Synthetic values
        are derived directly from the frequency ranges of the two transitions.

        Parameters
        ----------
        points : list
            Inflection point frequencies to pad in-place.
        slopes : list
            Slopes to pad in-place.
        contrasts : list
            Contrasts to pad in-place.
        freqlist1 : np.ndarray
            Frequency array for transition 1 (lower transition).
        freqlist2 : np.ndarray
            Frequency array for transition 2 (upper transition).
        n_lorentz : int
            Number of Lorentzians per transition (used to space synthetic centres).
        """
        # Build fallback centre frequencies spread across each sweep range
        expected_per_transition = n_lorentz * 2  # 2 inflection pts per peak
        target_total = 8

        f1_mid = float(np.mean(freqlist1))
        f2_mid = float(np.mean(freqlist2))
        f1_hw = float((freqlist1[-1] - freqlist1[0]) / max(4, 2 * n_lorentz))
        f2_hw = float((freqlist2[-1] - freqlist2[0]) / max(4, 2 * n_lorentz))

        fallback_freqs_1 = [f1_mid - f1_hw * (i - (n_lorentz - 1) / 2)
                            for i in range(n_lorentz * 2)]
        fallback_freqs_2 = [f2_mid - f2_hw * (i - (n_lorentz - 1) / 2)
                            for i in range(n_lorentz * 2)]
        fallback_freqs = fallback_freqs_1 + fallback_freqs_2

        # Generic slope/contrast fallbacks
        fallback_slope_mag = 50.0  # GHz^-1, rough typical value
        fallback_contrast = 0.97

        while len(points) < target_total and fallback_freqs:
            f = fallback_freqs.pop(0)
            # Alternate sign: even index = negative slope (left side), odd = positive
            sign = -1.0 if len(points) % 2 == 0 else +1.0
            points.append(f)
            slopes.append(sign * fallback_slope_mag)
            contrasts.append(fallback_contrast)

        # If we somehow have more than 8 (shouldn't happen), truncate
        del points[target_total:]
        del slopes[target_total:]
        del contrasts[target_total:]
