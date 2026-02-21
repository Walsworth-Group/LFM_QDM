"""
MagnetometryWorker — Background QThread for multi-point differential magnetometry.

Runs the multi-point inflection magnetometry loop:
1. Acquires ``state.sg384_lock`` for the entire measurement.
2. Calls ``qdm_gen.format_multi_point_frequencies`` to build freq/slope/parity/baseline
   lists from ``state.sweep_inflection_result``.
3. Loops ``state.mag_num_samples`` times, calling ``qdm_gen.measure_multi_point``
   (or a simulation equivalent) each iteration.
4. Emits a live cumulative average field map (in Gauss) every
   ``state.perf_live_avg_update_interval_samples`` samples.
5. Autosaves a partial stability cube every ``state.perf_autosave_interval_samples``
   samples.
6. On ``stop()``: completes the current sample, then exits — emits ``mag_completed``
   with the partial data collected so far.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import QCoreApplication, QThread, Signal

# Reach the ODMR code v2 project root (GUI/odmr_app/workers/ -> ODMR code v2/)
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import qdm_gen as qdm

# Gyromagnetic ratio for NV centre electron spin (GHz/Gauss)
_GAMMA_E_GHZ_PER_GAUSS = 0.0028024


class MagnetometryWorker(QThread):
    """
    Background thread that executes a multi-point differential magnetometry
    stability measurement.

    Acquires ``state.sg384_lock`` for the entire measurement duration so that
    ``SG384Worker``'s idle polling is blocked.  Emits progress, live preview,
    and final result signals.

    Parameters
    ----------
    state : ODMRAppState
        Shared application state.  Must expose magnetometry configuration
        properties (``mag_num_samples``, ``mag_selected_indices``,
        ``mag_selected_parities``, ``sweep_inflection_result``,
        ``sweep_ref_freq_ghz``, ``sg384_lock``, etc.).
    simulation_mode : bool, optional
        If ``True``, generate synthetic data instead of driving hardware.
        Defaults to ``False``.
    parent : QObject, optional
        Qt parent object.

    Signals
    -------
    mag_progress : (int, int)
        Emitted after each acquired sample with ``(samples_done, total)``.
    mag_sample_acquired : (int, object)
        Emitted every ``perf_live_avg_update_interval_samples`` samples with
        ``(samples_done, field_gauss)`` where ``field_gauss`` is a 2-D
        ``np.float32`` array of the cumulative-average field map in Gauss.
    mag_completed : dict
        Emitted on completion (normal or stopped) with the result dictionary.
    mag_failed : str
        Emitted on unhandled exception with the error message.
    """

    mag_progress = Signal(int, int)          # (samples_done, total)
    mag_sample_acquired = Signal(int, object)  # (samples_done, field_gauss_array)
    mag_completed = Signal(dict)
    mag_failed = Signal(str)

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
        """Execute the magnetometry measurement in the worker thread."""
        self.state.mag_is_running = True
        try:
            result = self._run_measurement()
            self.mag_completed.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.mag_failed.emit(str(exc))
        finally:
            self.state.mag_is_running = False

    # ------------------------------------------------------------------
    # Public control
    # ------------------------------------------------------------------

    def stop(self):
        """Request early termination after the current sample finishes."""
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

    def _run_measurement(self) -> dict:
        """
        Core measurement loop.

        Acquires the SG384 lock and repeatedly calls ``_acquire_sample``
        until ``mag_num_samples`` have been collected or ``stop()`` is called.

        Returns
        -------
        dict
            Keys:
            ``stability_cube`` (np.float32, shape (n_acquired, ny, nx)),
            ``freq_list``, ``slope_list``, ``parity_list``, ``baseline_list``,
            ``num_samples_acquired`` (int),
            ``timestamp`` (ISO-8601 str),
            ``metadata`` (dict from ``state.build_metadata()``).
        """
        state = self.state
        num_samples = state.mag_num_samples
        live_interval = max(1, state.perf_live_avg_update_interval_samples)
        autosave_interval = max(1, state.perf_autosave_interval_samples)

        # Build frequency configuration from inflection result
        freq_list, slope_list, parity_list, baseline_list = self._get_freq_config()

        # Initialise hardware handles first so we can read the true image shape
        # from the camera (shape depends on hardware binning settings).
        handles = self._init_handles()

        # Determine image shape from handles (simulation returns fixed small shape)
        ny, nx = handles.get('ny', 10), handles.get('nx', 10)

        # Allocate output arrays
        stability_cube = np.zeros((num_samples, ny, nx), dtype=np.float32)
        running_sum = np.zeros((ny, nx), dtype=np.float64)

        samples_done = 0

        try:
            with state.sg384_lock:
                for _i in range(num_samples):
                    if self._stop_requested:
                        break

                    sample = self._acquire_sample(
                        handles, freq_list, slope_list, parity_list, baseline_list,
                        ny, nx,
                    )

                    stability_cube[samples_done] = sample
                    running_sum += sample.astype(np.float64)
                    samples_done += 1

                    state.mag_current_sample = samples_done
                    self.mag_progress.emit(samples_done, num_samples)

                    # Live average field map preview
                    if samples_done % live_interval == 0:
                        field_gauss = (
                            running_sum / samples_done / _GAMMA_E_GHZ_PER_GAUSS
                        ).astype(np.float32)
                        self.mag_sample_acquired.emit(samples_done, field_gauss)

                    # Periodic autosave
                    if samples_done % autosave_interval == 0:
                        self._autosave_partial(stability_cube[:samples_done])
        finally:
            self._close_handles(handles)

        return {
            "stability_cube": stability_cube[:samples_done],
            "freq_list": freq_list,
            "slope_list": slope_list,
            "parity_list": parity_list,
            "baseline_list": baseline_list,
            "num_samples_acquired": samples_done,
            "timestamp": datetime.now().isoformat(),
            "metadata": state.build_metadata(),
        }

    def _get_freq_config(self):
        """
        Build frequency, slope, parity, and baseline lists for the measurement.

        Calls ``qdm.format_multi_point_frequencies`` using the inflection result
        stored in ``state.sweep_inflection_result``.

        Returns
        -------
        tuple
            ``(freq_list, slope_list, parity_list, baseline_list)``

        Raises
        ------
        RuntimeError
            If ``state.sweep_inflection_result`` is ``None`` (no sweep has been
            run yet to identify inflection points).
        """
        state = self.state
        if state.sweep_inflection_result is None:
            raise RuntimeError(
                "No inflection result available. Run an ODMR sweep first to "
                "identify inflection points before starting magnetometry."
            )

        result = state.sweep_inflection_result
        inflection_points = result["inflection_points"]
        inflection_slopes = result["inflection_slopes"]
        inflection_contrasts = result.get("inflection_contrasts", None)

        freq_list, slope_list, parity_list, baseline_list = (
            qdm.format_multi_point_frequencies(
                inflection_points=inflection_points,
                inflection_slopes=inflection_slopes,
                indices=state.mag_selected_indices,
                parities=state.mag_selected_parities,
                ref_freq=state.sweep_ref_freq_ghz,
                inflection_contrasts=inflection_contrasts,
            )
        )
        return freq_list, slope_list, parity_list, baseline_list

    def _init_handles(self) -> dict:
        """
        Initialise hardware handles for the measurement.

        In simulation mode, returns a minimal dict with a fixed small image
        shape suitable for testing.

        In hardware mode, opens the Basler camera, applies hardware binning
        from ``state.mag_hw_bin_x`` / ``state.mag_hw_bin_y``, grabs one test
        frame to determine the actual image dimensions, and returns a handles
        dict.  The SG384 is **not** opened here — ``_acquire_sample`` uses
        ``state.sg384_controller``, which is already connected.

        Returns
        -------
        dict
            Keys: ``'camera_instance'`` (hardware mode only), ``'ny'``, ``'nx'``.
        """
        if self.simulation_mode:
            return {'ny': 10, 'nx': 10}

        state = self.state
        from qdm_basler import basler  # noqa: PLC0415
        camera_instance = basler.connect_and_open(
            choice=state.odmr_camera_serial,
            exposure_time_us=state.mag_exposure_time_us,
            verbose=False,
        )
        # Apply hardware binning before grabbing the first frame
        _cam = camera_instance._camera
        _cam.BinningHorizontal.SetValue(state.mag_hw_bin_x)
        _cam.BinningVertical.SetValue(state.mag_hw_bin_y)
        _cam.BinningHorizontalMode.SetValue("Average")
        _cam.BinningVerticalMode.SetValue("Average")

        test_frame = camera_instance.grab_frames(n_frames=1, quiet=True)
        ny, nx = test_frame.shape
        return {'camera_instance': camera_instance, 'ny': ny, 'nx': nx}

    def _close_handles(self, handles: dict) -> None:
        """
        Release hardware resources after the measurement.

        Closes the camera connection if present.  Errors during cleanup are
        caught and suppressed so that they do not mask measurement exceptions.

        Parameters
        ----------
        handles : dict
            Hardware handles dict as returned by ``_init_handles``.
        """
        if self.simulation_mode:
            return
        try:
            camera = handles.get("camera_instance")
            if camera is not None:
                camera.close()
        except Exception:  # noqa: BLE001
            pass

    def _acquire_sample(
        self,
        handles: dict,
        freq_list: list,
        slope_list: list,
        parity_list: list,
        baseline_list: list,
        ny: int = 10,
        nx: int = 10,
    ) -> np.ndarray:
        """
        Acquire a single magnetometry sample.

        In simulation mode, returns a small array of Gaussian noise centred on
        zero (units: GHz frequency shift).  A ``time.sleep`` is added so that
        stopping mid-run in tests captures partial data within a reasonable
        wall-clock window.

        In hardware mode, calls ``qdm.measure_multi_point`` to drive the signal
        generator through the configured frequency sequence and capture camera
        frames.

        Parameters
        ----------
        handles : dict
            Hardware handles dict from ``_init_handles``.
        freq_list : list of float
            MW frequencies for each measurement point (GHz).
        slope_list : list of float
            Signed ODMR slopes at each frequency point (GHz^-1).
        parity_list : list of int
            Parities for each point (±1 for signal, 0 for reference).
        baseline_list : list of float
            Expected baseline PL contrast at each inflection point.

        Returns
        -------
        np.ndarray
            2-D float32 array of shape ``(ny, nx)`` representing the frequency
            shift at each pixel in GHz.
        """
        if self.simulation_mode:
            # Small sleep so that 20-sample run takes ~1 s total, allowing the
            # test_mag_stop_saves_partial test to interrupt after ~0.3 s.
            time.sleep(0.05)
            return np.random.normal(0, 1e-4, (ny, nx)).astype(np.float32)

        return qdm.measure_multi_point(
            sg384=self.state.sg384_controller,
            camera=handles["camera_instance"],
            freq_list=freq_list,
            slope_list=slope_list,
            parity_list=parity_list,
            settling_time=self.state.perf_mw_settling_time_s,
            n_frames=self.state.mag_n_frames_per_point,
            baseline_list=baseline_list,
        )

    def _autosave_partial(self, partial_cube: np.ndarray) -> None:
        """
        Save a partial stability cube to disk as a compressed .npz file.

        The file is written to::

            Path(state.save_base_path) / state.save_subfolder
                / "_magnetometry_partial_autosave.npz"

        Silently skipped if ``state.save_base_path`` is empty.  All exceptions
        are caught so that autosave failures never abort the measurement.

        Parameters
        ----------
        partial_cube : np.ndarray
            The stability cube trimmed to samples acquired so far,
            shape ``(n_acquired, ny, nx)``.
        """
        base = self.state.save_base_path
        if not base:
            return
        try:
            save_dir = Path(base) / self.state.save_subfolder
            save_dir.mkdir(parents=True, exist_ok=True)
            save_path = save_dir / "_magnetometry_partial_autosave.npz"
            np.savez_compressed(save_path, stability_cube=partial_cube)
        except Exception:  # noqa: BLE001
            pass
