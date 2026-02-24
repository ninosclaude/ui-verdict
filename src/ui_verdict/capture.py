from __future__ import annotations

import platform
import subprocess
import tempfile
import time

import cv2
import mss
import numpy as np

from .models import Region


def get_window_id(app_name: str) -> int | None:
    """Find the Quartz window ID for a running app by name. macOS only."""
    if platform.system() != "Darwin":
        return None
    try:
        import Quartz

        window_list = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
        )
        for w in window_list:
            owner = w.get("kCGWindowOwnerName", "")
            if app_name.lower() in owner.lower():
                return int(w.get("kCGWindowNumber", 0)) or None
    except ImportError:
        pass
    return None


def get_window_bounds(app_name: str) -> dict | None:
    """Return {left, top, width, height} of the first window of app_name. macOS only."""
    if platform.system() != "Darwin":
        return None
    try:
        import Quartz

        window_list = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
        )
        for w in window_list:
            owner = w.get("kCGWindowOwnerName", "")
            if app_name.lower() in owner.lower():
                b = w.get("kCGWindowBounds", {})
                return {
                    "left": int(b.get("X", 0)),
                    "top": int(b.get("Y", 0)),
                    "width": int(b.get("Width", 0)),
                    "height": int(b.get("Height", 0)),
                }
    except ImportError:
        pass
    return None


def capture_window(app_name: str, output_path: str) -> bool:
    """
    Capture only the window of app_name (macOS, uses screencapture -l).
    Falls back to full-monitor screenshot on non-macOS or if window not found.
    Returns True on success.
    """
    wid = get_window_id(app_name)
    if wid is None:
        return False
    result = subprocess.run(
        ["screencapture", "-l", str(wid), "-o", "-x", output_path],
        capture_output=True,
    )
    return result.returncode == 0


class ScreenGrabber:
    """
    Persistent screen grabber.
    Supports full monitor, region, or window-specific capture (macOS).
    """

    def __init__(self, monitor_index: int = 1, app_name: str | None = None):
        self._sct = mss.mss()
        self._monitor = self._sct.monitors[monitor_index]
        self._app_name = app_name
        # If app_name given, pin the monitor to that window's bounds
        if app_name:
            bounds = get_window_bounds(app_name)
            if bounds:
                # mss uses absolute screen coords — find which monitor contains the window
                for mon in self._sct.monitors[1:]:
                    if mon["left"] <= bounds["left"] < mon["left"] + mon["width"]:
                        self._monitor = mon
                        break

    def grab_gray(self, region: Region | None = None) -> np.ndarray:
        mon = self._region_to_mon(region)
        img = self._sct.grab(mon)
        frame = np.array(img, dtype=np.uint8)
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)

    def grab_bgr(self, region: Region | None = None) -> np.ndarray:
        mon = self._region_to_mon(region)
        img = self._sct.grab(mon)
        frame = np.array(img, dtype=np.uint8)
        return frame[:, :, :3]

    def grab_pair(
        self, delay_ms: int = 200, region: Region | None = None
    ) -> tuple[np.ndarray, np.ndarray]:
        """Capture before/after pair with delay. Returns grayscale arrays."""
        before = self.grab_gray(region)
        time.sleep(delay_ms / 1000.0)
        after = self.grab_gray(region)
        return before, after

    def crop_region(self, image: np.ndarray, region: Region) -> np.ndarray:
        """Crop a numpy array to region bounds."""
        return image[region.y : region.y + region.h, region.x : region.x + region.w]

    def save_screenshot(self, path: str, region: Region | None = None) -> None:
        """Save screenshot. If app_name was set, uses screencapture -l for clean window-only capture."""
        if self._app_name and region is None and platform.system() == "Darwin":
            if capture_window(self._app_name, path):
                return
        img = self.grab_bgr(region)
        cv2.imwrite(path, img)

    def _region_to_mon(self, region: Region | None) -> dict:
        if region is None:
            return self._monitor
        return {
            "top": region.y,
            "left": region.x,
            "width": region.w,
            "height": region.h,
        }

    def close(self) -> None:
        self._sct.close()

    def __enter__(self) -> "ScreenGrabber":
        return self

    def __exit__(self, *_) -> None:
        self.close()


def load_image_gray(path: str) -> np.ndarray:
    """Load image from file as grayscale numpy array."""
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError(f"Cannot load image: {path}")
    return img


def load_image_bgr(path: str) -> np.ndarray:
    """Load image from file as BGR numpy array."""
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Cannot load image: {path}")
    return img
