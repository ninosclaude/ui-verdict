"""
Visual baseline comparison with AI-assisted analysis.

Flow:
1. Pixel diff (fast, no LLM)
2. If change detected → Ask AI to classify
"""

from __future__ import annotations

import logging
from pathlib import Path

from .models import CompareVerdict, CompareResult, DiffRegion

logger = logging.getLogger(__name__)


def compare_with_baseline(
    baseline_path: Path | str,
    current_path: str,
    threshold: float = 0.001,
) -> CompareResult:
    """Compare current screenshot against baseline.

    Args:
        baseline_path: Path to baseline image
        current_path: Path to current screenshot
        threshold: Maximum change_ratio to consider "no change"

    Returns:
        CompareResult with verdict, change_ratio, and AI explanation
    """
    from ..capture import load_image_gray
    from ..diff.heatmap import generate_diff_mask

    # Guard: validate inputs
    if not baseline_path:
        logger.error("baseline_path is empty")
        return CompareResult(
            verdict=CompareVerdict.UNKNOWN,
            change_ratio=1.0,
            baseline_path=None,
            current_path=current_path,
            ai_explanation="baseline_path is required",
        )

    if not current_path:
        logger.error("current_path is empty")
        return CompareResult(
            verdict=CompareVerdict.UNKNOWN,
            change_ratio=1.0,
            baseline_path=str(baseline_path),
            current_path="",
            ai_explanation="current_path is required",
        )

    baseline_path = Path(baseline_path)

    # Guard: validate threshold
    if not 0.0 <= threshold <= 1.0:
        logger.warning(f"Invalid threshold {threshold}, clamping to [0.0, 1.0]")
        threshold = max(0.0, min(1.0, threshold))

    # Load images
    try:
        logger.debug(f"Loading baseline: {baseline_path}")
        before = load_image_gray(str(baseline_path))
    except FileNotFoundError:
        logger.error(f"Baseline not found: {baseline_path}")
        return CompareResult(
            verdict=CompareVerdict.UNKNOWN,
            change_ratio=1.0,
            baseline_path=str(baseline_path),
            current_path=current_path,
            ai_explanation=f"Baseline image not found: {baseline_path}",
        )
    except Exception as e:
        logger.error(f"Failed to load baseline: {e}")
        return CompareResult(
            verdict=CompareVerdict.UNKNOWN,
            change_ratio=1.0,
            baseline_path=str(baseline_path),
            current_path=current_path,
            ai_explanation=f"Failed to load baseline: {e}",
        )

    try:
        logger.debug(f"Loading current screenshot: {current_path}")
        after = load_image_gray(current_path)
    except FileNotFoundError:
        logger.error(f"Current screenshot not found: {current_path}")
        return CompareResult(
            verdict=CompareVerdict.UNKNOWN,
            change_ratio=1.0,
            baseline_path=str(baseline_path),
            current_path=current_path,
            ai_explanation=f"Current screenshot not found: {current_path}",
        )
    except Exception as e:
        logger.error(f"Failed to load current screenshot: {e}")
        return CompareResult(
            verdict=CompareVerdict.UNKNOWN,
            change_ratio=1.0,
            baseline_path=str(baseline_path),
            current_path=current_path,
            ai_explanation=f"Failed to load current screenshot: {e}",
        )

    # Guard: validate loaded images
    if before is None or before.size == 0:
        logger.error("Baseline image is empty after loading")
        return CompareResult(
            verdict=CompareVerdict.UNKNOWN,
            change_ratio=1.0,
            baseline_path=str(baseline_path),
            current_path=current_path,
            ai_explanation="Baseline image is empty",
        )

    if after is None or after.size == 0:
        logger.error("Current screenshot is empty after loading")
        return CompareResult(
            verdict=CompareVerdict.UNKNOWN,
            change_ratio=1.0,
            baseline_path=str(baseline_path),
            current_path=current_path,
            ai_explanation="Current screenshot is empty",
        )

    # Compute pixel diff
    logger.debug("Computing pixel difference")
    try:
        _, stats = generate_diff_mask(before, after)
    except Exception as e:
        logger.error(f"Failed to compute diff mask: {e}")
        return CompareResult(
            verdict=CompareVerdict.UNKNOWN,
            change_ratio=1.0,
            baseline_path=str(baseline_path),
            current_path=current_path,
            ai_explanation=f"Failed to compute diff: {e}",
        )

    change_ratio = stats.get("change_ratio", 0.0)

    logger.debug(
        f"Baseline comparison: change_ratio={change_ratio:.4f}, threshold={threshold}"
    )

    # Fast path: no change
    if change_ratio < threshold:
        logger.info(f"No visual change detected (ratio={change_ratio:.6f})")
        return CompareResult(
            verdict=CompareVerdict.NO_CHANGE,
            change_ratio=change_ratio,
            baseline_path=str(baseline_path),
            current_path=current_path,
            diff_regions=[],
        )

    # Extract diff regions
    regions = []
    raw_regions = stats.get("regions", [])
    logger.debug(f"Found {len(raw_regions)} diff regions")

    for r in raw_regions[:5]:  # Top 5 regions
        # Guard: validate region data
        if not isinstance(r, dict):
            logger.warning(f"Invalid region type: {type(r)}")
            continue

        try:
            regions.append(
                DiffRegion(
                    x=int(r.get("x", 0)),
                    y=int(r.get("y", 0)),
                    width=int(r.get("width", 0)),
                    height=int(r.get("height", 0)),
                    area=int(r.get("area", 0)),
                )
            )
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to parse region {r}: {e}")
            continue

    # Change detected → Ask AI
    logger.info(f"Visual change detected (ratio={change_ratio:.4f}), asking AI...")
    verdict, explanation = _ask_ai_classify(
        baseline_path, current_path, change_ratio, regions
    )

    return CompareResult(
        verdict=verdict,
        change_ratio=change_ratio,
        baseline_path=str(baseline_path),
        current_path=current_path,
        diff_regions=regions,
        ai_explanation=explanation,
    )


def _ask_ai_classify(
    baseline_path: Path,
    current_path: str,
    change_ratio: float,
    regions: list[DiffRegion],
) -> tuple[CompareVerdict, str]:
    """Ask vision model to classify the change.

    Uses side-by-side comparison for accurate analysis.
    """
    from ..capture import load_image_gray
    from ..diff.heatmap import generate_side_by_side
    from ..qa_agent.vision import ask_vision

    # Guard: validate inputs
    if not baseline_path:
        logger.error("baseline_path is required for AI classification")
        return CompareVerdict.UNKNOWN, "baseline_path is required"

    if not current_path:
        logger.error("current_path is required for AI classification")
        return CompareVerdict.UNKNOWN, "current_path is required"

    # Load images for side-by-side
    try:
        logger.debug("Loading images for side-by-side comparison")
        before = load_image_gray(str(baseline_path))
        after = load_image_gray(current_path)
    except Exception as e:
        logger.error(f"Failed to load images for AI analysis: {e}")
        return CompareVerdict.UNKNOWN, f"Failed to load images: {e}"

    # Guard: validate loaded images
    if before is None or before.size == 0:
        logger.error("Baseline image is empty for AI analysis")
        return CompareVerdict.UNKNOWN, "Baseline image is empty"

    if after is None or after.size == 0:
        logger.error("Current image is empty for AI analysis")
        return CompareVerdict.UNKNOWN, "Current image is empty"

    # Generate side-by-side image
    side_by_side_path = current_path.replace(".png", "_comparison.png")

    # Guard: ensure valid output path
    if not side_by_side_path.endswith("_comparison.png"):
        # Fallback if replace didn't work
        side_by_side_path = current_path + "_comparison.png"

    logger.debug(f"Generating side-by-side comparison: {side_by_side_path}")

    try:
        generate_side_by_side(before, after, side_by_side_path)
    except Exception as e:
        logger.error(f"Failed to generate side-by-side image: {e}")
        return CompareVerdict.UNKNOWN, f"Failed to generate comparison image: {e}"

    # Build region description
    region_desc = ""
    if regions:
        region_desc = "\n\nChanged regions (top-left corner):\n"
        for i, r in enumerate(regions[:3], 1):
            region_desc += (
                f"  {i}. Position ({r.x}, {r.y}), size {r.width}x{r.height}\n"
            )

    # Ask AI
    prompt = f"""This is a side-by-side comparison. LEFT is the expected baseline, RIGHT is the current state.

The pixel difference is {change_ratio * 100:.1f}%.{region_desc}

Analyze the changes and classify:
1. Is this an INTENTIONAL update (new feature, design change, content update)?
2. Or is this a REGRESSION (broken layout, missing elements, visual bug)?

Answer in this format:
VERDICT: [INTENTIONAL or REGRESSION]
EXPLANATION: [1-2 sentences describing what changed]"""

    try:
        logger.debug(f"Asking AI to classify change (prompt length={len(prompt)})")
        response = ask_vision(side_by_side_path, prompt)
    except Exception as e:
        logger.error(f"AI classification failed: {e}")
        return CompareVerdict.UNKNOWN, f"AI analysis failed: {e}"

    # Guard: validate response
    if not response or not response.strip():
        logger.error("AI returned empty response")
        return CompareVerdict.UNKNOWN, "AI returned empty response"

    # Parse response
    response_upper = response.upper()
    verdict = (
        CompareVerdict.INTENTIONAL
    )  # Default to intentional (less false positives)

    if "REGRESSION" in response_upper:
        verdict = CompareVerdict.REGRESSION
        logger.info("AI classified as REGRESSION")
    elif "INTENTIONAL" in response_upper:
        verdict = CompareVerdict.INTENTIONAL
        logger.info("AI classified as INTENTIONAL")
    else:
        logger.warning(
            f"Unclear AI response, defaulting to INTENTIONAL: {response[:100]}"
        )

    # Extract explanation
    explanation = response
    if "EXPLANATION:" in response.upper():
        parts = response.split("EXPLANATION:", 1)
        if len(parts) > 1:
            explanation = parts[1].strip()
            if not explanation:
                # Guard: empty explanation after split
                explanation = response
    elif "VERDICT:" in response.upper():
        # Try to extract everything after VERDICT line
        parts = response.split("\n", 1)
        if len(parts) > 1:
            explanation = parts[1].strip()
            if not explanation:
                # Guard: empty explanation
                explanation = response

    logger.info(f"AI verdict: {verdict.value} - {explanation[:100]}")
    return verdict, explanation


def compare_no_baseline(current_path: str) -> CompareResult:
    """Return result when no baseline exists.

    Args:
        current_path: Path to current screenshot

    Returns:
        CompareResult indicating no baseline exists
    """
    # Guard: validate input
    if not current_path:
        logger.warning("compare_no_baseline called with empty current_path")
        current_path = ""

    logger.info(f"No baseline exists for: {current_path}")

    return CompareResult(
        verdict=CompareVerdict.UNKNOWN,
        change_ratio=0.0,
        baseline_path=None,
        current_path=current_path,
        ai_explanation="No baseline exists. Create one with baseline_create().",
    )
