"""
Vision model integration for QA-Agent.

Supports multiple vision models via Ollama:
- glm-ocr (primary for Desktop - best general purpose)
- ui-tars (for Mobile/Web - specialized for standard UIs)
- moondream (lightweight fallback)

Platform-aware model selection:
- Desktop (GTK, Qt, etc.): glm-ocr (more robust for non-standard UIs)
- Web/Mobile: ui-tars (SOTA for standard mobile/web patterns)
"""

from __future__ import annotations

import re
import subprocess
import time
from functools import wraps

from .logging_config import get_logger

logger = get_logger(__name__)


# Model priority by platform
_MODEL_PRIORITY_DESKTOP = [
    "glm-ocr",  # Best for desktop apps (GTK, Qt, etc.)
    "moondream",  # Lightweight fallback
]

_MODEL_PRIORITY_WEB = [
    "ui-tars",  # SOTA for web/mobile UIs
    "glm-ocr",  # Fallback
    "moondream",  # Last resort
]

# Default to desktop for now
_MODEL_PRIORITY = _MODEL_PRIORITY_DESKTOP

_selected_model: str | None = None


def retry_with_backoff(max_attempts: int = 3, base_delay: float = 1.0):
    """Decorator for retrying functions with exponential backoff."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error: Exception | None = None
            for attempt in range(max_attempts):
                try:
                    result = func(*args, **kwargs)
                    if attempt > 0:
                        logger.info(
                            f"{func.__name__} succeeded on attempt {attempt + 1}"
                        )
                    return result
                except Exception as e:
                    last_error = e
                    if attempt < max_attempts - 1:
                        delay = base_delay * (2**attempt)
                        logger.warning(
                            f"{func.__name__} attempt {attempt + 1}/{max_attempts} failed: {e}. "
                            f"Retrying in {delay}s..."
                        )
                        time.sleep(delay)

            # Guard: last_error must be set if we exhausted retries
            if last_error is None:
                last_error = RuntimeError(f"{func.__name__} failed with unknown error")

            logger.error(
                f"{func.__name__} failed after {max_attempts} attempts: {last_error}"
            )
            raise last_error

        return wrapper

    return decorator


def set_platform(platform: str) -> None:
    """Set the target platform for model selection.

    Args:
        platform: "desktop" or "web"
    """
    global _MODEL_PRIORITY, _selected_model

    if platform == "web":
        _MODEL_PRIORITY = _MODEL_PRIORITY_WEB
    else:
        _MODEL_PRIORITY = _MODEL_PRIORITY_DESKTOP

    # Reset selection to re-evaluate
    _selected_model = None


def _get_available_models() -> list[str]:
    """Get list of available Ollama models."""
    try:
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return []

        models = []
        for line in result.stdout.strip().split("\n")[1:]:  # Skip header
            if line.strip():
                model_name = line.split()[0].split(":")[0]  # Get name without tag
                models.append(model_name.lower())
        return models
    except Exception:
        return []


def _select_best_model() -> str:
    """Select the best available vision model for current platform."""
    global _selected_model

    if _selected_model:
        return _selected_model

    available = _get_available_models()

    for preferred in _MODEL_PRIORITY:
        for available_model in available:
            if preferred in available_model.lower():
                _selected_model = available_model
                return _selected_model

    # Default fallback
    _selected_model = "glm-ocr"
    return _selected_model


def get_vision_model() -> str:
    """Get the currently selected vision model name."""
    return _select_best_model()


@retry_with_backoff(max_attempts=3, base_delay=1.0)
def ask_vision(image_path: str, question: str, model: str | None = None) -> str:
    """Ask vision model a question about an image with retry logic.

    Args:
        image_path: Path to image file
        question: Question to ask about the image
        model: Specific model to use (default: auto-select best available)

    Returns:
        Model's text response
    """
    from ..vision import ask_ollama

    if model is None:
        model = _select_best_model()

    start_time = time.time()
    logger.debug(f"Vision call: model={model}, question={question[:50]}...")

    response = ask_ollama(image_path, question, model=model)

    elapsed = time.time() - start_time
    logger.debug(f"Vision response received in {elapsed:.2f}s: {response[:100]}...")

    # Guard: response should not be empty
    if not response or not response.strip():
        raise ValueError("Empty response from vision model")

    return response


def ask_vision_bool(
    image_path: str,
    question: str,
    model: str | None = None,
    max_retries: int = 3,
) -> tuple[bool, str]:
    """Ask a yes/no question with retry on ambiguous responses.

    Following QA-Agent spec: aiBoolean questions must be answerable with YES/NO.
    Robust parsing handles various model response formats and retries with
    stronger prompts if the response is ambiguous.

    Args:
        image_path: Path to image file
        question: Yes/No question about the image
        model: Specific model to use (default: auto-select best available)
        max_retries: Maximum retry attempts for ambiguous responses

    Returns:
        (is_yes, full_response)
    """
    prompt = f"""{question}

Answer YES or NO first, then explain briefly (1 sentence max).
Format: YES: <reason> or NO: <reason>"""

    last_response = ""

    for attempt in range(max_retries):
        try:
            response = ask_vision(image_path, prompt, model)
            result, explanation = _parse_yes_no(response)
            last_response = response

            # Guard: got clear answer
            if result is not None and isinstance(result, bool):
                logger.debug(f"Vision bool: {question[:50]}... → {result}")
                return result, explanation

            # Ambiguous response - retry with stronger prompt
            if attempt < max_retries - 1:
                logger.info(
                    f"Retrying ambiguous response (attempt {attempt + 1}/{max_retries})"
                )
                prompt = f"""You MUST answer with exactly YES or NO as your first word. No other format is acceptable.

{question}

Answer: YES or NO (then brief explanation)"""
                continue

        except Exception as e:
            logger.error(f"Vision call failed on attempt {attempt + 1}: {e}")
            if attempt == max_retries - 1:
                raise

    # All retries exhausted, default to False with warning
    logger.error(
        f"Could not get clear answer after {max_retries} attempts for: {question[:50]}"
    )
    return False, f"AMBIGUOUS AFTER {max_retries} RETRIES: {last_response[:200]}"


def _parse_yes_no(response: str) -> tuple[bool | None, str]:
    """Parse YES/NO from vision model response with confidence detection.

    Returns:
        (result, explanation) where result is True/False/None (ambiguous)

    Handles cases like:
    - "YES: reason"
    - "No, because..."
    - "Format: YES: reason"  (model repeating prompt format)
    - "The answer is yes"
    """
    response_lower = response.lower().strip()

    # Guard: empty response
    if not response_lower:
        logger.warning("Empty vision response")
        return None, response

    # Strong positive indicators
    strong_yes = [
        "yes",
        "ja",
        "correct",
        "true",
        "affirmative",
        "definitely yes",
        "clearly yes",
    ]
    # Strong negative indicators
    strong_no = [
        "no",
        "nein",
        "incorrect",
        "false",
        "negative",
        "definitely no",
        "clearly no",
    ]

    # Check for strong matches first
    first_word = response_lower.split()[0] if response_lower else ""
    first_line = response_lower.split("\n")[0]

    # Explicit YES at start (most reliable)
    for yes in strong_yes:
        if first_word == yes or first_line.startswith(yes):
            logger.debug(f"Strong YES detected: {first_line[:50]}")
            return True, response

    # Explicit NO at start (most reliable)
    for no in strong_no:
        if first_word == no or first_line.startswith(no):
            logger.debug(f"Strong NO detected: {first_line[:50]}")
            return False, response

    # Check for embedded indicators with context
    yes_count = sum(1 for yes in strong_yes if yes in response_lower)
    no_count = sum(1 for no in strong_no if no in response_lower)

    # Guard: exclusive YES
    if yes_count > 0 and no_count == 0:
        logger.debug(f"Embedded YES detected (count={yes_count})")
        return True, response

    # Guard: exclusive NO
    if no_count > 0 and yes_count == 0:
        logger.debug(f"Embedded NO detected (count={no_count})")
        return False, response

    # Ambiguous - both or neither
    logger.warning(
        f"Ambiguous vision response (yes={yes_count}, no={no_count}): {response[:100]}"
    )
    return None, response

    # Look for YES/NO anywhere with word boundaries
    yes_match = re.search(r"\byes\b", response_lower)
    no_match = re.search(r"\bno\b", response_lower)

    # If both found, use the first occurrence
    if yes_match and no_match:
        return yes_match.start() < no_match.start()

    if yes_match:
        return True
    if no_match:
        return False

    # Fallback: look for positive/negative indicators
    positive_indicators = [
        "correct",
        "true",
        "affirmative",
        "visible",
        "exists",
        "present",
    ]
    negative_indicators = ["false", "incorrect", "not visible", "missing", "absent"]

    for indicator in positive_indicators:
        if indicator in response_lower:
            return True
    for indicator in negative_indicators:
        if indicator in response_lower:
            return False

    # Default to False if truly ambiguous
    return False


def ask_vision_locate(
    image_path: str, element_description: str, model: str | None = None
) -> tuple[int, int] | None:
    """Ask vision model to locate an element, return center coordinates.

    Uses UI-TARS element grounding capabilities when available.

    Args:
        image_path: Path to image file
        element_description: Description of element to find
        model: Specific model to use

    Returns:
        (x, y) center coordinates or None if not found
    """
    prompt = f"""Find the UI element: "{element_description}"

Return the bounding box as coordinates: x1,y1,x2,y2
Where (x1,y1) is top-left and (x2,y2) is bottom-right.
Example: 100,50,200,80

If element not found, respond with: NOT_FOUND"""

    response = ask_vision(image_path, prompt, model)

    if "NOT_FOUND" in response.upper():
        return None

    # Parse coordinates
    numbers = re.findall(r"\d+", response)

    if len(numbers) >= 4:
        x1, y1, x2, y2 = (
            int(numbers[0]),
            int(numbers[1]),
            int(numbers[2]),
            int(numbers[3]),
        )
        return ((x1 + x2) // 2, (y1 + y2) // 2)
    elif len(numbers) == 2:
        return (int(numbers[0]), int(numbers[1]))

    return None
