"""Test OmniParser local server."""

import httpx
import sys


def test_health():
    r = httpx.get("http://localhost:7860/health")
    print(f"Health: {r.json()}")


def test_process(image_path: str):
    with open(image_path, "rb") as f:
        r = httpx.post(
            "http://localhost:7860/process_image",
            files={"image_file": f},
            timeout=60.0,
        )
    data = r.json()
    print(f"Found {len(data['elements'])} elements:")
    for elem in data["elements"][:10]:
        print(f"  - {elem['label']}: {elem['bbox']}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        test_health()
    else:
        test_process(sys.argv[1])
