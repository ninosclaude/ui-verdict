"""
QA-Agent MCP Server.

Provides automated acceptance testing for desktop and web apps.
Implements QA-Agent spec with check taxonomy and abort logic.

Tools:
- run(): Full QA run with story → structured report
- check_screenshot(): Standalone vision checks on a screenshot
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Literal

from mcp.server.fastmcp import FastMCP

from .logging_config import get_logger

logger = get_logger(__name__)

from .models import QAReport, ACResult, Status, Severity, CheckLevel, StepLog
from .desktop_executor import DesktopExecutor, get_desktop_executor
from .web_executor import WebExecutor, WebConfig, get_web_executor
from .checks import (
    # Pre-Flight
    check_p01_app_launches,
    check_p02_navigation_exists,
    check_p03_correct_initial_state,
    # Reachability
    check_r01_feature_linked,
    check_r03_feature_visible,
    check_r04_no_feature_flag,
    check_r05_click_navigates,
    # Functional
    check_f01_action_causes_change,
    check_f05_state_consistent,
    check_f06_all_buttons_bound,
    # Edge Cases
    check_e01_empty_state,
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
from .vision import ask_vision_bool, ask_vision, set_platform
from ui_verdict.vm import build_in_vm


mcp = FastMCP("qa-agent")


def _check_p01_web(
    executor: WebExecutor,
    url: str,
    app_name: str,
    steps: list[StepLog],
) -> ACResult:
    """P-01 for web: Browser opens URL successfully."""

    # Check if executor is available
    if not executor.is_available():
        steps.append(
            StepLog(
                "Web executor check",
                "fail",
                {"error": "Node.js or Midscene not available"},
            )
        )
        return ACResult(
            ac="Browser opens URL",
            check_id="P-01",
            level=CheckLevel.PRE_FLIGHT,
            status=Status.FAIL,
            severity=Severity.CRITICAL,
            diagnosis="Web executor not available. Run: cd midscene && npm install",
        )

    steps.append(StepLog("Web executor ready", "ok"))

    # Start browser and navigate to URL
    result = executor.start_app(url, app_name)

    if not result.success:
        steps.append(
            StepLog("Browser launch", "fail", {"url": url, "error": result.message})
        )
        return ACResult(
            ac="Browser opens URL",
            check_id="P-01",
            level=CheckLevel.PRE_FLIGHT,
            status=Status.FAIL,
            severity=Severity.CRITICAL,
            diagnosis=f"Failed to open URL: {result.message}",
        )

    # Take screenshot to verify page loaded
    screenshot = executor.take_screenshot("p01_web")
    steps.append(StepLog("Browser opened URL", "ok", {"url": url}, screenshot))

    return ACResult(
        ac="Browser opens URL",
        check_id="P-01",
        level=CheckLevel.PRE_FLIGHT,
        status=Status.PASS,
        severity=Severity.CRITICAL,
        diagnosis=f"Successfully opened {url}",
        screenshot=screenshot,
    )


def _check_p02_web(
    executor: WebExecutor,
    steps: list[StepLog],
) -> ACResult:
    """P-02 for web: Navigation/interactive elements exist."""

    screenshot = executor.take_screenshot("p02_web")

    description = ask_vision(
        screenshot,
        "List all interactive UI elements visible: buttons, menus, toolbars, links, icons. Be brief, just list them.",
    )

    ui_keywords = [
        "button",
        "link",
        "menu",
        "icon",
        "nav",
        "tab",
        "input",
        "search",
        "form",
    ]
    found = any(kw in description.lower() for kw in ui_keywords)

    if not found:
        steps.append(
            StepLog("Navigation check", "fail", {"description": description[:200]})
        )
        return ACResult(
            ac="Navigation exists",
            check_id="P-02",
            level=CheckLevel.PRE_FLIGHT,
            status=Status.FAIL,
            severity=Severity.HIGH,
            diagnosis="No interactive elements found",
            screenshot=screenshot,
        )

    steps.append(
        StepLog(
            "Navigation found", "ok", {"description": description[:100]}, screenshot
        )
    )
    return ACResult(
        ac="Navigation exists",
        check_id="P-02",
        level=CheckLevel.PRE_FLIGHT,
        status=Status.PASS,
        severity=Severity.HIGH,
        diagnosis=f"Found: {description[:100]}",
        screenshot=screenshot,
    )


def _check_r01_web(
    executor: WebExecutor,
    feature_hints: list[str],
    steps: list[StepLog],
) -> ACResult:
    """R-01 for web: Feature linked/visible on page."""
    screenshot = executor.take_screenshot("r01_web")
    hints_str = ", ".join(feature_hints)

    # Better prompt for web - describe what you SEE, then check
    description = ask_vision(
        screenshot,
        "Look at this webpage and describe what content and features are visible. "
        "Focus on: titles, headings, lists, data, and main content areas. Be specific.",
    )

    # Check if any hint appears in the description
    description_lower = description.lower()
    found_hints = [h for h in feature_hints if h.lower() in description_lower]

    if found_hints:
        steps.append(
            StepLog(
                f"Feature linked ({hints_str})",
                "ok",
                {"found": found_hints},
                screenshot,
            )
        )
        return ACResult(
            ac=f"Feature linked ({hints_str})",
            check_id="R-01",
            level=CheckLevel.REACHABILITY,
            status=Status.PASS,
            severity=Severity.CRITICAL,
            diagnosis=f"Found: {', '.join(found_hints)}. Content: {description[:150]}",
            screenshot=screenshot,
        )

    # Fallback: direct question
    result, explanation = ask_vision_bool(
        screenshot,
        f"Does this page show content related to any of these topics: {hints_str}? "
        f"Look for headings, lists, or data that match these keywords.",
    )

    status = Status.PASS if result else Status.FAIL
    steps.append(
        StepLog(
            f"Feature linked ({hints_str})",
            "ok" if result else "fail",
            screenshot=screenshot,
        )
    )

    return ACResult(
        ac=f"Feature linked ({hints_str})",
        check_id="R-01",
        level=CheckLevel.REACHABILITY,
        status=status,
        severity=Severity.CRITICAL,
        diagnosis=explanation,
        screenshot=screenshot,
    )


def _check_r03_web(
    executor: WebExecutor,
    feature_desc: str,
    steps: list[StepLog],
) -> ACResult:
    """R-03 for web: Feature clearly visible (not hidden/loading)."""
    screenshot = executor.take_screenshot("r03_web")

    result, explanation = ask_vision_bool(
        screenshot,
        "Is the main content of this page fully loaded and visible? "
        "There should be no loading spinners, 'coming soon' messages, or error states.",
    )

    steps.append(
        StepLog("Content visible", "ok" if result else "fail", screenshot=screenshot)
    )

    return ACResult(
        ac="Content visible",
        check_id="R-03",
        level=CheckLevel.REACHABILITY,
        status=Status.PASS if result else Status.FAIL,
        severity=Severity.CRITICAL,
        diagnosis=explanation,
        screenshot=screenshot,
    )


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
    build_source_path: str | None = None,
    build_vm_dest: str | None = None,
    test_all_buttons: bool = False,
    platform: Literal["desktop", "web"] = "desktop",
    baseline_mode: bool = False,
    baseline_name: str | None = None,
) -> str:
    """
    Run full QA acceptance test suite on a desktop or web app.

    Args:
        story: User story text (e.g. "Als User möchte ich...")
        binary: Path to app binary in VM (desktop) or URL (web)
        app_name: Process name for pgrep (desktop) or optional name for logging (web)
        acs: Optional explicit acceptance criteria
        feature_hints: Keywords for R-01 feature search
        initial_state: Expected initial state for P-03
        env: Environment variables for app launch (desktop only)
        skip_levels: Levels to skip (e.g. ["edge_cases", "visual"])
        project_id: Manyminds project ID for context fetching
        navigation_action: Explicit action to reach feature (e.g. "key:ctrl+o").
                          If provided, used for R-05 and functional checks. If not, many checks are skipped.
        build_source_path: Mac path to project root (desktop only). If set, syncs source to VM and
                          runs cargo build --release before launching the app.
        build_vm_dest: VM path to build directory (desktop only, required when build_source_path is set).
                      E.g. "/home/nwagensonner/imagination-linux"
        test_all_buttons: If True, runs F-06 (all buttons bound check).
                          ⚠️  DANGEROUS: This clicks every visible button which may trigger
                          destructive actions (logout, delete, etc.). Disabled by default.
                          Only enable in isolated test environments.
        platform: Platform to test on ("desktop" or "web"). Default: "desktop"
        baseline_mode: If True, enables baseline visual comparison instead of detailed checks.
        baseline_name: Optional name for baseline. If not provided, generates hash from story.

    Returns:
        JSON string of QAReport with all check results
    """
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    start_time = time.time()
    steps: list[StepLog] = []
    acs_results: list[ACResult] = []
    skip_levels = skip_levels or []

    logger.info(
        f"Starting QA run: {run_id} | story={story[:50]}... | platform={platform}"
    )

    # Select executor based on platform
    if platform == "web":
        executor = get_web_executor()
    else:
        executor = get_desktop_executor()

    # Track if app was started (for cleanup)
    app_started = False

    try:
        # 0. Build latest binary if requested (desktop only)
        if platform == "desktop" and build_source_path and build_vm_dest:
            build_result = build_in_vm(build_source_path, build_vm_dest)
            if build_result["success"]:
                steps.append(
                    StepLog(
                        "Build succeeded",
                        "ok",
                        {"elapsed_seconds": round(build_result["elapsed_seconds"], 1)},
                    )
                )
            else:
                steps.append(
                    StepLog("Build failed", "error", {"error": build_result["error"]})
                )
                return _abort_report(
                    run_id,
                    story,
                    acs_results,
                    steps,
                    start_time,
                    f"Build failed: {build_result['error'][:200]}",
                )

        # 1. Fetch context if project_id given
        if project_id:
            context = fetch_context(project_id, story)
            steps.append(StepLog("Context fetched", "ok", {"project_id": project_id}))

        # 2. Pre-Flight
        if platform == "web":
            # Web: Use executor directly for pre-flight
            if not isinstance(executor, WebExecutor):
                raise ValueError("Expected WebExecutor for web platform")
            p01 = _check_p01_web(executor, binary, app_name, steps)
        else:
            # Desktop: Use existing check
            p01 = check_p01_app_launches(binary, app_name, env, steps)

        acs_results.append(p01)
        logger.debug(f"P-01 result: {p01.status.name} | {p01.diagnosis[:100]}")
        if p01.status == Status.FAIL:
            logger.warning(f"Aborting run {run_id}: P-01 failed (app won't start)")
            return _abort_report(
                run_id,
                story,
                acs_results,
                steps,
                start_time,
                "Pre-flight failed: app won't start",
            )

        # App is now started - enable cleanup
        app_started = True

        if platform == "web":
            if not isinstance(executor, WebExecutor):
                raise ValueError("Expected WebExecutor for web platform")
            p02 = _check_p02_web(executor, steps)
        else:
            p02 = check_p02_navigation_exists(steps)

        acs_results.append(p02)
        if p02.status == Status.FAIL:
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

            if platform == "web":
                if not isinstance(executor, WebExecutor):
                    raise ValueError("Expected WebExecutor for web platform")
                r01 = _check_r01_web(executor, hints, steps)
            else:
                r01 = check_r01_feature_linked(hints, steps)

            acs_results.append(r01)
            if r01.status == Status.FAIL:
                return _abort_report(
                    run_id,
                    story,
                    acs_results,
                    steps,
                    start_time,
                    "Reachability failed: feature not linked",
                )

            # R-02: Skipped - too unstable with vision-based clicking
            # Can be re-enabled when OmniParser has proper element labels
            steps.append(
                StepLog(
                    "R-02 skipped",
                    "info",
                    {"reason": "vision-based navigation unstable"},
                )
            )

            if platform == "web":
                if not isinstance(executor, WebExecutor):
                    raise ValueError("Expected WebExecutor for web platform")
                r03 = _check_r03_web(executor, hints[0] if hints else "feature", steps)
            else:
                r03 = check_r03_feature_visible(hints[0] if hints else "feature", steps)

            acs_results.append(r03)

            # R-04: No feature flag blocking
            r04 = check_r04_no_feature_flag(steps)
            acs_results.append(r04)
            if r04.status == Status.FAIL:
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
                    return _abort_report(
                        run_id,
                        story,
                        acs_results,
                        steps,
                        start_time,
                        "Reachability failed: navigation action didn't work",
                    )

        # 4. Functional (only meaningful checks)
        reachability_passed = all(
            ac.status != Status.FAIL
            for ac in acs_results
            if ac.level == CheckLevel.REACHABILITY
        )

        if reachability_passed and "functional" not in skip_levels:
            # F-01: Primary action causes change (only if we have an action)
            if navigation_action:
                f01 = check_f01_action_causes_change(navigation_action, steps)
                acs_results.append(f01)

            # F-04: Verify each AC is true on current screenshot (NO action, just verify)
            # Take ONE screenshot and check all ACs against it
            if acs:
                current_screenshot = executor.take_screenshot("functional")

                for ac_text in acs:
                    result, explanation = ask_vision_bool(
                        current_screenshot,
                        f"Is the following true about this screenshot: '{ac_text}'?",
                    )
                    acs_results.append(
                        ACResult(
                            ac=ac_text,
                            check_id="F-04",
                            level=CheckLevel.FUNCTIONAL,
                            status=Status.PASS if result else Status.FAIL,
                            severity=Severity.HIGH,
                            diagnosis=explanation,
                            screenshot=current_screenshot,
                        )
                    )

            # F-05: State consistency (always run, no action needed)
            f05 = check_f05_state_consistent(["header", "content", "status"], steps)
            acs_results.append(f05)

            # F-06: All buttons bound (DANGEROUS - disabled by default)
            if test_all_buttons:
                logger.warning(
                    "⚠️  F-06 (all buttons bound) is enabled. This will click every visible button "
                    "which may trigger destructive actions (logout, delete, etc.). "
                    "Consider using a fresh test environment."
                )
                steps.append(
                    StepLog(
                        "F-06 warning",
                        "warn",
                        {
                            "message": "All buttons will be clicked - may trigger destructive actions"
                        },
                    )
                )
                f06 = check_f06_all_buttons_bound(steps)
                acs_results.append(f06)
            else:
                steps.append(
                    StepLog(
                        "F-06 skipped",
                        "info",
                        {
                            "reason": "Disabled by default (set test_all_buttons=True to enable)"
                        },
                    )
                )

        # 5. Edge Cases (simplified - only meaningful checks)
        functional_passed = all(
            ac.status != Status.FAIL
            for ac in acs_results
            if ac.level == CheckLevel.FUNCTIONAL
        )

        if functional_passed and "edge_cases" not in skip_levels:
            # E-01: Empty state handling (just check current state)
            e01 = check_e01_empty_state(
                None, "Is there a helpful empty state or content visible?", steps
            )
            acs_results.append(e01)

            # Skip E-02 to E-05 - they need specific input fields which we don't know
            # E-06: Persistence only if we have a navigation action
            if navigation_action:
                e06 = check_e06_persistence(
                    navigation_action,
                    "Is the feature still accessible after reload?",
                    steps,
                )
                acs_results.append(e06)

        # 6. Visual checks
        if "visual" not in skip_levels:
            final_screenshot = executor.take_screenshot("final")

            if baseline_mode:
                from ..baseline import (
                    BaselineStore,
                    compare_with_baseline,
                    compare_no_baseline,
                    CompareVerdict,
                )

                store = BaselineStore()
                effective_name = (
                    baseline_name
                    or f"auto_{hashlib.sha256(story.encode()).hexdigest()[:8]}"
                )

                baseline_data = store.get(effective_name)
                if baseline_data:
                    baseline_path, meta = baseline_data
                    compare_result = compare_with_baseline(
                        baseline_path, final_screenshot, meta.change_threshold
                    )

                    # Convert verdict to status
                    status_map = {
                        CompareVerdict.NO_CHANGE: Status.PASS,
                        CompareVerdict.INTENTIONAL: Status.WARN,
                        CompareVerdict.REGRESSION: Status.FAIL,
                        CompareVerdict.UNKNOWN: Status.WARN,
                    }

                    acs_results.append(
                        ACResult(
                            ac="Visual baseline match",
                            check_id="V-00",
                            level=CheckLevel.VISUAL,
                            status=status_map[compare_result.verdict],
                            severity=Severity.HIGH,
                            diagnosis=compare_result.ai_explanation
                            or f"change_ratio={compare_result.change_ratio:.4f}",
                            screenshot=final_screenshot,
                            details={
                                "verdict": compare_result.verdict.value,
                                "change_ratio": compare_result.change_ratio,
                                "baseline": effective_name,
                            },
                        )
                    )

                    # Skip detailed checks if no change
                    if compare_result.verdict == CompareVerdict.NO_CHANGE:
                        steps.append(
                            StepLog(
                                "Visual checks skipped",
                                "info",
                                {"reason": "baseline match"},
                            )
                        )
                    else:
                        # Run detailed checks for regression analysis
                        acs_results.append(check_v01_contrast(final_screenshot))
                        acs_results.append(check_v02_text_truncated(final_screenshot))
                        acs_results.append(check_v03_element_overlaps(final_screenshot))
                        acs_results.append(check_v04_touch_targets(final_screenshot))
                        acs_results.append(check_v05_render_performance(steps))
                        acs_results.append(check_v06_ui_bleeding(final_screenshot))
                else:
                    # No baseline exists - create one automatically
                    store.create(effective_name, final_screenshot, url=binary)
                    steps.append(
                        StepLog("Baseline created", "info", {"name": effective_name})
                    )
                    acs_results.append(
                        ACResult(
                            ac="Visual baseline created",
                            check_id="V-00",
                            level=CheckLevel.VISUAL,
                            status=Status.PASS,
                            severity=Severity.LOW,
                            diagnosis=f"Created baseline '{effective_name}' for future comparisons",
                            screenshot=final_screenshot,
                        )
                    )
            else:
                # Existing visual checks
                acs_results.append(check_v01_contrast(final_screenshot))
                acs_results.append(check_v02_text_truncated(final_screenshot))
                acs_results.append(check_v03_element_overlaps(final_screenshot))
                acs_results.append(check_v04_touch_targets(final_screenshot))
                acs_results.append(check_v05_render_performance(steps))
                acs_results.append(check_v06_ui_bleeding(final_screenshot))

        # Build report (success path)
        duration = time.time() - start_time
        report = build_report(run_id, story, acs_results, steps, duration)
        logger.info(
            f"QA run complete: {run_id} | status={report.overall_status.name} | duration={duration:.1f}s | passed={report.acs_passed} failed={report.acs_failed}"
        )
        return report.to_json()

    except Exception as e:
        # Log the error and create error report
        logger.exception(f"QA run failed: {e}")
        steps.append(StepLog(f"Fatal error: {str(e)}", "error", {}))
        duration = time.time() - start_time
        report = build_report(run_id, story, acs_results, steps, duration)
        return report.to_json()

    finally:
        # GUARANTEED cleanup - runs even on exception
        if app_started:
            try:
                executor.stop_app(app_name)
                logger.info(f"Cleanup successful: stopped {app_name}")
            except Exception as cleanup_error:
                logger.warning(f"Cleanup failed: {cleanup_error}")


@mcp.tool()
def run_quick(
    story: str,
    binary: str,
    app_name: str,
    acs: list[str] | None = None,
    feature_hints: list[str] | None = None,
    env: dict[str, str] | None = None,
    navigation_action: str | None = None,
    build_source_path: str | None = None,
    build_vm_dest: str | None = None,
    platform: Literal["desktop", "web"] = "desktop",
) -> str:
    """
    Quick QA run - Pre-Flight + Reachability only.

    Use this for fast feedback during development.
    Skips Functional, Edge Cases, and Visual checks.

    Args:
        story: User story text (e.g. "Als User möchte ich...")
        binary: Path to app binary in VM (desktop) or URL (web)
        app_name: Process name for pgrep (desktop) or optional name for logging (web)
        acs: Optional explicit acceptance criteria
        feature_hints: Keywords for R-01 feature search
        env: Environment variables for app launch (desktop only)
        navigation_action: Explicit action to reach feature (e.g. "key:ctrl+o")
        build_source_path: Mac path to project root (desktop only). If set, syncs source to VM and
                          runs cargo build --release before launching the app.
        build_vm_dest: VM path to build directory (desktop only, required when build_source_path is set).
        platform: Platform to test on ("desktop" or "web"). Default: "desktop"

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
        build_source_path=build_source_path,
        build_vm_dest=build_vm_dest,
        platform=platform,
    )


@mcp.tool()
def check_screenshot(
    path: str,
    checks: list[str],
    platform: Literal["desktop", "web"] | None = None,
) -> str:
    """
    Check a screenshot with vision model questions.

    Args:
        path: Local path to screenshot
        checks: List of yes/no questions in English
        platform: Optional platform hint for vision model selection ("desktop" or "web")

    Returns:
        JSON with {"check_text": true/false, ...}
    """
    if platform:
        from .vision import set_platform

        set_platform(platform)

    results = {}
    for check in checks:
        result, _ = ask_vision_bool(path, check)
        results[check] = result
    return json.dumps(results, indent=2)


# ============================================================================
# BASELINE TOOLS
# ============================================================================


@mcp.tool()
def baseline_create(
    name: str,
    url: str | None = None,
    platform: Literal["desktop", "web"] = "desktop",
) -> str:
    """Create a new visual baseline from current URL/app state.

    Opens the URL (web) or launches the app (desktop), takes a screenshot,
    and saves it as the baseline for future comparisons.

    Args:
        name: Human-readable name (e.g., "homepage", "login-form", "dashboard")
        url: URL (web) or binary path (desktop) to capture
        platform: Platform to use ("desktop" or "web")

    Returns:
        JSON with baseline metadata

    Example:
        baseline_create(name="github-trending", url="https://github.com/trending", platform="web")
    """
    from ..baseline import BaselineStore

    if not url:
        return json.dumps({"error": "url is required"})

    # Select executor
    if platform == "web":
        executor = get_web_executor()
    else:
        executor = get_desktop_executor()

    try:
        # Start app/browser
        result = executor.start_app(url, name)
        if not result.success:
            return json.dumps({"error": f"Failed to open: {result.message}"})

        # Take screenshot
        screenshot_path = executor.take_screenshot(f"baseline_{name}")

        # Save baseline
        store = BaselineStore()
        meta = store.create(
            name=name,
            screenshot_path=screenshot_path,
            url=url,
            threshold=0.001,
        )

        logger.info(f"Created baseline '{name}' from {url}")
        return json.dumps(
            {
                "success": True,
                "baseline": meta.to_dict(),
                "screenshot": screenshot_path,
            }
        )

    finally:
        executor.stop_app(name)


@mcp.tool()
def baseline_compare(
    name: str,
    url: str | None = None,
    platform: Literal["desktop", "web"] = "desktop",
) -> str:
    """Compare current state against saved baseline.

    Opens the URL/app, takes a screenshot, and compares against the saved baseline.
    Uses pixel diff for fast detection, then AI for change classification.

    Args:
        name: Baseline name to compare against
        url: URL (web) or binary path (desktop). If not provided, uses URL from baseline metadata.
        platform: Platform to use ("desktop" or "web")

    Returns:
        JSON with CompareResult (verdict, change_ratio, ai_explanation)

    Verdicts:
        - NO_CHANGE: Visual identical (pixel diff < 0.1%)
        - INTENTIONAL: AI detected planned change (new feature, design update)
        - REGRESSION: AI detected bug (broken layout, missing elements)
        - UNKNOWN: No baseline exists
    """
    from ..baseline import BaselineStore, compare_with_baseline, compare_no_baseline

    store = BaselineStore()

    # Get baseline
    baseline_data = store.get(name)
    if not baseline_data:
        return json.dumps(
            {
                "error": f"Baseline '{name}' not found",
                "available": [b.name for b in store.list_all()],
            }
        )

    baseline_path, meta = baseline_data

    # Use stored URL if not provided
    target_url = url or meta.url
    if not target_url:
        return json.dumps({"error": "No URL provided and baseline has no stored URL"})

    # Select executor
    if platform == "web":
        executor = get_web_executor()
    else:
        executor = get_desktop_executor()

    try:
        # Start app/browser
        result = executor.start_app(target_url, name)
        if not result.success:
            return json.dumps({"error": f"Failed to open: {result.message}"})

        # Take screenshot
        current_screenshot = executor.take_screenshot(f"compare_{name}")

        # Compare
        compare_result = compare_with_baseline(
            baseline_path=baseline_path,
            current_path=current_screenshot,
            threshold=meta.change_threshold,
        )

        logger.info(f"Baseline compare '{name}': {compare_result.verdict.value}")
        return json.dumps(
            {
                "success": True,
                "result": compare_result.to_dict(),
            }
        )

    finally:
        executor.stop_app(name)


@mcp.tool()
def baseline_update(
    name: str,
    url: str | None = None,
    platform: Literal["desktop", "web"] = "desktop",
) -> str:
    """Update existing baseline with current state.

    Use this after confirming a visual change is intentional.

    Args:
        name: Baseline name to update
        url: URL (web) or binary path (desktop). Uses stored URL if not provided.
        platform: Platform to use ("desktop" or "web")

    Returns:
        JSON with updated baseline metadata
    """
    from ..baseline import BaselineStore

    store = BaselineStore()

    # Get existing baseline
    baseline_data = store.get(name)
    if not baseline_data:
        return json.dumps({"error": f"Baseline '{name}' not found"})

    _, meta = baseline_data
    target_url = url or meta.url

    if not target_url:
        return json.dumps({"error": "No URL provided and baseline has no stored URL"})

    # Select executor
    if platform == "web":
        executor = get_web_executor()
    else:
        executor = get_desktop_executor()

    try:
        # Start app/browser
        result = executor.start_app(target_url, name)
        if not result.success:
            return json.dumps({"error": f"Failed to open: {result.message}"})

        # Take screenshot
        screenshot_path = executor.take_screenshot(f"baseline_update_{name}")

        # Update baseline
        updated_meta = store.update(name=name, screenshot_path=screenshot_path)

        logger.info(f"Updated baseline '{name}'")
        return json.dumps(
            {
                "success": True,
                "baseline": updated_meta.to_dict(),
            }
        )

    finally:
        executor.stop_app(name)


@mcp.tool()
def baseline_list() -> str:
    """List all saved baselines.

    Returns:
        JSON array of baseline metadata
    """
    from ..baseline import BaselineStore

    store = BaselineStore()
    baselines = store.list_all()

    return json.dumps(
        {
            "count": len(baselines),
            "baselines": [b.to_dict() for b in baselines],
        }
    )


@mcp.tool()
def verify_acs(
    url: str,
    acs: list[str],
    timeout_seconds: float = 30.0,
) -> str:
    """Verify acceptance criteria against a live URL.

    Fast, reliable verification for AI coding agents.
    Single vision call, mandatory grounding, actionable failures.

    Args:
        url: The page to verify (e.g., "http://localhost:3000/login")
        acs: List of acceptance criteria to verify
        timeout_seconds: Max time for operation (default: 30s)

    Returns:
        JSON with passed/failed ACs, reasons, and suggestions

    Example:
        verify_acs(
            url="http://localhost:3000",
            acs=["Login button is visible", "Clicking login shows spinner"]
        )
    """
    from ..verify import verify_acs as _verify_acs

    result = _verify_acs(url, acs, timeout_seconds=timeout_seconds)
    return json.dumps(result.to_dict(), indent=2)


if __name__ == "__main__":
    mcp.run()
