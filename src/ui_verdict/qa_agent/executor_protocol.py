"""
Executor Protocol for QA-Agent.

Defines the interface that all executor backends must implement.
Uses Python Protocol (structural subtyping) for Go-like duck typing.

Backends:
- DesktopExecutor: OrbStack VM (Linux) via xdotool/scrot
- WebExecutor: Browser via Midscene.js/Playwright (planned)
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from dataclasses import dataclass


@dataclass
class AppStartResult:
    """Result of starting an application."""
    success: bool
    pid: int | None
    message: str


@dataclass
class PixelDiffResult:
    """Result of pixel difference calculation."""
    changed_pixels: int
    change_ratio: float
    num_regions: int
    regions: list[dict]


@runtime_checkable
class ExecutorProtocol(Protocol):
    """Protocol that all executor backends must satisfy.
    
    This is a structural type - any class with these methods works.
    No need to inherit from anything.
    """

    def take_screenshot(self, prefix: str = "qa") -> str:
        """Take screenshot, return local file path.
        
        Args:
            prefix: Filename prefix for the screenshot
            
        Returns:
            Absolute path to the screenshot file
        """
        ...

    def execute_action(self, action: str) -> None:
        """Execute an action.
        
        Action formats:
        - "key:ctrl+o" - Keyboard shortcut
        - "click:ElementName" - Click element by text
        - "type:some text" - Type text
        - "wait:1000" - Wait milliseconds
        
        Args:
            action: Action string to execute
            
        Raises:
            RuntimeError: If action fails
        """
        ...

    def start_app(
        self, 
        target: str, 
        name: str, 
        env: dict[str, str] | None = None
    ) -> AppStartResult:
        """Start application or open URL.
        
        For Desktop: target = path to binary
        For Web: target = URL
        
        Args:
            target: Binary path or URL
            name: Process/tab name for identification
            env: Environment variables (Desktop only)
            
        Returns:
            AppStartResult with success status
        """
        ...

    def stop_app(self, name: str) -> None:
        """Stop application or close browser tab.
        
        Args:
            name: Process/tab name to stop
        """
        ...

    def get_pixel_diff(self, before: str, after: str) -> PixelDiffResult:
        """Calculate pixel difference between two screenshots.
        
        Args:
            before: Path to before screenshot
            after: Path to after screenshot
            
        Returns:
            PixelDiffResult with change statistics
        """
        ...

    def is_available(self) -> bool:
        """Check if this executor backend is available.
        
        Returns:
            True if backend can be used
        """
        ...

    def focus_window(self) -> None:
        """Focus the application window.
        
        For Desktop: Focus via window manager
        For Web: Focus browser tab
        """
        ...


# Type alias for executor instances
Executor = ExecutorProtocol
