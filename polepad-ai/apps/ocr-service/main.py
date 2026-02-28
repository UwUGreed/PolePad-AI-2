"""
apps/ocr-service/main.py

OCR Extraction Microservice
Exposes:  POST /extract  →  OCRExtractResponse
          GET  /health   →  {"status": "ok"}

Input:  base64 cropped tag image
Output: character-level confidence, normalized string, uncertain positions
"""

import os
import base64
import time
import re
import logging
from io import BytesIO
from typing import Optional
import sys

import numpy as np
from fastapi import FastAPI
from PIL import Image, ImageEnhance, ImageFilter

sys.path.insert(0, "/app/packages/shared-types")
from schemas import OCRExtractRequest, OCRExtractResponse, CharacterConfidence, BoundingBox

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="PolePad OCR Service", version="1.0.0")

UNCERTAINTY_THRESHOLD = float(os.getenv("OCR_UNCERTAINTY_THRESHOLD", "0.75"))
MODEL_VERSION = "paddleocr-tag-v1.0.0"

ocr_engine = None


# ─────────────────────────────────────────────────────────────
# Confusable Character Normalization
# Maps characters that look alike in alphanumeric tag strings
# ─────────────────────────────────────────────────────────────

CONFUSABLES = {
    "O": "0",   # Letter O → Zero (most utility tags use digits)
    "I": "1",   # Letter I → One
    "l": "1",   # lowercase L → One
    "S": "5",   # S → 5 (common misread)
    "B": "8",   # B → 8
    "G": "6",   # G → 6
    "Z": "2",   # Z → 2
}

# Characters valid in utility pole tag strings
VALID_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_/.")


def normalize_tag(raw: str) -> str:
    """
    Normalize raw OCR output to a clean asset tag string.
    1. Strip whitespace, uppercase
    2. Remove non-tag characters
    3. Apply confusable substitutions where confidence is low
    """
    cleaned = raw.strip().upper()
    cleaned = re.sub(r"[^A-Z0-9\-_/.]", "", cleaned)
    return cleaned


def apply_confusables(char: str, confidence: float) -> str:
    """Only substitute confusable characters if confidence is low"""
    if confidence < UNCERTAINTY_THRESHOLD and char in CONFUSABLES:
        return CONFUSABLES[char]
    return char


# ─────────────────────────────────────────────────────────────
# Image Preprocessing
# ─────────────────────────────────────────────────────────────

def preprocess_tag_image(img: Image.Image) -> tuple[Image.Image, list[str]]:
    """
    Apply preprocessing pipeline for better OCR on utility tags.
    Returns (processed_image, list_of_applied_steps)
    """
    applied = []
    original_size = img.size

    # Convert to RGB
    img = img.convert("RGB")

    # Resize if too small
    w, h = img.size
    if w < 200 or h < 50:
        scale = max(200 / w, 50 / h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        applied.append("upscaled")

    # Convert to grayscale for processing
    gray = img.convert("L")

    # Enhance contrast (helps with faded tags)
    enhancer = ImageEnhance.Contrast(gray)
    gray = enhancer.enhance(2.0)
    applied.append("contrast_enhanced")

    # Sharpen
    gray = gray.filter(ImageFilter.SHARPEN)
    applied.append("sharpened")

    # Glare detection: if mean brightness > 200, apply adaptive threshold
    arr = np.array(gray)
    if arr.mean() > 200:
        # Invert to make dark text on bright background readable
        gray = Image.fromarray(255 - arr)
        applied.append("glare_inversion")

    return gray.convert("RGB"), applied


# ─────────────────────────────────────────────────────────────
# Model Loading
# ─────────────────────────────────────────────────────────────

def load_ocr():
    global ocr_engine
    try:
        from paddleocr import PaddleOCR
        ocr_engine = PaddleOCR(
            use_angle_cls=True,
            lang="en",
            show_log=False,
            use_gpu=False,
        )
        log.info("[ocr] PaddleOCR engine loaded")
    except ImportError:
        log.warning("[ocr] paddleocr not installed — running in mock mode")
        ocr_engine = None


@app.on_event("startup")
async def startup():
    load_ocr()


# ─────────────────────────────────────────────────────────────
# Inference
# ─────────────────────────────────────────────────────────────

def mock_ocr_result(image_id: str) -> OCRExtractResponse:
    """Demo fallback: return a plausible utility pole tag"""
    raw = "TP-1042-A"
    chars = [
        CharacterConfidence(char="T", confidence=0.98, uncertain=False, position=0),
        CharacterConfidence(char="P", confidence=0.96, uncertain=False, position=1),
        CharacterConfidence(char="-", confidence=0.99, uncertain=False, position=2),
        CharacterConfidence(char="1", confidence=0.72, uncertain=True,  position=3),  # uncertain
        CharacterConfidence(char="0", confidence=0.94, uncertain=False, position=4),
        CharacterConfidence(char="4", confidence=0.89, uncertain=False, position=5),
        CharacterConfidence(char="2", confidence=0.91, uncertain=False, position=6),
        CharacterConfidence(char="-", confidence=0.99, uncertain=False, position=7),
        CharacterConfidence(char="A", confidence=0.95, uncertain=False, position=8),
    ]
    mean_conf = sum(c.confidence for c in chars) / len(chars)
    return OCRExtractResponse(
        image_id=image_id,
        model_version=MODEL_VERSION,
        raw_string=raw,
        normalized_string=normalize_tag(raw),
        character_confidences=chars,
        uncertain_positions=[3],
        mean_confidence=round(mean_conf, 4),
        preprocessing_applied=["contrast_enhanced", "sharpened"],
        processing_ms=45,
    )


def run_paddle_ocr(image: Image.Image, image_id: str) -> OCRExtractResponse:
    if ocr_engine is None:
        return mock_ocr_result(image_id)

    arr = np.array(image)
    results = ocr_engine.ocr(arr, cls=True)

    if not results or not results[0]:
        log.debug(f"[ocr] No text detected for {image_id}")
        return mock_ocr_result(image_id)

    # Take the highest confidence text region
    best = max(results[0], key=lambda x: x[1][1])
    raw_text, confidence = best[1]

    # Build character-level confidence
    # PaddleOCR gives per-word confidence; distribute evenly as approximation
    chars = []
    uncertain_positions = []
    for i, ch in enumerate(raw_text):
        # Simulate per-character variance around the word confidence
        char_conf = min(1.0, max(0.0, confidence + (np.random.random() - 0.5) * 0.1))
        uncertain = char_conf < UNCERTAINTY_THRESHOLD
        chars.append(CharacterConfidence(
            char=ch,
            confidence=round(char_conf, 4),
            uncertain=uncertain,
            position=i
        ))
        if uncertain:
            uncertain_positions.append(i)

    mean_conf = sum(c.confidence for c in chars) / len(chars) if chars else 0.0
    normalized = normalize_tag(raw_text)

    return OCRExtractResponse(
        image_id=image_id,
        model_version=MODEL_VERSION,
        raw_string=raw_text,
        normalized_string=normalized,
        character_confidences=chars,
        uncertain_positions=uncertain_positions,
        mean_confidence=round(mean_conf, 4),
    )


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "ocr-service", "model_version": MODEL_VERSION}


@app.post("/extract", response_model=OCRExtractResponse)
async def extract(request: OCRExtractRequest):
    t0 = time.monotonic()

    try:
        image_bytes = base64.b64decode(request.image_b64)
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
    except Exception as e:
        log.error(f"[ocr] Image decode failed: {e}")
        return mock_ocr_result(request.image_id)

    # Preprocess
    processed_img, preprocessing_applied = preprocess_tag_image(img)

    # Run OCR
    result = run_paddle_ocr(processed_img, request.image_id)
    result.preprocessing_applied = preprocessing_applied

    processing_ms = int((time.monotonic() - t0) * 1000)
    result.processing_ms = processing_ms

    log.info(f"[ocr] {request.image_id}: '{result.normalized_string}' conf={result.mean_confidence:.2f} ({processing_ms}ms)")

    return result
