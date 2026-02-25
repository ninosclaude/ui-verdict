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
import os
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

            # Wait for navigation/network to settle (action might trigger page change)
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except:
                pass  # Page might not navigate, that's OK

            # Extra wait for animations/transitions
            await page.wait_for_timeout(500)

            after_path = screenshot_dir / "after.png"
            await page.screenshot(path=str(after_path))

        await browser.close()

    return str(before_path), str(after_path) if after_path else None


async def _execute_action(page, action: ActionAC) -> None:
    """Execute a single action on the page."""
    target = action.target.strip()

    # Extract core text - remove trailing "button", "link", "icon" etc
    core_target = re.sub(
        r"\s*(button|link|icon|menu|tab)$", "", target, flags=re.IGNORECASE
    ).strip()

    try:
        if action.action_type == "click":
            # Try multiple strategies with both full and core target
            clicked = False
            for search_text in [target, core_target]:
                if clicked:
                    break
                # Strategy 1: Button by role
                try:
                    await page.get_by_role("button", name=search_text).click(
                        timeout=3000
                    )
                    clicked = True
                    continue
                except:
                    pass
                # Strategy 2: Link by role
                try:
                    await page.get_by_role("link", name=search_text).click(timeout=3000)
                    clicked = True
                    continue
                except:
                    pass
                # Strategy 3: Any text match
                try:
                    await page.get_by_text(search_text, exact=False).first.click(
                        timeout=3000
                    )
                    clicked = True
                    continue
                except:
                    pass

            if not clicked:
                logger.warning(
                    f"Could not click '{target}' (also tried '{core_target}')"
                )

        elif action.action_type == "fill":
            # Find input by label or placeholder
            try:
                await page.get_by_label(target).fill(
                    action.fill_value or "", timeout=5000
                )
            except:
                try:
                    await page.get_by_placeholder(target).fill(
                        action.fill_value or "", timeout=5000
                    )
                except:
                    # Try core target without "field", "input" suffix
                    core_input = re.sub(
                        r"\s*(field|input|box)$", "", target, flags=re.IGNORECASE
                    ).strip()
                    await page.get_by_label(core_input).fill(
                        action.fill_value or "", timeout=5000
                    )

        elif action.action_type == "hover":
            try:
                await page.get_by_text(target, exact=False).first.hover(timeout=5000)
            except:
                core_hover = re.sub(
                    r"\s*(button|link|icon|element)$", "", target, flags=re.IGNORECASE
                ).strip()
                await page.get_by_text(core_hover, exact=False).first.hover(
                    timeout=5000
                )

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

For action criteria (e.g., "Clicking X shows Y"):
- Compare BEFORE and AFTER screenshots
- PASS if Y is visible in AFTER (regardless of whether page changed/navigated)
- FAIL only if Y is not visible in AFTER at all
- Navigation to a new page counts as "showing" the new content
"""

    if has_before_after:
        intro = "You are a precise UI testing assistant. Examine both screenshots and verify each criterion."
    else:
        intro = "You are a precise UI testing assistant. Examine this screenshot and verify each criterion."

    return f"""{intro}

SCAN THE ENTIRE PAGE: navigation bar, main content, sidebar, footer - all visible elements.
{context}
Criteria:
{ac_list}

OUTPUT FORMAT - JSON array with one object per criterion:

For PASS, location must be SPECIFIC like:
- "top-center, large dark heading"
- "center, first input field with Email label above"
- "below password field, primary blue button"
- "footer section, small gray link"

NOT acceptable locations: "visible", "on the page", "present", "Form field", "Link", "Button"

PASS example:
{{"index": 1, "status": "PASS", "location": "center-left, input with placeholder Email", "description": "White input field with gray placeholder"}}

FAIL example:
{{"index": 1, "status": "FAIL", "reason": "No email input found in form area", "suggestion": "Add input[type=email] to login form"}}

Return JSON array with exactly {len(acs)} objects:"""


def _get_configured_model() -> str:
    """Get vision model from environment variable or auto-detect."""
    configured = os.environ.get("UI_VERDICT_MODEL", "").strip()
    if configured:
        return configured

    # Auto-detect: prefer gpt-4o if OpenAI key is set
    if os.environ.get("OPENAI_API_KEY"):
        return "gpt-4o"

    # Default to best local fallback
    return "gemma3:12b"


async def verify_with_vision(
    before_path: str,
    after_path: str | None,
    acs: list[str],
) -> list[ACResult]:
    """Send screenshots + ACs to vision model, parse response."""
    model = _get_configured_model()
    logger.info(f"Using vision model: {model}")

    # For action-based ACs, only use the AFTER image (simpler for local models)
    # The before image comparison adds complexity that confuses gemma3
    image_path = after_path if after_path else before_path
    has_action = after_path is not None

    # Route to appropriate provider
    if model.startswith("gpt-"):
        try:
            # GPT-4o can handle both images well
            return await _verify_openai(before_path, after_path, acs, model)
        except Exception as e:
            logger.warning(f"OpenAI failed: {e}, falling back to local model")
            # Fall through to Ollama

    # For Ollama, use single-image approach for action ACs
    if has_action and not model.startswith("gpt-"):
        logger.info("Action-based ACs detected, using single-image verification")
        return await _verify_ollama_single(image_path, acs, model)

    return await _verify_ollama(before_path, after_path, acs, model)


async def _verify_openai(
    before_path: str, after_path: str | None, acs: list[str], model: str = "gpt-4o"
) -> list[ACResult]:
    """Verify using OpenAI vision model."""
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
        model=model,
        messages=[{"role": "user", "content": content}],
        max_tokens=1500,
    )

    content_text = response.choices[0].message.content
    if not content_text:
        raise ValueError("Empty response from OpenAI")

    return _parse_response(content_text, acs)


async def _verify_ollama(
    before_path: str, after_path: str | None, acs: list[str], model: str = "gemma3:12b"
) -> list[ACResult]:
    """Verify using local Ollama model with fallback chain."""
    import httpx

    prompt = build_verification_prompt(acs, has_before_after=after_path is not None)

    with open(before_path, "rb") as f:
        images = [base64.b64encode(f.read()).decode()]

    if after_path:
        with open(after_path, "rb") as f:
            images.append(base64.b64encode(f.read()).decode())

    # Define fallback chain if model is gemma3:12b (best local option)
    models_to_try = [model]
    if model == "gemma3:12b":
        models_to_try.append("glm-ocr")  # Fast fallback if gemma3 fails

    last_error = None
    for model_name in models_to_try:
        try:
            logger.info(f"Trying Ollama model: {model_name}")
            # Gemma3 needs more time for reliable JSON generation
            timeout = 90.0 if "gemma" in model_name else 60.0

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:11434/api/generate",
                    json={
                        "model": model_name,
                        "prompt": prompt,
                        "images": images,
                        "stream": False,
                    },
                    timeout=timeout,
                )

            response_text = response.json().get("response", "")
            if not response_text:
                raise ValueError(f"Empty response from {model_name}")

            return _parse_response(response_text, acs)

        except Exception as e:
            last_error = e
            logger.warning(f"Ollama model {model_name} failed: {e}")
            continue

    # All models failed
    raise Exception(f"All Ollama models failed. Last error: {last_error}")


async def _verify_ollama_single(
    image_path: str, acs: list[str], model: str = "gemma3:12b"
) -> list[ACResult]:
    """Verify using single image (for action-based ACs with Ollama).

    Transforms action ACs like "Clicking X shows Y" into "Y is visible".
    """
    import httpx

    # Transform action ACs into simple visibility checks
    transformed_acs = []
    for ac in acs:
        # "Clicking X shows Y" → "Y is visible"
        match = re.match(r"clicking .+? shows (.+)", ac, re.IGNORECASE)
        if match:
            transformed_acs.append(f"{match.group(1)} is visible")
            continue
        # "Hovering over X reveals Y" → "Y is visible"
        match = re.match(r"hovering over .+? reveals (.+)", ac, re.IGNORECASE)
        if match:
            transformed_acs.append(f"{match.group(1)} is visible")
            continue
        # "After entering X in Y, Z appears" → "Z is visible"
        match = re.match(
            r"after entering .+? in .+?, (.+?) (?:appears|is shown)", ac, re.IGNORECASE
        )
        if match:
            transformed_acs.append(f"{match.group(1)} is visible")
            continue
        # Default: keep as-is
        transformed_acs.append(ac)

    ac_list = "\n".join(f"{i + 1}. {ac}" for i, ac in enumerate(transformed_acs))

    prompt = f"""You are a UI testing assistant. This screenshot shows the CURRENT state of a web page AFTER a user action was performed.

Check if each element is visible in this screenshot:

{ac_list}

For each criterion:
PASS if the element IS visible (provide specific location)
FAIL if the element is NOT visible (explain what you see instead)

JSON format:
PASS: {{"index": N, "status": "PASS", "location": "center, form with 3 input fields", "description": "registration form visible"}}
FAIL: {{"index": N, "status": "FAIL", "reason": "no form visible, page shows landing content", "suggestion": "ensure action navigates to form"}}

Return JSON array:"""

    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()

    fallback_models = [model, "glm-ocr"] if model != "glm-ocr" else ["glm-ocr"]

    for try_model in fallback_models:
        try:
            timeout = 90.0 if "gemma" in try_model or "12b" in try_model else 60.0
            logger.info(f"Trying Ollama model: {try_model}")

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:11434/api/generate",
                    json={
                        "model": try_model,
                        "prompt": prompt,
                        "images": [image_b64],
                        "stream": False,
                    },
                    timeout=timeout,
                )

            if response.status_code != 200:
                continue

            return _parse_response(response.json().get("response", "[]"), acs)
        except Exception as e:
            logger.warning(f"Ollama {try_model} failed: {e}")
            continue

    # All models failed
    return [
        ACResult(
            ac=ac,
            status="FAIL",
            reason="All vision models failed",
            suggestion="Check Ollama is running and models are available",
        )
        for ac in acs
    ]


def _parse_response(content: str, acs: list[str]) -> list[ACResult]:
    """Parse vision model response, validate grounding."""
    # Extract JSON from response
    try:
        # Strip markdown code blocks if present
        cleaned = content.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        # Try to find JSON array first
        array_start = cleaned.find("[")
        array_end = cleaned.rfind("]") + 1

        # Try to find JSON object as fallback
        obj_start = cleaned.find("{")
        obj_end = cleaned.rfind("}") + 1

        results = None

        # Prefer array if found
        if array_start != -1 and array_end > array_start:
            json_str = cleaned[array_start:array_end]
            results = json.loads(json_str)

        # Fall back to single object, wrap in array
        if results is None and obj_start != -1 and obj_end > obj_start:
            json_str = cleaned[obj_start:obj_end]
            single_result = json.loads(json_str)
            results = [single_result]

        if results is None:
            raise ValueError("No JSON array or object found in response")

        # Ensure results is a list
        if not isinstance(results, list):
            results = [results]

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
