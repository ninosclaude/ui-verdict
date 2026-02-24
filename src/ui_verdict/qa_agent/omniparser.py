"""
OmniParser V2 client for structured UI element detection.

OmniParser returns:
- Bounding boxes for ALL interactive elements
- Element descriptions/labels
- Interactability classification

This replaces unreliable vision-based element finding.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path

import httpx


OMNIPARSER_URL = os.environ.get("OMNIPARSER_URL", "http://localhost:7860")


@dataclass
class UIElement:
    """A detected UI element from OmniParser."""

    label: str
    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2
    interactable: bool = True
    confidence: float = 1.0

    @property
    def center(self) -> tuple[int, int]:
        """Get center point of element."""
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    @property
    def width(self) -> int:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> int:
        return self.bbox[3] - self.bbox[1]


@dataclass
class ParseResult:
    """Result from OmniParser."""

    elements: list[UIElement]
    annotated_image: bytes | None = None  # Image with bboxes drawn


def parse_screenshot(image_path: str, timeout: float = 30.0) -> ParseResult:
    """Parse a screenshot using OmniParser V2.

    Args:
        image_path: Path to screenshot file
        timeout: Request timeout in seconds

    Returns:
        ParseResult with detected UI elements
    """
    # Read and encode image
    image_bytes = Path(image_path).read_bytes()
    image_b64 = base64.b64encode(image_bytes).decode()

    # Call OmniParser API
    try:
        response = httpx.post(
            f"{OMNIPARSER_URL}/process_image",
            json={"image": image_b64},
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as e:
        raise RuntimeError(f"OmniParser request failed: {e}")

    # Parse response
    elements = []
    for elem in data.get("parsed_elements", []):
        bbox = elem.get("bbox", [0, 0, 0, 0])
        elements.append(
            UIElement(
                label=elem.get("text", elem.get("description", "")),
                bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
                interactable=elem.get("interactable", True),
                confidence=elem.get("confidence", 1.0),
            )
        )

    # Get annotated image if available
    annotated = None
    if "annotated_image" in data:
        annotated = base64.b64decode(data["annotated_image"])

    return ParseResult(elements=elements, annotated_image=annotated)


def find_element_by_text(image_path: str, target_text: str) -> UIElement | None:
    """Find a UI element by its label/text.

    Args:
        image_path: Path to screenshot
        target_text: Text to search for (case-insensitive, fuzzy)

    Returns:
        Matching UIElement or None
    """
    result = parse_screenshot(image_path)
    target_lower = target_text.lower()

    # Exact match first
    for elem in result.elements:
        if elem.label.lower() == target_lower:
            return elem

    # Partial match
    for elem in result.elements:
        if target_lower in elem.label.lower():
            return elem

    # Word match
    for elem in result.elements:
        if any(target_lower in word.lower() for word in elem.label.split()):
            return elem

    return None


def get_all_buttons(image_path: str) -> list[UIElement]:
    """Get all interactive button-like elements.

    Returns only elements that are likely buttons (interactable, reasonable size).
    """
    result = parse_screenshot(image_path)

    buttons = []
    for elem in result.elements:
        if not elem.interactable:
            continue
        # Filter out tiny elements (likely noise)
        if elem.width < 20 or elem.height < 15:
            continue
        # Filter out huge elements (likely containers)
        if elem.width > 500 and elem.height > 200:
            continue
        buttons.append(elem)

    return buttons


def is_omniparser_available() -> bool:
    """Check if OmniParser API is available."""
    try:
        response = httpx.get(f"{OMNIPARSER_URL}/docs", timeout=5.0)
        return response.status_code == 200
    except:
        return False
