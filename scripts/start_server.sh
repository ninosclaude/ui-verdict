#!/bin/bash
# Start OmniParser local server

set -e

echo "Starting OmniParser server on port 7860..."
echo "Device: $(python3 -c 'import torch; print("mps" if torch.backends.mps.is_available() else "cpu")')"

cd "$(dirname "$0")/.."
python scripts/omniparser_server.py
