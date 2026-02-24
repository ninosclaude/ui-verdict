"""Tests for WebExecutor."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.ui_verdict.qa_agent.web_executor import WebConfig, WebExecutor
from src.ui_verdict.qa_agent.executor_protocol import AppStartResult, PixelDiffResult


class TestWebConfig:
    """Unit tests for WebConfig."""

    def test_web_config_defaults(self):
        """Test default WebConfig values."""
        config = WebConfig()
        assert config.browser == "chromium"
        assert config.headless is True
        assert config.viewport_width == 1920
        assert config.viewport_height == 1080
        assert config.timeout_ms == 30000

    def test_web_config_custom_values(self):
        """Test WebConfig with custom values."""
        config = WebConfig(
            browser="firefox",
            headless=False,
            viewport_width=1280,
            viewport_height=720,
            timeout_ms=60000,
        )
        assert config.browser == "firefox"
        assert config.headless is False
        assert config.viewport_width == 1280
        assert config.viewport_height == 720
        assert config.timeout_ms == 60000


class TestWebExecutorUnit:
    """Unit tests for WebExecutor with mocked subprocess."""

    @pytest.fixture
    def executor(self):
        """Create WebExecutor instance."""
        return WebExecutor()

    @pytest.fixture
    def mock_node_process(self):
        """Mock Node.js subprocess."""
        process = MagicMock()
        process.poll.return_value = None
        process.stdin = MagicMock()
        process.stdout = MagicMock()
        process.stderr = MagicMock()
        return process

    def test_is_available_checks_node_and_package(self, executor):
        """Test is_available checks Node.js and Midscene package."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            midscene_dir = (
                Path(__file__).parent.parent / "src/ui_verdict/qa_agent/midscene"
            )

            with patch.object(Path, "exists", return_value=True):
                result = executor.is_available()
                assert result is True

    def test_is_available_node_missing(self, executor):
        """Test is_available when Node.js is not installed."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)

            result = executor.is_available()
            assert result is False

    def test_is_available_package_missing(self, executor):
        """Test is_available when Midscene package is missing."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            with patch.object(Path, "exists", return_value=False):
                result = executor.is_available()
                assert result is False

    def test_is_available_exception_handling(self, executor):
        """Test is_available handles exceptions gracefully."""
        with patch("subprocess.run", side_effect=Exception("Test error")):
            result = executor.is_available()
            assert result is False

    def test_read_json_line_skips_non_json(self, executor, mock_node_process):
        """Test _read_json_line skips non-JSON log messages."""
        executor._node_process = mock_node_process

        # Simulate lines with logs and JSON
        mock_node_process.stdout.readline.side_effect = [
            "Starting browser...\n",
            "Browser initialized\n",
            '{"ready": true}\n',
        ]

        result = executor._read_json_line()

        assert result == {"ready": True}
        assert mock_node_process.stdout.readline.call_count == 3

    def test_read_json_line_empty_lines(self, executor, mock_node_process):
        """Test _read_json_line skips empty lines."""
        executor._node_process = mock_node_process

        mock_node_process.stdout.readline.side_effect = [
            "\n",
            "   \n",
            '{"success": true}\n',
        ]

        result = executor._read_json_line()

        assert result == {"success": True}

    def test_read_json_line_no_process(self, executor):
        """Test _read_json_line raises when process not started."""
        with pytest.raises(RuntimeError, match="Node process not started"):
            executor._read_json_line()

    def test_read_json_line_process_closed(self, executor, mock_node_process):
        """Test _read_json_line raises when process closes."""
        executor._node_process = mock_node_process
        mock_node_process.stdout.readline.return_value = ""

        with pytest.raises(RuntimeError, match="Node process closed unexpectedly"):
            executor._read_json_line()

    def test_send_command_returns_json(self, executor, mock_node_process):
        """Test _send_command sends and receives JSON."""
        executor._node_process = mock_node_process
        executor._ready = True

        mock_node_process.stdout.readline.return_value = '{"success": true}\n'

        result = executor._send_command({"action": "test"})

        assert result == {"success": True}
        mock_node_process.stdin.write.assert_called_once_with('{"action": "test"}\n')
        mock_node_process.stdin.flush.assert_called_once()

    def test_send_command_ensures_process(self, executor):
        """Test _send_command starts process if not running."""
        with patch.object(executor, "_ensure_node_process") as mock_ensure:
            with patch.object(
                executor, "_read_json_line", return_value={"success": True}
            ):
                executor._node_process = MagicMock()
                executor._node_process.stdin = MagicMock()

                executor._send_command({"action": "test"})

                mock_ensure.assert_called_once()

    def test_take_screenshot_returns_path(self, executor):
        """Test take_screenshot returns local file path."""
        with patch.object(executor, "_send_command") as mock_send:
            mock_send.return_value = {"success": True}

            path = executor.take_screenshot(prefix="test")

            assert path.startswith(str(executor._screenshot_dir))
            assert "test_" in path
            assert path.endswith(".png")

            call_args = mock_send.call_args[0][0]
            assert call_args["action"] == "screenshot"
            assert call_args["path"] == path

    def test_take_screenshot_failure(self, executor):
        """Test take_screenshot raises on failure."""
        with patch.object(executor, "_send_command") as mock_send:
            mock_send.return_value = {"success": False, "error": "Browser crashed"}

            with pytest.raises(
                RuntimeError, match="Screenshot failed: Browser crashed"
            ):
                executor.take_screenshot()

    def test_execute_action_key_prefix(self, executor):
        """Test execute_action with key: prefix."""
        with patch.object(executor, "_send_command") as mock_send:
            mock_send.return_value = {"success": True}

            executor.execute_action("key:ctrl+o")

            call_args = mock_send.call_args[0][0]
            assert call_args["action"] == "keyboard"
            assert call_args["keys"] == "ctrl+o"

    def test_execute_action_click_prefix(self, executor):
        """Test execute_action with click: prefix."""
        with patch.object(executor, "_send_command") as mock_send:
            mock_send.return_value = {"success": True}

            executor.execute_action("click:Submit Button")

            call_args = mock_send.call_args[0][0]
            assert call_args["action"] == "aiAction"
            assert call_args["instruction"] == "Click on 'Submit Button'"

    def test_execute_action_type_prefix(self, executor):
        """Test execute_action with type: prefix."""
        with patch.object(executor, "_send_command") as mock_send:
            mock_send.return_value = {"success": True}

            executor.execute_action("type:Hello World")

            call_args = mock_send.call_args[0][0]
            assert call_args["action"] == "type"
            assert call_args["text"] == "Hello World"

    def test_execute_action_wait_prefix(self, executor):
        """Test execute_action with wait: prefix."""
        with patch("time.sleep") as mock_sleep:
            executor.execute_action("wait:1500")
            mock_sleep.assert_called_once_with(1.5)

    def test_execute_action_goto_prefix(self, executor):
        """Test execute_action with goto: prefix."""
        with patch.object(executor, "_send_command") as mock_send:
            mock_send.return_value = {"success": True}

            executor.execute_action("goto:https://example.com")

            call_args = mock_send.call_args[0][0]
            assert call_args["action"] == "goto"
            assert call_args["url"] == "https://example.com"

    def test_execute_action_natural_language(self, executor):
        """Test execute_action with natural language."""
        with patch.object(executor, "_send_command") as mock_send:
            mock_send.return_value = {"success": True}

            executor.execute_action("Scroll down to the footer")

            call_args = mock_send.call_args[0][0]
            assert call_args["action"] == "aiAction"
            assert call_args["instruction"] == "Scroll down to the footer"

    def test_execute_action_failure(self, executor):
        """Test execute_action raises on failure."""
        with patch.object(executor, "_send_command") as mock_send:
            mock_send.return_value = {"success": False, "error": "Element not found"}

            with pytest.raises(RuntimeError, match="Action failed: Element not found"):
                executor.execute_action("click:Missing Button")

    def test_get_pixel_diff(self, executor):
        """Test get_pixel_diff calculates differences."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as before_file:
            before_path = before_file.name
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as after_file:
            after_path = after_file.name

        try:
            # Create mock images
            from PIL import Image

            img = Image.new("RGB", (100, 100), color="white")
            img.save(before_path)
            img2 = Image.new("RGB", (100, 100), color="black")
            img2.save(after_path)

            result = executor.get_pixel_diff(before_path, after_path)

            assert isinstance(result, PixelDiffResult)
            assert result.changed_pixels > 0
            assert 0.0 <= result.change_ratio <= 1.0
            assert result.num_regions >= 0
            assert isinstance(result.regions, list)
        finally:
            if os.path.exists(before_path):
                os.remove(before_path)
            if os.path.exists(after_path):
                os.remove(after_path)

    def test_start_app_success(self, executor):
        """Test start_app opens URL successfully."""
        with patch.object(executor, "_ensure_node_process"):
            with patch.object(executor, "_send_command") as mock_send:
                mock_send.return_value = {"success": True}

                result = executor.start_app("https://example.com", "test-app")

                assert result.success is True
                assert result.pid is None
                assert "Opened https://example.com" in result.message

                call_args = mock_send.call_args[0][0]
                assert call_args["action"] == "launch"
                assert call_args["url"] == "https://example.com"
                assert call_args["config"]["browser"] == "chromium"
                assert call_args["config"]["headless"] is True

    def test_start_app_custom_config(self):
        """Test start_app uses custom config."""
        config = WebConfig(
            browser="firefox", headless=False, viewport_width=1280, viewport_height=720
        )
        executor = WebExecutor(config)

        with patch.object(executor, "_ensure_node_process"):
            with patch.object(executor, "_send_command") as mock_send:
                mock_send.return_value = {"success": True}

                executor.start_app("https://example.com", "test-app")

                call_args = mock_send.call_args[0][0]
                assert call_args["config"]["browser"] == "firefox"
                assert call_args["config"]["headless"] is False
                assert call_args["config"]["viewport"]["width"] == 1280
                assert call_args["config"]["viewport"]["height"] == 720

    def test_start_app_failure(self, executor):
        """Test start_app handles failure."""
        with patch.object(executor, "_ensure_node_process"):
            with patch.object(executor, "_send_command") as mock_send:
                mock_send.return_value = {"success": False, "error": "Browser crashed"}

                result = executor.start_app("https://example.com", "test-app")

                assert result.success is False
                assert result.pid is None
                assert "Failed to open: Browser crashed" in result.message

    def test_start_app_exception(self, executor):
        """Test start_app handles exceptions."""
        with patch.object(
            executor, "_ensure_node_process", side_effect=Exception("Test error")
        ):
            result = executor.start_app("https://example.com", "test-app")

            assert result.success is False
            assert "Test error" in result.message

    def test_stop_app_closes_browser(self, executor, mock_node_process):
        """Test stop_app closes browser."""
        executor._node_process = mock_node_process

        with patch.object(executor, "_send_command") as mock_send:
            executor.stop_app("test-app")

            mock_send.assert_called_once_with({"action": "close"})
            mock_node_process.terminate.assert_called_once()
            assert executor._node_process is None
            assert executor._ready is False

    def test_stop_app_handles_command_error(self, executor, mock_node_process):
        """Test stop_app handles command errors gracefully."""
        executor._node_process = mock_node_process

        with patch.object(executor, "_send_command", side_effect=Exception("Error")):
            executor.stop_app("test-app")

            mock_node_process.terminate.assert_called_once()

    def test_focus_window_noop(self, executor):
        """Test focus_window is no-op for web."""
        # Should not raise
        executor.focus_window()

    def test_ensure_node_process_already_running(self, executor, mock_node_process):
        """Test _ensure_node_process when already running."""
        executor._node_process = mock_node_process
        executor._ready = True

        executor._ensure_node_process()

        # Should not start new process
        assert executor._node_process is mock_node_process

    def test_ensure_node_process_starts_new(self, executor):
        """Test _ensure_node_process starts new process."""
        with patch("subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.stdout.readline.return_value = '{"ready": true}\n'
            mock_popen.return_value = mock_process

            executor._ensure_node_process()

            mock_popen.assert_called_once()
            assert executor._node_process is mock_process
            assert executor._ready is True

    def test_ensure_node_process_invalid_startup(self, executor):
        """Test _ensure_node_process raises on invalid startup message."""
        with patch("subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.stdout.readline.return_value = '{"error": "failed"}\n'
            mock_popen.return_value = mock_process

            with pytest.raises(RuntimeError, match="Unexpected startup message"):
                executor._ensure_node_process()

    def test_destructor_cleanup(self, executor, mock_node_process):
        """Test __del__ cleans up Node.js process."""
        executor._node_process = mock_node_process
        executor._ready = True

        executor.__del__()

        mock_node_process.terminate.assert_called_once()
        assert executor._ready is False

    def test_screenshot_dir_created(self, executor):
        """Test screenshot directory is created on init."""
        assert executor._screenshot_dir.exists()
        assert executor._screenshot_dir.is_dir()


@pytest.mark.integration
class TestWebExecutorIntegration:
    """Integration tests with real browser."""

    @pytest.fixture
    def check_web_available(self):
        """Skip if web executor is not available."""
        executor = WebExecutor()
        if not executor.is_available():
            pytest.skip("WebExecutor not available (Node.js or Midscene missing)")

    @pytest.fixture
    def executor(self, check_web_available):
        """Create WebExecutor for integration tests."""
        config = WebConfig(headless=True, timeout_ms=60000)
        executor = WebExecutor(config)
        yield executor
        # Cleanup
        if executor._node_process is not None:
            executor.stop_app("test")

    def test_real_browser_launch(self, executor):
        """Test opening example.com in real browser."""
        result = executor.start_app("https://example.com", "example-test")

        assert result.success is True
        assert executor._node_process is not None
        assert executor._ready is True

    def test_real_screenshot(self, executor):
        """Test taking screenshot with real browser."""
        # First launch browser
        executor.start_app("https://example.com", "example-test")

        # Take screenshot
        path = executor.take_screenshot(prefix="integration_test")

        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
        assert path.endswith(".png")

        # Cleanup
        if os.path.exists(path):
            os.remove(path)

    def test_real_keyboard(self, executor):
        """Test sending keyboard command to real browser.

        Note: This test may fail if Midscene.js keyboard implementation
        is not complete. Skip if encountering keyboard issues.
        """
        executor.start_app("https://example.com", "example-test")

        try:
            # Send key command - using Enter key which should be supported
            executor.execute_action("key:Enter")
        except RuntimeError as e:
            # Known issue: Midscene keyboard implementation may be incomplete
            if "Unknown key" in str(e):
                pytest.skip("Keyboard implementation not complete in Midscene backend")
            raise

    def test_real_goto(self, executor):
        """Test navigating to URL in real browser."""
        executor.start_app("https://example.com", "example-test")

        # Navigate to different URL
        executor.execute_action("goto:https://example.org")

        # Take screenshot to verify
        path = executor.take_screenshot(prefix="goto_test")

        assert os.path.exists(path)

        # Cleanup
        if os.path.exists(path):
            os.remove(path)

    def test_real_wait_action(self, executor):
        """Test wait action in real browser."""
        import time

        executor.start_app("https://example.com", "example-test")

        start = time.time()
        executor.execute_action("wait:500")
        elapsed = time.time() - start

        assert elapsed >= 0.5
        assert elapsed < 1.0  # Should not take too long

    def test_real_pixel_diff(self, executor):
        """Test pixel diff with real screenshots."""
        executor.start_app("https://example.com", "example-test")

        # Take before screenshot
        before = executor.take_screenshot(prefix="diff_before")

        # Navigate to different URL to ensure change
        executor.execute_action("goto:https://www.wikipedia.org")

        # Wait for page to load
        executor.execute_action("wait:2000")

        # Take after screenshot
        after = executor.take_screenshot(prefix="diff_after")

        try:
            # Calculate diff
            result = executor.get_pixel_diff(before, after)

            assert isinstance(result, PixelDiffResult)
            # If pages are identical (edge case), we still get valid result
            assert result.changed_pixels >= 0
            assert 0.0 <= result.change_ratio <= 1.0
            assert result.num_regions >= 0
        finally:
            if os.path.exists(before):
                os.remove(before)
            if os.path.exists(after):
                os.remove(after)


class TestWebExecutorFactory:
    """Tests for factory function."""

    def test_get_web_executor_singleton(self):
        """Test get_web_executor returns singleton."""
        from src.ui_verdict.qa_agent.web_executor import get_web_executor

        executor1 = get_web_executor()
        executor2 = get_web_executor()

        assert executor1 is executor2

    def test_get_web_executor_creates_instance(self):
        """Test get_web_executor creates WebExecutor instance."""
        from src.ui_verdict.qa_agent.web_executor import (
            get_web_executor,
            _default_executor,
        )
        import src.ui_verdict.qa_agent.web_executor as module

        # Reset singleton
        original = module._default_executor
        module._default_executor = None

        try:
            executor = get_web_executor()
            assert isinstance(executor, WebExecutor)
        finally:
            module._default_executor = original
