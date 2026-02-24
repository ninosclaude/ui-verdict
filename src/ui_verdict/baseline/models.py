"""
Data models for Visual Baseline Comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class CompareVerdict(str, Enum):
    """Result of baseline comparison."""

    NO_CHANGE = "no_change"  # pixel_diff < threshold
    INTENTIONAL = "intentional"  # AI: looks like a planned update
    REGRESSION = "regression"  # AI: looks broken/buggy
    UNKNOWN = "unknown"  # No baseline exists


@dataclass
class BaselineMeta:
    """Metadata for a stored baseline."""

    key: str  # Unique identifier
    name: str  # Human-readable name
    url: str  # URL or app state description
    viewport: tuple[int, int]  # (width, height)
    created_at: datetime
    updated_at: datetime
    change_threshold: float = 0.001  # Default: 0.1% change tolerance

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "url": self.url,
            "viewport": list(self.viewport),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "change_threshold": self.change_threshold,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaselineMeta:
        return cls(
            key=data["key"],
            name=data["name"],
            url=data["url"],
            viewport=tuple(data["viewport"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            change_threshold=data.get("change_threshold", 0.001),
        )


@dataclass
class DiffRegion:
    """A region where visual change was detected."""

    x: int
    y: int
    width: int
    height: int
    area: int

    def to_dict(self) -> dict[str, int]:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "area": self.area,
        }


@dataclass
class CompareResult:
    """Result of comparing current screenshot against baseline."""

    verdict: CompareVerdict
    change_ratio: float  # 0.0 to 1.0
    baseline_path: str | None  # Path to baseline image
    current_path: str  # Path to current screenshot
    diff_regions: list[DiffRegion] = field(default_factory=list)
    ai_explanation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "change_ratio": self.change_ratio,
            "baseline_path": self.baseline_path,
            "current_path": self.current_path,
            "diff_regions": [r.to_dict() for r in self.diff_regions],
            "ai_explanation": self.ai_explanation,
        }
