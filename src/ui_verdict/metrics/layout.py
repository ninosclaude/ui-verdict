from __future__ import annotations

import io
import numpy as np
from PIL import Image
from scipy.stats import entropy

from ..models import LayoutReport, Issue, Severity


def check_layout(image_path: str) -> LayoutReport:
    """
    Deterministic layout quality metrics:
    - Balance score: Shannon entropy variance across quadrants (lower std = better)
    - Clutter score: PNG compression ratio (higher = cleaner)
    ~10-30ms on 1920x1080.
    """
    img = Image.open(image_path).convert("L")  # grayscale
    arr = np.array(img)

    balance = _balance_score(arr)
    clutter = _clutter_score(img)
    alignment = _alignment_score(arr)

    issues: list[Issue] = []
    if balance < 0.5:
        issues.append(
            Issue(
                severity=Severity.WARN,
                category="layout",
                message=f"Layout imbalance detected (balance_score={balance:.2f})",
            )
        )
    if clutter < 0.3:
        issues.append(
            Issue(
                severity=Severity.WARN,
                category="layout",
                message=f"High visual clutter (clutter_score={clutter:.2f})",
            )
        )

    return LayoutReport(
        balance_score=balance,
        clutter_score=clutter,
        alignment_score=alignment,
        issues=issues,
    )


def _balance_score(arr: np.ndarray) -> float:
    """
    Divide into 4 quadrants, compute Shannon entropy per quadrant.
    Normalised std of entropies: low std = balanced layout → score near 1.0.
    """
    h, w = arr.shape
    mh, mw = h // 2, w // 2
    quadrants = [
        arr[:mh, :mw],
        arr[:mh, mw:],
        arr[mh:, :mw],
        arr[mh:, mw:],
    ]
    entropies = [_shannon_entropy(q) for q in quadrants]
    std = float(np.std(entropies))
    # Normalise: std of 0 = perfect balance (1.0), std of 3 = very imbalanced (~0)
    return float(max(0.0, 1.0 - std / 3.0))


def _shannon_entropy(region: np.ndarray) -> float:
    hist, _ = np.histogram(region.ravel(), bins=256, range=(0, 256))
    hist = hist[hist > 0].astype(float)
    probs = hist / hist.sum()
    return float(entropy(probs))


def _clutter_score(img: Image.Image) -> float:
    """
    Compression ratio as clutter proxy.
    raw_bytes / compressed_bytes → higher = simpler (cleaner) UI.
    Normalised to 0-1 range based on empirical bounds [1.0, 8.0].
    """
    raw = img.width * img.height  # grayscale = 1 byte/pixel
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=9)
    compressed = buf.tell()
    if compressed == 0:
        return 0.0
    ratio = raw / compressed
    # Clamp and normalise: ratio 1.0 → score 0.0, ratio 8.0 → score 1.0
    return float(min(1.0, max(0.0, (ratio - 1.0) / 7.0)))


def _alignment_score(arr: np.ndarray) -> float:
    """
    Placeholder alignment heuristic using edge density.
    A future version will use Hough lines for grid detection.
    Returns 0.7 as neutral default until full implementation.
    """
    # Edge density: very dense = lots of elements = potentially well-structured
    import cv2

    edges = cv2.Canny(arr, 50, 150)
    density = float(np.count_nonzero(edges)) / edges.size
    # Moderate density is ideal — too sparse or too dense both score lower
    ideal = 0.05
    deviation = abs(density - ideal) / ideal
    return float(max(0.0, 1.0 - min(deviation, 1.0)))
