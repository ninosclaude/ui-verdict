# OmniParser V2 Integration

## Overview

Integrated Microsoft's OmniParser V2 to replace unreliable glm-ocr vision-based element detection. OmniParser provides structured UI element detection with bounding boxes for ALL interactive elements.

## Changes Made

### 1. New Module: `omniparser.py`

Location: `/src/ui_verdict/qa_agent/omniparser.py`

**Key Components:**
- `UIElement` - Dataclass for detected UI elements with bbox, label, interactable flag
- `ParseResult` - Container for parse results with optional annotated image
- `parse_screenshot()` - Main parsing function
- `find_element_by_text()` - Find element by fuzzy text match
- `get_all_buttons()` - Get all interactive button-like elements
- `is_omniparser_available()` - Health check function

**Features:**
- Fuzzy text matching (exact, partial, word-level)
- Size filtering for buttons (removes noise and containers)
- 30-second timeout for API calls
- Environment variable configuration via `OMNIPARSER_URL`

### 2. Updated: `executor.py`

**Function:** `click_element_by_text()`

**Changes:**
- Primary: OmniParser-based element detection (structured, reliable)
- Fallback: Vision model detection (if OmniParser unavailable)
- Guard clause pattern - early return on success
- Clear messaging about which method was used

**Benefits:**
- No more coordinate parsing from text responses
- Direct bbox access
- Fuzzy matching built-in
- Graceful degradation

### 3. Updated: `checks.py`

**Function:** `check_f06_all_buttons_bound()`

**Changes:**
- Primary: OmniParser's `get_all_buttons()` (detects ALL buttons)
- Fallback: Vision model button listing (if OmniParser unavailable)
- Guard clause pattern with try-except for OmniParser errors
- Method tracking in result details

**Benefits:**
- No missed buttons
- Structured button list
- Size-based filtering (removes noise)
- Confidence scores available

### 4. Docker Setup

**Location:** `/docker/omniparser/`

**Files:**
- `docker-compose.yml` - OmniParser service with GPU support
- `README.md` - Setup and troubleshooting guide

**Configuration:**
- Port 7860
- NVIDIA GPU required
- CUDA support
- Auto-restart

### 5. Updated Dependencies

**File:** `pyproject.toml`

**Added:**
- `httpx>=0.27.0` (for OmniParser API calls)

Note: httpx was already present as transitive dependency, now explicit.

## Usage

### Start OmniParser

```bash
cd docker/omniparser
docker compose up -d
```

### Check Availability

```bash
curl http://localhost:7860/docs
```

### Set Custom URL

```bash
export OMNIPARSER_URL=http://your-host:7860
```

### In Code

```python
from ui_verdict.qa_agent.omniparser import find_element_by_text, is_omniparser_available

if is_omniparser_available():
    element = find_element_by_text(screenshot_path, "Submit")
    if element:
        x, y = element.center
        print(f"Found at ({x}, {y})")
```

## Architecture Pattern

**Guard Clause Fallback Pattern:**

```python
# 1. Check availability (fast, prevents timeouts)
if is_omniparser_available():
    try:
        # 2. Use primary method
        result = use_omniparser(input)
        if result:
            return process_result(result)
        return failure("Not found")
    except Exception as e:
        # 3. Log and fall through to fallback
        log(f"OmniParser failed: {e}")

# 4. Fallback method
result = use_vision(input)
return process_fallback(result)
```

**Key Principles:**
- No else statements
- Early returns on success
- Clear error messages
- Graceful degradation
- Method tracking in results

## Testing

### Import Verification

```bash
# Test omniparser module
uv run python -c "from ui_verdict.qa_agent.omniparser import is_omniparser_available; print(is_omniparser_available())"

# Test executor integration
uv run python -c "from ui_verdict.qa_agent.executor import click_element_by_text; print('OK')"

# Test checks integration
uv run python -c "from ui_verdict.qa_agent.checks import check_f06_all_buttons_bound; print('OK')"
```

### Functional Test

1. Start OmniParser: `cd docker/omniparser && docker compose up -d`
2. Run QA-Agent with any UI test
3. Check logs for "via OmniParser" messages
4. Verify no fallback to vision model

## Benefits

### Reliability
- ✅ Structured data (no text parsing)
- ✅ ALL elements detected (no missed buttons)
- ✅ Confidence scores
- ✅ Bounding boxes for every element

### Performance
- ✅ Faster than vision model prompts
- ✅ Single API call per screenshot
- ✅ No coordinate extraction/parsing

### Maintainability
- ✅ Clear separation of concerns
- ✅ Fallback to vision model
- ✅ Environment-based configuration
- ✅ No breaking changes to existing code

## Requirements

### Runtime
- OmniParser API (optional, falls back to vision)
- httpx library (installed)
- Environment: `OMNIPARSER_URL` (optional)

### OmniParser Service
- Docker with GPU support
- NVIDIA GPU with CUDA
- `nvidia-container-toolkit`

## Troubleshooting

### "OmniParser request failed"
- Check if OmniParser is running: `docker compose ps`
- Check logs: `docker compose logs omniparser`
- Verify URL: `echo $OMNIPARSER_URL`

### GPU Not Available
```bash
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

### Slow First Request
First request may take longer due to model loading. Subsequent requests will be faster.

## Future Enhancements

1. **Caching**: Cache parse results for same screenshot
2. **Batch Processing**: Parse multiple screenshots in parallel
3. **Element Relationships**: Detect parent-child relationships
4. **Accessibility**: Extract ARIA labels and roles
5. **Visual Hierarchy**: Build element tree structure

## References

- OmniParser: https://github.com/microsoft/OmniParser
- OmniParser API: https://github.com/addy999/omniparser-api
- Vision Model Fallback: `ui_verdict/qa_agent/vision.py`
