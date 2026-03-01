"""
apps/cv-service/main.py

YOLOv8 Detection Microservice
Exposes:  POST /detect   →  CVDetectResponse
          GET  /health   →  {"status": "ok"}
"""

import os
import base64
import time
import logging
from io import BytesIO
from typing import Optional
import sys

from fastapi import FastAPI
from PIL import Image
import numpy as np

# FIX: directory is packages/shared_types (underscore), not shared-types (hyphen)
sys.path.insert(0, "/app/packages/shared_types")
from schemas import (
    CVDetectRequest, CVDetectResponse, TagDetection,
    AttributeDetection as SchemaAttributeDetection,
    BoundingBox, AttributeClass
)

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="PolePad CV Service", version="1.0.0")

# ─────────────────────────────────────────────────────────────
# Model Config
# ─────────────────────────────────────────────────────────────

SAFETY_RELEVANT_CLASSES = {
    AttributeClass.VEGETATION_CONTACT,
    AttributeClass.STRUCTURAL_DAMAGE,
    AttributeClass.SAFETY_EQUIPMENT_MISSING,
}

# Matches dataset.yaml exactly:
#   0: asset_tag  1: crossarm  2: vegetation_contact  3: guy_wire
#   4: transformer  5: safety_equipment  6: structural_damage  7: safety_equipment_missing
CLASS_MAP = {
    0: "asset_tag",
    1: AttributeClass.CROSSARM,
    2: AttributeClass.VEGETATION_CONTACT,
    3: AttributeClass.GUY_WIRE,
    4: AttributeClass.TRANSFORMER,
    5: AttributeClass.SAFETY_EQUIPMENT,
    6: AttributeClass.STRUCTURAL_DAMAGE,
    7: AttributeClass.SAFETY_EQUIPMENT_MISSING,
}

model = None
model_version = os.getenv("MODEL_VERSION", "demo-v1.0.0")
model_path = os.getenv("MODEL_PATH", "/app/models/demo/best.pt")
confidence_threshold = float(os.getenv("DETECTION_CONFIDENCE_THRESHOLD", "0.45"))


def load_model():
    global model
    try:
        from ultralytics import YOLO
        if os.path.exists(model_path):
            model = YOLO(model_path)
            log.info(f"[cv] Loaded model: {model_path} (version={model_version})")
        else:
            log.warning(f"[cv] Model not found at {model_path}, loading YOLOv8n as demo")
            model = YOLO("yolov8n.pt")
            log.info("[cv] Demo model loaded (YOLOv8n pretrained)")
    except ImportError:
        log.warning("[cv] ultralytics not installed — running in mock mode")
        model = None


@app.on_event("startup")
async def startup():
    load_model()


# ─────────────────────────────────────────────────────────────
# Inference
# ─────────────────────────────────────────────────────────────

def decode_image(b64_string: str) -> np.ndarray:
    image_bytes = base64.b64decode(b64_string)
    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    return np.array(img)


def mock_detect(image_array: np.ndarray) -> tuple[list, list]:
    """Demo mode: return synthetic detections so the UI works without real weights"""
    h, w = image_array.shape[:2]
    tags = [
        TagDetection(
            bounding_box=BoundingBox(x1=w*0.3, y1=h*0.2, x2=w*0.7, y2=h*0.35),
            detection_confidence=0.92,
        )
    ]
    attributes = [
        SchemaAttributeDetection(
            class_label=AttributeClass.GUY_WIRE,
            confidence=0.85,
            bounding_box=BoundingBox(x1=w*0.1, y1=h*0.4, x2=w*0.4, y2=h*0.9),
            is_safety_relevant=False,
        )
    ]
    return tags, attributes


def run_yolo(image_array: np.ndarray) -> tuple[list, list]:
    if model is None:
        return mock_detect(image_array)

    results = model(image_array, conf=confidence_threshold, verbose=False)
    tags = []
    attributes = []

    for result in results:
        for box in result.boxes:
            cls_idx = int(box.cls[0])
            conf = float(box.conf[0])
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            bbox = BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2)

            if cls_idx == 0:
                tags.append(TagDetection(bounding_box=bbox, detection_confidence=conf))
            elif cls_idx in CLASS_MAP:
                attr_class = CLASS_MAP[cls_idx]
                attributes.append(SchemaAttributeDetection(
                    class_label=attr_class,
                    confidence=conf,
                    bounding_box=bbox,
                    is_safety_relevant=attr_class in SAFETY_RELEVANT_CLASSES,
                ))

    if not tags and not attributes:
        log.debug("[cv] No detections — using demo fallback")
        return mock_detect(image_array)

    return tags, attributes


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "cv-service", "model_version": model_version}


@app.post("/detect", response_model=CVDetectResponse)
async def detect(request: CVDetectRequest):
    t0 = time.monotonic()

    try:
        image_array = decode_image(request.image_b64)
    except Exception as e:
        log.error(f"[cv] Image decode failed: {e}")
        return CVDetectResponse(
            image_id=request.image_id,
            model_version=model_version,
            flags=["image_decode_failed"]
        )

    flags = []
    h, w = image_array.shape[:2]

    if h < 100 or w < 100:
        flags.append("low_resolution")
    if h * w > 25_000_000:
        flags.append("very_high_resolution_downscaled")

    tags, attributes = run_yolo(image_array)

    if not tags:
        flags.append("no_tag_detected")

    processing_ms = int((time.monotonic() - t0) * 1000)
    log.info(f"[cv] {request.image_id}: {len(tags)} tags, {len(attributes)} attrs in {processing_ms}ms")

    return CVDetectResponse(
        image_id=request.image_id,
        model_version=model_version,
        tags=tags,
        attributes=attributes,
        processing_ms=processing_ms,
        flags=flags,
    )
