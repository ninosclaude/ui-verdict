# OmniParser V2 Setup

OmniParser provides structured UI element detection with bounding boxes for ALL interactive elements.

## Requirements

- Docker with NVIDIA GPU support
- CUDA-capable GPU
- `nvidia-container-toolkit` installed

## Quick Start

```bash
# Start OmniParser
docker compose up -d

# Check if it's running
curl http://localhost:7860/docs

# Stop OmniParser
docker compose down
```

## Configuration

Set the `OMNIPARSER_URL` environment variable to use a different URL:

```bash
export OMNIPARSER_URL=http://your-host:7860
```

Default: `http://localhost:7860`

## Integration

The QA-Agent automatically uses OmniParser if available, falling back to vision models if not.

### In executor.py
- `click_element_by_text()` - Uses OmniParser for element detection

### In checks.py
- `check_f06_all_buttons_bound()` - Uses OmniParser to list all buttons

## API Reference

### POST /process_image

Request:
```json
{
  "image": "base64-encoded-image"
}
```

Response:
```json
{
  "parsed_elements": [
    {
      "text": "Button Label",
      "bbox": [x1, y1, x2, y2],
      "interactable": true,
      "confidence": 0.95
    }
  ],
  "annotated_image": "base64-encoded-annotated-image"
}
```

## Troubleshooting

### GPU Not Available
Ensure NVIDIA Docker runtime is installed:
```bash
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

### Connection Refused
Check if service is running:
```bash
docker compose logs omniparser
```

### Slow Responses
First request may be slow due to model loading. Subsequent requests should be faster.
