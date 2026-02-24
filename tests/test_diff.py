"""Tests for pixel diff and optical flow classification."""

import numpy as np
import pytest

from ui_verdict.diff.pixel import pixel_diff
from ui_verdict.diff.flow import optical_flow
from ui_verdict.diff.classify import classify_change
from ui_verdict.models import ChangeType, Direction


def _solid(value: int, h: int = 100, w: int = 100) -> np.ndarray:
    return np.full((h, w), value, dtype=np.uint8)


def _with_rect(
    base: int, rx: int, ry: int, rw: int, rh: int, fill: int = 255
) -> np.ndarray:
    arr = _solid(base)
    arr[ry : ry + rh, rx : rx + rw] = fill
    return arr


class TestPixelDiff:
    def test_identical_frames_no_change(self):
        frame = _solid(128)
        result = pixel_diff(frame, frame.copy())
        assert result["changed"] is False
        assert result["change_ratio"] == pytest.approx(0.0)

    def test_fully_different_frames_changed(self):
        before = _solid(0)
        after = _solid(255)
        result = pixel_diff(before, after)
        assert result["changed"] is True
        assert result["change_ratio"] > 0.99

    def test_small_noise_below_threshold(self):
        before = _solid(100)
        after = _solid(110)  # diff=10, below PIXEL_THRESHOLD=25
        result = pixel_diff(before, after)
        assert result["changed"] is False

    def test_partial_change(self):
        before = _solid(0)
        after = _with_rect(0, 10, 10, 50, 50, fill=200)
        result = pixel_diff(before, after)
        assert result["changed"] is True
        assert 0.1 < result["change_ratio"] < 0.9


class TestClassify:
    def test_no_change(self):
        frame = _solid(100)
        result = classify_change(frame, frame.copy())
        assert result.changed is False
        assert result.change_type == ChangeType.NONE
        assert result.direction == Direction.NONE

    def test_appearance(self):
        before = _solid(50)
        after = _with_rect(50, 20, 20, 60, 60, fill=220)
        result = classify_change(before, after)
        assert result.changed is True
        assert result.change_type in (ChangeType.APPEARANCE, ChangeType.MIXED)

    def test_large_change_detected(self):
        before = _solid(0, h=200, w=200)
        after = _solid(255, h=200, w=200)
        result = classify_change(before, after)
        assert result.changed is True
        assert result.change_ratio > 0.9
