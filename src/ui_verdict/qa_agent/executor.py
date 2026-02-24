"""
Executor: VM operations for QA-Agent.

Handles all interaction with the OrbStack VM:
- Screenshots
- Input (keyboard, mouse)
- App lifecycle
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..capture import load_image_gray
from ..action import execute_action as _execute_action, ActionParseError


@dataclass
class VMConfig:
    """VM configuration."""

    name: str = "ui-test"
    display: str = ":99"
    resolution: str = "1920x1080x24"


_vm_config = VMConfig()


def run_in_vm(cmd: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run command in VM via orb."""
    full_cmd = f"orb run -m {_vm_config.name} bash -c {repr(cmd)}"
    try:
        result = subprocess.run(
            full_cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


def vm_available() -> bool:
    """Check if VM is accessible."""
    code, out, _ = run_in_vm("echo ok", timeout=5)
    return code == 0 and "ok" in out


def ensure_display() -> bool:
    """Ensure Xvfb and window manager are running."""
    # Xvfb
    code, _, _ = run_in_vm(f"pgrep -f 'Xvfb {_vm_config.display}'")
    if code != 0:
        run_in_vm(f"Xvfb {_vm_config.display} -screen 0 {_vm_config.resolution} &")
        time.sleep(0.5)

    # Window manager
    code, _, _ = run_in_vm("pgrep openbox")
    if code != 0:
        run_in_vm(f"export DISPLAY={_vm_config.display} && openbox &")
        time.sleep(0.3)

    return True


def take_screenshot(prefix: str = "qa") -> str:
    """Take screenshot in VM, return local path."""
    unique_id = uuid.uuid4().hex[:8]
    vm_path = f"/mnt/mac/tmp/{prefix}_{unique_id}.png"
    local_path = f"/tmp/{prefix}_{unique_id}.png"

    code, _, err = run_in_vm(
        f"export DISPLAY={_vm_config.display} && scrot -o {vm_path}"
    )
    if code != 0:
        raise RuntimeError(f"Screenshot failed: {err}")

    for _ in range(20):
        if os.path.exists(local_path):
            return local_path
        time.sleep(0.1)

    raise RuntimeError(f"Screenshot file not found: {local_path}")


def focus_window():
    """Click center of screen to focus window."""
    run_in_vm(
        f"export DISPLAY={_vm_config.display} && xdotool mousemove 960 540 click 1"
    )
    time.sleep(0.2)


def _parse_coordinates(response: str) -> tuple[int | None, int | None]:
    """Parse coordinates from vision model response.

    Handles formats:
    - "450,320" (center point)
    - "100,50,200,80" (bounding box x1,y1,x2,y2)
    - "[[450,320,480,350]]" (JSON-like bounding box)
    - "[100, 50, 200, 80]" (JSON array)
    """
    import re

    # Clean up response - extract numbers
    numbers = re.findall(r"\d+", response)

    if not numbers:
        return None, None

    coords = [int(n) for n in numbers]

    # 2 numbers = center point (x, y)
    if len(coords) == 2:
        return coords[0], coords[1]

    # 4 numbers = bounding box (x1, y1, x2, y2) - calculate center
    if len(coords) >= 4:
        x1, y1, x2, y2 = coords[0], coords[1], coords[2], coords[3]
        center_x = (x1 + x2) // 2
        center_y = (y1 + y2) // 2
        return center_x, center_y

    # 1 number or 3 numbers - invalid
    return None, None


def click_element_by_text(target_text: str) -> tuple[bool, str]:
    """Click an element by its visible text/label.

    Uses OmniParser if available, falls back to vision model.

    Args:
        target_text: The text/label to find and click

    Returns:
        (success, message)
    """
    from .omniparser import find_element_by_text, is_omniparser_available

    if not target_text:
        return False, "target_text cannot be empty"

    screenshot = take_screenshot("click_target")

    # Try OmniParser first (more reliable)
    if is_omniparser_available():
        element = find_element_by_text(screenshot, target_text)
        if element:
            x, y = element.center
            run_in_vm(
                f"export DISPLAY={_vm_config.display} && xdotool mousemove {x} {y} click 1"
            )
            return True, f"Clicked '{element.label}' at ({x}, {y}) via OmniParser"
        return False, f"OmniParser: Element '{target_text}' not found"

    # Fall back to vision model
    from .vision import ask_vision

    prompt = f"""Find the UI element labeled "{target_text}" in this screenshot.
Return the bounding box coordinates as: x1,y1,x2,y2
Where (x1,y1) is top-left and (x2,y2) is bottom-right.
Example: 100,50,200,80
If element not found, return exactly: NOT_FOUND"""

    response = ask_vision(screenshot, prompt)
    response = response.strip()

    if "NOT_FOUND" in response.upper():
        return False, f"Element '{target_text}' not found in UI"

    # Try to extract coordinates from various formats
    x, y = _parse_coordinates(response)

    if x is None or y is None:
        return False, f"Could not parse coordinates from: {response}"

    # Execute click
    run_in_vm(
        f"export DISPLAY={_vm_config.display} && xdotool mousemove {x} {y} click 1"
    )
    return True, f"Clicked at ({x}, {y}) via vision fallback"


def execute_action(action: str) -> None:
    """Execute an action in the VM.

    Handles all action types including vision-based CLICK_TEXT.
    """
    from ..action import parse_action, ActionType

    # Parse if string
    if isinstance(action, str):
        parsed = parse_action(action)
    else:
        parsed = action

    # Handle vision-based click
    if parsed.action_type == ActionType.CLICK_TEXT:
        if not parsed.target_text:
            raise RuntimeError("CLICK_TEXT action missing target_text")
        success, msg = click_element_by_text(parsed.target_text)
        if not success:
            raise RuntimeError(msg)
        return

    # Delegate other actions to base implementation
    _execute_action(parsed)


def get_pixel_diff(before_path: str, after_path: str) -> dict:
    """Calculate pixel difference between screenshots."""
    from ..diff.heatmap import generate_diff_mask

    before = load_image_gray(before_path)
    after = load_image_gray(after_path)
    _, stats = generate_diff_mask(before, after)

    return {
        "changed_pixels": stats["changed_pixels"],
        "change_ratio": stats["change_ratio"],
        "num_regions": stats["num_regions"],
        "regions": stats.get("regions", [])[:5],
    }


def start_app(
    binary: str, name: str, env: dict[str, str] | None = None
) -> tuple[bool, int | None, str]:
    """Start an application in the VM.

    Returns:
        (success, pid, message)
    """
    # Stop existing
    run_in_vm(f"pkill -f {name} 2>/dev/null || true")
    time.sleep(0.3)

    # Build env
    env_parts = [f"DISPLAY={_vm_config.display}"]
    if env:
        for k, v in env.items():
            env_parts.append(f"{k}={v}")
    env_str = " ".join(env_parts)

    # Start
    cmd = f"export {env_str} && {binary} > /tmp/{name}.log 2>&1 &"
    run_in_vm(cmd)

    # Wait for startup
    time.sleep(3.0)
    focus_window()

    # Verify
    code, out, _ = run_in_vm(f"pgrep -f {name}")
    if code != 0:
        _, log, _ = run_in_vm(f"tail -30 /tmp/{name}.log")
        return False, None, f"App not running. Log:\n{log}"

    pid = int(out.strip().split()[0])
    return True, pid, f"Running with PID {pid}"


def stop_app(name: str) -> None:
    """Stop an application."""
    run_in_vm(f"pkill -f {name} 2>/dev/null || true")


def check_binary_exists(path: str) -> bool:
    """Check if binary exists in VM."""
    code, _, _ = run_in_vm(f"test -f {path}")
    return code == 0


def get_app_log(name: str, lines: int = 30) -> str:
    """Get app log from VM."""
    _, log, _ = run_in_vm(f"tail -{lines} /tmp/{name}.log 2>/dev/null || echo 'No log'")
    return log
