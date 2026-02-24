"""
Local OmniParser server - YOLO-only mode.

Provides /process_image endpoint returning bounding boxes for UI elements.
No captioning - just fast detection.

Start: python scripts/omniparser_server.py
Test: curl http://localhost:7860/health
"""

from __future__ import annotations

import base64
import io
import os
from pathlib import Path

import torch
import uvicorn
from fastapi import FastAPI, File, UploadFile
from PIL import Image
from pydantic import BaseModel
from ultralytics import YOLO

WEIGHTS_DIR = Path(
    os.environ.get(
        "OMNIPARSER_WEIGHTS", "/Users/nwagensonner/Development/Hobby/OmniParser/weights"
    )
)

app = FastAPI(title="OmniParser Local (YOLO-only)")


# Device selection
def get_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


DEVICE = get_device()
yolo_model: YOLO | None = None


def load_models():
    global yolo_model

    yolo_path = WEIGHTS_DIR / "icon_detect" / "model.pt"
    if not yolo_path.exists():
        yolo_path = WEIGHTS_DIR / "icon_detect" / "best.pt"

    print(f"Loading YOLO from {yolo_path}")
    print(f"Device: {DEVICE}")

    yolo_model = YOLO(str(yolo_path))
    # Don't move to MPS - YOLO handles device internally
    print("YOLO model loaded!")


class UIElement(BaseModel):
    label: str
    bbox: list[int]  # [x1, y1, x2, y2]
    confidence: float
    interactable: bool = True


class ProcessResponse(BaseModel):
    elements: list[UIElement]
    annotated_image: str | None = None


@app.on_event("startup")
async def startup():
    load_models()


@app.get("/health")
async def health():
    return {"status": "ok", "device": DEVICE, "model_loaded": yolo_model is not None}


@app.post("/process_image", response_model=ProcessResponse)
async def process_image(
    image_file: UploadFile = File(...),
    box_threshold: float = 0.3,
):
    """Detect UI elements in screenshot."""
    if yolo_model is None:
        raise RuntimeError("Model not loaded")

    contents = await image_file.read()
    image = Image.open(io.BytesIO(contents)).convert("RGB")

    # Run YOLO
    results = yolo_model.predict(image, conf=box_threshold, verbose=False)

    elements = []
    for result in results:
        for i, box in enumerate(result.boxes):
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
            conf = float(box.conf[0])

            # Use class name if available, else generic label
            cls_id = int(box.cls[0]) if box.cls is not None else 0
            class_names = result.names if hasattr(result, "names") else {}
            label = class_names.get(cls_id, f"icon_{i}")

            elements.append(
                UIElement(
                    label=label,
                    bbox=[int(x1), int(y1), int(x2), int(y2)],
                    confidence=conf,
                )
            )

    # Sort by position (top-to-bottom, left-to-right)
    elements.sort(key=lambda e: (e.bbox[1], e.bbox[0]))

    return ProcessResponse(elements=elements)


if __name__ == "__main__":
    print("Starting OmniParser server (YOLO-only)...")
    uvicorn.run(app, host="0.0.0.0", port=7860)
