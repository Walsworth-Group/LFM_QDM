# Project overview
Code to control instruments to perform CW ODMR magnetometry with nitrogen-vacancy centers in diamond in a widefield quantum diamond microscope (QDM) setup. The experiment seeks to use a widefield NV QDM to image magnetic fields from magnetostatic bacteria, as proof of potential biological applications of quantum sensing.

## Goals
* Short term: improve and extend capabilities for performing CW ODMR magnetometry, including a) modularizing scripts and functions, e.g. those whose code is currently in the Jupyter notebook rather than in .py files, b) adding capability for longer-term averaging (since the magnetostatic bacteria signal is potentially very small), including periodically monitoring the laser power and adjusting PID controller settings if needed, c) create a library of functions to interact with DAQ to handle data acquisition from photodiodes,
* Longer term: 1) convert Jupyter notebook into a full GUI program (e.g. using NiceGUI framework) with buttons that can both be pressed by humans as well as executed by AI via command line interface
* Very long term: integrate LLM chat into GUI program so that AI can fully plan and execute experiments based on human commands

## List of experimental hardware connected to computer
* Laser: Lighthouse Sprout 10 W 532 nm - currently controlled either directly on the device or using the Lighthouse RC program. The laser is aligned through an AOM which allows it to be pulsed on/off quickly if needed (e.g. in pulsed quantum sensing experiments, although we are not focusing on that right now), as well as partially turned down in power by modifying the AOM voltage.
* AOM (Acousto-optical modulator) RF source: Agilent E4430B signal generator supplies voltage to AOM. Modifying this voltage effectively allows controlling the laser power. Currently not yet connected to the computer.
* Laser power monitoring: a 90/10 beam splitter with the side port output connected to a PD to measure the laser power right before it enters the QDM breadboard. The PD voltage is connected to Dev3 DAQ, channel AI0. Can be monitored with laser_power_app.py
* Laser stabilization: SRS SIM960 Analog PID controller in a SIM900 Mainframe chassis. Output voltage is fed to the Agilent E4430B which allows modulating the AOM voltage, thus modulating the laser power. Currently connected to the computer via DB9/USB COM3 and can be controlled with pid_control_app.py
* Microwave generator: 2x SRS SG384 (currently using only one), connected via TCP IP. Has several hardware MW amplifiers connected to the output before being delivered to the diamond via an omega loop. 
* Main widefield imaging camera: Basler acA1920-155um (SN 25061217), connected via USB.
* Data acquisition systems: two NI USB 6361 (Dev1, Dev3), currently only used when taking QDM calibration/alignment data with photodiode rather than camera, as well as to monitor laser power
* Motorized linear stages: Thorlabs KCube DC motor controller. Controls mirror used to redirect laser beam from photodiode to camera. Currently controlled using Thorlabs Kinesis program

## Key files
* Camera ODMR-new.ipynb: top-level Jupyter notebook used to execute experimental procedures (e.g. ODMR frequency sweep) and display results. Some scripts and functions are still pasted inside notebook cells. Currently we open this notebook to run experiments.
* qdm_basler.py: library of custom functions to acquire data with Basler camera
* qdm_srs.py: library of custom functions to control SRS RF generators
* qdm_gen.py: general function library. Contains functions for data processing, plotting, and others not specifically associated with experimental hardware. If adding new functions, please keep up the organization.
* qdm_nidaq.py: library of functions for NI-DAQ data acquisition (analog input from photodiodes, laser power monitoring)

## Important functions

### Hardware Control & Initialization
* `initialize_system(simulation_mode, settings, logger)` in qdm_gen.py - Top-level function to initialize camera + SRS or simulation mode. Returns dict with `camera_instance`, `sg384`, `ny`, `nx`, and optionally `sim_field_map`.
* `basler` class in qdm_basler.py - Context manager for Basler camera. Key methods:
  - `connect()` / `close()` - Open/close camera connection
  - `grab_frames(n_frames, quiet)` - Grab and average n_frames, returns 2D numpy array
  - `connect_and_open(choice, exposure_time_us, ...)` - Static method for quick setup
* `SG384Controller` class in qdm_srs.py - Controls SRS SG384 signal generator via PyVISA. Key methods:
  - `open_connection()` / `close_connection()`
  - `set_frequency(frequency, unit='MHz')` - Set MW frequency
  - `set_amplitude(level)` - Set RF power in dBm

### ODMR Data Acquisition
* `run_odmr_sweep(freqlist, ref_freq, num_sweeps, settings, simulation_mode, live_plot, auto_analyze, save_data, ...)` in qdm_gen.py - **High-level function** to run complete ODMR sweep. Handles init, acquisition, live PL plotting, optional auto-analysis, optional data saving, cleanup. If `save_data=True`, saves `odmr_data_cube` and `freqlist` to timestamped .npz file. Returns dict with `odmr_data_cube`, `freqlist`, `elapsed_time`, dimensions, and optionally `peak_params`.
* `run_stability_measurement(fixed_freq, ref_freq, num_samples, settings, simulation_mode, show_progress, save_data, ...)` in qdm_gen.py - **High-level function** to acquire stability/noise data at fixed frequency. Handles init, acquisition, cleanup, optional saving. Returns dict with `stability_cube`, `settings`, `elapsed_time`, dimensions.
* `run_hardware_sweep(freqlist, ref_freq, settings, handles, odmr_data_cube, pbar, sweep_num, live_plot_ctx)` in qdm_gen.py - Performs one physical frequency sweep, updates odmr_data_cube in-place
* `run_simulation_sweep(freqlist, ref_freq, settings, sim_field_map, odmr_data_cube, pbar, sweep_num, live_plot_ctx)` in qdm_gen.py - Simulated sweep using vectorized synthetic data
* `measure_odmr_point(sg384, camera, freq, ref_freq, settling_time, n_frames, odmr_data_cube, idx)` in qdm_gen.py - Single signal/reference measurement at one frequency point
* `run_stability_check(fixed_freq, ref_freq, settings, handles, stability_cube, pbar)` in qdm_gen.py - Low-level worker for repeated measurements at fixed frequency (called by run_stability_measurement)

### Multi-Point Differential Magnetometry (Global Mean)
* `identify_multi_transition_inflection_points(start_freq1, end_freq1, num_steps1, start_freq2, end_freq2, num_steps2, ref_freq, num_sweeps, settings, ...)` in qdm_gen.py - **High-level function** to identify all inflection points, slopes, and baseline contrasts from both NV transitions (m=0→-1 and m=0→+1). Runs two ODMR sweeps, analyzes both, extracts all inflection points (typically 8 total from 4 hyperfine peaks), their slopes, and their expected baseline contrasts (from the fitted ODMR model). Returns dict with `inflection_points` array, `inflection_slopes` array (in GHz^-1), `inflection_contrasts` array, sweep results, and peak parameters. **Uses global mean ODMR** - single slope value applied across entire FOV.
* `format_multi_point_frequencies(inflection_points, inflection_slopes, indices, parities, ref_freq, inflection_contrasts=None)` in qdm_gen.py - **Helper function** to select specific inflection points/slopes/contrasts and format for multi-point measurement with flexible reference placement. Use 0 in indices to specify where references occur. Returns (freq_list, slope_list, parity_list, baseline_list) ready for measurement.
* `measure_multi_point(sg384, camera, freq_list, slope_list, parity_list, settling_time, n_frames, baseline_list=None)` in qdm_gen.py - **Low-level measurement function** with automatic PL-to-frequency conversion. Measures PL at multiple frequencies, converts each to frequency shift using slopes and per-frequency baseline contrasts: Δf = (C_measured - C_baseline) / slope. If baseline_list is None, defaults to 1.0 for all points. Returns combined frequency shift result (ny, nx) in GHz.
* `run_multi_point_stability_measurement(freq_list, slope_list, parity_list, num_samples, settings, baseline_list=None, ...)` in qdm_gen.py - **High-level function** for multi-point stability measurement. Uses generalized multi-point scheme with automatic PL-to-frequency conversion using actual baseline contrasts. Returns dict with `stability_cube` (in GHz), `freq_list`, `slope_list`, `parity_list`, `baseline_list`, settings, timing.
* `analyze_multi_point_magnetometry(stability_cube, outlier_sigma, denoise_method, show_plot, save_fig, save_data, ...)` in qdm_gen.py - **High-level function** to analyze multi-point magnetometry data. Takes stability cube already in frequency units (GHz), applies outlier removal and denoising, converts to magnetic field (B = freq/γ_e), generates 3-panel plot (raw, denoised, processed). Returns dict with field maps, frequency maps, noise maps, and figure. **Works with both global mean and spatially-binned measurements.**

### Spatially-Binned Multi-Point Magnetometry (Gradient Compensation)
**NEW (2026-02-13):** Functions for automatic spatial gradient compensation using per-bin ODMR slopes. Use when bias field gradients are significant and need to be automatically compensated. See `BINNED_MAGNETOMETRY_EXAMPLES.md` for detailed usage examples.

* `identify_multi_transition_inflection_points_binned(start_freq1, end_freq1, num_steps1, start_freq2, end_freq2, num_steps2, ref_freq, num_sweeps, settings, bin_x, bin_y, ...)` in qdm_gen.py - **High-level function** for spatially-binned ODMR analysis. Bins data spatially (user-specified bin_x, bin_y), performs parallel per-bin Lorentzian fitting, extracts local inflection points/slopes/contrasts. Returns 3D parameter arrays: `inflection_points` (8, ny_bins, nx_bins), `inflection_slopes` (8, ny_bins, nx_bins), `inflection_contrasts` (8, ny_bins, nx_bins). Always displays global mean ODMR for verification. Optional spatial parameter visualization with `show_binned_maps=True`. Handles failed bins by using global mean as fallback. **Recommend ≥10 sweeps for good per-bin SNR.**
* `format_multi_point_frequencies_binned(inflection_points, inflection_slopes, indices, parities, ref_freq, inflection_contrasts, bin_x, bin_y)` in qdm_gen.py - **Helper function** to select subset of spatially-varying inflection points and format for binned measurement. Takes 3D input arrays (N, ny_bins, nx_bins), returns 3D output arrays (n_points, ny_bins, nx_bins) ready for `measure_multi_point_binned()`.
* `measure_multi_point_binned(sg384, camera, freq_array, slope_array, parity_list, baseline_array, settling_time, n_frames, ny_full, nx_full, upsample_order=1)` in qdm_gen.py - **Low-level measurement function** with spatially-varying PL-to-frequency conversion. Upsamples parameter arrays from bin resolution to full camera resolution using scipy.ndimage.zoom (default: bilinear interpolation). Applies per-pixel slopes: Δf = (C_measured - C_baseline) / slope_pixel. Returns frequency shift map (ny_full, nx_full) in GHz.
* `run_multi_point_stability_measurement_binned(freq_array, slope_array, parity_list, baseline_array, num_samples, settings, bin_x, bin_y, ...)` in qdm_gen.py - **High-level function** for binned stability measurement. Orchestrates repeated measurements with spatially-varying parameters. Saves all parameter arrays (freq_array, slope_array, baseline_array) to .npz for reproducibility. Returns dict with `stability_cube` (num_samples, ny, nx) in GHz, parameter arrays, settings, timing.
* **Helper functions** (internal, called by binned functions):
  - `_extract_peak_params_from_popt(popt, baseline, model_func, n_lorentz)` - Refactored helper to extract structured peak parameters from fit results. Shared by `fit_global_odmr()` and binned fitting to eliminate code duplication.
  - `_fit_single_bin_odmr(spectrum, freqlist, n_lorentz, fit_tolerance, max_iters, freq_range)` - Worker function for per-bin ODMR fitting. Designed for parallel processing with joblib. Returns inflection points, slopes, contrasts, fit quality, or None if fit fails.
  - `_upsample_parameter_array(param_array, ny_full, nx_full, order=1)` - Upsample 2D array from bin resolution to full camera resolution. Uses scipy.ndimage.zoom with configurable interpolation: order=0 (nearest-neighbor), order=1 (bilinear, default), order=3 (cubic).

**Choosing between global mean vs. binned approaches:**
- **Global mean** (faster, simpler): Use when bias field is homogeneous across FOV. Single ODMR fit, low computational cost, good SNR. Default choice for most experiments.
- **Spatially-binned** (automatic gradient compensation): Use when bias field gradients are significant and mask small features (e.g., magnetostatic bacteria). Automatically compensates spatial variations in ODMR slope/frequency. Requires more sweeps (≥10), higher computational cost (parallel fitting ~2-3s for 30×48 bins), slightly higher noise per pixel. Trade spatial resolution (bin size) for SNR (larger bins = better fits but less spatial detail).

### ODMR Fitting & Analysis
* `analyze_and_plot_odmr(odmr_data_cube, freqlist, n_lorentz, x_roi, y_roi, show_plot, save_fig, ...)` in qdm_gen.py - **High-level function** for ODMR analysis. Fits Lorentzians, plots data with inflection points, prints summary. Returns dict with analysis results, figure, and peak_params.
* `analyze_stability_data(stability_cube, acquisition_settings, peak_params, slope_override, time_per_point_override, ...)` in qdm_gen.py - **High-level function** for stability/sensitivity analysis. Auto-extracts slope from ODMR peak_params and calculates time-per-point from settings. Supports manual overrides. Returns dict with sensitivities, pixel maps, and cleaned time series.
* `select_inflection_point(peak_params, manual_freq, side, peak_index, verbose)` in qdm_gen.py - **Helper function** to select inflection point frequency from ODMR analysis. Auto-detects left/right inflection point from specified peak, or allows manual override. Returns selected frequency in GHz. Prints clear selection info if verbose=True.
* `analyze_inflection_point_magnetometry(stability_cube, acquisition_settings, peak_params, inflection_freq, reference_mode, ...)` in qdm_gen.py - **High-level function** for single-point inflection point magnetometry. Converts mean S/R at each pixel to relative magnetic field using ODMR slope. **Auto-detects** which inflection point (left or right) is being measured by comparing `inflection_freq` to `peak_params` inflection points, and applies the correct **signed slope** (negative for left, positive for right). Supports outlier removal, multiple reference modes (global_mean, roi), and optional denoising. Returns dict with field_map_gauss, mean_contrast_map, noise_map, and figure.
* `analyze_allan_variance(sensitivity_result, show_plot, save_fig, ...)` in qdm_gen.py - Computes overlapping Allan deviation (OADEV) from sensitivity analysis results. Plots measured stability vs shot-noise limit. Returns dict with taus, adevs, errors, figure. Requires `allantools` package.
* `process_widefield_odmr(odmr_data_cube, freqlist, n_lorentz, bin_x, bin_y, fit_tolerance, save_data, ...)` in qdm_gen.py - **High-level function** for pixel-by-pixel fitting to generate magnetic field maps. Plots both field map and frequency center map. If `save_data=True`, saves per-pixel fit results (`freq_center_map`, `fit_quality_map`, `field_map_gauss`, and metadata) to timestamped .npz file for investigating fit failures. Returns dict with field_map_gauss, freq_center_map, fit_quality_map, and both figures.
* `plot_field_map(field_map_gauss, title, cmap)` in qdm_gen.py - Create publication-ready magnetic field map plot (default colormap: 'RdBu_r', centered at zero).
* `plot_frequency_map(freq_center_map, title, cmap)` in qdm_gen.py - Create publication-ready resonance frequency map plot (default colormap: 'viridis').
* `plot_field_map_comparison(raw, denoised, processed, method_name)` in qdm_gen.py - 3-panel comparison plot (raw, denoised, processed) for field maps.
* `denoise_field_map(field_map, method, ...)` in qdm_gen.py - Apply denoising to a field map. Methods: 'none', 'gaussian', 'tv', 'wavelet', 'nlm', 'bilateral'. Key kwargs: `gaussian_sigma`, `tv_weight`.
* `analyze_background_subtraction(bg_file, sample_file, gaussian_sigma, save_path, subfolder, show_plot, save_fig, save_data)` in qdm_gen.py - **High-level function** for background subtraction of magnetometry field maps. Loads two `.npz` field map files (background = no sample, sample = with sample), re-applies Gaussian denoising, computes processed (raw − denoised) for each, and subtracts processed background from processed sample. Generates: (1) 2×3 figure with raw/denoised/processed for both; (2) 1×3 comparison figure with bg_processed, sample_processed, and subtracted result. Saved .png files include filenames embedded at bottom. Returns dict with `bg_raw/denoised/processed`, `sample_raw/denoised/processed`, `subtracted`, `figure_analysis`, `figure_comparison`.
* `fit_global_odmr(odmr_data_cube, freqlist, n_lorentz=2)` in qdm_gen.py - Spatially averages cube, fits N Lorentzians. Returns dict with fit params, `peak_params` list (see Key Data Structures below), popt, model function, x/y fit data, and R².
* `fit_lorentzians(x, y, n_lorentz, ...)` in qdm_gen.py - Low-level robust Lorentzian fitting using scipy least_squares. Supports bounds, tolerances, robust loss functions. Returns dict with popt, model callable, R², and raw scipy result.
* `fit_pixel_worker(pixel_spectrum, freqlist, n_lorentz, ...)` in qdm_gen.py - Fits single pixel spectrum, designed for parallel processing. Returns (f_center, r2).
* `fast_guess_p0(x, y, n_lorentz, gamma_min, gamma_max, freq_range)` in qdm_gen.py - O(N) heuristic initial guess for Lorentzian fit parameters

### Diagnostic & Per-Pixel Analysis
* `extract_pixels_by_fit_quality(odmr_data_cube, freqlist, fit_results_file, r2_range, max_pixels, return_binned, ...)` in qdm_gen.py - Extract pixel spectra based on R² fit quality range. Handles binning mismatch between original data and fit results. Returns dict with spectra, coordinates, fit parameters, etc.
* `extract_pixels_by_roi(odmr_data_cube, freqlist, x_range, y_range, fit_results_file, bin_x, bin_y, ...)` in qdm_gen.py - Extract pixel spectra from spatial ROI. Optionally includes fit quality info if fit_results_file provided.
* `plot_pixel_spectra(pixel_data, title, max_plots, sort_by, ...)` in qdm_gen.py - Plot multiple pixel spectra in grid for diagnostics. Color-codes by R² value, supports sorting by quality/frequency/position.

### Array & Image Manipulation
* `gen_freqs(start_freq, end_freq, num_steps)` in qdm_gen.py - Generate linearly spaced frequency array
* `bin_2d(img, bin_size_x, bin_size_y)` in qdm_gen.py - Software binning of 2D image (beyond hardware 4x4 limit)
* `bin_qdm_cube(cube, bin_x, bin_y)` in qdm_gen.py - Spatially bin a 3D ODMR cube (Freq, Y, X)
* `get_cube_subset(cube, x_range, y_range)` in qdm_gen.py - Extract spatial ROI from 3D cube
* `save_qdm_figure(fig, base_filename, subfolder, ...)` in qdm_gen.py - Save matplotlib figure to project data directory with optional timestamp

### Simulation Mode
* `generate_synthetic_qdm_cube(freqlist, field_map, base_counts)` in qdm_gen.py - Generate synthetic ODMR data cube with realistic NV physics (D=2.87 GHz, hyperfine splitting, Poisson noise)
* `create_field_map(shape, pattern, bias_tesla)` in qdm_gen.py - Create spatial B-field distribution for simulation. Patterns: 'none', 'loop', 'square'

### NI-DAQ Data Acquisition (qdm_nidaq.py)
* `read_analog_voltage(device, channel, n_samples, sample_rate, ...)` - Read analog voltage from single DAQ channel. Returns numpy array.
* `acquire_continuous(duration_seconds, device, channel, sample_rate, conversion, live_plot, ...)` - Continuous acquisition with optional live plotting and voltage-to-physical-unit conversion. Returns dict with 'time', 'voltage', 'converted'.
* `analyze_and_plot_stability(data, title, ylabel, ...)` - Create summary figure with time series and FFT from acquired data.
* `save_daq_data(data, base_filename, save_dir, subfolder, ...)` - Save acquisition data to CSV and/or PNG.
* `monitor_laser_power(duration_seconds, sample_rate, live_plot, save_data, subfolder)` - High-level convenience function for laser power monitoring. Combines acquisition, analysis, and saving. Default conversion calibrated for current PD setup (slope=0.9527, intercept=0.0036).

## Key data structures

### `peak_params` (list of dicts, from `fit_global_odmr`)
Each entry describes one fitted Lorentzian peak:
* `'index'`: int - Peak number (1, 2, ...)
* `'center'`: float - Center frequency (GHz)
* `'width_fwhm'`: float - Full width at half maximum (GHz)
* `'contrast'`: float - Unitless ratio (dip amplitude / baseline), e.g. 0.03 for 3% contrast
* `'max_slope'`: float - Maximum slope in **normalized** GHz^-1. Computed as `(3√3/8) × (contrast / HWHM)`. This is the derivative of the normalized ODMR curve `y/baseline`, so it matches the units of the measured contrast ratio `PL_sig/PL_ref`.
* `'inflection_pts'`: tuple of (f_low, f_high) - Frequencies where slope is maximum (GHz). `f_low = f_center - HWHM/√3`, `f_high = f_center + HWHM/√3`.
* `'inflection_contrasts'`: tuple of (contrast_at_low, contrast_at_high) - Expected baseline contrast (PL_sig/PL_ref) at each inflection point, evaluated from the full fitted model and normalized by baseline. These are < 1.0 because inflection points sit partway down the Lorentzian dip. Used for accurate PL-to-frequency conversion instead of the approximation of 1.0.

### PL-to-frequency conversion math
The core formula used in `measure_multi_point` and `analyze_inflection_point_magnetometry`:
```
Δf = (C_measured - C_baseline) / slope
```
Where:
* `C_measured = PL_signal / PL_reference` — the measured contrast ratio
* `C_baseline` — the expected contrast at the inflection point when the magnetic field hasn't changed (from `inflection_contrasts`). For a single Lorentzian with contrast c, `C_baseline ≈ 1 - 3c/4` at the inflection points.
* `slope` — the signed ODMR slope at the inflection point (GHz^-1). **Left inflection = negative slope** (PL decreases as freq increases), **right inflection = positive slope** (PL increases as freq increases).
* `Δf` — frequency shift in GHz, then converted to magnetic field via `B = Δf / γ_e` where `γ_e = 0.0028024 GHz/Gauss`.

### Slope sign convention
* **Left inflection point** (lower frequency side of dip): slope is **negative** — as frequency increases, PL decreases (going down into the dip)
* **Right inflection point** (higher frequency side of dip): slope is **positive** — as frequency increases, PL increases (coming out of the dip)
* `peak_params['max_slope']` stores the **unsigned magnitude** (always positive). The sign must be applied when using it:
  - `identify_multi_transition_inflection_points` applies signs: `-max_slope` for left, `+max_slope` for right
  - `analyze_inflection_point_magnetometry` auto-detects the side by comparing `inflection_freq` to the peak's inflection points

## Common tasks
Indicated by headers in Jupyter notebook.
* ODMR freq sweep: main function used to scan MW frequency to identify NV resonances, check contrast, optimize experimental settings
* ODMR data analysis: Plot data vs. frequency for entire camera view (basically treating the camera like a single-point photodiode). Linked to the above. Plot the contrast, fit Lorentzians to identify NV hyperfine peak(s), measure PL slope at inflection points.
* Process widefield ODMR data: Perform pixel-by-pixel fitting of the ODMR peaks, extract the central frequency and make a magnetic field map.
* Single inflection point magnetometry: Sit at one inflection point and measure PL over time. Uses `run_stability_measurement` → `analyze_inflection_point_magnetometry`. Good for quick checks and sensitivity measurements.
* 4-point differential magnetometry (global mean): Uses inflection points from both NV transitions to cancel strain and temperature shifts. Workflow: `identify_multi_transition_inflection_points` → `format_multi_point_frequencies` → `run_multi_point_stability_measurement` → `analyze_multi_point_magnetometry`. See notebook cells 31-38. **Default approach** for homogeneous fields.
* **NEW:** 4-point differential magnetometry (spatially-binned): Same as above but with automatic spatial gradient compensation. Workflow: `identify_multi_transition_inflection_points_binned` → `format_multi_point_frequencies_binned` → `run_multi_point_stability_measurement_binned` → `analyze_multi_point_magnetometry`. See `BINNED_MAGNETOMETRY_EXAMPLES.md` for complete examples. Use when bias field gradients are significant.
* Measure noise at a single frequency: sit at a single MW frequency (usually the inflection point identified above) and measure the magnetic field for a set period. Used to measure the stability and sensitivity of the magnetometer. Also has scripts to compute the Allan variance.
* Laser power monitoring: Monitor Dev3/AI0 voltage to measure laser stability. (Laser is old, so often has significant fluctuations without PID control.)

## Notebook structure (Camera ODMR-new.ipynb)
Key cell groups (by markdown headers / cell IDs):
* Cells 0-3: Imports and module reloading
* Cells 4-8: Configuration (device settings, frequency settings, `exp_settings` dict)
* Cells 9-10: ODMR frequency sweep (`run_odmr_sweep`)
* Cells 12-16: Save/load ODMR data
* Cells 17-19: Widefield ODMR processing (pixel-by-pixel fitting → field maps)
* Cells 20-21: Reprocess saved fit results with different denoising
* Cells 22-23: Custom plotting
* Cells 24-26: **Single inflection point magnetometry** (`run_stability_measurement` → `analyze_inflection_point_magnetometry`)
* Cells 27-30: Single-point sensitivity and Allan variance
* Cells 31-38: **Multi-point differential magnetometry** (4-point scheme)
  - Cell 33: Identify inflection points from both transitions
  - Cell 34: Multi-point measurement and analysis
  - Cell 36: Module reload convenience cell
  - Cell 38: Reanalyze field map with different denoising

## GUI directory structure (/GUI/)
Five PySide6 + pyqtgraph apps for instrument control.

### App entry points (GUI root)
* `pid_control_app.py` — SRS SIM960 PID controller GUI
* `laser_power_app.py` — NI-DAQ laser power monitor GUI
* `camera_app.py` — Basler camera streaming GUI
* `launch_all_apps.py` — Launches the instrument apps + ODMR + LFM in one QApplication with shared state
* `simple_app.py` — Minimal example/sandbox app

### ODMR magnetometry GUI (odmr_app/)
The primary experiment GUI lives in `GUI/odmr_app/`. Run with `python GUI/odmr_app/odmr_app.py` or via launchers. It provides the full CW ODMR → field map workflow in 5 tabs: ODMR Sweep, Magnetometry, Analysis, Sensitivity, Settings. See `GUI/odmr_app/ODMR_APP_README.md` for complete documentation.

Key structure:
* `odmr_app/state/odmr_state.py` — `ODMRAppState`: all signals, properties, config I/O
* `odmr_app/workers/` — `SG384Worker`, `ODMRSweepWorker`, `MagnetometryWorker`, `AnalysisWorker`
* `odmr_app/tabs/` — `SweepTabHandler`, `MagnetometryTabHandler`, `AnalysisTabHandler`, `SensitivityTabHandler`, `SettingsTabHandler`
* `odmr_app/widgets/` — `InflectionTableWidget`, `FieldMapDisplayWidget` (3-panel RdBu_r with colorbars)
* `odmr_app/ui/` — Qt Designer `.ui` source files + generated `ui_*.py` files
* `odmr_app/config/` — `odmr_app_config.json` (auto-saved) + `presets/` folder
* `odmr_app/tests/` — 50 pytest tests (run with `python -m pytest GUI/odmr_app/tests/`)

### LFM microscopy GUI (lfm_app/)
The light field microscopy GUI lives in `GUI/lfm_app/`. Run with `python GUI/lfm_app/lfm_app.py` or via launchers. It provides the full LFM workflow in 5 tabs: Camera, Calibration, Reconstruction, Volume Viewer, Settings. See `GUI/lfm_app/LFM_APP_README.md` for complete documentation.

Key structure:
* `lfm_app/state/lfm_state.py` — `LFMAppState`: all signals, properties, config I/O, calibration stage tracking
* `lfm_app/workers/` — `CalibrationWorker` (pyolaf geometry + PSF pipeline), `ReconstructionWorker` (iterative deconvolution)
* `lfm_app/tabs/` — `CalibrationTabHandler`, `ReconstructionTabHandler`, `VolumeViewerTabHandler`, `SettingsTabHandler`
* `lfm_app/widgets/` — `VolumeSlicerWidget` (depth-slice browser with colorbar), `LensletOverlayWidget` (white image + detected centers)
* `lfm_app/config/` — `lfm_app_config.json` (auto-saved) + `lfm_camera_config.json`

Dependencies:
* `pyolaf-main/` — LFM reconstruction library (install with `pip install -e pyolaf-main/`)
* Camera tab is embedded from `GUI/camera_app.py` using sys.modules isolation (same pattern as odmr_app)
* Optional: CuPy for GPU-accelerated reconstruction

Sample data:
* `pyolaf-main/examples/fly-muscles-GFP/` — config.yaml, calib.tif, example_fly.tif

### Instrument helper apps (GUI root + subfolders)
* `state/` — Qt state objects (QObject + Signal). No internal GUI imports.
  - `experiment_state.py` — `ExperimentState`: shared state for laser power + PID apps
  - `camera_state.py` — `CameraState`: shared state for camera app
  - `pid_state.py` — `PIDState`: deprecated original PID state (kept for reference)
* `workers/` — QThread worker classes for non-blocking hardware I/O
  - `daq_worker.py` — `DAQWorker`: continuous NI-DAQ acquisition
  - `pid_worker.py` — `PIDWorker`: SIM900/SIM960 PID hardware comms
  - `camera_worker.py` — `CameraWorker`: Basler camera frame producer
  - `camera_consumer.py` — `CameraConsumer`: frame averaging and saving
* `widgets/` — Reusable UI components
  - `real_time_graph.py` — `RealTimeGraph`: drop-in rolling-window plot widget (connects to `state.data_point_recorded` signal)
* `config/` — JSON config files (auto-saved by apps on settings change)
  - `laser_power_config.json` — DAQ/conversion settings for laser power app
  - `pid_control_config.json` — PID app settings (created on first save)
  - `basler_camera_config.json` — Camera app settings (created on first save)
* `docs/` — Documentation and reference files
  - `REFACTOR_SUMMARY.md`, `CAMERA_APP_README.md`, `LAUNCHER_README.txt`, `SIM960m.pdf`, `ideal_default_size.png`

### Import conventions
* Apps import from subfolders using package notation: `from state.experiment_state import ExperimentState`, `from workers.daq_worker import DAQWorker`, `from widgets.real_time_graph import RealTimeGraph`
* Workers use `sys.path.insert(0, str(Path(__file__).parent.parent.parent))` to reach the `ODMR code v2/` root for qdm module imports
* Apps use `sys.path.insert(0, str(Path(__file__).parent.parent))` to reach `ODMR code v2/` root

### Architecture pattern
Each app follows: `AppMainWindow` ← `State` (QObject/Signal) ← `Worker` (QThread). The state object is the single source of truth; workers emit signals to update state; UI subscribes to state signals.

## Other notes
* Ignore /Labview and /legacy directories, these contain old outdated code
* Ignore other Jupyter notebooks such as Camera ODMR extra.ipynb, Scratch.ipynb
* simulation_mode: used for testing. Set to True if adding or modifying code on other computers or if a piece of hardware is temporarily not connected.
* When modifying notebook cells, preserve the user's custom frequency values and configuration — don't overwrite them with defaults.

## Raw data
* Experimental code is currently living in G:\Shared drives\PHYS - Walsworth Group\Experiment folders\Bioimaging\ODMR code\ODMR code v2 (may also appear as X: drive depending on the machine)
* Experimental data (including short-term calibration data) stored in E:\MTB project\CW ODMR

## When working on this project
* Ask permission before accessing or modifying files in other directories (i.e. outside G:\Shared drives\PHYS - Walsworth Group\Experiment folders\Bioimaging\ODMR code\ODMR code v2)
* **IMPORTANT - Version Control**: Before making substantial edits to any .py or .ipynb file, FIRST copy the current version to the `/legacy/` subfolder with a versioned filename: `<filename>_YYYY-MM-DD_v#.<ext>` (e.g., `qdm_gen_2026-02-04_v1.py`). Increment the version number if multiple backups are made on the same day.
* When I ask you to "compactify" or "modularize" something in the Jupyter notebook, it means to refactor the code - i.e. encapsulate lengthy scripts into new sub-functions stored in .py files (e.g. in qdm_gen.py) which are then called in a notebook cell. This helps to reduce unnecessary clutter in the top-level notebook. 
* You can encode default options for a function, but never hardcode real-world important experimental hardware settings (e.g. analog input channel numbers, camera identifiers, camera acquisition settings, etc.). All experimental settings (except for those which are always set to the hardware default and never changed programmatically) must be placed in a central file/object that can be easily tracked and modified.
* Use numpy & scipy for numerical operations
* Follow PEP 8 style guide
* Add docstrings to all functions
