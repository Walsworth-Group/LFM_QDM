"""
End-to-end hardware test: ODMR sweep → magnetometry run.

Runs without the GUI.  Connects to real hardware, performs a short sweep to
find inflection points, then runs 10 magnetometry samples and reports results.

Usage:
    cd GUI/odmr_app
    python tests/run_sweep_and_mag.py

Expected output:
    - Sweep completes, finds 8 inflection points
    - Magnetometry acquires 10 samples
    - Mean field and noise printed per pixel
"""

import sys
import time
from pathlib import Path

# Reach project root
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
app = QCoreApplication.instance() or QCoreApplication(sys.argv)

import numpy as np

from state.odmr_state import ODMRAppState, CameraMode
from workers.odmr_sweep_worker import ODMRSweepWorker
from workers.magnetometry_worker import MagnetometryWorker

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
INFO = "\033[94mINFO\033[0m"

def info(msg):  print(f"  [{INFO}] {msg}")
def ok(msg):    print(f"  [{PASS}] {msg}")
def fail(msg):  print(f"  [{FAIL}] {msg}")


def wait_for_worker(worker, timeout_ms=120_000):
    """Block until worker thread finishes, pumping the Qt event loop."""
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    worker.finished.connect(loop.quit)
    timer.start(timeout_ms)
    loop.exec()
    worker.wait(5000)       # final drain to flush queued signals
    app.processEvents()


# ---------------------------------------------------------------------------
# State — use settings from saved config / known hardware values
# ---------------------------------------------------------------------------
state = ODMRAppState()

# RF: SG384 on GPIB
state.rf_address        = "GPIB0::28::INSTR"
state.rf_amplitude_dbm  = -10.0

# Camera
state.odmr_camera_serial    = "25061217"
state.sweep_exposure_time_us = 100
state.sweep_n_frames_per_point = 5
state.sweep_hw_bin_x = 4
state.sweep_hw_bin_y = 4
state.mag_exposure_time_us   = 100
state.mag_n_frames_per_point = 5
state.mag_hw_bin_x = 4
state.mag_hw_bin_y = 4

# Sweep frequencies (from saved config — previously calibrated)
state.sweep_freq1_start_ghz = 2.516
state.sweep_freq1_end_ghz   = 2.528
state.sweep_freq1_steps     = 21
state.sweep_freq2_start_ghz = 3.210
state.sweep_freq2_end_ghz   = 3.220
state.sweep_freq2_steps     = 21
state.sweep_ref_freq_ghz    = 1.0
state.sweep_num_sweeps      = 1
state.sweep_n_lorentz       = 2

# Magnetometry (short run for testing)
state.mag_num_samples         = 10
state.mag_selected_indices    = [1, 4, 0, 5, 8, 0]
state.mag_selected_parities   = [1, 1, 0, -1, -1, 0]
state.perf_live_avg_update_interval_samples = 5
state.perf_mw_settling_time_s = 0.005

results = {}

# ---------------------------------------------------------------------------
# Step 1: Connect to SG384
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("Step 1: Connect to SG384")
print("=" * 60)

try:
    from qdm_srs import SG384Controller
    sg384 = SG384Controller(
        address=state.rf_address,
        verbose=False,
        verify_on_set=False,
    )
    sg384.open_connection()
    sg384.set_amplitude(state.rf_amplitude_dbm)
    state.sg384_controller = sg384
    ok(f"Connected to SG384 at {state.rf_address}")
    ok(f"Amplitude set to {state.rf_amplitude_dbm} dBm")
except Exception as exc:
    fail(f"SG384 connection failed: {exc}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Step 2: ODMR Sweep
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("Step 2: ODMR Sweep")
print("=" * 60)
info(f"Transition 1: {state.sweep_freq1_start_ghz:.4f}–{state.sweep_freq1_end_ghz:.4f} GHz "
     f"({state.sweep_freq1_steps} steps)")
info(f"Transition 2: {state.sweep_freq2_start_ghz:.4f}–{state.sweep_freq2_end_ghz:.4f} GHz "
     f"({state.sweep_freq2_steps} steps)")
info(f"Camera: serial={state.odmr_camera_serial}, exposure={state.sweep_exposure_time_us} µs, "
     f"frames={state.sweep_n_frames_per_point}, HW bin={state.sweep_hw_bin_x}×{state.sweep_hw_bin_y}")

sweep_completed = []
sweep_failed    = []

sweep_worker = ODMRSweepWorker(state, simulation_mode=False)
sweep_worker.sweep_progress.connect(
    lambda c, t: print(f"\r    Step {c}/{t}", end="", flush=True))
sweep_worker.sweep_completed.connect(lambda d: sweep_completed.append(d))
sweep_worker.sweep_failed.connect(lambda e: sweep_failed.append(e))

t0 = time.monotonic()
sweep_worker.start()
wait_for_worker(sweep_worker, timeout_ms=300_000)
elapsed = time.monotonic() - t0
print()  # newline after progress

if sweep_failed:
    fail(f"Sweep failed: {sweep_failed[0]}")
    sg384.close_connection()
    sys.exit(1)

if not sweep_completed:
    fail("Sweep completed but no result received")
    sg384.close_connection()
    sys.exit(1)

result = sweep_completed[0]
state.sweep_inflection_result = result
ok(f"Sweep completed in {elapsed:.1f} s")

inf_pts = result.get("inflection_points", [])
inf_slopes = result.get("inflection_slopes", [])
inf_contrasts = result.get("inflection_contrasts", [])

if len(inf_pts) == 8:
    ok(f"Found 8 inflection points")
else:
    fail(f"Expected 8 inflection points, got {len(inf_pts)}")

print("\n  Inflection points:")
for i, (f, s, c) in enumerate(zip(inf_pts, inf_slopes, inf_contrasts)):
    sign = "L" if s < 0 else "R"
    print(f"    [{i+1}] {f:.6f} GHz  slope={s:+.2f} GHz^-1  contrast={c:.4f}  ({sign})")

results["sweep"] = result

# ---------------------------------------------------------------------------
# Step 3: Magnetometry
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("Step 3: Magnetometry (10 samples)")
print("=" * 60)
info(f"Indices: {state.mag_selected_indices}")
info(f"Parities: {state.mag_selected_parities}")
info(f"Camera: exposure={state.mag_exposure_time_us} µs, "
     f"frames={state.mag_n_frames_per_point}, HW bin={state.mag_hw_bin_x}×{state.mag_hw_bin_y}")

mag_completed = []
mag_failed    = []

mag_worker = MagnetometryWorker(state, simulation_mode=False)
mag_worker.mag_progress.connect(
    lambda c, t: print(f"\r    Sample {c}/{t}", end="", flush=True))
mag_worker.mag_completed.connect(lambda d: mag_completed.append(d))
mag_worker.mag_failed.connect(lambda e: mag_failed.append(e))

t0 = time.monotonic()
mag_worker.start()
wait_for_worker(mag_worker, timeout_ms=300_000)
elapsed = time.monotonic() - t0
print()  # newline after progress

if mag_failed:
    fail(f"Magnetometry failed: {mag_failed[0]}")
    sg384.close_connection()
    sys.exit(1)

if not mag_completed:
    fail("Magnetometry completed but no result received")
    sg384.close_connection()
    sys.exit(1)

mag_result = mag_completed[0]
ok(f"Magnetometry completed in {elapsed:.1f} s")

cube = mag_result.get("stability_cube")
n_acquired = mag_result.get("num_samples_acquired", 0)
ok(f"Acquired {n_acquired} samples, stability_cube shape: {cube.shape}")

GAMMA_E = 0.0028024   # GHz/Gauss
field_ghz = cube.mean(axis=0)          # mean over samples (GHz)
noise_ghz = cube.std(axis=0)           # std over samples (GHz)
field_gauss = field_ghz / GAMMA_E
noise_gauss = noise_ghz / GAMMA_E

print(f"\n  Field map stats (in Gauss):")
print(f"    Mean field  : {field_gauss.mean():.4f} G")
print(f"    Std of mean : {field_gauss.std():.4f} G")
print(f"    Mean noise  : {noise_gauss.mean():.4f} G/sample")
print(f"    Frame shape : {cube.shape[1:]}")

results["magnetometry"] = mag_result

# ---------------------------------------------------------------------------
# Step 4: Disconnect
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("Step 4: Disconnect")
print("=" * 60)
try:
    sg384.close_connection()
    ok("SG384 disconnected")
except Exception as exc:
    fail(f"SG384 disconnect: {exc}")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
sweep_ok = len(sweep_completed) == 1 and len(inf_pts) == 8
mag_ok   = len(mag_completed) == 1 and n_acquired == state.mag_num_samples
if sweep_ok and mag_ok:
    print(f"\033[92mAll steps passed. Sweep + magnetometry run completed successfully.\033[0m")
    sys.exit(0)
else:
    if not sweep_ok:
        fail("Sweep did not complete cleanly")
    if not mag_ok:
        fail(f"Magnetometry: got {n_acquired}/{state.mag_num_samples} samples")
    sys.exit(1)
