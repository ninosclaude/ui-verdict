"""
Data models for QA-Agent (QA-Agent Spec compliant).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    SKIPPED = "SKIPPED"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CheckLevel(str, Enum):
    PRE_FLIGHT = "pre_flight"
    REACHABILITY = "reachability"
    FUNCTIONAL = "functional"
    EDGE_CASES = "edge_cases"
    VISUAL = "visual"


@dataclass
class ACResult:
    """Result of a single Acceptance Criterion check."""
    ac: str
    check_id: str  # e.g. "P-01", "R-03", "F-04"
    level: CheckLevel
    status: Status
    severity: Severity
    diagnosis: str = ""
    screenshot: str | None = None
    reason: str | None = None  # For SKIPPED
    details: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "ac": self.ac,
            "check_id": self.check_id,
            "level": self.level.value,
            "status": self.status.value,
            "severity": self.severity.value,
            "diagnosis": self.diagnosis,
            "screenshot": self.screenshot,
            "reason": self.reason,
            "details": self.details,
        }


@dataclass
class StepLog:
    """Log entry for a single execution step."""
    step: str
    status: str  # "ok", "fail", "info", "warn"
    details: dict[str, Any] = field(default_factory=dict)
    screenshot: str | None = None
    
    def to_dict(self) -> dict:
        d = {"step": self.step, "status": self.status}
        if self.details:
            d.update(self.details)
        if self.screenshot:
            d["screenshot"] = self.screenshot
        return d


@dataclass
class QAReport:
    """Structured report matching QA-Agent spec."""
    run_id: str
    story: str
    overall_status: Status
    duration_seconds: float
    acs_passed: int
    acs_failed: int
    acs_skipped: int
    what_to_fix: str
    levels: dict[str, str]
    acs: list[ACResult]
    steps: list[StepLog]
    
    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "story": self.story,
            "overall_status": self.overall_status.value,
            "duration_seconds": round(self.duration_seconds, 1),
            "acs_passed": self.acs_passed,
            "acs_failed": self.acs_failed,
            "acs_skipped": self.acs_skipped,
            "what_to_fix": self.what_to_fix,
            "levels": self.levels,
            "acs": [ac.to_dict() for ac in self.acs],
            "steps": [s.to_dict() for s in self.steps],
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)
    
    def summary(self) -> str:
        """Human-readable summary."""
        icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}.get(self.overall_status.value, "?")
        
        lines = [
            f"{icon} {self.overall_status.value} | {self.duration_seconds:.1f}s | ✅{self.acs_passed} ❌{self.acs_failed} ⏭️{self.acs_skipped}",
            "",
            "Levels:",
        ]
        for level, status in self.levels.items():
            lines.append(f"  {level}: {status}")
        
        if self.what_to_fix and self.what_to_fix != "All checks passed. No fixes needed.":
            lines.append("")
            lines.append("What to fix:")
            lines.append(self.what_to_fix)
        
        return "\n".join(lines)
