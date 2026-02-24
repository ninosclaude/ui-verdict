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


# Model priority by platform
_MODEL_PRIORITY_DESKTOP = [
    "glm-ocr",      # Best for desktop apps (GTK, Qt, etc.)
    "moondream",    # Lightweight fallback
]

_MODEL_PRIORITY_WEB = [
    "ui-tars",      # SOTA for web/mobile UIs
    "glm-ocr",      # Fallback
    "moondream",    # Last resort
]

# Default to desktop for now
_MODEL_PRIORITY = _MODEL_PRIORITY_DESKTOP

_selected_model: str | None = None


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
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=10
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


def ask_vision(image_path: str, question: str, model: str | None = None) -> str:
    """Ask vision model a question about an image.
    
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
    
    return ask_ollama(image_path, question, model=model)


def ask_vision_bool(image_path: str, question: str, model: str | None = None) -> tuple[bool, str]:
    """Ask a yes/no question, return (bool, explanation).
    
    Following QA-Agent spec: aiBoolean questions must be answerable with YES/NO.
    Robust parsing handles various model response formats.
    
    Args:
        image_path: Path to image file
        question: Yes/No question about the image
        model: Specific model to use (default: auto-select best available)
        
    Returns:
        (is_yes, full_response)
    """
    prompt = f"""{question}

Answer YES or NO first, then explain briefly (1 sentence max).
Format: YES: <reason> or NO: <reason>"""
    
    response = ask_vision(image_path, prompt, model)
    is_yes = _parse_yes_no(response)
    
    return is_yes, response


def _parse_yes_no(response: str) -> bool:
    """Parse YES/NO from potentially noisy model response.
    
    Handles cases like:
    - "YES: reason"
    - "No, because..."
    - "Format: YES: reason"  (model repeating prompt format)
    - "The answer is yes"
    """
    response_lower = response.lower().strip()
    
    # Direct prefix check (most common case)
    if response_lower.startswith("yes"):
        return True
    if response_lower.startswith("no"):
        return False
    
    # Look for YES/NO anywhere with word boundaries
    yes_match = re.search(r'\byes\b', response_lower)
    no_match = re.search(r'\bno\b', response_lower)
    
    # If both found, use the first occurrence
    if yes_match and no_match:
        return yes_match.start() < no_match.start()
    
    if yes_match:
        return True
    if no_match:
        return False
    
    # Fallback: look for positive/negative indicators
    positive_indicators = ["correct", "true", "affirmative", "visible", "exists", "present"]
    negative_indicators = ["false", "incorrect", "not visible", "missing", "absent"]
    
    for indicator in positive_indicators:
        if indicator in response_lower:
            return True
    for indicator in negative_indicators:
        if indicator in response_lower:
            return False
    
    # Default to False if truly ambiguous
    return False


def ask_vision_locate(image_path: str, element_description: str, model: str | None = None) -> tuple[int, int] | None:
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
        x1, y1, x2, y2 = int(numbers[0]), int(numbers[1]), int(numbers[2]), int(numbers[3])
        return ((x1 + x2) // 2, (y1 + y2) // 2)
    elif len(numbers) == 2:
        return (int(numbers[0]), int(numbers[1]))
    
    return None
