"""
Vision model integration for QA-Agent.

Uses Ollama with glm-ocr (or other vision models) for:
- UI element detection
- State verification (aiBoolean)
- Text extraction
"""
from __future__ import annotations


def ask_vision(image_path: str, question: str, model: str = "glm-ocr") -> str:
    """Ask vision model a question about an image."""
    from ..vision import ask_ollama
    return ask_ollama(image_path, question, model=model)


def ask_vision_bool(image_path: str, question: str, model: str = "glm-ocr") -> tuple[bool, str]:
    """Ask a yes/no question, return (bool, explanation).
    
    Following QA-Agent spec: aiBoolean questions must be answerable with YES/NO.
    """
    prompt = f"""{question}

Answer YES or NO first, then explain briefly (1 sentence max).
Format: YES: <reason> or NO: <reason>"""
    
    response = ask_vision(image_path, prompt, model)
    response_lower = response.lower().strip()
    
    # Parse response
    is_yes = response_lower.startswith("yes")
    
    return is_yes, response
