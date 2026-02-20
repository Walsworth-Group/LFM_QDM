# Bug Report: `measure_multi_point_binned` — Per-Bin Frequency Stepping Not Implemented
**Date:** 2026-02-19
**File affected:** `qdm_gen.py`
**Function affected:** `measure_multi_point_binned()` (line ~1765)
**Severity:** The binned magnetometry pipeline (`identify_multi_transition_inflection_points_binned` → `format_multi_point_frequencies_binned` → `run_multi_point_stability_measurement_binned` → `analyze_multi_point_magnetometry`) runs without error but does **not** provide any improvement over the global-mean approach for suppressing the large-scale bias field gradient.

---

## Background

This bug was identified during a conversation on 2026-02-19 while investigating why spatially-binned multi-point magnetometry produced the same large-scale magnetic field gradient as the global-mean approach, regardless of bin size (including 100×100 pixel bins).

The experiment uses a widefield NV-diamond quantum diamond microscope (QDM) to image magnetostatic bacteria. A permanent magnet applies a ~few-Gauss bias field to the diamond, but the field is inhomogeneous across the ~480×300 pixel FOV, producing a gradient of approximately **200 mG** across the full field of view. At γₑ = 2.8024 MHz/G, this corresponds to a **~0.56 MHz** frequency shift across the FOV.

The Lorentzian linewidth from a typical ODMR sweep is **FWHM ≈ 1.44 MHz** (HWHM ≈ 0.72 MHz), placing the inflection points at ±HWHM/√3 ≈ **±0.42 MHz** from each peak center. The gradient therefore pushes pixels near the FOV edges **past the inflection point and toward the peak center**, into the nonlinear regime of the Lorentzian.

The purpose of `identify_multi_transition_inflection_points_binned` was to address this: by fitting the ODMR spectrum in each spatial bin, the local resonance frequency (and hence the local inflection point frequency) can be found for each region of the FOV. Then, during the multi-point magnetometry measurement, each bin should be measured at its own local inflection frequency so that all pixels are correctly on-resonance. The baseline contrast `C_baseline` from the ODMR fit encodes what PL/PL_ref ratio is expected at each bin's local inflection point when no magnetic signal is present.

---

## The Bug

In `measure_multi_point_binned()`, the MW generator is set using the **median** of the spatially-varying frequency array, not the per-bin local frequency:

```python
# CURRENT (BUGGY) CODE — lines ~1844-1852 in qdm_gen.py
measurements = []
for i in range(n_points):
    # Use median frequency as representative value for MW generator
    freq_scalar = np.nanmedian(freq_array_full[i])   # <-- BUG IS HERE

    sg384.set_frequency(freq_scalar, 'GHz')
    time.sleep(settling_time)
    camera.flush_buffer()
    frame = camera.grab_frames(n_frames=n_frames, quiet=True)
    measurements.append(frame.astype(np.float32))
```

Subsequently, the per-pixel PL-to-frequency conversion is applied correctly:

```python
# Frequency shift: Δf = (C_measured - C_baseline) / slope
contrast = np.divide(pl_sig, pl_ref, where=(pl_ref != 0))
contrast_deviation = contrast - baseline_map
freq_shift = np.divide(contrast_deviation, slope_map, where=(slope_map != 0))
```

### Why this is wrong

The formula `Δf = (C_measured − C_baseline) / slope` is physically correct **only if the MW was set to the bin's local inflection frequency** when acquiring `C_measured`. If the MW is set to the median frequency instead:

- A bin whose local inflection point is at frequency `f_local` but which is measured at the median `f_median` records a `C_measured` that corresponds to a point on the Lorentzian that is `δf = f_local − f_median` away from its local inflection point.
- `C_baseline` was computed from the ODMR fit evaluated at `f_local` — i.e., at the correct local inflection point.
- Therefore `C_measured − C_baseline ≠ 0` even with **zero magnetic signal from bacteria**, because the measured PL and the baseline PL were acquired at different points on the Lorentzian.
- The residual `C_measured − C_baseline` is proportional to `δf`, which is in turn proportional to the local bias field offset from the median — i.e., it reproduces the gradient.

In short: **`C_baseline` is the correct reference only if the hardware frequency matches the local inflection point. Using the median frequency makes `C_baseline` irrelevant, and the gradient is not removed.**

### Why this affects all bin sizes equally

The median frequency is computed across **all bins**, so it is always approximately the global mean inflection frequency regardless of bin size. Changing the bin size changes the granularity at which `C_baseline` is computed, but since the hardware never uses those per-bin frequencies, the output is nearly identical to the global-mean approach.

---

## Quantitative Assessment of Nonlinearity

Using numbers from a typical experiment (2026-02-19):

| Parameter | Value |
|---|---|
| FWHM | ~1.44 MHz |
| HWHM | ~0.72 MHz |
| Inflection point offset (HWHM/√3) | ~0.42 MHz |
| Linear dynamic range (±inflection offset) | ±0.42 MHz ≈ ±0.15 G |
| Gradient across FOV | ~200 mG = 0.56 MHz |
| Gradient as fraction of linear range | ~133% — **exceeds linear range** |

Pixels at the FOV edges are pushed past the peak center into the opposite side of the Lorentzian, where the local slope has the wrong sign. The linear approximation fails significantly for the outer ~30-40% of the FOV.

---

## The Fix

The fix requires replacing the single-frequency measurement loop with a **per-bin frequency stepping loop**. For each measurement point (signal or reference), the MW generator must be stepped through each bin's local inflection frequency, and only that bin's pixels extracted from the grabbed frame.

### Proposed new implementation for the measurement loop in `measure_multi_point_binned()`

```python
# PROPOSED FIX
# Replace the current single-loop measurement block with per-bin stepping.
# freq_array shape: (n_points, ny_bins, nx_bins)
# slope_array, baseline_array: same shape
# All are already upsampled to (n_points, ny_full, nx_full) before this block.

n_points = len(parity_list)
ny_bins, nx_bins = freq_array.shape[1], freq_array.shape[2]

# Pre-compute bin pixel masks at full resolution
# bin_mask[iy, ix] is a boolean array of shape (ny_full, nx_full)
# marking which pixels belong to bin (iy, ix)
bin_h = ny_full // ny_bins   # height of each bin in pixels
bin_w = nx_full // nx_bins   # width of each bin in pixels

# measurements_full[i] will hold the assembled full-res PL image
# for measurement point i, where each bin was measured at its local frequency
measurements_full = [np.zeros((ny_full, nx_full), dtype=np.float32)
                     for _ in range(n_points)]

for i in range(n_points):
    for iy in range(ny_bins):
        for ix in range(nx_bins):
            # Set MW to this bin's local inflection frequency
            freq_scalar = freq_array[i, iy, ix]   # already at bin resolution
            sg384.set_frequency(freq_scalar, 'GHz')
            time.sleep(settling_time)
            camera.flush_buffer()
            frame = camera.grab_frames(n_frames=n_frames, quiet=True).astype(np.float32)

            # Extract this bin's pixel region from the grabbed frame
            y0 = iy * bin_h
            y1 = y0 + bin_h if iy < ny_bins - 1 else ny_full   # handle remainder
            x0 = ix * bin_w
            x1 = x0 + bin_w if ix < nx_bins - 1 else nx_full

            measurements_full[i][y0:y1, x0:x1] = frame[y0:y1, x0:x1]

# The rest of the function (PL-to-frequency conversion) remains unchanged,
# using measurements_full[i] in place of measurements[i].
```

### Important notes on the fix

1. **Time cost scales as N_bins × N_points × N_frames per sample.** For 100×100 pixel bins on a 480×300 FOV, N_bins ≈ 15, so measurements take ~15× longer. For 10×10 bins (N_bins ≈ 1440), the approach is completely impractical.

2. **The `freq_array` passed into `measure_multi_point_binned` should be at bin resolution** for this loop, not upsampled. The upsampling (currently done at the top of the function for the conversion step) is still needed for the per-pixel `Δf = ΔC/slope` conversion, but the hardware frequency setting should use the bin-resolution values directly.

3. **The reference measurements** (parity == 0, set to `ref_freq`) don't need per-bin stepping since they are measured at a single off-resonance frequency for all bins — that loop is unchanged.

4. **Bin boundary handling:** The simple rectangular slicing above assumes integer-divisible dimensions. The `bin_qdm_cube` function already handles remainders; the pixel extraction should match the same convention.

5. **`run_multi_point_stability_measurement_binned`** calls `measure_multi_point_binned` and does not need changes beyond passing `freq_array` at bin resolution rather than upsampled resolution for the hardware stepping part. The function signature and return values remain the same.

---

## Current Practical Workaround

Despite this bug, the existing pipeline produces usable results because:

1. The 4-point differential scheme (measuring inflection points from both NV transitions) cancels **first-order** common-mode effects (strain, temperature).
2. Post-processing with `analyze_multi_point_magnetometry` applies a Gaussian spatial filter to the raw field map and subtracts it, removing the smooth large-scale gradient in post-processing.
3. Bacterial magnetic dipole fields are highly localized (~few pixels) compared to the smooth gradient length scale (~full FOV), so the Gaussian subtraction cleanly separates signal from background.

The global-mean approach with Gaussian subtraction is therefore adequate for imaging magnetostatic bacteria and is currently the recommended workflow. The per-bin fix described above is implemented for completeness and future use, e.g. if a sample produces features at intermediate spatial scales where the Gaussian subtraction would also remove signal.

---

## Files to Modify If Implementing the Fix

- **`qdm_gen.py`**: `measure_multi_point_binned()` — replace measurement loop as described above. Also update docstring to reflect that `freq_array` should be passed at bin resolution (not upsampled) for the hardware stepping, while upsampling is still applied internally for the conversion step.
- **No changes needed** to: `identify_multi_transition_inflection_points_binned`, `format_multi_point_frequencies_binned`, `run_multi_point_stability_measurement_binned`, `analyze_multi_point_magnetometry`.

---

## How to Resume This Work

This bug was identified in a Claude Code session on 2026-02-19. To resume:
1. Open the project in Claude Code from `G:\Shared drives\PHYS - Walsworth Group\Experiment folders\Bioimaging\ODMR code\ODMR code v2`
2. Reference this file (`BINNED_MAGNETOMETRY_BUG_REPORT_2026-02-19.md`) and ask Claude to implement the fix to `measure_multi_point_binned()` in `qdm_gen.py` following the proposed code above.
3. Remember to first back up `qdm_gen.py` to `/legacy/` as `qdm_gen_YYYY-MM-DD_v#.py` before making changes (per project convention in `CLAUDE.md`).
