"""
QA-Agent: Automated acceptance testing for desktop apps.

Implements the full QA-Agent spec with:
- Check taxonomy (Pre-Flight, Reachability, Functional, Edge Cases, Visual)
- Planner (Story → Test Plan via LLM)
- Manyminds context integration
- Structured QAReport output
"""
from .server import mcp, run, check_screenshot
from .models import QAReport, ACResult, Status, Severity, CheckLevel

__all__ = [
    "mcp",
    "run", 
    "check_screenshot",
    "QAReport",
    "ACResult", 
    "Status",
    "Severity",
    "CheckLevel",
]
