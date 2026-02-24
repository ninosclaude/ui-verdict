from __future__ import annotations

import cv2
import numpy as np

from ..models import Direction


_FEATURE_PARAMS = dict(maxCorners=200, qualityLevel=0.3, minDistance=7, blockSize=7)
_LK_PARAMS = dict(
    winSize=(15, 15),
    maxLevel=2,
    criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 0.03),
)
_MIN_MAGNITUDE = 2.0  # pixels — below this is noise


def optical_flow(before: np.ndarray, after: np.ndarray) -> dict:
    """
    Sparse Lucas-Kanade optical flow.
    Returns direction, magnitude, moving_ratio, mean_vector.
    ~5-15ms on 1920x1080.
    """
    p0 = cv2.goodFeaturesToTrack(before, mask=None, **_FEATURE_PARAMS)
    if p0 is None or len(p0) == 0:
        return _empty_flow()

    p1, status, _ = cv2.calcOpticalFlowPyrLK(before, after, p0, None, **_LK_PARAMS)
    good_old = p0[status == 1]
    good_new = p1[status == 1]

    if len(good_new) == 0:
        return _empty_flow()

    displacements = good_new - good_old
    magnitudes = np.linalg.norm(displacements, axis=1)
    moving_mask = magnitudes > _MIN_MAGNITUDE
    moving_count = int(np.count_nonzero(moving_mask))
    moving_ratio = moving_count / len(magnitudes)

    if moving_count == 0:
        return _empty_flow()

    mean_disp = np.mean(displacements[moving_mask], axis=0)
    dx, dy = float(mean_disp[0]), float(mean_disp[1])
    magnitude = float(np.sqrt(dx**2 + dy**2))
    direction = _vector_to_direction(dx, dy)

    return {
        "has_flow": True,
        "direction": direction,
        "magnitude": magnitude,
        "moving_ratio": moving_ratio,
        "dx": dx,
        "dy": dy,
    }


def _empty_flow() -> dict:
    return {
        "has_flow": False,
        "direction": Direction.NONE,
        "magnitude": 0.0,
        "moving_ratio": 0.0,
        "dx": 0.0,
        "dy": 0.0,
    }


def _vector_to_direction(dx: float, dy: float) -> Direction:
    """Convert mean displacement vector to cardinal Direction.
    Image coords: +x = right, +y = down.
    """
    if abs(dx) < 0.5 and abs(dy) < 0.5:
        return Direction.NONE

    angle = float(np.degrees(np.arctan2(dy, dx))) % 360

    if angle < 22.5 or angle >= 337.5:
        return Direction.RIGHT
    if angle < 67.5:
        return Direction.DOWN_RIGHT
    if angle < 112.5:
        return Direction.DOWN
    if angle < 157.5:
        return Direction.DOWN_LEFT
    if angle < 202.5:
        return Direction.LEFT
    if angle < 247.5:
        return Direction.UP_LEFT
    if angle < 292.5:
        return Direction.UP
    return Direction.UP_RIGHT
