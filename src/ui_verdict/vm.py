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
    try:
        result = subprocess.run(
            full_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


def vm_available() -> bool:
    """Check if the VM is running and accessible."""
    try:
        code, out, _ = _run_in_vm("echo ok", timeout=5)
        return code == 0 and "ok" in out
    except Exception:
        return False


def ensure_xvfb() -> bool:
    """Ensure Xvfb is running in the VM with a window manager."""
    # Check if Xvfb already running
    code, out, _ = _run_in_vm(f"pgrep -f 'Xvfb {_config.display}'")
    if code != 0 or not out.strip():
        # Start Xvfb
        _run_in_vm(f"Xvfb {_config.display} -screen 0 {_config.screen_size} &")
        time.sleep(0.5)
    
    # Check if openbox running (needed for window focus)
    code, out, _ = _run_in_vm("pgrep openbox")
    if code != 0 or not out.strip():
        _run_in_vm(f"DISPLAY={_config.display} openbox &", timeout=5)
        time.sleep(0.3)
    
    # Verify Xvfb is running
    code, out, _ = _run_in_vm(f"pgrep -f 'Xvfb {_config.display}'")
    return code == 0 and bool(out.strip())


def vm_screenshot(save_path: str | None = None) -> str:
    """Take a screenshot in the VM and copy it to the Mac."""
    if save_path is None:
        fd, save_path = tempfile.mkstemp(suffix=".png", prefix="vm_screenshot_")
        os.close(fd)
    
    unique_id = uuid.uuid4().hex[:8]
    mac_tmp = "/tmp"
    vm_accessible_path = f"/mnt/mac{mac_tmp}/vm_ss_{unique_id}.png"
    local_tmp_path = f"{mac_tmp}/vm_ss_{unique_id}.png"
    
    cmd = f"export DISPLAY={_config.display} && scrot -o {vm_accessible_path}"
    code, out, err = _run_in_vm(cmd)
    if code != 0:
        raise RuntimeError(f"Screenshot failed: {err}")
    
    time.sleep(0.2)
    
    for _ in range(10):
        if os.path.exists(local_tmp_path):
            shutil.move(local_tmp_path, save_path)
            return save_path
        time.sleep(0.1)
    
    raise RuntimeError(f"Screenshot file not found at {local_tmp_path}")


def _find_window(name: str | None = None) -> int | None:
    """Find a window ID by name or get the active window."""
    if name:
        cmd = f"export DISPLAY={_config.display} && xdotool search --name '{name}' | head -1"
    else:
        cmd = f"export DISPLAY={_config.display} && xdotool search --name '' | head -1"
    
    code, out, _ = _run_in_vm(cmd, timeout=5)
    if code == 0 and out.strip():
        try:
            return int(out.strip().split()[0])
        except ValueError:
            pass
    return None


def _focus_window(window_id: int | None = None) -> bool:
    """Focus the application window."""
    if window_id:
        cmd = f"export DISPLAY={_config.display} && xdotool windowactivate --sync {window_id}"
        code, _, _ = _run_in_vm(cmd, timeout=5)
        if code == 0:
            return True
    
    # Fallback: click in center of screen
    cmd = f"export DISPLAY={_config.display} && xdotool mousemove 960 540 click 1"
    code, _, _ = _run_in_vm(cmd, timeout=5)
    time.sleep(0.1)
    return code == 0


def vm_send_key(key: str, hold_ms: int = 50, window_name: str | None = None) -> None:
    """Send a key press to the VM.
    
    Args:
        key: Key to send (e.g., "ctrl+n", "Return", "a")
        hold_ms: How long to hold the key in milliseconds
        window_name: Optional window name to focus first
    """
    # Find and focus window
    window_id = _find_window(window_name) if window_name else _find_window()
    _focus_window(window_id)
    time.sleep(0.1)
    
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
        cmd = f"export DISPLAY={_config.display} && xdotool keydown {xdo_key} && sleep {hold_ms/1000:.3f} && xdotool keyup {xdo_key}"
    else:
        cmd = f"export DISPLAY={_config.display} && xdotool key {xdo_key}"
    
    code, _, err = _run_in_vm(cmd, timeout=10)
    if code != 0:
        raise RuntimeError(f"Key send failed: {err}")


def vm_click(x: int, y: int, button: str = "left") -> None:
    """Send a mouse click to the VM."""
    button_map = {"left": 1, "middle": 2, "right": 3}
    btn = button_map.get(button.lower(), 1)
    
    cmd = f"export DISPLAY={_config.display} && xdotool mousemove {x} {y} click {btn}"
    code, _, err = _run_in_vm(cmd, timeout=10)
    if code != 0:
        raise RuntimeError(f"Click failed: {err}")


def vm_type(text: str, window_name: str | None = None) -> None:
    """Type text in the VM."""
    window_id = _find_window(window_name) if window_name else _find_window()
    _focus_window(window_id)
    
    escaped = text.replace("'", "'\\''")
    cmd = f"export DISPLAY={_config.display} && xdotool type '{escaped}'"
    code, _, err = _run_in_vm(cmd, timeout=10)
    if code != 0:
        raise RuntimeError(f"Type failed: {err}")


def vm_stop_app(pid: int | None = None, name: str | None = None) -> None:
    """Stop an application in the VM."""
    if pid:
        _run_in_vm(f"kill {pid} 2>/dev/null || true")
    elif name:
        _run_in_vm(f"pkill -f {name} 2>/dev/null || true")


def vm_window_info() -> dict:
    """Get information about windows in the VM."""
    cmd = f"export DISPLAY={_config.display} && xdotool search --name '' getwindowname %@ 2>/dev/null | head -20"
    code, out, _ = _run_in_vm(cmd, timeout=5)
    
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
    env: dict[str, str] | None = None,
) -> dict:
    """Deploy a binary to VM and run it.
    
    Args:
        binary_path: Path to binary (Mac path or VM path starting with /home/ or /tmp/)
        app_name: Name for the running application
        args: Command line arguments
        env: Additional environment variables (e.g., {"GEGL_PATH": "/usr/lib/..."})
    """
    if not vm_available():
        raise RuntimeError(f"VM '{_config.name}' is not available. Run: orb create ubuntu:24.04 {_config.name}")
    
    ensure_xvfb()
    
    is_vm_path = binary_path.startswith("/home/") or binary_path.startswith("/tmp/")
    
    if is_vm_path:
        vm_binary = binary_path
        binary_name = Path(binary_path).name
        
        code, _, _ = _run_in_vm(f"test -f {vm_binary}")
        if code != 0:
            raise FileNotFoundError(f"Binary not found in VM: {vm_binary}")
    else:
        mac_path = Path(binary_path).resolve()
        if not mac_path.exists():
            raise FileNotFoundError(f"Binary not found: {binary_path}")
        
        binary_name = mac_path.name
        vm_binary = f"/mnt/mac{mac_path}"
        
        code, _, _ = _run_in_vm(f"test -f {vm_binary}")
        if code != 0:
            vm_binary = f"/tmp/{binary_name}"
            _run_in_vm(f"cp '/mnt/mac{mac_path}' {vm_binary} && chmod +x {vm_binary}")
    
    vm_stop_app(name=binary_name)
    time.sleep(0.3)
    
    args_str = " ".join(args or [])
    env_vars = f"DISPLAY={_config.display}"
    
    # Add custom environment variables
    if env:
        for key, value in env.items():
            env_vars += f" {key}={value}"
    
    cmd = f"export {env_vars} && {vm_binary} {args_str} > /tmp/{app_name}.log 2>&1 &"
    _run_in_vm(cmd)
    
    time.sleep(2.0)
    
    # Focus the application window
    window_id = _find_window(app_name)
    _focus_window(window_id)
    
    code, out, _ = _run_in_vm(f"pgrep -f {binary_name}")
    pid = int(out.strip().split()[0]) if code == 0 and out.strip() else None
    
    return {
        "pid": pid,
        "vm_binary": vm_binary,
        "display": _config.display,
        "app_name": app_name,
        "running": pid is not None,
        "window_id": window_id,
    }
