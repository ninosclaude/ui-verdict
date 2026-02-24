"""
Report generation for QA-Agent.

Generates structured QAReport with actionable what_to_fix.
"""

from __future__ import annotations

from .models import QAReport, ACResult, Status, Severity, CheckLevel, StepLog
from .logging_config import get_logger

logger = get_logger(__name__)


def generate_what_to_fix(acs: list[ACResult]) -> str:
    """Generate actionable fix instructions with screenshot references.

    Returns a formatted string that developers can act on immediately.
    Includes screenshot paths so developers don't need to search JSON.
    """
    failed = [ac for ac in acs if ac.status == Status.FAIL]
    warned = [ac for ac in acs if ac.status == Status.WARN]

    if not failed and not warned:
        return "All checks passed. No fixes needed."

    lines = []

    # Critical failures first (severity-based)
    critical_fails = [ac for ac in failed if ac.severity == Severity.CRITICAL]
    if critical_fails:
        lines.append("🔴 CRITICAL - Must fix before release:")
        for ac in critical_fails:
            lines.append(f"  • [{ac.check_id}] {ac.ac}")
            if ac.diagnosis:
                lines.append(f"    Problem: {ac.diagnosis}")
            if ac.screenshot:
                lines.append(f"    Screenshot: {ac.screenshot}")
            if ac.details:
                _append_relevant_details(lines, ac.details)
        lines.append("")

    # High severity failures
    high_fails = [ac for ac in failed if ac.severity == Severity.HIGH]
    if high_fails:
        lines.append("🟠 HIGH - Should fix:")
        for ac in high_fails:
            lines.append(f"  • [{ac.check_id}] {ac.ac}")
            if ac.diagnosis:
                lines.append(f"    Problem: {ac.diagnosis}")
            if ac.screenshot:
                lines.append(f"    Screenshot: {ac.screenshot}")
            if ac.details:
                _append_relevant_details(lines, ac.details)
        lines.append("")

    # Medium/Low failures
    other_fails = [
        ac for ac in failed if ac.severity in (Severity.MEDIUM, Severity.LOW)
    ]
    if other_fails:
        lines.append("🟡 MEDIUM/LOW:")
        for ac in other_fails:
            lines.append(f"  • [{ac.check_id}] {ac.ac}")
            if ac.diagnosis:
                lines.append(f"    Problem: {ac.diagnosis}")
            if ac.screenshot:
                lines.append(f"    Screenshot: {ac.screenshot}")
            if ac.details:
                _append_relevant_details(lines, ac.details)
        lines.append("")

    # Warnings (collapsed)
    if warned:
        lines.append(f"⚠️ WARNINGS ({len(warned)} items):")
        for ac in warned:
            diagnosis_preview = (
                (ac.diagnosis[:80] + "...")
                if ac.diagnosis and len(ac.diagnosis) > 80
                else (ac.diagnosis or "Unknown")
            )
            lines.append(f"  • [{ac.check_id}] {ac.ac}: {diagnosis_preview}")
            if ac.screenshot:
                lines.append(f"    See: {ac.screenshot}")

    return "\n".join(lines).strip()


def _append_relevant_details(lines: list[str], details: dict) -> None:
    """Append human-relevant details from the details dict."""
    if not details:
        return

    if "change_ratio" in details:
        lines.append(f"    Pixel diff: {details['change_ratio']:.4f}")

    if "expected" in details and "actual" in details:
        lines.append(f"    Expected: {details['expected']}, Got: {details['actual']}")

    if "error" in details:
        lines.append(f"    Error: {details['error']}")

    # Add other relevant detail keys as needed
    ignored_keys = {"change_ratio", "expected", "actual", "error"}
    for key, value in details.items():
        if key in ignored_keys:
            continue
        if isinstance(value, (str, int, float, bool)):
            lines.append(f"    {key}: {value}")


def compute_level_statuses(acs: list[ACResult]) -> dict[str, str]:
    """Compute status for each check level."""
    levels = {}

    for level in CheckLevel:
        level_acs = [ac for ac in acs if ac.level == level]

        if not level_acs:
            levels[level.value] = "SKIPPED"
            continue

        fails = sum(1 for ac in level_acs if ac.status == Status.FAIL)
        warns = sum(1 for ac in level_acs if ac.status == Status.WARN)

        if fails > 0:
            levels[level.value] = "FAIL"
        elif warns > 0:
            levels[level.value] = f"{warns} warnings"
        else:
            levels[level.value] = "PASS"

    return levels


def build_report(
    run_id: str,
    story: str,
    acs: list[ACResult],
    steps: list[StepLog],
    duration: float,
) -> QAReport:
    """Build final QAReport from check results.

    Includes summary counts, actionable what_to_fix with screenshots,
    level breakdown, and all detailed results.
    """
    passed = sum(1 for ac in acs if ac.status == Status.PASS)
    failed = sum(1 for ac in acs if ac.status == Status.FAIL)
    warned = sum(1 for ac in acs if ac.status == Status.WARN)
    skipped = sum(1 for ac in acs if ac.status == Status.SKIPPED)

    # Determine overall status (guard clauses)
    if failed > 0:
        overall = Status.FAIL
        logger.info(f"Report status: FAIL ({failed} failures)")
    elif warned > 0:
        overall = Status.WARN
        logger.info(f"Report status: WARN ({warned} warnings)")
    elif passed > 0:
        overall = Status.PASS
        logger.info(f"Report status: PASS ({passed} passed)")
    else:
        overall = Status.SKIPPED
        logger.info("Report status: SKIPPED (no checks run)")

    return QAReport(
        run_id=run_id,
        story=story,
        overall_status=overall,
        duration_seconds=duration,
        acs_passed=passed,
        acs_failed=failed,
        acs_skipped=skipped,
        what_to_fix=generate_what_to_fix(acs),
        levels=compute_level_statuses(acs),
        acs=acs,
        steps=steps,
    )
