"""
VM integration for ui-verdict.

Enables running and testing GUI applications in an OrbStack Linux VM
while the MCP server runs on macOS. This solves the focus-stealing problem
and provides isolated, reproducible testing environments.
"""
from __future__ import annotations

import subprocess
import tempfile
import os
import time
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VMConfig:
    """Configuration for VM testing."""
    name: str = "ui-test"
    display: str = ":99"
    screen_size: str = "1920x1080x24"


_config = VMConfig()


def set_vm(name: str) -> None:
    """Set the VM name to use for testing."""
    _config.name = name


def _run_in_vm(cmd: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run a command in the VM via orb run."""
    full_cmd = f'orb run -m {_config.name} bash -c {repr(cmd)}'
    result = subprocess.run(
        full_cmd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def vm_available() -> bool:
    """Check if the VM is running and accessible."""
    try:
        code, out, _ = _run_in_vm("echo ok", timeout=5)
        return code == 0 and "ok" in out
    except Exception:
        return False


def ensure_xvfb() -> bool:
    """Ensure Xvfb is running in the VM."""
    # Check if already running
    code, out, _ = _run_in_vm(f"pgrep -f 'Xvfb {_config.display}'")
    if code == 0 and out.strip():
        return True
    
    # Start Xvfb
    cmd = f"Xvfb {_config.display} -screen 0 {_config.screen_size} &"
    _run_in_vm(cmd)
    time.sleep(0.5)
    
    # Verify
    code, out, _ = _run_in_vm(f"pgrep -f 'Xvfb {_config.display}'")
    return code == 0 and bool(out.strip())


def vm_screenshot(save_path: str | None = None) -> str:
    """Take a screenshot in the VM and copy it to the Mac.
    
    Uses OrbStack's mounted filesystem for reliable file transfer.
    
    Args:
        save_path: Local path to save the screenshot. If None, uses a temp file.
        
    Returns:
        Path to the saved screenshot on the Mac.
    """
    if save_path is None:
        fd, save_path = tempfile.mkstemp(suffix=".png", prefix="vm_screenshot_")
        os.close(fd)
    
    # Use unique ID to avoid collisions
    unique_id = uuid.uuid4().hex[:8]
    mac_tmp = "/tmp"
    vm_accessible_path = f"/mnt/mac{mac_tmp}/vm_ss_{unique_id}.png"
    local_tmp_path = f"{mac_tmp}/vm_ss_{unique_id}.png"
    
    # Take screenshot and save to Mac-mounted path
    cmd = f"DISPLAY={_config.display} scrot -o {vm_accessible_path}"
    code, out, err = _run_in_vm(cmd)
    if code != 0:
        raise RuntimeError(f"Screenshot failed: {err}")
    
    # Small delay to ensure write completes
    time.sleep(0.2)
    
    # Move to final destination on Mac
    for _ in range(10):  # Retry up to 10 times
        if os.path.exists(local_tmp_path):
            shutil.move(local_tmp_path, save_path)
            return save_path
        time.sleep(0.1)
    
    raise RuntimeError(f"Screenshot file not found at {local_tmp_path}")


def vm_send_key(key: str, hold_ms: int = 50) -> None:
    """Send a key press to the VM.
    
    Args:
        key: Key name (e.g., "w", "space", "Return", "Escape")
        hold_ms: How long to hold the key in milliseconds
    """
    # Map common key names to xdotool format
    key_map = {
        "space": "space",
        "enter": "Return",
        "return": "Return",
        "escape": "Escape",
        "esc": "Escape",
        "tab": "Tab",
        "backspace": "BackSpace",
        "delete": "Delete",
        "up": "Up",
        "down": "Down",
        "left": "Left",
        "right": "Right",
        "shift": "shift",
        "ctrl": "ctrl",
        "alt": "alt",
    }
    
    xdo_key = key_map.get(key.lower(), key)
    
    if hold_ms > 100:
        # For long holds, use keydown/keyup
        cmd = f"DISPLAY={_config.display} xdotool keydown {xdo_key} && sleep {hold_ms/1000:.3f} && DISPLAY={_config.display} xdotool keyup {xdo_key}"
    else:
        cmd = f"DISPLAY={_config.display} xdotool key {xdo_key}"
    
    code, _, err = _run_in_vm(cmd)
    if code != 0:
        raise RuntimeError(f"Key send failed: {err}")


def vm_click(x: int, y: int, button: str = "left") -> None:
    """Send a mouse click to the VM.
    
    Args:
        x: X coordinate
        y: Y coordinate
        button: "left", "right", or "middle"
    """
    button_map = {"left": 1, "middle": 2, "right": 3}
    btn = button_map.get(button.lower(), 1)
    
    cmd = f"DISPLAY={_config.display} xdotool mousemove {x} {y} click {btn}"
    code, _, err = _run_in_vm(cmd)
    if code != 0:
        raise RuntimeError(f"Click failed: {err}")


def vm_type(text: str) -> None:
    """Type text in the VM.
    
    Args:
        text: Text to type
    """
    # Escape special characters for shell
    escaped = text.replace("'", "'\\''")
    cmd = f"DISPLAY={_config.display} xdotool type '{escaped}'"
    code, _, err = _run_in_vm(cmd)
    if code != 0:
        raise RuntimeError(f"Type failed: {err}")


def vm_stop_app(pid: int | None = None, name: str | None = None) -> None:
    """Stop an application in the VM.
    
    Args:
        pid: Process ID to kill
        name: Process name to kill (uses pkill)
    """
    if pid:
        _run_in_vm(f"kill {pid} 2>/dev/null || true")
    elif name:
        _run_in_vm(f"pkill -f {name} 2>/dev/null || true")


def vm_window_info() -> dict:
    """Get information about windows in the VM.
    
    Returns:
        Dict with window info (id, name, geometry)
    """
    cmd = f"DISPLAY={_config.display} xdotool search --name '' getwindowname %@ 2>/dev/null | head -20"
    code, out, _ = _run_in_vm(cmd)
    
    windows = []
    if code == 0:
        for line in out.strip().split("\n"):
            if line:
                windows.append(line)
    
    return {"windows": windows}


def deploy_and_run(
    binary_path: str,
    app_name: str,
    args: list[str] | None = None,
) -> dict:
    """Deploy a binary to VM and run it.
    
    Supports three modes:
    1. Mac path (/Users/...): Copy to VM via OrbStack mounted filesystem
    2. VM path (/home/...): Use directly in VM
    3. Relative path: Resolve from current directory
    
    Args:
        binary_path: Path to binary
        app_name: Name for the running app (for later reference)
        args: Command line arguments
        
    Returns:
        Dict with pid, vm_binary_path, display
    """
    if not vm_available():
        raise RuntimeError(f"VM '{_config.name}' is not available. Run: orb create ubuntu:24.04 {_config.name}")
    
    ensure_xvfb()
    
    # Determine if path is Mac or VM
    is_vm_path = binary_path.startswith("/home/") or binary_path.startswith("/tmp/")
    
    if is_vm_path:
        # Path is already in VM
        vm_binary = binary_path
        binary_name = Path(binary_path).name
        
        # Verify it exists
        code, _, _ = _run_in_vm(f"test -f {vm_binary}")
        if code != 0:
            raise FileNotFoundError(f"Binary not found in VM: {vm_binary}")
    else:
        # Path is on Mac - use mounted filesystem
        mac_path = Path(binary_path).resolve()
        if not mac_path.exists():
            raise FileNotFoundError(f"Binary not found: {binary_path}")
        
        binary_name = mac_path.name
        # Access via mounted filesystem - faster than copying
        vm_binary = f"/mnt/mac{mac_path}"
        
        # Verify accessible from VM
        code, _, _ = _run_in_vm(f"test -f {vm_binary}")
        if code != 0:
            # Fall back to copying
            vm_binary = f"/tmp/{binary_name}"
            _run_in_vm(f"cp '/mnt/mac{mac_path}' {vm_binary} && chmod +x {vm_binary}")
    
    # Kill any existing instance
    vm_stop_app(name=binary_name)
    time.sleep(0.3)
    
    # Start app
    args_str = " ".join(args or [])
    # Set GEGL_PATH for imagination specifically
    env_vars = f"DISPLAY={_config.display}"
    if "imagination" in app_name.lower():
        env_vars += " GEGL_PATH=/usr/lib/aarch64-linux-gnu/gegl-0.4"
    
    cmd = f"{env_vars} {vm_binary} {args_str} > /tmp/{app_name}.log 2>&1 &"
    _run_in_vm(cmd)
    
    time.sleep(2.0)  # Wait for app to initialize
    
    # Get PID
    code, out, _ = _run_in_vm(f"pgrep -f {binary_name}")
    pid = int(out.strip().split()[0]) if code == 0 and out.strip() else None
    
    return {
        "pid": pid,
        "vm_binary": vm_binary,
        "display": _config.display,
        "app_name": app_name,
        "running": pid is not None,
    }
