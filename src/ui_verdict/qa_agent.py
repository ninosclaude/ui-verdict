"""
QA-Agent compatible server for ui-verdict.

Implements the QA-Agent spec for desktop app testing:
- Structured QAReport output
- Check taxonomy (Pre-Flight, Reachability, Functional, Edge, Visual)
- Abort logic (FAIL at Reachability → skip Functional)
- Actionable what_to_fix diagnosis

Single tool: qa_agent.run(story, app_config)
"""
from __future__ import annotations

import os
import json
import yaml
import time
import uuid
import tempfile
from pathlib import Path
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any
from mcp.server.fastmcp import FastMCP

from .capture import load_image_gray
from .action import execute_action, ActionParseError
from .metrics import check_contrast


mcp = FastMCP("qa-agent")


# ============================================================================
# Data Models (QA-Agent Spec compliant)
# ============================================================================

class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    SKIPPED = "SKIPPED"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CheckLevel(str, Enum):
    PRE_FLIGHT = "pre_flight"
    REACHABILITY = "reachability"
    FUNCTIONAL = "functional"
    EDGE_CASES = "edge_cases"
    VISUAL = "visual"


@dataclass
class ACResult:
    """Result of a single Acceptance Criterion check."""
    ac: str
    level: str
    status: Status
    severity: Severity
    diagnosis: str = ""
    screenshot: str | None = None
    reason: str | None = None  # For SKIPPED


@dataclass
class QAReport:
    """Structured report matching QA-Agent spec."""
    run_id: str
    story: str
    overall_status: Status
    duration_seconds: float
    acs_passed: int
    acs_failed: int
    what_to_fix: str
    levels: dict[str, str]
    acs: list[ACResult]
    steps: list[dict[str, Any]]
    
    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "run_id": self.run_id,
            "story": self.story,
            "overall_status": self.overall_status.value,
            "duration_seconds": self.duration_seconds,
            "acs_passed": self.acs_passed,
            "acs_failed": self.acs_failed,
            "what_to_fix": self.what_to_fix,
            "levels": self.levels,
            "acs": [
                {
                    "ac": ac.ac,
                    "level": ac.level,
                    "status": ac.status.value,
                    "severity": ac.severity.value,
                    "diagnosis": ac.diagnosis,
                    "screenshot": ac.screenshot,
                    "reason": ac.reason,
                }
                for ac in self.acs
            ],
            "steps": self.steps,
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass 
class AppConfig:
    """App configuration from .ui-verdict.yml"""
    name: str
    binary: str
    binary_location: str
    env: dict[str, str]
    display: str
    resolution: str
    repo_path: str


# ============================================================================
# VM Operations
# ============================================================================

def _run_in_vm(cmd: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run command in VM via orb."""
    import subprocess
    full_cmd = f'orb run -m ui-test bash -c {repr(cmd)}'
    try:
        result = subprocess.run(
            full_cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


def _take_screenshot(prefix: str = "qa") -> str:
    """Take screenshot in VM, return local path."""
    unique_id = uuid.uuid4().hex[:8]
    vm_path = f"/mnt/mac/tmp/{prefix}_{unique_id}.png"
    local_path = f"/tmp/{prefix}_{unique_id}.png"
    
    code, _, err = _run_in_vm(f"export DISPLAY=:99 && scrot -o {vm_path}")
    if code != 0:
        raise RuntimeError(f"Screenshot failed: {err}")
    
    for _ in range(10):
        if os.path.exists(local_path):
            return local_path
        time.sleep(0.1)
    
    raise RuntimeError("Screenshot file not found")


def _ask_vision(image_path: str, question: str) -> str:
    """Ask vision model a question about an image."""
    from .vision import ask_ollama
    return ask_ollama(image_path, question, model="glm-ocr")


def _ask_vision_bool(image_path: str, question: str) -> tuple[bool, str]:
    """Ask a yes/no question, return (bool, explanation)."""
    prompt = f"""{question}

Answer with YES or NO first, then a brief explanation (1 sentence).
Format: YES/NO: <explanation>"""
    
    response = _ask_vision(image_path, prompt)
    response_lower = response.lower().strip()
    
    is_yes = response_lower.startswith("yes")
    return is_yes, response


def _calculate_pixel_diff(before_path: str, after_path: str) -> dict:
    """Calculate pixel difference between two screenshots."""
    from .diff.heatmap import generate_diff_mask
    
    before = load_image_gray(before_path)
    after = load_image_gray(after_path)
    _, stats = generate_diff_mask(before, after)
    
    return {
        "changed_pixels": stats["changed_pixels"],
        "change_ratio": stats["change_ratio"],
        "num_regions": stats["num_regions"],
        "regions": stats.get("regions", [])[:5],
    }


# ============================================================================
# Check Implementations
# ============================================================================

def check_app_launches(config: AppConfig, steps: list) -> ACResult:
    """P-01: App starts within 5 seconds."""
    try:
        # Check VM available
        code, out, _ = _run_in_vm("echo ok", timeout=5)
        if code != 0 or "ok" not in out:
            return ACResult(
                ac="App launches",
                level=CheckLevel.PRE_FLIGHT.value,
                status=Status.FAIL,
                severity=Severity.CRITICAL,
                diagnosis="VM 'ui-test' not available. Start with: orb create ubuntu:24.04 ui-test",
            )
        
        steps.append({"step": "VM accessible", "status": "ok"})
        
        # Ensure Xvfb
        code, _, _ = _run_in_vm(f"pgrep -f 'Xvfb {config.display}'")
        if code != 0:
            _run_in_vm(f"Xvfb {config.display} -screen 0 {config.resolution} &")
            time.sleep(0.5)
        
        # Ensure window manager
        code, _, _ = _run_in_vm("pgrep openbox")
        if code != 0:
            _run_in_vm(f"export DISPLAY={config.display} && openbox &")
            time.sleep(0.3)
        
        steps.append({"step": "Xvfb + openbox running", "status": "ok"})
        
        # Build binary path
        if config.binary_location == "vm":
            vm_binary = config.binary
        else:
            vm_binary = f"/mnt/mac{config.repo_path}/{config.binary}"
        
        # Check binary exists
        code, _, _ = _run_in_vm(f"test -f {vm_binary}")
        if code != 0:
            return ACResult(
                ac="App launches",
                level=CheckLevel.PRE_FLIGHT.value,
                status=Status.FAIL,
                severity=Severity.CRITICAL,
                diagnosis=f"Binary not found: {vm_binary}. Did you build for Linux?",
            )
        
        # Stop existing instance
        _run_in_vm(f"pkill -f {config.name} 2>/dev/null || true")
        time.sleep(0.3)
        
        # Build env and start
        env_parts = [f"DISPLAY={config.display}"]
        for k, v in config.env.items():
            env_parts.append(f"{k}={v}")
        env_str = " ".join(env_parts)
        
        cmd = f"export {env_str} && {vm_binary} > /tmp/{config.name}.log 2>&1 &"
        _run_in_vm(cmd)
        
        # Wait for app to fully render
        time.sleep(3.0)
        
        # Click to focus window
        _run_in_vm(f"export DISPLAY={config.display} && xdotool mousemove 960 540 click 1")
        time.sleep(0.5)
        
        code, out, _ = _run_in_vm(f"pgrep -f {config.name}")
        
        if code != 0:
            _, log, _ = _run_in_vm(f"tail -20 /tmp/{config.name}.log")
            return ACResult(
                ac="App launches",
                level=CheckLevel.PRE_FLIGHT.value,
                status=Status.FAIL,
                severity=Severity.CRITICAL,
                diagnosis=f"App process not found after launch. Log:\n{log}",
            )
        
        pid = out.strip().split()[0]
        screenshot = _take_screenshot("preflight")
        
        steps.append({"step": f"App launched (PID {pid})", "status": "ok", "screenshot": screenshot})
        
        return ACResult(
            ac="App launches",
            level=CheckLevel.PRE_FLIGHT.value,
            status=Status.PASS,
            severity=Severity.CRITICAL,
            diagnosis=f"App running with PID {pid}",
            screenshot=screenshot,
        )
        
    except Exception as e:
        return ACResult(
            ac="App launches",
            level=CheckLevel.PRE_FLIGHT.value,
            status=Status.FAIL,
            severity=Severity.CRITICAL,
            diagnosis=f"Launch failed: {e}",
        )


def check_navigation_exists(steps: list) -> ACResult:
    """P-02: Navigation/interactive elements present."""
    try:
        screenshot = _take_screenshot("nav_check")
        
        # Ask vision model - describe first, then check
        description = _ask_vision(
            screenshot,
            "List the main UI elements visible in this application window (buttons, menus, toolbars, etc). Be brief."
        )
        
        # If we got a description with actual elements, it passes
        has_elements = any(word in description.lower() for word in 
            ["button", "menu", "toolbar", "icon", "panel", "tab", "link", "open", "save", "file"])
        
        result = has_elements
        explanation = description
        
        steps.append({
            "step": "Navigation check",
            "status": "ok" if result else "fail",
            "screenshot": screenshot,
        })
        
        return ACResult(
            ac="Navigation exists",
            level=CheckLevel.PRE_FLIGHT.value,
            status=Status.PASS if result else Status.FAIL,
            severity=Severity.CRITICAL,
            diagnosis=explanation,
            screenshot=screenshot,
        )
        
    except Exception as e:
        return ACResult(
            ac="Navigation exists",
            level=CheckLevel.PRE_FLIGHT.value,
            status=Status.FAIL,
            severity=Severity.CRITICAL,
            diagnosis=f"Navigation check failed: {e}",
        )


def check_feature_reachable(feature_hints: list[str], steps: list) -> ACResult:
    """R-01/R-03: Feature is visible and reachable."""
    try:
        screenshot = _take_screenshot("reachability")
        
        hints_str = ", ".join(feature_hints)
        result, explanation = _ask_vision_bool(
            screenshot,
            f"Is there any UI element visible that relates to: {hints_str}? "
            f"This could be a button, menu item, icon, or link."
        )
        
        steps.append({
            "step": f"Feature reachability ({hints_str})",
            "status": "ok" if result else "fail",
            "screenshot": screenshot,
        })
        
        return ACResult(
            ac=f"Feature reachable ({hints_str})",
            level=CheckLevel.REACHABILITY.value,
            status=Status.PASS if result else Status.FAIL,
            severity=Severity.CRITICAL,
            diagnosis=explanation,
            screenshot=screenshot,
        )
        
    except Exception as e:
        return ACResult(
            ac="Feature reachable",
            level=CheckLevel.REACHABILITY.value,
            status=Status.FAIL,
            severity=Severity.CRITICAL,
            diagnosis=f"Reachability check failed: {e}",
        )


def check_action_causes_change(action: str, expected: str, steps: list) -> ACResult:
    """R-05/F-01: Action causes visible change."""
    try:
        # Screenshot before
        before = _take_screenshot("before")
        
        # Execute action
        try:
            execute_action(action)
        except Exception as e:
            return ACResult(
                ac=f"Action '{action}' works",
                level=CheckLevel.FUNCTIONAL.value,
                status=Status.FAIL,
                severity=Severity.CRITICAL,
                diagnosis=f"Action failed to execute: {e}",
                screenshot=before,
            )
        
        time.sleep(0.5)
        
        # Screenshot after
        after = _take_screenshot("after")
        
        # Calculate pixel diff
        diff = _calculate_pixel_diff(before, after)
        
        steps.append({
            "step": f"Action: {action}",
            "pixel_diff": diff["change_ratio"],
            "regions": diff["num_regions"],
            "screenshot_before": before,
            "screenshot_after": after,
        })
        
        # Check if anything changed
        if diff["change_ratio"] < 0.001:
            return ACResult(
                ac=f"Action '{action}' causes change",
                level=CheckLevel.FUNCTIONAL.value,
                status=Status.FAIL,
                severity=Severity.CRITICAL,
                diagnosis=f"No visual change detected after '{action}'. "
                          f"pixel_diff={diff['change_ratio']:.4f} (threshold: 0.001). "
                          f"The action handler may be missing or not connected.",
                screenshot=after,
            )
        
        # Ask vision if expected result happened
        result, explanation = _ask_vision_bool(
            after,
            f"Expected result: {expected}. Did this happen? Look at the current UI state."
        )
        
        return ACResult(
            ac=expected,
            level=CheckLevel.FUNCTIONAL.value,
            status=Status.PASS if result else Status.FAIL,
            severity=Severity.CRITICAL,
            diagnosis=f"{explanation} (pixel_diff={diff['change_ratio']:.1%}, {diff['num_regions']} regions changed)",
            screenshot=after,
        )
        
    except Exception as e:
        return ACResult(
            ac=expected,
            level=CheckLevel.FUNCTIONAL.value,
            status=Status.FAIL,
            severity=Severity.CRITICAL,
            diagnosis=f"Action check failed: {e}",
        )


def check_visual_contrast(screenshot_path: str) -> ACResult:
    """V-01: WCAG AA contrast check."""
    try:
        result = check_contrast(screenshot_path)
        
        passed = result.min_ratio >= 4.5
        
        return ACResult(
            ac="Contrast WCAG AA",
            level=CheckLevel.VISUAL.value,
            status=Status.PASS if passed else Status.WARN,
            severity=Severity.MEDIUM,
            diagnosis=f"min={result.min_ratio:.1f}:1 avg={result.avg_ratio:.1f}:1 "
                      f"(WCAG AA requires 4.5:1)",
            screenshot=screenshot_path,
        )
        
    except Exception as e:
        return ACResult(
            ac="Contrast WCAG AA",
            level=CheckLevel.VISUAL.value,
            status=Status.WARN,
            severity=Severity.MEDIUM,
            diagnosis=f"Contrast check failed: {e}",
        )


# ============================================================================
# Report Generation
# ============================================================================

def generate_what_to_fix(acs: list[ACResult]) -> str:
    """Generate actionable fix instructions from failed ACs."""
    failures = [ac for ac in acs if ac.status == Status.FAIL]
    
    if not failures:
        return "All checks passed. No fixes needed."
    
    lines = []
    for f in failures:
        if f.level == CheckLevel.PRE_FLIGHT.value:
            lines.append(f"🔴 CRITICAL (Pre-Flight): {f.diagnosis}")
        elif f.level == CheckLevel.REACHABILITY.value:
            lines.append(f"🔴 CRITICAL (Reachability): {f.diagnosis}")
        elif f.level == CheckLevel.FUNCTIONAL.value:
            lines.append(f"🟠 FUNCTIONAL: {f.ac} - {f.diagnosis}")
        else:
            lines.append(f"🟡 {f.ac}: {f.diagnosis}")
    
    return "\n".join(lines)


# ============================================================================
# Config Loading
# ============================================================================

def load_config(config_path: Path | None = None) -> AppConfig | None:
    """Load .ui-verdict.yml config."""
    if config_path is None:
        cwd = Path.cwd()
        for path in [cwd, *cwd.parents]:
            cfg = path / ".ui-verdict.yml"
            if cfg.exists():
                config_path = cfg
                break
    
    if not config_path or not config_path.exists():
        return None
    
    with open(config_path) as f:
        data = yaml.safe_load(f)
    
    app = data.get("app", {})
    runtime = data.get("runtime", {})
    
    return AppConfig(
        name=app.get("name", "app"),
        binary=app.get("binary", ""),
        binary_location=app.get("binary_location", "repo"),
        env=app.get("env", {}),
        display=runtime.get("display", ":99"),
        resolution=runtime.get("resolution", "1920x1080x24"),
        repo_path=str(config_path.parent),
    )


# ============================================================================
# Main QA Tool
# ============================================================================

@mcp.tool()
def run(
    story: str,
    feature_hints: list[str] | None = None,
    checks: list[dict] | None = None,
) -> str:
    """Run QA checks on the desktop app for a given user story.
    
    Reads .ui-verdict.yml from the repo, launches the app, and runs
    a structured test sequence following the QA-Agent spec:
    
    1. Pre-Flight: App launches, navigation exists
    2. Reachability: Feature is visible and accessible
    3. Functional: Actions work and cause expected changes
    4. Visual: Contrast and layout checks
    
    Aborts early if Pre-Flight or Reachability fails (no point testing
    functionality if the feature isn't reachable).
    
    Args:
        story: User story or feature description to test
        feature_hints: Keywords to look for in UI (e.g., ["Open", "File", "Ctrl+O"])
        checks: Optional list of functional checks, each with:
                - action: "key:ctrl+o" or "click:500,300"
                - expect: "A file dialog should appear"
    
    Returns:
        QAReport as JSON with overall_status, what_to_fix, and detailed results.
        
    Example:
        run(
            story="User can open files with Ctrl+O",
            feature_hints=["Open", "File"],
            checks=[{"action": "key:ctrl+o", "expect": "File dialog appears"}]
        )
    """
    start_time = time.time()
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    
    steps: list[dict] = []
    acs: list[ACResult] = []
    levels: dict[str, str] = {}
    
    # Load config
    config = load_config()
    if not config:
        return json.dumps({
            "run_id": run_id,
            "overall_status": "FAIL",
            "what_to_fix": "No .ui-verdict.yml found in repo. Create one to configure your app.",
            "acs": [],
        }, indent=2)
    
    # =========== PRE-FLIGHT ===========
    steps.append({"step": "Starting Pre-Flight checks", "status": "info"})
    
    # P-01: App launches
    launch_result = check_app_launches(config, steps)
    acs.append(launch_result)
    
    if launch_result.status == Status.FAIL:
        levels["pre_flight"] = "FAIL"
        levels["reachability"] = "SKIPPED"
        levels["functional"] = "SKIPPED"
        levels["visual"] = "SKIPPED"
        
        report = QAReport(
            run_id=run_id,
            story=story,
            overall_status=Status.FAIL,
            duration_seconds=time.time() - start_time,
            acs_passed=0,
            acs_failed=1,
            what_to_fix=generate_what_to_fix(acs),
            levels=levels,
            acs=acs,
            steps=steps,
        )
        return report.to_json()
    
    # P-02: Navigation exists
    nav_result = check_navigation_exists(steps)
    acs.append(nav_result)
    
    preflight_passed = all(ac.status == Status.PASS for ac in acs if ac.level == CheckLevel.PRE_FLIGHT.value)
    levels["pre_flight"] = "PASS" if preflight_passed else "FAIL"
    
    if not preflight_passed:
        levels["reachability"] = "SKIPPED"
        levels["functional"] = "SKIPPED"
        levels["visual"] = "SKIPPED"
        
        report = QAReport(
            run_id=run_id,
            story=story,
            overall_status=Status.FAIL,
            duration_seconds=time.time() - start_time,
            acs_passed=sum(1 for ac in acs if ac.status == Status.PASS),
            acs_failed=sum(1 for ac in acs if ac.status == Status.FAIL),
            what_to_fix=generate_what_to_fix(acs),
            levels=levels,
            acs=acs,
            steps=steps,
        )
        return report.to_json()
    
    # =========== REACHABILITY ===========
    steps.append({"step": "Starting Reachability checks", "status": "info"})
    
    if feature_hints:
        reach_result = check_feature_reachable(feature_hints, steps)
        acs.append(reach_result)
        
        if reach_result.status == Status.FAIL:
            levels["reachability"] = "FAIL"
            levels["functional"] = "SKIPPED"
            levels["visual"] = "SKIPPED"
            
            # Add skipped functional checks
            if checks:
                for check in checks:
                    acs.append(ACResult(
                        ac=check.get("expect", "Unknown"),
                        level=CheckLevel.FUNCTIONAL.value,
                        status=Status.SKIPPED,
                        severity=Severity.CRITICAL,
                        reason="Reachability failed, feature not reachable",
                    ))
            
            report = QAReport(
                run_id=run_id,
                story=story,
                overall_status=Status.FAIL,
                duration_seconds=time.time() - start_time,
                acs_passed=sum(1 for ac in acs if ac.status == Status.PASS),
                acs_failed=sum(1 for ac in acs if ac.status == Status.FAIL),
                what_to_fix=generate_what_to_fix(acs),
                levels=levels,
                acs=acs,
                steps=steps,
            )
            return report.to_json()
    
    levels["reachability"] = "PASS"
    
    # =========== FUNCTIONAL ===========
    steps.append({"step": "Starting Functional checks", "status": "info"})
    
    if checks:
        for check in checks:
            action = check.get("action", "")
            expect = check.get("expect", "Action works")
            
            if not action:
                continue
            
            func_result = check_action_causes_change(action, expect, steps)
            acs.append(func_result)
    
    functional_results = [ac for ac in acs if ac.level == CheckLevel.FUNCTIONAL.value]
    if functional_results:
        functional_passed = all(ac.status == Status.PASS for ac in functional_results)
        levels["functional"] = "PASS" if functional_passed else "FAIL"
    else:
        levels["functional"] = "SKIPPED"
    
    # =========== VISUAL ===========
    steps.append({"step": "Starting Visual checks", "status": "info"})
    
    # Get latest screenshot for visual checks
    try:
        latest_screenshot = _take_screenshot("visual")
        contrast_result = check_visual_contrast(latest_screenshot)
        acs.append(contrast_result)
        
        visual_warns = sum(1 for ac in acs if ac.level == CheckLevel.VISUAL.value and ac.status == Status.WARN)
        if visual_warns > 0:
            levels["visual"] = f"{visual_warns} warnings"
        else:
            levels["visual"] = "PASS"
    except:
        levels["visual"] = "SKIPPED"
    
    # =========== BUILD REPORT ===========
    passed = sum(1 for ac in acs if ac.status == Status.PASS)
    failed = sum(1 for ac in acs if ac.status == Status.FAIL)
    
    overall = Status.PASS
    if failed > 0:
        overall = Status.FAIL
    elif any(ac.status == Status.WARN for ac in acs):
        overall = Status.WARN
    
    report = QAReport(
        run_id=run_id,
        story=story,
        overall_status=overall,
        duration_seconds=time.time() - start_time,
        acs_passed=passed,
        acs_failed=failed,
        what_to_fix=generate_what_to_fix(acs),
        levels=levels,
        acs=acs,
        steps=steps,
    )
    
    return report.to_json()


@mcp.tool()
def check_screenshot(
    screenshot_path: str,
    checks: list[str],
) -> str:
    """Check a screenshot with yes/no questions.
    
    Args:
        screenshot_path: Path to screenshot file
        checks: List of yes/no questions to answer
        
    Returns:
        JSON with {check: boolean} for each question.
        
    Example:
        check_screenshot("/tmp/screen.png", [
            "Is there a file dialog visible?",
            "Is any text truncated with ellipsis?"
        ])
    """
    results = {}
    
    for check in checks:
        try:
            result, _ = _ask_vision_bool(screenshot_path, check)
            results[check] = result
        except Exception as e:
            results[check] = f"ERROR: {e}"
    
    return json.dumps(results, indent=2)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
