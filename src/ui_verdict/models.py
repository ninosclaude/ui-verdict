from __future__ import annotations

from enum import Enum
from pydantic import BaseModel


class Severity(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class ChangeType(str, Enum):
    NONE = "no_change"
    MOVEMENT = "movement"
    APPEARANCE = "appearance"
    DISAPPEARANCE = "disappearance"
    MIXED = "mixed"


class Direction(str, Enum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    UP_LEFT = "up-left"
    UP_RIGHT = "up-right"
    DOWN_LEFT = "down-left"
    DOWN_RIGHT = "down-right"
    NONE = "none"


class Region(BaseModel):
    x: int
    y: int
    w: int
    h: int

    @classmethod
    def from_str(cls, s: str) -> "Region":
        """Parse '100,50,200,30' into Region(x=100,y=50,w=200,h=30)."""
        parts = [int(p.strip()) for p in s.split(",")]
        if len(parts) != 4:
            raise ValueError(f"Region must be 'x,y,w,h', got: {s!r}")
        return cls(x=parts[0], y=parts[1], w=parts[2], h=parts[3])


class Issue(BaseModel):
    severity: Severity
    category: str
    message: str
    location: str | None = None


class DiffReport(BaseModel):
    changed: bool
    change_type: ChangeType
    change_ratio: float
    direction: Direction
    magnitude: float
    moving_ratio: float

    def to_text(self) -> str:
        if not self.changed:
            return "NO CHANGE — action produced no visible reaction"
        lines = [
            f"CHANGED: {self.change_type.value}",
            f"  change_ratio: {self.change_ratio:.1%}",
            f"  direction: {self.direction.value}",
            f"  magnitude: {self.magnitude:.1f}px",
        ]
        return "\n".join(lines)


class ContrastReport(BaseModel):
    min_ratio: float
    avg_ratio: float
    wcag_aa: bool
    wcag_aaa: bool
    issues: list[Issue]

    def to_text(self) -> str:
        status = "PASS" if self.wcag_aa else "FAIL"
        return (
            f"Contrast {status}: min={self.min_ratio:.1f}:1 avg={self.avg_ratio:.1f}:1"
            f" AA={'✅' if self.wcag_aa else '❌'} AAA={'✅' if self.wcag_aaa else '❌'}"
        )


class LayoutReport(BaseModel):
    balance_score: float
    clutter_score: float
    alignment_score: float
    issues: list[Issue]

    def to_text(self) -> str:
        return (
            f"Layout: balance={self.balance_score:.2f}"
            f" clutter={self.clutter_score:.2f}"
            f" alignment={self.alignment_score:.2f}"
        )


class VerdictReport(BaseModel):
    overall: Severity
    diff: DiffReport | None = None
    contrast: ContrastReport | None = None
    layout: LayoutReport | None = None
    vision_analysis: str | None = None
    issues: list[Issue] = []

    def to_text(self) -> str:
        sections = [f"## UI Verdict: {self.overall.value.upper()}"]

        if self.diff:
            sections.append(f"\n### Action-Reaction\n{self.diff.to_text()}")

        if self.contrast:
            sections.append(f"\n### Contrast\n{self.contrast.to_text()}")

        if self.layout:
            sections.append(f"\n### Layout\n{self.layout.to_text()}")

        if self.issues:
            issue_lines = "\n".join(
                f"- {'⚠️' if i.severity == Severity.WARN else '❌'} {i.category}: {i.message}"
                for i in self.issues
            )
            sections.append(f"\n### Issues\n{issue_lines}")

        if self.vision_analysis:
            sections.append(f"\n### Vision Analysis\n{self.vision_analysis}")

        return "\n".join(sections)
