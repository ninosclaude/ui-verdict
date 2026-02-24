"""
High-level agentic MCP server for ui-verdict.

Exposes only 3-4 tools optimized for LLM agents:
- deploy_app: Start app from .ui-verdict.yml config
- test_interaction: Execute actions + verify with vision
- ask_vision: Ask questions about current UI state
- run_test: Run predefined test from config

No low-level tools. No manual screenshot reading needed.
"""
from __future__ import annotations

import os
import yaml
import tempfile
from pathlib import Path
from dataclasses import dataclass
from mcp.server.fastmcp import FastMCP

from .capture import load_image_gray
from .action import execute_action, ActionParseError


mcp = FastMCP("ui-verdict")


@dataclass
class AppConfig:
    """Configuration loaded from .ui-verdict.yml"""
    name: str
    binary: str
    binary_location: str  # "vm" or "repo"
    env: dict[str, str]
    packages: list[str]
    display: str
    resolution: str
    tests: dict[str, dict]
    repo_path: str


_config: AppConfig | None = None
_app_running: bool = False


def _find_config() -> Path | None:
    """Find .ui-verdict.yml in current directory or parents."""
    cwd = Path.cwd()
    for path in [cwd, *cwd.parents]:
        config_file = path / ".ui-verdict.yml"
        if config_file.exists():
            return config_file
    return None


def _load_config(config_path: Path) -> AppConfig:
    """Load and parse .ui-verdict.yml"""
    with open(config_path) as f:
        data = yaml.safe_load(f)
    
    app = data.get("app", {})
    runtime = data.get("runtime", {})
    tests = data.get("tests", {})
    
    return AppConfig(
        name=app.get("name", "app"),
        binary=app.get("binary", ""),
        binary_location=app.get("binary_location", "repo"),  # "vm" or "repo"
        env=app.get("env", {}),
        packages=runtime.get("packages", []),
        display=runtime.get("display", ":99"),
        resolution=runtime.get("resolution", "1920x1080x24"),
        tests=tests,
        repo_path=str(config_path.parent),
    )


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


def _take_screenshot() -> str:
    """Take screenshot in VM, return local path."""
    import uuid
    import time
    import shutil
    
    unique_id = uuid.uuid4().hex[:8]
    vm_path = f"/mnt/mac/tmp/ui_verdict_{unique_id}.png"
    local_path = f"/tmp/ui_verdict_{unique_id}.png"
    
    code, _, err = _run_in_vm(f"export DISPLAY=:99 && scrot -o {vm_path}")
    if code != 0:
        raise RuntimeError(f"Screenshot failed: {err}")
    
    # Wait for file to appear
    for _ in range(10):
        if os.path.exists(local_path):
            return local_path
        time.sleep(0.1)
    
    raise RuntimeError("Screenshot file not found")


def _ask_vision_internal(image_path: str, question: str) -> str:
    """Ask vision model about an image."""
    from .vision import ask_ollama
    return ask_ollama(image_path, question, model="glm-ocr")


def _generate_diff_description(before_path: str, after_path: str) -> dict:
    """Generate diff stats between two images."""
    from .diff.heatmap import generate_diff_mask
    
    before = load_image_gray(before_path)
    after = load_image_gray(after_path)
    
    _, stats = generate_diff_mask(before, after)
    return stats


@mcp.tool()
def deploy_app(config_path: str | None = None) -> str:
    """Deploy and start the application for testing.
    
    Reads .ui-verdict.yml from the repo, sets up the VM environment,
    and starts the application. Call this once at the start of a session.
    
    Args:
        config_path: Optional path to .ui-verdict.yml. If not provided,
                     searches current directory and parents.
    
    Returns:
        Status message with app info, or error.
        
    Example:
        deploy_app()  # Reads .ui-verdict.yml from repo
    """
    global _config, _app_running
    
    try:
        # Find and load config
        if config_path:
            cfg_path = Path(config_path)
        else:
            cfg_path = _find_config()
        
        if not cfg_path or not cfg_path.exists():
            return "❌ No .ui-verdict.yml found. Create one in your repo root."
        
        _config = _load_config(cfg_path)
        
        # Check VM available
        code, out, _ = _run_in_vm("echo ok", timeout=5)
        if code != 0 or "ok" not in out:
            return "❌ VM 'ui-test' not available. Start with: orb create ubuntu:24.04 ui-test"
        
        # Ensure Xvfb running
        code, _, _ = _run_in_vm(f"pgrep -f 'Xvfb {_config.display}'")
        if code != 0:
            _run_in_vm(f"Xvfb {_config.display} -screen 0 {_config.resolution} &")
            import time; time.sleep(0.5)
        
        # Ensure window manager
        code, _, _ = _run_in_vm("pgrep openbox")
        if code != 0:
            _run_in_vm(f"export DISPLAY={_config.display} && openbox &")
            import time; time.sleep(0.3)
        
        # Build binary path
        if _config.binary_location == "vm":
            # Binary already in VM
            vm_binary = _config.binary
            vm_repo = f"/mnt/mac{_config.repo_path}"
        else:
            # Binary in repo (mounted at /mnt/mac)
            vm_repo = f"/mnt/mac{_config.repo_path}"
            vm_binary = f"{vm_repo}/{_config.binary}"
        
        # Check binary exists
        code, _, _ = _run_in_vm(f"test -f {vm_binary}")
        if code != 0:
            return f"❌ Binary not found: {vm_binary}\nDid you build for Linux?"
        
        # Stop any existing instance
        _run_in_vm(f"pkill -f {_config.name} 2>/dev/null || true")
        import time; time.sleep(0.3)
        
        # Build env string
        env_parts = [f"DISPLAY={_config.display}"]
        for k, v in _config.env.items():
            env_parts.append(f"{k}={v}")
        env_str = " ".join(env_parts)
        
        # Start app
        cmd = f"export {env_str} && cd {vm_repo} && {vm_binary} > /tmp/{_config.name}.log 2>&1 &"
        _run_in_vm(cmd)
        
        import time; time.sleep(2.0)
        
        # Verify running
        code, out, _ = _run_in_vm(f"pgrep -f {_config.name}")
        if code != 0:
            # Get log for debugging
            _, log, _ = _run_in_vm(f"tail -20 /tmp/{_config.name}.log")
            return f"❌ App failed to start.\nLog:\n{log}"
        
        pid = out.strip().split()[0]
        _app_running = True
        
        # Take initial screenshot to verify
        screenshot = _take_screenshot()
        
        # Quick vision check
        vision_desc = _ask_vision_internal(screenshot, f"Briefly describe what you see in this {_config.name} application window.")
        
        tests_available = list(_config.tests.keys()) if _config.tests else []
        tests_str = f"\nPredefined tests: {', '.join(tests_available)}" if tests_available else ""
        
        return f"""✅ {_config.name} deployed and running
PID: {pid}
Display: {_config.display}
Binary: {vm_binary}
{tests_str}

Current state: {vision_desc}"""

    except Exception as e:
        return f"❌ Deploy failed: {e}"


@mcp.tool()
def test_interaction(
    actions: list[str],
    expect: str | None = None,
    timeout_ms: int = 500,
) -> str:
    """Test a UI interaction and verify the result.
    
    Executes a sequence of actions and uses vision AI to verify the outcome.
    This is the main testing tool - no need to manually look at screenshots.
    
    Args:
        actions: List of actions to perform. Formats:
            "key:ctrl+o"       - Key combination
            "key:Escape"       - Single key
            "click:500,300"    - Left click at coordinates
            "type:hello"       - Type text
            "wait:500ms"       - Wait
        expect: What should happen (in plain English).
                If provided, vision AI verifies this.
        timeout_ms: Wait time after actions before checking result.
        
    Returns:
        PASS/FAIL verdict with vision AI explanation.
        
    Examples:
        test_interaction(["key:ctrl+o"], "A file open dialog should appear")
        test_interaction(["click:538,792"], "The dialog should close")
        test_interaction(["key:ctrl+s"], "A save dialog should appear")
    """
    global _config, _app_running
    
    if not _app_running:
        return "❌ No app running. Call deploy_app() first."
    
    try:
        import time
        
        # Screenshot before
        before_path = _take_screenshot()
        
        # Execute actions
        action_log = []
        for action in actions:
            try:
                execute_action(action)
                action_log.append(f"✓ {action}")
            except ActionParseError as e:
                return f"❌ Invalid action '{action}': {e}"
            except Exception as e:
                return f"❌ Action '{action}' failed: {e}"
            
            # Small delay between actions
            time.sleep(0.1)
        
        # Wait for UI to settle
        time.sleep(timeout_ms / 1000.0)
        
        # Screenshot after
        after_path = _take_screenshot()
        
        # Calculate diff
        diff_stats = _generate_diff_description(before_path, after_path)
        changed = diff_stats["change_ratio"] > 0.001
        change_pct = diff_stats["change_ratio"] * 100
        num_regions = diff_stats["num_regions"]
        
        # Build vision prompt
        actions_desc = " → ".join(actions)
        
        if expect:
            vision_prompt = f"""I performed these actions on a GUI app: {actions_desc}

Expected result: {expect}

Looking at the AFTER screenshot:
1. Did the expected result happen? (YES/NO)
2. What do you see now? (1-2 sentences)
3. If NO, what went wrong?

Be concise and direct."""
        else:
            vision_prompt = f"""I performed these actions on a GUI app: {actions_desc}

What changed in the UI? Describe briefly what you see now."""
        
        # Ask vision model about the result (using after screenshot)
        vision_response = _ask_vision_internal(after_path, vision_prompt)
        
        # Determine pass/fail
        if expect:
            # Check if vision says YES
            response_lower = vision_response.lower()
            passed = "yes" in response_lower[:50] or "successfully" in response_lower or "correctly" in response_lower
            
            if not changed and "no" not in response_lower[:20]:
                # No pixel change but vision didn't say no - might be okay
                passed = passed or "yes" in response_lower
            
            status = "✅ PASS" if passed else "❌ FAIL"
        else:
            # No expectation - just report what happened
            status = "ℹ️ DONE" if changed else "⚠️ NO CHANGE"
        
        # Build response
        change_info = f"{change_pct:.1f}% pixels changed, {num_regions} regions" if changed else "No visual change detected"
        
        return f"""{status}

Actions: {actions_desc}
Result: {change_info}

Vision: {vision_response}"""

    except Exception as e:
        return f"❌ Test failed: {e}"


@mcp.tool()
def ask_vision(question: str) -> str:
    """Ask a question about the current UI state.
    
    Takes a screenshot and asks the vision model your question.
    Use this for inspection, debugging, or understanding the current state.
    
    Args:
        question: What you want to know about the UI.
        
    Returns:
        Vision model's response.
        
    Examples:
        ask_vision("What buttons are visible in the toolbar?")
        ask_vision("Is there an error message displayed?")
        ask_vision("What is the current state of the application?")
    """
    global _app_running
    
    if not _app_running:
        return "❌ No app running. Call deploy_app() first."
    
    try:
        screenshot = _take_screenshot()
        response = _ask_vision_internal(screenshot, question)
        return response
    except Exception as e:
        return f"❌ Vision query failed: {e}"


@mcp.tool()
def run_test(test_name: str) -> str:
    """Run a predefined test from .ui-verdict.yml
    
    Executes a test defined in the config file's 'tests' section.
    
    Args:
        test_name: Name of the test to run (from .ui-verdict.yml)
        
    Returns:
        PASS/FAIL verdict with details.
        
    Example:
        run_test("open-file")  # Runs the 'open-file' test from config
    """
    global _config
    
    if not _config:
        return "❌ No config loaded. Call deploy_app() first."
    
    if test_name not in _config.tests:
        available = list(_config.tests.keys())
        return f"❌ Test '{test_name}' not found.\nAvailable: {', '.join(available)}"
    
    test = _config.tests[test_name]
    actions = test.get("actions", [])
    expect = test.get("expect", None)
    
    if not actions:
        return f"❌ Test '{test_name}' has no actions defined."
    
    return test_interaction(actions, expect)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
