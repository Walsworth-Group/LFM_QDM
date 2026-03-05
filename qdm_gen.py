# General Python functions for ODMR QDM control

from typing import Union, Optional
import numpy as np
import scipy
from scipy.signal import find_peaks
from scipy.ndimage import zoom
import time
from qdm_basler import basler
from qdm_srs import SG384Controller

import os
from pathlib import Path
from datetime import datetime
import matplotlib.pyplot as plt

# Import denoising functions (optional - will be checked at runtime)
try:
    from skimage.restoration import (
        denoise_wavelet, denoise_nl_means, denoise_tv_chambolle,
        denoise_bilateral, estimate_sigma
    )
    from skimage.filters import gaussian
    SKIMAGE_AVAILABLE = True
except ImportError:
    SKIMAGE_AVAILABLE = False

# ============================================================
# General top-level ODMR commands
# ============================================================

def run_odmr_sweep(
    freqlist,
    ref_freq,
    num_sweeps,
    settings,
    simulation_mode=False,
    live_plot=True,
    show_progress=True,
    auto_analyze=True,
    n_lorentz=2,
    save_data=False,
    save_fig=False,
    save_path=None,
    subfolder="",
    logger=None,
    fit_tolerance=None,
    max_iters=None
):
    """
    High-level function to execute a complete ODMR frequency sweep experiment.

    This function handles initialization, data acquisition (hardware or simulation),
    live plotting, cleanup, and optionally automatic analysis with plotting.

    Parameters
    ----------
    freqlist : np.ndarray
        Array of frequencies to sweep (in GHz).
    ref_freq : float
        Reference frequency for normalization (in GHz). Should be far from resonance.
    num_sweeps : int
        Number of complete frequency sweeps to average.
    settings : dict
        Nested settings dictionary containing 'camera', 'srs', and 'simulation' configs.
    simulation_mode : bool
        If True, generate synthetic data instead of using hardware.
    live_plot : bool
        If True, display live PL vs frequency plot during acquisition.
    show_progress : bool
        If True, display tqdm progress bar.
    auto_analyze : bool
        If True, automatically run ODMR analysis and plotting after acquisition.
    n_lorentz : int
        Number of Lorentzian peaks to fit (used if auto_analyze=True).
    save_data : bool
        If True, save the raw ODMR data cube and frequency list to .npz file.
    save_fig : bool
        If True and auto_analyze=True, save the analysis figure.
    save_path : str or Path or None
        Base directory for saving data and figures. Uses default if None.
    subfolder : str
        Subfolder for saving data and figures.
    logger : callable or None
        Optional logging function (e.g., tqdm.write).
    fit_tolerance : float or None
        Convergence tolerance (ftol and xtol) for Lorentzian fitting.
        None uses fit_lorentzians default (1e-8). Only used if auto_analyze=True.
    max_iters : int or None
        Maximum function evaluations for Lorentzian fitting.
        None uses fit_lorentzians default (20000). Only used if auto_analyze=True.

    Returns
    -------
    dict
        Dictionary containing:
        - 'odmr_data_cube': np.ndarray of shape (n_freqs, ny, nx)
        - 'freqlist': the frequency array used
        - 'elapsed_time': total acquisition time in seconds
        - 'ny', 'nx': image dimensions
        - 'num_sweeps': number of sweeps performed
        - 'analysis': dict with fit results (if auto_analyze=True)
        - 'peak_params': list of peak parameter dicts (if auto_analyze=True)
    """
    from tqdm.auto import tqdm as tqdm_auto
    from IPython import display

    if logger is None:
        logger = print

    # --- 1. Initialize System ---
    sys_config = initialize_system(simulation_mode, settings, logger=logger)
    ny = sys_config['ny']
    nx = sys_config['nx']
    sim_field_map = sys_config.get('sim_field_map')

    num_freqs = len(freqlist)
    total_points = num_sweeps * num_freqs
    odmr_data_cube = np.zeros((num_freqs, ny, nx), dtype=np.float32)

    # --- 2. Setup Live Plot with display handle for non-clearing updates ---
    fig_live, ax_live, line_live, plot_handle = None, None, None, None
    if live_plot:
        plt.ioff()  # Turn off interactive mode - we'll manage updates manually
        fig_live, ax_live = plt.subplots(figsize=(10, 5))
        line_live, = ax_live.plot(freqlist, np.ones(num_freqs), 'b.-', markersize=4, lw=1)
        ax_live.set_xlabel('Frequency (GHz)')
        ax_live.set_ylabel('PL Intensity (S/R)')
        ax_live.set_title('Live ODMR Sweep')
        ax_live.grid(True, alpha=0.3)
        ax_live.set_xlim(freqlist.min(), freqlist.max())
        fig_live.tight_layout()
        # Display the figure and get a handle for updating without clear_output
        plot_handle = display.display(fig_live, display_id=True)

    # Live plot context to pass to sweep functions
    live_plot_ctx = None
    if live_plot:
        live_plot_ctx = {
            'fig': fig_live,
            'ax': ax_live,
            'line': line_live,
            'handle': plot_handle,
            'num_sweeps': num_sweeps,
            'display': display,                                    # avoid repeated import inside the loop
            'accumulated_mean': np.zeros(num_freqs, dtype=np.float64)  # updated per-point, avoids full-cube mean every frame
        }

    # --- 3. Run Acquisition Loop ---
    start_time = time.perf_counter()

    pbar_context = tqdm_auto(total=total_points, unit="pt", desc="Initializing...",
                              disable=not show_progress)

    try:
        with pbar_context as pbar:
            for sweep_idx in range(num_sweeps):
                if not simulation_mode:
                    run_hardware_sweep(
                        freqlist, ref_freq, settings, sys_config,
                        odmr_data_cube, pbar, sweep_idx + 1,
                        live_plot_ctx=live_plot_ctx
                    )
                else:
                    run_simulation_sweep(
                        freqlist, ref_freq, settings, sim_field_map,
                        odmr_data_cube, pbar, sweep_idx + 1,
                        live_plot_ctx=live_plot_ctx
                    )

        # --- 4. Final Averaging ---
        odmr_data_cube /= num_sweeps

    finally:
        # --- 5. Cleanup ---
        if not simulation_mode:
            if sys_config.get('camera_instance'):
                basler.close_instance(sys_config['camera_instance'])
            if sys_config.get('sg384'):
                sys_config['sg384'].close_connection()

        if live_plot and fig_live is not None:
            plt.close(fig_live)
            plt.ion()  # restore interactive mode for subsequent cells

    elapsed_time = time.perf_counter() - start_time
    logger(f"\nExperiment Complete: {num_sweeps} sweeps in {elapsed_time:.2f} seconds.")

    # Save raw data if requested
    if save_data:
        if save_path is None:
            save_path = Path(r"E:\MTB project\CW ODMR")
        else:
            save_path = Path(save_path)

        save_dir = save_path / subfolder
        save_dir.mkdir(parents=True, exist_ok=True)

        # Create filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"odmr_data_{num_freqs}pts_{num_sweeps}sweeps_{timestamp}.npz"
        full_path = save_dir / filename

        np.savez_compressed(
            full_path,
            data=odmr_data_cube,
            frequencies=freqlist,
            num_sweeps=num_sweeps,
            ref_freq=ref_freq
        )
        logger(f"ODMR data saved: {full_path}")

    result = {
        'odmr_data_cube': odmr_data_cube,
        'freqlist': freqlist,
        'elapsed_time': elapsed_time,
        'ny': ny,
        'nx': nx,
        'num_sweeps': num_sweeps
    }

    # Auto-analysis if requested
    if auto_analyze:
        logger("\nRunning automatic ODMR analysis...")
        analysis_result = analyze_and_plot_odmr(
            odmr_data_cube,
            freqlist,
            n_lorentz=n_lorentz,
            show_plot=True,
            save_fig=save_fig,
            subfolder=subfolder,
            title_prefix=f"ODMR Analysis ({num_sweeps} sweeps)",
            fit_tolerance=fit_tolerance,
            max_iters=max_iters
        )
        result['analysis'] = analysis_result['analysis']
        result['peak_params'] = analysis_result['peak_params']
        result['analysis_figure'] = analysis_result['figure']
        result['r2'] = analysis_result['r2']

    return result


def initialize_system(simulation_mode, settings, logger=None):
    """
    Initializes hardware or simulation using a nested settings dictionary.
    """
    results = {
        'camera_instance': None,
        'sg384': None,
        'ny': 0, 'nx': 0,
        'sim_field_map': None
    }

    if not simulation_mode:
        # Access nested Camera settings
        cam_cfg = settings['camera']
        camera_instance = basler.connect_and_open(
            choice=cam_cfg['serial'],
            exposure_time_us=cam_cfg['exposure_time_us'],
            logger=logger,
            verbose=False
        )

        # Apply Binning
        cam = camera_instance._camera
        cam.BinningHorizontal.SetValue(cam_cfg['bin_x'])
        cam.BinningVertical.SetValue(cam_cfg['bin_y'])
        cam.BinningHorizontalMode.SetValue("Average") # "Sum" is also an option, but could more easily saturate
        cam.BinningVerticalMode.SetValue("Average")
        
        # Determine Dimensions
        test_frame = camera_instance.grab_frames(n_frames=1, quiet=True)
        ny, nx = test_frame.shape

        # Access nested SRS settings
        srs_cfg = settings['srs']
        sg384 = SG384Controller(
            address=srs_cfg['address'],
            logger=logger,
            verbose=False,
            verify_on_set=False
        )
        sg384.open_connection()
        sg384.set_amplitude(srs_cfg['rf_power'])

        results.update({
            'camera_instance': camera_instance,
            'sg384': sg384,
            'ny': ny, 'nx': nx
        })

    else:
        # Access nested Simulation settings
        sim_cfg = settings['simulation']
        ny, nx = sim_cfg['img_shape']
        sim_field_map = create_field_map(
            sim_cfg['img_shape'], 
            pattern=sim_cfg['field_pattern'], 
            bias_tesla=sim_cfg['bias_field']
        )
        
        results.update({
            'ny': ny, 'nx': nx,
            'sim_field_map': sim_field_map
        })

    return results

def run_hardware_sweep(freqlist, ref_freq, settings, handles, odmr_data_cube, pbar, sweep_num,
                       live_plot_ctx=None):
    """
    Performs a single physical frequency sweep.

    Parameters
    ----------
    live_plot_ctx : dict or None
        If provided, contains figure, axis, line, and display handle for live updates.
    """
    sg384 = handles['sg384']
    camera = handles['camera_instance']
    settling_time = settings['srs']['settling_time']
    n_frames = settings['camera']['n_frames']

    # Calculate total sweeps for the description
    total_sweeps = pbar.total // len(freqlist)
    num_freqs = len(freqlist)

    for i, freq in enumerate(freqlist):
        t0 = time.perf_counter()

        measure_odmr_point(
            sg384, camera, freq, ref_freq,
            settling_time, n_frames, odmr_data_cube, i
        )

        # Update live plot after each frequency point
        if live_plot_ctx is not None:
            live_plot_ctx['accumulated_mean'][i] = np.nanmean(odmr_data_cube[i, :, :])
            _update_live_plot(live_plot_ctx, sweep_num, i, num_freqs)

        # Atomic Update: Update description and progress without creating a new line
        pbar.set_description(f"Sweep {sweep_num}/{total_sweeps}", refresh=False)
        pbar.update(1)
        pbar.set_postfix(freq=f"{freq:.4f}GHz", loop=f"{time.perf_counter()-t0:.2f}s")
        
def measure_odmr_point(sg384, camera, freq, ref_freq, settling_time, n_frames, odmr_data_cube, idx):
    """
    Performs a single Signal/Reference measurement and updates the data cube.

    On the first call the camera is switched to ``GrabStrategy_LatestImageOnly``
    continuous grabbing (subsequent calls are no-ops).  In this mode no explicit
    ``flush_buffer()`` is required: since the transport layer keeps only one buffer
    slot, any frame from the previous frequency is overwritten within one frame
    period — well before the settling sleep completes.  This eliminates the
    per-step ``StopGrabbing``/``StartGrabbing`` overhead (~500 ms each on USB).

    Parameters
    ----------
    sg384 : SG384Controller
        Signal generator instance.
    camera : basler
        Camera instance (must be open and connected).
    freq : float
        Signal frequency in GHz.
    ref_freq : float
        Reference frequency in GHz.
    settling_time : float
        Time to wait after each frequency change (seconds).  Must be longer
        than one camera frame period so that the LatestImageOnly buffer
        is guaranteed to hold a post-settling frame.
    n_frames : int
        Number of frames to average per measurement.
    odmr_data_cube : np.ndarray
        3-D accumulation array of shape (n_freqs, ny, nx); updated in-place.
    idx : int
        Frequency step index into odmr_data_cube.
    """
    # Ensure camera is in continuous LatestImageOnly grab mode.
    # Idempotent — only performs StopGrabbing/StartGrabbing once per session.
    camera.start_continuous_grab()

    # 1. Measure Signal at target frequency
    sg384.set_frequency(freq, 'GHz')
    time.sleep(settling_time)
    # LatestImageOnly buffer now holds a frame from the new frequency;
    # no explicit flush_buffer() needed.
    sig = camera.grab_frames(n_frames=n_frames, quiet=True)

    # 2. Measure Reference at background frequency
    sg384.set_frequency(ref_freq, 'GHz')
    time.sleep(settling_time)
    ref = camera.grab_frames(n_frames=n_frames, quiet=True)

    # 3. Normalize and accumulate
    if sig is not None and ref is not None:
        odmr_data_cube[idx, :, :] += np.divide(sig, ref, where=ref!=0)


def measure_multi_point(sg384, camera, freq_list, slope_list, parity_list, settling_time,
                        n_frames, baseline_list=None):
    """
    Generalized multi-point measurement with automatic PL-to-frequency conversion.

    Measures PL at multiple frequencies, converts each signal to frequency shift using
    slopes and baseline contrasts, then combines according to parities. Supports
    differential measurements with multiple reference points.

    Parameters
    ----------
    sg384 : SG384Controller
        Signal generator instance.
    camera : basler instance
        Camera instance for grabbing frames.
    freq_list : list of float
        List of frequencies to measure at (in GHz).
    slope_list : list of float
        Slopes at each frequency (in GHz^-1, fractional PL change per GHz).
        Should be 0 for reference frequencies.
    parity_list : list of int
        Parity/operation for each frequency:
        - 1: add this measurement
        - -1: subtract this measurement
        - 0: reference frequency (used for normalization)
    settling_time : float
        Time to wait after setting frequency (seconds).
    n_frames : int
        Number of frames to average for each measurement.
    baseline_list : list of float or None
        Expected baseline contrast (PL_sig/PL_ref) at each signal frequency,
        computed from the fitted ODMR model. This is what the contrast would
        equal if the magnetic field has not changed. If None, defaults to 1.0
        for all points (less accurate for deep Lorentzian dips).

    Returns
    -------
    np.ndarray
        Combined frequency shift result in GHz, shape (ny, nx).

    Examples
    --------
    # Simple 4-point differential with single reference
    >>> result = measure_multi_point(sg, cam, [f1,f2,f3,f4,fref],
    ...                              [s1,s2,s3,s4,0], [1,-1,-1,1,0], 0.02, 10,
    ...                              baseline_list=[bl1,bl2,bl3,bl4,1.0])
    # Result = freq1 - freq2 - freq3 + freq4 (in GHz)
    # where freq_i = (PL_i/PL_ref - baseline_i) / slope_i

    # 4-point with two references
    >>> result = measure_multi_point(sg, cam, [f1,f2,fref1,f3,f4,fref2],
    ...                              [s1,s2,0,s3,s4,0], [1,-1,0,-1,1,0], 0.02, 10,
    ...                              baseline_list=[bl1,bl2,1.0,bl3,bl4,1.0])
    # Result = freq1 - freq2 - freq3 + freq4
    # where freq1,2 use fref1 and freq3,4 use fref2
    """
    # Default baseline: 1.0 for all points if not provided
    if baseline_list is None:
        baseline_list = [1.0] * len(freq_list)

    # Validate inputs
    if len(freq_list) != len(parity_list) or len(freq_list) != len(slope_list):
        raise ValueError(f"freq_list, slope_list, and parity_list must have same length "
                        f"(got {len(freq_list)}, {len(slope_list)}, {len(parity_list)})")

    if len(freq_list) != len(baseline_list):
        raise ValueError(f"baseline_list must have same length as freq_list "
                        f"(got {len(baseline_list)} and {len(freq_list)})")

    if len(freq_list) == 0:
        raise ValueError("freq_list cannot be empty")

    if parity_list[0] == 0:
        raise ValueError("First measurement cannot be a reference (parity=0)")

    # Check for consecutive references
    for i in range(len(parity_list) - 1):
        if parity_list[i] == 0 and parity_list[i+1] == 0:
            raise ValueError(f"Cannot have consecutive reference frequencies at indices {i}, {i+1}")

    # Validate that each signal has a following reference
    for i, parity in enumerate(parity_list):
        if parity != 0:  # Signal frequency
            has_ref = any(parity_list[j] == 0 for j in range(i+1, len(parity_list)))
            if not has_ref:
                raise ValueError(f"Signal at index {i} has no following reference frequency")

    # =========================================================================
    # STEP 1: Take PL measurements at all frequencies
    # =========================================================================
    # Ensure camera is in continuous LatestImageOnly grab mode (idempotent).
    camera.start_continuous_grab()
    measurements = []
    for freq in freq_list:
        sg384.set_frequency(freq, 'GHz')
        time.sleep(settling_time)
        # LatestImageOnly buffer is overwritten within one frame period;
        # no explicit flush_buffer() needed.
        frame = camera.grab_frames(n_frames=n_frames, quiet=True)
        # Convert to float32 to avoid overflow during arithmetic
        measurements.append(frame.astype(np.float32))

    # =========================================================================
    # STEP 2: Convert each signal PL to frequency using slope and reference
    # =========================================================================
    # Algorithm: For each signal (parity != 0), find the next reference (parity == 0)
    # and compute: freq_shift = PL_signal / (slope * PL_reference)
    # This gives frequency shift in GHz since slope is in GHz^-1

    freq_shifts = []
    for i, (pl_sig, parity, slope, baseline_contrast) in enumerate(
            zip(measurements, parity_list, slope_list, baseline_list)):
        if parity == 0:
            # Reference - no conversion, will be used by previous signals
            freq_shifts.append(None)
        else:
            # Signal - find next reference for normalization
            ref_idx = None
            for j in range(i+1, len(parity_list)):
                if parity_list[j] == 0:
                    ref_idx = j
                    break

            pl_ref = measurements[ref_idx]

            # *** CRITICAL CONVERSION STEP ***
            # Convert PL to frequency shift using the formula:
            #   freq_shift (GHz) = (contrast - baseline_contrast) / slope
            #
            # Where:
            #   - contrast = PL_signal / PL_reference (measured contrast ratio)
            #   - baseline_contrast = expected contrast at this inflection point when
            #     the magnetic field has not changed (from fitted ODMR model).
            #     This is < 1.0 because inflection points sit partway down the
            #     Lorentzian dip. Using the actual fitted value instead of 1.0
            #     eliminates systematic offsets in the frequency shift.
            #   - slope: ODMR slope at this inflection point (GHz^-1)
            #   - freq_shift: resulting frequency shift in GHz
            #
            # Physics: At an inflection point, contrast change relates to frequency shift:
            #          ΔC = slope × Δf
            #          Therefore: Δf = ΔC / slope = (C_measured - C_expected) / slope

            contrast = np.divide(pl_sig, pl_ref, where=(pl_ref != 0))
            contrast_deviation = contrast - baseline_contrast
            freq_shift = np.divide(contrast_deviation, slope, where=(slope != 0))
            freq_shifts.append(freq_shift)

    # =========================================================================
    # STEP 3: Apply parities and accumulate frequency shifts
    # =========================================================================
    result = np.zeros_like(freq_shifts[0])

    for i, (freq_shift, parity) in enumerate(zip(freq_shifts, parity_list)):
        if parity == 0:
            continue  # Skip references in accumulation

        # Apply parity (+1 or -1) and accumulate
        result = result + parity * freq_shift

    return result.astype(np.float32)


def identify_multi_transition_inflection_points(
    start_freq1, end_freq1, num_steps1,
    start_freq2, end_freq2, num_steps2,
    ref_freq, num_sweeps, settings,
    simulation_mode=False,
    n_lorentz_per_sweep=2,
    show_plot=True,
    save_data=False,
    save_fig=False,
    save_path=None,
    subfolder="",
    logger=None,
    fit_tolerance=None,
    max_iters=None
):
    """
    Identify all inflection points from both NV transitions for multi-point magnetometry.

    Runs two ODMR sweeps covering different frequency ranges (typically m=0→-1 and
    m=0→+1 transitions), analyzes each to find hyperfine peaks, and extracts all
    inflection points. This is the first step for 4-point differential magnetometry
    that cancels strain and temperature shifts.

    Parameters
    ----------
    start_freq1, end_freq1 : float
        Frequency range for first sweep (GHz), typically lower transition.
    num_steps1 : int
        Number of frequency points in first sweep.
    start_freq2, end_freq2 : float
        Frequency range for second sweep (GHz), typically higher transition.
    num_steps2 : int
        Number of frequency points in second sweep.
    ref_freq : float
        Reference frequency for normalization (GHz).
    num_sweeps : int
        Number of sweeps to average for each range.
    settings : dict
        Nested settings dictionary (camera, srs, simulation configs).
    simulation_mode : bool
        If True, generate synthetic data.
    n_lorentz_per_sweep : int
        Number of Lorentzian peaks expected per sweep (typically 2 for hyperfine).
    show_plot : bool
        If True, display analysis plots for both sweeps.
    save_data : bool
        If True, save raw ODMR data for both sweeps.
    save_fig : bool
        If True, save analysis figures.
    save_path : str or Path or None
        Base directory for saving. Uses default if None.
    subfolder : str
        Subfolder for saving data and figures.
    logger : callable or None
        Optional logging function.
    fit_tolerance : float or None
        Convergence tolerance (ftol and xtol) for Lorentzian fitting.
        None uses fit_lorentzians default (1e-8).
    max_iters : int or None
        Maximum function evaluations for Lorentzian fitting.
        None uses fit_lorentzians default (20000).

    Returns
    -------
    dict
        Dictionary containing:
        - 'inflection_points': np.ndarray of all inflection frequencies (8 total for 2x2 peaks)
        - 'inflection_slopes': np.ndarray of signed slopes at each inflection point (GHz^-1)
        - 'inflection_contrasts': np.ndarray of baseline contrast (PL_sig/PL_ref) at each
          inflection point, computed from the fitted ODMR model. These are the expected
          contrast values when the magnetic field has not changed.
        - 'sweep1_result': full result dict from first run_odmr_sweep
        - 'sweep2_result': full result dict from second run_odmr_sweep
        - 'peak_params_1': list of peak parameters from first sweep
        - 'peak_params_2': list of peak parameters from second sweep
    """
    if logger is None:
        logger = print

    logger("\n" + "="*60)
    logger("MULTI-TRANSITION INFLECTION POINT IDENTIFICATION")
    logger("="*60)

    # Generate frequency arrays
    freqlist1 = gen_freqs(start_freq1, end_freq1, num_steps1)
    freqlist2 = gen_freqs(start_freq2, end_freq2, num_steps2)

    # Run first sweep (lower transition)
    logger(f"\nSweep 1: {start_freq1:.4f} - {end_freq1:.4f} GHz ({num_steps1} points)")
    sweep1_result = run_odmr_sweep(
        freqlist=freqlist1,
        ref_freq=ref_freq,
        num_sweeps=num_sweeps,
        settings=settings,
        simulation_mode=simulation_mode,
        live_plot=False,  # Disable live plot for cleaner output
        show_progress=True,
        auto_analyze=True,
        n_lorentz=n_lorentz_per_sweep,
        save_data=save_data,
        save_fig=save_fig,
        save_path=save_path,
        subfolder=subfolder,
        logger=logger,
        fit_tolerance=fit_tolerance,
        max_iters=max_iters
    )

    if show_plot and 'analysis_figure' in sweep1_result:
        import matplotlib.pyplot as plt
        plt.show()

    # Run second sweep (higher transition)
    logger(f"\nSweep 2: {start_freq2:.4f} - {end_freq2:.4f} GHz ({num_steps2} points)")
    sweep2_result = run_odmr_sweep(
        freqlist=freqlist2,
        ref_freq=ref_freq,
        num_sweeps=num_sweeps,
        settings=settings,
        simulation_mode=simulation_mode,
        live_plot=False,
        show_progress=True,
        auto_analyze=True,
        n_lorentz=n_lorentz_per_sweep,
        save_data=save_data,
        save_fig=save_fig,
        save_path=save_path,
        subfolder=subfolder,
        logger=logger,
        fit_tolerance=fit_tolerance,
        max_iters=max_iters
    )

    if show_plot and 'analysis_figure' in sweep2_result:
        import matplotlib.pyplot as plt
        plt.show()

    # Extract inflection points and slopes from both sweeps
    peak_params_1 = sweep1_result['peak_params']
    peak_params_2 = sweep2_result['peak_params']

    inflection_points = []
    inflection_slopes = []  # Slopes in GHz^-1 (fractional PL change per GHz)
    inflection_contrasts = []  # Baseline contrast at each inflection point

    # Extract from first sweep
    for peak in peak_params_1:
        inflection_points.extend(peak['inflection_pts'])
        inflection_contrasts.extend(peak['inflection_contrasts'])
        # Each peak has two inflection points (left and right)
        # Slope is same magnitude, but we need to track sign
        # Left inflection: negative slope, Right inflection: positive slope
        inflection_slopes.append(-peak['max_slope'])  # Left (low freq) - negative slope
        inflection_slopes.append(peak['max_slope'])   # Right (high freq) - positive slope

    # Extract from second sweep
    for peak in peak_params_2:
        inflection_points.extend(peak['inflection_pts'])
        inflection_contrasts.extend(peak['inflection_contrasts'])
        inflection_slopes.append(-peak['max_slope'])  # Left - negative slope
        inflection_slopes.append(peak['max_slope'])   # Right - positive slope

    inflection_points = np.array(inflection_points)
    inflection_slopes = np.array(inflection_slopes)
    inflection_contrasts = np.array(inflection_contrasts)

    # Print summary
    logger("\n" + "="*60)
    logger(f"IDENTIFIED {len(inflection_points)} INFLECTION POINTS:")
    logger("="*60)
    for i, (freq, slope, bl_contrast) in enumerate(
            zip(inflection_points, inflection_slopes, inflection_contrasts), 1):
        logger(f"  Point {i}: {freq:.6f} GHz, Slope: {slope:.6f} GHz^-1, "
               f"Baseline contrast: {bl_contrast:.6f}")
    logger("="*60 + "\n")

    return {
        'inflection_points': inflection_points,
        'inflection_slopes': inflection_slopes,
        'inflection_contrasts': inflection_contrasts,
        'sweep1_result': sweep1_result,
        'sweep2_result': sweep2_result,
        'peak_params_1': peak_params_1,
        'peak_params_2': peak_params_2
    }


def format_multi_point_frequencies(inflection_points, inflection_slopes, indices, parities,
                                   ref_freq, inflection_contrasts=None):
    """
    Select and format inflection points and slopes for multi-point measurement.

    Takes the full arrays of identified inflection points and slopes (typically 8 from 4 peaks),
    selects a subset based on user-specified indices, and formats them into
    frequency, slope, parity, and baseline contrast lists ready for measure_multi_point().

    Supports flexible reference placement: use 0 in indices to specify where reference
    measurements should occur.

    Parameters
    ----------
    inflection_points : np.ndarray or list
        Array of all available inflection frequencies (in GHz).
    inflection_slopes : np.ndarray or list
        Array of slopes at inflection points (in GHz^-1, fractional PL change per GHz).
    indices : list of int
        Which inflection points to use (1-indexed). Use 0 to insert reference frequency.
        Examples:
        - [1,4,5,8,0]: four signals, then reference at end
        - [1,4,0,5,8,0]: signals 1,4, then ref, then signals 5,8, then ref
        - [1,0,4,0,5,0,8,0]: alternate signal and reference
    parities : list of int
        Parity for each entry (±1 for signals, 0 for references).
        Must have same length as indices.
    ref_freq : float
        Reference frequency (in GHz).
    inflection_contrasts : np.ndarray, list, or None
        Baseline contrast (PL_sig/PL_ref) at each inflection point from the fitted
        ODMR model. If None, defaults to 1.0 for all points (less accurate).

    Returns
    -------
    tuple
        (freq_list, slope_list, parity_list, baseline_list) ready for measure_multi_point():
        - freq_list: list of selected frequencies with ref_freq at specified positions
        - slope_list: list of selected slopes with 0 for references
        - parity_list: list of parities
        - baseline_list: list of expected baseline contrasts at each frequency

    Examples
    --------
    >>> # Single reference at end (traditional)
    >>> freq_list, slope_list, par_list, bl_list = format_multi_point_frequencies(
    ...     inflection_pts, inflection_slp,
    ...     indices=[1,4,5,8,0], parities=[1,-1,-1,1,0], ref_freq=3.2,
    ...     inflection_contrasts=inflection_contrasts)

    >>> # Two reference groups
    >>> freq_list, slope_list, par_list, bl_list = format_multi_point_frequencies(
    ...     inflection_pts, inflection_slp,
    ...     indices=[1,4,0,5,8,0], parities=[1,-1,0,-1,1,0], ref_freq=3.2,
    ...     inflection_contrasts=inflection_contrasts)
    """
    inflection_points = np.asarray(inflection_points)
    inflection_slopes = np.asarray(inflection_slopes)

    if inflection_contrasts is not None:
        inflection_contrasts = np.asarray(inflection_contrasts)
    else:
        print("WARNING: inflection_contrasts not provided, using baseline=1.0 for all points.")
        print("  For accurate PL-to-frequency conversion, provide inflection_contrasts from")
        print("  identify_multi_transition_inflection_points().")
        inflection_contrasts = np.ones(len(inflection_points))

    # Validate lengths
    if len(indices) != len(parities):
        raise ValueError(f"indices and parities must have same length "
                        f"(got {len(indices)} and {len(parities)})")

    # Validate that 0 in indices corresponds to 0 in parities
    n_available = len(inflection_points)
    for idx, parity in zip(indices, parities):
        if idx == 0:  # Reference position
            if parity != 0:
                raise ValueError(f"Index 0 (reference) must have parity 0, got {parity}")
        else:  # Signal position
            if idx < 1 or idx > n_available:
                raise ValueError(f"Index {idx} out of range (must be 1-{n_available} or 0 for reference)")
            if parity not in [-1, 1]:
                raise ValueError(f"Signal index {idx} must have parity ±1, got {parity}")

    # Build frequency, slope, parity, and baseline lists
    freq_list = []
    slope_list = []
    parity_list = []
    baseline_list = []

    for idx, parity in zip(indices, parities):
        if idx == 0:  # Reference
            freq_list.append(ref_freq)
            slope_list.append(0.0)
            parity_list.append(0)
            baseline_list.append(1.0)  # Reference points don't need a baseline contrast
        else:  # Signal (convert from 1-indexed to 0-indexed)
            freq_list.append(inflection_points[idx-1])
            slope_list.append(inflection_slopes[idx-1])
            parity_list.append(parity)
            baseline_list.append(float(inflection_contrasts[idx-1]))

    # Print summary
    print("\n" + "="*60)
    print("MULTI-POINT MEASUREMENT CONFIGURATION:")
    print("="*60)
    for i, (freq, slope, parity, bl) in enumerate(
            zip(freq_list, slope_list, parity_list, baseline_list)):
        if parity == 0:
            print(f"  {i+1}. {freq:.6f} GHz  [REFERENCE]")
        else:
            sign = "+" if parity == 1 else "-"
            print(f"  {i+1}. {freq:.6f} GHz, Slope: {slope:.6f} GHz^-1, "
                  f"Baseline: {bl:.6f}  [{sign}]")
    print("="*60 + "\n")

    return freq_list, slope_list, parity_list, baseline_list


def run_multi_point_stability_measurement(
    freq_list,
    slope_list,
    parity_list,
    num_samples,
    settings,
    baseline_list=None,
    simulation_mode=False,
    show_progress=True,
    save_data=False,
    save_path=None,
    subfolder="",
    logger=None
):
    """
    Stability measurement using multi-point differential scheme with PL-to-frequency conversion.

    Similar to run_stability_measurement() but uses the generalized multi-point
    measurement scheme for differential magnetometry. Automatically converts PL to
    frequency shifts using slopes and baseline contrasts. Supports 4-point measurements
    that cancel strain and temperature shifts.

    Parameters
    ----------
    freq_list : list of float
        List of frequencies to measure at (GHz), including reference(s).
    slope_list : list of float
        Slopes at each frequency (in GHz^-1). Should be 0 for references.
    parity_list : list of int
        Parity for each frequency (1=add, -1=subtract, 0=reference).
    num_samples : int
        Number of repeated measurements to acquire.
    settings : dict
        Nested settings dictionary (camera, srs, simulation configs).
    baseline_list : list of float or None
        Expected baseline contrast (PL_sig/PL_ref) at each signal frequency,
        from the fitted ODMR model. If None, defaults to 1.0 for all points.
    simulation_mode : bool
        If True, generate synthetic data (not yet implemented for multi-point).
    show_progress : bool
        If True, display tqdm progress bar.
    save_data : bool
        If True, save the stability cube to .npz file.
    save_path : str or Path or None
        Base directory for saving. Uses default if None.
    subfolder : str
        Subfolder within save_path.
    logger : callable or None
        Optional logging function.

    Returns
    -------
    dict
        Dictionary containing:
        - 'stability_cube': np.ndarray of shape (num_samples, ny, nx)
        - 'freq_list': the frequency list used
        - 'parity_list': the parity list used
        - 'settings': copy of acquisition settings
        - 'elapsed_time': total acquisition time in seconds
        - 'ny', 'nx': image dimensions
    """
    from tqdm.auto import tqdm as tqdm_auto

    if logger is None:
        logger = print

    if simulation_mode:
        raise NotImplementedError("Simulation mode not yet implemented for multi-point measurements")

    # Initialize system
    logger("Initializing multi-point stability measurement...")
    sys_config = initialize_system(simulation_mode, settings, logger=logger)
    ny, nx = sys_config['ny'], sys_config['nx']

    sg384 = sys_config['sg384']
    camera = sys_config['camera_instance']
    settling_time = settings['srs']['settling_time']
    n_frames = settings['camera']['n_frames']

    # Allocate data cube (time x height x width)
    stability_cube = np.zeros((num_samples, ny, nx), dtype=np.float32)

    # Acquisition loop
    start_time = time.perf_counter()
    pbar_context = tqdm_auto(total=num_samples, unit="pt", desc="Multi-Point Stability",
                              disable=not show_progress)

    try:
        with pbar_context as pbar:
            for i in range(num_samples):
                t0 = time.perf_counter()

                # Multi-point measurement (returns frequency shifts in GHz)
                result = measure_multi_point(
                    sg384, camera, freq_list, slope_list, parity_list,
                    settling_time, n_frames, baseline_list=baseline_list
                )

                stability_cube[i, :, :] = result

                # UI Update
                pbar.update(1)
                pbar.set_postfix(idx=f"{i+1}/{num_samples}", loop=f"{time.perf_counter()-t0:.2f}s")

    finally:
        # Cleanup
        if sys_config.get('camera_instance'):
            basler.close_instance(sys_config['camera_instance'])
        if sys_config.get('sg384'):
            sys_config['sg384'].close_connection()

    elapsed_time = time.perf_counter() - start_time
    logger(f"\nMulti-point stability measurement complete: {num_samples} samples in {elapsed_time:.2f} seconds.")

    # Save data if requested
    if save_data:
        if save_path is None:
            save_path = Path(r"E:\MTB project\CW ODMR")
        else:
            save_path = Path(save_path)

        save_dir = save_path / subfolder
        save_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"multipoint_stability_{num_samples}pts_{timestamp}.npz"
        full_path = save_dir / filename

        np.savez_compressed(
            full_path,
            data=stability_cube,
            freq_list=np.array(freq_list),
            slope_list=np.array(slope_list),
            parity_list=np.array(parity_list),
            baseline_list=np.array(baseline_list if baseline_list is not None
                                   else [1.0] * len(freq_list)),
            settings=settings
        )
        logger(f"Multi-point stability data saved: {full_path}")

    return {
        'stability_cube': stability_cube,
        'freq_list': freq_list,
        'slope_list': slope_list,
        'parity_list': parity_list,
        'baseline_list': baseline_list,
        'settings': settings,
        'elapsed_time': elapsed_time,
        'ny': ny,
        'nx': nx
    }


# ============================================================
# Spatially-Binned Multi-Point Magnetometry
# ============================================================
# These functions extend multi-point magnetometry to use spatially-varying
# ODMR slopes and baseline contrasts, enabling automatic compensation of
# spatial field gradients caused by bias field inhomogeneity.


def _extract_peak_params_from_popt(popt, baseline, model_func, n_lorentz):
    """
    Extract structured peak parameters from fit parameters.

    Refactored helper to be shared by both fit_global_odmr() and
    identify_multi_transition_inflection_points_binned().

    Parameters
    ----------
    popt : np.ndarray
        Fit parameters: [baseline, A1, x01, gamma1, A2, x02, gamma2, ...]
    baseline : float
        Baseline value from popt[0]
    model_func : callable
        Model function to evaluate at inflection points
    n_lorentz : int
        Number of Lorentzian peaks

    Returns
    -------
    list of dict
        List of peak parameter dictionaries with keys:
        'index', 'center', 'width_fwhm', 'contrast', 'max_slope',
        'inflection_pts', 'inflection_contrasts'
    """
    peak_params = []

    for i in range(n_lorentz):
        idx = 1 + (i * 3)
        amp = abs(popt[idx])
        f_center = popt[idx + 1]
        hwhm = popt[idx + 2]

        # Unitless contrast (ratio of baseline)
        contrast = amp / baseline

        # Max slope in GHz^-1
        max_slope = (3 * np.sqrt(3) / 8) * (contrast / hwhm)

        f_linear_low = f_center - (hwhm / np.sqrt(3))
        f_linear_high = f_center + (hwhm / np.sqrt(3))

        # Evaluate model at inflection points for baseline contrast
        contrast_at_low = model_func(np.array([f_linear_low]), *popt)[0] / baseline
        contrast_at_high = model_func(np.array([f_linear_high]), *popt)[0] / baseline

        peak_params.append({
            'index': i + 1,
            'center': f_center,
            'width_fwhm': 2 * hwhm,
            'contrast': contrast,
            'max_slope': max_slope,
            'inflection_pts': (f_linear_low, f_linear_high),
            'inflection_contrasts': (contrast_at_low, contrast_at_high)
        })

    return peak_params


def _fit_single_bin_odmr(spectrum, freqlist, n_lorentz, fit_tolerance, max_iters, freq_range):
    """
    Fit ODMR spectrum for a single spatial bin.

    Worker function for per-bin fitting, designed for parallel processing.

    Parameters
    ----------
    spectrum : np.ndarray
        1D ODMR spectrum for this bin
    freqlist : np.ndarray
        Frequency array
    n_lorentz : int
        Number of Lorentzian peaks to fit
    fit_tolerance : float
        Tolerance for fit termination
    max_iters : int
        Maximum iterations for fitting
    freq_range : tuple
        (min_freq, max_freq) to constrain peak centers

    Returns
    -------
    dict or None
        Dictionary with 'inflection_points', 'inflection_slopes', 'inflection_contrasts',
        'r2', 'peak_params' if fit succeeds, None if fit fails.
    """
    # Quick skip for empty or invalid bins
    if np.isnan(spectrum).sum() > len(spectrum) * 0.5:
        return None

    if np.ptp(spectrum) < 1e-6:  # No variation
        return None

    try:
        # Perform fit
        fit_results = fit_lorentzians(
            freqlist,
            spectrum,
            n_lorentz=n_lorentz,
            freq_range=freq_range,
            max_nfev=max_iters,
            ftol=fit_tolerance,
            xtol=fit_tolerance,
            gtol=fit_tolerance
        )

        popt = fit_results['popt']
        model_func = fit_results['model']
        r2 = fit_results['r2']

        # Check fit quality
        if r2 < 0.5:  # Threshold for acceptable fit
            return None

        # Extract peak parameters
        baseline = popt[0]
        peak_params = _extract_peak_params_from_popt(popt, baseline, model_func, n_lorentz)

        # Extract inflection points, slopes, and contrasts
        inflection_points = []
        inflection_slopes = []
        inflection_contrasts = []

        for peak in peak_params:
            inflection_points.extend(peak['inflection_pts'])
            inflection_contrasts.extend(peak['inflection_contrasts'])
            # Left inflection: negative slope, Right inflection: positive slope
            inflection_slopes.append(-peak['max_slope'])
            inflection_slopes.append(peak['max_slope'])

        return {
            'inflection_points': np.array(inflection_points),
            'inflection_slopes': np.array(inflection_slopes),
            'inflection_contrasts': np.array(inflection_contrasts),
            'r2': r2,
            'peak_params': peak_params
        }

    except Exception as e:
        # Fit failed
        return None


def _upsample_parameter_array(param_array, ny_full, nx_full, order=1):
    """
    Upsample 2D parameter array from bin resolution to full camera resolution.

    Uses scipy.ndimage.zoom with specified interpolation order. The upsampled
    array is cropped to exact target size to handle rounding.

    Parameters
    ----------
    param_array : np.ndarray
        2D array at bin resolution (ny_bins, nx_bins)
    ny_full : int
        Target height (full camera resolution)
    nx_full : int
        Target width (full camera resolution)
    order : int
        Interpolation order:
        - 0: Nearest-neighbor (preserves exact fitted values within bins)
        - 1: Bilinear (smooth transitions between bins)
        - 3: Cubic (smoothest)
        Default is 1 (bilinear).

    Returns
    -------
    np.ndarray
        Upsampled array of shape (ny_full, nx_full)

    Notes
    -----
    For parameter maps (slopes, frequencies, contrasts), bilinear (order=1) provides
    a good balance between smoothness and fidelity to fitted values. Nearest-neighbor
    (order=0) creates block-like artifacts but preserves exact bin values.
    """
    ny_bins, nx_bins = param_array.shape
    zoom_factors = (ny_full / ny_bins, nx_full / nx_bins)

    # Upsample with specified interpolation
    upsampled = zoom(param_array, zoom_factors, order=order)

    # Crop to exact size (zoom can overshoot by 1 pixel due to rounding)
    return upsampled[:ny_full, :nx_full]


def identify_multi_transition_inflection_points_binned(
    start_freq1, end_freq1, num_steps1,
    start_freq2, end_freq2, num_steps2,
    ref_freq, num_sweeps, settings,
    bin_x=None, bin_y=None,
    simulation_mode=False,
    n_lorentz_per_sweep=2,
    show_plot=True,
    show_binned_maps=False,
    save_data=False,
    save_fig=False,
    save_path=None,
    subfolder="",
    fit_tolerance=1e-8,
    max_iters=20000,
    n_jobs=-1,
    logger=None
):
    """
    Identify inflection points with SPATIAL BINNING for spatially-varying magnetometry.

    Performs per-bin Lorentzian fitting of ODMR sweeps to extract local (spatially-varying)
    inflection points, slopes, and baseline contrasts. This enables automatic compensation
    of spatial field gradients caused by bias field inhomogeneity.

    Key differences from identify_multi_transition_inflection_points():
    - Bins ODMR data spatially before fitting
    - Performs parallel per-bin fitting instead of single global fit
    - Returns 3D parameter arrays (8, ny_bins, nx_bins) instead of 1D arrays
    - Always displays global mean ODMR for user verification
    - Optionally visualizes spatial parameter maps

    Workflow:
    1. Run two ODMR sweeps (m=0→-1 and m=0→+1 transitions)
    2. Bin each data cube spatially
    3. Fit each bin in parallel to extract local parameters
    4. Display global mean ODMR plot (even though per-bin parameters are used)
    5. Optionally display spatial maps of parameters

    Parameters
    ----------
    start_freq1, end_freq1 : float
        Frequency range for first sweep (GHz), typically lower transition.
    num_steps1 : int
        Number of frequency points in first sweep.
    start_freq2, end_freq2 : float
        Frequency range for second sweep (GHz), typically higher transition.
    num_steps2 : int
        Number of frequency points in second sweep.
    ref_freq : float
        Reference frequency for normalization (GHz).
    num_sweeps : int
        Number of sweeps to average per range. Recommend ≥10 for good per-bin SNR.
    settings : dict
        Nested settings dictionary (camera, srs, simulation configs).
    bin_x, bin_y : int or None
        Spatial binning (pixels per bin). Default None = global-mean mode.
        When None, the full camera FOV is treated as a single bin and parameters
        are read directly from the global mean ODMR fit (same code path as
        identify_multi_transition_inflection_points). This gives results that are
        functionally identical to the non-binned pipeline. Returns shape (8, 1, 1)
        parameter arrays, compatible with all downstream binned functions.
        Example: bin_x=50, bin_y=50 → 50×50 pixel bins.
    simulation_mode : bool
        If True, generate synthetic data.
    n_lorentz_per_sweep : int
        Number of Lorentzian peaks per sweep (typically 2 for hyperfine).
    show_plot : bool
        If True, display global mean ODMR analysis plots.
    show_binned_maps : bool
        If True, display spatial maps of peak centers, contrasts, slopes.
    save_data : bool
        If True, save ODMR data and binned parameter arrays.
    save_fig : bool
        If True, save analysis figures.
    save_path : str or Path or None
        Base directory for saving.
    subfolder : str
        Subfolder for saving.
    fit_tolerance : float
        Tolerance for per-bin fitting termination.
    max_iters : int
        Max iterations for per-bin fitting.
    n_jobs : int
        Number of parallel jobs for fitting. -1 uses all CPU cores.
    logger : callable or None
        Optional logging function.

    Returns
    -------
    dict
        Dictionary containing:
        - 'inflection_points': np.ndarray, shape (8, ny_bins, nx_bins)
          All inflection frequencies from both transitions.
        - 'inflection_slopes': np.ndarray, shape (8, ny_bins, nx_bins)
          Signed slopes at each inflection point (GHz^-1).
        - 'inflection_contrasts': np.ndarray, shape (8, ny_bins, nx_bins)
          Expected baseline contrast at each inflection point.
        - 'bin_x', 'bin_y': int
          Binning used.
        - 'ny_bins', 'nx_bins': int
          Number of bins in y and x.
        - 'sweep1_result': dict
          Full result from first sweep (includes global analysis).
        - 'sweep2_result': dict
          Full result from second sweep.
        - 'fit_quality_map_1', 'fit_quality_map_2': np.ndarray
          Per-bin R² values for each sweep.
        - 'figure_odmr': Figure or None
          Global mean ODMR plot (if show_plot=True).
        - 'figure_maps': Figure or None
          Spatial parameter maps (if show_binned_maps=True).

    Examples
    --------
    >>> # Identify inflection points with 10×10 pixel binning
    >>> result = identify_multi_transition_inflection_points_binned(
    ...     start_freq1=2.516, end_freq1=2.528, num_steps1=201,
    ...     start_freq2=3.21, end_freq2=3.22, num_steps2=201,
    ...     ref_freq=1.0, num_sweeps=10, settings=exp_settings,
    ...     bin_x=10, bin_y=10, simulation_mode=False,
    ...     show_plot=True, show_binned_maps=True, n_jobs=-1
    ... )
    >>>
    >>> # Extract 3D parameter arrays
    >>> spatial_freqs = result['inflection_points']  # (8, ny_bins, nx_bins)
    >>> spatial_slopes = result['inflection_slopes']  # (8, ny_bins, nx_bins)
    >>> spatial_contrasts = result['inflection_contrasts']  # (8, ny_bins, nx_bins)
    """
    from joblib import Parallel, delayed

    if logger is None:
        logger = print

    global_mode = (bin_x is None or bin_y is None)

    logger("\n" + "="*60)
    logger("SPATIALLY-BINNED MULTI-TRANSITION INFLECTION POINT IDENTIFICATION")
    logger("="*60)
    if global_mode:
        logger("Mode: GLOBAL-MEAN (bin_x=None / bin_y=None) — parameters from global fit")
    else:
        logger(f"Binning: {bin_x}×{bin_y} pixels per bin")
    logger(f"Parallel fitting with n_jobs={n_jobs}")

    # Generate frequency arrays
    freqlist1 = gen_freqs(start_freq1, end_freq1, num_steps1)
    freqlist2 = gen_freqs(start_freq2, end_freq2, num_steps2)

    # Run first sweep (lower transition)
    logger(f"\nSweep 1: {start_freq1:.4f} - {end_freq1:.4f} GHz ({num_steps1} points)")
    sweep1_result = run_odmr_sweep(
        freqlist=freqlist1,
        ref_freq=ref_freq,
        num_sweeps=num_sweeps,
        settings=settings,
        simulation_mode=simulation_mode,
        live_plot=False,
        show_progress=True,
        auto_analyze=True,  # For global mean plot
        n_lorentz=n_lorentz_per_sweep,
        save_data=save_data,
        save_fig=save_fig,
        save_path=save_path,
        subfolder=subfolder,
        logger=logger,
        fit_tolerance=fit_tolerance,
        max_iters=max_iters
    )

    if show_plot and 'analysis_figure' in sweep1_result:
        plt.show()

    # Run second sweep (higher transition)
    logger(f"\nSweep 2: {start_freq2:.4f} - {end_freq2:.4f} GHz ({num_steps2} points)")
    sweep2_result = run_odmr_sweep(
        freqlist=freqlist2,
        ref_freq=ref_freq,
        num_sweeps=num_sweeps,
        settings=settings,
        simulation_mode=simulation_mode,
        live_plot=False,
        show_progress=True,
        auto_analyze=True,  # For global mean plot
        n_lorentz=n_lorentz_per_sweep,
        save_data=save_data,
        save_fig=save_fig,
        save_path=save_path,
        subfolder=subfolder,
        logger=logger,
        fit_tolerance=fit_tolerance,
        max_iters=max_iters
    )

    if show_plot and 'analysis_figure' in sweep2_result:
        plt.show()

    # =========================================================================
    # PARAMETER EXTRACTION: GLOBAL-MEAN MODE OR PER-BIN FITTING
    # =========================================================================

    # Number of inflection points per sweep (2 per peak × n_lorentz_per_sweep)
    n_infl_per_sweep = 2 * n_lorentz_per_sweep
    n_infl_total = 2 * n_infl_per_sweep  # Total from both sweeps

    if global_mode:
        # ------------------------------------------------------------------
        # GLOBAL-MEAN MODE: bypass per-bin fitting entirely.
        # Read parameters directly from fit_global_odmr results already
        # computed inside run_odmr_sweep (auto_analyze=True).
        # Returns shape (n_infl_total, 1, 1) — compatible with all downstream
        # binned functions; _upsample_parameter_array produces a uniform map.
        # ------------------------------------------------------------------
        logger("\n" + "="*60)
        logger("GLOBAL-MEAN MODE — reading parameters from global ODMR fit")
        logger("="*60)

        ny_bins, nx_bins = 1, 1

        global_peak_params_1 = sweep1_result.get('peak_params', [])
        global_peak_params_2 = sweep2_result.get('peak_params', [])

        global_infl_pts_1, global_infl_slopes_1, global_infl_contrasts_1 = [], [], []
        for peak in global_peak_params_1:
            global_infl_pts_1.extend(peak['inflection_pts'])
            global_infl_contrasts_1.extend(peak['inflection_contrasts'])
            global_infl_slopes_1.append(-peak['max_slope'])
            global_infl_slopes_1.append(peak['max_slope'])

        global_infl_pts_2, global_infl_slopes_2, global_infl_contrasts_2 = [], [], []
        for peak in global_peak_params_2:
            global_infl_pts_2.extend(peak['inflection_pts'])
            global_infl_contrasts_2.extend(peak['inflection_contrasts'])
            global_infl_slopes_2.append(-peak['max_slope'])
            global_infl_slopes_2.append(peak['max_slope'])

        inflection_points_3d = np.full((n_infl_total, 1, 1), np.nan, dtype=np.float32)
        inflection_slopes_3d = np.full((n_infl_total, 1, 1), np.nan, dtype=np.float32)
        inflection_contrasts_3d = np.full((n_infl_total, 1, 1), np.nan, dtype=np.float32)
        fit_quality_map_1 = np.ones((1, 1), dtype=np.float32)
        fit_quality_map_2 = np.ones((1, 1), dtype=np.float32)

        if len(global_infl_pts_1) == n_infl_per_sweep:
            inflection_points_3d[:n_infl_per_sweep, 0, 0] = global_infl_pts_1
            inflection_slopes_3d[:n_infl_per_sweep, 0, 0] = global_infl_slopes_1
            inflection_contrasts_3d[:n_infl_per_sweep, 0, 0] = global_infl_contrasts_1
        else:
            logger("  WARNING: sweep 1 peak_params has unexpected length — NaN values retained")

        if len(global_infl_pts_2) == n_infl_per_sweep:
            inflection_points_3d[n_infl_per_sweep:, 0, 0] = global_infl_pts_2
            inflection_slopes_3d[n_infl_per_sweep:, 0, 0] = global_infl_slopes_2
            inflection_contrasts_3d[n_infl_per_sweep:, 0, 0] = global_infl_contrasts_2
        else:
            logger("  WARNING: sweep 2 peak_params has unexpected length — NaN values retained")

        logger(f"  Output shape: {inflection_points_3d.shape} (1×1 bin = global mean)")

    else:
        # ------------------------------------------------------------------
        # BINNED MODE: spatially bin each ODMR cube, fit all bins in parallel.
        # ------------------------------------------------------------------
        logger("\n" + "="*60)
        logger("PERFORMING PER-BIN ODMR FITTING")
        logger("="*60)

        odmr_cube_1 = sweep1_result['odmr_data_cube']
        odmr_cube_2 = sweep2_result['odmr_data_cube']

        binned_cube_1 = bin_qdm_cube(odmr_cube_1, bin_x, bin_y)
        binned_cube_2 = bin_qdm_cube(odmr_cube_2, bin_x, bin_y)

        n_freq1, ny_bins, nx_bins = binned_cube_1.shape

        logger(f"Binned data shape: ({ny_bins}, {nx_bins}) bins")
        logger(f"Total bins to fit: {ny_bins * nx_bins * 2} ({ny_bins * nx_bins} per sweep)")

        # Setup frequency ranges for fitting
        scan_width_1 = freqlist1.max() - freqlist1.min()
        margin_1 = max(0.05 * scan_width_1, 0.001)
        freq_range_1 = (freqlist1.min() + margin_1, freqlist1.max() - margin_1)

        scan_width_2 = freqlist2.max() - freqlist2.min()
        margin_2 = max(0.05 * scan_width_2, 0.001)
        freq_range_2 = (freqlist2.min() + margin_2, freqlist2.max() - margin_2)

        def prepare_bin_data(binned_cube):
            """Extract all bin spectra and coordinates for parallel fitting."""
            bin_spectra = []
            bin_coords = []
            for iy in range(ny_bins):
                for ix in range(nx_bins):
                    bin_spectra.append(binned_cube[:, iy, ix])
                    bin_coords.append((iy, ix))
            return bin_spectra, bin_coords

        # Fit all bins for sweep 1
        logger(f"Fitting sweep 1 bins...")
        bin_spectra_1, bin_coords_1 = prepare_bin_data(binned_cube_1)

        fit_results_1 = Parallel(n_jobs=n_jobs, verbose=5)(
            delayed(_fit_single_bin_odmr)(
                spectrum, freqlist1, n_lorentz_per_sweep, fit_tolerance, max_iters, freq_range_1
            )
            for spectrum in bin_spectra_1
        )

        # Fit all bins for sweep 2
        logger(f"Fitting sweep 2 bins...")
        bin_spectra_2, bin_coords_2 = prepare_bin_data(binned_cube_2)

        fit_results_2 = Parallel(n_jobs=n_jobs, verbose=5)(
            delayed(_fit_single_bin_odmr)(
                spectrum, freqlist2, n_lorentz_per_sweep, fit_tolerance, max_iters, freq_range_2
            )
            for spectrum in bin_spectra_2
        )

        # Allocate 3D arrays
        logger("\nAssembling 3D parameter arrays...")
        inflection_points_3d = np.full((n_infl_total, ny_bins, nx_bins), np.nan, dtype=np.float32)
        inflection_slopes_3d = np.full((n_infl_total, ny_bins, nx_bins), np.nan, dtype=np.float32)
        inflection_contrasts_3d = np.full((n_infl_total, ny_bins, nx_bins), np.nan, dtype=np.float32)

        fit_quality_map_1 = np.full((ny_bins, nx_bins), np.nan, dtype=np.float32)
        fit_quality_map_2 = np.full((ny_bins, nx_bins), np.nan, dtype=np.float32)

        # Get global mean parameters as fallback for failed bins
        global_peak_params_1 = sweep1_result.get('peak_params', [])
        global_peak_params_2 = sweep2_result.get('peak_params', [])

        global_infl_pts_1, global_infl_slopes_1, global_infl_contrasts_1 = [], [], []
        for peak in global_peak_params_1:
            global_infl_pts_1.extend(peak['inflection_pts'])
            global_infl_contrasts_1.extend(peak['inflection_contrasts'])
            global_infl_slopes_1.append(-peak['max_slope'])
            global_infl_slopes_1.append(peak['max_slope'])

        global_infl_pts_2, global_infl_slopes_2, global_infl_contrasts_2 = [], [], []
        for peak in global_peak_params_2:
            global_infl_pts_2.extend(peak['inflection_pts'])
            global_infl_contrasts_2.extend(peak['inflection_contrasts'])
            global_infl_slopes_2.append(-peak['max_slope'])
            global_infl_slopes_2.append(peak['max_slope'])

        # Fill arrays from sweep 1
        failed_bins_1 = 0
        for idx, ((iy, ix), fit_result) in enumerate(zip(bin_coords_1, fit_results_1)):
            if fit_result is not None:
                inflection_points_3d[:n_infl_per_sweep, iy, ix] = fit_result['inflection_points']
                inflection_slopes_3d[:n_infl_per_sweep, iy, ix] = fit_result['inflection_slopes']
                inflection_contrasts_3d[:n_infl_per_sweep, iy, ix] = fit_result['inflection_contrasts']
                fit_quality_map_1[iy, ix] = fit_result['r2']
            else:
                if len(global_infl_pts_1) == n_infl_per_sweep:
                    inflection_points_3d[:n_infl_per_sweep, iy, ix] = global_infl_pts_1
                    inflection_slopes_3d[:n_infl_per_sweep, iy, ix] = global_infl_slopes_1
                    inflection_contrasts_3d[:n_infl_per_sweep, iy, ix] = global_infl_contrasts_1
                failed_bins_1 += 1

        # Fill arrays from sweep 2
        failed_bins_2 = 0
        for idx, ((iy, ix), fit_result) in enumerate(zip(bin_coords_2, fit_results_2)):
            if fit_result is not None:
                inflection_points_3d[n_infl_per_sweep:, iy, ix] = fit_result['inflection_points']
                inflection_slopes_3d[n_infl_per_sweep:, iy, ix] = fit_result['inflection_slopes']
                inflection_contrasts_3d[n_infl_per_sweep:, iy, ix] = fit_result['inflection_contrasts']
                fit_quality_map_2[iy, ix] = fit_result['r2']
            else:
                if len(global_infl_pts_2) == n_infl_per_sweep:
                    inflection_points_3d[n_infl_per_sweep:, iy, ix] = global_infl_pts_2
                    inflection_slopes_3d[n_infl_per_sweep:, iy, ix] = global_infl_slopes_2
                    inflection_contrasts_3d[n_infl_per_sweep:, iy, ix] = global_infl_contrasts_2
                failed_bins_2 += 1

        total_bins = ny_bins * nx_bins
        logger(f"\nFit quality:")
        logger(f"  Sweep 1: {total_bins - failed_bins_1}/{total_bins} bins successful "
               f"({100*(total_bins - failed_bins_1)/total_bins:.1f}%)")
        logger(f"  Sweep 2: {total_bins - failed_bins_2}/{total_bins} bins successful "
               f"({100*(total_bins - failed_bins_2)/total_bins:.1f}%)")
        if failed_bins_1 > 0 or failed_bins_2 > 0:
            logger(f"  Failed bins replaced with global mean parameters")

    # =========================================================================
    # OPTIONAL: VISUALIZE SPATIAL PARAMETER MAPS
    # =========================================================================
    figure_maps = None
    if show_binned_maps:
        logger("\nGenerating spatial parameter maps...")

        # Create figure with parameter maps
        fig, axes = plt.subplots(3, 4, figsize=(16, 10))
        fig.suptitle('Spatially-Binned ODMR Parameters', fontsize=14, fontweight='bold')

        # Helper to plot a parameter map
        def plot_param_map(ax, data, title, cmap='viridis', label=''):
            im = ax.imshow(data, aspect='auto', cmap=cmap, interpolation='nearest')
            ax.set_title(title, fontsize=10)
            ax.set_xlabel('Bin X')
            ax.set_ylabel('Bin Y')
            plt.colorbar(im, ax=ax, label=label, fraction=0.046, pad=0.04)
            return im

        # Sweep 1 maps
        # Peak centers (average of two peaks)
        if n_lorentz_per_sweep == 2:
            peak1_centers = (inflection_points_3d[0] + inflection_points_3d[1]) / 2
            peak2_centers = (inflection_points_3d[2] + inflection_points_3d[3]) / 2
            plot_param_map(axes[0, 0], peak1_centers, 'Sweep 1 - Peak 1 Center', 'viridis', 'GHz')
            plot_param_map(axes[0, 1], peak2_centers, 'Sweep 1 - Peak 2 Center', 'viridis', 'GHz')

        # Slopes (show magnitude of left inflection for peak 1)
        plot_param_map(axes[1, 0], np.abs(inflection_slopes_3d[0]),
                       'Sweep 1 - Peak 1 Slope', 'plasma', 'GHz⁻¹')
        if n_infl_per_sweep > 2:
            plot_param_map(axes[1, 1], np.abs(inflection_slopes_3d[2]),
                          'Sweep 1 - Peak 2 Slope', 'plasma', 'GHz⁻¹')

        # Fit quality
        plot_param_map(axes[2, 0], fit_quality_map_1, 'Sweep 1 - R²', 'RdYlGn', 'R²')

        # Sweep 2 maps
        if n_lorentz_per_sweep == 2:
            peak3_centers = (inflection_points_3d[4] + inflection_points_3d[5]) / 2
            peak4_centers = (inflection_points_3d[6] + inflection_points_3d[7]) / 2
            plot_param_map(axes[0, 2], peak3_centers, 'Sweep 2 - Peak 1 Center', 'viridis', 'GHz')
            plot_param_map(axes[0, 3], peak4_centers, 'Sweep 2 - Peak 2 Center', 'viridis', 'GHz')

        plot_param_map(axes[1, 2], np.abs(inflection_slopes_3d[4]),
                       'Sweep 2 - Peak 1 Slope', 'plasma', 'GHz⁻¹')
        if n_infl_per_sweep > 2:
            plot_param_map(axes[1, 3], np.abs(inflection_slopes_3d[6]),
                          'Sweep 2 - Peak 2 Slope', 'plasma', 'GHz⁻¹')

        plot_param_map(axes[2, 1], fit_quality_map_2, 'Sweep 2 - R²', 'RdYlGn', 'R²')

        # Hide unused subplots
        axes[2, 2].axis('off')
        axes[2, 3].axis('off')

        plt.tight_layout()
        figure_maps = fig

        if save_fig:
            if save_path is None:
                save_path = Path(r"E:\MTB project\CW ODMR")
            else:
                save_path = Path(save_path)

            save_dir = save_path / subfolder
            save_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"binned_odmr_params_{timestamp}.png"
            fig.savefig(save_dir / filename, dpi=300, bbox_inches='tight')
            logger(f"Saved parameter maps: {save_dir / filename}")

        plt.show()

    # =========================================================================
    # PRINT SUMMARY
    # =========================================================================
    logger("\n" + "="*60)
    logger(f"IDENTIFIED {n_infl_total} INFLECTION POINTS PER BIN:")
    logger("="*60)

    # Print statistics for each inflection point
    for i in range(n_infl_total):
        freq_mean = np.nanmean(inflection_points_3d[i])
        freq_std = np.nanstd(inflection_points_3d[i])
        slope_mean = np.nanmean(inflection_slopes_3d[i])
        slope_std = np.nanstd(inflection_slopes_3d[i])
        contrast_mean = np.nanmean(inflection_contrasts_3d[i])

        logger(f"  Point {i+1}: Freq = {freq_mean:.6f} ± {freq_std:.6f} GHz, "
               f"Slope = {slope_mean:.6f} ± {slope_std:.6f} GHz⁻¹, "
               f"Baseline = {contrast_mean:.6f}")
    logger("="*60 + "\n")

    # Save data if requested
    if save_data:
        if save_path is None:
            save_path = Path(r"E:\MTB project\CW ODMR")
        else:
            save_path = Path(save_path)

        save_dir = save_path / subfolder
        save_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"binned_inflection_params_{timestamp}.npz"
        full_path = save_dir / filename

        np.savez_compressed(
            full_path,
            inflection_points=inflection_points_3d,
            inflection_slopes=inflection_slopes_3d,
            inflection_contrasts=inflection_contrasts_3d,
            fit_quality_map_1=fit_quality_map_1,
            fit_quality_map_2=fit_quality_map_2,
            bin_x=bin_x,
            bin_y=bin_y,
            ny_bins=ny_bins,
            nx_bins=nx_bins,
            freqlist1=freqlist1,
            freqlist2=freqlist2,
            settings=settings
        )
        logger(f"Binned parameter arrays saved: {full_path}")

    return {
        'inflection_points': inflection_points_3d,
        'inflection_slopes': inflection_slopes_3d,
        'inflection_contrasts': inflection_contrasts_3d,
        'bin_x': bin_x,
        'bin_y': bin_y,
        'ny_bins': ny_bins,
        'nx_bins': nx_bins,
        'sweep1_result': sweep1_result,
        'sweep2_result': sweep2_result,
        'fit_quality_map_1': fit_quality_map_1,
        'fit_quality_map_2': fit_quality_map_2,
        'figure_odmr': sweep1_result.get('analysis_figure') if show_plot else None,
        'figure_maps': figure_maps
    }


def print_binned_inflection_summary(multi_sweep_result):
    """
    Print a summary of spatially-binned inflection point identification results.

    Displays array shape, spatial bin count, per-sweep fit quality (mean and
    minimum R²), and per-inflection-point statistics (mean ± std frequency,
    mean |slope|) across all spatial bins.

    Parameters
    ----------
    multi_sweep_result : dict
        Result dict from identify_multi_transition_inflection_points_binned.
        Expected keys: 'inflection_points' (8, ny_bins, nx_bins),
        'inflection_slopes', 'ny_bins', 'nx_bins',
        'fit_quality_map_1', 'fit_quality_map_2'.
    """
    pts = multi_sweep_result['inflection_points']
    slopes = multi_sweep_result['inflection_slopes']
    ny_bins = multi_sweep_result['ny_bins']
    nx_bins = multi_sweep_result['nx_bins']
    fq1 = multi_sweep_result['fit_quality_map_1']
    fq2 = multi_sweep_result['fit_quality_map_2']
    n_pts = pts.shape[0]

    print(f"\n{'='*70}")
    print("BINNED PARAMETER EXTRACTION COMPLETE")
    print(f"{'='*70}")
    print(f"  Parameter array shape : {pts.shape}")
    print(f"  Spatial bins          : {ny_bins} × {nx_bins} = {ny_bins * nx_bins}")
    print(f"  Fit quality (sweep 1) : mean R² = {np.nanmean(fq1):.3f}  "
          f"(min {np.nanmin(fq1):.3f})")
    print(f"  Fit quality (sweep 2) : mean R² = {np.nanmean(fq2):.3f}  "
          f"(min {np.nanmin(fq2):.3f})")
    print(f"\n  Inflection point statistics (mean ± std across all bins):")
    for i in range(n_pts):
        freq_mean = np.nanmean(pts[i])
        freq_std = np.nanstd(pts[i])
        slope_mean = np.nanmean(np.abs(slopes[i]))
        print(f"    Point {i + 1}: {freq_mean:.6f} ± {freq_std:.6f} GHz  |  "
              f"|slope| = {slope_mean:.6f} GHz⁻¹")
    print(f"{'='*70}")


def format_multi_point_frequencies_binned(inflection_points, inflection_slopes, indices, parities,
                                          ref_freq, inflection_contrasts=None, bin_x=None, bin_y=None):
    """
    Select and format spatially-varying inflection points for binned multi-point measurement.

    Similar to format_multi_point_frequencies() but operates on 3D parameter arrays
    instead of 1D lists. Returns 3D arrays ready for measure_multi_point_binned().

    Parameters
    ----------
    inflection_points : np.ndarray
        3D array of inflection frequencies, shape (8, ny_bins, nx_bins).
    inflection_slopes : np.ndarray
        3D array of slopes, shape (8, ny_bins, nx_bins).
    indices : list of int
        Which inflection points to use (1-indexed). Use 0 to insert reference.
        Example: [1, 4, 0, 5, 8, 0] → signals 1,4, ref, signals 5,8, ref.
    parities : list of int
        Parity for each entry (±1 for signals, 0 for references).
    ref_freq : float
        Reference frequency (GHz).
    inflection_contrasts : np.ndarray or None
        3D array of baseline contrasts, shape (8, ny_bins, nx_bins).
        If None, defaults to 1.0 for all bins.
    bin_x, bin_y : int or None
        Binning parameters (for metadata only).

    Returns
    -------
    dict
        Dictionary containing:
        - 'freq_array': np.ndarray, shape (n_points, ny_bins, nx_bins)
        - 'slope_array': np.ndarray, shape (n_points, ny_bins, nx_bins)
        - 'parity_list': np.ndarray, shape (n_points,)
        - 'baseline_array': np.ndarray, shape (n_points, ny_bins, nx_bins)
        - 'bin_x', 'bin_y': int (passed through)

    Examples
    --------
    >>> # Format 4-point differential with two references
    >>> formatted = format_multi_point_frequencies_binned(
    ...     inflection_points=spatial_infl_pts,  # (8, ny_bins, nx_bins)
    ...     inflection_slopes=spatial_slopes,
    ...     indices=[1, 4, 0, 5, 8, 0],
    ...     parities=[1, -1, 0, -1, 1, 0],
    ...     ref_freq=1.0,
    ...     inflection_contrasts=spatial_contrasts,
    ...     bin_x=10, bin_y=10
    ... )
    >>>
    >>> freq_array = formatted['freq_array']  # (6, ny_bins, nx_bins)
    >>> slope_array = formatted['slope_array']  # (6, ny_bins, nx_bins)
    """
    inflection_points = np.asarray(inflection_points)
    inflection_slopes = np.asarray(inflection_slopes)

    # Validate shape: should be (N, ny_bins, nx_bins)
    if inflection_points.ndim != 3:
        raise ValueError(f"inflection_points must be 3D array (N, ny_bins, nx_bins), "
                        f"got shape {inflection_points.shape}")

    if inflection_slopes.shape != inflection_points.shape:
        raise ValueError(f"inflection_slopes must have same shape as inflection_points")

    n_available, ny_bins, nx_bins = inflection_points.shape

    if inflection_contrasts is not None:
        inflection_contrasts = np.asarray(inflection_contrasts)
        if inflection_contrasts.shape != inflection_points.shape:
            raise ValueError(f"inflection_contrasts must have same shape as inflection_points")
    else:
        print("WARNING: inflection_contrasts not provided, using baseline=1.0 for all bins.")
        print("  For accurate PL-to-frequency conversion, provide inflection_contrasts from")
        print("  identify_multi_transition_inflection_points_binned().")
        inflection_contrasts = np.ones((n_available, ny_bins, nx_bins))

    # Validate lengths
    if len(indices) != len(parities):
        raise ValueError(f"indices and parities must have same length "
                        f"(got {len(indices)} and {len(parities)})")

    # Validate indices and parities
    for idx, parity in zip(indices, parities):
        if idx == 0:  # Reference position
            if parity != 0:
                raise ValueError(f"Index 0 (reference) must have parity 0, got {parity}")
        else:  # Signal position
            if idx < 1 or idx > n_available:
                raise ValueError(f"Index {idx} out of range (must be 1-{n_available} or 0 for reference)")
            if parity not in [-1, 1]:
                raise ValueError(f"Signal index {idx} must have parity ±1, got {parity}")

    # Build 3D parameter arrays
    n_points = len(indices)
    freq_array = np.zeros((n_points, ny_bins, nx_bins), dtype=np.float32)
    slope_array = np.zeros((n_points, ny_bins, nx_bins), dtype=np.float32)
    baseline_array = np.zeros((n_points, ny_bins, nx_bins), dtype=np.float32)
    parity_list = np.array(parities, dtype=np.int32)

    for i, (idx, parity) in enumerate(zip(indices, parities)):
        if idx == 0:  # Reference
            freq_array[i, :, :] = ref_freq
            slope_array[i, :, :] = 0.0
            baseline_array[i, :, :] = 1.0
        else:  # Signal (convert from 1-indexed to 0-indexed)
            freq_array[i, :, :] = inflection_points[idx-1, :, :]
            slope_array[i, :, :] = inflection_slopes[idx-1, :, :]
            baseline_array[i, :, :] = inflection_contrasts[idx-1, :, :]

    # Print summary (show statistics across bins)
    print("\n" + "="*60)
    print("BINNED MULTI-POINT MEASUREMENT CONFIGURATION:")
    print("="*60)
    for i, (idx, parity) in enumerate(zip(indices, parities)):
        if parity == 0:
            print(f"  {i+1}. {ref_freq:.6f} GHz  [REFERENCE]")
        else:
            freq_mean = np.nanmean(freq_array[i])
            freq_std = np.nanstd(freq_array[i])
            slope_mean = np.nanmean(slope_array[i])
            baseline_mean = np.nanmean(baseline_array[i])
            sign = "+" if parity == 1 else "-"
            print(f"  {i+1}. Freq: {freq_mean:.6f} ± {freq_std:.6f} GHz, "
                  f"Slope: {slope_mean:.6f} GHz⁻¹, Baseline: {baseline_mean:.6f}  [{sign}]")
    print("="*60 + "\n")

    return {
        'freq_array': freq_array,
        'slope_array': slope_array,
        'parity_list': parity_list,
        'baseline_array': baseline_array,
        'bin_x': bin_x,
        'bin_y': bin_y
    }


def print_binned_time_estimate(formatted_binned, exp_settings, num_samples):
    """
    Print an acquisition time estimate for binned multi-point measurement.

    Computes the expected number of camera captures per sample based on the
    number of spatial bins and signal/reference measurement points, then
    estimates total acquisition time for several reference NUM_SAMPLES values
    and for the planned num_samples.

    Parameters
    ----------
    formatted_binned : dict
        Result dict from format_multi_point_frequencies_binned.
        Expected keys: 'freq_array' (n_pts, ny_bins, nx_bins), 'parity_list'.
    exp_settings : dict
        Nested settings dict with 'srs'['settling_time'] and
        'camera'['exposure_time_us', 'n_frames'].
    num_samples : int
        Planned number of samples (highlighted in the printed table).
    """
    n_pts, ny_bins, nx_bins = formatted_binned['freq_array'].shape
    n_bins = ny_bins * nx_bins
    parity = np.asarray(formatted_binned['parity_list'])
    n_signal = int(np.sum(parity != 0))
    n_ref = n_pts - n_signal
    t_settle = exp_settings['srs']['settling_time']
    t_camera = (exp_settings['camera']['exposure_time_us'] * 1e-6
                * exp_settings['camera']['n_frames'])
    t_per_cap = t_settle + t_camera
    n_caps = n_signal * n_bins + n_ref
    t_per_sample = n_caps * t_per_cap

    print(f"\n--- Acquisition time estimate (per-bin MW stepping) ---")
    print(f"  Bins        : {ny_bins} × {nx_bins} = {n_bins}")
    print(f"  Signal pts  : {n_signal}  |  Ref pts : {n_ref}")
    print(f"  Caps/sample : {n_caps}  ({n_signal} × {n_bins} bins + {n_ref} refs)")
    print(f"  t/capture   : {t_per_cap * 1e3:.1f} ms  "
          f"(settling {t_settle * 1e3:.0f} ms + camera {t_camera * 1e3:.1f} ms)")
    print(f"  Est. t/sample: {t_per_sample:.1f} s")
    reference_ns = [10, 100, 1000]
    for n in reference_ns:
        marker = "  <-- current" if n == num_samples else ""
        print(f"    {n:>5} samples → ~{n * t_per_sample / 3600:.2f} h{marker}")
    if num_samples not in reference_ns:
        print(f"    {num_samples:>5} samples → ~{num_samples * t_per_sample / 3600:.2f} h  <-- current")
    print(f"  (Adjust NUM_SAMPLES or increase BIN_X/BIN_Y in cell 1 to change.)")
    print(f"---")


def measure_multi_point_binned(sg384, camera, freq_array, slope_array, parity_list,
                                baseline_array, settling_time, n_frames, ny_full, nx_full,
                                upsample_order=1, _pbar=None):
    """
    Multi-point measurement with SPATIALLY-VARYING slopes and baseline contrasts.

    Key difference from measure_multi_point(): Parameter arrays are at bin resolution
    and are upsampled to full camera resolution before applying PL-to-frequency conversion.
    This enables per-pixel application of spatially-varying ODMR slopes.

    Algorithm:
    1. Upsample freq_array, slope_array, baseline_array from bin to full resolution
    2. Measure PL at each frequency point:
       - Signal points (parity != 0): step the MW through each bin's local inflection
         frequency and assemble the full-res PL image from per-bin camera captures.
       - Reference points (parity == 0): single capture at ref_freq (same for all bins).
    3. Apply per-pixel PL-to-frequency conversion: Δf = (C - C_baseline) / slope
    4. Combine according to parities

    Parameters
    ----------
    sg384 : SG384Controller
        Signal generator instance.
    camera : basler instance
        Camera instance.
    freq_array : np.ndarray
        3D array of frequencies at bin resolution, shape (n_points, ny_bins, nx_bins).
        For signal points, each bin entry holds the local inflection frequency used to
        set the MW hardware for that bin's pixels. For reference points (parity == 0),
        all bin entries are equal to ref_freq.
    slope_array : np.ndarray
        3D array of slopes, shape (n_points, ny_bins, nx_bins).
    parity_list : np.ndarray or list
        1D array of parities, shape (n_points,). Values: 1, -1, or 0.
    baseline_array : np.ndarray
        3D array of baseline contrasts, shape (n_points, ny_bins, nx_bins).
    settling_time : float
        Time to wait after setting frequency (seconds).
    n_frames : int
        Number of frames to average per measurement.
    ny_full, nx_full : int
        Full camera resolution (height, width).
    upsample_order : int
        Interpolation order for upsampling (0=nearest, 1=bilinear, 3=cubic).
        Default is 1 (bilinear).

    Returns
    -------
    np.ndarray
        Combined frequency shift result in GHz, shape (ny_full, nx_full).

    Notes
    -----
    For signal measurements, the MW is stepped through each bin's local inflection
    frequency. Only that bin's pixel region is used from each captured frame, then the
    regions are assembled into a full-res image. This ensures that C_measured and
    C_baseline correspond to the same point on the local Lorentzian, correctly removing
    the bias field gradient. Acquisition time scales as N_bins × N_signal_points.

    For reference measurements (parity == 0), all bins share the same ref_freq so a
    single camera capture suffices.
    """
    parity_list = np.asarray(parity_list)
    n_points = len(parity_list)

    # Validate inputs
    if freq_array.shape[0] != n_points:
        raise ValueError(f"freq_array first dimension must match parity_list length")
    if slope_array.shape != freq_array.shape:
        raise ValueError(f"slope_array must have same shape as freq_array")
    if baseline_array.shape != freq_array.shape:
        raise ValueError(f"baseline_array must have same shape as freq_array")

    # Upsample parameter arrays to full camera resolution
    freq_array_full = np.array([
        _upsample_parameter_array(freq_array[i], ny_full, nx_full, order=upsample_order)
        for i in range(n_points)
    ])

    slope_array_full = np.array([
        _upsample_parameter_array(slope_array[i], ny_full, nx_full, order=upsample_order)
        for i in range(n_points)
    ])

    baseline_array_full = np.array([
        _upsample_parameter_array(baseline_array[i], ny_full, nx_full, order=upsample_order)
        for i in range(n_points)
    ])

    # Take PL measurements at all frequency points.
    # Signal points (parity != 0): step MW through each bin's local inflection frequency
    # and assemble full-res PL image from per-bin captures.
    # Reference points (parity == 0): all bins share the same ref_freq; single capture.
    ny_bins = freq_array.shape[1]
    nx_bins = freq_array.shape[2]
    bin_h = ny_full // ny_bins
    bin_w = nx_full // nx_bins

    # Ensure continuous LatestImageOnly grabbing (idempotent after first call).
    camera.start_continuous_grab()
    measurements = []
    for i in range(n_points):
        if parity_list[i] == 0:
            # Reference: single off-resonance capture (ref_freq is identical for all bins)
            freq_scalar = np.nanmedian(freq_array[i])
            sg384.set_frequency(freq_scalar, 'GHz')
            time.sleep(settling_time)
            # LatestImageOnly buffer is overwritten within one frame period; no flush needed.
            frame = camera.grab_frames(n_frames=n_frames, quiet=True)
            measurements.append(frame.astype(np.float32))
        else:
            # Signal: step through each bin at its local inflection frequency
            assembled = np.zeros((ny_full, nx_full), dtype=np.float32)
            for iy in range(ny_bins):
                for ix in range(nx_bins):
                    freq_scalar = freq_array[i, iy, ix]
                    if _pbar is not None:
                        bin_num = iy * nx_bins + ix + 1
                        _pbar.set_postfix(
                            pt=f"{i+1}/{n_points}",
                            bin=f"{bin_num}/{ny_bins*nx_bins}",
                            freq=f"{freq_scalar:.4f}GHz"
                        )
                    sg384.set_frequency(freq_scalar, 'GHz')
                    time.sleep(settling_time)
                    frame = camera.grab_frames(n_frames=n_frames, quiet=True).astype(np.float32)
                    # Pixel boundaries; last bin extends to full edge to cover any remainder
                    y0 = iy * bin_h
                    y1 = y0 + bin_h if iy < ny_bins - 1 else ny_full
                    x0 = ix * bin_w
                    x1 = x0 + bin_w if ix < nx_bins - 1 else nx_full
                    assembled[y0:y1, x0:x1] = frame[y0:y1, x0:x1]
            measurements.append(assembled)

    # Convert each signal PL to frequency using spatially-varying slope
    freq_shifts = []
    for i in range(n_points):
        if parity_list[i] == 0:
            # Reference - no conversion
            freq_shifts.append(None)
        else:
            # Signal - find next reference
            ref_idx = None
            for j in range(i+1, n_points):
                if parity_list[j] == 0:
                    ref_idx = j
                    break

            if ref_idx is None:
                raise ValueError(f"Signal at index {i} has no following reference")

            pl_sig = measurements[i]
            pl_ref = measurements[ref_idx]

            # Per-pixel PL-to-frequency conversion
            slope_map = slope_array_full[i]
            baseline_map = baseline_array_full[i]

            # Contrast = PL_signal / PL_reference
            contrast = np.divide(pl_sig, pl_ref, where=(pl_ref != 0))

            # Frequency shift: Δf = (C_measured - C_baseline) / slope
            contrast_deviation = contrast - baseline_map
            freq_shift = np.divide(contrast_deviation, slope_map, where=(slope_map != 0))

            freq_shifts.append(freq_shift)

    # Apply parities and accumulate
    result = np.zeros((ny_full, nx_full), dtype=np.float32)
    for i in range(n_points):
        if parity_list[i] == 0:
            continue  # Skip references
        result = result + parity_list[i] * freq_shifts[i]

    return result


def run_multi_point_stability_measurement_binned(
    freq_array,
    slope_array,
    parity_list,
    baseline_array,
    num_samples,
    settings,
    bin_x,
    bin_y,
    simulation_mode=False,
    show_progress=True,
    save_data=False,
    save_path=None,
    subfolder="",
    upsample_order=1,
    logger=None
):
    """
    Stability measurement with SPATIALLY-VARYING ODMR parameters.

    Orchestrates repeated multi-point measurements using binned (spatially-varying)
    slopes and baseline contrasts. This is the high-level function for acquiring
    differential magnetometry data with automatic spatial gradient compensation.

    Parameters
    ----------
    freq_array : np.ndarray
        3D array of frequencies, shape (n_points, ny_bins, nx_bins).
    slope_array : np.ndarray
        3D array of slopes, shape (n_points, ny_bins, nx_bins).
    parity_list : np.ndarray or list
        1D array of parities, shape (n_points,).
    baseline_array : np.ndarray
        3D array of baseline contrasts, shape (n_points, ny_bins, nx_bins).
    num_samples : int
        Number of repeated measurements.
    settings : dict
        Nested settings dictionary.
    bin_x, bin_y : int
        Binning parameters (for metadata).
    simulation_mode : bool
        If True, generate synthetic data (not yet implemented).
    show_progress : bool
        If True, display progress bar.
    save_data : bool
        If True, save stability cube and parameter arrays.
    save_path : str or Path or None
        Base directory for saving.
    subfolder : str
        Subfolder within save_path.
    upsample_order : int
        Interpolation order for upsampling (default 1=bilinear).
    logger : callable or None
        Optional logging function.

    Returns
    -------
    dict
        Dictionary containing:
        - 'stability_cube': np.ndarray, shape (num_samples, ny, nx) in GHz
        - 'freq_array': np.ndarray, shape (n_points, ny_bins, nx_bins)
        - 'slope_array': np.ndarray, shape (n_points, ny_bins, nx_bins)
        - 'parity_list': np.ndarray
        - 'baseline_array': np.ndarray, shape (n_points, ny_bins, nx_bins)
        - 'bin_x', 'bin_y': int
        - 'settings': dict
        - 'elapsed_time': float
        - 'ny', 'nx': int

    Examples
    --------
    >>> # Run 5000-sample stability measurement with binned parameters
    >>> result = run_multi_point_stability_measurement_binned(
    ...     freq_array=formatted['freq_array'],
    ...     slope_array=formatted['slope_array'],
    ...     parity_list=formatted['parity_list'],
    ...     baseline_array=formatted['baseline_array'],
    ...     num_samples=5000,
    ...     settings=exp_settings,
    ...     bin_x=10, bin_y=10,
    ...     simulation_mode=False,
    ...     show_progress=True,
    ...     save_data=True
    ... )
    >>>
    >>> # Extract stability cube (already in GHz)
    >>> stability_cube = result['stability_cube']  # (5000, ny, nx)
    """
    from tqdm.auto import tqdm as tqdm_auto

    if logger is None:
        logger = print

    if simulation_mode:
        raise NotImplementedError("Simulation mode not yet implemented for binned multi-point measurements")

    # Initialize system
    logger("Initializing binned multi-point stability measurement...")
    sys_config = initialize_system(simulation_mode, settings, logger=logger)
    ny, nx = sys_config['ny'], sys_config['nx']

    sg384 = sys_config['sg384']
    camera = sys_config['camera_instance']
    settling_time = settings['srs']['settling_time']
    n_frames = settings['camera']['n_frames']

    # Validate that bin resolution matches expected camera resolution
    _, ny_bins, nx_bins = freq_array.shape
    logger(f"Camera resolution: {ny} × {nx}")
    logger(f"Bin resolution: {ny_bins} × {nx_bins} ({bin_x}×{bin_y} pixels/bin)")
    logger(f"Upsample interpolation order: {upsample_order} "
           f"({'nearest' if upsample_order==0 else 'bilinear' if upsample_order==1 else 'cubic'})")

    # Allocate data cube (time x height x width)
    stability_cube = np.zeros((num_samples, ny, nx), dtype=np.float32)

    # Acquisition loop
    start_time = time.perf_counter()
    pbar_context = tqdm_auto(total=num_samples, unit="pt", desc="Binned Multi-Point",
                              disable=not show_progress)

    try:
        with pbar_context as pbar:
            for i in range(num_samples):
                t0 = time.perf_counter()

                # Binned multi-point measurement (returns frequency shifts in GHz).
                # Pass pbar so the inner bin loop can update the postfix with live
                # bin/frequency info during the (potentially long) per-bin stepping.
                result = measure_multi_point_binned(
                    sg384, camera, freq_array, slope_array, parity_list,
                    baseline_array, settling_time, n_frames, ny, nx,
                    upsample_order=upsample_order, _pbar=pbar
                )

                stability_cube[i, :, :] = result

                # UI Update: reset postfix to sample-level summary after each sample
                elapsed = time.perf_counter() - t0
                pbar.update(1)
                pbar.set_postfix(sample=f"{i+1}/{num_samples}", t=f"{elapsed:.1f}s")

    finally:
        # Cleanup
        if sys_config.get('camera_instance'):
            basler.close_instance(sys_config['camera_instance'])
        if sys_config.get('sg384'):
            sys_config['sg384'].close_connection()

    elapsed_time = time.perf_counter() - start_time
    logger(f"\nBinned multi-point stability measurement complete: {num_samples} samples in {elapsed_time:.2f} seconds.")

    # Save data if requested
    if save_data:
        if save_path is None:
            save_path = Path(r"E:\MTB project\CW ODMR")
        else:
            save_path = Path(save_path)

        save_dir = save_path / subfolder
        save_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"binned_multipoint_stability_{num_samples}pts_{timestamp}.npz"
        full_path = save_dir / filename

        np.savez_compressed(
            full_path,
            data=stability_cube,
            freq_array=freq_array,
            slope_array=slope_array,
            parity_list=parity_list,
            baseline_array=baseline_array,
            bin_x=bin_x,
            bin_y=bin_y,
            settings=settings,
            upsample_order=upsample_order
        )
        logger(f"Binned multi-point stability data saved: {full_path}")

    return {
        'stability_cube': stability_cube,
        'freq_array': freq_array,
        'slope_array': slope_array,
        'parity_list': parity_list,
        'baseline_array': baseline_array,
        'bin_x': bin_x,
        'bin_y': bin_y,
        'settings': settings,
        'elapsed_time': elapsed_time,
        'ny': ny,
        'nx': nx
    }


def run_stability_measurement(
    fixed_freq,
    ref_freq,
    num_samples,
    settings,
    simulation_mode=False,
    show_progress=True,
    save_data=False,
    save_path=None,
    subfolder="",
    logger=None
):
    """
    High-level function to acquire stability/noise data at a fixed frequency.

    Performs repeated sig/ref measurements at a single MW frequency to characterize
    magnetometer noise and stability. Handles initialization, acquisition, cleanup,
    and optional data saving.

    Parameters
    ----------
    fixed_freq : float
        MW frequency to measure at (GHz), typically an inflection point.
    ref_freq : float
        Reference frequency for normalization (GHz).
    num_samples : int
        Number of time-points to acquire.
    settings : dict
        Nested settings dictionary (camera, srs, simulation configs).
    simulation_mode : bool
        If True, generate synthetic data.
    show_progress : bool
        If True, display tqdm progress bar.
    save_data : bool
        If True, save the stability cube to .npz file.
    save_path : str or Path or None
        Base directory for saving. Uses default if None.
    subfolder : str
        Subfolder within save_path.
    logger : callable or None
        Optional logging function.

    Returns
    -------
    dict
        Dictionary containing:
        - 'stability_cube': np.ndarray of shape (num_samples, ny, nx)
        - 'settings': copy of acquisition settings for later analysis
        - 'elapsed_time': total acquisition time in seconds
        - 'ny', 'nx': image dimensions
    """
    from tqdm.auto import tqdm as tqdm_auto

    if logger is None:
        logger = print

    # Initialize system
    logger("Initializing stability measurement...")
    sys_config = initialize_system(simulation_mode, settings, logger=logger)
    ny, nx = sys_config['ny'], sys_config['nx']

    # Allocate data cube (time x height x width)
    stability_cube = np.zeros((num_samples, ny, nx), dtype=np.float32)

    # Acquisition loop
    start_time = time.perf_counter()
    pbar_context = tqdm_auto(total=num_samples, unit="pt", desc="Stability Measurement",
                              disable=not show_progress)

    try:
        with pbar_context as pbar:
            run_stability_check(fixed_freq, ref_freq, settings, sys_config, stability_cube, pbar)

    finally:
        # Cleanup
        if not simulation_mode:
            if sys_config.get('camera_instance'):
                basler.close_instance(sys_config['camera_instance'])
            if sys_config.get('sg384'):
                sys_config['sg384'].close_connection()

    elapsed_time = time.perf_counter() - start_time
    logger(f"\nStability measurement complete: {num_samples} points in {elapsed_time:.2f} seconds.")

    # Save if requested
    if save_data:
        if save_path is None:
            save_path = Path(r"E:\MTB project\CW ODMR")
        else:
            save_path = Path(save_path)

        save_dir = save_path / subfolder
        save_dir.mkdir(parents=True, exist_ok=True)

        filename = f"stability_data_{num_samples}pts.npz"
        full_path = save_dir / filename

        np.savez_compressed(
            full_path,
            data=stability_cube,
            fixed_freq=fixed_freq,
            ref_freq=ref_freq,
            num_samples=num_samples
        )
        logger(f"Stability data saved: {full_path}")

    return {
        'stability_cube': stability_cube,
        'settings': settings,
        'elapsed_time': elapsed_time,
        'ny': ny,
        'nx': nx,
        'fixed_freq': fixed_freq,
        'ref_freq': ref_freq
    }


def run_stability_check(fixed_freq, ref_freq, settings, handles, stability_cube, pbar):
    """
    Repeatedly measures the same frequency to analyze noise/stability.
    (Low-level worker function called by run_stability_measurement.)
    """
    sg384 = handles['sg384']
    camera = handles['camera_instance']
    settling_time = settings['srs']['settling_time']
    n_frames = settings['camera']['n_frames']
    num_measurements = stability_cube.shape[0]

    for i in range(num_measurements):
        t0 = time.perf_counter()

        # Measure at the fixed frequency
        measure_odmr_point(
            sg384, camera, fixed_freq, ref_freq,
            settling_time, n_frames, stability_cube, i
        )

        # UI Update
        pbar.update(1)
        pbar.set_postfix(idx=f"{i+1}/{num_measurements}", loop=f"{time.perf_counter()-t0:.2f}s")


def analyze_stability_data(
    stability_cube,
    acquisition_settings=None,
    peak_params=None,
    slope_override=None,
    time_per_point_override=None,
    outlier_sigma=4.0,
    show_plot=True,
    save_fig=False,
    save_path=None,
    subfolder=""
):
    """
    Analyzes stability data to compute magnetometer sensitivity.

    Automatically extracts max slope from ODMR peak_params and calculates time-per-point
    from acquisition settings. Allows manual override of both parameters.

    Parameters
    ----------
    stability_cube : np.ndarray
        3D array of shape (num_samples, ny, nx) with S/R measurements over time.
    acquisition_settings : dict or None
        Settings dict with 'camera' and 'srs' configs. Used to auto-calculate time_per_point.
        If None and time_per_point_override is None, will prompt for manual input.
    peak_params : list of dict or None
        Peak parameters from ODMR analysis (output of analyze_and_plot_odmr).
        If provided, uses max_slope from the first peak. Can be overridden by slope_override.
    slope_override : float or None
        Manual override for contrast slope (unitless/MHz). If None, extracted from peak_params.
    time_per_point_override : float or None
        Manual override for time per S/R measurement (seconds). If None, calculated from settings.
    outlier_sigma : float
        Sigma threshold for outlier removal (default 4.0).
    show_plot : bool
        If True, display analysis plots.
    save_fig : bool
        If True, save the figure.
    save_path : str or Path or None
        Base path for saving figures.
    subfolder : str
        Subfolder within save_path.

    Returns
    -------
    dict
        Dictionary containing:
        - 'global_sensitivity': float, global averaged sensitivity (µT/√Hz)
        - 'median_pixel_sensitivity': float, median per-pixel sensitivity (µT/√Hz)
        - 'pixel_sensitivity_map': 2D array of per-pixel sensitivities
        - 'raw_series': 1D array of spatially-averaged S/R values over time
        - 'clean_series': 1D array after outlier removal
        - 'num_outliers': int, number of outliers removed
        - 'slope_used': float, slope value used in calculation
        - 'time_per_point_used': float, time per point used in calculation
        - 'figure': matplotlib Figure object (if show_plot or save_fig)
    """
    GAMMA_E_MHZ_MT = 28.024  # GHz/T = MHz/mT

    # 1. Determine slope (contrast per MHz)
    if slope_override is not None:
        slope_c_per_mhz = slope_override
        print(f"Using manual slope override: {slope_c_per_mhz:.6f} per MHz")
    elif peak_params is not None and len(peak_params) > 0:
        # Use max_slope from first peak (convert GHz^-1 to MHz^-1)
        slope_c_per_mhz = peak_params[0]['max_slope'] / 1000  # GHz^-1 to MHz^-1
        print(f"Extracted slope from ODMR peak 1: {slope_c_per_mhz:.6f} per MHz")
    else:
        raise ValueError(
            "Cannot determine slope: either provide peak_params from ODMR analysis "
            "or set slope_override manually."
        )

    # 2. Determine time per point
    if time_per_point_override is not None:
        time_per_point_s = time_per_point_override
        print(f"Using manual time override: {time_per_point_s:.4f} s per point")
    elif acquisition_settings is not None:
        # Calculate from settings: 2 * (exposure * n_frames + settling_time)
        exp_time_us = acquisition_settings['camera']['exposure_time_us']
        n_frames = acquisition_settings['camera']['n_frames']
        settling_s = acquisition_settings['srs']['settling_time']

        grab_time_s = (exp_time_us * 1e-6) * n_frames  # exposure time per grab
        time_per_point_s = 2 * (grab_time_s + settling_s)  # sig + ref
        print(f"Calculated time per point from settings: {time_per_point_s:.4f} s")
    else:
        raise ValueError(
            "Cannot determine time per point: either provide acquisition_settings "
            "or set time_per_point_override manually."
        )

    # 3. Outlier removal
    raw_series = np.nanmean(stability_cube, axis=(1, 2))
    initial_mean = np.nanmean(raw_series)
    initial_std = np.nanstd(raw_series)

    mask = np.abs(raw_series - initial_mean) <= (outlier_sigma * initial_std)
    clean_indices = np.where(mask)[0]
    clean_series = raw_series[mask]
    num_outliers = np.sum(~mask)

    print(f"Outlier removal: {num_outliers} outliers removed ({outlier_sigma}σ threshold)")

    # 4. Per-pixel noise
    filtered_cube = stability_cube[mask, :, :]
    pixel_sd_map = np.nanstd(filtered_cube, axis=0)

    # 5. Sensitivity calculation
    def calculate_sensitivity(sd_signal):
        sigma_f_mhz = sd_signal / abs(slope_c_per_mhz)
        sigma_b_mt = sigma_f_mhz / GAMMA_E_MHZ_MT
        return (sigma_b_mt * 1000) * np.sqrt(time_per_point_s)  # µT/√Hz

    global_noise_std = np.std(clean_series)
    global_sensitivity = calculate_sensitivity(global_noise_std)
    pixel_sensitivity_map = calculate_sensitivity(pixel_sd_map)
    median_pixel_sensitivity = np.nanmedian(pixel_sensitivity_map)

    print(f"\n{'='*60}")
    print("SENSITIVITY ANALYSIS RESULTS")
    print(f"{'='*60}")
    print(f"Global Averaged Sensitivity: {global_sensitivity:.3f} µT/√Hz")
    print(f"Median Per-Pixel Sensitivity: {median_pixel_sensitivity:.3f} µT/√Hz")
    print(f"Mean Pixel SD: {np.nanmean(pixel_sd_map):.6e}")
    print(f"{'='*60}")

    # 6. Plotting
    fig = None
    if show_plot or save_fig:
        fig = plt.figure(figsize=(16, 10))
        gs = fig.add_gridspec(2, 2)

        # A: Time series
        ax1 = fig.add_subplot(gs[0, 0])
        ax1.plot(clean_indices, clean_series, color='teal', marker='.', markersize=4, linestyle='-')
        ax1.set_title(f"Global Stability ({num_outliers} outliers removed)")
        ax1.set_ylabel("Contrast (S/R)")
        ax1.set_xlabel("Sample Index")
        ax1.grid(True, alpha=0.3)

        # B: Pixel sensitivity map
        vmax_focus = np.nanpercentile(pixel_sensitivity_map, 75)
        ax2 = fig.add_subplot(gs[0, 1])
        im = ax2.imshow(pixel_sensitivity_map, cmap='viridis', vmin=0, vmax=vmax_focus)
        ax2.set_title(r"Pixel Sensitivity Map (µT/√Hz)")
        fig.colorbar(im, ax=ax2, label=r"µT/√Hz")

        # C: Global distribution
        ax3 = fig.add_subplot(gs[1, 0])
        ax3.hist(clean_series, bins=30, color='teal', alpha=0.7, edgecolor='black')
        ax3.set_title("Global S/R Distribution")
        ax3.set_xlabel("S/R Value")
        ax3.set_ylabel("Count")

        # D: Pixel sensitivity distribution
        ax4 = fig.add_subplot(gs[1, 1])
        ax4.hist(pixel_sensitivity_map.flatten(), bins=50, color='purple', alpha=0.7)
        ax4.axvline(median_pixel_sensitivity, color='red', linestyle='--',
                    label=f'Median: {median_pixel_sensitivity:.2f} µT/√Hz')
        ax4.set_title("Pixel Sensitivity Distribution")
        ax4.set_xlabel(r"µT/√Hz")
        ax4.set_ylabel("Count")
        ax4.legend()

        fig.tight_layout()

        if save_fig:
            if save_path is None:
                save_path = Path(r"E:\MTB project\CW ODMR")
            save_qdm_figure(fig, base_filename="stability_analysis",
                            subfolder=subfolder, base_path=save_path)

        if show_plot:
            plt.show()

    return {
        'global_sensitivity': global_sensitivity,
        'median_pixel_sensitivity': median_pixel_sensitivity,
        'pixel_sensitivity_map': pixel_sensitivity_map,
        'pixel_sd_map': pixel_sd_map,
        'raw_series': raw_series,
        'clean_series': clean_series,
        'clean_indices': clean_indices,
        'num_outliers': num_outliers,
        'slope_used': slope_c_per_mhz,
        'time_per_point_used': time_per_point_s,
        'figure': fig
    }


def select_inflection_point(peak_params, manual_freq=None, side='left', peak_index=0, verbose=True):
    """
    Select inflection point frequency from ODMR analysis, with auto-detection and manual override.

    Parameters
    ----------
    peak_params : list of dict or None
        Peak parameters from ODMR analysis (output of analyze_and_plot_odmr).
        Each peak dict contains 'inflection_pts': (low_freq, high_freq).
    manual_freq : float or None
        Manual frequency override (GHz). If provided, this value is used directly.
    side : str
        Which inflection point to use: 'left' (lower frequency) or 'right' (higher frequency).
        Only used if manual_freq is None. Default 'left'.
    peak_index : int
        Which peak to use (0 = first peak, 1 = second peak, etc.). Default 0.
    verbose : bool
        If True, print selection information.

    Returns
    -------
    float
        Selected inflection point frequency in GHz.

    Raises
    ------
    ValueError
        If peak_params is not available and manual_freq is not provided.

    Examples
    --------
    # Auto-detect left inflection point from first peak
    freq = select_inflection_point(peak_params)

    # Use right inflection point
    freq = select_inflection_point(peak_params, side='right')

    # Manual override
    freq = select_inflection_point(peak_params, manual_freq=2.52000)
    """
    if manual_freq is not None:
        # Manual override
        if verbose:
            print(f"{'='*60}")
            print(f"MANUAL INFLECTION POINT OVERRIDE")
            print(f"{'='*60}")
            print(f"Using manually specified frequency: {manual_freq:.6f} GHz")
            print(f"{'='*60}\n")
        return manual_freq

    # Auto-detect from peak_params
    if peak_params is None or len(peak_params) == 0:
        raise ValueError(
            "Cannot auto-detect inflection point: peak_params not available. "
            "Please run ODMR analysis first or provide manual_freq."
        )

    if peak_index >= len(peak_params):
        raise ValueError(
            f"Peak index {peak_index} out of range. Only {len(peak_params)} peak(s) available."
        )

    inflection_pts = peak_params[peak_index]['inflection_pts']
    left_freq = inflection_pts[0]
    right_freq = inflection_pts[1]

    if side.lower() == 'left':
        selected_freq = left_freq
        other_freq = right_freq
        side_label = "LEFT (lower frequency)"
        other_label = "RIGHT"
    elif side.lower() == 'right':
        selected_freq = right_freq
        other_freq = left_freq
        side_label = "RIGHT (higher frequency)"
        other_label = "LEFT"
    else:
        raise ValueError(f"Invalid side '{side}'. Must be 'left' or 'right'.")

    if verbose:
        print(f"{'='*60}")
        print(f"AUTO-DETECTED INFLECTION POINT")
        print(f"{'='*60}")
        print(f"Using {side_label} inflection point from Peak {peak_index + 1}:")
        print(f"  Selected: {selected_freq:.6f} GHz")
        print(f"  (Other {other_label} inflection point: {other_freq:.6f} GHz)")
        if len(peak_params) > 1:
            print(f"  ({len(peak_params)} peaks detected - using peak {peak_index + 1})")
        print(f"{'='*60}\n")

    return selected_freq


def analyze_inflection_point_magnetometry(
    stability_cube,
    acquisition_settings=None,
    peak_params=None,
    slope_override=None,
    inflection_freq=None,
    outlier_sigma=4.0,
    reference_mode='global_mean',
    reference_roi=None,
    show_plot=True,
    save_fig=False,
    save_data=False,
    save_path=None,
    subfolder="",
    denoise_method='none',
    **denoise_kwargs
):
    """
    Analyzes stability data at inflection point to generate widefield magnetic field map.

    Similar to analyze_stability_data but instead of computing noise/sensitivity,
    this function extracts the mean signal at each pixel and converts it to a
    relative magnetic field map using the ODMR slope at the inflection point.

    The workflow matches process_widefield_odmr: applies optional denoising to the raw
    field map, computes processed map (raw - denoised) to remove large-scale background,
    and displays all three (raw, denoised, processed) in a 3-panel comparison plot.

    Parameters
    ----------
    stability_cube : np.ndarray
        3D array of shape (num_samples, ny, nx) with S/R measurements over time.
    acquisition_settings : dict or None
        Settings dict with 'camera' and 'srs' configs (for metadata only).
    peak_params : list of dict or None
        Peak parameters from ODMR analysis. Used to extract slope at inflection point.
    slope_override : float or None
        Manual override for contrast slope (unitless/MHz). If None, extracted from peak_params.
    inflection_freq : float or None
        The MW frequency (GHz) at which data was acquired (for metadata).
    outlier_sigma : float
        Sigma threshold for temporal outlier removal at each pixel (default 4.0).
    reference_mode : str
        How to establish the magnetic field zero reference. Options:
        - 'global_mean': Use spatial mean across all pixels (default)
        - 'roi': Use mean within specified ROI
        - 'temporal': Use temporal mean at each pixel (shows only temporal variations)
    reference_roi : tuple or None
        If reference_mode='roi', specify as (y_start, y_end, x_start, x_end).
    show_plot : bool
        If True, display field map and analysis plots.
    save_fig : bool
        If True, save the figures.
    save_data : bool
        If True, save field map and metadata to .npz file.
    save_path : str or Path or None
        Base path for saving data and figures.
    subfolder : str
        Subfolder within save_path.
    denoise_method : str
        Denoising method for field map. Options: 'none', 'gaussian', 'tv',
        'wavelet', 'nlm', 'bilateral'. Default 'none'.
    **denoise_kwargs
        Additional arguments passed to denoise_field_map().

    Returns
    -------
    dict
        Dictionary containing:
        - 'field_map_gauss': 2D array of processed magnetic field (raw - denoised) in Gauss
        - 'field_map_gauss_raw': 2D array of raw magnetic field before processing in Gauss
        - 'field_map_gauss_denoised': 2D array of denoised magnetic field in Gauss
        - 'field_map_gauss_processed': 2D array of processed magnetic field (raw - denoised) in Gauss
        - 'mean_contrast_map': 2D array of mean S/R at each pixel
        - 'noise_map': 2D array of temporal SD at each pixel
        - 'outlier_count_map': 2D array of number of outliers removed per pixel
        - 'reference_contrast': float, reference S/R value used for field calculation
        - 'slope_used': float, slope value used (unitless/MHz)
        - 'inflection_freq': float, MW frequency (GHz)
        - 'figure': matplotlib Figure object with 3-panel comparison (if show_plot or save_fig)
    """
    GAMMA_E_MHZ_MT = 28.024  # MHz/mT
    GAMMA_E_GHZ_T = 28.024   # GHz/T

    # 1. Determine slope (contrast per MHz) with CORRECT SIGN
    if slope_override is not None:
        slope_c_per_mhz = slope_override
        print(f"Using manual slope override: {slope_c_per_mhz:.6f} per MHz")
    elif peak_params is not None and len(peak_params) > 0:
        # Determine which inflection point (left or right) we're measuring at
        # This is CRITICAL for getting the correct sign!

        if inflection_freq is not None:
            # Get inflection point frequencies from first peak
            peak = peak_params[0]
            left_freq, right_freq = peak['inflection_pts']

            # Determine which inflection point is closer to our measurement frequency
            dist_to_left = abs(inflection_freq - left_freq)
            dist_to_right = abs(inflection_freq - right_freq)

            if dist_to_left < dist_to_right:
                # Measuring at LEFT inflection → NEGATIVE slope
                # (as freq increases, PL decreases going down left side of dip)
                slope_c_per_ghz = -peak['max_slope']
                inflection_side = "left"
            else:
                # Measuring at RIGHT inflection → POSITIVE slope
                # (as freq increases, PL increases going up right side of dip)
                slope_c_per_ghz = peak['max_slope']
                inflection_side = "right"

            slope_c_per_mhz = slope_c_per_ghz / 1000  # GHz^-1 to MHz^-1
            print(f"Detected {inflection_side} inflection point at {inflection_freq:.6f} GHz")
            print(f"Using SIGNED slope: {slope_c_per_mhz:.6f} per MHz")
        else:
            # No inflection_freq provided - use magnitude as fallback
            # WARNING: This will give WRONG sign for right inflection points!
            slope_c_per_mhz = peak_params[0]['max_slope'] / 1000
            print(f"WARNING: inflection_freq not provided, using MAGNITUDE of slope")
            print(f"Extracted slope from ODMR peak 1: {slope_c_per_mhz:.6f} per MHz (unsigned)")
            print(f"This will give INCORRECT sign if measuring at right inflection point!")
    else:
        raise ValueError(
            "Cannot determine slope: either provide peak_params from ODMR analysis "
            "or set slope_override manually."
        )

    num_samples, ny, nx = stability_cube.shape
    print(f"\nProcessing inflection point magnetometry data...")
    print(f"Data shape: {num_samples} samples × {ny}×{nx} pixels")
    print(f"Reference mode: {reference_mode}")

    # 2. Per-pixel outlier removal and statistics (VECTORIZED for speed)
    print("Computing per-pixel statistics with outlier removal (vectorized)...")

    # Compute initial mean and std for all pixels at once
    initial_mean = np.nanmean(stability_cube, axis=0)  # Shape: (ny, nx)
    initial_std = np.nanstd(stability_cube, axis=0)    # Shape: (ny, nx)

    # Create outlier mask for entire cube using broadcasting
    # stability_cube shape: (num_samples, ny, nx)
    # initial_mean/std shape: (ny, nx)
    # Broadcasting: stability_cube[t, y, x] - initial_mean[y, x] for all t
    deviation = np.abs(stability_cube - initial_mean[None, :, :])
    threshold = outlier_sigma * initial_std[None, :, :]
    mask = deviation <= threshold  # Shape: (num_samples, ny, nx), True = keep

    # Count outliers per pixel
    outlier_count_map = np.sum(~mask, axis=0).astype(np.int32)  # Shape: (ny, nx)

    # Set outliers to NaN for clean statistics
    masked_cube = stability_cube.copy()
    masked_cube[~mask] = np.nan

    # Compute mean and std with outliers excluded (vectorized)
    mean_contrast_map = np.nanmean(masked_cube, axis=0).astype(np.float32)  # Shape: (ny, nx)
    noise_map = np.nanstd(masked_cube, axis=0).astype(np.float32)          # Shape: (ny, nx)

    total_outliers = np.sum(outlier_count_map)
    print(f"Outlier removal: {total_outliers} outliers removed ({outlier_sigma}σ threshold)")

    # 3. Establish reference contrast value (zero field reference)
    if reference_mode == 'global_mean':
        reference_contrast = np.nanmean(mean_contrast_map)
        print(f"Using global spatial mean as reference: {reference_contrast:.6f}")
    elif reference_mode == 'roi':
        if reference_roi is None:
            raise ValueError("reference_roi must be specified when reference_mode='roi'")
        y0, y1, x0, x1 = reference_roi
        reference_contrast = np.nanmean(mean_contrast_map[y0:y1, x0:x1])
        print(f"Using ROI mean as reference: {reference_contrast:.6f} (ROI: y={y0}:{y1}, x={x0}:{x1})")
    elif reference_mode == 'temporal':
        # Each pixel is its own reference (shows temporal variations only)
        reference_contrast = None
        print("Using per-pixel temporal mean (field map shows temporal variations)")
    else:
        raise ValueError(f"Invalid reference_mode: {reference_mode}")

    # 4. Convert contrast to magnetic field
    # At inflection point: ΔC = slope * Δf, and Δf = γ_e * ΔB
    # Therefore: ΔB = ΔC / (slope * γ_e)

    if reference_mode == 'temporal':
        # Already at mean, so field map would be zero. This mode doesn't make sense for magnetometry
        raise ValueError("reference_mode='temporal' is not meaningful for magnetometry (use analyze_stability_data for noise analysis)")

    contrast_deviation = mean_contrast_map - reference_contrast

    # Convert to frequency shift (MHz)
    freq_shift_mhz = contrast_deviation / slope_c_per_mhz

    # Convert to magnetic field (Gauss)
    # freq (MHz) = γ_e (MHz/mT) * B (mT)
    # B (mT) = freq (MHz) / γ_e (MHz/mT)
    # B (Gauss) = B (mT) * 10
    field_map_mt = freq_shift_mhz / GAMMA_E_MHZ_MT
    field_map_gauss_raw = field_map_mt * 10  # mT to Gauss

    print(f"\nField map statistics (raw):")
    print(f"  Mean: {np.nanmean(field_map_gauss_raw):.4f} Gauss")
    print(f"  Std: {np.nanstd(field_map_gauss_raw):.4f} Gauss")
    print(f"  Range: [{np.nanmin(field_map_gauss_raw):.4f}, {np.nanmax(field_map_gauss_raw):.4f}] Gauss")

    # 5. Denoising and processing (always applied, even when method='none')
    print(f"\nApplying denoising (method='{denoise_method}') and computing (raw - denoised)...")
    field_map_gauss_denoised = denoise_field_map(
        field_map_gauss_raw,
        method=denoise_method,
        **denoise_kwargs
    )
    field_map_gauss_processed = field_map_gauss_raw - field_map_gauss_denoised
    field_map_gauss = field_map_gauss_processed  # Final output is the processed map

    print(f"Raw field range: {np.nanmin(field_map_gauss_raw):.3f} to {np.nanmax(field_map_gauss_raw):.3f} Gauss")
    print(f"Denoised field range: {np.nanmin(field_map_gauss_denoised):.3f} to {np.nanmax(field_map_gauss_denoised):.3f} Gauss")
    print(f"Processed (raw-denoised) range: {np.nanmin(field_map_gauss_processed):.3f} to {np.nanmax(field_map_gauss_processed):.3f} Gauss")

    # 6. Plotting (always show 3-panel comparison)
    fig = None
    if show_plot or save_fig:
        # Create 3-panel comparison plot: Raw | Denoised | Processed
        fig = plot_field_map_comparison(
            field_map_gauss_raw,
            field_map_gauss_denoised,
            field_map_gauss_processed,
            method_name=denoise_method.upper()
        )

        fig.tight_layout()

        if save_fig:
            if save_path is None:
                save_path = Path(r"E:\MTB project\CW ODMR")
            save_qdm_figure(fig, base_filename="inflection_magnetometry",
                            subfolder=subfolder, base_path=save_path)

        if show_plot:
            plt.show()

    # 7. Save data if requested
    if save_data:
        if save_path is None:
            save_path = Path(r"E:\MTB project\CW ODMR")

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"inflection_magnetometry_{ny}x{nx}_{timestamp}.npz"
        full_path = Path(save_path) / subfolder / filename
        full_path.parent.mkdir(parents=True, exist_ok=True)

        save_dict = {
            'field_map_gauss_raw': field_map_gauss_raw,
            'field_map_gauss_denoised': field_map_gauss_denoised,
            'field_map_gauss_processed': field_map_gauss_processed,
            'field_map_gauss': field_map_gauss_processed,  # Alias for backwards compatibility
            'mean_contrast_map': mean_contrast_map,
            'noise_map': noise_map,
            'outlier_count_map': outlier_count_map,
            'reference_contrast': reference_contrast,
            'slope_used': slope_c_per_mhz,
            'inflection_freq': inflection_freq,
            'reference_mode': reference_mode,
            'outlier_sigma': outlier_sigma,
            'denoise_method': denoise_method
        }

        if reference_roi is not None:
            save_dict['reference_roi'] = reference_roi

        np.savez_compressed(full_path, **save_dict)
        print(f"\n✅ Magnetometry data saved: {filename}")

    return {
        'field_map_gauss': field_map_gauss,  # Processed map (raw - denoised)
        'field_map_gauss_raw': field_map_gauss_raw,
        'field_map_gauss_denoised': field_map_gauss_denoised,
        'field_map_gauss_processed': field_map_gauss_processed,
        'mean_contrast_map': mean_contrast_map,
        'noise_map': noise_map,
        'outlier_count_map': outlier_count_map,
        'reference_contrast': reference_contrast,
        'slope_used': slope_c_per_mhz,
        'inflection_freq': inflection_freq,
        'figure': fig
    }


def analyze_multi_point_magnetometry(
    stability_cube,
    outlier_sigma=4.0,
    reference_mode='global_mean',
    reference_roi=None,
    denoise_method='gaussian',
    show_plot=True,
    save_fig=False,
    save_data=False,
    save_path=None,
    subfolder="",
    **denoise_kwargs
):
    """
    Analyze multi-point differential magnetometry data and generate field maps.

    Takes stability data that's already been converted to frequency shifts (GHz)
    by measure_multi_point(), applies outlier removal, establishes a reference
    frequency, converts relative frequency shifts to magnetic field, applies
    denoising, and generates 3-panel visualization.

    Parameters
    ----------
    stability_cube : np.ndarray
        3D array of frequency shifts (num_samples, ny, nx) in GHz.
        Already converted from PL by measure_multi_point().
    outlier_sigma : float
        Number of standard deviations for outlier removal threshold.
    reference_mode : str
        How to establish zero-field reference:
        - 'global_mean': Use spatial mean of entire image as reference
        - 'roi': Use mean of specified ROI as reference
    reference_roi : tuple or None
        ROI coordinates (y0, y1, x0, x1) for reference_mode='roi'.
    denoise_method : str
        Denoising method: 'none', 'gaussian', 'tv', 'wavelet', 'nlm', 'bilateral'.
    show_plot : bool
        If True, display the 3-panel field map plot.
    save_fig : bool
        If True, save the figure to disk.
    save_data : bool
        If True, save field maps to .npz file.
    save_path : str or Path or None
        Base directory for saving. Uses default if None.
    subfolder : str
        Subfolder for saving data and figures.
    **denoise_kwargs
        Additional parameters for denoising (e.g., gaussian_sigma=1.0).

    Returns
    -------
    dict
        Dictionary containing:
        - 'field_map_gauss_raw': raw magnetic field map (Gauss)
        - 'field_map_gauss_denoised': denoised field map (Gauss)
        - 'field_map_gauss_processed': processed (raw - denoised) field map (Gauss)
        - 'mean_freq_shift': mean frequency shift map (GHz)
        - 'reference_freq': reference frequency used (GHz)
        - 'noise_freq': frequency noise map (GHz)
        - 'field_noise_gauss': magnetic field noise map (Gauss)
        - 'outlier_count_map': number of outliers removed per pixel
        - 'figure': matplotlib figure object
    """
    import matplotlib.pyplot as plt

    GAMMA_E_GHZ_PER_GAUSS = 0.0028024  # NV gyromagnetic ratio (GHz/Gauss)

    num_samples, ny, nx = stability_cube.shape

    print(f"\nProcessing multi-point magnetometry data...")
    print(f"Data shape: {num_samples} samples × {ny}×{nx} pixels")
    print(f"Reference mode: {reference_mode}")

    # =========================================================================
    # Outlier Removal
    # =========================================================================
    print("Computing per-pixel statistics with outlier removal...")

    initial_mean = np.nanmean(stability_cube, axis=0)  # (ny, nx)
    initial_std = np.nanstd(stability_cube, axis=0)
    deviation = np.abs(stability_cube - initial_mean[None, :, :])
    threshold = outlier_sigma * initial_std[None, :, :]
    mask = deviation <= threshold
    outlier_count_map = np.sum(~mask, axis=0).astype(np.int32)

    # Apply mask
    masked_cube = stability_cube.copy()
    masked_cube[~mask] = np.nan

    # Compute mean frequency shift and noise
    mean_freq_shift = np.nanmean(masked_cube, axis=0).astype(np.float32)  # GHz
    noise_freq = np.nanstd(masked_cube, axis=0).astype(np.float32)  # GHz

    total_outliers = np.sum(outlier_count_map)
    print(f"Outlier removal: {total_outliers} outliers removed ({outlier_sigma}σ threshold)")

    # =========================================================================
    # Establish Reference Frequency (Zero Field Reference)
    # =========================================================================
    # CRITICAL: We need to compute relative frequency shifts from a reference
    # to get spatial variation in the magnetic field map

    if reference_mode == 'global_mean':
        reference_freq = np.nanmean(mean_freq_shift)
        print(f"Using global spatial mean as reference: {reference_freq:.6f} GHz")
    elif reference_mode == 'roi':
        if reference_roi is None:
            raise ValueError("reference_roi must be specified when reference_mode='roi'")
        y0, y1, x0, x1 = reference_roi
        reference_freq = np.nanmean(mean_freq_shift[y0:y1, x0:x1])
        print(f"Using ROI mean as reference: {reference_freq:.6f} GHz (ROI: y={y0}:{y1}, x={x0}:{x1})")
    else:
        raise ValueError(f"Invalid reference_mode: {reference_mode}")

    # Compute frequency deviation from reference
    freq_deviation = mean_freq_shift - reference_freq

    # =========================================================================
    # Convert Frequency Deviation to Magnetic Field
    # =========================================================================
    # B (Gauss) = freq_shift (GHz) / gamma_e (GHz/Gauss)
    field_map_gauss_raw = freq_deviation / GAMMA_E_GHZ_PER_GAUSS
    field_noise_gauss = noise_freq / GAMMA_E_GHZ_PER_GAUSS

    print(f"\nField map statistics (raw):")
    print(f"  Mean: {np.nanmean(field_map_gauss_raw):.4f} Gauss")
    print(f"  Std: {np.nanstd(field_map_gauss_raw):.4f} Gauss")
    print(f"  Range: [{np.nanmin(field_map_gauss_raw):.4f}, {np.nanmax(field_map_gauss_raw):.4f}] Gauss")

    # =========================================================================
    # Apply Denoising
    # =========================================================================
    field_map_gauss_denoised = denoise_field_map(
        field_map_gauss_raw, method=denoise_method, **denoise_kwargs
    )

    # Compute processed map (raw - denoised)
    field_map_gauss_processed = field_map_gauss_raw - field_map_gauss_denoised

    # =========================================================================
    # Create 3-Panel Plot
    # =========================================================================
    fig = None
    if show_plot or save_fig:
        fig = plot_field_map_comparison(
            field_map_gauss_raw,
            field_map_gauss_denoised,
            field_map_gauss_processed,
            method_name=denoise_method.upper()
        )

        if show_plot:
            plt.show()

    # =========================================================================
    # Save Results
    # =========================================================================
    if save_fig and fig is not None:
        if save_path is None:
            save_qdm_figure(
                fig,
                base_filename="multipoint_field_map",
                subfolder=subfolder
            )
        else:
            save_qdm_figure(
                fig,
                base_filename="multipoint_field_map",
                subfolder=subfolder,
                base_path=save_path
            )

    if save_data:
        if save_path is None:
            save_path = Path(r"E:\MTB project\CW ODMR")
        else:
            save_path = Path(save_path)

        save_dir = save_path / subfolder
        save_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"multipoint_field_maps_{timestamp}.npz"
        full_path = save_dir / filename

        np.savez_compressed(
            full_path,
            field_map_gauss_raw=field_map_gauss_raw,
            field_map_gauss_denoised=field_map_gauss_denoised,
            field_map_gauss_processed=field_map_gauss_processed,
            mean_freq_shift=mean_freq_shift,
            reference_freq=reference_freq,
            noise_freq=noise_freq,
            field_noise_gauss=field_noise_gauss,
            outlier_count_map=outlier_count_map,
            denoise_method=denoise_method,
            outlier_sigma=outlier_sigma,
            reference_mode=reference_mode
        )
        print(f"Multi-point field maps saved: {full_path}")

    # =========================================================================
    # Print Summary Statistics
    # =========================================================================
    print("\n" + "="*60)
    print("4-POINT DIFFERENTIAL MAGNETOMETRY RESULTS")
    print("="*60)
    print(f"Mean frequency shift: {np.nanmean(mean_freq_shift)*1000:.3f} MHz")
    print(f"Frequency noise (std): {np.nanmean(noise_freq)*1000:.3f} MHz")
    print(f"Mean magnetic field: {np.nanmean(field_map_gauss_raw):.3f} Gauss")
    print(f"Field noise (std): {np.nanmean(field_noise_gauss):.3f} Gauss")
    print(f"Total outliers removed: {np.sum(outlier_count_map)}")
    print("="*60)

    return {
        'field_map_gauss_raw': field_map_gauss_raw,
        'field_map_gauss_denoised': field_map_gauss_denoised,
        'field_map_gauss_processed': field_map_gauss_processed,
        'mean_freq_shift': mean_freq_shift,
        'reference_freq': reference_freq,
        'noise_freq': noise_freq,
        'field_noise_gauss': field_noise_gauss,
        'outlier_count_map': outlier_count_map,
        'figure': fig
    }


def analyze_allan_variance(
    sensitivity_result,
    show_plot=True,
    save_fig=False,
    save_path=None,
    subfolder=""
):
    """
    Compute and plot Allan deviation for magnetometer stability characterization.

    Uses cleaned time series and parameters from sensitivity analysis to compute
    overlapping Allan deviation (OADEV) and compare against shot-noise limit.

    Parameters
    ----------
    sensitivity_result : dict
        Output from analyze_stability_data(), must contain 'clean_series',
        'slope_used', and 'time_per_point_used'.
    show_plot : bool
        If True, display the Allan deviation plot.
    save_fig : bool
        If True, save the figure.
    save_path : str or Path or None
        Base path for saving figures.
    subfolder : str
        Subfolder within save_path.

    Returns
    -------
    dict
        Dictionary containing:
        - 'taus': np.ndarray, integration times (s)
        - 'adevs': np.ndarray, Allan deviations (µT)
        - 'errors': np.ndarray, error bars
        - 'ns': np.ndarray, number of samples per tau
        - 'figure': matplotlib Figure object (if show_plot or save_fig)

    Notes
    -----
    Requires the `allantools` package: pip install allantools
    """
    try:
        import allantools
    except ImportError:
        raise ImportError(
            "allantools package required for Allan variance analysis. "
            "Install with: pip install allantools"
        )

    GAMMA_E_MHZ_MT = 28.024  # MHz/mT

    # Extract parameters from sensitivity analysis
    clean_series = sensitivity_result['clean_series']
    slope_c_per_mhz = sensitivity_result['slope_used']
    time_per_point_s = sensitivity_result['time_per_point_used']

    # Convert S/R series to magnetic field (µT)
    freq_noise_mhz = (clean_series - np.mean(clean_series)) / abs(slope_c_per_mhz)
    mag_noise_ut = (freq_noise_mhz / GAMMA_E_MHZ_MT) * 1000

    # Calculate overlapping Allan deviation
    sampling_rate = 1 / time_per_point_s
    (taus, adevs, errors, ns) = allantools.oadev(
        mag_noise_ut,
        rate=sampling_rate,
        data_type="freq",
        taus="octave"
    )

    print(f"\n{'='*60}")
    print("ALLAN DEVIATION ANALYSIS")
    print(f"{'='*60}")
    print(f"Sampling rate: {sampling_rate:.2f} Hz")
    print(f"Tau range: {taus[0]:.3f} s to {taus[-1]:.1f} s")
    print(f"Allan deviation at τ=1s: {np.interp(1.0, taus, adevs):.3f} µT")
    print(f"{'='*60}")

    # Plot
    fig = None
    if show_plot or save_fig:
        fig, ax = plt.subplots(figsize=(8, 6))

        # Measured stability
        ax.errorbar(taus, adevs, yerr=errors, fmt='o-', capsize=3,
                    label='Measured Stability', color='blue')

        # Shot-noise reference (1/√τ scaling)
        ideal_line = adevs[0] * (taus / taus[0])**-0.5
        ax.loglog(taus, ideal_line, 'k--', alpha=0.6,
                  label=r'Shot Noise Limit ($\tau^{-1/2}$)')

        ax.set_xscale('log')
        ax.set_yscale('log')
        ax.set_xlabel(r'Integration Time $\tau$ (s)', fontsize=12)
        ax.set_ylabel(r'Allan Deviation $\sigma_A(\tau)$ [µT]', fontsize=12)
        ax.set_title('QDM Magnetometer Stability (Overlapping Allan Deviation)', fontsize=14)
        ax.legend(fontsize=10)
        ax.grid(True, which="both", ls="-", alpha=0.2)
        fig.tight_layout()

        if save_fig:
            if save_path is None:
                save_path = Path(r"E:\MTB project\CW ODMR")
            save_qdm_figure(fig, base_filename="allan_variance",
                            subfolder=subfolder, base_path=save_path)

        if show_plot:
            plt.show()

    return {
        'taus': taus,
        'adevs': adevs,
        'errors': errors,
        'ns': ns,
        'figure': fig
    }


def run_simulation_sweep(freqlist, ref_freq, settings, sim_field_map, odmr_data_cube, pbar, sweep_num,
                         live_plot_ctx=None):
    """
    Performs a single simulated sweep using vectorized calculations.

    Parameters
    ----------
    live_plot_ctx : dict or None
        If provided, contains figure, axis, line, and display handle for live updates.
    """
    sim_cfg = settings['simulation']
    cam_cfg = settings['camera']
    effective_counts = sim_cfg['base_counts'] * cam_cfg['n_frames']
    total_sweeps = pbar.total // len(freqlist)
    num_freqs = len(freqlist)

    # Vectorized generation
    sig_cube = generate_synthetic_qdm_cube(freqlist, sim_field_map, effective_counts)
    ref_data = generate_synthetic_qdm_cube(np.array([ref_freq]), sim_field_map, effective_counts)

    # Accumulate
    odmr_data_cube += (sig_cube / ref_data[0])

    # Pre-compute spatial means once, then update plot point-by-point for visual consistency
    if live_plot_ctx is not None:
        live_plot_ctx['accumulated_mean'][:] = np.nanmean(odmr_data_cube, axis=(1, 2))

    for i in range(num_freqs):
        if live_plot_ctx is not None:
            _update_live_plot(live_plot_ctx, sweep_num, i, num_freqs)
        pbar.set_description(f"Sweep {sweep_num}/{total_sweeps}", refresh=False)
        pbar.update(1)

    pbar.set_postfix(status="Sweep done")


def _update_live_plot(ctx, sweep_num, freq_idx, num_freqs):
    """
    Updates the live ODMR plot without clearing the progress bar.

    Uses the pre-cached accumulated_mean (updated by the caller after each
    measurement) so that only a single-frequency mean needs to be computed
    per point rather than a full-cube reduction.  handle.update() already
    triggers a canvas draw internally, so draw_idle() is not called.
    """
    fig = ctx['fig']
    ax = ctx['ax']
    line = ctx['line']
    handle = ctx['handle']
    num_sweeps = ctx['num_sweeps']
    accumulated_mean = ctx['accumulated_mean']  # shape: (num_freqs,)

    # Compute per-point averages using the actual measurement count.
    # Points 0..freq_idx have sweep_num measurements;
    # points freq_idx+1..end have sweep_num-1 (0 on the first sweep).
    current_avg = np.zeros_like(accumulated_mean)
    current_avg[:freq_idx + 1] = accumulated_mean[:freq_idx + 1] / sweep_num
    if sweep_num > 1:
        current_avg[freq_idx + 1:] = accumulated_mean[freq_idx + 1:] / (sweep_num - 1)

    line.set_ydata(current_avg)

    # Auto-scale y-axis using only measured points (zeros are unmeasured)
    measured = current_avg[current_avg != 0]
    if len(measured) > 0 and np.ptp(measured) > 0:
        ymin, ymax = np.nanmin(measured), np.nanmax(measured)
        margin = 0.05 * (ymax - ymin)
        ax.set_ylim(ymin - margin, ymax + margin)

    ax.set_title(f'Live ODMR Sweep ({sweep_num}/{num_sweeps}) - Freq {freq_idx + 1}/{num_freqs}')

    # Update display without clearing (keeps progress bar visible)
    handle.update(fig)
    
# ============================================================
# Array and image manipulation
# ============================================================

def gen_freqs(
    start_freq: Union[int, float],
    end_freq: Union[int, float],
    num_steps: int
) -> np.ndarray:
    """
    Generate a linearly spaced frequency array.

    Parameters
    ----------
    start_freq : int or float
        Starting frequency.
    end_freq : int or float
        Ending frequency.
    num_steps : int
        Number of frequency points.

    Returns
    -------
    np.ndarray
        Linearly spaced frequency array.
    """
    return np.linspace(start_freq, end_freq, num_steps)

def bin_2d(
    img: np.ndarray,
    bin_size_x: int,
    bin_size_y: int,
) -> np.ndarray:
    """
    Spatially bin a 2D image by averaging using fixed bin sizes.
    Excess pixels on the right/bottom are cropped.
    Note that Basler camera can already do hardware binning up to 4 x 4 pixels, 
    so this is only for additional binning on top of that if needed.

    Example:
        (103, 103) image with bin_size_x=bin_size_y=5
        -> (20, 20) output
    """
    img = np.asarray(img)
    if img.ndim != 2:
        raise ValueError("img must be a 2D array")

    Ny, Nx = img.shape

    bins_x = Nx // bin_size_x
    bins_y = Ny // bin_size_y

    if bins_x == 0 or bins_y == 0:
        raise ValueError("Bin size larger than image dimensions")

    img_cropped = img[:bins_y * bin_size_y, :bins_x * bin_size_x]

    return img_cropped.reshape(
        bins_y, bin_size_y,
        bins_x, bin_size_x
    ).mean(axis=(1, 3))
    
def bin_qdm_cube(cube: np.ndarray, bin_x: int, bin_y: int) -> np.ndarray:
    """
    Spatially bins a 3D ODMR data cube of shape (Freq, Y, X).
    Returns a new cube with reduced spatial dimensions.
    """
    n_freqs, ny_orig, nx_orig = cube.shape
    
    # Calculate new dimensions (integer division crops leftovers)
    ny_new = ny_orig // bin_y
    nx_new = nx_orig // bin_x
    
    # Pre-allocate the binned cube
    binned_cube = np.zeros((n_freqs, ny_new, nx_new), dtype=cube.dtype)
    
    # Loop through each frequency and apply 2D binning
    for i in range(n_freqs):
        binned_cube[i, :, :] = bin_2d(cube[i, :, :], bin_x, bin_y)
        
    return binned_cube
    
def get_cube_subset(cube: np.ndarray, x_range: tuple, y_range: tuple) -> np.ndarray:
    """
    Returns a spatial subset (ROI) of a 3D ODMR cube.
    cube: array of shape (Freq, Y, X)
    x_range: (x_start, x_end)
    y_range: (y_start, y_end)
    """
    x_start, x_end = x_range
    y_start, y_end = y_range
    
    # Slicing the cube: [All Frequencies, Y-range, X-range]
    return cube[:, y_start:y_end, x_start:x_end]
 
def save_qdm_figure(fig, base_filename, subfolder="", 
                    base_path=r"E:\MTB project\CW ODMR", 
                    add_timestamp=True, dpi=300, extension=".png"):
    """
    Saves a Matplotlib figure to a specified QDM project directory.
    """
    # 1. Setup the directory path
    save_dir = Path(base_path) / subfolder
    
    try:
        save_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"Warning: Could not access {save_dir}. Error: {e}")
        save_dir = Path("./backup_plots")
        save_dir.mkdir(exist_ok=True)

    # 2. Handle Timestamping
    if add_timestamp:
        timestamp = datetime.now().strftime("%m%d%y_%H%M%S")
        filename = f"{base_filename}_{timestamp}{extension}"
    else:
        filename = f"{base_filename}{extension}"

    full_path = save_dir / filename

    # 3. Save the figure
    fig.tight_layout()
    fig.savefig(full_path, dpi=dpi)
    print(f"Successfully saved: {full_path}")
    
    return full_path

# ============================================================
# ODMR peak fitting and analysis
# ============================================================

def analyze_and_plot_odmr(
    odmr_data_cube,
    freqlist,
    n_lorentz=2,
    x_roi=None,
    y_roi=None,
    show_plot=True,
    save_fig=False,
    save_path=None,
    subfolder="",
    title_prefix="ODMR Analysis",
    fit_tolerance=None,
    max_iters=None
):
    """
    High-level function to analyze and plot spatially-averaged ODMR data.

    Performs Lorentzian fitting, extracts peak parameters (center, width, contrast,
    slope, inflection points), and generates a publication-ready plot.

    Parameters
    ----------
    odmr_data_cube : np.ndarray
        3D array of shape (n_freqs, ny, nx).
    freqlist : np.ndarray
        Frequency values in GHz.
    n_lorentz : int
        Number of Lorentzian peaks to fit (1 or 2 typical).
    x_roi : tuple or None
        (x_start, x_end) to select ROI. None = full range.
    y_roi : tuple or None
        (y_start, y_end) to select ROI. None = full range.
    show_plot : bool
        If True, display the plot.
    save_fig : bool
        If True, save the figure.
    save_path : str or Path or None
        Base path for saving. Uses default if None.
    subfolder : str
        Subfolder within save_path.
    title_prefix : str
        Prefix for plot title.
    fit_tolerance : float or None
        Convergence tolerance (ftol and xtol) for scipy least_squares.
        None uses fit_lorentzians default (1e-8).
    max_iters : int or None
        Maximum function evaluations for scipy least_squares.
        None uses fit_lorentzians default (20000).

    Returns
    -------
    dict
        Dictionary containing:
        - 'analysis': dict from fit_global_odmr (x_data, y_data, x_fit, y_fit, popt, peak_params, r2)
        - 'figure': matplotlib Figure object
        - 'peak_params': list of peak parameter dicts (center, width_fwhm, contrast, max_slope, inflection_pts)
    """
    # 1. Apply ROI if specified
    ny, nx = odmr_data_cube.shape[1], odmr_data_cube.shape[2]
    if x_roi is None:
        x_roi = (0, nx)
    if y_roi is None:
        y_roi = (0, ny)

    subset_cube = get_cube_subset(odmr_data_cube, x_roi, y_roi)

    # 2. Perform fitting
    analysis = fit_global_odmr(subset_cube, freqlist, n_lorentz=n_lorentz,
                               fit_tolerance=fit_tolerance, max_iters=max_iters)
    peak_params = analysis['peak_params']
    baseline = analysis['popt'][0]
    r2 = analysis['r2']

    # 3. Create plot
    fig, ax = plt.subplots(figsize=(10, 7))

    # Main data and fit
    ax.scatter(analysis['x_data'], analysis['y_data'], color='indigo', alpha=0.3, s=15, label='Data')
    ax.plot(analysis['x_fit'], analysis['y_fit'], color='black', lw=2, label=f'{n_lorentz}-Lorentz Fit')

    text_lines = [f"ROI: X{x_roi}, Y{y_roi} ($R^2$={r2:.4f})"]

    # Plot peaks and inflection points
    for p in peak_params:
        f0 = p['center']
        df_lin = p['inflection_pts']

        ax.axvline(f0, color='gray', linestyle=':', alpha=0.5)

        for i, f_lin in enumerate(df_lin):
            amp = p['contrast'] * baseline
            y_lin = baseline - (0.75 * amp)
            hwhm = p['width_fwhm'] / 2
            dx_tangent = hwhm * 0.25
            m_ghz = p['max_slope'] * baseline if i == 1 else -p['max_slope'] * baseline

            # Inflection point marker
            ax.plot(f_lin, y_lin, 'ro' if i == 0 else 'go', markersize=8, zorder=5)

            # Tangent line
            side = "Low" if i == 0 else "High"
            legend_label = f"Peak {p['index']} {side}: {f_lin:.5f} GHz"
            ax.plot([f_lin - dx_tangent, f_lin + dx_tangent],
                    [y_lin - m_ghz * dx_tangent, y_lin + m_ghz * dx_tangent],
                    color='orange', lw=2, alpha=0.9, label=legend_label)

        # Summary text
        slope_mhz = p['max_slope'] / 1000
        text_lines.append(f"Peak {p['index']}: {f0:.5f} GHz, FWHM: {p['width_fwhm']*1000:.2f} MHz, "
                          f"Contrast: {p['contrast']*100:.2f}%, Slope: {slope_mhz:.4f} MHz$^{{-1}}$")

    # Formatting
    ax.text(0.02, 0.98, "\n".join(text_lines), transform=ax.transAxes,
            verticalalignment='top', family='monospace', fontsize=9,
            bbox=dict(facecolor='white', alpha=0.8))

    ax.set_title(f'{title_prefix}', fontsize=14)
    ax.set_ylabel('PL Intensity (S/R)')
    ax.set_xlabel('Frequency (GHz)')
    ax.legend(loc='upper left', bbox_to_anchor=(1, 1), fontsize=8, frameon=True)
    ax.grid(alpha=0.2)
    fig.tight_layout()

    # 4. Save if requested
    if save_fig:
        save_qdm_figure(fig, base_filename="odmr_analysis", subfolder=subfolder,
                        base_path=save_path if save_path else r"E:\MTB project\CW ODMR")

    if show_plot:
        plt.show()

    # 5. Print summary
    print(f"\n{'='*60}")
    print("ODMR Analysis Summary")
    print(f"{'='*60}")
    print(f"Fit Quality: R² = {r2:.4f}")
    for p in peak_params:
        print(f"\nPeak {p['index']}:")
        print(f"  Center:      {p['center']:.5f} GHz")
        print(f"  FWHM:        {p['width_fwhm']*1000:.2f} MHz")
        print(f"  Contrast:    {p['contrast']*100:.2f}%")
        print(f"  Max Slope:   {p['max_slope']/1000:.4f} MHz^-1")
        print(f"  Inflection points: {p['inflection_pts'][0]:.5f}, {p['inflection_pts'][1]:.5f} GHz")
        print(f"  Inflection contrasts: {p['inflection_contrasts'][0]:.6f}, {p['inflection_contrasts'][1]:.6f}")

    return {
        'analysis': analysis,
        'figure': fig,
        'peak_params': peak_params,
        'r2': r2,
        'baseline': baseline
    }


def fit_global_odmr(odmr_data_cube, freqlist, n_lorentz=2, fit_tolerance=None, max_iters=None):
    """
    Spatially averages a 3D ODMR cube and fits it to N Lorentzians.

    Parameters
    ----------
    odmr_data_cube : np.ndarray
        3D array of shape (n_freqs, ny, nx).
    freqlist : np.ndarray
        Frequency values in GHz.
    n_lorentz : int
        Number of Lorentzian peaks to fit.
    fit_tolerance : float or None
        Convergence tolerance (ftol and xtol) passed to scipy least_squares.
        None uses fit_lorentzians default (1e-8).
    max_iters : int or None
        Maximum function evaluations passed to scipy least_squares.
        None uses fit_lorentzians default (20000).
    """
    # 1. Data Preparation: Spatial Average
    y_data = np.nanmean(odmr_data_cube, axis=(1, 2))
    x_data = freqlist

    # Adaptive resonance window: use 10% of scan range as margin (5% each side)
    scan_width = x_data.max() - x_data.min()
    margin = max(0.05 * scan_width, 0.001)  # At least 1 MHz margin
    resonance_window = (x_data.min() + margin, x_data.max() - margin)

    # 2. Perform the Fit
    tol_kwargs = {}
    if fit_tolerance is not None:
        tol_kwargs['ftol'] = fit_tolerance
        tol_kwargs['xtol'] = fit_tolerance
    if max_iters is not None:
        tol_kwargs['max_nfev'] = max_iters
    fit_results = fit_lorentzians(
        x_data,
        y_data,
        n_lorentz=n_lorentz,
        freq_range=resonance_window,
        **tol_kwargs
    )
    
    popt = fit_results['popt']
    model_func = fit_results['model']
    
    x_fit = np.linspace(x_data.min(), x_data.max(), 1000)
    y_fit = model_func(x_fit, *popt)

    # 3. Extract Parameters Dynamically (using refactored helper function)
    baseline = popt[0]
    peak_params = _extract_peak_params_from_popt(popt, baseline, model_func, n_lorentz)

    return {
        'x_data': x_data,
        'y_data': y_data,
        'x_fit': x_fit,
        'y_fit': y_fit,
        'popt': popt,
        'peak_params': peak_params,
        'r2': fit_results['r2']
    }


def fit_pixel_worker(pixel_spectrum, freqlist, n_lorentz, resonance_window, max_iter, tol):
    """
    Processes a single pixel's spectrum. 
    Everything the function needs is passed in to avoid global variable issues 
    which can sometimes occur in parallel environments.
    """
    # Quick skip for empty pixels
    if np.isnan(pixel_spectrum).sum() > len(pixel_spectrum) * 0.5:
        return np.nan, np.nan
        
    try:
        res = fit_lorentzians(
            freqlist, 
            pixel_spectrum, 
            n_lorentz=n_lorentz,
            freq_range=resonance_window,
            max_nfev=max_iter,
            ftol=tol,
            xtol=tol
        )
        popt = res['popt']
        # Extract f_center: (x01 + x02) / 2
        f_center = (popt[2] + popt[5]) / 2
        return f_center, res['r2']
    except Exception:
        return np.nan, np.nan

def fit_lorentzians(
    x: np.ndarray,
    y: np.ndarray,
    n_lorentz: int = 2,
    *,
    gamma_min: float | None = None,     # same units as x (GHz here)
    gamma_max: float | None = None,
    loss: str = "soft_l1",              # "linear" for ordinary LS
    f_scale: float = 0.05,              # robustness scale for non-linear losses
    p0: np.ndarray | None = None,       # INTERNAL params: [c, a1, x01, g1, ...]
    max_nfev: int = 20000,
    ftol: float = 1e-8,                 # tolerance for termination by cost change
    xtol: float = 1e-8,                 # tolerance for termination by step size
    gtol: float = 1e-8,                 # tolerance for termination by gradient norm
    sep_floor: float = 0.002,           # only for backward compatibility
    freq_range: tuple[float, float] | None = None, # restrains the guesser
):
    """
    Robustly fit a sum of n Lorentzians + constant baseline.
    Now includes tolerance parameters (ftol, xtol, gtol) for speed control.
    """
    x = np.asarray(x, dtype=float).ravel()
    y = np.asarray(y, dtype=float).ravel()
    if x.size != y.size:
        raise ValueError("x and y must have same length.")
    if n_lorentz < 1:
        raise ValueError("n_lorentz must be >= 1.")

    from scipy.optimize import least_squares

    # ---- Sampling-derived width bounds ----
    xspan = float(x.max() - x.min())
    xs = np.sort(x)
    dx = float(np.median(np.diff(xs))) if xs.size > 2 else 1.0

    if gamma_min is None:
        gamma_min = max(3.0 * dx, 1e-6)
    if gamma_max is None:
        gamma_max = max(0.25*xspan, 3*gamma_min)

    # ---- Internal-parameter model ----
    def model_internal(params: np.ndarray, xv: np.ndarray) -> np.ndarray:
        c = params[0]
        yv = np.full_like(xv, c, dtype=float)
        for i in range(n_lorentz):
            a, x0, g = params[1+3*i], params[2+3*i], params[3+3*i]
            yv += -np.exp(a) / (1.0 + ((xv - x0) / g) ** 2)
        return yv

    def residuals(params: np.ndarray) -> np.ndarray:
        return model_internal(params, x) - y

    # ---- Initial guess ----
    if p0 is None:
        p0 = fast_guess_p0(
            x, y, n_lorentz, gamma_min, gamma_max,
            freq_range=freq_range
        )
    else:
        p0 = np.asarray(p0, dtype=float).ravel()
        expected = 1 + 3 * n_lorentz
        if p0.size != expected:
            raise ValueError(f"p0 must have length {expected}.")

    # ---- Bounds (internal params) ----
    yptp = float(np.ptp(y)) if float(np.ptp(y)) > 0 else 1.0
    lower = [float(np.min(y) - 5.0 * yptp)]
    upper = [float(np.max(y) + 5.0 * yptp)]
    for _ in range(n_lorentz):
        lower += [-50.0, float(x.min()), float(gamma_min)]
        upper += [ 50.0, float(x.max()), float(gamma_max)]
    
    lb, ub = np.array(lower), np.array(upper)
    p0 = np.clip(p0, lb + 1e-12, ub - 1e-12)
        
    # ---- Optimization with explicit tolerances ----
    res = least_squares(
        residuals, p0, bounds=(lb, ub),
        loss=loss, 
        f_scale=f_scale, 
        max_nfev=max_nfev,
        ftol=ftol,
        xtol=xtol,
        gtol=gtol
    )

    # ---- Convert to user-facing popt [c, A1, x01, g1, ...] ----
    params = res.x
    popt = [params[0]]
    for i in range(n_lorentz):
        popt += [float(-np.exp(params[1+3*i])), float(params[2+3*i]), float(params[3+3*i])]
    popt = np.asarray(popt, dtype=float)

    # ---- User-facing model callable ----
    def model(xv: np.ndarray, *p: float) -> np.ndarray:
        xv = np.asarray(xv)
        yv = np.full_like(xv, p[0])
        for i in range(n_lorentz):
            yv += p[1+3*i] / (1.0 + ((xv - p[2+3*i]) / p[3+3*i]) ** 2)
        return yv

    yfit = model(x, *popt)
    r2 = 1.0 - np.sum((y-yfit)**2)/np.sum((y-np.mean(y))**2) if np.ptp(y) > 0 else 0.0

    return {"popt": popt, "model": model, "r2": r2, "result": res}


def denoise_field_map(
    field_map_gauss,
    method='none',
    gaussian_sigma=5.0,
    wavelet_method='BayesShrink',
    wavelet_mode='soft',
    nlm_h=None,
    nlm_fast_mode=True,
    nlm_patch_size=5,
    nlm_patch_distance=6,
    tv_weight=0.1,
    bilateral_sigma_color=0.05,
    bilateral_sigma_spatial=1.5
):
    """
    Apply denoising filters to magnetic field maps.

    This function provides various denoising options for improving field map quality
    while preserving features. Can be called both during initial processing and for
    reprocessing saved results.

    Parameters
    ----------
    field_map_gauss : np.ndarray
        2D array of magnetic field values in Gauss.
    method : str
        Denoising method. Options:
        - 'none': No denoising (returns original)
        - 'gaussian': Gaussian blur (fast, simple smoothing)
        - 'wavelet': Wavelet denoising (BayesShrink or VisuShrink)
        - 'nlm': Non-local means denoising (slow but excellent edge preservation)
        - 'tv': Total variation denoising (good for piecewise constant images)
        - 'bilateral': Bilateral filter (edge-preserving smoothing)
    gaussian_sigma : float
        Standard deviation of Gaussian kernel in pixels (used when method='gaussian').
        Larger values = more smoothing. Equivalent to kernel size ~6*sigma.
        Default is 5.0 pixels.
    wavelet_method : str
        Method for wavelet denoising ('BayesShrink' or 'VisuShrink').
    wavelet_mode : str
        Thresholding mode for wavelet ('soft' or 'hard').
    nlm_h : float or None
        Filtering parameter for non-local means. If None, auto-estimated as 1.15*sigma.
    nlm_fast_mode : bool
        Use fast approximation for non-local means.
    nlm_patch_size : int
        Patch size for non-local means (odd number).
    nlm_patch_distance : int
        Max distance to search for similar patches.
    tv_weight : float
        Regularization weight for total variation (smaller = less smoothing).
    bilateral_sigma_color : float
        Standard deviation for color/intensity distance.
    bilateral_sigma_spatial : float
        Standard deviation for spatial distance (pixels).

    Returns
    -------
    np.ndarray
        Denoised field map with same shape as input.

    Notes
    -----
    Requires scikit-image package. Methods ranked by speed (fast to slow):
    1. gaussian (fastest, simple blur)
    2. bilateral (fast, edge-preserving)
    3. tv
    4. wavelet
    5. nlm (slowest, but best quality)

    Examples
    --------
    >>> # Apply Gaussian blur with kernel size ~20 pixels (sigma=20)
    >>> denoised = denoise_field_map(field_map, method='gaussian', gaussian_sigma=20)
    >>>
    >>> # Apply wavelet denoising
    >>> denoised = denoise_field_map(field_map, method='wavelet')
    >>>
    >>> # Apply non-local means with custom parameters
    >>> denoised = denoise_field_map(field_map, method='nlm', nlm_h=0.1)
    """
    if method == 'none':
        return field_map_gauss

    if not SKIMAGE_AVAILABLE:
        raise ImportError(
            "scikit-image is required for denoising. "
            "Install with: pip install scikit-image"
        )

    # Normalize to 0-1 range for processing
    field_min, field_max = np.nanmin(field_map_gauss), np.nanmax(field_map_gauss)
    field_norm = (field_map_gauss - field_min) / (field_max - field_min)

    # Apply selected denoising method
    if method == 'gaussian':
        print(f"Applying Gaussian blur (σ={gaussian_sigma} pixels)...")
        denoised_norm = gaussian(field_norm, sigma=gaussian_sigma, mode='reflect', preserve_range=True)

    elif method == 'wavelet':
        print(f"Applying wavelet denoising (method={wavelet_method}, mode={wavelet_mode})...")
        denoised_norm = denoise_wavelet(
            field_norm,
            method=wavelet_method,
            mode=wavelet_mode,
            rescale_sigma=True
        )

    elif method == 'nlm':
        # Estimate noise if h not provided
        if nlm_h is None:
            sigma_est = estimate_sigma(field_norm)
            nlm_h = 1.15 * sigma_est
            print(f"Applying non-local means (auto h={nlm_h:.4f})...")
        else:
            print(f"Applying non-local means (h={nlm_h})...")

        denoised_norm = denoise_nl_means(
            field_norm,
            h=nlm_h,
            fast_mode=nlm_fast_mode,
            patch_size=nlm_patch_size,
            patch_distance=nlm_patch_distance
        )

    elif method == 'tv':
        print(f"Applying total variation denoising (weight={tv_weight})...")
        denoised_norm = denoise_tv_chambolle(field_norm, weight=tv_weight)

    elif method == 'bilateral':
        print(f"Applying bilateral filter (σ_color={bilateral_sigma_color}, σ_spatial={bilateral_sigma_spatial})...")
        denoised_norm = denoise_bilateral(
            field_norm,
            sigma_color=bilateral_sigma_color,
            sigma_spatial=bilateral_sigma_spatial
        )

    else:
        raise ValueError(
            f"Unknown denoising method: {method}. "
            f"Options: 'none', 'gaussian', 'wavelet', 'nlm', 'tv', 'bilateral'"
        )

    # Convert back to original scale
    denoised = denoised_norm * (field_max - field_min) + field_min
    print(f"Denoising complete. Range: {np.nanmin(denoised):.3f} to {np.nanmax(denoised):.3f} Gauss")

    return denoised


def process_widefield_odmr(
    odmr_data_cube,
    freqlist,
    n_lorentz=2,
    bin_x=1,
    bin_y=1,
    fit_tolerance=1e-3,
    max_iters=600,
    n_jobs=-1,
    show_progress=True,
    show_plot=True,
    save_data=False,
    save_fig=False,
    save_path=None,
    subfolder="",
    denoise_method='none',
    **denoise_kwargs
):
    """
    High-level function for pixel-by-pixel ODMR fitting to generate magnetic field maps.

    Parameters
    ----------
    odmr_data_cube : np.ndarray
        3D array of shape (n_freqs, ny, nx).
    freqlist : np.ndarray
        Frequency values in GHz.
    n_lorentz : int
        Number of Lorentzian peaks to fit per pixel.
    bin_x, bin_y : int
        Additional spatial binning factors (1 = no binning).
    fit_tolerance : float
        Fitting tolerance (1e-3 is usually sufficient).
    max_iters : int
        Maximum iterations per pixel fit.
    n_jobs : int
        Number of parallel jobs (-1 = all cores).
    show_progress : bool
        If True, show tqdm progress bar.
    show_plot : bool
        If True, display field maps (raw, denoised, processed) and frequency map.
    save_data : bool
        If True, save per-pixel fit results (f_center, r2, and metadata) to .npz file.
        Saves raw, denoised, and processed field maps. Useful for investigating fitting failures.
    save_fig : bool
        If True, save both figures.
    save_path : str or Path or None
        Base path for saving data and figures.
    subfolder : str
        Subfolder within save_path.
    denoise_method : str
        Denoising method ('none', 'wavelet', 'nlm', 'tv', 'bilateral').
        The function ALWAYS computes processed = (raw - denoised) to highlight small-scale
        features by removing large-scale background structure. When method='none', the
        denoised map equals the raw map, so processed will be all zeros (blank).
    **denoise_kwargs
        Additional keyword arguments passed to denoise_field_map().
        See denoise_field_map() docstring for available options.

    Returns
    -------
    dict
        Dictionary containing:
        - 'field_map_gauss_raw': 2D array of raw relative B-field in Gauss (before processing)
        - 'field_map_gauss_denoised': 2D array of denoised B-field in Gauss
        - 'field_map_gauss_processed': 2D array of processed B-field in Gauss (raw - denoised)
        - 'field_map_gauss': alias for 'field_map_gauss_processed' (for backwards compatibility)
        - 'freq_center_map': 2D array of fitted center frequencies in GHz
        - 'fit_quality_map': 2D array of R² values
        - 'global_mean_freq': mean frequency used as zero reference
        - 'figure_field': matplotlib Figure object with 3-panel comparison (raw, denoised, processed)
        - 'figure_freq': matplotlib Figure object for frequency map (if show_plot or save_fig)
    """
    from joblib import Parallel, delayed
    from tqdm.auto import tqdm as tqdm_auto

    GAMMA_E = 28.024  # GHz/Tesla

    # 1. Apply binning if requested
    if bin_x > 1 or bin_y > 1:
        print(f"Applying {bin_x}x{bin_y} additional spatial binning...")
        binned_cube = bin_qdm_cube(odmr_data_cube, bin_x, bin_y)
    else:
        binned_cube = odmr_data_cube

    n_freqs, ny, nx = binned_cube.shape

    # Adaptive resonance window: use 10% of scan range as margin (5% each side)
    # with minimum 1 MHz to avoid overly restrictive windows on narrow scans
    scan_width = freqlist.max() - freqlist.min()
    margin = max(0.05 * scan_width, 0.001)  # At least 1 MHz margin
    resonance_window = (freqlist.min() + margin, freqlist.max() - margin)

    # 2. Flatten cube for parallel processing
    pixel_list = binned_cube.reshape(n_freqs, -1).T

    print(f"Analyzing {nx * ny} pixels in parallel...")

    # 3. Parallel fitting
    iterator = range(len(pixel_list))
    if show_progress:
        iterator = tqdm_auto(iterator, desc="Fitting Field Map")

    results = Parallel(n_jobs=n_jobs)(
        delayed(fit_pixel_worker)(
            pixel_list[i],
            freqlist,
            n_lorentz,
            resonance_window,
            max_iters,
            fit_tolerance
        )
        for i in iterator
    )

    # 4. Reconstruct maps
    results_array = np.array(results)
    f_doublet_center = results_array[:, 0].reshape(ny, nx)
    fit_quality_map = results_array[:, 1].reshape(ny, nx)

    # 5. Calculate magnetic field
    global_mean_freq = np.nanmean(f_doublet_center)
    f_shift_ghz = f_doublet_center - global_mean_freq
    relative_bz_gauss = -(f_shift_ghz / GAMMA_E) * 10000

    print(f"\nWidefield analysis complete.")
    print(f"Mean resonance frequency (zero reference): {global_mean_freq:.6f} GHz")
    print(f"Frequency range: {np.nanmin(f_doublet_center):.6f} to {np.nanmax(f_doublet_center):.6f} GHz")
    print(f"Field range: {np.nanmin(relative_bz_gauss):.3f} to {np.nanmax(relative_bz_gauss):.3f} Gauss")

    # 6. Apply denoising and compute processed image (raw - denoised)
    raw_field_map = relative_bz_gauss.copy()  # Keep raw data

    print(f"\nApplying denoising (method='{denoise_method}') and computing (raw - denoised)...")
    denoised_field_map = denoise_field_map(raw_field_map, method=denoise_method, **denoise_kwargs)
    processed_field_map = raw_field_map - denoised_field_map

    print(f"Raw field range: {np.nanmin(raw_field_map):.3f} to {np.nanmax(raw_field_map):.3f} Gauss")
    print(f"Denoised field range: {np.nanmin(denoised_field_map):.3f} to {np.nanmax(denoised_field_map):.3f} Gauss")
    print(f"Processed (raw-denoised) range: {np.nanmin(processed_field_map):.3f} to {np.nanmax(processed_field_map):.3f} Gauss")

    # Save fit results if requested
    if save_data:
        if save_path is None:
            save_path = Path(r"E:\MTB project\CW ODMR")
        else:
            save_path = Path(save_path)

        save_dir = save_path / subfolder
        save_dir.mkdir(parents=True, exist_ok=True)

        # Create filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"widefield_fit_results_{ny}x{nx}_{timestamp}.npz"
        full_path = save_dir / filename

        # Calculate R² statistics for summary
        valid_r2 = fit_quality_map[~np.isnan(fit_quality_map)]
        failed_pixels = np.sum(np.isnan(f_doublet_center))

        np.savez_compressed(
            full_path,
            freq_center_map=f_doublet_center,
            fit_quality_map=fit_quality_map,
            field_map_gauss_raw=raw_field_map,
            field_map_gauss_denoised=denoised_field_map,
            field_map_gauss_processed=processed_field_map,
            global_mean_freq=global_mean_freq,
            freqlist=freqlist,
            n_lorentz=n_lorentz,
            resonance_window=resonance_window,
            fit_tolerance=fit_tolerance,
            denoise_method=denoise_method,
            shape=(ny, nx)
        )
        print(f"Fit results saved: {full_path}")
        print(f"  Valid pixels: {len(valid_r2)} / {ny * nx}")
        print(f"  Failed fits: {failed_pixels}")
        if len(valid_r2) > 0:
            print(f"  R² range: {np.min(valid_r2):.3f} to {np.max(valid_r2):.3f}")
            print(f"  Mean R²: {np.mean(valid_r2):.3f}")

    # 7. Plot if requested
    fig_field = None
    fig_freq = None
    if show_plot or save_fig:
        # Create 3-panel comparison plot
        fig_field = plot_field_map_comparison(
            raw_field_map, denoised_field_map, processed_field_map,
            method_name=denoise_method
        )

        if save_fig:
            save_qdm_figure(fig_field, base_filename="magnetic_field_map_comparison", subfolder=subfolder,
                            base_path=save_path if save_path else r"E:\MTB project\CW ODMR")
        if show_plot:
            plt.show()

        # Plot frequency center map
        fig_freq = plot_frequency_map(f_doublet_center, title="Resonance Frequency Map")
        if save_fig:
            save_qdm_figure(fig_freq, base_filename="frequency_center_map", subfolder=subfolder,
                            base_path=save_path if save_path else r"E:\MTB project\CW ODMR")
        if show_plot:
            plt.show()

    return {
        'field_map_gauss_raw': raw_field_map,
        'field_map_gauss_denoised': denoised_field_map,
        'field_map_gauss_processed': processed_field_map,
        'field_map_gauss': processed_field_map,  # For backwards compatibility
        'freq_center_map': f_doublet_center,
        'fit_quality_map': fit_quality_map,
        'global_mean_freq': global_mean_freq,
        'figure_field': fig_field,
        'figure_freq': fig_freq
    }


def plot_field_map(field_map_gauss, title="Magnetic Field Map", cmap='RdBu_r',
                   vmin_percentile=5, vmax_percentile=95, symmetric=True):
    """
    Create a publication-ready magnetic field map plot.

    Parameters
    ----------
    field_map_gauss : np.ndarray
        2D array of magnetic field values in Gauss.
    title : str
        Plot title.
    cmap : str
        Colormap name (default 'RdBu_r').
    vmin_percentile : float
        Lower percentile for colorbar range (default 5).
        Helps exclude outliers from skewing the colorbar.
    vmax_percentile : float
        Upper percentile for colorbar range (default 95).
    symmetric : bool
        If True, make colorbar symmetric around zero (default True).
        Uses max(abs(percentiles)) for both vmin and vmax.

    Returns
    -------
    plt.Figure
        Matplotlib figure object.
    """
    fig, ax = plt.subplots(figsize=(10, 8))

    # Use percentiles to avoid outliers skewing the colorbar
    vmin = np.nanpercentile(field_map_gauss, vmin_percentile)
    vmax = np.nanpercentile(field_map_gauss, vmax_percentile)

    if symmetric:
        # Make symmetric around zero for diverging colormap
        vlim = max(abs(vmin), abs(vmax))
        vmin, vmax = -vlim, vlim

    im = ax.imshow(field_map_gauss, cmap=cmap, origin='upper', vmin=vmin, vmax=vmax)

    ax.set_title(rf'{title} $\Delta B_z$', fontsize=14)
    ax.set_xlabel('Pixel X', fontsize=12)
    ax.set_ylabel('Pixel Y', fontsize=12)

    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label('Field Shift (Gauss)', fontsize=12)

    fig.tight_layout()
    return fig


def plot_frequency_map(freq_center_map, title="Resonance Frequency Map", cmap='viridis',
                       vmin_percentile=5, vmax_percentile=95):
    """
    Create a publication-ready resonance frequency map plot.

    Parameters
    ----------
    freq_center_map : np.ndarray
        2D array of fitted center frequencies in GHz.
    title : str
        Plot title.
    cmap : str
        Colormap name (default 'viridis').
    vmin_percentile : float
        Lower percentile for colorbar range (default 5).
        Helps exclude outliers from skewing the colorbar.
    vmax_percentile : float
        Upper percentile for colorbar range (default 95).

    Returns
    -------
    plt.Figure
        Matplotlib figure object.
    """
    fig, ax = plt.subplots(figsize=(10, 8))

    # Use percentiles to avoid outliers skewing the colorbar
    vmin = np.nanpercentile(freq_center_map, vmin_percentile)
    vmax = np.nanpercentile(freq_center_map, vmax_percentile)

    im = ax.imshow(freq_center_map, cmap=cmap, origin='upper', vmin=vmin, vmax=vmax)

    ax.set_title(title, fontsize=14)
    ax.set_xlabel('Pixel X', fontsize=12)
    ax.set_ylabel('Pixel Y', fontsize=12)

    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label('Resonance Frequency (GHz)', fontsize=12)

    fig.tight_layout()
    return fig


def plot_field_map_comparison(raw_field_map, denoised_field_map, processed_field_map,
                               method_name='Denoising', vmin_percentile=5, vmax_percentile=95):
    """
    Create a 3-panel comparison plot showing raw, denoised, and processed field maps.

    Parameters
    ----------
    raw_field_map : np.ndarray
        2D array of raw magnetic field values in Gauss.
    denoised_field_map : np.ndarray
        2D array of denoised magnetic field values in Gauss.
    processed_field_map : np.ndarray
        2D array of processed (raw - denoised) field values in Gauss.
    method_name : str
        Name of denoising method for plot title (default 'Denoising').
    vmin_percentile : float
        Lower percentile for colorbar range (default 5).
    vmax_percentile : float
        Upper percentile for colorbar range (default 95).

    Returns
    -------
    plt.Figure
        Matplotlib figure object with 3 subplots.
    """
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))

    # Determine colorbar limits using percentiles to avoid outliers
    vmin_raw = np.nanpercentile(raw_field_map, vmin_percentile)
    vmax_raw = np.nanpercentile(raw_field_map, vmax_percentile)
    vlim_raw = max(abs(vmin_raw), abs(vmax_raw))

    vmin_denoised = np.nanpercentile(denoised_field_map, vmin_percentile)
    vmax_denoised = np.nanpercentile(denoised_field_map, vmax_percentile)
    vlim_denoised = max(abs(vmin_denoised), abs(vmax_denoised))

    vmin_proc = np.nanpercentile(processed_field_map, vmin_percentile)
    vmax_proc = np.nanpercentile(processed_field_map, vmax_percentile)
    vlim_proc = max(abs(vmin_proc), abs(vmax_proc))

    # Plot 1: Raw field map
    im1 = axes[0].imshow(raw_field_map, cmap='RdBu_r', origin='upper',
                         vmin=-vlim_raw, vmax=vlim_raw)
    axes[0].set_title('Raw Magnetic Field Map', fontsize=12)
    axes[0].set_xlabel('Pixel X')
    axes[0].set_ylabel('Pixel Y')
    cbar1 = fig.colorbar(im1, ax=axes[0])
    cbar1.set_label('Field (Gauss)', fontsize=10)

    # Plot 2: Denoised field map
    im2 = axes[1].imshow(denoised_field_map, cmap='RdBu_r', origin='upper',
                         vmin=-vlim_denoised, vmax=vlim_denoised)
    axes[1].set_title(f'Denoised ({method_name})', fontsize=12)
    axes[1].set_xlabel('Pixel X')
    axes[1].set_ylabel('Pixel Y')
    cbar2 = fig.colorbar(im2, ax=axes[1])
    cbar2.set_label('Field (Gauss)', fontsize=10)

    # Plot 3: Processed (raw - denoised) field map
    im3 = axes[2].imshow(processed_field_map, cmap='RdBu_r', origin='upper',
                         vmin=-vlim_proc, vmax=vlim_proc)
    axes[2].set_title('Processed (Raw - Denoised)', fontsize=12)
    axes[2].set_xlabel('Pixel X')
    axes[2].set_ylabel('Pixel Y')
    cbar3 = fig.colorbar(im3, ax=axes[2])
    cbar3.set_label('Field (Gauss)', fontsize=10)

    fig.tight_layout()
    return fig


def plot_global_vs_binned_comparison(global_result, binned_result,
                                      save_path=None, subfolder="",
                                      show_plot=True, save_fig=False):
    """
    Create a 2×3 comparison figure: global-mean vs. spatially-binned field maps.

    Rows: global-mean (top) and spatially-binned (bottom).
    Columns: raw, denoised, processed (raw − denoised).
    Color scales are matched per column across both rows. Prints a quantitative
    comparison of field map std dev and median pixel noise to the console.

    Parameters
    ----------
    global_result : dict or None
        Result dict from analyze_multi_point_magnetometry for the global-mean
        measurement. Pass None to skip the comparison figure and only print
        binned statistics.
        Expected keys: 'field_map_gauss_raw', 'field_map_gauss_denoised',
        'field_map_gauss_processed', 'field_noise_gauss'.
    binned_result : dict
        Result dict from analyze_multi_point_magnetometry for the binned
        measurement. Same expected keys as global_result.
    save_path : str or Path or None
        Base directory for saving the figure.
    subfolder : str
        Subfolder within save_path.
    show_plot : bool
        Display the figure inline (default True).
    save_fig : bool
        Save the figure as a .png file (default False).

    Returns
    -------
    fig : plt.Figure or None
        The 2×3 comparison figure, or None if global_result is None.
    stats : dict
        Quantitative comparison stats with keys: 'global_std', 'binned_std',
        'global_noise', 'binned_noise', 'std_ratio', 'noise_ratio'.
        Keys 'global_std' and 'global_noise' are omitted if global_result is None.
    """
    b_std = np.nanstd(binned_result['field_map_gauss_processed'])
    b_noise = np.nanmedian(binned_result['field_noise_gauss'])

    print(f"Binned field map statistics:")
    print(f"  Mean  : {np.nanmean(binned_result['field_map_gauss_processed']):.4f} Gauss")
    print(f"  Std   : {b_std:.4f} Gauss")
    print(f"  Noise : {b_noise:.4f} Gauss (median pixel)")

    if global_result is None:
        print("\n[INFO] global_result=None — run global-mean cells first to enable comparison.")
        return None, {'binned_std': b_std, 'binned_noise': b_noise}

    def _sym_clim(arrays, pct=99.5):
        vals = np.concatenate([a.ravel() for a in arrays])
        vals = vals[np.isfinite(vals)]
        v = np.nanpercentile(np.abs(vals), pct) if len(vals) > 0 else 1.0
        return -v, v

    vmin_r, vmax_r = _sym_clim([global_result['field_map_gauss_raw'],
                                  binned_result['field_map_gauss_raw']])
    vmin_d, vmax_d = _sym_clim([global_result['field_map_gauss_denoised'],
                                  binned_result['field_map_gauss_denoised']])
    vmin_p, vmax_p = _sym_clim([global_result['field_map_gauss_processed'],
                                  binned_result['field_map_gauss_processed']])

    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    fig.suptitle('Global Mean vs. Spatially-Binned Multi-Point Magnetometry',
                 fontsize=14, fontweight='bold')

    rows = [
        ('Global Mean',      global_result),
        ('Spatially-Binned', binned_result),
    ]
    cols = [
        ('Raw',                      'field_map_gauss_raw',       vmin_r, vmax_r),
        ('Denoised',                 'field_map_gauss_denoised',  vmin_d, vmax_d),
        ('Processed (Raw−Denoised)', 'field_map_gauss_processed', vmin_p, vmax_p),
    ]

    for r, (row_label, res) in enumerate(rows):
        axes[r, 0].set_ylabel(row_label, fontsize=12, fontweight='bold')
        for c, (col_title, key, vmin, vmax) in enumerate(cols):
            ax = axes[r, c]
            im = ax.imshow(res[key], cmap='RdBu_r', vmin=vmin, vmax=vmax, origin='upper')
            ax.set_title(col_title)
            ax.set_xlabel('Pixel X')
            fig.colorbar(im, ax=ax, fraction=0.046, label='B (Gauss)')

    fig.tight_layout()

    if save_fig and save_path is not None:
        save_dir = Path(save_path) / subfolder
        save_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = save_dir / f"global_vs_binned_comparison_{ts}.png"
        fig.savefig(fname, dpi=300, bbox_inches='tight')
        print(f"Saved: {fname}")

    if show_plot:
        plt.show()

    g_std = np.nanstd(global_result['field_map_gauss_processed'])
    g_noise = np.nanmedian(global_result['field_noise_gauss'])
    print(f"\nQuantitative comparison (global mean vs. binned):")
    print(f"  Std dev      : {g_std:.4f} G  vs.  {b_std:.4f} G  (ratio {b_std / g_std:.2f}x)")
    print(f"  Median noise : {g_noise:.4f} G  vs.  {b_noise:.4f} G  (ratio {b_noise / g_noise:.2f}x)")

    return fig, {
        'global_std': g_std, 'binned_std': b_std,
        'global_noise': g_noise, 'binned_noise': b_noise,
        'std_ratio': b_std / g_std, 'noise_ratio': b_noise / g_noise,
    }


# ============================================================
# Background Subtraction Analysis
# ============================================================

def analyze_background_subtraction(
    bg_file,
    sample_file,
    gaussian_sigma=7.0,
    save_path=None,
    subfolder="",
    show_plot=True,
    save_fig=False,
    save_data=False,
    vrange_raw=None,
    vrange_denoised=None,
    vrange_processed=None,
    vrange_subtracted=None,
):
    """
    Load two multi-point field map .npz files (background and sample), apply
    Gaussian denoising to each, subtract the processed background from the
    processed sample, and generate comparison figures.

    The background file is a measurement taken without sample present. The
    sample file is a measurement taken with sample. Subtracting removes
    spatially-correlated noise and bias field artifacts common to both.

    Parameters
    ----------
    bg_file : str or Path
        Full path to background .npz file (measurement without sample).
    sample_file : str or Path
        Full path to sample .npz file (measurement with sample).
    gaussian_sigma : float
        Sigma (pixels) for Gaussian denoising filter (default 7.0).
    save_path : str or Path, optional
        Base directory for saving outputs.
    subfolder : str
        Subfolder within save_path.
    show_plot : bool
        Display figures inline (default True).
    save_fig : bool
        Save both figures as .png files (default False).
    save_data : bool
        Save result arrays as a .npz file (default False).
    vrange_raw : tuple of (vmin, vmax) or None
        Explicit color limits (Gauss) for the 'Raw' column in the analysis figure.
        If None, auto-computed as symmetric 99.5th percentile (default).
    vrange_denoised : tuple of (vmin, vmax) or None
        Explicit color limits (Gauss) for the 'Denoised' column in the analysis
        figure. If None, auto-computed (default).
    vrange_processed : tuple of (vmin, vmax) or None
        Explicit color limits (Gauss) for the 'Processed (Raw - Denoised)' column
        in the analysis figure and the background/sample panels in the comparison
        figure. If None, auto-computed (default).
    vrange_subtracted : tuple of (vmin, vmax) or None
        Explicit color limits (Gauss) for the 'Background-Subtracted' panel in the
        comparison figure. If None, auto-computed (default).

    Returns
    -------
    dict with keys:
        'bg_raw', 'bg_denoised', 'bg_processed'      : background field maps (Gauss)
        'sample_raw', 'sample_denoised', 'sample_processed' : sample field maps (Gauss)
        'subtracted'     : background-subtracted result = sample_processed - bg_processed
        'gaussian_sigma' : float, sigma used for Gaussian denoising
        'bg_file'        : str, path to the background .npz file
        'sample_file'    : str, path to the sample .npz file
        'figure_analysis': Figure, 2x3 panel showing raw/denoised/processed for each
        'figure_comparison': Figure, 1x3 showing bg_processed, sample_processed, subtracted
    """
    bg_file = Path(bg_file)
    sample_file = Path(sample_file)
    bg_fname = bg_file.name
    sample_fname = sample_file.name

    # --- Load raw field maps ---
    bg_raw = np.load(bg_file)['field_map_gauss_raw'].astype(np.float64)
    sample_raw = np.load(sample_file)['field_map_gauss_raw'].astype(np.float64)

    # --- Apply Gaussian denoising ---
    bg_denoised = denoise_field_map(bg_raw, method='gaussian', gaussian_sigma=gaussian_sigma)
    bg_processed = bg_raw - bg_denoised

    sample_denoised = denoise_field_map(sample_raw, method='gaussian', gaussian_sigma=gaussian_sigma)
    sample_processed = sample_raw - sample_denoised

    # --- Background subtraction ---
    subtracted = sample_processed - bg_processed

    # --- Helper: symmetric color limits ---
    def _sym_clim(arrays, pct=99.5):
        vals = np.concatenate([a.ravel() for a in arrays])
        vals = vals[np.isfinite(vals)]
        vabs = np.nanpercentile(np.abs(vals), pct) if len(vals) > 0 else 1.0
        return -vabs, vabs

    source_label = f'BG: {bg_fname}  |  Sample: {sample_fname}'

    # -------------------------------------------------------
    # Figure 1: 2-row x 3-col analysis (raw / denoised / processed)
    # -------------------------------------------------------
    fig1, axes1 = plt.subplots(2, 3, figsize=(16, 9))
    fig1.suptitle(
        f'Field Map Analysis  |  Gaussian sigma={gaussian_sigma} px\n{source_label}',
        fontsize=10, fontweight='bold'
    )

    vmin_raw, vmax_raw = vrange_raw if vrange_raw is not None else _sym_clim([bg_raw, sample_raw])
    vmin_den, vmax_den = vrange_denoised if vrange_denoised is not None else _sym_clim([bg_denoised, sample_denoised])
    vmin_proc, vmax_proc = vrange_processed if vrange_processed is not None else _sym_clim([bg_processed, sample_processed])

    rows = [
        ('Background', bg_raw, bg_denoised, bg_processed),
        ('Sample',     sample_raw, sample_denoised, sample_processed),
    ]
    col_specs = [
        ('Raw', vmin_raw, vmax_raw),
        ('Denoised (Gaussian)', vmin_den, vmax_den),
        ('Processed (Raw - Denoised)', vmin_proc, vmax_proc),
    ]

    for r, (row_label, raw, den, proc) in enumerate(rows):
        axes1[r, 0].set_ylabel(row_label, fontsize=12, fontweight='bold')
        imgs = [raw, den, proc]
        for c, (col_title, vmin, vmax) in enumerate(col_specs):
            ax = axes1[r, c]
            im = ax.imshow(imgs[c], cmap='RdBu_r', vmin=vmin, vmax=vmax, origin='upper')
            ax.set_title(col_title, fontsize=10)
            ax.set_xlabel('Pixel X')
            fig1.colorbar(im, ax=ax, fraction=0.046, label='B (Gauss)')

    fig1.tight_layout(rect=[0, 0.03, 1, 1])

    # -------------------------------------------------------
    # Figure 2: 1x3 comparison (bg processed / sample processed / subtracted)
    # -------------------------------------------------------
    fig2, axes2 = plt.subplots(1, 3, figsize=(17, 5))
    fig2.suptitle(
        f'Background Subtraction Result  |  Gaussian sigma={gaussian_sigma} px\n{source_label}',
        fontsize=10, fontweight='bold'
    )

    vmin_proc_all, vmax_proc_all = vrange_processed if vrange_processed is not None else _sym_clim([bg_processed, sample_processed])
    vmin_sub, vmax_sub = vrange_subtracted if vrange_subtracted is not None else _sym_clim([subtracted])

    panels = [
        (axes2[0], bg_processed,     vmin_proc_all, vmax_proc_all, 'Background\n(Processed: Raw - Denoised)'),
        (axes2[1], sample_processed, vmin_proc_all, vmax_proc_all, 'Sample\n(Processed: Raw - Denoised)'),
        (axes2[2], subtracted,       vmin_sub,      vmax_sub,      'Background-Subtracted\n(Sample - Background)'),
    ]
    for i, (ax, img, vmin, vmax, title) in enumerate(panels):
        im = ax.imshow(img, cmap='RdBu_r', vmin=vmin, vmax=vmax, origin='upper')
        ax.set_title(title, fontsize=11)
        ax.set_xlabel('Pixel X')
        if i == 0:
            ax.set_ylabel('Pixel Y')
        fig2.colorbar(im, ax=ax, fraction=0.046, label='B (Gauss)')

    fig2.tight_layout(rect=[0, 0.04, 1, 1])

    # --- Save ---
    if (save_fig or save_data) and save_path is not None:
        save_dir = Path(save_path) / subfolder
        save_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if save_fig:
            for fig_obj, base in [
                (fig1, f'background_subtraction_analysis_{timestamp}.png'),
                (fig2, f'background_subtracted_comparison_{timestamp}.png'),
            ]:
                out_path = save_dir / base
                fig_obj.text(
                    0.5, 0.002,
                    f'File: {base}  |  {source_label}',
                    ha='center', fontsize=6, color='gray',
                    transform=fig_obj.transFigure
                )
                fig_obj.savefig(out_path, dpi=300, bbox_inches='tight')
                print(f'Saved figure: {out_path}')

        if save_data:
            npz_name = f'background_subtracted_field_map_{timestamp}.npz'
            npz_path = save_dir / npz_name
            np.savez_compressed(
                npz_path,
                bg_raw=bg_raw, bg_denoised=bg_denoised, bg_processed=bg_processed,
                sample_raw=sample_raw, sample_denoised=sample_denoised,
                sample_processed=sample_processed,
                subtracted=subtracted,
                bg_file=str(bg_file),
                sample_file=str(sample_file),
                gaussian_sigma=gaussian_sigma,
            )
            print(f'Saved data: {npz_path}')

    if show_plot:
        plt.show()

    return {
        'bg_raw': bg_raw,
        'bg_denoised': bg_denoised,
        'bg_processed': bg_processed,
        'sample_raw': sample_raw,
        'sample_denoised': sample_denoised,
        'sample_processed': sample_processed,
        'subtracted': subtracted,
        'gaussian_sigma': gaussian_sigma,
        'bg_file': str(bg_file),
        'sample_file': str(sample_file),
        'figure_analysis': fig1,
        'figure_comparison': fig2,
    }


def replot_background_subtraction(
    result,
    gaussian_sigma=None,
    source_label=None,
    vrange_raw=None,
    vrange_denoised=None,
    vrange_processed=None,
    vrange_subtracted=None,
    show_plot=True,
    save_fig=False,
    save_path=None,
    subfolder="",
):
    """
    Replot the output of analyze_background_subtraction with custom color limits.

    Takes the result dict from analyze_background_subtraction and regenerates
    both figures without reloading files or recomputing denoising. Useful for
    adjusting the display range to highlight specific features.

    Parameters
    ----------
    result : dict
        Output dict from analyze_background_subtraction.
    gaussian_sigma : float or None
        Sigma used for Gaussian denoising (for figure title). If None, reads
        from result dict key 'gaussian_sigma' if present.
    source_label : str or None
        Label shown in figure titles. If None, reconstructed from result dict
        keys 'bg_file' and 'sample_file' if present.
    vrange_raw : tuple of (vmin, vmax) or None
        Explicit color limits (Gauss) for the 'Raw' column. None = auto.
    vrange_denoised : tuple of (vmin, vmax) or None
        Explicit color limits (Gauss) for the 'Denoised' column. None = auto.
    vrange_processed : tuple of (vmin, vmax) or None
        Explicit color limits (Gauss) for the 'Processed' column (both analysis
        figure and bg/sample panels in comparison figure). None = auto.
    vrange_subtracted : tuple of (vmin, vmax) or None
        Explicit color limits (Gauss) for the 'Background-Subtracted' panel.
        None = auto.
    show_plot : bool
        Display figures inline (default True).
    save_fig : bool
        Save both figures as .png files (default False).
    save_path : str or Path or None
        Base directory for saving outputs.
    subfolder : str
        Subfolder within save_path.

    Returns
    -------
    dict with keys:
        'figure_analysis'  : Figure, 2x3 panel analysis figure
        'figure_comparison': Figure, 1x3 comparison figure
    """
    bg_raw = result['bg_raw']
    bg_denoised = result['bg_denoised']
    bg_processed = result['bg_processed']
    sample_raw = result['sample_raw']
    sample_denoised = result['sample_denoised']
    sample_processed = result['sample_processed']
    subtracted = result['subtracted']

    # Extract metadata from result dict if not provided explicitly
    if gaussian_sigma is None:
        gaussian_sigma = result.get('gaussian_sigma', None)
    if source_label is None:
        bg_f = result.get('bg_file', '')
        sample_f = result.get('sample_file', '')
        if bg_f or sample_f:
            source_label = f'BG: {Path(bg_f).name}  |  Sample: {Path(sample_f).name}'
        else:
            source_label = ''

    sigma_str = f'Gaussian sigma={gaussian_sigma} px' if gaussian_sigma is not None else ''

    # Helper: symmetric color limits
    def _sym_clim(arrays, pct=99.5):
        vals = np.concatenate([a.ravel() for a in arrays])
        vals = vals[np.isfinite(vals)]
        vabs = np.nanpercentile(np.abs(vals), pct) if len(vals) > 0 else 1.0
        return -vabs, vabs

    # Resolve color limits
    vmin_raw, vmax_raw = vrange_raw if vrange_raw is not None else _sym_clim([bg_raw, sample_raw])
    vmin_den, vmax_den = vrange_denoised if vrange_denoised is not None else _sym_clim([bg_denoised, sample_denoised])
    vmin_proc, vmax_proc = vrange_processed if vrange_processed is not None else _sym_clim([bg_processed, sample_processed])
    vmin_proc_all, vmax_proc_all = vrange_processed if vrange_processed is not None else _sym_clim([bg_processed, sample_processed])
    vmin_sub, vmax_sub = vrange_subtracted if vrange_subtracted is not None else _sym_clim([subtracted])

    # Build title components
    title_suffix = '  |  '.join(p for p in [sigma_str, source_label] if p)
    title1 = f'Field Map Analysis  |  {title_suffix}' if title_suffix else 'Field Map Analysis'
    title2 = f'Background Subtraction Result  |  {title_suffix}' if title_suffix else 'Background Subtraction Result'

    # -------------------------------------------------------
    # Figure 1: 2-row x 3-col analysis (raw / denoised / processed)
    # -------------------------------------------------------
    fig1, axes1 = plt.subplots(2, 3, figsize=(16, 9))
    fig1.suptitle(title1, fontsize=10, fontweight='bold')

    rows = [
        ('Background', bg_raw, bg_denoised, bg_processed),
        ('Sample',     sample_raw, sample_denoised, sample_processed),
    ]
    col_specs = [
        ('Raw', vmin_raw, vmax_raw),
        ('Denoised (Gaussian)', vmin_den, vmax_den),
        ('Processed (Raw - Denoised)', vmin_proc, vmax_proc),
    ]

    for r, (row_label, raw, den, proc) in enumerate(rows):
        axes1[r, 0].set_ylabel(row_label, fontsize=12, fontweight='bold')
        imgs = [raw, den, proc]
        for c, (col_title, vmin, vmax) in enumerate(col_specs):
            ax = axes1[r, c]
            im = ax.imshow(imgs[c], cmap='RdBu_r', vmin=vmin, vmax=vmax, origin='upper')
            ax.set_title(col_title, fontsize=10)
            ax.set_xlabel('Pixel X')
            fig1.colorbar(im, ax=ax, fraction=0.046, label='B (Gauss)')

    fig1.tight_layout(rect=[0, 0.03, 1, 1])

    # -------------------------------------------------------
    # Figure 2: 1x3 comparison (bg processed / sample processed / subtracted)
    # -------------------------------------------------------
    fig2, axes2 = plt.subplots(1, 3, figsize=(17, 5))
    fig2.suptitle(title2, fontsize=10, fontweight='bold')

    panels = [
        (axes2[0], bg_processed,     vmin_proc_all, vmax_proc_all, 'Background\n(Processed: Raw - Denoised)'),
        (axes2[1], sample_processed, vmin_proc_all, vmax_proc_all, 'Sample\n(Processed: Raw - Denoised)'),
        (axes2[2], subtracted,       vmin_sub,      vmax_sub,      'Background-Subtracted\n(Sample - Background)'),
    ]
    for i, (ax, img, vmin, vmax, title) in enumerate(panels):
        im = ax.imshow(img, cmap='RdBu_r', vmin=vmin, vmax=vmax, origin='upper')
        ax.set_title(title, fontsize=11)
        ax.set_xlabel('Pixel X')
        if i == 0:
            ax.set_ylabel('Pixel Y')
        fig2.colorbar(im, ax=ax, fraction=0.046, label='B (Gauss)')

    fig2.tight_layout(rect=[0, 0.04, 1, 1])

    # --- Save ---
    if save_fig and save_path is not None:
        save_dir = Path(save_path) / subfolder
        save_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for fig_obj, base in [
            (fig1, f'background_subtraction_analysis_replot_{timestamp}.png'),
            (fig2, f'background_subtracted_comparison_replot_{timestamp}.png'),
        ]:
            out_path = save_dir / base
            fig_obj.savefig(out_path, dpi=300, bbox_inches='tight')
            print(f'Saved figure: {out_path}')

    if show_plot:
        plt.show()

    return {
        'figure_analysis': fig1,
        'figure_comparison': fig2,
    }


def plot_subtracted_field_map(
    result,
    vrange=None,
    figsize=(7, 5),
    title=None,
    show_plot=True,
    save_fig=False,
    save_path=None,
    subfolder="",
):
    """
    Plot only the background-subtracted field map as a single-panel figure.

    Takes the result dict from analyze_background_subtraction and plots just
    the subtracted result (sample_processed - bg_processed). Allows explicit
    control over the color range and figure size.

    Parameters
    ----------
    result : dict
        Output dict from analyze_background_subtraction (must contain key
        'subtracted' and optionally 'bg_file', 'sample_file', 'gaussian_sigma').
    vrange : tuple of (vmin, vmax) or None
        Explicit color limits in Gauss. If None, auto-computed as symmetric
        99.5th percentile (default).
    figsize : tuple of (width, height)
        Figure size in inches (default (7, 5)).
    title : str or None
        Figure title. If None, a default title is generated from the result
        metadata (filenames, gaussian_sigma).
    show_plot : bool
        Display the figure inline (default True).
    save_fig : bool
        Save the figure as a .png file (default False).
    save_path : str or Path or None
        Base directory for saving output.
    subfolder : str
        Subfolder within save_path.

    Returns
    -------
    matplotlib.figure.Figure
    """
    subtracted = result['subtracted']

    # Auto color limits
    if vrange is not None:
        vmin, vmax = vrange
    else:
        vals = subtracted[np.isfinite(subtracted)].ravel()
        vabs = np.nanpercentile(np.abs(vals), 99.5) if len(vals) > 0 else 1.0
        vmin, vmax = -vabs, vabs

    # Build default title from metadata
    if title is None:
        sigma = result.get('gaussian_sigma', None)
        bg_f = Path(result.get('bg_file', '')).name
        sample_f = Path(result.get('sample_file', '')).name
        parts = []
        if sigma is not None:
            parts.append(f'Gaussian sigma={sigma} px')
        if bg_f or sample_f:
            parts.append(f'BG: {bg_f}  |  Sample: {sample_f}')
        title = 'Background-Subtracted Field Map'
        if parts:
            title += '\n' + '  |  '.join(parts)

    fig, ax = plt.subplots(figsize=figsize)
    im = ax.imshow(subtracted, cmap='RdBu_r', vmin=vmin, vmax=vmax, origin='upper')
    ax.set_title(title, fontsize=10)
    ax.set_xlabel('Pixel X')
    ax.set_ylabel('Pixel Y')
    fig.colorbar(im, ax=ax, fraction=0.046, label='B (Gauss)')
    fig.tight_layout()

    if save_fig and save_path is not None:
        save_dir = Path(save_path) / subfolder
        save_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = save_dir / f'background_subtracted_single_{timestamp}.png'
        fig.savefig(out_path, dpi=300, bbox_inches='tight')
        print(f'Saved figure: {out_path}')

    if show_plot:
        plt.show()

    return fig


def fast_guess_p0(
    x: np.ndarray,
    y: np.ndarray,
    n_lorentz: int,
    gamma_min: float,
    gamma_max: float | None = None,
    freq_range: tuple[float, float] | None = None,
) -> np.ndarray:
    """
    Initial guess for ODMR dips using scipy peak finding.

    Uses scipy.signal.find_peaks to locate dips in the spectrum, providing
    more robust initial guesses than simple heuristics, especially for noisy data.
    Falls back to heuristic method if peak finding fails.

    Parameters
    ----------
    x : array-like
        Frequency values (assumed sorted)
    y : array-like
        ODMR spectrum (signal/reference)
    n_lorentz : int
        Number of Lorentzian peaks to fit
    gamma_min : float
        Minimum linewidth (HWHM) in same units as x
    gamma_max : float, optional
        Maximum linewidth (HWHM)
    freq_range : tuple, optional
        (min_freq, max_freq) to restrict search window

    Returns
    -------
    p0 : ndarray
        Initial parameters [c0, a1, x01, g1, a2, x02, g2, ...]
        where a_i is log-amplitude, x0_i is center, g_i is HWHM
    """
    # 1. Restrain work area to search window
    if freq_range is not None:
        mask = (x >= freq_range[0]) & (x <= freq_range[1])
        if np.any(mask):
            x_work, y_work = x[mask], y[mask]
            x_to_work_idx = np.where(mask)[0]  # Map work indices back to full array
        else:
            x_work, y_work = x, y
            x_to_work_idx = np.arange(len(x))
    else:
        x_work, y_work = x, y
        x_to_work_idx = np.arange(len(x))

    # 2. Calculate sampling parameters
    dx = np.median(np.diff(x)) if len(x) > 2 else (x[-1] - x[0]) / len(x) if len(x) > 1 else 0.001

    # Set gamma_max if not provided
    if gamma_max is None:
        xspan = x.max() - x.min()
        gamma_max = max(0.25 * xspan, 3 * gamma_min)

    # 3. Try peak finding on inverted signal (dips become peaks)
    y_inv = -y_work

    # Adaptive peak detection parameters
    min_distance = int(0.0015 / dx) if dx > 0 else 5  # ~1.5 MHz minimum separation
    baseline_inv = np.percentile(y_inv, 25)
    max_inv = np.max(y_inv)
    threshold = baseline_inv + 0.4 * (max_inv - baseline_inv)

    try:
        peaks, properties = find_peaks(
            y_inv,
            height=threshold,
            distance=min_distance,
            prominence=0.0003
        )

        # Sort peaks by prominence (deepest dips first)
        if len(peaks) > 0 and 'prominences' in properties:
            prominences = properties['prominences']
            sorted_idx = np.argsort(prominences)[::-1]
            peaks_sorted = peaks[sorted_idx]
        else:
            peaks_sorted = peaks
    except:
        peaks_sorted = np.array([])

    # 4. Build initial guess
    c0 = np.mean(y_work)
    p0 = [c0]

    if len(peaks_sorted) >= n_lorentz:
        # Use found peaks - take top n_lorentz by prominence, then sort by frequency
        top_peak_indices = sorted(peaks_sorted[:n_lorentz])

        for peak_idx in top_peak_indices:
            x0 = x_work[peak_idx]
            depth = c0 - y_work[peak_idx]
            a_log = np.log(max(depth, 1e-6))

            # Estimate width from half-depth points
            half_val = y_work[peak_idx] + depth / 2
            left_mask = (x_work < x0) & (y_work < half_val)
            right_mask = (x_work > x0) & (y_work < half_val)

            if np.any(left_mask) and np.any(right_mask):
                left_idx = np.where(left_mask)[0]
                right_idx = np.where(right_mask)[0]
                g0 = (x_work[right_idx[0]] - x_work[left_idx[-1]]) / 2
            else:
                g0 = 10.0 * dx

            # Clip to bounds
            g0 = np.clip(g0, gamma_min, gamma_max * 0.99)

            p0 += [a_log, x0, g0]

    else:
        # Fallback to simple heuristic if peak finding failed
        jmin = np.argmin(y_work)
        x_center = x_work[jmin]

        depth = max(c0 - y_work[jmin], 1e-6)
        a_each = np.log(depth / n_lorentz)
        g0 = np.clip(max(10.0 * dx, gamma_min), gamma_min, gamma_max * 0.99)

        # Assume hyperfine splitting ~2-3 MHz
        sep = max(6.0 * dx, 0.002)
        offsets = (np.arange(n_lorentz) - (n_lorentz - 1) / 2.0) * sep

        for offset in offsets:
            p0 += [a_each, x_center + offset, g0]

    return np.array(p0, dtype=float)

# ============================================================
# Generate synthetic data for simulation mode (troubleshooting when setup is not on)
# ============================================================
def generate_synthetic_qdm_cube(freqlist, field_map, base_counts=10000):
    """
    Generates a full 3D ODMR data cube (Freq, Y, X) in one go using vectorization.
    """
    D, gamma_e, A = 2.870, 28.024, 0.00303
    linewidth, contrast = 0.001, 0.05
    
    # 1. Pre-calculate resonance maps (Shape: 1, Y, X)
    f_low = (D - (gamma_e * field_map))[None, :, :]
    f_high = (D + (gamma_e * field_map))[None, :, :]
    
    # 2. Reshape freqlist to (Freq, 1, 1) for broadcasting
    f_grid = freqlist[:, None, None]
    gamma_half_sq = (linewidth / 2)**2

    def lorentzian_vec(f, f0):
        return gamma_half_sq / ((f - f0)**2 + gamma_half_sq)
    
    # 3. Calculate all dips simultaneously
    dip_low = (contrast / 2) * (lorentzian_vec(f_grid, f_low - A/2) + 
                               lorentzian_vec(f_grid, f_low + A/2))
    dip_high = (contrast / 2) * (lorentzian_vec(f_grid, f_high - A/2) + 
                                lorentzian_vec(f_grid, f_high + A/2))
    
    cube = base_counts * (1 - (dip_low + dip_high))
    
    # 4. Poisson noise on the entire volume
    return np.random.poisson(cube).astype(np.float32)

def create_field_map(shape, pattern='none', bias_tesla=0.0125):
    """
    Creates a spatial B-field distribution in Tesla.
    """
    y, x = np.indices(shape)
    center = np.array(shape) / 2
    dist_from_center = np.sqrt((x - center[1])**2 + (y - center[0])**2)
    
    # Start with the global bias field (quantization axis)
    field_map = np.full(shape, bias_tesla)
    
    # Add the local sample field on top
    if pattern == 'loop':
        radius = shape[0] // 4
        field_map += 1e-3 * np.exp(-((dist_from_center - radius)**2) / (radius/2)**2)
    elif pattern == 'square':
        mask = (np.abs(x - center[1]) < shape[1]//4) & (np.abs(y - center[0]) < shape[0]//4)
        field_map[mask] += 0.5e-3 # +0.5 mT sample field
        
    return field_map

# ============================================================================
# DIAGNOSTIC FUNCTIONS - Per-pixel ODMR Data Analysis
# ============================================================================

# These functions help analyze per-pixel ODMR data quality



def extract_pixels_by_fit_quality(
    odmr_data_cube,
    freqlist,
    fit_results_file,
    r2_range=(0.0, 1.0),
    max_pixels=None,
    return_binned=True,
    random_seed=None
):
    """
    Extract pixel spectra from ODMR data based on fit quality (R²).

    Handles binning mismatch: if fit results were generated from binned data,
    this function maps back to original pixel coordinates and optionally
    rebins to match what was actually fitted.

    Parameters
    ----------
    odmr_data_cube : ndarray or str
        3D ODMR data (Freq, Y, X) or path to .npz file containing 'data' key
    freqlist : ndarray or None
        Frequency array. If None and odmr_data_cube is a file path,
        loaded from file's 'frequencies' key
    fit_results_file : str
        Path to widefield_fit_results_*.npz file from process_widefield_odmr()
    r2_range : tuple
        (min_r2, max_r2) range to select pixels (inclusive)
    max_pixels : int or None
        Maximum number of pixels to return. If more pixels match the criteria,
        a random sample is returned. None = return all matching pixels.
    return_binned : bool
        If True and fit used binning, return the binned spectra that were actually fit.
        If False, return individual unbinned pixel spectra from the original data.
    random_seed : int or None
        Random seed for reproducible sampling when max_pixels is used

    Returns
    -------
    dict with keys:
        'spectra' : ndarray, shape (n_pixels, n_freq)
            Pixel spectra (binned if return_binned=True and binning was used)
        'freqlist' : ndarray, shape (n_freq,)
            Frequency array
        'coordinates' : ndarray, shape (n_pixels, 2)
            Pixel coordinates as (y, x). If return_binned=True, these are
            bin-center coordinates in original data space. If False, individual
            pixel coordinates.
        'fit_coordinates' : ndarray, shape (n_pixels, 2) or (n_bins, 2)
            Coordinates in the fit results space (binned coordinates)
        'r2_values' : ndarray, shape (n_pixels,) or (n_bins,)
            R² fit quality for each pixel/bin
        'freq_centers' : ndarray, shape (n_pixels,) or (n_bins,)
            Fitted frequency centers [GHz]
        'field_values' : ndarray, shape (n_pixels,) or (n_bins,)
            Magnetic field values [Gauss] if available in fit results
        'bin_factors' : tuple (bin_y, bin_x)
            Binning factors used in fit (1, 1) if no binning
        'n_selected' : int
            Number of pixels/bins matching criteria (before max_pixels limit)
        'n_returned' : int
            Number of pixels/bins actually returned (after max_pixels limit)
    """
    from pathlib import Path

    # Load ODMR data
    if isinstance(odmr_data_cube, (str, Path)):
        odmr_file = np.load(odmr_data_cube)
        cube = odmr_file['data']
        if freqlist is None:
            freqlist = odmr_file['frequencies']
    else:
        cube = odmr_data_cube

    if freqlist is None:
        raise ValueError("freqlist must be provided if odmr_data_cube is an array")

    # Load fit results
    fit_data = np.load(fit_results_file)
    r2_map = fit_data['fit_quality_map']
    freq_map = fit_data['freq_center_map']

    # Get field map if available
    field_map = fit_data.get('field_map_gauss', None)

    # Determine binning factors
    fit_shape = r2_map.shape  # (ny_fit, nx_fit)
    orig_shape = cube.shape[1:]  # (ny_orig, nx_orig)
    bin_y = orig_shape[0] // fit_shape[0]
    bin_x = orig_shape[1] // fit_shape[1]

    # Validate binning
    if orig_shape[0] != fit_shape[0] * bin_y or orig_shape[1] != fit_shape[1] * bin_x:
        print(f"Warning: Shape mismatch. Original {orig_shape}, Fit {fit_shape}, "
              f"inferred binning ({bin_y}, {bin_x})")

    # Find pixels matching R² criteria
    mask = (r2_map >= r2_range[0]) & (r2_map <= r2_range[1])
    fit_coords = np.argwhere(mask)  # (n_matched, 2) as (y_fit, x_fit)
    n_selected = len(fit_coords)

    # Sample if needed
    if max_pixels is not None and n_selected > max_pixels:
        if random_seed is not None:
            np.random.seed(random_seed)
        indices = np.random.choice(n_selected, size=max_pixels, replace=False)
        fit_coords = fit_coords[indices]

    n_returned = len(fit_coords)

    # Extract data
    if return_binned and (bin_y > 1 or bin_x > 1):
        # Return binned spectra (what was actually fit)
        binned_cube = bin_qdm_cube(cube, bin_x, bin_y)
        spectra = np.array([binned_cube[:, y, x] for y, x in fit_coords])

        # Bin-center coordinates in original space
        coords = np.array([
            (y * bin_y + bin_y / 2 - 0.5, x * bin_x + bin_x / 2 - 0.5)
            for y, x in fit_coords
        ])
    else:
        # Return unbinned individual pixels
        if bin_y > 1 or bin_x > 1:
            # Each fit pixel corresponds to multiple original pixels
            all_spectra = []
            all_coords = []
            for y_fit, x_fit in fit_coords:
                y_start = y_fit * bin_y
                x_start = x_fit * bin_x
                for dy in range(bin_y):
                    for dx in range(bin_x):
                        y = y_start + dy
                        x = x_start + dx
                        all_spectra.append(cube[:, y, x])
                        all_coords.append((y, x))
            spectra = np.array(all_spectra)
            coords = np.array(all_coords)
        else:
            # No binning, 1:1 correspondence
            spectra = np.array([cube[:, y, x] for y, x in fit_coords])
            coords = fit_coords.astype(float)

    # Extract fit parameters for selected pixels
    r2_values = np.array([r2_map[y, x] for y, x in fit_coords])
    freq_centers = np.array([freq_map[y, x] for y, x in fit_coords])

    if field_map is not None:
        field_values = np.array([field_map[y, x] for y, x in fit_coords])
    else:
        field_values = None

    return {
        'spectra': spectra,
        'freqlist': freqlist,
        'coordinates': coords,
        'fit_coordinates': fit_coords,
        'r2_values': r2_values,
        'freq_centers': freq_centers,
        'field_values': field_values,
        'bin_factors': (bin_y, bin_x),
        'n_selected': n_selected,
        'n_returned': n_returned
    }


def extract_pixels_by_roi(
    odmr_data_cube,
    freqlist,
    x_range=None,
    y_range=None,
    fit_results_file=None,
    bin_x=1,
    bin_y=1
):
    """
    Extract pixel spectra from a spatial region of interest (ROI).

    Parameters
    ----------
    odmr_data_cube : ndarray or str
        3D ODMR data (Freq, Y, X) or path to .npz file containing 'data' key
    freqlist : ndarray or None
        Frequency array. If None and odmr_data_cube is a file path,
        loaded from file's 'frequencies' key
    x_range : tuple or None
        (x_min, x_max) in original data coordinates (inclusive).
        None = full X range
    y_range : tuple or None
        (y_min, y_max) in original data coordinates (inclusive).
        None = full Y range
    fit_results_file : str or None
        Optional path to fit results to include R² and fit parameter info
    bin_x, bin_y : int
        Binning factors to apply to extracted region (default 1 = no binning).
        If >1, pixels are spatially binned before returning.

    Returns
    -------
    dict with keys:
        'spectra' : ndarray, shape (n_pixels, n_freq)
            Pixel spectra (binned if bin_x/bin_y > 1)
        'freqlist' : ndarray, shape (n_freq,)
            Frequency array
        'coordinates' : ndarray, shape (n_pixels, 2)
            Pixel coordinates as (y, x) in original data space.
            If binning applied, these are bin-center coordinates.
        'r2_values' : ndarray or None
            R² fit quality (if fit_results_file provided)
        'freq_centers' : ndarray or None
            Fitted frequency centers [GHz] (if fit_results_file provided)
        'field_values' : ndarray or None
            Magnetic field [Gauss] (if fit_results_file provided)
        'roi_shape' : tuple (ny, nx)
            Shape of extracted ROI before binning
        'bin_factors' : tuple (bin_y, bin_x)
            Binning factors applied
    """
    from pathlib import Path

    # Load ODMR data
    if isinstance(odmr_data_cube, (str, Path)):
        odmr_file = np.load(odmr_data_cube)
        cube = odmr_file['data']
        if freqlist is None:
            freqlist = odmr_file['frequencies']
    else:
        cube = odmr_data_cube

    if freqlist is None:
        raise ValueError("freqlist must be provided if odmr_data_cube is an array")

    n_freq, ny_orig, nx_orig = cube.shape

    # Set default ranges
    if x_range is None:
        x_range = (0, nx_orig - 1)
    if y_range is None:
        y_range = (0, ny_orig - 1)

    # Validate and clip ranges
    x_min = max(0, min(x_range))
    x_max = min(nx_orig - 1, max(x_range))
    y_min = max(0, min(y_range))
    y_max = min(ny_orig - 1, max(y_range))

    # Extract ROI
    roi_cube = cube[:, y_min:y_max+1, x_min:x_max+1]
    roi_shape = roi_cube.shape[1:]  # (ny_roi, nx_roi)

    # Apply binning if requested
    if bin_x > 1 or bin_y > 1:
        binned_cube = bin_qdm_cube(roi_cube, bin_x, bin_y)
        ny_bin, nx_bin = binned_cube.shape[1:]

        # Generate bin-center coordinates
        coords = []
        for iy in range(ny_bin):
            for ix in range(nx_bin):
                y_center = y_min + iy * bin_y + bin_y / 2 - 0.5
                x_center = x_min + ix * bin_x + bin_x / 2 - 0.5
                coords.append((y_center, x_center))
        coords = np.array(coords)

        # Flatten spatial dimensions
        spectra = binned_cube.reshape(n_freq, -1).T  # (n_pixels, n_freq)
    else:
        # No binning
        ny_roi, nx_roi = roi_shape
        coords = []
        for iy in range(ny_roi):
            for ix in range(nx_roi):
                coords.append((y_min + iy, x_min + ix))
        coords = np.array(coords)

        spectra = roi_cube.reshape(n_freq, -1).T  # (n_pixels, n_freq)

    # Load fit results if provided
    r2_values = None
    freq_centers = None
    field_values = None

    if fit_results_file is not None:
        fit_data = np.load(fit_results_file)
        r2_map = fit_data['fit_quality_map']
        freq_map = fit_data['freq_center_map']
        field_map = fit_data.get('field_map_gauss', None)

        # Determine fit binning
        fit_shape = r2_map.shape
        fit_bin_y = ny_orig // fit_shape[0]
        fit_bin_x = nx_orig // fit_shape[1]

        # Map coordinates to fit space and extract values
        r2_list = []
        freq_list = []
        field_list = [] if field_map is not None else None

        for y, x in coords:
            # Map to fit coordinates (handle fractional coordinates from bin centers)
            y_fit = int(y / fit_bin_y)
            x_fit = int(x / fit_bin_x)

            # Clip to valid range
            y_fit = np.clip(y_fit, 0, fit_shape[0] - 1)
            x_fit = np.clip(x_fit, 0, fit_shape[1] - 1)

            r2_list.append(r2_map[y_fit, x_fit])
            freq_list.append(freq_map[y_fit, x_fit])
            if field_map is not None:
                field_list.append(field_map[y_fit, x_fit])

        r2_values = np.array(r2_list)
        freq_centers = np.array(freq_list)
        if field_list is not None:
            field_values = np.array(field_list)

    return {
        'spectra': spectra,
        'freqlist': freqlist,
        'coordinates': coords,
        'r2_values': r2_values,
        'freq_centers': freq_centers,
        'field_values': field_values,
        'roi_shape': roi_shape,
        'bin_factors': (bin_y, bin_x)
    }


def plot_pixel_spectra(
    pixel_data,
    title="Pixel Spectra",
    max_plots=9,
    figsize=None,
    show_fit_info=True,
    colormap='viridis',
    sort_by='r2'
):
    """
    Plot multiple pixel spectra in a grid for diagnostic purposes.

    Parameters
    ----------
    pixel_data : dict
        Output from extract_pixels_by_fit_quality() or extract_pixels_by_roi()
    title : str
        Overall figure title
    max_plots : int
        Maximum number of spectra to plot in grid
    figsize : tuple or None
        Figure size (width, height). If None, auto-calculated based on grid size
    show_fit_info : bool
        If True, include R²/frequency info in subplot titles (if available)
    colormap : str
        Colormap name for coloring plots by R² value
    sort_by : str
        How to order plots: 'r2' (highest first), 'r2_ascending' (lowest first),
        'freq' (by fitted frequency), 'spatial' (by position), 'random'

    Returns
    -------
    fig : matplotlib.figure.Figure
        The created figure
    """
    import matplotlib.pyplot as plt
    from matplotlib import cm

    spectra = pixel_data['spectra']
    freqlist = pixel_data['freqlist']
    coords = pixel_data['coordinates']
    r2_values = pixel_data.get('r2_values', None)
    freq_centers = pixel_data.get('freq_centers', None)

    n_pixels = len(spectra)
    n_plots = min(n_pixels, max_plots)

    # Determine grid size
    n_cols = int(np.ceil(np.sqrt(n_plots)))
    n_rows = int(np.ceil(n_plots / n_cols))

    if figsize is None:
        figsize = (5 * n_cols, 4 * n_rows)

    # Sort pixels
    if sort_by == 'r2' and r2_values is not None:
        indices = np.argsort(r2_values)[::-1][:n_plots]  # Highest R² first
    elif sort_by == 'r2_ascending' and r2_values is not None:
        indices = np.argsort(r2_values)[:n_plots]  # Lowest R² first
    elif sort_by == 'freq' and freq_centers is not None:
        indices = np.argsort(freq_centers)[:n_plots]
    elif sort_by == 'spatial':
        indices = np.arange(n_plots)  # Original order
    elif sort_by == 'random':
        indices = np.random.choice(n_pixels, size=n_plots, replace=False)
    else:
        indices = np.arange(n_plots)

    # Setup colormap for R² values
    if r2_values is not None and len(r2_values) > 0:
        r2_min = max(0, np.nanmin(r2_values))
        r2_max = min(1, np.nanmax(r2_values))
        norm = plt.Normalize(vmin=r2_min, vmax=r2_max)
        cmap = cm.get_cmap(colormap)
    else:
        norm = None
        cmap = None

    # Create figure
    fig, axes = plt.subplots(n_rows, n_cols, figsize=figsize)
    if n_plots == 1:
        axes = np.array([axes])
    axes = axes.flatten()

    for i, idx in enumerate(indices):
        ax = axes[i]
        spectrum = spectra[idx]
        coord = coords[idx]

        # Determine line color
        if r2_values is not None and cmap is not None:
            color = cmap(norm(r2_values[idx]))
        else:
            color = 'blue'

        # Plot spectrum
        ax.plot(freqlist, spectrum, '-', linewidth=1.5, color=color, alpha=0.8)
        ax.plot(freqlist, spectrum, '.', markersize=3, color=color, alpha=0.6)

        # Format axes
        ax.set_xlabel('Frequency (GHz)', fontsize=9)
        ax.set_ylabel('Signal/Reference', fontsize=9)
        ax.grid(True, alpha=0.3)
        ax.tick_params(labelsize=8)

        # Build title
        title_parts = [f'Pixel ({coord[0]:.1f}, {coord[1]:.1f})']
        if show_fit_info:
            if r2_values is not None:
                title_parts.append(f'R²={r2_values[idx]:.4f}')
            if freq_centers is not None:
                title_parts.append(f'f={freq_centers[idx]:.5f} GHz')

        ax.set_title(', '.join(title_parts), fontsize=10)

    # Hide unused subplots
    for i in range(n_plots, len(axes)):
        axes[i].axis('off')

    fig.suptitle(title, fontsize=14, fontweight='bold')
    plt.tight_layout()

    return fig
