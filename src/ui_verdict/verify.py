"""
Visual Assertion Tool for AI Coding Agents.

Simple, fast verification of acceptance criteria against live URLs.
Single vision call, mandatory grounding, actionable failures.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)


# ============================================================================
# DATA TYPES
# ============================================================================


@dataclass
class ACResult:
    """Result for a single acceptance criterion."""

    ac: str
    status: Literal["PASS", "FAIL"]
    location: str | None = None  # Required for PASS - where element was found
    description: str | None = None  # Optional for PASS
    reason: str | None = None  # Required for FAIL - why it failed
    suggestion: str | None = None  # Required for FAIL - how to fix


@dataclass
class VerifyResult:
    """Result of verify_acs call."""

    passed: list[ACResult] = field(default_factory=list)
    failed: list[ACResult] = field(default_factory=list)
    screenshot: str | None = None
    duration_seconds: float = 0.0

    @property
    def all_passed(self) -> bool:
        return len(self.failed) == 0

    def to_dict(self) -> dict:
        return {
            "all_passed": self.all_passed,
            "passed": [{"ac": r.ac, "location": r.location} for r in self.passed],
            "failed": [
                {"ac": r.ac, "reason": r.reason, "suggestion": r.suggestion}
                for r in self.failed
            ],
            "screenshot": self.screenshot,
            "duration_seconds": self.duration_seconds,
        }


# ============================================================================
# ACTION PATTERNS
# ============================================================================

ACTION_PATTERNS = [
    # "Clicking X shows Y" → click X, verify Y appeared
    (re.compile(r"clicking (.+?) shows (.+)", re.IGNORECASE), "click"),
    # "After entering X in Y, Z appears" → fill Y with X, verify Z
    (
        re.compile(r"after entering ['\"]?(.+?)['\"]? in (.+?), (.+)", re.IGNORECASE),
        "fill",
    ),
    # "Hovering over X reveals Y" → hover X, verify Y
    (re.compile(r"hovering over (.+?) reveals (.+)", re.IGNORECASE), "hover"),
]


@dataclass
class ActionAC:
    """AC that requires an action before verification."""

    ac: str
    action_type: str  # click, fill, hover
    target: str  # what to interact with
    expected: str  # what should appear after action
    fill_value: str = ""  # value for fill actions (empty string for non-fill actions)


def classify_acs(acs: list[str]) -> tuple[list[str], list[ActionAC]]:
    """Split ACs into static (verify only) and action-based."""
    static = []
    actions = []

    for ac in acs:
        matched = False
        for pattern, action_type in ACTION_PATTERNS:
            match = pattern.match(ac)
            if not match:
                continue

            if action_type == "click":
                actions.append(
                    ActionAC(
                        ac=ac,
                        action_type="click",
                        target=match.group(1),
                        expected=match.group(2),
                    )
                )
            elif action_type == "fill":
                actions.append(
                    ActionAC(
                        ac=ac,
                        action_type="fill",
                        target=match.group(2),
                        fill_value=match.group(1),
                        expected=match.group(3),
                    )
                )
            elif action_type == "hover":
                actions.append(
                    ActionAC(
                        ac=ac,
                        action_type="hover",
                        target=match.group(1),
                        expected=match.group(2),
                    )
                )
            matched = True
            break

        if not matched:
            static.append(ac)

    return static, actions


# ============================================================================
# BROWSER INTERACTION
# ============================================================================


async def capture_page(
    url: str,
    actions: list[ActionAC],
    screenshot_dir: Path,
) -> tuple[str, str | None]:
    """Navigate to URL, perform actions, capture screenshots.

    Returns (before_path, after_path). after_path is None if no actions.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 720})

        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            logger.error(f"Failed to load {url}: {e}")
            raise

        # Before screenshot
        before_path = screenshot_dir / "before.png"
        await page.screenshot(path=str(before_path))

        # Execute actions if any
        after_path = None
        if actions:
            for action in actions:
                await _execute_action(page, action)

            # Wait for UI to settle
            await page.wait_for_timeout(500)

            after_path = screenshot_dir / "after.png"
            await page.screenshot(path=str(after_path))

        await browser.close()

    return str(before_path), str(after_path) if after_path else None


async def _execute_action(page, action: ActionAC) -> None:
    """Execute a single action on the page."""
    target = action.target.strip()

    try:
        if action.action_type == "click":
            # Try multiple strategies
            try:
                await page.get_by_role("button", name=target).click(timeout=5000)
            except:
                try:
                    await page.get_by_text(target, exact=False).first.click(
                        timeout=5000
                    )
                except:
                    await page.locator(f"text={target}").first.click(timeout=5000)

        elif action.action_type == "fill":
            # Find input by label or placeholder
            try:
                await page.get_by_label(target).fill(
                    action.fill_value or "", timeout=5000
                )
            except:
                await page.get_by_placeholder(target).fill(
                    action.fill_value or "", timeout=5000
                )

        elif action.action_type == "hover":
            await page.get_by_text(target, exact=False).first.hover(timeout=5000)

    except Exception as e:
        logger.warning(f"Action failed: {action.action_type} on '{target}': {e}")


# ============================================================================
# VISION VERIFICATION
# ============================================================================

GENERIC_LOCATIONS = {
    "on the page",
    "visible",
    "somewhere",
    "in the ui",
    "present",
    "on screen",
    "displayed",
}


def build_verification_prompt(acs: list[str], has_before_after: bool = False) -> str:
    """Build the verification prompt with grounding requirements."""
    ac_list = "\n".join(f"{i + 1}. {ac}" for i, ac in enumerate(acs))

    context = ""
    if has_before_after:
        context = """
Two screenshots provided:
- Image 1 (BEFORE): Initial page state
- Image 2 (AFTER): State after user actions

For action criteria (e.g., "Clicking X shows Y"), verify Y appears in AFTER but not BEFORE.
"""

    return f"""Verify these UI acceptance criteria.
{context}
Criteria:
{ac_list}

Respond with JSON array. For EACH criterion:

PASS example:
{{"index": 1, "status": "PASS", "location": "top-right corner, blue button labeled 'Submit'", "description": "48px button with white text"}}

FAIL example:
{{"index": 1, "status": "FAIL", "reason": "No submit button found on page", "suggestion": "Add a button element with text 'Submit' in the form footer"}}

RULES:
- PASS requires SPECIFIC location (not "visible" or "on the page")
- FAIL requires actionable suggestion for developer
- If unsure, mark FAIL with reason "Element not clearly identifiable"
- Response must be valid JSON array"""


async def verify_with_vision(
    before_path: str,
    after_path: str | None,
    acs: list[str],
) -> list[ACResult]:
    """Send screenshots + ACs to vision model, parse response."""

    # Try OpenAI first, fall back to Ollama
    try:
        return await _verify_openai(before_path, after_path, acs)
    except Exception as e:
        logger.warning(f"OpenAI failed, trying Ollama: {e}")
        return await _verify_ollama(before_path, after_path, acs)


async def _verify_openai(
    before_path: str, after_path: str | None, acs: list[str]
) -> list[ACResult]:
    """Verify using OpenAI GPT-4o."""
    import openai

    client = openai.AsyncOpenAI()
    prompt = build_verification_prompt(acs, has_before_after=after_path is not None)

    # Build content with images
    content = [{"type": "text", "text": prompt}]

    with open(before_path, "rb") as f:
        before_b64 = base64.b64encode(f.read()).decode()
    content.append(
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{before_b64}"},
        }
    )

    if after_path:
        with open(after_path, "rb") as f:
            after_b64 = base64.b64encode(f.read()).decode()
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{after_b64}"},
            }
        )

    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": content}],
        max_tokens=1500,
    )

    return _parse_response(response.choices[0].message.content, acs)


async def _verify_ollama(
    before_path: str, after_path: str | None, acs: list[str]
) -> list[ACResult]:
    """Verify using local Ollama model."""
    import httpx

    prompt = build_verification_prompt(acs, has_before_after=after_path is not None)

    with open(before_path, "rb") as f:
        images = [base64.b64encode(f.read()).decode()]

    if after_path:
        with open(after_path, "rb") as f:
            images.append(base64.b64encode(f.read()).decode())

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "glm-ocr",
                "prompt": prompt,
                "images": images,
                "stream": False,
            },
            timeout=60.0,
        )

    return _parse_response(response.json().get("response", "[]"), acs)


def _parse_response(content: str, acs: list[str]) -> list[ACResult]:
    """Parse vision model response, validate grounding."""
    # Extract JSON from response
    try:
        # Find JSON array in response
        start = content.find("[")
        end = content.rfind("]") + 1
        if start == -1 or end == 0:
            raise ValueError("No JSON array found")
        json_str = content[start:end]
        results = json.loads(json_str)
    except Exception as e:
        logger.error(f"Failed to parse response: {e}")
        # Return all failures
        return [
            ACResult(
                ac=ac,
                status="FAIL",
                reason="Verification failed: could not parse model response",
                suggestion="Try running verification again",
            )
            for ac in acs
        ]

    parsed = []
    for r in results:
        idx = r.get("index", 1) - 1
        if idx < 0 or idx >= len(acs):
            continue

        ac = acs[idx]
        status = r.get("status", "FAIL").upper()

        if status == "PASS":
            location = r.get("location", "")
            stripped_location = location.strip()
            # Validate grounding - reject generic locations
            if not stripped_location or stripped_location.lower() in GENERIC_LOCATIONS:
                parsed.append(
                    ACResult(
                        ac=ac,
                        status="FAIL",
                        reason="Model could not provide specific location",
                        suggestion="Element may not be clearly visible or properly labeled",
                    )
                )
                continue

            parsed.append(
                ACResult(
                    ac=ac,
                    status="PASS",
                    location=location,
                    description=r.get("description"),
                )
            )
        else:
            parsed.append(
                ACResult(
                    ac=ac,
                    status="FAIL",
                    reason=r.get("reason", "Criterion not met"),
                    suggestion=r.get("suggestion", "Review the UI implementation"),
                )
            )

    # Handle missing ACs
    parsed_indices = {acs.index(r.ac) for r in parsed}
    for i, ac in enumerate(acs):
        if i not in parsed_indices:
            parsed.append(
                ACResult(
                    ac=ac,
                    status="FAIL",
                    reason="Not verified by model",
                    suggestion="Try rephrasing the acceptance criterion",
                )
            )

    return parsed


# ============================================================================
# MAIN FUNCTION
# ============================================================================


async def verify_acs_async(
    url: str,
    acs: list[str],
    *,
    timeout_seconds: float = 30.0,
) -> VerifyResult:
    """Verify acceptance criteria against a live URL.

    Args:
        url: The page to verify
        acs: List of acceptance criteria strings
        timeout_seconds: Max time for entire operation

    Returns:
        VerifyResult with passed/failed ACs, screenshot path, duration

    Example:
        result = await verify_acs_async(
            url="http://localhost:3000/login",
            acs=[
                "Login button is visible",
                "Email input field exists",
                "Clicking login shows loading spinner",
            ]
        )

        if result.all_passed:
            print("All ACs verified!")
        else:
            for fail in result.failed:
                print(f"FAIL: {fail.ac}")
                print(f"  Reason: {fail.reason}")
                print(f"  Fix: {fail.suggestion}")
    """
    start = time.monotonic()

    # Guard: validate inputs
    if not url:
        return VerifyResult(
            failed=[
                ACResult(
                    ac=ac,
                    status="FAIL",
                    reason="No URL provided",
                    suggestion="Provide a valid URL to verify",
                )
                for ac in acs
            ],
            duration_seconds=0.0,
        )

    if not acs:
        return VerifyResult(duration_seconds=0.0)

    # Create temp dir for screenshots
    screenshot_dir = Path(tempfile.mkdtemp(prefix="verify_acs_"))

    try:
        # Classify ACs
        static_acs, action_acs = classify_acs(acs)
        logger.info(
            f"Verifying {len(acs)} ACs: {len(static_acs)} static, {len(action_acs)} action-based"
        )

        # Capture page
        before_path, after_path = await asyncio.wait_for(
            capture_page(url, action_acs, screenshot_dir),
            timeout=timeout_seconds,
        )

        # Verify with vision
        results = await verify_with_vision(before_path, after_path, acs)

        # Split results
        passed = [r for r in results if r.status == "PASS"]
        failed = [r for r in results if r.status == "FAIL"]

        return VerifyResult(
            passed=passed,
            failed=failed,
            screenshot=before_path,
            duration_seconds=time.monotonic() - start,
        )

    except asyncio.TimeoutError:
        logger.error(f"Verification timed out after {timeout_seconds}s")
        return VerifyResult(
            failed=[
                ACResult(
                    ac=ac,
                    status="FAIL",
                    reason="Verification timed out",
                    suggestion="Check if the URL is accessible and responsive",
                )
                for ac in acs
            ],
            duration_seconds=time.monotonic() - start,
        )
    except Exception as e:
        logger.exception(f"Verification failed: {e}")
        return VerifyResult(
            failed=[
                ACResult(
                    ac=ac,
                    status="FAIL",
                    reason=f"Verification error: {e}",
                    suggestion="Check logs for details",
                )
                for ac in acs
            ],
            duration_seconds=time.monotonic() - start,
        )


def verify_acs(url: str, acs: list[str], **kwargs) -> VerifyResult:
    """Synchronous wrapper for verify_acs_async."""
    return asyncio.run(verify_acs_async(url, acs, **kwargs))
