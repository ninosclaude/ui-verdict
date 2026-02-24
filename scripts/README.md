# OmniParser Local Server

FastAPI server for UI element detection using OmniParser models on Apple Silicon.

## Installation

```bash
# Install dependencies
pip install fastapi uvicorn torch torchvision transformers ultralytics pillow httpx

# Or with uv
uv pip install fastapi uvicorn torch torchvision transformers ultralytics pillow httpx
```

## Usage

### 1. Start the server

```bash
python scripts/omniparser_server.py
```

Server will start on `http://localhost:7860`

### 2. Test the server

```bash
# Health check
python scripts/test_omniparser.py

# Process an image
python scripts/test_omniparser.py path/to/screenshot.png
```

### 3. Use in code

```python
import httpx

with open("screenshot.png", "rb") as f:
    response = httpx.post(
        "http://localhost:7860/process_image",
        files={"image_file": f},
        timeout=60.0,
    )

data = response.json()
for element in data["elements"]:
    print(f"{element['label']}: {element['bbox']}")
```

## API Endpoints

### `GET /health`

Returns server status and device info.

**Response:**
```json
{
  "status": "ok",
  "device": "mps"
}
```

### `POST /process_image`

Detect UI elements in an image.

**Parameters:**
- `image_file` (file): Screenshot to process
- `box_threshold` (float, optional): Detection confidence threshold (default: 0.3)
- `caption_elements` (bool, optional): Generate labels using Florence2 (default: true)

**Response:**
```json
{
  "elements": [
    {
      "label": "search button",
      "bbox": [10, 20, 50, 60],
      "confidence": 0.95,
      "interactable": true
    }
  ],
  "annotated_image": null
}
```

## Environment Variables

- `OMNIPARSER_WEIGHTS`: Path to weights directory (default: `/Users/nwagensonner/Development/Hobby/OmniParser/weights`)

## Device Support

- **Apple Silicon (MPS)**: Preferred on M1/M2/M3 Macs
- **CUDA**: For NVIDIA GPUs
- **CPU**: Fallback (slower)

The server automatically selects the best available device.

## Troubleshooting

### Models not loading

Ensure weights are in the correct location:
```
$OMNIPARSER_WEIGHTS/
  icon_detect/model.pt
  icon_caption_florence/
    model.safetensors
    config.json
```

### MPS errors on Apple Silicon

If you get MPS-related errors, the server will fall back to CPU automatically. You can force CPU mode:

```python
# In omniparser_server.py, change get_device():
def get_device():
    return "cpu"
```

### Slow performance

- First request is slow due to model initialization
- Captioning adds ~1-2s per element
- Disable captioning for faster results: `caption_elements=false`
