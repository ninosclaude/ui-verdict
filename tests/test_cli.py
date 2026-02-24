"""Test CLI interface."""

import json
from unittest.mock import Mock, patch

import pytest

from ui_verdict.cli import (
    cmd_baseline_compare,
    cmd_baseline_create,
    cmd_baseline_list,
    cmd_baseline_update,
    cmd_check,
)


def test_cmd_check_success():
    """Test check command with successful result."""
    mock_args = Mock()
    mock_args.url = "https://example.com"
    mock_args.acs = None
    mock_args.platform = "web"
    mock_args.baseline = None
    mock_args.full = False

    mock_result = {
        "overall_status": "PASS",
        "acs_passed": 5,
        "acs_failed": 0,
        "duration_seconds": 12.5,
        "acs": [],
    }

    with patch("ui_verdict.qa_agent.server.run", return_value=json.dumps(mock_result)):
        exit_code = cmd_check(mock_args)
        assert exit_code == 0


def test_cmd_check_failure():
    """Test check command with failed result."""
    mock_args = Mock()
    mock_args.url = "https://example.com"
    mock_args.acs = None
    mock_args.platform = "web"
    mock_args.baseline = None
    mock_args.full = False

    mock_result = {
        "overall_status": "FAIL",
        "acs_passed": 3,
        "acs_failed": 2,
        "duration_seconds": 15.2,
        "acs": [],
        "what_to_fix": "Fix these issues...",
    }

    with patch("ui_verdict.qa_agent.server.run", return_value=json.dumps(mock_result)):
        exit_code = cmd_check(mock_args)
        assert exit_code == 1


def test_cmd_check_warning():
    """Test check command with warning result."""
    mock_args = Mock()
    mock_args.url = "https://example.com"
    mock_args.acs = None
    mock_args.platform = "web"
    mock_args.baseline = None
    mock_args.full = False

    mock_result = {
        "overall_status": "WARN",
        "acs_passed": 4,
        "acs_failed": 0,
        "duration_seconds": 10.0,
        "acs": [{"status": "WARN"}],
    }

    with patch("ui_verdict.qa_agent.server.run", return_value=json.dumps(mock_result)):
        exit_code = cmd_check(mock_args)
        assert exit_code == 0


def test_cmd_baseline_create_success():
    """Test baseline create command."""
    mock_args = Mock()
    mock_args.name = "test-baseline"
    mock_args.url = "https://example.com"
    mock_args.platform = "web"

    mock_result = {
        "success": True,
        "screenshot": "/path/to/screenshot.png",
    }

    with patch(
        "ui_verdict.qa_agent.server.baseline_create",
        return_value=json.dumps(mock_result),
    ):
        exit_code = cmd_baseline_create(mock_args)
        assert exit_code == 0


def test_cmd_baseline_create_failure():
    """Test baseline create command with failure."""
    mock_args = Mock()
    mock_args.name = "test-baseline"
    mock_args.url = "https://example.com"
    mock_args.platform = "web"

    mock_result = {"error": "Failed to open URL"}

    with patch(
        "ui_verdict.qa_agent.server.baseline_create",
        return_value=json.dumps(mock_result),
    ):
        exit_code = cmd_baseline_create(mock_args)
        assert exit_code == 1


def test_cmd_baseline_compare_no_change():
    """Test baseline compare with no change."""
    mock_args = Mock()
    mock_args.name = "test-baseline"
    mock_args.url = None
    mock_args.platform = "web"

    mock_result = {
        "success": True,
        "result": {
            "verdict": "no_change",
            "change_ratio": 0.001,
        },
    }

    with patch(
        "ui_verdict.qa_agent.server.baseline_compare",
        return_value=json.dumps(mock_result),
    ):
        exit_code = cmd_baseline_compare(mock_args)
        assert exit_code == 0


def test_cmd_baseline_compare_regression():
    """Test baseline compare with regression."""
    mock_args = Mock()
    mock_args.name = "test-baseline"
    mock_args.url = None
    mock_args.platform = "web"

    mock_result = {
        "success": True,
        "result": {
            "verdict": "regression",
            "change_ratio": 0.15,
            "ai_explanation": "Layout is broken",
        },
    }

    with patch(
        "ui_verdict.qa_agent.server.baseline_compare",
        return_value=json.dumps(mock_result),
    ):
        exit_code = cmd_baseline_compare(mock_args)
        assert exit_code == 1


def test_cmd_baseline_compare_intentional():
    """Test baseline compare with intentional change."""
    mock_args = Mock()
    mock_args.name = "test-baseline"
    mock_args.url = None
    mock_args.platform = "web"

    mock_result = {
        "success": True,
        "result": {
            "verdict": "intentional",
            "change_ratio": 0.25,
            "ai_explanation": "New feature added",
        },
    }

    with patch(
        "ui_verdict.qa_agent.server.baseline_compare",
        return_value=json.dumps(mock_result),
    ):
        exit_code = cmd_baseline_compare(mock_args)
        assert exit_code == 0


def test_cmd_baseline_list_empty():
    """Test baseline list with no baselines."""
    mock_args = Mock()

    mock_result = {"count": 0, "baselines": []}

    with patch(
        "ui_verdict.qa_agent.server.baseline_list", return_value=json.dumps(mock_result)
    ):
        exit_code = cmd_baseline_list(mock_args)
        assert exit_code == 0


def test_cmd_baseline_list_with_baselines():
    """Test baseline list with baselines."""
    mock_args = Mock()

    mock_result = {
        "count": 2,
        "baselines": [
            {
                "name": "test1",
                "url": "https://example.com",
                "viewport": [1920, 1080],
                "updated_at": "2026-02-24T20:00:00",
            },
            {
                "name": "test2",
                "url": "https://test.com",
                "viewport": [1280, 720],
                "updated_at": "2026-02-24T21:00:00",
            },
        ],
    }

    with patch(
        "ui_verdict.qa_agent.server.baseline_list", return_value=json.dumps(mock_result)
    ):
        exit_code = cmd_baseline_list(mock_args)
        assert exit_code == 0


def test_cmd_baseline_update_success():
    """Test baseline update command."""
    mock_args = Mock()
    mock_args.name = "test-baseline"
    mock_args.url = None
    mock_args.platform = "web"

    mock_result = {"success": True}

    with patch(
        "ui_verdict.qa_agent.server.baseline_update",
        return_value=json.dumps(mock_result),
    ):
        exit_code = cmd_baseline_update(mock_args)
        assert exit_code == 0


def test_cmd_baseline_update_failure():
    """Test baseline update command with failure."""
    mock_args = Mock()
    mock_args.name = "test-baseline"
    mock_args.url = None
    mock_args.platform = "web"

    mock_result = {"error": "Baseline not found"}

    with patch(
        "ui_verdict.qa_agent.server.baseline_update",
        return_value=json.dumps(mock_result),
    ):
        exit_code = cmd_baseline_update(mock_args)
        assert exit_code == 1


def test_cmd_check_with_acs():
    """Test check command with custom acceptance criteria."""
    mock_args = Mock()
    mock_args.url = "https://example.com"
    mock_args.acs = "AC1,AC2,AC3"
    mock_args.platform = "web"
    mock_args.baseline = None
    mock_args.full = False

    mock_result = {
        "overall_status": "PASS",
        "acs_passed": 3,
        "acs_failed": 0,
        "duration_seconds": 10.0,
        "acs": [],
    }

    with patch("ui_verdict.qa_agent.server.run") as mock_run:
        mock_run.return_value = json.dumps(mock_result)
        exit_code = cmd_check(mock_args)

        # Verify that acs were split correctly
        call_args = mock_run.call_args
        assert call_args[1]["acs"] == ["AC1", "AC2", "AC3"]
        assert exit_code == 0


def test_cmd_check_with_baseline():
    """Test check command with baseline mode."""
    mock_args = Mock()
    mock_args.url = "https://example.com"
    mock_args.acs = None
    mock_args.platform = "web"
    mock_args.baseline = "my-baseline"
    mock_args.full = False

    mock_result = {
        "overall_status": "PASS",
        "acs_passed": 1,
        "acs_failed": 0,
        "duration_seconds": 5.0,
        "acs": [],
    }

    with patch("ui_verdict.qa_agent.server.run") as mock_run:
        mock_run.return_value = json.dumps(mock_result)
        exit_code = cmd_check(mock_args)

        # Verify baseline mode is enabled
        call_args = mock_run.call_args
        assert call_args[1]["baseline_mode"] is True
        assert call_args[1]["baseline_name"] == "my-baseline"
        assert exit_code == 0


def test_cmd_check_full_mode():
    """Test check command with full mode (no skip levels)."""
    mock_args = Mock()
    mock_args.url = "https://example.com"
    mock_args.acs = None
    mock_args.platform = "web"
    mock_args.baseline = None
    mock_args.full = True

    mock_result = {
        "overall_status": "PASS",
        "acs_passed": 10,
        "acs_failed": 0,
        "duration_seconds": 30.0,
        "acs": [],
    }

    with patch("ui_verdict.qa_agent.server.run") as mock_run:
        mock_run.return_value = json.dumps(mock_result)
        exit_code = cmd_check(mock_args)

        # Verify no skip levels when full=True
        call_args = mock_run.call_args
        assert call_args[1]["skip_levels"] == []
        assert exit_code == 0
