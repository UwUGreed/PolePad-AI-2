"""
scripts/test_ocr.py

Tests the OCR pipeline end to end.
Hits the running ocr-service on localhost:8002.

Usage:
    python scripts/test_ocr.py path/to/image.jpg
    python scripts/test_ocr.py path/to/image.jpg --x1 100 --y1 50 --x2 400 --y2 150

If no bounding box is provided, sends the full image to OCR.
If a bounding box is provided, crops first then sends to OCR
(simulating exactly what the API does after YOLO detection).

Requirements:
    pip install httpx pillow numpy
    ocr-service must be running on localhost:8002
"""

import sys
import base64
import argparse
import json
from io import BytesIO
from pathlib import Path

try:
    import httpx
    from PIL import Image, ImageEnhance, ImageFilter
    import numpy as np
except ImportError:
    print("Missing deps. Run: pip install httpx pillow numpy")
    sys.exit(1)

OCR_URL = "http://localhost:8002"
UNCERTAINTY_THRESHOLD = 0.75


# ─── Preprocessing (mirrors ocr-service exactly) ──────────────────────────────

def preprocess_tag_image(img: Image.Image) -> tuple[Image.Image, list[str]]:
    applied = []
    img = img.convert("RGB")
    w, h = img.size

    if w < 200 or h < 50:
        scale = max(200 / w, 50 / h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        applied.append("upscaled")

    gray = img.convert("L")
    enhancer = ImageEnhance.Contrast(gray)
    gray = enhancer.enhance(2.0)
    applied.append("contrast_enhanced")

    gray = gray.filter(ImageFilter.SHARPEN)
    applied.append("sharpened")

    arr = np.array(gray)
    if arr.mean() > 200:
        gray = Image.fromarray(255 - arr)
        applied.append("glare_inversion")

    return gray.convert("RGB"), applied


# ─── Helpers ──────────────────────────────────────────────────────────────────

def image_to_b64(img: Image.Image) -> str:
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def crop_image(img: Image.Image, x1: int, y1: int, x2: int, y2: int) -> Image.Image:
    return img.crop((x1, y1, x2, y2))


def print_separator(char="─", width=60):
    print(char * width)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Test OCR pipeline")
    parser.add_argument("image", help="Path to image file")
    parser.add_argument("--x1", type=int, default=None)
    parser.add_argument("--y1", type=int, default=None)
    parser.add_argument("--x2", type=int, default=None)
    parser.add_argument("--y2", type=int, default=None)
    parser.add_argument("--url", default=OCR_URL, help="OCR service URL")
    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.exists():
        print(f"ERROR: Image not found: {image_path}")
        sys.exit(1)

    print_separator("═")
    print("  POLEPAD OCR PIPELINE TEST")
    print_separator("═")
    print(f"  Image:   {image_path}")
    print(f"  Service: {args.url}")

    # Check service is up
    try:
        health = httpx.get(f"{args.url}/health", timeout=5).json()
        print(f"  Service: ✅ {health.get('status')} "
              f"(model: {health.get('model_version', 'unknown')})")
    except Exception as e:
        print(f"  Service: ❌ Cannot reach {args.url}")
        print(f"  Error:   {e}")
        print("\n  Is ocr-service running? Try: docker compose up ocr-service")
        sys.exit(1)

    print_separator()

    # Load image
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    print(f"\n📷 Original image: {w}x{h}px")

    # Crop if bounding box provided
    if all(v is not None for v in [args.x1, args.y1, args.x2, args.y2]):
        print(f"\n✂️  Cropping to bbox: "
              f"({args.x1}, {args.y1}) → ({args.x2}, {args.y2})")
        img = crop_image(img, args.x1, args.y1, args.x2, args.y2)
        cw, ch = img.size
        print(f"   Crop size: {cw}x{ch}px")
    else:
        print("\nℹ️  No bounding box provided — sending full image to OCR")
        print("   Tip: use --x1 --y1 --x2 --y2 to test with a crop")

    # Show preprocessing
    print("\n🔧 Running preprocessing pipeline...")
    processed, steps = preprocess_tag_image(img)
    print(f"   Steps applied: {', '.join(steps)}")

    # Save crops for inspection
    img.save("/tmp/polepad_ocr_raw_crop.jpg")
    processed.save("/tmp/polepad_ocr_processed_crop.jpg")
    print(f"\n   Raw crop saved:       /tmp/polepad_ocr_raw_crop.jpg")
    print(f"   Processed crop saved: /tmp/polepad_ocr_processed_crop.jpg")

    # Send to OCR service
    print("\n📡 Sending to OCR service...")
    image_b64 = image_to_b64(processed)

    payload = {
        "image_b64": image_b64,
        "image_id": "test-ocr-script",
        "original_bounding_box": {
            "x1": args.x1 or 0,
            "y1": args.y1 or 0,
            "x2": args.x2 or w,
            "y2": args.y2 or h,
            "width": 0,
            "height": 0,
        }
    }

    try:
        resp = httpx.post(
            f"{args.url}/extract",
            json=payload,
            timeout=30
        )
        resp.raise_for_status()
        result = resp.json()
    except httpx.HTTPStatusError as e:
        print(f"\n❌ OCR service error: {e.response.status_code}")
        print(e.response.text)
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Request failed: {e}")
        sys.exit(1)

    # Print results
    print_separator()
    print("\n📋 OCR RESULTS")
    print_separator()

    raw = result.get("raw_string", "")
    normalized = result.get("normalized_string", "")
    mean_conf = result.get("mean_confidence", 0)
    uncertain_positions = result.get("uncertain_positions", [])
    preprocessing = result.get("preprocessing_applied", [])
    processing_ms = result.get("processing_ms", 0)

    print(f"\n  Raw string:        {raw!r}")
    print(f"  Normalized string: {normalized!r}")
    print(f"  Mean confidence:   {mean_conf:.1%}")
    print(f"  Processing time:   {processing_ms}ms")
    print(f"  Preprocessing:     {', '.join(preprocessing) or 'none'}")

    # Character breakdown
    char_confs = result.get("character_confidences", [])
    if char_confs:
        print(f"\n  Character breakdown:")
        print(f"  {'Pos':<5} {'Char':<6} {'Confidence':<12} {'Status'}")
        print(f"  {'─'*4} {'─'*5} {'─'*11} {'─'*20}")

        for c in char_confs:
            char = c.get("char", "?")
            conf = c.get("confidence", 0)
            uncertain = c.get("uncertain", False)
            pos = c.get("position", 0)

            status = "🟡 UNCERTAIN (amber in UI)" if uncertain else "✅ confident"
            print(f"  {pos:<5} {char!r:<6} {conf:<12.1%} {status}")

    # Summary
    print_separator()
    if uncertain_positions:
        print(f"\n⚠️  {len(uncertain_positions)} uncertain character(s) "
              f"at position(s): {uncertain_positions}")
        print(f"   These will be highlighted amber in the UI")
    else:
        print(f"\n✅ All characters confident — no amber highlighting")

    if normalized:
        print(f"\n🏷️  Final tag reading: {normalized}")
    else:
        print(f"\n❌ No tag text extracted")

    print_separator("═")


if __name__ == "__main__":
    main()
