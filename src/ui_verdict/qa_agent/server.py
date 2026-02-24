"""
QA-Agent MCP Server.

Provides automated acceptance testing for desktop apps.
Implements QA-Agent spec with check taxonomy and abort logic.

Tools:
- run(): Full QA run with story → structured report
- check_screenshot(): Standalone vision checks on a screenshot
"""

from __future__ import annotations

import json
import time
import uuid

from mcp.server.fastmcp import FastMCP

from .models import QAReport, ACResult, Status, Severity, CheckLevel, StepLog
from .executor import stop_app, take_screenshot
from .checks import (
    # Pre-Flight
    check_p01_app_launches,
    check_p02_navigation_exists,
    check_p03_correct_initial_state,
    # Reachability
    check_r01_feature_linked,
    check_r02_reachable_in_clicks,
    check_r03_feature_visible,
    check_r04_no_feature_flag,
    check_r05_click_navigates,
    # Functional
    check_f01_action_causes_change,
    check_f02_system_status,
    check_f03_result_appears,
    check_f04_result_matches_ac,
    check_f05_state_consistent,
    check_f06_all_buttons_bound,
    # Edge Cases
    check_e01_empty_state,
    check_e02_long_input,
    check_e03_special_chars,
    check_e04_error_state,
    check_e05_double_submit,
    check_e06_persistence,
    # Visual
    check_v01_contrast,
    check_v02_text_truncated,
    check_v03_element_overlaps,
    check_v04_touch_targets,
    check_v05_render_performance,
    check_v06_ui_bleeding,
)
from .report import build_report
from .context import fetch_context
from .vision import ask_vision_bool


mcp = FastMCP("qa-agent")


def _extract_keywords(story: str) -> list[str]:
    """Extract likely feature keywords from story."""
    words = story.lower().split()
    keywords = []
    skip_words = {
        "als",
        "user",
        "möchte",
        "ich",
        "damit",
        "kann",
        "können",
        "das",
        "die",
        "der",
        "ein",
        "eine",
    }
    for word in words:
        clean = word.strip(".,!?")
        if len(clean) > 3 and clean not in skip_words:
            keywords.append(clean)
    return keywords[:3]


def _abort_report(
    run_id: str,
    story: str,
    acs_results: list[ACResult],
    steps: list[StepLog],
    start_time: float,
    abort_reason: str,
) -> str:
    """Create report when aborting due to critical failure."""
    duration = time.time() - start_time
    steps.append(StepLog(f"Abort: {abort_reason}", "error", {}))
    report = build_report(run_id, story, acs_results, steps, duration)
    return report.to_json()


@mcp.tool()
def run(
    story: str,
    binary: str,
    app_name: str,
    acs: list[str] | None = None,
    feature_hints: list[str] | None = None,
    initial_state: str | None = None,
    env: dict[str, str] | None = None,
    skip_levels: list[str] | None = None,
    project_id: str | None = None,
    navigation_action: str | None = None,
) -> str:
    """
    Run full QA acceptance test suite on a desktop app.

    Args:
        story: User story text (e.g. "Als User möchte ich...")
        binary: Path to app binary in VM (e.g. "/app/myapp")
        app_name: Process name for pgrep (e.g. "myapp")
        acs: Optional explicit acceptance criteria
        feature_hints: Keywords for R-01 feature search
        initial_state: Expected initial state for P-03
        env: Environment variables for app launch
        skip_levels: Levels to skip (e.g. ["edge_cases", "visual"])
        project_id: Manyminds project ID for context fetching
        navigation_action: Explicit action to reach feature (e.g. "key:ctrl+o").
                          If provided, used for R-05 check. If not, R-05 is skipped.

    Returns:
        JSON string of QAReport with all check results
    """
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    start_time = time.time()
    steps: list[StepLog] = []
    acs_results: list[ACResult] = []
    skip_levels = skip_levels or []

    # 1. Fetch context if project_id given
    if project_id:
        context = fetch_context(project_id, story)
        steps.append(StepLog("Context fetched", "ok", {"project_id": project_id}))

    # 2. Pre-Flight
    p01 = check_p01_app_launches(binary, app_name, env, steps)
    acs_results.append(p01)
    if p01.status == Status.FAIL:
        return _abort_report(
            run_id,
            story,
            acs_results,
            steps,
            start_time,
            "Pre-flight failed: app won't start",
        )

    p02 = check_p02_navigation_exists(steps)
    acs_results.append(p02)
    if p02.status == Status.FAIL:
        stop_app(app_name)
        return _abort_report(
            run_id,
            story,
            acs_results,
            steps,
            start_time,
            "Pre-flight failed: no navigation found",
        )

    p03 = check_p03_correct_initial_state(initial_state, steps)
    acs_results.append(p03)

    # 3. Reachability
    if "reachability" not in skip_levels:
        hints = feature_hints or _extract_keywords(story)
        r01 = check_r01_feature_linked(hints, steps)
        acs_results.append(r01)
        if r01.status == Status.FAIL:
            stop_app(app_name)
            return _abort_report(
                run_id,
                story,
                acs_results,
                steps,
                start_time,
                "Reachability failed: feature not linked",
            )

        # R-02: Feature reachable in ≤3 clicks
        r02 = check_r02_reachable_in_clicks(3, hints[0] if hints else "feature", steps)
        acs_results.append(r02)

        r03 = check_r03_feature_visible(hints[0] if hints else "feature", steps)
        acs_results.append(r03)

        # R-04: No feature flag blocking
        r04 = check_r04_no_feature_flag(steps)
        acs_results.append(r04)
        if r04.status == Status.FAIL:
            stop_app(app_name)
            return _abort_report(
                run_id,
                story,
                acs_results,
                steps,
                start_time,
                "Feature blocked by feature flag",
            )

        # R-05: Click navigates correctly (only if navigation_action provided)
        if not navigation_action:
            steps.append(
                StepLog(
                    "R-05 skipped",
                    "info",
                    {"reason": "no navigation_action provided"},
                )
            )

        if navigation_action and acs:
            r05 = check_r05_click_navigates(navigation_action, acs[0], steps)
            acs_results.append(r05)
            if r05.status == Status.FAIL:
                stop_app(app_name)
                return _abort_report(
                    run_id,
                    story,
                    acs_results,
                    steps,
                    start_time,
                    "Reachability failed: navigation action didn't work",
                )

    # 4. Functional
    reachability_passed = all(
        ac.status != Status.FAIL
        for ac in acs_results
        if ac.level == CheckLevel.REACHABILITY
    )

    if reachability_passed and "functional" not in skip_levels:
        hints = feature_hints or _extract_keywords(story)

        # F-01: Primary action causes change
        if hints:
            f01 = check_f01_action_causes_change(f"click:{hints[0]}", steps)
            acs_results.append(f01)

        # F-02: System status shown during actions
        f02 = check_f02_system_status("", steps)
        acs_results.append(f02)

        # F-03 and F-04: Check ACs
        for ac_text in acs or []:
            f04 = check_f04_result_matches_ac(
                action="", expected=ac_text, timeout_ms=500, steps=steps
            )
            acs_results.append(f04)

        # F-05: State consistency
        f05 = check_f05_state_consistent(["header", "content", "status"], steps)
        acs_results.append(f05)

        # F-06: All buttons bound
        f06 = check_f06_all_buttons_bound(steps)
        acs_results.append(f06)

    # 5. Edge Cases
    functional_passed = all(
        ac.status != Status.FAIL
        for ac in acs_results
        if ac.level == CheckLevel.FUNCTIONAL
    )

    if functional_passed and "edge_cases" not in skip_levels:
        # E-01: Empty state handling
        e01 = check_e01_empty_state(
            None, "Is there a helpful empty state message?", steps
        )
        acs_results.append(e01)

        # E-02: Long input handling
        e02 = check_e02_long_input("input", steps)
        acs_results.append(e02)

        # E-03: Special characters
        e03 = check_e03_special_chars("input", steps)
        acs_results.append(e03)

        # E-04: Error state handling
        e04 = check_e04_error_state("invalid action", steps)
        acs_results.append(e04)

        # E-05: Double submit protection
        e05 = check_e05_double_submit("click:submit", steps)
        acs_results.append(e05)

        # E-06: Persistence after reload
        hints = feature_hints or _extract_keywords(story)
        e06 = check_e06_persistence(
            f"click:{hints[0]}" if hints else "click:feature",
            "Is the previous state still visible?",
            steps,
        )
        acs_results.append(e06)

    # 6. Visual checks on final screenshot
    if "visual" not in skip_levels:
        final_screenshot = take_screenshot("final")
        acs_results.append(check_v01_contrast(final_screenshot))
        acs_results.append(check_v02_text_truncated(final_screenshot))
        acs_results.append(check_v03_element_overlaps(final_screenshot))
        acs_results.append(check_v04_touch_targets(final_screenshot))
        acs_results.append(check_v05_render_performance(steps))
        acs_results.append(check_v06_ui_bleeding(final_screenshot))

    # 7. Cleanup
    stop_app(app_name)

    # 8. Build report
    duration = time.time() - start_time
    report = build_report(run_id, story, acs_results, steps, duration)
    return report.to_json()


@mcp.tool()
def run_quick(
    story: str,
    binary: str,
    app_name: str,
    acs: list[str] | None = None,
    feature_hints: list[str] | None = None,
    env: dict[str, str] | None = None,
    navigation_action: str | None = None,
) -> str:
    """
    Quick QA run - Pre-Flight + Reachability only.

    Use this for fast feedback during development.
    Skips Functional, Edge Cases, and Visual checks.

    Args:
        story: User story text (e.g. "Als User möchte ich...")
        binary: Path to app binary in VM (e.g. "/app/myapp")
        app_name: Process name for pgrep (e.g. "myapp")
        acs: Optional explicit acceptance criteria
        feature_hints: Keywords for R-01 feature search
        env: Environment variables for app launch
        navigation_action: Explicit action to reach feature (e.g. "key:ctrl+o")

    Returns:
        JSON string of QAReport with Pre-Flight and Reachability results only
    """
    return run(
        story=story,
        binary=binary,
        app_name=app_name,
        acs=acs,
        feature_hints=feature_hints,
        env=env,
        skip_levels=["functional", "edge_cases", "visual"],
        navigation_action=navigation_action,
    )


@mcp.tool()
def check_screenshot(
    path: str,
    checks: list[str],
) -> str:
    """
    Check a screenshot with vision model questions.

    Args:
        path: Local path to screenshot
        checks: List of yes/no questions in English

    Returns:
        JSON with {"check_text": true/false, ...}
    """
    results = {}
    for check in checks:
        result, _ = ask_vision_bool(path, check)
        results[check] = result
    return json.dumps(results, indent=2)


if __name__ == "__main__":
    mcp.run()
