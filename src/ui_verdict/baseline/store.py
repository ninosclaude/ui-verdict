"""
Baseline storage for visual regression testing.

Baselines are stored in .ui-verdict/baselines/ with:
- PNG images named by key (hash of name + viewport)
- index.json mapping names to metadata
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

from .models import BaselineMeta

logger = logging.getLogger(__name__)


def generate_key(name: str, viewport: tuple[int, int]) -> str:
    """Generate unique key for baseline from name and viewport."""
    raw = f"{name}_{viewport[0]}x{viewport[1]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


class BaselineStore:
    """Manages visual baseline storage.

    Storage structure:
        .ui-verdict/
        └── baselines/
            ├── index.json
            ├── abc123def456.png
            └── abc123def456.meta.json
    """

    def __init__(self, repo_root: Path | None = None):
        """Initialize store.

        Args:
            repo_root: Repository root. If None, uses current directory.
        """
        if repo_root is None:
            repo_root = Path.cwd()

        self.repo_root = Path(repo_root)
        self.baselines_dir = self.repo_root / ".ui-verdict" / "baselines"
        self.index_path = self.baselines_dir / "index.json"
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        """Create baselines directory if needed."""
        self.baselines_dir.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self._save_index({})

    def _load_index(self) -> dict[str, dict]:
        """Load index.json."""
        if not self.index_path.exists():
            return {}
        with open(self.index_path) as f:
            return json.load(f)

    def _save_index(self, index: dict[str, dict]) -> None:
        """Save index.json."""
        with open(self.index_path, "w") as f:
            json.dump(index, f, indent=2)

    def create(
        self,
        name: str,
        screenshot_path: str,
        url: str = "",
        viewport: tuple[int, int] = (1920, 1080),
        threshold: float = 0.001,
    ) -> BaselineMeta:
        """Create a new baseline from screenshot.

        Args:
            name: Human-readable name (e.g., "homepage", "login-form")
            screenshot_path: Path to screenshot to use as baseline
            url: URL or app state description
            viewport: Screen size
            threshold: Change threshold for comparison

        Returns:
            BaselineMeta for created baseline

        Raises:
            FileExistsError: If baseline with name already exists
            FileNotFoundError: If screenshot_path doesn't exist
        """
        # Guard: check screenshot exists
        src = Path(screenshot_path)
        if not src.exists():
            raise FileNotFoundError(f"Screenshot not found: {screenshot_path}")

        # Guard: check name not taken
        index = self._load_index()
        if name in index:
            raise FileExistsError(
                f"Baseline '{name}' already exists. Use update() or delete first."
            )

        # Generate key and paths
        key = generate_key(name, viewport)
        now = datetime.now()

        meta = BaselineMeta(
            key=key,
            name=name,
            url=url,
            viewport=viewport,
            created_at=now,
            updated_at=now,
            change_threshold=threshold,
        )

        # Copy screenshot
        dest = self.baselines_dir / f"{key}.png"
        shutil.copy2(src, dest)

        # Save to index
        index[name] = meta.to_dict()
        self._save_index(index)

        logger.info(f"Created baseline '{name}' at {dest}")
        return meta

    def get(self, name: str) -> tuple[Path, BaselineMeta] | None:
        """Get baseline image path and metadata.

        Args:
            name: Baseline name

        Returns:
            (image_path, metadata) or None if not found
        """
        index = self._load_index()

        if name not in index:
            return None

        meta = BaselineMeta.from_dict(index[name])
        image_path = self.baselines_dir / f"{meta.key}.png"

        if not image_path.exists():
            logger.warning(
                f"Baseline '{name}' in index but image missing: {image_path}"
            )
            return None

        return image_path, meta

    def update(
        self,
        name: str,
        screenshot_path: str,
    ) -> BaselineMeta:
        """Update existing baseline with new screenshot.

        Args:
            name: Baseline name to update
            screenshot_path: Path to new screenshot

        Returns:
            Updated BaselineMeta

        Raises:
            KeyError: If baseline doesn't exist
            FileNotFoundError: If screenshot_path doesn't exist
        """
        # Guard: check screenshot exists
        src = Path(screenshot_path)
        if not src.exists():
            raise FileNotFoundError(f"Screenshot not found: {screenshot_path}")

        # Guard: check baseline exists
        index = self._load_index()
        if name not in index:
            raise KeyError(f"Baseline '{name}' not found. Use create() first.")

        meta = BaselineMeta.from_dict(index[name])
        meta.updated_at = datetime.now()

        # Copy new screenshot
        dest = self.baselines_dir / f"{meta.key}.png"
        shutil.copy2(src, dest)

        # Update index
        index[name] = meta.to_dict()
        self._save_index(index)

        logger.info(f"Updated baseline '{name}'")
        return meta

    def delete(self, name: str) -> bool:
        """Delete a baseline.

        Args:
            name: Baseline name to delete

        Returns:
            True if deleted, False if not found
        """
        index = self._load_index()

        if name not in index:
            return False

        meta = BaselineMeta.from_dict(index[name])
        image_path = self.baselines_dir / f"{meta.key}.png"

        # Remove image
        if image_path.exists():
            image_path.unlink()

        # Remove from index
        del index[name]
        self._save_index(index)

        logger.info(f"Deleted baseline '{name}'")
        return True

    def list_all(self) -> list[BaselineMeta]:
        """List all baselines.

        Returns:
            List of all baseline metadata
        """
        index = self._load_index()
        return [BaselineMeta.from_dict(data) for data in index.values()]

    def exists(self, name: str) -> bool:
        """Check if baseline exists."""
        index = self._load_index()
        return name in index
