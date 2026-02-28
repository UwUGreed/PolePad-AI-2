"""
scripts/test_cv.py

Tests the CV pipeline using your trained YOLO weights directly.
No services needed — runs the model locally.

Usage:
    python scripts/test_cv.py path/to/image.jpg
    python scripts/test_cv.py path/to/image.jpg --model ml/models/polepad-v1/best.pt
    python scripts/test_cv.py path/to/image.jpg --confidence 0.35

Requirements:
    pip install ultralytics pillow numpy opencv-python
"""

import sys
import argparse
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    import cv2
except ImportError:
    print("Missing deps. Run: pip install ultralytics pillow numpy opencv-python")
    sys.exit(1)

DEFAULT_MODEL = "ml/models/polepad-v1/best.pt"
DEFAULT_CONFIDENCE = 0.45

# Must match your dataset.yaml exactly
CLASS_MAP = {
    0: "asset_tag",
    1: "pole_wood",
    2: "pole_steel",
    3: "pole_concrete",
}

CLASS_COLORS = {
    "asset_tag":    (0, 255, 0),      # green
    "pole_wood":    (139, 69, 19),    # brown
    "pole_steel":   (128, 128, 128),  # gray
    "pole_concrete":(200, 200, 200),  # light gray
}


def print_separator(char="─", width=60):
    print(char * width)


def draw_boxes(img_array: np.ndarray, detections: list) -> np.ndarray:
    """Draw bounding boxes on image for visual output."""
    img = img_array.copy()

    for det in detections:
        x1, y1, x2, y2 = int(det["x1"]), int(det["y1"]), int(det["x2"]), int(det["y2"])
        label = det["class"]
        conf = det["confidence"]
        color = CLASS_COLORS.get(label, (255, 0, 255))

        # Box
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)

        # Label background
        text = f"{label} {conf:.0%}"
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
        cv2.rectangle(img, (x1, y1 - th - 8), (x1 + tw + 4, y1), color, -1)
        cv2.putText(img, text, (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)

    return img


def crop_to_box(img_array: np.ndarray, det: dict, padding: int = 10) -> np.ndarray:
    """Crop image to detection bounding box with optional padding."""
    h, w = img_array.shape[:2]
    x1 = max(0, int(det["x1"]) - padding)
    y1 = max(0, int(det["y1"]) - padding)
    x2 = min(w, int(det["x2"]) + padding)
    y2 = min(h, int(det["y2"]) + padding)
    return img_array[y1:y2, x1:x2]


def main():
    parser = argparse.ArgumentParser(description="Test CV/YOLO pipeline")
    parser.add_argument("image", help="Path to image file")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"Path to model weights (default: {DEFAULT_MODEL})")
    parser.add_argument("--confidence", type=float, default=DEFAULT_CONFIDENCE,
                        help=f"Detection confidence threshold (default: {DEFAULT_CONFIDENCE})")
    parser.add_argument("--no-visual", action="store_true",
                        help="Skip saving visual outputs")
    args = parser.parse_args()

    image_path = Path(args.image)
    model_path = Path(args.model)

    if not image_path.exists():
        print(f"ERROR: Image not found: {image_path}")
        sys.exit(1)

    print_separator("═")
    print("  POLEPAD CV PIPELINE TEST")
    print_separator("═")
    print(f"  Image:      {image_path}")
    print(f"  Model:      {model_path}")
    print(f"  Confidence: {args.confidence}")

    # Load model
    print_separator()
    print("\n🔧 Loading model...")

    if not model_path.exists():
        print(f"\n⚠️  Model not found at {model_path}")
        print(f"   Falling back to YOLOv8n pretrained (demo mode)")
        print(f"   Drop your weights at: {DEFAULT_MODEL}")
        model_path_str = "yolov8n.pt"
        demo_mode = True
    else:
        model_path_str = str(model_path)
        demo_mode = False

    try:
        from ultralytics import YOLO
        model = YOLO(model_path_str)
        if demo_mode:
            print(f"   ✅ YOLOv8n loaded (demo — not your trained weights)")
        else:
            print(f"   ✅ Model loaded: {model_path}")
    except ImportError:
        print("\n❌ ultralytics not installed")
        print("   Run: pip install ultralytics")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Failed to load model: {e}")
        sys.exit(1)

    # Load image
    img = Image.open(image_path).convert("RGB")
    img_array = np.array(img)
    h, w = img_array.shape[:2]
    print(f"\n📷 Image loaded: {w}x{h}px")

    # Run YOLO
    print(f"\n🔍 Running detection (confidence threshold: {args.confidence})...")
    results = model(img_array, conf=args.confidence, verbose=False)

    # Parse detections
    detections = []
    for result in results:
        for box in result.boxes:
            cls_idx = int(box.cls[0])
            conf = float(box.conf[0])
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            class_name = CLASS_MAP.get(cls_idx, f"unknown_class_{cls_idx}")

            detections.append({
                "class": class_name,
                "class_idx": cls_idx,
                "confidence": conf,
                "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                "width": x2 - x1,
                "height": y2 - y1,
            })

    # Print results
    print_separator()
    print("\n📋 DETECTION RESULTS")
    print_separator()

    if not detections:
        print(f"\n  ❌ No detections above {args.confidence} confidence threshold")
        print(f"     Try lowering --confidence (e.g. --confidence 0.25)")
    else:
        print(f"\n  Found {len(detections)} detection(s):\n")

        tags = [d for d in detections if d["class"] == "asset_tag"]
        pole_types = [d for d in detections if d["class"] != "asset_tag"]

        # Tags
        if tags:
            print(f"  Asset Tags ({len(tags)}):")
            for i, t in enumerate(tags):
                print(f"    [{i+1}] confidence: {t['confidence']:.1%}")
                print(f"         bbox: ({t['x1']:.0f}, {t['y1']:.0f}) → "
                      f"({t['x2']:.0f}, {t['y2']:.0f})")
                print(f"         size: {t['width']:.0f}x{t['height']:.0f}px")
                crop_ratio = (t['width'] * t['height']) / (w * h)
                print(f"         area: {crop_ratio:.1%} of full image")
                if t['width'] < 50 or t['height'] < 20:
                    print(f"         ⚠️  Very small crop — OCR may struggle")
        else:
            print(f"  ❌ No asset_tag detected")
            print(f"     OCR pipeline would not run")

        # Pole types
        if pole_types:
            print(f"\n  Pole Type ({len(pole_types)}):")
            for pt in pole_types:
                print(f"    → {pt['class'].upper()}")
                print(f"       confidence: {pt['confidence']:.1%}")
        else:
            print(f"\n  ❌ No pole type detected")

    # Crop simulation — show what OCR would receive
    if tags:
        print_separator()
        print("\n✂️  OCR CROP SIMULATION")
        print_separator()
        print(f"\n  This is exactly what gets sent to the OCR service:\n")

        for i, tag in enumerate(tags):
            crop = crop_to_box(img_array, tag, padding=10)
            ch, cw = crop.shape[:2]
            print(f"  Tag [{i+1}]: {cw}x{ch}px crop")

            if not args.no_visual:
                crop_path = f"/tmp/polepad_cv_tag_crop_{i+1}.jpg"
                cv2.imwrite(crop_path, cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
                print(f"           Saved: {crop_path}")

            # Warn if crop is too small for OCR
            if cw < 100:
                print(f"  ⚠️  Width {cw}px is narrow — OCR preprocessing "
                      f"will upscale but quality may suffer")
            if ch < 30:
                print(f"  ⚠️  Height {ch}px is very short — tag may be cut off")

    # Save annotated image
    if not args.no_visual and detections:
        print_separator()
        print("\n💾 Saving visual outputs...")

        annotated = draw_boxes(img_array, detections)
        annotated_path = "/tmp/polepad_cv_detections.jpg"
        cv2.imwrite(annotated_path, cv2.cvtColor(annotated, cv2.COLOR_RGB2BGR))
        print(f"  Annotated image: {annotated_path}")
        print(f"  (all detections with labels and confidence scores)")

    # Summary
    print_separator("═")
    print("\n  PIPELINE SUMMARY")
    print_separator("═")

    tag_count = len([d for d in detections if d["class"] == "asset_tag"])
    pole_detected = [d["class"] for d in detections if d["class"] != "asset_tag"]

    print(f"\n  Asset tags detected:  {tag_count}")
    print(f"  Pole type detected:   "
          f"{pole_detected[0] if pole_detected else 'none'}")
    print(f"  OCR would run:        {'yes' if tag_count > 0 else 'no'}")

    if tag_count > 0 and pole_detected:
        print(f"\n  ✅ Full pipeline would complete successfully")
        print(f"     YOLO → crop → OCR → store as {pole_detected[0]}")
    elif tag_count > 0:
        print(f"\n  ⚠️  Tag detected but no pole type — asset_type will be 'unknown'")
    elif pole_detected:
        print(f"\n  ⚠️  Pole type detected but no tag — OCR would not run")
    else:
        print(f"\n  ❌ Nothing detected — check confidence threshold and model weights")

    print_separator("═")


if __name__ == "__main__":
    main()
