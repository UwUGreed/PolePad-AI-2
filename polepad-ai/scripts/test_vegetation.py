"""
scripts/test_vegetation.py

Tests the vegetation green pixel detection pipeline.
Runs completely standalone — no services needed.

Usage:
    python scripts/test_vegetation.py path/to/image.jpg
    python scripts/test_vegetation.py path/to/image.jpg --threshold 0.25

Requirements:
    pip install pillow numpy opencv-python
"""

import sys
import argparse
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageDraw
    import cv2
except ImportError:
    print("Missing deps. Run: pip install pillow numpy opencv-python")
    sys.exit(1)


# ─── Detection (mirrors cv-service exactly) ───────────────────────────────────

def check_vegetation(image_array: np.ndarray, threshold: float = 0.25) -> tuple[bool, float, np.ndarray]:
    """
    Returns (flagged, green_ratio, roi_array)
    ROI array returned so we can visualize exactly what was analyzed.
    """
    h, w = image_array.shape[:2]

    # Same ROI as cv-service — middle vertical strip
    roi_top    = int(h * 0.10)
    roi_bottom = int(h * 0.85)
    roi_left   = int(w * 0.10)
    roi_right  = int(w * 0.90)

    roi = image_array[roi_top:roi_bottom, roi_left:roi_right]

    r = roi[:, :, 0].astype(float)
    g = roi[:, :, 1].astype(float)
    b = roi[:, :, 2].astype(float)

    green_mask = (
        (g > 60) &
        (g > r * 1.15) &
        (g > b * 1.10)
    )

    total_pixels = roi.shape[0] * roi.shape[1]
    green_ratio = float(green_mask.sum()) / total_pixels
    flagged = green_ratio > threshold

    return flagged, round(green_ratio, 4), roi, green_mask, (roi_top, roi_bottom, roi_left, roi_right)


def print_separator(char="─", width=60):
    print(char * width)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Test vegetation detection pipeline")
    parser.add_argument("image", help="Path to image file")
    parser.add_argument("--threshold", type=float, default=0.25,
                        help="Green ratio threshold for flagging (default: 0.25)")
    parser.add_argument("--no-visual", action="store_true",
                        help="Skip saving visual output")
    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.exists():
        print(f"ERROR: Image not found: {image_path}")
        sys.exit(1)

    print_separator("═")
    print("  POLEPAD VEGETATION DETECTION TEST")
    print_separator("═")
    print(f"  Image:     {image_path}")
    print(f"  Threshold: {args.threshold:.0%} green coverage = flagged")

    # Load image
    img = Image.open(image_path).convert("RGB")
    img_array = np.array(img)
    h, w = img_array.shape[:2]
    print(f"  Size:      {w}x{h}px")
    print_separator()

    # Run detection
    print("\n🔍 Running vegetation detection...")
    flagged, green_ratio, roi, green_mask, roi_coords = check_vegetation(
        img_array, args.threshold
    )
    roi_top, roi_bottom, roi_left, roi_right = roi_coords

    # Results
    print_separator()
    print("\n📋 RESULTS")
    print_separator()
    print(f"\n  Green pixel ratio: {green_ratio:.1%}")
    print(f"  Threshold:         {args.threshold:.0%}")
    print(f"  ROI analyzed:      top={roi_top}px bottom={roi_bottom}px "
          f"left={roi_left}px right={roi_right}px")

    if flagged:
        print(f"\n  🌿 VEGETATION FLAGGED = YES")
        print(f"     {green_ratio:.1%} green coverage exceeds {args.threshold:.0%} threshold")
        print(f"     This pole would be flagged in the database")
    else:
        print(f"\n  ✅ VEGETATION FLAGGED = NO")
        print(f"     {green_ratio:.1%} green coverage is under {args.threshold:.0%} threshold")

    # Threshold sensitivity — show what different thresholds would decide
    print(f"\n  Threshold sensitivity:")
    for t in [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]:
        would_flag = green_ratio > t
        marker = " ← current" if t == args.threshold else ""
        verdict = "FLAGGED" if would_flag else "clear  "
        print(f"    {t:.0%}  →  {verdict}{marker}")

    # Save visual outputs
    if not args.no_visual:
        print_separator()
        print("\n💾 Saving visual outputs...")

        # 1. Full image with ROI box drawn on it
        visual = img.copy()
        draw = ImageDraw.Draw(visual)

        # Draw ROI rectangle
        draw.rectangle(
            [roi_left, roi_top, roi_right, roi_bottom],
            outline=(255, 165, 0),   # orange box
            width=3
        )

        # Draw label
        label = f"ROI analyzed ({green_ratio:.1%} green)"
        draw.rectangle([roi_left, roi_top - 25, roi_left + 280, roi_top], fill=(255, 165, 0))
        draw.text((roi_left + 4, roi_top - 22), label, fill=(0, 0, 0))

        visual.save("/tmp/polepad_veg_roi.jpg")
        print(f"  ROI overlay:    /tmp/polepad_veg_roi.jpg")

        # 2. Green mask visualization — shows exactly which pixels triggered
        roi_rgb = np.array(img)[roi_top:roi_bottom, roi_left:roi_right]
        mask_visual = roi_rgb.copy()

        # Highlight green pixels in bright green, dim non-green pixels
        mask_visual[~green_mask] = (mask_visual[~green_mask] * 0.3).astype(np.uint8)
        mask_visual[green_mask] = [0, 255, 0]  # bright green overlay

        mask_img = Image.fromarray(mask_visual)
        mask_img.save("/tmp/polepad_veg_mask.jpg")
        print(f"  Green mask:     /tmp/polepad_veg_mask.jpg")
        print(f"                  (bright green = pixels that triggered detection)")

        # 3. Side by side comparison
        roi_img = Image.fromarray(roi_rgb)
        roi_resized = roi_img.resize((400, 300))
        mask_resized = mask_img.resize((400, 300))

        comparison = Image.new("RGB", (800, 300))
        comparison.paste(roi_resized, (0, 0))
        comparison.paste(mask_resized, (400, 0))

        comp_draw = ImageDraw.Draw(comparison)
        comp_draw.rectangle([0, 0, 400, 25], fill=(50, 50, 50))
        comp_draw.rectangle([400, 0, 800, 25], fill=(50, 50, 50))
        comp_draw.text((5, 5), "Original ROI", fill=(255, 255, 255))
        comp_draw.text((405, 5), f"Green mask ({green_ratio:.1%})", fill=(255, 255, 255))

        comparison.save("/tmp/polepad_veg_comparison.jpg")
        print(f"  Comparison:     /tmp/polepad_veg_comparison.jpg")

    print_separator("═")
    print(f"\n  VERDICT: vegetation_flagged = {'True  🌿' if flagged else 'False ✅'}")
    print_separator("═")


if __name__ == "__main__":
    main()
