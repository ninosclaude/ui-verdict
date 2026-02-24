"""
Diff heatmap visualization.

Generates visual heatmaps showing where changes occurred between two screenshots.
This helps agents understand WHAT changed and WHERE, not just IF something changed.
"""
from __future__ import annotations

import cv2
import numpy as np
from pathlib import Path


def generate_heatmap(
    before: np.ndarray,
    after: np.ndarray,
    output_path: str | None = None,
    colormap: int = cv2.COLORMAP_JET,
    threshold: int = 10,
    overlay_alpha: float = 0.5,
) -> tuple[np.ndarray, str | None]:
    """Generate a heatmap visualization of differences between two images.
    
    Args:
        before: Grayscale image before action
        after: Grayscale image after action
        output_path: Where to save the heatmap image. If None, doesn't save.
        colormap: OpenCV colormap (default: JET for red=high, blue=low)
        threshold: Minimum pixel difference to consider (reduces noise)
        overlay_alpha: How much to blend heatmap with original (0-1)
        
    Returns:
        Tuple of (heatmap_array, saved_path or None)
    """
    # Ensure same size
    if before.shape != after.shape:
        after = cv2.resize(after, (before.shape[1], before.shape[0]))
    
    # Compute absolute difference
    diff = cv2.absdiff(before, after)
    
    # Apply threshold to reduce noise
    _, diff_thresh = cv2.threshold(diff, threshold, 255, cv2.THRESH_TOZERO)
    
    # Blur for smoother heatmap
    diff_blurred = cv2.GaussianBlur(diff_thresh, (21, 21), 0)
    
    # Normalize to 0-255
    diff_norm = cv2.normalize(diff_blurred, None, 0, 255, cv2.NORM_MINMAX)
    
    # Apply colormap
    heatmap = cv2.applyColorMap(diff_norm.astype(np.uint8), colormap)
    
    # Convert grayscale original to BGR for overlay
    if len(before.shape) == 2:
        original_bgr = cv2.cvtColor(before, cv2.COLOR_GRAY2BGR)
    else:
        original_bgr = before
    
    # Create overlay
    overlay = cv2.addWeighted(original_bgr, 1 - overlay_alpha, heatmap, overlay_alpha, 0)
    
    saved_path = None
    if output_path:
        cv2.imwrite(output_path, overlay)
        saved_path = output_path
    
    return overlay, saved_path


def generate_diff_mask(
    before: np.ndarray,
    after: np.ndarray,
    output_path: str | None = None,
    threshold: int = 10,
) -> tuple[np.ndarray, dict]:
    """Generate a binary mask showing changed regions.
    
    Args:
        before: Grayscale image before action
        after: Grayscale image after action
        output_path: Where to save the mask image
        threshold: Minimum pixel difference to consider
        
    Returns:
        Tuple of (mask_array, stats_dict)
    """
    # Ensure same size
    if before.shape != after.shape:
        after = cv2.resize(after, (before.shape[1], before.shape[0]))
    
    # Compute difference
    diff = cv2.absdiff(before, after)
    
    # Binary threshold
    _, mask = cv2.threshold(diff, threshold, 255, cv2.THRESH_BINARY)
    
    # Find contours (changed regions)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # Calculate stats
    total_pixels = before.shape[0] * before.shape[1]
    changed_pixels = np.count_nonzero(mask)
    
    # Find bounding boxes of changed regions
    regions = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = cv2.contourArea(contour)
        if area > 50:  # Filter tiny noise
            regions.append({
                "x": int(x),
                "y": int(y),
                "width": int(w),
                "height": int(h),
                "area": int(area),
            })
    
    # Sort by area (largest first)
    regions.sort(key=lambda r: r["area"], reverse=True)
    
    stats = {
        "changed_pixels": int(changed_pixels),
        "total_pixels": int(total_pixels),
        "change_ratio": changed_pixels / total_pixels,
        "num_regions": len(regions),
        "regions": regions[:10],  # Top 10 regions
    }
    
    if output_path:
        cv2.imwrite(output_path, mask)
    
    return mask, stats


def generate_side_by_side(
    before: np.ndarray,
    after: np.ndarray,
    output_path: str,
    add_labels: bool = True,
) -> str:
    """Generate a side-by-side comparison image.
    
    Args:
        before: Image before action
        after: Image after action
        output_path: Where to save the comparison
        add_labels: Whether to add "Before" / "After" labels
        
    Returns:
        Path to saved image
    """
    # Ensure same size
    if before.shape != after.shape:
        after = cv2.resize(after, (before.shape[1], before.shape[0]))
    
    # Convert to BGR if grayscale
    if len(before.shape) == 2:
        before = cv2.cvtColor(before, cv2.COLOR_GRAY2BGR)
        after = cv2.cvtColor(after, cv2.COLOR_GRAY2BGR)
    
    # Add separator line
    h, w = before.shape[:2]
    separator = np.ones((h, 3, 3), dtype=np.uint8) * 128
    
    # Concatenate
    combined = np.hstack([before, separator, after])
    
    # Add labels
    if add_labels:
        font = cv2.FONT_HERSHEY_SIMPLEX
        cv2.putText(combined, "BEFORE", (10, 30), font, 1, (0, 255, 0), 2)
        cv2.putText(combined, "AFTER", (w + 13, 30), font, 1, (0, 255, 0), 2)
    
    cv2.imwrite(output_path, combined)
    return output_path


def annotate_changes(
    image: np.ndarray,
    regions: list[dict],
    output_path: str,
    color: tuple = (0, 0, 255),  # Red
    thickness: int = 2,
) -> str:
    """Draw bounding boxes around changed regions.
    
    Args:
        image: Base image (before or after)
        regions: List of region dicts from generate_diff_mask
        output_path: Where to save annotated image
        color: BGR color for boxes
        thickness: Line thickness
        
    Returns:
        Path to saved image
    """
    # Convert to BGR if grayscale
    if len(image.shape) == 2:
        annotated = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    else:
        annotated = image.copy()
    
    for i, region in enumerate(regions):
        x, y, w, h = region["x"], region["y"], region["width"], region["height"]
        cv2.rectangle(annotated, (x, y), (x + w, y + h), color, thickness)
        
        # Add label
        label = f"#{i+1}"
        cv2.putText(annotated, label, (x, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    
    cv2.imwrite(output_path, annotated)
    return output_path
