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
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue

from .executor_protocol import AppStartResult, PixelDiffResult
from .logging_config import get_logger

logger = get_logger(__name__)


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
        self._ready = False
        self._screenshot_dir = Path(tempfile.gettempdir()) / "qa_web_screenshots"
        self._screenshot_dir.mkdir(exist_ok=True)
        self._stdout_queue: Queue[str] = Queue()
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None

    def is_available(self) -> bool:
        """Check if Midscene.js and Node.js are available."""
        try:
            # Check Node.js
            result = subprocess.run(
                ["node", "--version"], capture_output=True, text=True, timeout=5
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

    def _start_stdout_reader(self) -> None:
        """Start background thread to read stdout without blocking."""

        def reader():
            while self._node_process and self._node_process.poll() is None:
                try:
                    if self._node_process.stdout is None:
                        break
                    line = self._node_process.stdout.readline()
                    if not line:
                        break
                    self._stdout_queue.put(line)
                except Exception:
                    break

        self._reader_thread = threading.Thread(target=reader, daemon=True)
        self._reader_thread.start()

    def _start_stderr_reader(self) -> None:
        """Start background thread to read and log stderr."""

        def reader():
            while self._node_process and self._node_process.poll() is None:
                try:
                    if self._node_process.stderr is None:
                        break
                    line = self._node_process.stderr.readline()
                    if not line:
                        break
                    line = line.strip()
                    if line:
                        # Log Node.js stderr as warnings
                        logger.warning(f"[node] {line}")
                except Exception:
                    break

        self._stderr_thread = threading.Thread(target=reader, daemon=True)
        self._stderr_thread.start()

    def _read_line_with_timeout(self, timeout_seconds: float = 30.0) -> str:
        """Read a line from stdout with timeout."""
        try:
            return self._stdout_queue.get(timeout=timeout_seconds)
        except Empty:
            raise TimeoutError(
                f"Node.js process did not respond within {timeout_seconds}s"
            )

    def _read_json_line(self, timeout_seconds: float = 30.0) -> dict:
        """Read lines until we get valid JSON, skip log messages."""
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError(f"No JSON response within {timeout_seconds}s")

            try:
                line = self._read_line_with_timeout(remaining)
            except TimeoutError:
                raise

            line = line.strip()
            if not line:
                continue
            if not line.startswith("{"):
                logger.debug(f"Skipping non-JSON: {line[:100]}")
                continue
            return json.loads(line)

        raise TimeoutError(f"No JSON response within {timeout_seconds}s")

    def _ensure_node_process(self) -> None:
        """Start Node.js subprocess if not running."""
        if (
            self._node_process is not None
            and self._node_process.poll() is None
            and self._ready
        ):
            return  # Already running and ready

        # Kill any existing process
        if self._node_process is not None:
            self._node_process.terminate()
            self._node_process = None

        midscene_dir = Path(__file__).parent / "midscene"

        self._node_process = subprocess.Popen(
            ["node", "executor.js"],
            cwd=midscene_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # Line buffered
        )

        # Start background reader threads
        self._start_stdout_reader()
        self._start_stderr_reader()

        # Wait for ready signal with timeout
        try:
            ready_msg = self._read_json_line(timeout_seconds=10.0)
            if not ready_msg.get("ready"):
                raise RuntimeError(f"Invalid startup message: {ready_msg}")
            self._ready = True
        except TimeoutError as e:
            self._node_process.terminate()
            self._node_process = None
            raise RuntimeError(f"Node.js process failed to start: {e}")

    def _send_command(
        self, command: dict, timeout_seconds: float | None = None
    ) -> dict:
        """Send command to Node.js process and get response."""
        self._ensure_node_process()

        if self._node_process is None:
            raise RuntimeError("Failed to start Node.js process")
        if self._node_process.stdin is None:
            raise RuntimeError("Node process stdin not available")

        timeout = timeout_seconds or (self.config.timeout_ms / 1000)

        # Send command
        cmd_json = json.dumps(command) + "\n"
        logger.debug(f"Sending command: {command['action']}")
        self._node_process.stdin.write(cmd_json)
        self._node_process.stdin.flush()

        # Read response with timeout
        response = self._read_json_line(timeout_seconds=timeout)
        logger.debug(f"Command response: success={response.get('success')}")
        return response

    def take_screenshot(self, prefix: str = "qa") -> str:
        """Take screenshot of browser, return local path."""
        unique_id = uuid.uuid4().hex[:8]
        local_path = str(self._screenshot_dir / f"{prefix}_{unique_id}.png")

        response = self._send_command(
            {
                "action": "screenshot",
                "path": local_path,
            }
        )

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
            response = self._send_command(
                {
                    "action": "keyboard",
                    "keys": keys,
                }
            )
        elif action.startswith("click:"):
            # Click element by text - use Midscene aiAction
            target = action[6:]
            response = self._send_command(
                {
                    "action": "aiAction",
                    "instruction": f"Click on '{target}'",
                }
            )
        elif action.startswith("type:"):
            # Type text
            text = action[5:]
            response = self._send_command(
                {
                    "action": "type",
                    "text": text,
                }
            )
        elif action.startswith("wait:"):
            # Wait milliseconds
            ms = int(action[5:])
            time.sleep(ms / 1000)
            return
        elif action.startswith("goto:"):
            # Navigate to URL
            url = action[5:]
            response = self._send_command(
                {
                    "action": "goto",
                    "url": url,
                }
            )
        else:
            # Natural language action via Midscene
            response = self._send_command(
                {
                    "action": "aiAction",
                    "instruction": action,
                }
            )

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
        self, target: str, name: str, env: dict[str, str] | None = None
    ) -> AppStartResult:
        """Open URL in browser.

        For web executor, target should be a URL.
        """
        logger.info(f"Starting browser: url={target}")
        try:
            self._ensure_node_process()

            response = self._send_command(
                {
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
                }
            )

            if not response.get("success"):
                return AppStartResult(
                    False, None, f"Failed to open: {response.get('error')}"
                )

            return AppStartResult(True, None, f"Opened {target}")
        except Exception as e:
            return AppStartResult(False, None, str(e))

    def stop_app(self, name: str) -> None:
        """Close browser and cleanup."""
        logger.info(f"Stopping browser: {name}")
        if self._node_process is None:
            return

        try:
            # Try graceful close with short timeout
            self._send_command({"action": "close"}, timeout_seconds=5.0)
        except Exception:
            pass

        # Force terminate
        self._node_process.terminate()
        try:
            self._node_process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            self._node_process.kill()

        self._node_process = None
        self._ready = False

    def __del__(self):
        """Cleanup Node.js process on destruction."""
        if self._node_process is None:
            return

        self._node_process.terminate()
        try:
            self._node_process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            self._node_process.kill()
        self._ready = False


# Factory function
_default_executor: WebExecutor | None = None


def get_web_executor() -> WebExecutor:
    """Get the default web executor instance."""
    global _default_executor
    if _default_executor is None:
        _default_executor = WebExecutor()
    return _default_executor
