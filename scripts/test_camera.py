"""
Quick test: detect and connect to a PCO camera.
Prints camera info if connected, or a clear error if not found.

Run with: C:\ProgramData\anaconda3\python.exe test_camera.py
"""
import importlib.metadata
import sys

try:
    import pco
    print(f"pco library version: {importlib.metadata.version('pco')}")
except ImportError as e:
    print(f"ERROR: pco library not found: {e}")
    print("Install with: pip install pco")
    sys.exit(1)

print("Attempting to open PCO camera...")
try:
    with pco.Camera() as cam:
        print("Camera found!")

        try:
            info = cam.sdk.get_camera_type()
            print(f"  Camera type:   {info}")
        except Exception:
            pass

        try:
            desc = cam.sdk.get_camera_description()
            print(f"  Description:   {desc}")
        except Exception:
            pass

        try:
            temp = cam.sdk.get_temperature()
            print(f"  Temperature:   {temp}")
        except Exception:
            pass

        print("\nCamera connected successfully.")

except pco.camera_exception.CameraException as e:
    print(f"\nPCO SDK error: {e}")
    print("\nPossible reasons:")
    print("  - Camera is not plugged in or powered on")
    print("  - Camera is in use by another process (e.g. pco.camware)")
    print("  - USB 3.0 cable or port issue")
except Exception as e:
    print(f"\nUnexpected error: {type(e).__name__}: {e}")
