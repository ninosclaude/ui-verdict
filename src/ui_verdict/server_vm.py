"""
VM-only MCP server for ui-verdict.

This server exposes ONLY the VM tools - no local screen capture.
Use this when you want agents to test apps in the Linux VM without
accessing the developer's desktop.
"""
from __future__ import annotations

import tempfile
import os
from mcp.server.fastmcp import FastMCP

from .capture import load_image_bgr, load_image_gray
from .metrics import check_contrast, check_layout
from .models import Issue, Severity, VerdictReport
from .action import execute_action, ActionParseError

mcp = FastMCP("ui-verdict-vm")


@mcp.tool()
def vm_deploy(
    binary_path: str,
    app_name: str = "app",
    args: str | None = None,
    env: str | None = None,
) -> str:
    """Deploy and run a GUI application in the Linux VM for testing.
    
    This starts Xvfb (virtual display) and runs the application headlessly.
    Use this before vm_screenshot or vm_action.
    
    Args:
        binary_path: Path to binary (VM path like /home/... or Mac path)
        app_name: Name to identify this app instance
        args: Optional command line arguments (space-separated)
        env: Optional environment variables (format: "KEY=value,KEY2=value2")
             Example: "GEGL_PATH=/usr/lib/aarch64-linux-gnu/gegl-0.4"
        
    Returns:
        Status with PID and display info, or error message.
        
    Example:
        vm_deploy("/home/user/app/target/release/myapp", "myapp",
                  env="GEGL_PATH=/usr/lib/aarch64-linux-gnu/gegl-0.4")
    """
    try:
        from .vm import deploy_and_run
        
        args_list = args.split() if args else None
        
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
            "key:ctrl+o"         — key combination
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
        import time
        
        before_path = take_screenshot()
        before = load_image_gray(before_path)
        
        execute_action(action)
        
        time.sleep(timeout_ms / 1000.0)
        
        after_path = take_screenshot()
        after = load_image_gray(after_path)
        
        result = classify_change(before, after)
        
        exp = expected.lower().strip()
        if exp == "no_change":
            if not result.changed:
                return f"✅ PASS: No change detected (as expected)"
            return f"❌ FAIL: Expected no change but {result.change_type.value} detected ({result.change_ratio:.1%} pixels changed)"
        else:
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
        
        screenshot_path = take_screenshot()
        
        issues: list[Issue] = []
        
        contrast = check_contrast(screenshot_path)
        issues.extend(contrast.issues)
        
        layout = check_layout(screenshot_path)
        issues.extend(layout.issues)
        
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
        app_name: Name of the app to stop. If None, stops common test apps.
        
    Returns:
        Confirmation message.
    """
    try:
        from .vm import vm_stop_app
        
        if app_name:
            vm_stop_app(name=app_name)
            return f"Stopped {app_name}"
        else:
            for name in ["imagination", "pipeline"]:
                vm_stop_app(name=name)
            return "Stopped test applications"
    except Exception as e:
        return f"❌ Stop failed: {e}"


@mcp.tool() 
def vm_status() -> str:
    """Check the status of the VM testing environment.
    
    Returns:
        Status of VM, Xvfb, and running apps.
    """
    try:
        from .vm import vm_available, ensure_xvfb, _run_in_vm, _config
        
        lines = []
        
        if vm_available():
            lines.append(f"✅ VM '{_config.name}' is running")
        else:
            lines.append(f"❌ VM '{_config.name}' is not available")
            return "\n".join(lines)
        
        if ensure_xvfb():
            lines.append(f"✅ Xvfb running on {_config.display}")
        else:
            lines.append(f"⚠️ Xvfb not running")
        
        code, out, _ = _run_in_vm("ps aux | grep -E 'imagination|pipeline' | grep -v grep | awk '{print $2, $11}'")
        if code == 0 and out.strip():
            lines.append("📱 Running apps:")
            for line in out.strip().split("\n"):
                if line:
                    lines.append(f"   {line}")
        else:
            lines.append("📱 No test apps running")
        
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Status check failed: {e}"


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
        import time
        
        before_path = take_screenshot()
        before = load_image_gray(before_path)
        
        execute_action(action)
        
        time.sleep(timeout_ms / 1000.0)
        
        after_path = take_screenshot()
        after = load_image_gray(after_path)
        
        if output_path is None:
            fd, output_path = tempfile.mkstemp(suffix="_heatmap.png", prefix="vm_diff_")
            os.close(fd)
        
        _, saved = generate_heatmap(before, after, output_path)
        _, stats = generate_diff_mask(before, after)
        
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
        import time
        
        before_path = take_screenshot()
        before = load_image_gray(before_path)
        
        execute_action(action)
        
        time.sleep(timeout_ms / 1000.0)
        
        after_path = take_screenshot()
        after = load_image_gray(after_path)
        
        _, stats = generate_diff_mask(before, after)
        
        if stats["num_regions"] == 0:
            return f"No changes detected.\nAfter screenshot: {after_path}"
        
        if output_path is None:
            fd, output_path = tempfile.mkstemp(suffix="_annotated.png", prefix="vm_diff_")
            os.close(fd)
        
        saved = annotate_changes(after, stats["regions"], output_path)
        
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
def vm_ask_vision(
    question: str,
    model: str = "glm-ocr",
) -> str:
    """Ask a vision model about the current VM screen.
    
    Takes a screenshot of the VM and sends it to the vision model.
    
    Args:
        question: Question to ask about the UI
        model: Vision model to use (default: glm-ocr)
        
    Returns:
        Vision model's response.
    """
    try:
        from .vm import vm_screenshot as take_screenshot
        from .vision import ask_ollama
        
        screenshot_path = take_screenshot()
        response = ask_ollama(screenshot_path, question, model)
        return response
    except Exception as e:
        return f"❌ Vision query failed: {e}"


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
