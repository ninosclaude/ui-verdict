"""
Vision model integration for QA-Agent.

Uses Ollama with glm-ocr (or other vision models) for:
- UI element detection
- State verification (aiBoolean)
- Text extraction
"""
from __future__ import annotations

import re


def ask_vision(image_path: str, question: str, model: str = "glm-ocr") -> str:
    """Ask vision model a question about an image."""
    from ..vision import ask_ollama
    return ask_ollama(image_path, question, model=model)


def ask_vision_bool(image_path: str, question: str, model: str = "glm-ocr") -> tuple[bool, str]:
    """Ask a yes/no question, return (bool, explanation).
    
    Following QA-Agent spec: aiBoolean questions must be answerable with YES/NO.
    Robust parsing handles various model response formats.
    """
    prompt = f"""{question}

Answer YES or NO first, then explain briefly (1 sentence max).
Format: YES: <reason> or NO: <reason>"""
    
    response = ask_vision(image_path, prompt, model)
    
    # Robust parsing - model might prefix with "Format:" or other noise
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
