"""
Web Executor: Browser backend for QA-Agent via Midscene.js.

Uses Midscene.js with Playwright for web application testing.
Spawns a Node.js subprocess for Midscene operations.

Status: STUB - Implementation pending
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .executor_protocol import AppStartResult, PixelDiffResult


@dataclass
class WebConfig:
    """Web executor configuration."""
    browser: str = "chromium"  # chromium, firefox, webkit
    headless: bool = True
    viewport_width: int = 1920
    viewport_height: int = 1080
    timeout_ms: int = 30000


class WebExecutor:
    """Executor for web apps via Midscene.js/Playwright.
    
    Implements ExecutorProtocol via duck typing.
    
    Architecture:
    - Python: orchestration, screenshot analysis, reporting
    - Node.js subprocess: Midscene.js for browser control
    
    Communication:
    - Python -> Node: JSON commands via stdin
    - Node -> Python: JSON responses via stdout
    """

    def __init__(self, config: WebConfig | None = None):
        self.config = config or WebConfig()
        self._node_process: subprocess.Popen | None = None
        self._screenshot_dir = Path(tempfile.gettempdir()) / "qa_web_screenshots"
        self._screenshot_dir.mkdir(exist_ok=True)

    def is_available(self) -> bool:
        """Check if Midscene.js and Node.js are available."""
        try:
            # Check Node.js
            result = subprocess.run(
                ["node", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                return False
            
            # Check if Midscene is installed (look for package.json in project)
            midscene_dir = Path(__file__).parent / "midscene"
            if not (midscene_dir / "package.json").exists():
                return False
            
            return True
        except Exception:
            return False

    def _ensure_node_process(self) -> None:
        """Start Node.js subprocess if not running."""
        if self._node_process is not None and self._node_process.poll() is None:
            return  # Already running
        
        midscene_dir = Path(__file__).parent / "midscene"
        
        self._node_process = subprocess.Popen(
            ["node", "executor.js"],
            cwd=midscene_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def _send_command(self, command: dict) -> dict:
        """Send command to Node.js process and get response."""
        self._ensure_node_process()
        
        if self._node_process is None:
            raise RuntimeError("Failed to start Node.js process")
        
        # Send command
        cmd_json = json.dumps(command) + "\n"
        self._node_process.stdin.write(cmd_json)
        self._node_process.stdin.flush()
        
        # Read response
        response_line = self._node_process.stdout.readline()
        return json.loads(response_line)

    def take_screenshot(self, prefix: str = "qa") -> str:
        """Take screenshot of browser, return local path."""
        unique_id = uuid.uuid4().hex[:8]
        local_path = str(self._screenshot_dir / f"{prefix}_{unique_id}.png")
        
        response = self._send_command({
            "action": "screenshot",
            "path": local_path,
        })
        
        if not response.get("success"):
            raise RuntimeError(f"Screenshot failed: {response.get('error')}")
        
        return local_path

    def focus_window(self) -> None:
        """Focus browser tab (no-op for web, tab is always focused)."""
        pass

    def execute_action(self, action: str) -> None:
        """Execute an action in the browser via Midscene.
        
        Uses Midscene's aiAction for natural language commands.
        """
        # Parse action format
        if action.startswith("key:"):
            # Keyboard shortcut
            keys = action[4:]
            response = self._send_command({
                "action": "keyboard",
                "keys": keys,
            })
        elif action.startswith("click:"):
            # Click element by text - use Midscene aiAction
            target = action[6:]
            response = self._send_command({
                "action": "aiAction",
                "instruction": f"Click on '{target}'",
            })
        elif action.startswith("type:"):
            # Type text
            text = action[5:]
            response = self._send_command({
                "action": "type",
                "text": text,
            })
        elif action.startswith("wait:"):
            # Wait milliseconds
            ms = int(action[5:])
            time.sleep(ms / 1000)
            return
        elif action.startswith("goto:"):
            # Navigate to URL
            url = action[5:]
            response = self._send_command({
                "action": "goto",
                "url": url,
            })
        else:
            # Natural language action via Midscene
            response = self._send_command({
                "action": "aiAction",
                "instruction": action,
            })
        
        if not response.get("success"):
            raise RuntimeError(f"Action failed: {response.get('error')}")

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
        """Open URL in browser.
        
        For web executor, target should be a URL.
        """
        try:
            self._ensure_node_process()
            
            response = self._send_command({
                "action": "launch",
                "url": target,
                "config": {
                    "browser": self.config.browser,
                    "headless": self.config.headless,
                    "viewport": {
                        "width": self.config.viewport_width,
                        "height": self.config.viewport_height,
                    },
                },
            })
            
            if not response.get("success"):
                return AppStartResult(False, None, f"Failed to open: {response.get('error')}")
            
            return AppStartResult(True, None, f"Opened {target}")
        except Exception as e:
            return AppStartResult(False, None, str(e))

    def stop_app(self, name: str) -> None:
        """Close browser."""
        if self._node_process is not None:
            try:
                self._send_command({"action": "close"})
            except:
                pass
            self._node_process.terminate()
            self._node_process = None

    def __del__(self):
        """Cleanup Node.js process on destruction."""
        if self._node_process is not None:
            self._node_process.terminate()


# Factory function
_default_executor: WebExecutor | None = None


def get_web_executor() -> WebExecutor:
    """Get the default web executor instance."""
    global _default_executor
    if _default_executor is None:
        _default_executor = WebExecutor()
    return _default_executor
