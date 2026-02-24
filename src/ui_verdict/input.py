from __future__ import annotations

import time
from pynput.keyboard import Key, Controller as KeyboardController
from pynput.mouse import Button, Controller as MouseController

_keyboard = KeyboardController()
_mouse = MouseController()

_SPECIAL_KEYS: dict[str, Key] = {
    "space": Key.space,
    "enter": Key.enter,
    "tab": Key.tab,
    "escape": Key.esc,
    "esc": Key.esc,
    "backspace": Key.backspace,
    "delete": Key.delete,
    "up": Key.up,
    "down": Key.down,
    "left": Key.left,
    "right": Key.right,
    "shift": Key.shift,
    "ctrl": Key.ctrl,
    "alt": Key.alt,
    "cmd": Key.cmd,
    "f1": Key.f1,
    "f2": Key.f2,
    "f3": Key.f3,
    "f4": Key.f4,
    "f5": Key.f5,
}


def send_action(action: str) -> None:
    """
    Parse and execute an action string.

    Formats:
      "key:w"                  — tap W
      "key:w:hold:200ms"       — hold W for 200ms
      "key:space"              — tap Space
      "click:500,300"          — left click at (500, 300)
      "rightclick:500,300"     — right click at (500, 300)
      "move:500,300"           — move mouse to (500, 300)
      "wait:200ms"             — sleep 200ms
    """
    parts = action.strip().split(":")
    cmd = parts[0].lower()

    if cmd == "key":
        _handle_key(parts[1:])
    elif cmd == "click":
        x, y = _parse_coords(parts[1])
        _mouse.position = (x, y)
        time.sleep(0.01)
        _mouse.click(Button.left)
    elif cmd == "rightclick":
        x, y = _parse_coords(parts[1])
        _mouse.position = (x, y)
        time.sleep(0.01)
        _mouse.click(Button.right)
    elif cmd == "move":
        x, y = _parse_coords(parts[1])
        _mouse.position = (x, y)
    elif cmd == "wait":
        ms = _parse_ms(parts[1])
        time.sleep(ms / 1000.0)
    else:
        raise ValueError(
            f"Unknown action command: {cmd!r}. Use key/click/rightclick/move/wait"
        )


def _handle_key(parts: list[str]) -> None:
    if not parts:
        raise ValueError("key action requires a key name")

    key_name = parts[0].lower()
    key = _SPECIAL_KEYS.get(key_name, key_name)

    hold_ms = 50  # default tap duration
    if len(parts) >= 3 and parts[1].lower() == "hold":
        hold_ms = _parse_ms(parts[2])

    _keyboard.press(key)
    time.sleep(hold_ms / 1000.0)
    _keyboard.release(key)


def _parse_coords(s: str) -> tuple[int, int]:
    parts = s.split(",")
    if len(parts) != 2:
        raise ValueError(f"Expected 'x,y' coordinates, got: {s!r}")
    return int(parts[0]), int(parts[1])


def _parse_ms(s: str) -> int:
    s = s.lower().replace("ms", "").strip()
    return int(s)
