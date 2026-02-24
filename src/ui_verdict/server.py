from __future__ import annotations

import tempfile
import os
from mcp.server.fastmcp import FastMCP

from .capture import ScreenGrabber, load_image_bgr, load_image_gray
from .diff import classify_change
from .input import send_action
from .metrics import check_contrast, check_layout
from .models import DiffReport, Issue, Region, Severity, VerdictReport
from .action import parse_action, execute_action, ActionParseError

mcp = FastMCP("ui-verdict")

# Single shared grabber — keep alive for performance
_grabber = ScreenGrabber()


@mcp.tool()
def verify_action(
    action: str,
    region: str | None = None,
    expected: str = "any_change",
    timeout_ms: int = 200,
) -> str:
    """Verify that an action caused a visible change on screen (action-reaction check).

    Use this after implementing interactive UI to confirm it responds to input.

    Args:
        action: Input to send. Examples:
            "key:w"                 — tap W key
            "key:space:hold:200ms" — hold Space for 200ms
            "key:w:hold:300ms"     — hold W for 300ms
            "click:500,300"        — left click at screen position (500, 300)
            "rightclick:200,400"   — right click
            "wait:500ms"           — just wait, no input (for observing changes)
        region: Screen region to watch as "x,y,w,h" e.g. "0,0,800,600".
            None = full primary monitor.
        expected: What change to expect:
            "any_change"      — any visible reaction (default)
            "movement"        — something moves
            "movement:up"     — movement upward
            "movement:down"   — movement downward
            "movement:left"   — movement leftward
            "movement:right"  — movement rightward
            "appear"          — something new appears
            "disappear"       — something disappears
            "no_change"       — assert nothing changes (negative test)
        timeout_ms: Wait time after action before capturing (default 200ms).

    Returns structured verdict: PASS or FAIL with details on what changed.
    """
    parsed_region = Region.from_str(region) if region else None

    before = _grabber.grab_gray(parsed_region)
    try:
        send_action(action)
    except Exception as e:
        return f"FAIL: Could not send action {action!r}: {e}"

    import time

    time.sleep(timeout_ms / 1000.0)
    after = _grabber.grab_gray(parsed_region)

    result = classify_change(before, after)

    diff_report = DiffReport(
        changed=result.changed,
        change_type=result.change_type,
        change_ratio=result.change_ratio,
        direction=result.direction,
        magnitude=result.magnitude,
        moving_ratio=result.moving_ratio,
    )

    verdict = _evaluate_expected(result, expected)
    overall = Severity.PASS if verdict["pass"] else Severity.FAIL

    issues: list[Issue] = []
    if not verdict["pass"]:
        issues.append(
            Issue(
                severity=Severity.FAIL,
                category="action_reaction",
                message=verdict["message"],
            )
        )

    report = VerdictReport(overall=overall, diff=diff_report, issues=issues)
    return report.to_text()


@mcp.tool()
def analyze_ui(
    path: str,
    expectations: str | None = None,
) -> str:
    """Analyze a screenshot for visual quality: contrast, layout balance, and clutter.

    Use this to check if a rendered UI meets visual quality standards without
    requiring interaction.

    Args:
        path: Absolute path to screenshot file (PNG, JPG).
        expectations: Optional plain-text description of what should be visible.
            Used as context in the report. Does not affect scoring.

    Returns structured report with contrast scores, layout metrics, and issues.
    """
    if not os.path.exists(path):
        return f"FAIL: Screenshot not found at {path!r}"

    issues: list[Issue] = []

    contrast = check_contrast(path)
    issues.extend(contrast.issues)

    layout = check_layout(path)
    issues.extend(layout.issues)

    overall = Severity.PASS
    if any(i.severity == Severity.FAIL for i in issues):
        overall = Severity.FAIL
    elif any(i.severity == Severity.WARN for i in issues):
        overall = Severity.WARN

    report = VerdictReport(
        overall=overall,
        contrast=contrast,
        layout=layout,
        issues=issues,
    )

    if expectations:
        report.vision_analysis = f"Expected: {expectations}"

    return report.to_text()


@mcp.tool()
def screenshot(
    region: str | None = None,
    save_path: str | None = None,
    app: str | None = None,
) -> str:
    """Take a screenshot and optionally save it to disk.

    Args:
        region: Region as "x,y,w,h" or None for full screen.
        save_path: Optional path to save PNG. If omitted, saves to a temp file.
        app: App name to capture only that window (macOS only, e.g. "imagination").
             Produces a clean window-only screenshot without other monitors/apps.

    Returns: Path to the saved screenshot file.
    """
    parsed_region = Region.from_str(region) if region else None

    if save_path is None:
        fd, save_path = tempfile.mkstemp(suffix=".png", prefix="ui_verdict_")
        os.close(fd)

    if app:
        from .capture import capture_window, ScreenGrabber

        if not capture_window(app, save_path):
            # fallback to monitor grab
            grabber = ScreenGrabber()
            grabber.save_screenshot(save_path, parsed_region)
            grabber.close()
    else:
        _grabber.save_screenshot(save_path, parsed_region)

    return f"Screenshot saved: {save_path}"


def _evaluate_expected(result, expected: str) -> dict:
    """Check if the change result matches the expected outcome."""
    exp = expected.lower().strip()

    if exp == "no_change":
        if not result.changed:
            return {"pass": True, "message": ""}
        return {
            "pass": False,
            "message": f"Expected no change but {result.change_type.value} detected ({result.change_ratio:.1%} pixels changed)",
        }

    if not result.changed:
        return {
            "pass": False,
            "message": f"Expected {exp!r} but NO CHANGE detected — action had no visible effect",
        }

    if exp == "any_change":
        return {"pass": True, "message": ""}

    if exp == "movement":
        from .models import ChangeType

        if result.change_type in (ChangeType.MOVEMENT, ChangeType.MIXED):
            return {"pass": True, "message": ""}
        return {
            "pass": False,
            "message": f"Expected movement but got {result.change_type.value}",
        }

    if exp.startswith("movement:"):
        direction = exp.split(":", 1)[1]
        if result.direction.value == direction:
            return {"pass": True, "message": ""}
        return {
            "pass": False,
            "message": f"Expected movement:{direction} but direction was {result.direction.value}",
        }

    if exp == "appear":
        from .models import ChangeType

        if result.change_type in (ChangeType.APPEARANCE, ChangeType.MIXED):
            return {"pass": True, "message": ""}
        return {
            "pass": False,
            "message": f"Expected appearance but got {result.change_type.value}",
        }

    if exp == "disappear":
        from .models import ChangeType

        if result.change_type in (ChangeType.DISAPPEARANCE, ChangeType.MIXED):
            return {"pass": True, "message": ""}
        return {
            "pass": False,
            "message": f"Expected disappearance but got {result.change_type.value}",
        }

    return {
        "pass": True,
        "message": f"Unknown expected value {exp!r}, defaulting to pass",
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()


@mcp.tool()
def ask_vision(
    path: str,
    question: str,
    model: str = "glm-ocr",
) -> str:
    """Ask a vision model a question about a screenshot.

    Use this for semantic UI analysis: checking if specific elements are visible,
    reading text, detecting overlaps, or assessing visual quality.

    Args:
        path: Path to screenshot file (PNG, JPG).
        question: Question to ask about the image. Examples:
            "Is there a Submit button visible?"
            "Read all text in this screenshot"
            "Are any elements overlapping or cut off?"
            "What is the main heading text?"
            "Describe the layout of this UI"
        model: Vision model to use (default: glm-ocr, alternatives: moondream, llava).

    Returns: The vision model's answer.
    """
    if not os.path.exists(path):
        return f"Error: Screenshot not found at {path!r}"

    try:
        from .vision import ask_ollama
        return ask_ollama(path, question, model)
    except ImportError as e:
        return f"Error: Vision module not available: {e}"
    except Exception as e:
        return f"Error: Vision model failed: {e}"


@mcp.tool()
def analyze_ui_full(
    path: str | None = None,
    app: str | None = None,
    expectations: str | None = None,
) -> str:
    """Full UI analysis: deterministic metrics + vision model.

    Combines contrast/layout checks with AI vision for comprehensive analysis.
    This is the most thorough analysis available.

    Args:
        path: Path to existing screenshot, OR
        app: App name to capture fresh screenshot (macOS, e.g. "imagination").
        expectations: Description of expected UI state for the vision model to verify.

    Returns: Complete verdict with metrics, issues, and vision analysis.
    """
    # Get or capture screenshot
    if path and os.path.exists(path):
        screenshot_path = path
    elif app:
        fd, screenshot_path = tempfile.mkstemp(suffix=".png", prefix="ui_verdict_")
        os.close(fd)
        from .capture import capture_window
        if not capture_window(app, screenshot_path):
            return f"Error: Could not capture window for app {app!r}"
    else:
        return "Error: Provide either 'path' to existing screenshot or 'app' name to capture"

    # Run deterministic analysis
    issues: list[Issue] = []

    contrast = check_contrast(screenshot_path)
    issues.extend(contrast.issues)

    layout = check_layout(screenshot_path)
    issues.extend(layout.issues)

    # Run vision analysis
    vision_result = None
    try:
        from .vision import ask_ollama

        if expectations:
            vision_question = f"Analyze this UI. Verify: {expectations}. Also check for any visual issues like overlapping elements, cut-off text, or readability problems."
        else:
            vision_question = "Analyze this UI. Describe the layout, read visible text, and note any visual issues like overlapping elements, cut-off text, or readability problems."

        vision_result = ask_ollama(screenshot_path, vision_question)
    except Exception as e:
        vision_result = f"Vision analysis failed: {e}"

    # Determine overall verdict
    overall = Severity.PASS
    if any(i.severity == Severity.FAIL for i in issues):
        overall = Severity.FAIL
    elif any(i.severity == Severity.WARN for i in issues):
        overall = Severity.WARN

    report = VerdictReport(
        overall=overall,
        contrast=contrast,
        layout=layout,
        issues=issues,
        vision_analysis=vision_result,
    )

    return report.to_text()


# =============================================================================
# VM Testing Tools - Run and test GUI apps in OrbStack Linux VM
# =============================================================================

@mcp.tool()
def vm_deploy(
    binary_path: str,
    app_name: str = "app",
    args: str | None = None,
    env: str | None = None,
) -> str:
    """Deploy and run a GUI application in the Linux VM for testing.
    
    This copies a Mac-built binary to the VM, starts Xvfb (virtual display),
    and runs the application headlessly. Use this before vm_screenshot or vm_action.
    
    Args:
        binary_path: Path to binary on Mac (e.g., "target/release/imagination")
        app_name: Name to identify this app instance
        args: Optional command line arguments (space-separated)
        env: Optional environment variables (format: "KEY=value,KEY2=value2")
             Example: "GEGL_PATH=/usr/lib/aarch64-linux-gnu/gegl-0.4"
        
    Returns:
        Status with PID and display info, or error message.
        
    Example:
        vm_deploy("target/release/imagination", "imagination", 
                  env="GEGL_PATH=/usr/lib/aarch64-linux-gnu/gegl-0.4")
    """
    try:
        from .vm import deploy_and_run
        
        args_list = args.split() if args else None
        
        # Parse env string into dict
        env_dict = None
        if env:
            env_dict = {}
            for pair in env.split(","):
                if "=" in pair:
                    key, value = pair.split("=", 1)
                    env_dict[key.strip()] = value.strip()
        
        result = deploy_and_run(binary_path, app_name, args_list, env_dict)
        
        if result["running"]:
            return f"✅ {app_name} deployed and running\n  PID: {result['pid']}\n  Display: {result['display']}\n  Binary: {result['vm_binary']}"
        else:
            return f"⚠️ {app_name} deployed but may not be running. Check logs with: orb run -m ui-test cat /tmp/{app_name}.log"
    except Exception as e:
        return f"❌ Deploy failed: {e}"


@mcp.tool()
def vm_screenshot(save_path: str | None = None) -> str:
    """Take a screenshot of the VM's virtual display.
    
    Captures the current state of the Xvfb display where the test app runs.
    The screenshot is copied to the Mac for analysis.
    
    Args:
        save_path: Where to save on Mac. If None, uses a temp file.
        
    Returns:
        Path to the saved screenshot file.
    """
    try:
        from .vm import vm_screenshot as take_screenshot
        
        path = take_screenshot(save_path)
        return f"Screenshot saved: {path}"
    except Exception as e:
        return f"❌ Screenshot failed: {e}"


@mcp.tool()
def vm_action(action: str) -> str:
    """Send input to the application running in the VM.
    
    Args:
        action: Input to send. Formats:
            "key:w"              — tap W key
            "key:space"          — tap Space
            "key:Return"         — tap Enter
            "key:w:hold:500ms"   — hold W for 500ms
            "click:500,300"      — left click at (500, 300)
            "rightclick:500,300" — right click
            "type:hello world"   — type text
            "wait:500ms"         — just wait
            
    Returns:
        "OK" on success, error message on failure.
    """
    try:
        execute_action(action)
        return "OK"
    except ActionParseError as e:
        return f"❌ Invalid action: {e}"
    except Exception as e:
        return f"❌ Action failed: {e}"


@mcp.tool()
def vm_verify_action(
    action: str,
    expected: str = "any_change",
    timeout_ms: int = 500,
) -> str:
    """Send input to VM app and verify it caused a visible change.
    
    This is the main testing tool: send input, wait, compare before/after.
    
    Args:
        action: Input to send (same format as vm_action)
        expected: What change to expect:
            "any_change" — any visible difference (default)
            "no_change"  — assert nothing changes
        timeout_ms: Wait time after action before comparing
        
    Returns:
        PASS/FAIL verdict with details.
    """
    try:
        from .vm import vm_screenshot as take_screenshot
        from .diff import classify_change
        from .capture import load_image_gray
        import time
        
        # Take before screenshot
        before_path = take_screenshot()
        before = load_image_gray(before_path)
        
        # Execute action
        execute_action(action)
        
        # Wait for UI to update
        time.sleep(timeout_ms / 1000.0)
        
        # Take after screenshot
        after_path = take_screenshot()
        after = load_image_gray(after_path)
        
        # Compare
        result = classify_change(before, after)
        
        # Evaluate
        exp = expected.lower().strip()
        if exp == "no_change":
            if not result.changed:
                return f"✅ PASS: No change detected (as expected)"
            return f"❌ FAIL: Expected no change but {result.change_type.value} detected ({result.change_ratio:.1%} pixels changed)"
        else:  # any_change
            if result.changed:
                return f"✅ PASS: {result.change_type.value} detected ({result.change_ratio:.1%} pixels changed)"
            return f"❌ FAIL: Expected change but nothing happened — action had no visible effect"
            
    except Exception as e:
        return f"❌ Verify failed: {e}"


@mcp.tool()
def vm_analyze(expectations: str | None = None) -> str:
    """Analyze the current VM screen with vision model and metrics.
    
    Takes a screenshot of the VM and runs full analysis:
    - Contrast and layout metrics
    - Vision model analysis (if available)
    
    Args:
        expectations: What should be visible (e.g., "main window with toolbar")
        
    Returns:
        Full analysis report.
    """
    try:
        from .vm import vm_screenshot as take_screenshot
        
        # Take screenshot
        screenshot_path = take_screenshot()
        
        # Run analysis (reuse analyze_ui_full logic)
        issues: list[Issue] = []
        
        contrast = check_contrast(screenshot_path)
        issues.extend(contrast.issues)
        
        layout = check_layout(screenshot_path)
        issues.extend(layout.issues)
        
        # Vision analysis
        vision_result = None
        try:
            from .vision import ask_ollama
            
            if expectations:
                q = f"Analyze this UI. Verify: {expectations}. Note any visual issues."
            else:
                q = "Analyze this UI. Describe the layout and note any visual issues."
            
            vision_result = ask_ollama(screenshot_path, q)
        except Exception as e:
            vision_result = f"Vision analysis unavailable: {e}"
        
        # Build report
        overall = Severity.PASS
        if any(i.severity == Severity.FAIL for i in issues):
            overall = Severity.FAIL
        elif any(i.severity == Severity.WARN for i in issues):
            overall = Severity.WARN
        
        report = VerdictReport(
            overall=overall,
            contrast=contrast,
            layout=layout,
            issues=issues,
            vision_analysis=vision_result,
        )
        
        return report.to_text()
        
    except Exception as e:
        return f"❌ Analysis failed: {e}"


@mcp.tool()
def vm_stop(app_name: str | None = None) -> str:
    """Stop an application running in the VM.
    
    Args:
        app_name: Name of the app to stop. If None, stops all user apps.
        
    Returns:
        Confirmation message.
    """
    try:
        from .vm import vm_stop_app
        
        if app_name:
            vm_stop_app(name=app_name)
            return f"Stopped {app_name}"
        else:
            # Stop common test apps
            for name in ["imagination", "pipeline"]:
                vm_stop_app(name=name)
            return "Stopped test applications"
    except Exception as e:
        return f"❌ Stop failed: {e}"


@mcp.tool() 
def vm_status() -> str:
    """Check the status of the VM testing environment.
    
    Returns:
        Status report including VM availability, Xvfb status, running apps.
    """
    try:
        from .vm import vm_available, _run_in_vm, _config
        
        lines = []
        
        # VM availability
        if vm_available():
            lines.append(f"✅ VM '{_config.name}' is running")
        else:
            lines.append(f"❌ VM '{_config.name}' is not available")
            lines.append(f"   Run: orb create ubuntu:24.04 {_config.name}")
            return "\n".join(lines)
        
        # Xvfb status
        code, out, _ = _run_in_vm(f"pgrep -f 'Xvfb {_config.display}'")
        if code == 0 and out.strip():
            lines.append(f"✅ Xvfb running on {_config.display}")
        else:
            lines.append(f"⚠️ Xvfb not running (will start on first deploy)")
        
        # Running apps
        code, out, _ = _run_in_vm("pgrep -a imagination 2>/dev/null || pgrep -a pipeline 2>/dev/null || echo 'none'")
        if "none" not in out:
            lines.append(f"📱 Running apps:\n   {out.strip()}")
        else:
            lines.append("📱 No test apps running")
        
        return "\n".join(lines)
        
    except Exception as e:
        return f"❌ Status check failed: {e}"


# =============================================================================
# Diff Visualization Tools - Help agents SEE what changed
# =============================================================================

@mcp.tool()
def vm_diff_heatmap(
    action: str,
    output_path: str | None = None,
    timeout_ms: int = 500,
) -> str:
    """Perform action and generate a heatmap showing WHERE changes occurred.
    
    This is more informative than vm_verify_action because it shows the
    LOCATION of changes, not just whether something changed.
    
    Args:
        action: Input to send (same format as vm_action)
        output_path: Where to save heatmap. If None, uses temp file.
        timeout_ms: Wait time after action
        
    Returns:
        Path to heatmap image + stats about changed regions.
    """
    try:
        from .vm import vm_screenshot as take_screenshot
        from .diff.heatmap import generate_heatmap, generate_diff_mask
        import tempfile
        import time
        
        # Take before screenshot
        before_path = take_screenshot()
        before = load_image_gray(before_path)
        
        # Execute action
        execute_action(action)
        
        # Wait
        time.sleep(timeout_ms / 1000.0)
        
        # Take after screenshot
        after_path = take_screenshot()
        after = load_image_gray(after_path)
        
        # Generate heatmap
        if output_path is None:
            fd, output_path = tempfile.mkstemp(suffix="_heatmap.png", prefix="vm_diff_")
            os.close(fd)
        
        _, saved = generate_heatmap(before, after, output_path)
        
        # Get stats
        _, stats = generate_diff_mask(before, after)
        
        # Format result
        if stats["num_regions"] == 0:
            return f"No changes detected.\nHeatmap: {saved}"
        
        regions_str = "\n".join([
            f"  #{i+1}: ({r['x']},{r['y']}) {r['width']}x{r['height']} ({r['area']}px)"
            for i, r in enumerate(stats["regions"][:5])
        ])
        
        return f"""Changes detected: {stats['change_ratio']:.1%} of screen
Regions changed: {stats['num_regions']}
Top regions:
{regions_str}

Heatmap saved: {saved}"""
        
    except Exception as e:
        return f"❌ Heatmap generation failed: {e}"


@mcp.tool()
def vm_diff_annotated(
    action: str,
    output_path: str | None = None,
    timeout_ms: int = 500,
) -> str:
    """Perform action and generate annotated screenshot with change boxes.
    
    Draws red bounding boxes around all regions that changed.
    
    Args:
        action: Input to send
        output_path: Where to save annotated image
        timeout_ms: Wait time after action
        
    Returns:
        Path to annotated image + list of changed regions with coordinates.
    """
    try:
        from .vm import vm_screenshot as take_screenshot
        from .diff.heatmap import generate_diff_mask, annotate_changes
        import tempfile
        import time
        
        # Take before screenshot
        before_path = take_screenshot()
        before = load_image_gray(before_path)
        
        # Execute action
        execute_action(action)
        
        # Wait
        time.sleep(timeout_ms / 1000.0)
        
        # Take after screenshot
        after_path = take_screenshot()
        after = load_image_gray(after_path)
        
        # Get changed regions
        _, stats = generate_diff_mask(before, after)
        
        if stats["num_regions"] == 0:
            return f"No changes detected.\nAfter screenshot: {after_path}"
        
        # Annotate after image
        if output_path is None:
            fd, output_path = tempfile.mkstemp(suffix="_annotated.png", prefix="vm_diff_")
            os.close(fd)
        
        saved = annotate_changes(after, stats["regions"], output_path)
        
        # Format regions as actionable coordinates
        regions_str = "\n".join([
            f"  Region #{i+1}: x={r['x']}, y={r['y']}, w={r['width']}, h={r['height']} (center: {r['x']+r['width']//2}, {r['y']+r['height']//2})"
            for i, r in enumerate(stats["regions"][:5])
        ])
        
        return f"""Changes detected: {stats['num_regions']} regions

{regions_str}

Annotated image: {saved}
(Red boxes show changed regions, numbered by size)"""
        
    except Exception as e:
        return f"❌ Annotation failed: {e}"


@mcp.tool()
def vm_compare(
    output_path: str | None = None,
) -> str:
    """Take two screenshots (now and 500ms later) and create side-by-side comparison.
    
    Useful for observing animations or delayed changes.
    
    Args:
        output_path: Where to save comparison image
        
    Returns:
        Path to side-by-side comparison image.
    """
    try:
        from .vm import vm_screenshot as take_screenshot
        from .diff.heatmap import generate_side_by_side
        import tempfile
        import time
        
        # Take first screenshot
        before_path = take_screenshot()
        before = load_image_gray(before_path)
        
        # Wait
        time.sleep(0.5)
        
        # Take second screenshot
        after_path = take_screenshot()
        after = load_image_gray(after_path)
        
        # Generate side-by-side
        if output_path is None:
            fd, output_path = tempfile.mkstemp(suffix="_compare.png", prefix="vm_")
            os.close(fd)
        
        saved = generate_side_by_side(before, after, output_path)
        
        return f"Side-by-side comparison saved: {saved}"
        
    except Exception as e:
        return f"❌ Comparison failed: {e}"
