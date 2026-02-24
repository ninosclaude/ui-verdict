from __future__ import annotations

import cv2
import numpy as np


# Threshold in intensity units (0-255) to filter JPEG/PNG compression noise
_PIXEL_THRESHOLD = 25
# Minimum ratio of changed pixels to consider "meaningful change"
# 0.0005 = 0.05% — catches subtle UI state changes (toolbar highlights, cursor changes)
# while filtering display/compression noise (~0.001%)
_MIN_CHANGE_RATIO = 0.0005


def pixel_diff(before: np.ndarray, after: np.ndarray) -> dict:
    """
    Fast tiered pixel difference.
    Returns changed (bool), change_ratio (float 0-1), changed_mask (ndarray).
    ~2ms on 1920x1080.
    """
    diff = cv2.absdiff(before, after)
    _, mask = cv2.threshold(diff, _PIXEL_THRESHOLD, 255, cv2.THRESH_BINARY)
    changed_pixels = int(np.count_nonzero(mask))
    total_pixels = mask.size
    ratio = changed_pixels / total_pixels
    return {
        "changed": ratio >= _MIN_CHANGE_RATIO,
        "change_ratio": ratio,
        "mean_diff": float(np.mean(diff)),
        "changed_mask": mask,
    }
