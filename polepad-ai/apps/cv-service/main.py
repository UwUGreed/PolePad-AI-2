import os
import base64
import time
import logging
from io import BytesIO
import sys

from fastapi import FastAPI
from PIL import Image
import numpy as np

sys.path.insert(0, "/app/packages/shared_types")
from schemas import (
    CVDetectRequest, CVDetectResponse, TagDetection,
    AttributeDetection as SchemaAttributeDetection,
    BoundingBox, AttributeClass, ModelDecision,
)

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="PolePad CV Service", version="1.2.0")

SAFETY_RELEVANT_CLASSES = {
    AttributeClass.VEGETATION_CONTACT,
    AttributeClass.STRUCTURAL_DAMAGE,
    AttributeClass.SAFETY_EQUIPMENT_MISSING,
}

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
material_model = None
model_version = os.getenv("MODEL_VERSION", "demo-v1.0.0")
model_path = os.getenv("MODEL_PATH", "/home/anon/Desktop/polepad/polepad-ai/ml/models/demo/best.pt")
material_model_version = os.getenv("POLE_MATERIAL_MODEL_VERSION", "pole-material-v1")
material_model_path = os.getenv("POLE_MATERIAL_MODEL_PATH", "/app/models/demo/pole_material.pt")
confidence_threshold = float(os.getenv("DETECTION_CONFIDENCE_THRESHOLD", "0.45"))
material_ok = False


def _load_yolo(path: str):
    from ultralytics import YOLO
    return YOLO(path)


def _resolve_class_name(names: dict | list | None, class_index: int) -> str:
    if isinstance(names, dict):
        return str(names.get(class_index, f"class_{class_index}"))
    if isinstance(names, list) and 0 <= class_index < len(names):
        return str(names[class_index])
    return f"class_{class_index}"


def load_models():
    global model, material_model, material_ok

    log.info("[cv] Starting model load. model_path=%s", model_path)
    if not os.path.isfile(model_path):
        raise RuntimeError(f"Required CV model missing at {model_path}")

    try:
        model = _load_yolo(model_path)
    except Exception as exc:
        raise RuntimeError(f"Failed loading CV model at {model_path}: {exc}") from exc

    class_names = getattr(model, "names", None)
    if class_names is None:
        raise RuntimeError(f"Loaded model at {model_path} has no class labels/names metadata")

    log.info("[cv] Loaded detection model %s (%s)", model_path, model_version)
    log.info("[cv] Detection classes: %s", class_names)

    if os.path.exists(material_model_path):
        material_model = _load_yolo(material_model_path)
        material_ok = True
        log.info("[cv] Loaded pole material model %s (%s)", material_model_path, material_model_version)
    else:
        material_ok = False
        material_model = None
        log.warning("[cv] Pole material model missing at %s; returning unknown", material_model_path)


@app.on_event("startup")
async def startup():
    load_models()


def decode_image(b64_string: str) -> np.ndarray:
    image_bytes = base64.b64decode(b64_string)
    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    return np.array(img)


def classify_pole_material(image_array: np.ndarray) -> tuple[str, float]:
    if material_model is None:
        return "unknown", 0.0

    result = material_model(image_array, verbose=False)
    try:
        probs = result[0].probs
        if probs is None:
            return "unknown", 0.0
        top_idx = int(probs.top1)
        conf = float(probs.top1conf)
        name = result[0].names.get(top_idx, "unknown").lower()
        if "wood" in name:
            return "wood", conf
        if "metal" in name or "steel" in name:
            return "metal", conf
        return "unknown", conf
    except Exception:
        return "unknown", 0.0


def run_yolo(image_array: np.ndarray) -> tuple[list, list, ModelDecision | None]:
    results = model(image_array, conf=confidence_threshold, verbose=False)
    tags = []
    attributes = []
    primary_decision = None

    for result in results:
        names = getattr(result, "names", getattr(model, "names", {}))
        best_box = None
        best_conf = -1.0

        probs = getattr(result, "probs", None)
        if primary_decision is None and probs is not None and getattr(probs, "top1", None) is not None:
            class_index = int(probs.top1)
            conf = float(probs.top1conf)
            primary_decision = ModelDecision(
                label=_resolve_class_name(names, class_index),
                confidence=conf,
                source="classification",
                class_index=class_index,
                metadata={"threshold": confidence_threshold},
            )

        for box in result.boxes:
            cls_idx = int(box.cls[0])
            conf = float(box.conf[0])
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            bbox = BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2)

            if conf > best_conf:
                best_conf = conf
                best_box = (cls_idx, conf, bbox)

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

        if best_box is not None and primary_decision is None:
            cls_idx, conf, bbox = best_box
            primary_decision = ModelDecision(
                label=_resolve_class_name(names, cls_idx),
                confidence=conf,
                source="detection",
                class_index=cls_idx,
                bounding_box=bbox,
                metadata={"threshold": confidence_threshold},
            )

    tags.sort(key=lambda t: t.detection_confidence, reverse=True)
    return tags, attributes, primary_decision


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "cv-service",
        "model_version": model_version,
        "model_path": model_path,
        "pole_material_model_version": material_model_version,
        "pole_material_model_loaded": material_ok,
    }


@app.post("/detect", response_model=CVDetectResponse)
async def detect(request: CVDetectRequest):
    t0 = time.monotonic()
    image_array = decode_image(request.image_b64)
    tags, attributes, primary_decision = run_yolo(image_array)
    pole_material, pole_material_confidence = classify_pole_material(image_array)
    flags = []
    if not tags:
        flags.append("no_tag_detected")
    if pole_material == "unknown":
        flags.append("pole_material_unknown")
    return CVDetectResponse(
        image_id=request.image_id,
        model_version=model_version,
        tags=tags,
        attributes=attributes,
        pole_material=pole_material,
        pole_material_confidence=pole_material_confidence,
        processing_ms=int((time.monotonic() - t0) * 1000),
        flags=flags,
        primary_decision=primary_decision,
    )
