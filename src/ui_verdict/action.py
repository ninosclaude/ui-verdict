"""
Action parsing and execution for VM input.

This module provides a clean interface for parsing text-based action commands
and executing them via the VM module. It consolidates the action parsing logic
that was previously duplicated across multiple MCP tools.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum


class ActionType(Enum):
    """Types of actions that can be sent to the VM."""

    KEY = "key"
    CLICK = "click"
    RIGHTCLICK = "rightclick"
    TYPE = "type"
    WAIT = "wait"
    CLICK_TEXT = "click_text"


@dataclass
class ParsedAction:
    """A parsed action ready for execution."""

    action_type: ActionType
    key: str | None = None
    hold_ms: int = 50
    x: int | None = None
    y: int | None = None
    text: str | None = None
    wait_ms: int | None = None
    target_text: str | None = None


class ActionParseError(ValueError):
    """Raised when an action string cannot be parsed."""

    pass


def parse_action(action: str) -> ParsedAction:
    """Parse an action string into a structured ParsedAction.

    Supported formats:
        "key:w"              — tap W key
        "key:space"          — tap Space
        "key:ctrl+o"         — key combination
        "key:w:hold:500ms"   — hold W for 500ms
        "click:500,300"      — left click at (500, 300)
        "click:Open"         — click element by text (uses vision)
        "rightclick:500,300" — right click
        "type:hello world"   — type text
        "wait:500ms"         — just wait

    Args:
        action: The action string to parse

    Returns:
        ParsedAction ready for execution

    Raises:
        ActionParseError: If the action format is invalid
    """
    parts = action.strip().split(":")
    if not parts:
        raise ActionParseError("Empty action string")

    cmd = parts[0].lower()

    if cmd == "key":
        if len(parts) < 2 or not parts[1]:
            raise ActionParseError("key action requires key name: key:w")
        key = parts[1]
        hold_ms = 50
        if len(parts) >= 4 and parts[2].lower() == "hold":
            try:
                hold_ms = int(parts[3].lower().replace("ms", ""))
            except ValueError:
                raise ActionParseError(f"Invalid hold duration: {parts[3]}")
        return ParsedAction(ActionType.KEY, key=key, hold_ms=hold_ms)

    if cmd == "click":
        if len(parts) < 2 or not parts[1]:
            raise ActionParseError(
                "click action requires coordinates or text: click:500,300 or click:Open"
            )

        # Try to parse as coordinates first
        if "," in parts[1]:
            try:
                coords = parts[1].split(",")
                x, y = int(coords[0]), int(coords[1])
                return ParsedAction(ActionType.CLICK, x=x, y=y)
            except (ValueError, IndexError):
                raise ActionParseError(f"Invalid click coordinates: {parts[1]}")

        # Fall back to text-based click
        target = parts[1]
        return ParsedAction(ActionType.CLICK_TEXT, target_text=target)

    if cmd == "rightclick":
        if len(parts) < 2:
            raise ActionParseError(
                "rightclick action requires coordinates: rightclick:500,300"
            )
        try:
            coords = parts[1].split(",")
            x, y = int(coords[0]), int(coords[1])
        except (ValueError, IndexError):
            raise ActionParseError(f"Invalid rightclick coordinates: {parts[1]}")
        return ParsedAction(ActionType.RIGHTCLICK, x=x, y=y)

    if cmd == "type":
        if len(parts) < 2:
            raise ActionParseError("type action requires text: type:hello world")
        # Rejoin in case text contains colons
        text = ":".join(parts[1:])
        return ParsedAction(ActionType.TYPE, text=text)

    if cmd == "wait":
        if len(parts) < 2:
            raise ActionParseError("wait action requires duration: wait:500ms")
        try:
            wait_ms = int(parts[1].lower().replace("ms", ""))
        except ValueError:
            raise ActionParseError(f"Invalid wait duration: {parts[1]}")
        return ParsedAction(ActionType.WAIT, wait_ms=wait_ms)

    raise ActionParseError(
        f"Unknown action type: {cmd}. Use key/click/rightclick/type/wait/click_text"
    )


def execute_action(action: str | ParsedAction) -> None:
    """Execute an action in the VM.

    Args:
        action: Either an action string or a pre-parsed ParsedAction

    Raises:
        ActionParseError: If the action string is invalid
        RuntimeError: If the action execution fails
    """
    from .vm import vm_send_key, vm_click, vm_type

    if isinstance(action, str):
        parsed = parse_action(action)
    else:
        parsed = action

    if parsed.action_type == ActionType.CLICK_TEXT:
        raise RuntimeError(
            "CLICK_TEXT requires vision support. Use qa_agent.executor.execute_action instead."
        )

    if parsed.action_type == ActionType.KEY:
        vm_send_key(parsed.key, parsed.hold_ms)
        return

    if parsed.action_type == ActionType.CLICK:
        vm_click(parsed.x, parsed.y, "left")
        return

    if parsed.action_type == ActionType.RIGHTCLICK:
        vm_click(parsed.x, parsed.y, "right")
        return

    if parsed.action_type == ActionType.TYPE:
        vm_type(parsed.text)
        return

    if parsed.action_type == ActionType.WAIT:
        time.sleep(parsed.wait_ms / 1000.0)
        return
