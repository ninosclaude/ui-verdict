"""
Desktop Executor: OrbStack VM backend for QA-Agent.

Handles all interaction with the OrbStack Linux VM:
- Screenshots via scrot
- Input via xdotool
- App lifecycle via pkill/pgrep
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from dataclasses import dataclass

from .executor_protocol import AppStartResult, PixelDiffResult


@dataclass
class VMConfig:
    """VM configuration."""
    name: str = "ui-test"
    display: str = ":99"
    resolution: str = "1920x1080x24"


class DesktopExecutor:
    """Executor for desktop apps running in OrbStack VM.
    
    Implements ExecutorProtocol via duck typing.
    """

    def __init__(self, config: VMConfig | None = None):
        self.config = config or VMConfig()

    def _run_in_vm(self, cmd: str, timeout: int = 30) -> tuple[int, str, str]:
        """Run command in VM via orb."""
        full_cmd = f"orb run -m {self.config.name} bash -c {repr(cmd)}"
        try:
            result = subprocess.run(
                full_cmd, shell=True, capture_output=True, text=True, timeout=timeout
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "timeout"

    def is_available(self) -> bool:
        """Check if VM is accessible."""
        code, out, _ = self._run_in_vm("echo ok", timeout=5)
        return code == 0 and "ok" in out

    def _ensure_display(self) -> bool:
        """Ensure Xvfb and window manager are running."""
        # Xvfb
        code, _, _ = self._run_in_vm(f"pgrep -f 'Xvfb {self.config.display}'")
        if code != 0:
            self._run_in_vm(f"Xvfb {self.config.display} -screen 0 {self.config.resolution} &")
            time.sleep(0.5)

        # Window manager
        code, _, _ = self._run_in_vm("pgrep openbox")
        if code != 0:
            self._run_in_vm(f"export DISPLAY={self.config.display} && openbox &")
            time.sleep(0.3)

        return True

    def take_screenshot(self, prefix: str = "qa") -> str:
        """Take screenshot in VM, return local path."""
        unique_id = uuid.uuid4().hex[:8]
        vm_path = f"/mnt/mac/tmp/{prefix}_{unique_id}.png"
        local_path = f"/tmp/{prefix}_{unique_id}.png"

        code, _, err = self._run_in_vm(
            f"export DISPLAY={self.config.display} && scrot -o {vm_path}"
        )
        if code != 0:
            raise RuntimeError(f"Screenshot failed: {err}")

        for _ in range(20):
            if os.path.exists(local_path):
                return local_path
            time.sleep(0.1)

        raise RuntimeError(f"Screenshot file not found: {local_path}")

    def focus_window(self) -> None:
        """Click center of screen to focus window."""
        self._run_in_vm(
            f"export DISPLAY={self.config.display} && xdotool mousemove 960 540 click 1"
        )
        time.sleep(0.2)

    def execute_action(self, action: str) -> None:
        """Execute an action in the VM."""
        from ..action import parse_action, ActionType
        from ..action import execute_action as base_execute

        parsed = parse_action(action)

        # Handle vision-based click
        if parsed.action_type == ActionType.CLICK_TEXT:
            if not parsed.target_text:
                raise RuntimeError("CLICK_TEXT action missing target_text")
            success, msg = self._click_element_by_text(parsed.target_text)
            if not success:
                raise RuntimeError(msg)
            return

        # Delegate to base action executor (handles key:, type:, wait:, etc.)
        base_execute(parsed)

    def _click_element_by_text(self, target_text: str) -> tuple[bool, str]:
        """Click an element by its visible text/label."""
        from .omniparser import find_element_by_text, is_omniparser_available
        from .vision import ask_vision
        import re

        if not target_text:
            return False, "target_text cannot be empty"

        screenshot = self.take_screenshot("click_target")

        # Try OmniParser first (more reliable)
        if is_omniparser_available():
            element = find_element_by_text(screenshot, target_text)
            if element:
                x, y = element.center
                self._run_in_vm(
                    f"export DISPLAY={self.config.display} && xdotool mousemove {x} {y} click 1"
                )
                return True, f"Clicked '{element.label}' at ({x}, {y}) via OmniParser"
            return False, f"OmniParser: Element '{target_text}' not found"

        # Fall back to vision model
        prompt = f"""Find the UI element labeled "{target_text}" in this screenshot.
Return the bounding box coordinates as: x1,y1,x2,y2
Where (x1,y1) is top-left and (x2,y2) is bottom-right.
Example: 100,50,200,80
If element not found, return exactly: NOT_FOUND"""

        response = ask_vision(screenshot, prompt).strip()

        if "NOT_FOUND" in response.upper():
            return False, f"Element '{target_text}' not found in UI"

        # Parse coordinates
        numbers = re.findall(r"\d+", response)
        if len(numbers) >= 4:
            x1, y1, x2, y2 = int(numbers[0]), int(numbers[1]), int(numbers[2]), int(numbers[3])
            x, y = (x1 + x2) // 2, (y1 + y2) // 2
        elif len(numbers) == 2:
            x, y = int(numbers[0]), int(numbers[1])
        else:
            return False, f"Could not parse coordinates from: {response}"

        self._run_in_vm(
            f"export DISPLAY={self.config.display} && xdotool mousemove {x} {y} click 1"
        )
        return True, f"Clicked at ({x}, {y}) via vision fallback"

    def get_pixel_diff(self, before: str, after: str) -> PixelDiffResult:
        """Calculate pixel difference between screenshots."""
        from ..capture import load_image_gray
        from ..diff.heatmap import generate_diff_mask

        before_img = load_image_gray(before)
        after_img = load_image_gray(after)
        _, stats = generate_diff_mask(before_img, after_img)

        return PixelDiffResult(
            changed_pixels=stats["changed_pixels"],
            change_ratio=stats["change_ratio"],
            num_regions=stats["num_regions"],
            regions=stats.get("regions", [])[:5],
        )

    def start_app(
        self, 
        target: str, 
        name: str, 
        env: dict[str, str] | None = None
    ) -> AppStartResult:
        """Start an application in the VM."""
        # Ensure display is ready
        self._ensure_display()

        # Stop existing
        self._run_in_vm(f"pkill -f {name} 2>/dev/null || true")
        time.sleep(0.3)

        # Build env
        env_parts = [f"DISPLAY={self.config.display}"]
        if env:
            for k, v in env.items():
                env_parts.append(f"{k}={v}")
        env_str = " ".join(env_parts)

        # Start
        cmd = f"export {env_str} && {target} > /tmp/{name}.log 2>&1 &"
        self._run_in_vm(cmd)

        # Wait for startup
        time.sleep(3.0)
        self.focus_window()

        # Verify
        code, out, _ = self._run_in_vm(f"pgrep -f {name}")
        if code != 0:
            _, log, _ = self._run_in_vm(f"tail -30 /tmp/{name}.log")
            return AppStartResult(False, None, f"App not running. Log:\n{log}")

        pid = int(out.strip().split()[0])
        return AppStartResult(True, pid, f"Running with PID {pid}")

    def stop_app(self, name: str) -> None:
        """Stop an application."""
        self._run_in_vm(f"pkill -f {name} 2>/dev/null || true")

    def check_binary_exists(self, path: str) -> bool:
        """Check if binary exists in VM."""
        code, _, _ = self._run_in_vm(f"test -f {path}")
        return code == 0

    def get_app_log(self, name: str, lines: int = 30) -> str:
        """Get app log from VM."""
        _, log, _ = self._run_in_vm(f"tail -{lines} /tmp/{name}.log 2>/dev/null || echo 'No log'")
        return log


# Default instance for backward compatibility
_default_executor: DesktopExecutor | None = None


def get_desktop_executor() -> DesktopExecutor:
    """Get the default desktop executor instance."""
    global _default_executor
    if _default_executor is None:
        _default_executor = DesktopExecutor()
    return _default_executor
