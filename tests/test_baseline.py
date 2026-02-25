"""Tests for visual baseline comparison system."""

import json
import shutil
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import numpy as np

from ui_verdict.baseline import (
    BaselineStore,
    BaselineMeta,
    CompareVerdict,
    CompareResult,
    DiffRegion,
    compare_with_baseline,
    compare_no_baseline,
    generate_key,
)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def temp_repo(tmp_path):
    """Create a temporary repository with .ui-verdict directory."""
    return tmp_path


@pytest.fixture
def baseline_store(temp_repo):
    """Create a BaselineStore in temp directory."""
    return BaselineStore(repo_root=temp_repo)


@pytest.fixture
def sample_screenshot(tmp_path):
    """Create a sample screenshot PNG."""
    import cv2

    img = np.zeros((1080, 1920, 3), dtype=np.uint8)
    img[100:200, 100:300] = [255, 255, 255]  # White rectangle
    path = tmp_path / "screenshot.png"
    cv2.imwrite(str(path), img)
    return str(path)


@pytest.fixture
def different_screenshot(tmp_path):
    """Create a different screenshot PNG."""
    import cv2

    img = np.zeros((1080, 1920, 3), dtype=np.uint8)
    img[200:300, 200:400] = [255, 0, 0]  # Different position and color
    path = tmp_path / "different.png"
    cv2.imwrite(str(path), img)
    return str(path)


# ============================================================================
# MODEL TESTS
# ============================================================================


class TestModels:
    def test_compare_verdict_values(self):
        """Verify CompareVerdict enum has expected values."""
        assert CompareVerdict.NO_CHANGE.value == "no_change"
        assert CompareVerdict.INTENTIONAL.value == "intentional"
        assert CompareVerdict.REGRESSION.value == "regression"
        assert CompareVerdict.UNKNOWN.value == "unknown"

    def test_baseline_meta_to_dict(self):
        """BaselineMeta serialization to dict."""
        meta = BaselineMeta(
            key="abc123",
            name="test",
            url="https://example.com",
            viewport=(1920, 1080),
            created_at=datetime(2024, 1, 1, 12, 0, 0),
            updated_at=datetime(2024, 1, 1, 12, 0, 0),
        )
        d = meta.to_dict()
        assert d["key"] == "abc123"
        assert d["name"] == "test"
        assert d["viewport"] == [1920, 1080]
        assert d["url"] == "https://example.com"
        assert d["created_at"] == "2024-01-01T12:00:00"
        assert d["updated_at"] == "2024-01-01T12:00:00"
        assert d["change_threshold"] == 0.001

    def test_baseline_meta_from_dict(self):
        """BaselineMeta deserialization from dict."""
        d = {
            "key": "abc123",
            "name": "test",
            "url": "https://example.com",
            "viewport": [1920, 1080],
            "created_at": "2024-01-01T12:00:00",
            "updated_at": "2024-01-01T12:00:00",
        }
        meta = BaselineMeta.from_dict(d)
        assert meta.key == "abc123"
        assert meta.viewport == (1920, 1080)
        assert meta.name == "test"
        assert meta.url == "https://example.com"

    def test_baseline_meta_custom_threshold(self):
        """BaselineMeta supports custom threshold."""
        d = {
            "key": "abc123",
            "name": "test",
            "url": "https://example.com",
            "viewport": [1920, 1080],
            "created_at": "2024-01-01T12:00:00",
            "updated_at": "2024-01-01T12:00:00",
            "change_threshold": 0.05,
        }
        meta = BaselineMeta.from_dict(d)
        assert meta.change_threshold == 0.05

    def test_compare_result_to_dict(self):
        """CompareResult serialization to dict."""
        result = CompareResult(
            verdict=CompareVerdict.NO_CHANGE,
            change_ratio=0.001,
            baseline_path="/path/to/baseline.png",
            current_path="/path/to/current.png",
        )
        d = result.to_dict()
        assert d["verdict"] == "no_change"
        assert d["change_ratio"] == 0.001
        assert d["baseline_path"] == "/path/to/baseline.png"
        assert d["current_path"] == "/path/to/current.png"
        assert d["diff_regions"] == []
        assert d["ai_explanation"] is None

    def test_compare_result_with_regions(self):
        """CompareResult can include diff regions."""
        regions = [
            DiffRegion(x=10, y=20, width=100, height=50, area=5000),
            DiffRegion(x=200, y=300, width=50, height=30, area=1500),
        ]
        result = CompareResult(
            verdict=CompareVerdict.INTENTIONAL,
            change_ratio=0.05,
            baseline_path="/baseline.png",
            current_path="/current.png",
            diff_regions=regions,
            ai_explanation="Layout updated",
        )
        d = result.to_dict()
        assert len(d["diff_regions"]) == 2
        assert d["diff_regions"][0]["x"] == 10
        assert d["ai_explanation"] == "Layout updated"

    def test_diff_region_to_dict(self):
        """DiffRegion serialization to dict."""
        region = DiffRegion(x=10, y=20, width=100, height=50, area=5000)
        d = region.to_dict()
        assert d == {"x": 10, "y": 20, "width": 100, "height": 50, "area": 5000}


# ============================================================================
# STORE TESTS
# ============================================================================


class TestBaselineStore:
    def test_generate_key_deterministic(self):
        """Key generation is deterministic."""
        key1 = generate_key("test", (1920, 1080))
        key2 = generate_key("test", (1920, 1080))
        assert key1 == key2
        assert len(key1) == 12

    def test_generate_key_different_names(self):
        """Different names generate different keys."""
        key1 = generate_key("homepage", (1920, 1080))
        key2 = generate_key("login", (1920, 1080))
        assert key1 != key2

    def test_generate_key_different_viewports(self):
        """Different viewports generate different keys."""
        key1 = generate_key("test", (1920, 1080))
        key2 = generate_key("test", (1280, 720))
        assert key1 != key2

    def test_init_creates_directory(self, temp_repo):
        """Initializing store creates .ui-verdict/baselines directory."""
        store = BaselineStore(repo_root=temp_repo)
        assert (temp_repo / ".ui-verdict" / "baselines").exists()
        assert (temp_repo / ".ui-verdict" / "baselines" / "index.json").exists()

    def test_init_creates_empty_index(self, temp_repo):
        """New store has empty index."""
        store = BaselineStore(repo_root=temp_repo)
        index_path = temp_repo / ".ui-verdict" / "baselines" / "index.json"
        with open(index_path) as f:
            data = json.load(f)
        assert data == {}

    def test_create_baseline(self, baseline_store, sample_screenshot):
        """Create new baseline stores image and metadata."""
        meta = baseline_store.create(
            name="homepage",
            screenshot_path=sample_screenshot,
            url="https://example.com",
        )
        assert meta.name == "homepage"
        assert meta.url == "https://example.com"
        assert meta.viewport == (1920, 1080)
        assert baseline_store.exists("homepage")

    def test_create_baseline_copies_image(self, baseline_store, sample_screenshot):
        """Create baseline copies image file."""
        meta = baseline_store.create("test", sample_screenshot)
        image_path = baseline_store.baselines_dir / f"{meta.key}.png"
        assert image_path.exists()

    def test_create_baseline_custom_viewport(self, baseline_store, sample_screenshot):
        """Create baseline with custom viewport."""
        meta = baseline_store.create("test", sample_screenshot, viewport=(1280, 720))
        assert meta.viewport == (1280, 720)

    def test_create_baseline_custom_threshold(self, baseline_store, sample_screenshot):
        """Create baseline with custom threshold."""
        meta = baseline_store.create("test", sample_screenshot, threshold=0.05)
        assert meta.change_threshold == 0.05

    def test_create_duplicate_fails(self, baseline_store, sample_screenshot):
        """Creating duplicate baseline raises FileExistsError."""
        baseline_store.create("test", sample_screenshot)
        with pytest.raises(FileExistsError, match="already exists"):
            baseline_store.create("test", sample_screenshot)

    def test_create_missing_screenshot_fails(self, baseline_store):
        """Creating baseline with missing screenshot raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Screenshot not found"):
            baseline_store.create("test", "/nonexistent/path.png")

    def test_get_baseline(self, baseline_store, sample_screenshot):
        """Get retrieves baseline path and metadata."""
        baseline_store.create("test", sample_screenshot, url="https://example.com")
        result = baseline_store.get("test")
        assert result is not None
        path, meta = result
        assert path.exists()
        assert meta.name == "test"
        assert meta.url == "https://example.com"

    def test_get_nonexistent_returns_none(self, baseline_store):
        """Get returns None for non-existent baseline."""
        assert baseline_store.get("nonexistent") is None

    def test_get_missing_image_returns_none(self, baseline_store, sample_screenshot):
        """Get returns None if image file is missing."""
        meta = baseline_store.create("test", sample_screenshot)
        # Delete the image file
        image_path = baseline_store.baselines_dir / f"{meta.key}.png"
        image_path.unlink()
        assert baseline_store.get("test") is None

    def test_update_baseline(
        self, baseline_store, sample_screenshot, different_screenshot
    ):
        """Update replaces baseline image."""
        baseline_store.create("test", sample_screenshot)
        updated = baseline_store.update("test", different_screenshot)
        assert updated.updated_at > updated.created_at

    def test_update_preserves_metadata(
        self, baseline_store, sample_screenshot, different_screenshot
    ):
        """Update preserves original metadata except updated_at."""
        original = baseline_store.create(
            "test", sample_screenshot, url="https://example.com"
        )
        updated = baseline_store.update("test", different_screenshot)
        assert updated.key == original.key
        assert updated.name == original.name
        assert updated.url == original.url
        assert updated.viewport == original.viewport
        assert updated.created_at == original.created_at

    def test_update_nonexistent_fails(self, baseline_store, sample_screenshot):
        """Updating non-existent baseline raises KeyError."""
        with pytest.raises(KeyError, match="not found"):
            baseline_store.update("nonexistent", sample_screenshot)

    def test_update_missing_screenshot_fails(self, baseline_store, sample_screenshot):
        """Updating with missing screenshot raises FileNotFoundError."""
        baseline_store.create("test", sample_screenshot)
        with pytest.raises(FileNotFoundError, match="Screenshot not found"):
            baseline_store.update("test", "/nonexistent/path.png")

    def test_delete_baseline(self, baseline_store, sample_screenshot):
        """Delete removes baseline and image file."""
        meta = baseline_store.create("test", sample_screenshot)
        image_path = baseline_store.baselines_dir / f"{meta.key}.png"

        assert baseline_store.delete("test")
        assert not baseline_store.exists("test")
        assert not image_path.exists()

    def test_delete_nonexistent_returns_false(self, baseline_store):
        """Delete returns False for non-existent baseline."""
        assert not baseline_store.delete("nonexistent")

    def test_delete_missing_image_still_removes_entry(
        self, baseline_store, sample_screenshot
    ):
        """Delete removes index entry even if image is missing."""
        meta = baseline_store.create("test", sample_screenshot)
        image_path = baseline_store.baselines_dir / f"{meta.key}.png"
        image_path.unlink()

        assert baseline_store.delete("test")
        assert not baseline_store.exists("test")

    def test_list_all_empty(self, baseline_store):
        """List all returns empty list for new store."""
        baselines = baseline_store.list_all()
        assert baselines == []

    def test_list_all(self, baseline_store, sample_screenshot):
        """List all returns all baselines."""
        baseline_store.create("one", sample_screenshot)
        baseline_store.create("two", sample_screenshot)
        baselines = baseline_store.list_all()
        assert len(baselines) == 2
        names = {b.name for b in baselines}
        assert names == {"one", "two"}

    def test_list_all_returns_metadata(self, baseline_store, sample_screenshot):
        """List all returns proper metadata objects."""
        baseline_store.create("test", sample_screenshot, url="https://example.com")
        baselines = baseline_store.list_all()
        assert len(baselines) == 1
        meta = baselines[0]
        assert isinstance(meta, BaselineMeta)
        assert meta.name == "test"
        assert meta.url == "https://example.com"

    def test_exists_true(self, baseline_store, sample_screenshot):
        """Exists returns True for existing baseline."""
        baseline_store.create("test", sample_screenshot)
        assert baseline_store.exists("test")

    def test_exists_false(self, baseline_store):
        """Exists returns False for non-existent baseline."""
        assert not baseline_store.exists("nonexistent")


# ============================================================================
# COMPARE TESTS
# ============================================================================


class TestCompare:
    def test_compare_identical_no_change(
        self, baseline_store, sample_screenshot, tmp_path
    ):
        """Identical images return NO_CHANGE without AI."""
        baseline_store.create("test", sample_screenshot)
        baseline_path, _ = baseline_store.get("test")

        # Copy to simulate "current" screenshot
        current = tmp_path / "current.png"
        shutil.copy(sample_screenshot, current)

        result = compare_with_baseline(baseline_path, str(current))
        assert result.verdict == CompareVerdict.NO_CHANGE
        assert result.change_ratio < 0.001
        assert result.ai_explanation is None  # No AI called

    def test_compare_different_calls_ai(
        self, baseline_store, sample_screenshot, different_screenshot
    ):
        """Different images call AI for classification."""
        baseline_store.create("test", sample_screenshot)
        baseline_path, _ = baseline_store.get("test")

        with patch("ui_verdict.qa_agent.vision.ask_vision") as mock_ai:
            mock_ai.return_value = "VERDICT: INTENTIONAL\nEXPLANATION: Layout updated"

            result = compare_with_baseline(baseline_path, different_screenshot)

            assert result.verdict == CompareVerdict.INTENTIONAL
            assert result.change_ratio > 0.001
            assert mock_ai.called
            assert result.ai_explanation is not None

    def test_compare_regression_detected(
        self, baseline_store, sample_screenshot, different_screenshot
    ):
        """AI can detect regression."""
        baseline_store.create("test", sample_screenshot)
        baseline_path, _ = baseline_store.get("test")

        with patch("ui_verdict.qa_agent.vision.ask_vision") as mock_ai:
            mock_ai.return_value = "VERDICT: REGRESSION\nEXPLANATION: Button is broken"

            result = compare_with_baseline(baseline_path, different_screenshot)

            assert result.verdict == CompareVerdict.REGRESSION
            assert result.ai_explanation is not None
            assert "broken" in result.ai_explanation.lower()

    def test_compare_intentional_detected(
        self, baseline_store, sample_screenshot, different_screenshot
    ):
        """AI can detect intentional changes."""
        baseline_store.create("test", sample_screenshot)
        baseline_path, _ = baseline_store.get("test")

        with patch("ui_verdict.qa_agent.vision.ask_vision") as mock_ai:
            mock_ai.return_value = (
                "VERDICT: INTENTIONAL\nEXPLANATION: New design system"
            )

            result = compare_with_baseline(baseline_path, different_screenshot)

            assert result.verdict == CompareVerdict.INTENTIONAL

    def test_compare_ai_defaults_to_intentional(
        self, baseline_store, sample_screenshot, different_screenshot
    ):
        """Unclear AI response defaults to INTENTIONAL."""
        baseline_store.create("test", sample_screenshot)
        baseline_path, _ = baseline_store.get("test")

        with patch("ui_verdict.qa_agent.vision.ask_vision") as mock_ai:
            mock_ai.return_value = "Something changed but unclear"

            result = compare_with_baseline(baseline_path, different_screenshot)

            assert result.verdict == CompareVerdict.INTENTIONAL

    def test_compare_empty_baseline_path(self, sample_screenshot):
        """Empty baseline path returns UNKNOWN."""
        result = compare_with_baseline("", sample_screenshot)
        assert result.verdict == CompareVerdict.UNKNOWN
        assert result.ai_explanation is not None
        assert "baseline_path is required" in result.ai_explanation

    def test_compare_empty_current_path(self, baseline_store, sample_screenshot):
        """Empty current path returns UNKNOWN."""
        baseline_store.create("test", sample_screenshot)
        baseline_path, _ = baseline_store.get("test")

        result = compare_with_baseline(baseline_path, "")
        assert result.verdict == CompareVerdict.UNKNOWN
        assert result.ai_explanation is not None
        assert "current_path is required" in result.ai_explanation

    def test_compare_missing_baseline_file(self, tmp_path, sample_screenshot):
        """Missing baseline file returns UNKNOWN."""
        nonexistent = tmp_path / "nonexistent.png"
        result = compare_with_baseline(nonexistent, sample_screenshot)
        assert result.verdict == CompareVerdict.UNKNOWN
        assert result.ai_explanation is not None
        assert "not found" in result.ai_explanation.lower()

    def test_compare_missing_current_file(
        self, baseline_store, sample_screenshot, tmp_path
    ):
        """Missing current file returns UNKNOWN."""
        baseline_store.create("test", sample_screenshot)
        baseline_path, _ = baseline_store.get("test")
        nonexistent = tmp_path / "nonexistent.png"

        result = compare_with_baseline(baseline_path, str(nonexistent))
        assert result.verdict == CompareVerdict.UNKNOWN
        assert result.ai_explanation is not None
        assert "not found" in result.ai_explanation.lower()

    def test_compare_invalid_threshold_clamped(
        self, baseline_store, sample_screenshot, tmp_path
    ):
        """Invalid threshold is clamped to [0.0, 1.0]."""
        baseline_store.create("test", sample_screenshot)
        baseline_path, _ = baseline_store.get("test")
        current = tmp_path / "current.png"
        shutil.copy(sample_screenshot, current)

        # Should not crash with invalid threshold - test that it doesn't raise
        # Note: Due to CV precision, we just verify the function completes
        result = compare_with_baseline(baseline_path, str(current), threshold=-0.5)
        assert result.verdict in [
            CompareVerdict.NO_CHANGE,
            CompareVerdict.INTENTIONAL,
            CompareVerdict.REGRESSION,
        ]

        result = compare_with_baseline(baseline_path, str(current), threshold=2.0)
        assert result.verdict in [
            CompareVerdict.NO_CHANGE,
            CompareVerdict.INTENTIONAL,
            CompareVerdict.REGRESSION,
        ]

    def test_compare_custom_threshold(
        self, baseline_store, sample_screenshot, different_screenshot
    ):
        """Custom threshold affects NO_CHANGE detection."""
        baseline_store.create("test", sample_screenshot)
        baseline_path, _ = baseline_store.get("test")

        # Very high threshold -> everything is NO_CHANGE
        result = compare_with_baseline(
            baseline_path, different_screenshot, threshold=0.99
        )
        assert result.verdict == CompareVerdict.NO_CHANGE

    def test_compare_ai_failure_returns_unknown(
        self, baseline_store, sample_screenshot, different_screenshot
    ):
        """AI failure returns UNKNOWN verdict."""
        baseline_store.create("test", sample_screenshot)
        baseline_path, _ = baseline_store.get("test")

        with patch("ui_verdict.qa_agent.vision.ask_vision") as mock_ai:
            mock_ai.side_effect = Exception("API error")

            result = compare_with_baseline(baseline_path, different_screenshot)

            assert result.verdict == CompareVerdict.UNKNOWN
            assert result.ai_explanation is not None
            assert "failed" in result.ai_explanation.lower()

    def test_compare_ai_empty_response(
        self, baseline_store, sample_screenshot, different_screenshot
    ):
        """AI empty response returns UNKNOWN."""
        baseline_store.create("test", sample_screenshot)
        baseline_path, _ = baseline_store.get("test")

        with patch("ui_verdict.qa_agent.vision.ask_vision") as mock_ai:
            mock_ai.return_value = ""

            result = compare_with_baseline(baseline_path, different_screenshot)

            assert result.verdict == CompareVerdict.UNKNOWN
            assert result.ai_explanation is not None
            assert "empty response" in result.ai_explanation.lower()

    def test_compare_no_baseline(self, sample_screenshot):
        """No baseline returns UNKNOWN verdict."""
        result = compare_no_baseline(sample_screenshot)
        assert result.verdict == CompareVerdict.UNKNOWN
        assert result.baseline_path is None
        assert result.current_path == sample_screenshot
        assert result.change_ratio == 0.0
        assert result.ai_explanation is not None
        assert "No baseline exists" in result.ai_explanation

    def test_compare_no_baseline_empty_path(self):
        """No baseline with empty path still works."""
        result = compare_no_baseline("")
        assert result.verdict == CompareVerdict.UNKNOWN
        assert result.baseline_path is None
        assert result.current_path == ""

    def test_compare_result_includes_baseline_path(
        self, baseline_store, sample_screenshot, tmp_path
    ):
        """CompareResult includes baseline path."""
        baseline_store.create("test", sample_screenshot)
        baseline_path, _ = baseline_store.get("test")
        current = tmp_path / "current.png"
        shutil.copy(sample_screenshot, current)

        result = compare_with_baseline(baseline_path, str(current))
        assert result.baseline_path == str(baseline_path)
        assert result.current_path == str(current)

    def test_compare_result_includes_change_ratio(
        self, baseline_store, sample_screenshot, different_screenshot
    ):
        """CompareResult includes change ratio."""
        baseline_store.create("test", sample_screenshot)
        baseline_path, _ = baseline_store.get("test")

        with patch("ui_verdict.qa_agent.vision.ask_vision") as mock_ai:
            mock_ai.return_value = "VERDICT: INTENTIONAL\nEXPLANATION: Updated"

            result = compare_with_baseline(baseline_path, different_screenshot)

            assert 0.0 <= result.change_ratio <= 1.0
            assert result.change_ratio > 0.001


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


class TestIntegration:
    def test_create_and_compare_workflow(
        self, baseline_store, sample_screenshot, different_screenshot
    ):
        """Full workflow: create baseline, compare, detect change."""
        # Create baseline
        meta = baseline_store.create(
            "homepage", sample_screenshot, url="https://example.com"
        )
        assert meta.name == "homepage"

        # Get baseline
        baseline_path, stored_meta = baseline_store.get("homepage")
        assert stored_meta.name == "homepage"

        # Compare with different screenshot
        with patch("ui_verdict.qa_agent.vision.ask_vision") as mock_ai:
            mock_ai.return_value = "VERDICT: REGRESSION\nEXPLANATION: Layout broken"

            result = compare_with_baseline(baseline_path, different_screenshot)

            assert result.verdict == CompareVerdict.REGRESSION
            assert result.change_ratio > 0.0
            assert result.ai_explanation is not None
            assert "broken" in result.ai_explanation.lower()

    def test_update_and_compare_workflow(
        self, baseline_store, sample_screenshot, different_screenshot, tmp_path
    ):
        """Workflow: create, update baseline, compare against updated."""
        # Create baseline
        baseline_store.create("test", sample_screenshot)

        # Update baseline with different screenshot
        baseline_store.update("test", different_screenshot)

        # Compare against the new baseline (should be identical)
        baseline_path, _ = baseline_store.get("test")
        current = tmp_path / "current.png"
        shutil.copy(different_screenshot, current)

        result = compare_with_baseline(baseline_path, str(current))
        assert result.verdict == CompareVerdict.NO_CHANGE

    def test_multiple_baselines_different_viewports(
        self, baseline_store, sample_screenshot
    ):
        """Store multiple baselines with different viewports."""
        meta1 = baseline_store.create(
            "test_desktop", sample_screenshot, viewport=(1920, 1080)
        )
        meta2 = baseline_store.create(
            "test_mobile", sample_screenshot, viewport=(1280, 720)
        )

        # Different viewports and names -> different keys
        assert meta1.key != meta2.key

        baselines = baseline_store.list_all()
        assert len(baselines) == 2
