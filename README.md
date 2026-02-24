# ui-verdict

MCP server for visual UI verification in agentic coding workflows.

Enables AI agents to visually verify their GUI applications through screenshots, action-reaction testing, and vision model analysis — **without stealing focus** from the developer.

## Features

### Local Testing (macOS)
- `screenshot` — Capture screen or specific app window
- `verify_action` — Send input and verify visible change
- `analyze_ui` — Check contrast, layout metrics
- `ask_vision` — Query vision model about UI
- `analyze_ui_full` — Combined metrics + vision analysis

### VM Testing (Linux via OrbStack)
- `vm_deploy` — Deploy and run app in headless Linux VM
- `vm_screenshot` — Capture VM display
- `vm_action` — Send keyboard/mouse to VM
- `vm_verify_action` — Action-reaction testing in VM
- `vm_analyze` — Full analysis of VM screenshot
- `vm_status` — Check VM environment status
- `vm_stop` — Stop running applications

## Quick Start

### 1. Install

```bash
cd visual-ui-verdict
pip install -e .
```

### 2. Configure MCP

Add to your MCP config (e.g., `~/.config/opencode/opencode.json`):

```json
{
  "mcpServers": {
    "ui-verdict": {
      "command": "python",
      "args": ["-m", "ui_verdict.server"],
      "cwd": "/path/to/visual-ui-verdict/src"
    }
  }
}
```

### 3. Set up VM (for focus-free testing)

```bash
# Create Ubuntu VM via OrbStack
orb create ubuntu:24.04 ui-test

# Install dependencies (one-time)
orb run -m ui-test bash -c 'sudo apt-get update && sudo apt-get install -y xvfb xdotool scrot'
```

## Usage Examples

### VM Testing Workflow

```python
# Deploy app to VM
vm_deploy("/path/to/my-app", "my-app")

# Take screenshot
vm_screenshot("/tmp/app.png")

# Send input and verify response
vm_verify_action("key:space", expected="any_change")

# Click at coordinates
vm_action("click:500,300")

# Full visual analysis
vm_analyze("Main window should show login form")

# Stop app
vm_stop("my-app")
```

### Imagination-specific Workflow

```python
# Build on Mac
# cargo build --release

# Deploy to VM and run
vm_deploy("target/release/imagination", "imagination")

# Verify UI loads
vm_analyze("Should show Imagination welcome screen with Open Image button")

# Test keyboard shortcut
vm_verify_action("key:o", expected="any_change")  # Should open file dialog
```

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                         macOS                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐      │
│  │   Agent     │───▶│  ui-verdict │───▶│   Ollama    │      │
│  │  (Claude)   │    │  MCP Server │    │  (glm-ocr)  │      │
│  └─────────────┘    └──────┬──────┘    └─────────────┘      │
│                            │                                  │
│                      orb run                                  │
│                            │                                  │
├────────────────────────────┼─────────────────────────────────┤
│                            ▼                                  │
│                    OrbStack VM (ui-test)                     │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐      │
│  │    Xvfb     │───▶│    App      │◀───│   xdotool   │      │
│  │  (Display)  │    │ (headless)  │    │   (input)   │      │
│  └─────────────┘    └─────────────┘    └─────────────┘      │
│                            │                                  │
│                          scrot                                │
│                            │                                  │
│                            ▼                                  │
│                    /mnt/mac/tmp/                             │
│                    (shared filesystem)                        │
└──────────────────────────────────────────────────────────────┘
```

## Why VM Testing?

**Problem**: When testing GUI apps locally, input automation (pynput, pyautogui) steals focus from your editor — interrupting your workflow.

**Solution**: Run the app in a headless Linux VM via OrbStack. The agent can click, type, and screenshot freely while you continue working.

Benefits:
- ✅ No focus stealing — work uninterrupted
- ✅ Isolated environment — reproducible tests
- ✅ Fast — OrbStack VMs are lightweight
- ✅ Cross-platform — test Linux builds from Mac

## Requirements

- Python 3.10+
- macOS (for local testing)
- OrbStack (for VM testing)
- Ollama with glm-ocr model (for vision analysis)

## Development

```bash
# Run tests
pytest tests/ -v

# Run only VM integration tests
pytest tests/test_vm.py -v

# Skip integration tests if VM not running
pytest tests/ -v -k "not Integration"
```

## MCP Tools Reference

| Tool | Description |
|------|-------------|
| `screenshot` | Take screenshot (local) |
| `verify_action` | Send input + verify change (local) |
| `analyze_ui` | Metrics analysis (contrast, layout) |
| `ask_vision` | Query vision model |
| `analyze_ui_full` | Combined analysis |
| `vm_deploy` | Deploy app to VM |
| `vm_screenshot` | Screenshot VM display |
| `vm_action` | Send input to VM |
| `vm_verify_action` | Action-reaction in VM |
| `vm_analyze` | Full VM analysis |
| `vm_status` | Check VM status |
| `vm_stop` | Stop VM app |
