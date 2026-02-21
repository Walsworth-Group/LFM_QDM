"""
Hardware integration test for Basler camera.

Run manually (requires camera connected via USB):

    cd GUI/odmr_app
    python tests/test_hardware_camera.py

Tests verified:
  1. Camera opens and connects
  2. Hardware binning is applied (BinningHorizontal / BinningVertical)
  3. Grabbed frame has the expected shape after binning
  4. Frame contains non-zero, finite pixel values (laser is on)
  5. Camera closes cleanly

Expected frame shape with default 4×4 binning:
    ny = 1200 / 4 = 300 rows
    nx = 1920 / 4 = 480 columns
    numpy shape: (300, 480)

Usage:
    python tests/test_hardware_camera.py              # 4×4 binning, serial 25061217 (defaults)
    python tests/test_hardware_camera.py --bin 2      # 2×2 binning
    python tests/test_hardware_camera.py --bin 1      # no binning (full res: 1200×1920)
    python tests/test_hardware_camera.py --serial 23049069  # other camera
    python tests/test_hardware_camera.py --exposure 5000    # 5 ms exposure
"""

import sys
import argparse
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def run_tests(bin_factor: int, serial: str, exposure_us: int):
    from qdm_basler import basler

    NATIVE_NX = 1920
    NATIVE_NY = 1200
    expected_nx = NATIVE_NX // bin_factor
    expected_ny = NATIVE_NY // bin_factor

    results = []
    camera_instance = None

    def check(label, passed, detail=""):
        tag = PASS if passed else FAIL
        line = f"  [{tag}] {label}"
        if detail:
            line += f"  ({detail})"
        print(line)
        results.append(passed)
        return passed

    print(f"\nCamera hardware test  (bin={bin_factor}, serial='{serial or 'any'}', "
          f"exposure={exposure_us} µs)")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. Open camera
    # ------------------------------------------------------------------
    print("\n[1] Open camera")
    try:
        camera_instance = basler.connect_and_open(
            choice=serial or "",
            exposure_time_us=exposure_us,
            verbose=True,
        )
        check("connect_and_open returned non-None", camera_instance is not None)
    except Exception as exc:
        check("connect_and_open", False, str(exc))
        traceback.print_exc()
        return results

    # ------------------------------------------------------------------
    # 2. Apply hardware binning
    # ------------------------------------------------------------------
    print(f"\n[2] Apply hardware binning ({bin_factor}×{bin_factor})")
    try:
        cam = camera_instance._camera
        cam.BinningHorizontal.SetValue(bin_factor)
        cam.BinningVertical.SetValue(bin_factor)
        cam.BinningHorizontalMode.SetValue("Average")
        cam.BinningVerticalMode.SetValue("Average")
        check("BinningHorizontal set", True, f"value={bin_factor}")
        check("BinningVertical set",   True, f"value={bin_factor}")

        actual_bin_x = cam.BinningHorizontal.GetValue()
        actual_bin_y = cam.BinningVertical.GetValue()
        check("BinningHorizontal readback", actual_bin_x == bin_factor,
              f"got {actual_bin_x}, expected {bin_factor}")
        check("BinningVertical readback",   actual_bin_y == bin_factor,
              f"got {actual_bin_y}, expected {bin_factor}")
    except Exception as exc:
        check("Apply binning", False, str(exc))
        traceback.print_exc()

    # ------------------------------------------------------------------
    # 3. Grab a single frame and check shape
    # ------------------------------------------------------------------
    print("\n[3] Grab frame and verify shape")
    frame = None
    try:
        frame = camera_instance.grab_frames(n_frames=1, quiet=True)
        check("grab_frames returned array", frame is not None)
        check(f"shape == ({expected_ny}, {expected_nx})",
              frame.shape == (expected_ny, expected_nx),
              f"got {frame.shape}")
    except Exception as exc:
        check("grab_frames", False, str(exc))
        traceback.print_exc()

    # ------------------------------------------------------------------
    # 4. Basic pixel sanity (requires laser on)
    # ------------------------------------------------------------------
    print("\n[4] Frame pixel sanity (requires laser on and aimed at camera)")
    if frame is not None:
        import numpy as np
        mean_val = float(frame.mean())
        max_val  = int(frame.max())
        min_val  = int(frame.min())
        all_finite = bool(np.isfinite(frame).all())
        nonzero    = mean_val > 0

        print(f"       mean={mean_val:.1f}  min={min_val}  max={max_val}")
        check("All pixels finite", all_finite)
        check("Mean > 0 (non-black frame)", nonzero,
              "if this fails: laser may be off or blocked")
    else:
        check("Frame pixel sanity", False, "no frame to check")

    # ------------------------------------------------------------------
    # 5. Grab multiple frames (averaging)
    # ------------------------------------------------------------------
    print("\n[5] Grab 3 averaged frames")
    try:
        avg_frame = camera_instance.grab_frames(n_frames=3, quiet=True)
        check("grab_frames(n_frames=3) shape",
              avg_frame.shape == (expected_ny, expected_nx),
              f"got {avg_frame.shape}")
    except Exception as exc:
        check("grab_frames(n_frames=3)", False, str(exc))

    # ------------------------------------------------------------------
    # 6. Close camera
    # ------------------------------------------------------------------
    print("\n[6] Close camera")
    try:
        camera_instance.close()
        camera_instance = None
        check("close() completed", True)
    except Exception as exc:
        check("close()", False, str(exc))
    finally:
        if camera_instance is not None:
            try:
                camera_instance.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    n_pass = sum(results)
    n_total = len(results)
    print("\n" + "=" * 60)
    print(f"Result: {n_pass}/{n_total} checks passed")
    if n_pass == n_total:
        print(f"\033[92mAll checks passed.\033[0m")
    else:
        print(f"\033[91m{n_total - n_pass} check(s) FAILED — see output above.\033[0m")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Basler camera hardware test")
    parser.add_argument("--bin", type=int, default=4,
                        help="Hardware binning factor (1-4, default 4)")
    parser.add_argument("--serial", type=str, default="25061217",
                        help="Camera serial number (default: 25061217, ODMR Basler acA1920-155um)")
    parser.add_argument("--exposure", type=int, default=10000,
                        help="Exposure time in µs (default 10000)")
    args = parser.parse_args()

    results = run_tests(args.bin, args.serial, args.exposure)
    sys.exit(0 if all(results) else 1)
