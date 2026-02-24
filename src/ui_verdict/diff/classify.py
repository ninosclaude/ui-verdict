from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..models import ChangeType, Direction
from .pixel import pixel_diff
from .flow import optical_flow


# If >30% of tracked features are lost, something appeared/disappeared
_APPEARANCE_THRESHOLD = 0.30
# If >10% of tracked points have significant motion, classify as movement
_MOVEMENT_THRESHOLD = 0.10


@dataclass
class ChangeResult:
    changed: bool
    change_type: ChangeType
    change_ratio: float
    direction: Direction
    magnitude: float
    moving_ratio: float


def classify_change(before: np.ndarray, after: np.ndarray) -> ChangeResult:
    """
    Tiered change classification:
    1. Pixel diff (fast gate, ~2ms)
    2. Optical flow for direction + type (~10ms)

    Returns ChangeResult with change_type: no_change / movement / appearance / mixed.
    """
    pdiff = pixel_diff(before, after)

    if not pdiff["changed"]:
        return ChangeResult(
            changed=False,
            change_type=ChangeType.NONE,
            change_ratio=pdiff["change_ratio"],
            direction=Direction.NONE,
            magnitude=0.0,
            moving_ratio=0.0,
        )

    flow = optical_flow(before, after)

    has_movement = flow["has_flow"] and flow["moving_ratio"] >= _MOVEMENT_THRESHOLD
    # Heuristic: high change ratio with low coherent flow = appearance/disappearance
    has_appearance = not flow["has_flow"] or (
        pdiff["change_ratio"] > 0.05 and flow["moving_ratio"] < _MOVEMENT_THRESHOLD
    )

    if has_movement and has_appearance:
        change_type = ChangeType.MIXED
    elif has_movement:
        change_type = ChangeType.MOVEMENT
    else:
        change_type = ChangeType.APPEARANCE

    return ChangeResult(
        changed=True,
        change_type=change_type,
        change_ratio=pdiff["change_ratio"],
        direction=flow["direction"],
        magnitude=flow["magnitude"],
        moving_ratio=flow["moving_ratio"],
    )
