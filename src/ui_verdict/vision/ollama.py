"""Vision model integration via Ollama (local)."""
from __future__ import annotations

from pathlib import Path

try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False


DEFAULT_MODEL = "glm-ocr"  # Best for UI analysis — reads all text, understands layout
FALLBACK_MODELS = ["moondream", "llava", "gemma3"]  # In order of preference


class OllamaVision:
    """Wrapper for Ollama vision models with automatic fallback."""

    def __init__(self, model: str = DEFAULT_MODEL):
        if not OLLAMA_AVAILABLE:
            raise ImportError("ollama package not installed. Run: pip install ollama")
        self.model = model
        self._verified = False

    def _ensure_model(self) -> None:
        """Check model is available, try fallbacks if not."""
        if self._verified:
            return

        try:
            result = ollama.list()
            # Handle both dict and object responses
            if isinstance(result, dict):
                models_data = result.get("models", [])
            else:
                models_data = getattr(result, "models", [])
            
            # Extract model names (handle both dict and object)
            models = []
            for m in models_data:
                if isinstance(m, dict):
                    name = m.get("name", "")
                else:
                    name = getattr(m, "name", "") or getattr(m, "model", "")
                if name:
                    models.append(name.lower())
        except Exception as e:
            raise RuntimeError(f"Could not list Ollama models: {e}")

        # Check primary model (match prefix, e.g. "glm-ocr" matches "glm-ocr:latest")
        model_lower = self.model.lower()
        for m in models:
            if m.startswith(model_lower) or model_lower in m:
                self._verified = True
                return

        # Try fallbacks
        for fallback in FALLBACK_MODELS:
            fallback_lower = fallback.lower()
            for m in models:
                if m.startswith(fallback_lower) or fallback_lower in m:
                    self.model = fallback
                    self._verified = True
                    return

        raise RuntimeError(
            f"No vision model available (checked: {self.model}, {FALLBACK_MODELS}). "
            f"Available: {models}. Install with: ollama pull {DEFAULT_MODEL}"
        )

    def ask(self, image_path: str, question: str) -> str:
        """Ask a question about an image. Returns the model's answer."""
        self._ensure_model()

        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        response = ollama.chat(
            model=self.model,
            messages=[{
                "role": "user",
                "content": question,
                "images": [str(path)],
            }],
        )
        return response["message"]["content"]

    def analyze_ui(self, image_path: str) -> dict:
        """Comprehensive UI analysis. Returns structured findings."""
        self._ensure_model()

        questions = {
            "text": "Read all visible text in this UI screenshot. List each text element you can see.",
            "layout": "Describe the layout structure of this UI. What panels, buttons, and sections exist?",
            "issues": "Are there any visual issues? Check for: overlapping elements, cut-off text, low contrast, misalignment.",
        }

        results = {}
        for key, question in questions.items():
            try:
                results[key] = self.ask(image_path, question)
            except Exception as e:
                results[key] = f"Error: {e}"

        return results


# Module-level convenience function
_default_vision: OllamaVision | None = None


def ask_ollama(image_path: str, question: str, model: str = DEFAULT_MODEL) -> str:
    """Ask a vision model about an image. Uses glm-ocr by default."""
    global _default_vision
    if _default_vision is None or _default_vision.model != model:
        _default_vision = OllamaVision(model)
    return _default_vision.ask(image_path, question)
