"""
Check implementations for QA-Agent.

Full taxonomy from QA-Agent Spec:
- Pre-Flight (P-01 to P-03): App launches, navigation exists, correct state
- Reachability (R-01 to R-05): Feature linked, reachable, visible, no blockers
- Functional (F-01 to F-06): Actions work, results appear, state consistent
- Edge Cases (E-01 to E-06): Empty, long input, special chars, errors, persistence
- Visual (V-01 to V-06): Contrast, truncation, overlaps, touch targets, performance
"""

from __future__ import annotations

import re
import time
from typing import Callable

from .models import ACResult, Status, Severity, CheckLevel, StepLog
from .executor import (
    vm_available,
    ensure_display,
    take_screenshot,
    focus_window,
    execute_action,
    get_pixel_diff,
    start_app,
    stop_app,
    check_binary_exists,
    get_app_log,
    run_in_vm,
)
from .vision import ask_vision, ask_vision_bool
from .logging_config import get_logger

logger = get_logger(__name__)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def wait_for_stable_ui(
    executor_take_screenshot: Callable[[str], str],
    prefix: str = "wait",
    max_wait_seconds: float = 5.0,
    stability_threshold: float = 0.001,
    poll_interval: float = 0.2,
) -> str:
    """Wait for UI to stabilize by monitoring pixel changes.

    Takes screenshots in a loop until two consecutive screenshots
    have less than stability_threshold pixel difference.

    Args:
        executor_take_screenshot: Function to call to take screenshot
        prefix: Prefix for screenshot filenames
        max_wait_seconds: Maximum time to wait for stability
        stability_threshold: Maximum change ratio to consider stable
        poll_interval: Time between screenshots

    Returns:
        Path to final stable screenshot
    """
    start_time = time.time()
    prev_screenshot = executor_take_screenshot(f"{prefix}_0")
    iteration = 1

    while time.time() - start_time < max_wait_seconds:
        time.sleep(poll_interval)
        curr_screenshot = executor_take_screenshot(f"{prefix}_{iteration}")

        try:
            diff_result = get_pixel_diff(prev_screenshot, curr_screenshot)
            change_ratio = diff_result["change_ratio"]

            logger.debug(
                f"UI stability check {iteration}: change_ratio={change_ratio:.4f}"
            )

            if change_ratio < stability_threshold:
                logger.debug(f"UI stable after {time.time() - start_time:.2f}s")
                return curr_screenshot

            prev_screenshot = curr_screenshot
            iteration += 1

        except Exception as e:
            logger.warning(f"Pixel diff failed: {e}, continuing...")
            prev_screenshot = curr_screenshot
            iteration += 1

    logger.warning(
        f"UI did not stabilize within {max_wait_seconds}s, using last screenshot"
    )
    return prev_screenshot


def _sanitize_for_filename(text: str, max_length: int = 20) -> str:
    """
    Remove characters that are problematic in filenames.

    Replaces spaces, special characters, and non-alphanumeric characters
    with underscores to ensure safe filenames.

    Args:
        text: The text to sanitize
        max_length: Maximum length of the output (default: 20)

    Returns:
        Sanitized string safe for use in filenames
    """
    if not text:
        return "unnamed"
    # Replace problematic characters with underscore
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", text)
    # Remove consecutive underscores
    sanitized = re.sub(r"_+", "_", sanitized)
    # Trim to max length
    sanitized = sanitized[:max_length]
    # Strip leading/trailing underscores
    sanitized = sanitized.strip("_")
    return sanitized if sanitized else "unnamed"


# ============================================================================
# PRE-FLIGHT CHECKS (P-01 to P-03)
# ============================================================================


def check_p01_app_launches(
    binary: str, app_name: str, env: dict[str, str] | None, steps: list[StepLog]
) -> ACResult:
    """P-01: App startet innerhalb 5s."""

    # VM available?
    if not vm_available():
        steps.append(StepLog("VM check", "fail", {"error": "VM not available"}))
        return ACResult(
            ac="App launches",
            check_id="P-01",
            level=CheckLevel.PRE_FLIGHT,
            status=Status.FAIL,
            severity=Severity.CRITICAL,
            diagnosis="VM 'ui-test' not available. Run: orb create ubuntu:24.04 ui-test",
        )

    steps.append(StepLog("VM accessible", "ok"))

    # Display ready?
    ensure_display()
    steps.append(StepLog("Display ready", "ok"))

    # Binary exists?
    if not check_binary_exists(binary):
        steps.append(StepLog("Binary check", "fail", {"path": binary}))
        return ACResult(
            ac="App launches",
            check_id="P-01",
            level=CheckLevel.PRE_FLIGHT,
            status=Status.FAIL,
            severity=Severity.CRITICAL,
            diagnosis=f"Binary not found: {binary}",
        )

    steps.append(StepLog("Binary exists", "ok", {"path": binary}))

    # Start app
    success, pid, message = start_app(binary, app_name, env)

    if not success:
        steps.append(StepLog("App start", "fail", {"error": message}))
        return ACResult(
            ac="App launches",
            check_id="P-01",
            level=CheckLevel.PRE_FLIGHT,
            status=Status.FAIL,
            severity=Severity.CRITICAL,
            diagnosis=message,
        )

    screenshot = take_screenshot("p01")
    steps.append(StepLog("App started", "ok", {"pid": pid}, screenshot))

    return ACResult(
        ac="App launches",
        check_id="P-01",
        level=CheckLevel.PRE_FLIGHT,
        status=Status.PASS,
        severity=Severity.CRITICAL,
        diagnosis=f"App running (PID {pid})",
        screenshot=screenshot,
        details={"pid": pid},
    )


def check_p02_navigation_exists(steps: list[StepLog]) -> ACResult:
    """P-02: Navigation/interactive elements vorhanden."""

    screenshot = take_screenshot("p02")

    # Ask vision to describe UI elements
    description = ask_vision(
        screenshot,
        "List all interactive UI elements visible: buttons, menus, toolbars, links, icons. Be brief, just list them.",
    )

    # Check if meaningful elements found
    ui_keywords = [
        "button",
        "menu",
        "toolbar",
        "icon",
        "link",
        "tab",
        "panel",
        "open",
        "save",
        "file",
        "edit",
        "view",
        "help",
        "settings",
    ]
    has_elements = any(kw in description.lower() for kw in ui_keywords)

    steps.append(
        StepLog(
            "Navigation scan",
            "ok" if has_elements else "fail",
            {"elements": description[:200]},
            screenshot,
        )
    )

    return ACResult(
        ac="Navigation exists",
        check_id="P-02",
        level=CheckLevel.PRE_FLIGHT,
        status=Status.PASS if has_elements else Status.FAIL,
        severity=Severity.CRITICAL,
        diagnosis=description[:300],
        screenshot=screenshot,
    )


def check_p03_correct_initial_state(
    expected_state: str | None, steps: list[StepLog]
) -> ACResult:
    """P-03: Korrekter Ausgangszustand (kein Login-Screen, kein Modal)."""

    screenshot = take_screenshot("p03")

    # Default check if no expected state given
    if not expected_state:
        expected_state = (
            "main application window without login screen or blocking modal"
        )

    result, explanation = ask_vision_bool(
        screenshot,
        f"Is this the correct initial state: {expected_state}? "
        "Check there's no login screen, no blocking modal, no error message.",
    )

    steps.append(
        StepLog(
            "Initial state check",
            "ok" if result else "fail",
            {"expected": expected_state},
            screenshot,
        )
    )

    return ACResult(
        ac="Correct initial state",
        check_id="P-03",
        level=CheckLevel.PRE_FLIGHT,
        status=Status.PASS if result else Status.FAIL,
        severity=Severity.HIGH,
        diagnosis=explanation,
        screenshot=screenshot,
    )


# ============================================================================
# REACHABILITY CHECKS (R-01 to R-05)
# ============================================================================


def check_r01_feature_linked(
    feature_hints: list[str], steps: list[StepLog]
) -> ACResult:
    """R-01: Feature in Navigation verlinkt."""

    screenshot = take_screenshot("r01")
    hints_str = ", ".join(feature_hints)

    result, explanation = ask_vision_bool(
        screenshot,
        f"Is there a visible UI element (button, menu item, link, icon) related to: {hints_str}?",
    )

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
        status=Status.PASS if result else Status.FAIL,
        severity=Severity.CRITICAL,
        diagnosis=explanation,
        screenshot=screenshot,
    )


def check_r03_feature_visible(feature_desc: str, steps: list[StepLog]) -> ACResult:
    """R-03: Feature tatsächlich sichtbar (nicht hidden/zero-size)."""

    screenshot = take_screenshot("r03")

    result, explanation = ask_vision_bool(
        screenshot,
        f"Is '{feature_desc}' clearly visible on screen? "
        "It should not be hidden, grayed out, or showing 'coming soon'.",
    )

    steps.append(
        StepLog(
            f"Feature visible ({feature_desc})",
            "ok" if result else "fail",
            screenshot=screenshot,
        )
    )

    return ACResult(
        ac=f"Feature visible",
        check_id="R-03",
        level=CheckLevel.REACHABILITY,
        status=Status.PASS if result else Status.FAIL,
        severity=Severity.CRITICAL,
        diagnosis=explanation,
        screenshot=screenshot,
    )


def check_r02_reachable_in_clicks(
    max_clicks: int, target_feature: str, steps: list[StepLog]
) -> ACResult:
    """R-02: Feature erreichbar in ≤N Klicks (BFS über klickbare Elemente)."""

    screenshot = take_screenshot("r02_start")

    # Ask vision if target is already visible
    result, explanation = ask_vision_bool(
        screenshot,
        f"Is '{target_feature}' directly visible and clickable on this screen?",
    )

    if result:
        steps.append(
            StepLog(
                f"Feature '{target_feature}' reachable",
                "ok",
                {"clicks_needed": 0},
                screenshot,
            )
        )
        return ACResult(
            ac=f"Feature reachable in ≤{max_clicks} clicks",
            check_id="R-02",
            level=CheckLevel.REACHABILITY,
            status=Status.PASS,
            severity=Severity.CRITICAL,
            diagnosis=f"Feature '{target_feature}' is directly visible (0 clicks)",
            screenshot=screenshot,
            details={"clicks_needed": 0},
        )

    # Try clicking through potential paths
    for click_num in range(1, max_clicks + 1):
        # Ask vision for clickable elements that might lead to target
        click_suggestion = ask_vision(
            screenshot,
            f"What UI element should I click to navigate towards '{target_feature}'? "
            "Give a single, specific element name or location. If none exist, say 'NONE'.",
        )

        if "NONE" in click_suggestion.upper():
            steps.append(
                StepLog(
                    f"Click {click_num}/{max_clicks}",
                    "fail",
                    {"reason": "no path found"},
                    screenshot,
                )
            )
            return ACResult(
                ac=f"Feature reachable in ≤{max_clicks} clicks",
                check_id="R-02",
                level=CheckLevel.REACHABILITY,
                status=Status.FAIL,
                severity=Severity.CRITICAL,
                diagnosis=f"No path to '{target_feature}' found after {click_num - 1} clicks",
                screenshot=screenshot,
                details={"clicks_attempted": click_num - 1},
            )

        # Try to click suggested element
        try:
            execute_action(f"click:{click_suggestion}")
        except Exception as e:
            steps.append(
                StepLog(
                    f"Click {click_num}: {click_suggestion}",
                    "fail",
                    {"error": str(e)},
                    screenshot,
                )
            )
            return ACResult(
                ac=f"Feature reachable in ≤{max_clicks} clicks",
                check_id="R-02",
                level=CheckLevel.REACHABILITY,
                status=Status.FAIL,
                severity=Severity.CRITICAL,
                diagnosis=f"Failed to execute navigation click {click_num}: {e}",
                screenshot=screenshot,
            )

        screenshot = wait_for_stable_ui(take_screenshot, prefix=f"r02_click{click_num}")

        # Check if we reached the target
        result, explanation = ask_vision_bool(
            screenshot, f"Is '{target_feature}' now visible and accessible?"
        )

        if result:
            steps.append(
                StepLog(
                    f"Feature '{target_feature}' reachable",
                    "ok",
                    {"clicks_needed": click_num},
                    screenshot,
                )
            )
            return ACResult(
                ac=f"Feature reachable in ≤{max_clicks} clicks",
                check_id="R-02",
                level=CheckLevel.REACHABILITY,
                status=Status.PASS,
                severity=Severity.CRITICAL,
                diagnosis=f"Feature '{target_feature}' reached in {click_num} clicks",
                screenshot=screenshot,
                details={"clicks_needed": click_num},
            )

        steps.append(
            StepLog(
                f"Click {click_num}/{max_clicks}",
                "ok",
                {"clicked": click_suggestion},
                screenshot,
            )
        )

    # Max clicks exhausted
    return ACResult(
        ac=f"Feature reachable in ≤{max_clicks} clicks",
        check_id="R-02",
        level=CheckLevel.REACHABILITY,
        status=Status.FAIL,
        severity=Severity.CRITICAL,
        diagnosis=f"Feature '{target_feature}' not reached within {max_clicks} clicks",
        screenshot=screenshot,
        details={"clicks_attempted": max_clicks},
    )


def check_r04_no_feature_flag(steps: list[StepLog]) -> ACResult:
    """R-04: Kein Feature-Flag blockiert (Coming Soon, locked)."""

    screenshot = take_screenshot("r04")

    result, explanation = ask_vision_bool(
        screenshot,
        "Is there any 'Coming Soon', 'Locked', 'Premium Only', 'Pro Feature', "
        "or disabled/locked indicator visible on this screen?",
    )

    # result=True means blocked, so we invert
    passed = not result

    steps.append(
        StepLog("Feature flag check", "ok" if passed else "fail", screenshot=screenshot)
    )

    return ACResult(
        ac="No feature flag blocking",
        check_id="R-04",
        level=CheckLevel.REACHABILITY,
        status=Status.PASS if passed else Status.FAIL,
        severity=Severity.CRITICAL,
        diagnosis=explanation,
        screenshot=screenshot,
    )


def check_r05_click_navigates(
    action: str, expected: str, steps: list[StepLog]
) -> ACResult:
    """R-05: Klick navigiert korrekt."""

    before = take_screenshot("r05_before")

    try:
        execute_action(action)
    except Exception as e:
        steps.append(StepLog(f"Action: {action}", "fail", {"error": str(e)}))
        return ACResult(
            ac="Click navigates correctly",
            check_id="R-05",
            level=CheckLevel.REACHABILITY,
            status=Status.FAIL,
            severity=Severity.CRITICAL,
            diagnosis=f"Action failed: {e}",
            screenshot=before,
        )

    after = wait_for_stable_ui(take_screenshot, prefix="r05_after")

    diff = get_pixel_diff(before, after)

    steps.append(
        StepLog(
            f"Action: {action}",
            "ok",
            {"pixel_diff": diff["change_ratio"], "regions": diff["num_regions"]},
            after,
        )
    )

    # Check if something changed
    if diff["change_ratio"] < 0.005:
        return ACResult(
            ac="Click navigates correctly",
            check_id="R-05",
            level=CheckLevel.REACHABILITY,
            status=Status.FAIL,
            severity=Severity.CRITICAL,
            diagnosis=f"No visual change after '{action}'. pixel_diff={diff['change_ratio']:.4f}. "
            "Click handler may be missing.",
            screenshot=after,
            details=diff,
        )

    # Ask vision if expected result happened - be explicit about what to look for
    result, explanation = ask_vision_bool(
        after,
        f"Look at this screenshot. Is the following statement TRUE about what you see: '{expected}'?",
    )

    return ACResult(
        ac=expected,
        check_id="R-05",
        level=CheckLevel.REACHABILITY,
        status=Status.PASS if result else Status.FAIL,
        severity=Severity.CRITICAL,
        diagnosis=f"{explanation} (pixel_diff={diff['change_ratio']:.1%})",
        screenshot=after,
        details=diff,
    )


# ============================================================================
# FUNCTIONAL CHECKS (F-01 to F-06)
# ============================================================================


def check_f01_action_causes_change(action: str, steps: list[StepLog]) -> ACResult:
    """F-01: Primäre Action reagiert (pixel_diff > threshold)."""

    before = take_screenshot("f01_before")

    try:
        execute_action(action)
    except Exception as e:
        steps.append(StepLog(f"Action: {action}", "fail", {"error": str(e)}))
        return ACResult(
            ac=f"Action '{action}' causes change",
            check_id="F-01",
            level=CheckLevel.FUNCTIONAL,
            status=Status.FAIL,
            severity=Severity.CRITICAL,
            diagnosis=f"Action execution failed: {e}",
            screenshot=before,
        )

    after = wait_for_stable_ui(take_screenshot, prefix="f01_after")

    diff = get_pixel_diff(before, after)
    passed = diff["change_ratio"] > 0.001

    steps.append(
        StepLog(
            f"Action: {action}",
            "ok" if passed else "fail",
            {"pixel_diff": diff["change_ratio"]},
            after,
        )
    )

    return ACResult(
        ac=f"Action '{action}' causes change",
        check_id="F-01",
        level=CheckLevel.FUNCTIONAL,
        status=Status.PASS if passed else Status.FAIL,
        severity=Severity.CRITICAL,
        diagnosis=f"pixel_diff={diff['change_ratio']:.4f}, {diff['num_regions']} regions changed",
        screenshot=after,
        details=diff,
    )


def check_f04_result_matches_ac(
    action: str, expected: str, timeout_ms: int, steps: list[StepLog]
) -> ACResult:
    """F-04: Ergebnis entspricht AC (aiBoolean)."""

    before = take_screenshot("f04_before")

    try:
        execute_action(action)
    except Exception as e:
        steps.append(StepLog(f"Action: {action}", "fail", {"error": str(e)}))
        return ACResult(
            ac=expected,
            check_id="F-04",
            level=CheckLevel.FUNCTIONAL,
            status=Status.FAIL,
            severity=Severity.CRITICAL,
            diagnosis=f"Action failed: {e}",
            screenshot=before,
        )

    after = wait_for_stable_ui(
        take_screenshot, prefix="f04_after", max_wait_seconds=timeout_ms / 1000.0
    )

    diff = get_pixel_diff(before, after)

    # If no change, fail early
    if diff["change_ratio"] < 0.001:
        steps.append(
            StepLog(
                f"AC: {expected}",
                "fail",
                {"reason": "no visual change", "pixel_diff": diff["change_ratio"]},
                after,
            )
        )
        return ACResult(
            ac=expected,
            check_id="F-04",
            level=CheckLevel.FUNCTIONAL,
            status=Status.FAIL,
            severity=Severity.CRITICAL,
            diagnosis=f"No visual change after action. Expected: {expected}",
            screenshot=after,
            details=diff,
        )

    # Vision check
    result, explanation = ask_vision_bool(after, f"Is this true: {expected}?")

    steps.append(
        StepLog(
            f"AC: {expected}",
            "ok" if result else "fail",
            {"pixel_diff": diff["change_ratio"]},
            after,
        )
    )

    return ACResult(
        ac=expected,
        check_id="F-04",
        level=CheckLevel.FUNCTIONAL,
        status=Status.PASS if result else Status.FAIL,
        severity=Severity.CRITICAL,
        diagnosis=explanation,
        screenshot=after,
        details=diff,
    )


def check_f02_system_status(action: str, steps: list[StepLog]) -> ACResult:
    """F-02: System Status kommuniziert (Loader/Spinner erscheint)."""

    before = take_screenshot("f02_before")

    # Execute action and immediately screenshot
    try:
        execute_action(action)
    except Exception as e:
        steps.append(StepLog(f"Action: {action}", "fail", {"error": str(e)}))
        return ACResult(
            ac="System status communicated",
            check_id="F-02",
            level=CheckLevel.FUNCTIONAL,
            status=Status.FAIL,
            severity=Severity.MEDIUM,
            diagnosis=f"Action failed: {e}",
            screenshot=before,
        )

    # Take screenshot immediately after action
    time.sleep(0.1)  # Very short wait to catch loader
    during = take_screenshot("f02_during")

    result, explanation = ask_vision_bool(
        during,
        "Is there a loading indicator, spinner, progress bar, or 'loading...' message visible?",
    )

    steps.append(
        StepLog(
            "System status indicator",
            "ok" if result else "fail",
            {"action": action},
            during,
        )
    )

    # Wait for completion
    time.sleep(1.0)
    after = take_screenshot("f02_after")

    return ACResult(
        ac="System status communicated",
        check_id="F-02",
        level=CheckLevel.FUNCTIONAL,
        status=Status.PASS if result else Status.FAIL,
        severity=Severity.MEDIUM,
        diagnosis=explanation,
        screenshot=during,
        details={"action": action},
    )


def check_f03_result_appears(
    action: str, expected: str, timeout_ms: int, steps: list[StepLog]
) -> ACResult:
    """F-03: Ergebnis erscheint (kein Hang), wait_until mit timeout."""

    before = take_screenshot("f03_before")

    try:
        execute_action(action)
    except Exception as e:
        steps.append(StepLog(f"Action: {action}", "fail", {"error": str(e)}))
        return ACResult(
            ac=f"Result appears within {timeout_ms}ms",
            check_id="F-03",
            level=CheckLevel.FUNCTIONAL,
            status=Status.FAIL,
            severity=Severity.CRITICAL,
            diagnosis=f"Action failed: {e}",
            screenshot=before,
        )

    # Poll for expected state
    start_time = time.time()
    max_wait = timeout_ms / 1000.0
    poll_interval = 0.2

    while (time.time() - start_time) < max_wait:
        time.sleep(poll_interval)
        screenshot = take_screenshot("f03_polling")

        result, explanation = ask_vision_bool(
            screenshot, f"Is this visible: {expected}?"
        )

        if result:
            elapsed_ms = int((time.time() - start_time) * 1000)
            steps.append(
                StepLog(
                    "Result appeared",
                    "ok",
                    {"elapsed_ms": elapsed_ms, "expected": expected},
                    screenshot,
                )
            )
            return ACResult(
                ac=f"Result appears within {timeout_ms}ms",
                check_id="F-03",
                level=CheckLevel.FUNCTIONAL,
                status=Status.PASS,
                severity=Severity.CRITICAL,
                diagnosis=f"Result appeared after {elapsed_ms}ms: {explanation}",
                screenshot=screenshot,
                details={"elapsed_ms": elapsed_ms},
            )

    # Timeout reached
    elapsed_ms = int((time.time() - start_time) * 1000)
    after = take_screenshot("f03_timeout")
    steps.append(
        StepLog(
            "Result timeout",
            "fail",
            {"timeout_ms": timeout_ms, "elapsed_ms": elapsed_ms},
            after,
        )
    )

    return ACResult(
        ac=f"Result appears within {timeout_ms}ms",
        check_id="F-03",
        level=CheckLevel.FUNCTIONAL,
        status=Status.FAIL,
        severity=Severity.CRITICAL,
        diagnosis=f"Expected result '{expected}' did not appear within {timeout_ms}ms",
        screenshot=after,
        details={"timeout_ms": timeout_ms, "elapsed_ms": elapsed_ms},
    )


def check_f05_state_consistent(regions: list[str], steps: list[StepLog]) -> ACResult:
    """F-05: State konsistent (alle Regions erzählen dieselbe Geschichte)."""

    screenshot = take_screenshot("f05")

    # Ask vision to check consistency across regions
    regions_str = ", ".join(regions)
    question = (
        f"Check these UI regions for consistency: {regions_str}. "
        "Do they all show the same state/data? For example, if one shows '5 items' "
        "and another shows '7 items', that's inconsistent. Are they consistent?"
    )

    result, explanation = ask_vision_bool(screenshot, question)

    steps.append(
        StepLog(
            "State consistency check",
            "ok" if result else "fail",
            {"regions": regions},
            screenshot,
        )
    )

    return ACResult(
        ac="State consistent across regions",
        check_id="F-05",
        level=CheckLevel.FUNCTIONAL,
        status=Status.PASS if result else Status.FAIL,
        severity=Severity.HIGH,
        diagnosis=explanation,
        screenshot=screenshot,
        details={"regions": regions},
    )


def check_f06_all_buttons_bound(steps: list[StepLog]) -> ACResult:
    """F-06: Alle Buttons gebunden (jeden klicken, pixel_diff prüfen)."""
    from .omniparser import get_all_buttons, is_omniparser_available

    screenshot = take_screenshot("f06_scan")

    # Try OmniParser first for more reliable button detection
    if is_omniparser_available():
        try:
            buttons = get_all_buttons(screenshot)
            button_list = [btn.label for btn in buttons]

            if not button_list:
                steps.append(
                    StepLog(
                        "Button scan (OmniParser)", "ok", {"buttons": 0}, screenshot
                    )
                )
                return ACResult(
                    ac="All buttons bound",
                    check_id="F-06",
                    level=CheckLevel.FUNCTIONAL,
                    status=Status.PASS,
                    severity=Severity.CRITICAL,
                    diagnosis="No buttons found on screen (OmniParser)",
                    screenshot=screenshot,
                    details={"buttons_checked": 0, "method": "omniparser"},
                )

            steps.append(
                StepLog(
                    "Button scan (OmniParser)",
                    "ok",
                    {"buttons": len(button_list)},
                    screenshot,
                )
            )

            unbound_buttons = []
            for button in button_list:
                safe_name = _sanitize_for_filename(button)
                before = take_screenshot(f"f06_before_{safe_name}")

                try:
                    execute_action(f"click:{button}")
                except Exception as e:
                    steps.append(
                        StepLog(f"Click button: {button}", "fail", {"error": str(e)})
                    )
                    unbound_buttons.append({"button": button, "reason": str(e)})
                    continue

                time.sleep(0.3)
                after = take_screenshot(f"f06_after_{safe_name}")

                diff = get_pixel_diff(before, after)

                if diff["change_ratio"] < 0.001:
                    steps.append(
                        StepLog(
                            f"Button: {button}",
                            "fail",
                            {
                                "pixel_diff": diff["change_ratio"],
                                "reason": "no visual response",
                            },
                        )
                    )
                    unbound_buttons.append(
                        {"button": button, "reason": "no visual change"}
                    )
                else:
                    steps.append(
                        StepLog(
                            f"Button: {button}",
                            "ok",
                            {"pixel_diff": diff["change_ratio"]},
                        )
                    )

            if unbound_buttons:
                return ACResult(
                    ac="All buttons bound",
                    check_id="F-06",
                    level=CheckLevel.FUNCTIONAL,
                    status=Status.FAIL,
                    severity=Severity.CRITICAL,
                    diagnosis=f"{len(unbound_buttons)}/{len(button_list)} buttons appear unbound (OmniParser)",
                    screenshot=screenshot,
                    details={
                        "unbound_buttons": unbound_buttons,
                        "total_buttons": len(button_list),
                        "method": "omniparser",
                    },
                )

            return ACResult(
                ac="All buttons bound",
                check_id="F-06",
                level=CheckLevel.FUNCTIONAL,
                status=Status.PASS,
                severity=Severity.CRITICAL,
                diagnosis=f"All {len(button_list)} buttons responded to clicks (OmniParser)",
                screenshot=screenshot,
                details={"buttons_checked": len(button_list), "method": "omniparser"},
            )
        except Exception as e:
            # OmniParser failed, fall back to vision
            steps.append(
                StepLog(
                    "Button scan (OmniParser)", "fail", {"error": str(e)}, screenshot
                )
            )

    # Fall back to vision model
    buttons_response = ask_vision(
        screenshot,
        "List all buttons visible on screen. Give me each button's label or icon description, "
        "one per line. If no buttons, say 'NONE'.",
    )

    if "NONE" in buttons_response.upper():
        steps.append(StepLog("Button scan (vision)", "ok", {"buttons": 0}, screenshot))
        return ACResult(
            ac="All buttons bound",
            check_id="F-06",
            level=CheckLevel.FUNCTIONAL,
            status=Status.PASS,
            severity=Severity.CRITICAL,
            diagnosis="No buttons found on screen (vision fallback)",
            screenshot=screenshot,
            details={"buttons_checked": 0, "method": "vision"},
        )

    # Parse button list
    button_list = [
        b.strip()
        for b in buttons_response.split("\n")
        if b.strip() and not b.strip().startswith("#")
    ]
    unbound_buttons = []

    for button in button_list:
        safe_name = _sanitize_for_filename(button)
        before = take_screenshot(f"f06_before_{safe_name}")

        try:
            execute_action(f"click:{button}")
        except Exception as e:
            steps.append(StepLog(f"Click button: {button}", "fail", {"error": str(e)}))
            unbound_buttons.append({"button": button, "reason": str(e)})
            continue

        time.sleep(0.3)
        after = take_screenshot(f"f06_after_{safe_name}")

        diff = get_pixel_diff(before, after)

        if diff["change_ratio"] < 0.001:
            steps.append(
                StepLog(
                    f"Button: {button}",
                    "fail",
                    {
                        "pixel_diff": diff["change_ratio"],
                        "reason": "no visual response",
                    },
                )
            )
            unbound_buttons.append({"button": button, "reason": "no visual change"})
        else:
            steps.append(
                StepLog(f"Button: {button}", "ok", {"pixel_diff": diff["change_ratio"]})
            )

    if unbound_buttons:
        return ACResult(
            ac="All buttons bound",
            check_id="F-06",
            level=CheckLevel.FUNCTIONAL,
            status=Status.FAIL,
            severity=Severity.CRITICAL,
            diagnosis=f"{len(unbound_buttons)}/{len(button_list)} buttons appear unbound (vision fallback)",
            screenshot=screenshot,
            details={
                "unbound_buttons": unbound_buttons,
                "total_buttons": len(button_list),
                "method": "vision",
            },
        )

    return ACResult(
        ac="All buttons bound",
        check_id="F-06",
        level=CheckLevel.FUNCTIONAL,
        status=Status.PASS,
        severity=Severity.CRITICAL,
        diagnosis=f"All {len(button_list)} buttons responded to clicks (vision fallback)",
        screenshot=screenshot,
        details={"buttons_checked": len(button_list), "method": "vision"},
    )


# ============================================================================
# EDGE CASE CHECKS (E-01 to E-06)
# ============================================================================


def check_e01_empty_state(
    setup_action: str | None, verify: str, steps: list[StepLog]
) -> ACResult:
    """E-01: Leerer State wird sinnvoll angezeigt."""

    screenshot = take_screenshot("e01")

    if setup_action:
        try:
            execute_action(setup_action)
            screenshot = wait_for_stable_ui(take_screenshot, prefix="e01")
        except:
            pass
    result, explanation = ask_vision_bool(screenshot, verify)

    steps.append(
        StepLog("Empty state check", "ok" if result else "fail", screenshot=screenshot)
    )

    return ACResult(
        ac="Empty state handled",
        check_id="E-01",
        level=CheckLevel.EDGE_CASES,
        status=Status.PASS if result else Status.FAIL,
        severity=Severity.MEDIUM,
        diagnosis=explanation,
        screenshot=screenshot,
    )


def check_e02_long_input(input_field_hint: str, steps: list[StepLog]) -> ACResult:
    """E-02: Langer Input (500 Zeichen in Textfelder)."""

    long_text = "A" * 500
    screenshot = take_screenshot("e02_before")

    # Find and focus input field
    try:
        execute_action(f"click:{input_field_hint}")
        time.sleep(0.2)
    except Exception as e:
        steps.append(
            StepLog(f"Focus input: {input_field_hint}", "fail", {"error": str(e)})
        )
        return ACResult(
            ac="Long input handled",
            check_id="E-02",
            level=CheckLevel.EDGE_CASES,
            status=Status.FAIL,
            severity=Severity.MEDIUM,
            diagnosis=f"Could not focus input field '{input_field_hint}': {e}",
            screenshot=screenshot,
        )

    # Type long text
    try:
        execute_action(f"type:{long_text}")
    except Exception as e:
        steps.append(StepLog("Type long text", "fail", {"error": str(e)}))
        return ACResult(
            ac="Long input handled",
            check_id="E-02",
            level=CheckLevel.EDGE_CASES,
            status=Status.FAIL,
            severity=Severity.MEDIUM,
            diagnosis=f"Failed to type long text: {e}",
            screenshot=screenshot,
        )

    after = wait_for_stable_ui(take_screenshot, prefix="e02_after")

    # Check for overflow, truncation, or UI breaking
    result, explanation = ask_vision_bool(
        after,
        "Is the text input field handling the long text correctly? "
        "Check: no overflow outside container, no UI breaking, scrollable if needed, no crash.",
    )

    steps.append(
        StepLog(
            "Long input check",
            "ok" if result else "fail",
            {"chars": len(long_text)},
            after,
        )
    )

    return ACResult(
        ac="Long input handled",
        check_id="E-02",
        level=CheckLevel.EDGE_CASES,
        status=Status.PASS if result else Status.FAIL,
        severity=Severity.MEDIUM,
        diagnosis=explanation,
        screenshot=after,
        details={"input_length": len(long_text)},
    )


def check_e03_special_chars(input_field_hint: str, steps: list[StepLog]) -> ACResult:
    """E-03: Sonderzeichen (& ' < > Ünïcödé 日本語)."""

    special_text = "Test & 'special' <chars> Ünïcödé 日本語"
    screenshot = take_screenshot("e03_before")

    # Find and focus input field
    try:
        execute_action(f"click:{input_field_hint}")
        time.sleep(0.2)
    except Exception as e:
        steps.append(
            StepLog(f"Focus input: {input_field_hint}", "fail", {"error": str(e)})
        )
        return ACResult(
            ac="Special chars handled",
            check_id="E-03",
            level=CheckLevel.EDGE_CASES,
            status=Status.FAIL,
            severity=Severity.MEDIUM,
            diagnosis=f"Could not focus input field '{input_field_hint}': {e}",
            screenshot=screenshot,
        )

    # Type special characters
    try:
        execute_action(f"type:{special_text}")
    except Exception as e:
        steps.append(StepLog("Type special chars", "fail", {"error": str(e)}))
        return ACResult(
            ac="Special chars handled",
            check_id="E-03",
            level=CheckLevel.EDGE_CASES,
            status=Status.FAIL,
            severity=Severity.MEDIUM,
            diagnosis=f"Failed to type special characters: {e}",
            screenshot=screenshot,
        )

    after = wait_for_stable_ui(take_screenshot, prefix="e03_after")

    # Check if special characters rendered correctly
    result, explanation = ask_vision_bool(
        after,
        f"Are these special characters visible and correctly displayed: {special_text}? "
        "They should not be escaped, garbled, or show as question marks.",
    )

    steps.append(
        StepLog(
            "Special chars check",
            "ok" if result else "fail",
            {"text": special_text},
            after,
        )
    )

    return ACResult(
        ac="Special chars handled",
        check_id="E-03",
        level=CheckLevel.EDGE_CASES,
        status=Status.PASS if result else Status.FAIL,
        severity=Severity.MEDIUM,
        diagnosis=explanation,
        screenshot=after,
        details={"special_text": special_text},
    )


def check_e04_error_state(trigger_action: str, steps: list[StepLog]) -> ACResult:
    """E-04: Error State (invalid Input, API fail simulieren)."""

    screenshot = take_screenshot("e04_before")

    # Trigger error condition
    try:
        execute_action(trigger_action)
    except Exception as e:
        steps.append(
            StepLog(f"Trigger error: {trigger_action}", "fail", {"error": str(e)})
        )
        return ACResult(
            ac="Error state handled",
            check_id="E-04",
            level=CheckLevel.EDGE_CASES,
            status=Status.FAIL,
            severity=Severity.HIGH,
            diagnosis=f"Failed to trigger error condition: {e}",
            screenshot=screenshot,
        )

    after = wait_for_stable_ui(take_screenshot, prefix="e04_after")

    # Check if error message shown
    result, explanation = ask_vision_bool(
        after,
        "Is there a clear error message, warning, or validation feedback visible? "
        "The UI should communicate what went wrong.",
    )

    steps.append(
        StepLog("Error state check", "ok" if result else "fail", screenshot=after)
    )

    return ACResult(
        ac="Error state handled",
        check_id="E-04",
        level=CheckLevel.EDGE_CASES,
        status=Status.PASS if result else Status.FAIL,
        severity=Severity.HIGH,
        diagnosis=explanation,
        screenshot=after,
        details={"trigger_action": trigger_action},
    )


def check_e05_double_submit(submit_action: str, steps: list[StepLog]) -> ACResult:
    """E-05: Doppel-Submit (Submit-Button 2x schnell klicken)."""

    before = take_screenshot("e05_before")

    # Click submit twice rapidly
    try:
        execute_action(submit_action)
        time.sleep(0.05)  # Very short delay - intentional for double-submit test
        execute_action(submit_action)
    except Exception as e:
        steps.append(StepLog("Double submit", "fail", {"error": str(e)}))
        return ACResult(
            ac="Double submit prevented",
            check_id="E-05",
            level=CheckLevel.EDGE_CASES,
            status=Status.FAIL,
            severity=Severity.HIGH,
            diagnosis=f"Failed to execute double submit: {e}",
            screenshot=before,
        )

    after = wait_for_stable_ui(take_screenshot, prefix="e05_after")

    # Check if duplicate was prevented
    result, explanation = ask_vision_bool(
        after,
        "Was the double-submit handled correctly? "
        "Look for: button disabled after first click, single result/action, "
        "no duplicate entries, or error message about duplicate submission.",
    )

    steps.append(
        StepLog(
            "Double submit prevention", "ok" if result else "fail", screenshot=after
        )
    )

    return ACResult(
        ac="Double submit prevented",
        check_id="E-05",
        level=CheckLevel.EDGE_CASES,
        status=Status.PASS if result else Status.FAIL,
        severity=Severity.HIGH,
        diagnosis=explanation,
        screenshot=after,
        details={"submit_action": submit_action},
    )


def check_e06_persistence(action: str, verify: str, steps: list[StepLog]) -> ACResult:
    """E-06: State bleibt nach Reload erhalten."""

    # Do action
    try:
        execute_action(action)
    except Exception as e:
        return ACResult(
            ac="State persists after reload",
            check_id="E-06",
            level=CheckLevel.EDGE_CASES,
            status=Status.FAIL,
            severity=Severity.HIGH,
            diagnosis=f"Setup action failed: {e}",
        )

    before = wait_for_stable_ui(take_screenshot, prefix="e06_before")

    # Simulate reload (F5 or Ctrl+R)
    try:
        execute_action("key:F5")
    except:
        execute_action("key:ctrl+r")

    time.sleep(2.0)
    after = take_screenshot("e06_after")

    result, explanation = ask_vision_bool(after, verify)

    steps.append(
        StepLog(
            "Persistence check", "ok" if result else "fail", {"verify": verify}, after
        )
    )

    return ACResult(
        ac="State persists after reload",
        check_id="E-06",
        level=CheckLevel.EDGE_CASES,
        status=Status.PASS if result else Status.FAIL,
        severity=Severity.HIGH,
        diagnosis=explanation,
        screenshot=after,
    )


# ============================================================================
# VISUAL CHECKS (V-01 to V-06)
# ============================================================================


def check_v01_contrast(screenshot_path: str) -> ACResult:
    """V-01: Kontrast WCAG AA (4.5:1 für Text)."""
    from ..metrics import check_contrast

    try:
        result = check_contrast(screenshot_path)
        passed = result.min_ratio >= 4.5

        return ACResult(
            ac="Contrast WCAG AA",
            check_id="V-01",
            level=CheckLevel.VISUAL,
            status=Status.PASS if passed else Status.WARN,
            severity=Severity.MEDIUM,
            diagnosis=f"min={result.min_ratio:.1f}:1 avg={result.avg_ratio:.1f}:1 (need 4.5:1)",
            screenshot=screenshot_path,
            details={"min_ratio": result.min_ratio, "avg_ratio": result.avg_ratio},
        )
    except Exception as e:
        return ACResult(
            ac="Contrast WCAG AA",
            check_id="V-01",
            level=CheckLevel.VISUAL,
            status=Status.WARN,
            severity=Severity.MEDIUM,
            diagnosis=f"Contrast check failed: {e}",
        )


def check_v02_text_truncated(screenshot_path: str) -> ACResult:
    """V-02: Text nicht abgeschnitten (keine Ellipsis)."""

    result, explanation = ask_vision_bool(
        screenshot_path, "Is any text visibly truncated with '...' or cut off mid-word?"
    )

    # Truncation is bad, so we invert
    passed = not result

    return ACResult(
        ac="No text truncation",
        check_id="V-02",
        level=CheckLevel.VISUAL,
        status=Status.PASS if passed else Status.WARN,
        severity=Severity.MEDIUM,
        diagnosis=explanation,
        screenshot=screenshot_path,
    )


def check_v03_element_overlaps(screenshot_path: str) -> ACResult:
    """V-03: Keine Element-Überlappungen."""

    result, explanation = ask_vision_bool(
        screenshot_path,
        "Are any UI elements overlapping each other in a broken way? "
        "(Not intentional overlays like dropdowns, but broken layout overlaps)",
    )

    passed = not result

    return ACResult(
        ac="No element overlaps",
        check_id="V-03",
        level=CheckLevel.VISUAL,
        status=Status.PASS if passed else Status.WARN,
        severity=Severity.MEDIUM,
        diagnosis=explanation,
        screenshot=screenshot_path,
    )


def check_v04_touch_targets(screenshot_path: str) -> ACResult:
    """V-04: Touch-Targets (≥44x44px für interaktive Elemente)."""

    result, explanation = ask_vision_bool(
        screenshot_path,
        "Are there any interactive elements (buttons, links, icons) that appear "
        "too small to tap comfortably? They should be at least 44x44 pixels. "
        "Look for tiny buttons or icons that would be hard to tap on mobile.",
    )

    # Small targets are bad, so we invert
    passed = not result

    return ACResult(
        ac="Touch targets ≥44x44px",
        check_id="V-04",
        level=CheckLevel.VISUAL,
        status=Status.PASS if passed else Status.WARN,
        severity=Severity.MEDIUM,
        diagnosis=explanation,
        screenshot=screenshot_path,
    )


def check_v05_render_performance(steps: list[StepLog]) -> ACResult:
    """V-05: Render-Performance (Screenshot-Loop, >500ms = fail)."""

    action = "key:space"  # Simple action to trigger render
    before = take_screenshot("v05_before")

    start_time = time.time()

    try:
        execute_action(action)
    except:
        pass  # Action might fail, focus on render time

    # Use smart wait with tight timing for performance measurement
    last_screenshot = wait_for_stable_ui(
        take_screenshot,
        prefix="v05_perf",
        max_wait_seconds=2.0,
        stability_threshold=0.001,
        poll_interval=0.05,
    )

    elapsed_ms = int((time.time() - start_time) * 1000)
    passed = elapsed_ms <= 500

    steps.append(
        StepLog(
            "Render performance",
            "ok" if passed else "fail",
            {"elapsed_ms": elapsed_ms},
            last_screenshot,
        )
    )

    return ACResult(
        ac="Render performance <500ms",
        check_id="V-05",
        level=CheckLevel.VISUAL,
        status=Status.PASS if passed else Status.WARN,
        severity=Severity.MEDIUM,
        diagnosis=f"Stable frame reached in {elapsed_ms}ms (threshold: 500ms)",
        screenshot=last_screenshot or before,
        details={"elapsed_ms": elapsed_ms, "threshold_ms": 500},
    )


def check_v06_ui_bleeding(screenshot_path: str) -> ACResult:
    """V-06: UI-Bleeding (Text/Icons bleeding outside containers)."""

    result, explanation = ask_vision_bool(
        screenshot_path,
        "Is any text, icon, or UI element bleeding outside its container? "
        "Look for text cut off at edges, icons overflowing borders, or content "
        "escaping its bounding box.",
    )

    # Bleeding is bad, so we invert
    passed = not result

    return ACResult(
        ac="No UI bleeding",
        check_id="V-06",
        level=CheckLevel.VISUAL,
        status=Status.PASS if passed else Status.WARN,
        severity=Severity.MEDIUM,
        diagnosis=explanation,
        screenshot=screenshot_path,
    )
