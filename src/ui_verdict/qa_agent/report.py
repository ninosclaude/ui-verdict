"""
Report generation for QA-Agent.

Generates structured QAReport with actionable what_to_fix.
"""
from __future__ import annotations

from .models import QAReport, ACResult, Status, Severity, CheckLevel, StepLog


def generate_what_to_fix(acs: list[ACResult]) -> str:
    """Generate actionable fix instructions from failed ACs.
    
    This is the most important output field - must be concrete, 
    actionable, and technical.
    """
    failures = [ac for ac in acs if ac.status == Status.FAIL]
    
    if not failures:
        return "All checks passed. No fixes needed."
    
    lines = []
    
    # Group by level for prioritization
    preflight_fails = [f for f in failures if f.level == CheckLevel.PRE_FLIGHT]
    reach_fails = [f for f in failures if f.level == CheckLevel.REACHABILITY]
    func_fails = [f for f in failures if f.level == CheckLevel.FUNCTIONAL]
    edge_fails = [f for f in failures if f.level == CheckLevel.EDGE_CASES]
    
    if preflight_fails:
        lines.append("🔴 CRITICAL - App won't start:")
        for f in preflight_fails:
            lines.append(f"  • [{f.check_id}] {f.diagnosis}")
        lines.append("")
    
    if reach_fails:
        lines.append("🔴 CRITICAL - Feature not reachable:")
        for f in reach_fails:
            lines.append(f"  • [{f.check_id}] {f.ac}")
            lines.append(f"    → {f.diagnosis}")
        lines.append("")
    
    if func_fails:
        lines.append("🟠 FUNCTIONAL - Feature broken:")
        for f in func_fails:
            lines.append(f"  • [{f.check_id}] {f.ac}")
            lines.append(f"    → {f.diagnosis}")
            if f.details.get("change_ratio") is not None:
                lines.append(f"    → pixel_diff: {f.details['change_ratio']:.4f}")
        lines.append("")
    
    if edge_fails:
        lines.append("🟡 EDGE CASES:")
        for f in edge_fails:
            lines.append(f"  • [{f.check_id}] {f.ac}: {f.diagnosis}")
    
    return "\n".join(lines).strip()


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
    """Build final QAReport from check results."""
    
    passed = sum(1 for ac in acs if ac.status == Status.PASS)
    failed = sum(1 for ac in acs if ac.status == Status.FAIL)
    skipped = sum(1 for ac in acs if ac.status == Status.SKIPPED)
    
    # Determine overall status
    if failed > 0:
        overall = Status.FAIL
    elif any(ac.status == Status.WARN for ac in acs):
        overall = Status.WARN
    else:
        overall = Status.PASS
    
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
