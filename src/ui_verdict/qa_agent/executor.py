"""
Executor: Backward-compatible module for QA-Agent.

This module maintains backward compatibility with existing code
while delegating to the new DesktopExecutor class.

For new code, use:
    from .desktop_executor import DesktopExecutor, get_desktop_executor
    
Or import the protocol:
    from .executor_protocol import ExecutorProtocol
"""

from __future__ import annotations

from .desktop_executor import DesktopExecutor, get_desktop_executor, VMConfig

# Re-export everything for backward compatibility
__all__ = [
    "VMConfig",
    "DesktopExecutor",
    "get_desktop_executor",
    # Legacy function exports
    "run_in_vm",
    "vm_available",
    "ensure_display",
    "take_screenshot",
    "focus_window",
    "execute_action",
    "get_pixel_diff",
    "start_app",
    "stop_app",
    "check_binary_exists",
    "get_app_log",
    "click_element_by_text",
]


# Legacy function wrappers that delegate to default executor
def run_in_vm(cmd: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run command in VM via orb."""
    return get_desktop_executor()._run_in_vm(cmd, timeout)


def vm_available() -> bool:
    """Check if VM is accessible."""
    return get_desktop_executor().is_available()


def ensure_display() -> bool:
    """Ensure Xvfb and window manager are running."""
    return get_desktop_executor()._ensure_display()


def take_screenshot(prefix: str = "qa") -> str:
    """Take screenshot in VM, return local path."""
    return get_desktop_executor().take_screenshot(prefix)


def focus_window() -> None:
    """Click center of screen to focus window."""
    get_desktop_executor().focus_window()


def execute_action(action: str) -> None:
    """Execute an action in the VM."""
    get_desktop_executor().execute_action(action)


def get_pixel_diff(before_path: str, after_path: str) -> dict:
    """Calculate pixel difference between screenshots."""
    result = get_desktop_executor().get_pixel_diff(before_path, after_path)
    # Return dict for backward compatibility
    return {
        "changed_pixels": result.changed_pixels,
        "change_ratio": result.change_ratio,
        "num_regions": result.num_regions,
        "regions": result.regions,
    }


def start_app(
    binary: str, name: str, env: dict[str, str] | None = None
) -> tuple[bool, int | None, str]:
    """Start an application in the VM."""
    result = get_desktop_executor().start_app(binary, name, env)
    return result.success, result.pid, result.message


def stop_app(name: str) -> None:
    """Stop an application."""
    get_desktop_executor().stop_app(name)


def check_binary_exists(path: str) -> bool:
    """Check if binary exists in VM."""
    return get_desktop_executor().check_binary_exists(path)


def get_app_log(name: str, lines: int = 30) -> str:
    """Get app log from VM."""
    return get_desktop_executor().get_app_log(name, lines)


def click_element_by_text(target_text: str) -> tuple[bool, str]:
    """Click an element by its visible text/label."""
    return get_desktop_executor()._click_element_by_text(target_text)
