"""Tests for action parsing module."""

import pytest

from ui_verdict.action import (
    parse_action,
    ActionType,
    ActionParseError,
    ParsedAction,
)


class TestParseAction:
    """Tests for parse_action function."""

    def test_key_simple(self):
        """Test simple key press."""
        result = parse_action("key:w")
        assert result.action_type == ActionType.KEY
        assert result.key == "w"
        assert result.hold_ms == 50

    def test_key_special(self):
        """Test special key."""
        result = parse_action("key:Return")
        assert result.action_type == ActionType.KEY
        assert result.key == "Return"

    def test_key_combination(self):
        """Test key combination."""
        result = parse_action("key:ctrl+o")
        assert result.action_type == ActionType.KEY
        assert result.key == "ctrl+o"

    def test_key_with_hold(self):
        """Test key with hold duration."""
        result = parse_action("key:w:hold:500ms")
        assert result.action_type == ActionType.KEY
        assert result.key == "w"
        assert result.hold_ms == 500

    def test_click(self):
        """Test left click."""
        result = parse_action("click:500,300")
        assert result.action_type == ActionType.CLICK
        assert result.x == 500
        assert result.y == 300

    def test_rightclick(self):
        """Test right click."""
        result = parse_action("rightclick:200,100")
        assert result.action_type == ActionType.RIGHTCLICK
        assert result.x == 200
        assert result.y == 100

    def test_type_simple(self):
        """Test typing text."""
        result = parse_action("type:hello world")
        assert result.action_type == ActionType.TYPE
        assert result.text == "hello world"

    def test_type_with_colons(self):
        """Test typing text with colons."""
        result = parse_action("type:time:12:30")
        assert result.action_type == ActionType.TYPE
        assert result.text == "time:12:30"

    def test_wait(self):
        """Test wait action."""
        result = parse_action("wait:500ms")
        assert result.action_type == ActionType.WAIT
        assert result.wait_ms == 500

    def test_wait_without_ms_suffix(self):
        """Test wait without ms suffix."""
        result = parse_action("wait:300")
        assert result.action_type == ActionType.WAIT
        assert result.wait_ms == 300

    def test_click_text(self):
        """Test text-based click."""
        result = parse_action("click:Open")
        assert result.action_type == ActionType.CLICK_TEXT
        assert result.target_text == "Open"

    def test_click_text_multi_word(self):
        """Test text-based click with multiple words."""
        result = parse_action("click:Save File")
        assert result.action_type == ActionType.CLICK_TEXT
        assert result.target_text == "Save File"

    def test_click_coordinates_not_text(self):
        """Test that click with comma is parsed as coordinates, not text."""
        result = parse_action("click:100,200")
        assert result.action_type == ActionType.CLICK
        assert result.x == 100
        assert result.y == 200
        assert result.target_text is None


class TestParseActionErrors:
    """Tests for error handling in parse_action."""

    def test_empty_action(self):
        """Test empty action string."""
        with pytest.raises(ActionParseError):
            parse_action("")

    def test_key_without_name(self):
        """Test key without key name."""
        with pytest.raises(ActionParseError):
            parse_action("key:")

    def test_click_invalid_coords(self):
        """Test click with invalid coordinates."""
        with pytest.raises(ActionParseError):
            parse_action("click:abc,def")

    def test_click_missing_coords(self):
        """Test click without coordinates."""
        with pytest.raises(ActionParseError):
            parse_action("click:")

    def test_unknown_action(self):
        """Test unknown action type."""
        with pytest.raises(ActionParseError):
            parse_action("unknown:something")

    def test_invalid_hold_duration(self):
        """Test invalid hold duration."""
        with pytest.raises(ActionParseError):
            parse_action("key:w:hold:abc")
