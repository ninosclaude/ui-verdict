"""Tests for heatmap visualization module."""
import pytest
import numpy as np
import tempfile
import os

from src.ui_verdict.diff.heatmap import (
    generate_heatmap,
    generate_diff_mask,
    generate_side_by_side,
    annotate_changes,
)


@pytest.fixture
def identical_images():
    """Create two identical test images."""
    img = np.zeros((100, 100), dtype=np.uint8)
    img[25:75, 25:75] = 128  # Gray square
    return img, img.copy()


@pytest.fixture
def different_images():
    """Create two different test images."""
    before = np.zeros((100, 100), dtype=np.uint8)
    before[25:75, 25:75] = 128
    
    after = np.zeros((100, 100), dtype=np.uint8)
    after[25:75, 25:75] = 128
    after[40:60, 40:60] = 255  # White square (change)
    
    return before, after


@pytest.fixture
def large_change_images():
    """Create images with large change."""
    before = np.zeros((100, 100), dtype=np.uint8)
    after = np.ones((100, 100), dtype=np.uint8) * 255  # All white
    return before, after


class TestGenerateHeatmap:
    """Tests for generate_heatmap function."""
    
    def test_identical_images(self, identical_images):
        """Test heatmap with identical images."""
        before, after = identical_images
        heatmap, _ = generate_heatmap(before, after)
        assert heatmap.shape[:2] == before.shape
        assert len(heatmap.shape) == 3  # BGR output
    
    def test_different_images(self, different_images):
        """Test heatmap with different images."""
        before, after = different_images
        heatmap, _ = generate_heatmap(before, after)
        assert heatmap.shape[:2] == before.shape
    
    def test_saves_to_file(self, different_images):
        """Test heatmap saves to file when path provided."""
        before, after = different_images
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        
        try:
            _, saved_path = generate_heatmap(before, after, path)
            assert saved_path == path
            assert os.path.exists(path)
            assert os.path.getsize(path) > 0
        finally:
            if os.path.exists(path):
                os.remove(path)
    
    def test_different_sizes(self):
        """Test heatmap resizes images if different sizes."""
        before = np.zeros((100, 100), dtype=np.uint8)
        after = np.zeros((120, 120), dtype=np.uint8)
        after[50:70, 50:70] = 255
        
        heatmap, _ = generate_heatmap(before, after)
        assert heatmap.shape[:2] == before.shape


class TestGenerateDiffMask:
    """Tests for generate_diff_mask function."""
    
    def test_identical_images(self, identical_images):
        """Test mask with identical images."""
        before, after = identical_images
        mask, stats = generate_diff_mask(before, after)
        
        assert stats["changed_pixels"] == 0
        assert stats["change_ratio"] == 0.0
        assert stats["num_regions"] == 0
    
    def test_different_images(self, different_images):
        """Test mask with different images."""
        before, after = different_images
        mask, stats = generate_diff_mask(before, after)
        
        assert stats["changed_pixels"] > 0
        assert stats["change_ratio"] > 0.0
        assert stats["num_regions"] > 0
    
    def test_large_change(self, large_change_images):
        """Test mask with large change."""
        before, after = large_change_images
        mask, stats = generate_diff_mask(before, after)
        
        # Most pixels should be changed
        assert stats["change_ratio"] > 0.9
    
    def test_regions_sorted_by_size(self, different_images):
        """Test regions are sorted by area (largest first)."""
        before, after = different_images
        _, stats = generate_diff_mask(before, after)
        
        if len(stats["regions"]) > 1:
            areas = [r["area"] for r in stats["regions"]]
            assert areas == sorted(areas, reverse=True)
    
    def test_region_has_required_fields(self, different_images):
        """Test regions have all required fields."""
        before, after = different_images
        _, stats = generate_diff_mask(before, after)
        
        if stats["regions"]:
            region = stats["regions"][0]
            assert "x" in region
            assert "y" in region
            assert "width" in region
            assert "height" in region
            assert "area" in region


class TestGenerateSideBySide:
    """Tests for generate_side_by_side function."""
    
    def test_creates_combined_image(self, different_images):
        """Test side-by-side creates combined image."""
        before, after = different_images
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        
        try:
            result = generate_side_by_side(before, after, path)
            assert os.path.exists(result)
            
            # Read back and verify dimensions
            import cv2
            combined = cv2.imread(result)
            # Should be: before_width + separator + after_width
            expected_width = before.shape[1] * 2 + 3  # 3px separator
            assert combined.shape[1] == expected_width
        finally:
            if os.path.exists(path):
                os.remove(path)


class TestAnnotateChanges:
    """Tests for annotate_changes function."""
    
    def test_draws_boxes(self, different_images):
        """Test annotation draws boxes on image."""
        before, after = different_images
        _, stats = generate_diff_mask(before, after)
        
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        
        try:
            result = annotate_changes(after, stats["regions"], path)
            assert os.path.exists(result)
            assert os.path.getsize(result) > 0
        finally:
            if os.path.exists(path):
                os.remove(path)
    
    def test_handles_empty_regions(self, identical_images):
        """Test annotation handles empty regions list."""
        before, after = identical_images
        
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        
        try:
            result = annotate_changes(after, [], path)
            assert os.path.exists(result)
        finally:
            if os.path.exists(path):
                os.remove(path)
