from __future__ import annotations

import colorsys
import numpy as np
from PIL import Image
import wcag_contrast_ratio as wcag

from ..models import ContrastReport, Issue, Severity

_AA_NORMAL = 4.5
_AAA_NORMAL = 7.0
_SAMPLE_STEP = 8  # sample every Nth pixel for speed


def check_contrast(image_path: str) -> ContrastReport:
    """
    Check WCAG contrast compliance by sampling pixel pairs.
    Compares each sampled pixel against its local neighborhood background.
    ~20-50ms on 1920x1080.
    """
    img = Image.open(image_path).convert("RGB")
    arr = np.array(img)
    ratios = _sample_contrast_ratios(arr)

    if not ratios:
        return ContrastReport(
            min_ratio=0.0,
            avg_ratio=0.0,
            wcag_aa=False,
            wcag_aaa=False,
            issues=[
                Issue(
                    severity=Severity.FAIL,
                    category="contrast",
                    message="No pixels sampled",
                )
            ],
        )

    min_ratio = float(np.min(ratios))
    avg_ratio = float(np.mean(ratios))
    aa_pass = min_ratio >= _AA_NORMAL
    aaa_pass = min_ratio >= _AAA_NORMAL

    issues: list[Issue] = []
    if not aa_pass:
        issues.append(
            Issue(
                severity=Severity.FAIL,
                category="contrast",
                message=f"Minimum contrast {min_ratio:.1f}:1 below WCAG AA threshold ({_AA_NORMAL}:1)",
            )
        )
    elif not aaa_pass:
        issues.append(
            Issue(
                severity=Severity.WARN,
                category="contrast",
                message=f"Minimum contrast {min_ratio:.1f}:1 below WCAG AAA threshold ({_AAA_NORMAL}:1)",
            )
        )

    return ContrastReport(
        min_ratio=min_ratio,
        avg_ratio=avg_ratio,
        wcag_aa=aa_pass,
        wcag_aaa=aaa_pass,
        issues=issues,
    )


def _sample_contrast_ratios(arr: np.ndarray) -> list[float]:
    """Sample local pixel pairs across the image and compute contrast ratios."""
    ratios: list[float] = []
    h, w = arr.shape[:2]

    for y in range(0, h - _SAMPLE_STEP, _SAMPLE_STEP * 4):
        for x in range(0, w - _SAMPLE_STEP, _SAMPLE_STEP * 4):
            fg = tuple(arr[y, x] / 255.0)
            bg = tuple(
                arr[min(y + _SAMPLE_STEP, h - 1), min(x + _SAMPLE_STEP, w - 1)] / 255.0
            )
            try:
                ratio = wcag.rgb(fg, bg)  # type: ignore[arg-type]
                ratios.append(float(ratio))
            except Exception:
                continue

    return ratios
