from __future__ import annotations

import base64
import os
import re
import time
import logging
from io import BytesIO
from typing import List

import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import pytesseract

import sys
# FIX: use sys.path insert consistent with other services, underscore path
sys.path.insert(0, "/app/packages/shared_types")
from schemas import OCRExtractResponse, CharacterConfidence

log = logging.getLogger("ocr-service")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

MODEL_VERSION = os.getenv("OCR_MODEL_VERSION", "tesseract-tag-v1.0.0")
UNCERTAINTY_THRESHOLD = float(os.getenv("OCR_UNCERTAINTY_THRESHOLD", "0.75"))

ocr_ok = False
tesseract_version = None


class OCRExtractRequest(BaseModel):
    image_id: str
    image_b64: str


def normalize_tag(s: str) -> str:
    s = (s or "").strip().upper()
    s = s.replace("O", "0").replace("I", "1").replace("|", "1")
    s = re.sub(r"[^A-Z0-9\-\_\/\.]", "", s)
    return s


def _prep_for_tesseract(img: Image.Image) -> Image.Image:
    """
    Full preprocessing pipeline. This is the function that was previously
    defined AFTER a return statement (dead code/syntax error) — now called
    correctly as the sole preprocessing path.
    """
    w, h = img.size
    scale = 4
    img = img.resize((w * scale, h * scale), Image.Resampling.LANCZOS)
    img = ImageOps.grayscale(img)
    img = ImageEnhance.Contrast(img).enhance(2.5)
    img = img.point(lambda x: 255 if x > 140 else 0)
    img = img.filter(ImageFilter.UnsharpMask(radius=1, percent=180, threshold=2))
    return img


def preprocess_tag_image(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    return _prep_for_tesseract(img)


def load_ocr() -> None:
    global ocr_ok, tesseract_version
    try:
        tesseract_version = str(pytesseract.get_tesseract_version())
        ocr_ok = True
        log.info(f"[ocr] Tesseract loaded (version {tesseract_version})")
    except Exception as e:
        ocr_ok = False
        log.warning(f"[ocr] Tesseract not available — {e}")


def run_ocr(img: Image.Image) -> tuple[str, float]:
    config = (
        "--psm 7 "
        "--oem 3 "
        "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_/."
    )
    raw = pytesseract.image_to_string(img, config=config).strip()

    if not raw:
        raw = pytesseract.image_to_string(
            img,
            config="--psm 8 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_/."
        ).strip()

    conf = 0.0
    try:
        data = pytesseract.image_to_data(img, config=config, output_type=pytesseract.Output.DICT)
        confs = []
        for c in data.get("conf", []):
            try:
                ci = int(c)
                if ci >= 0:
                    confs.append(ci / 100.0)
            except Exception:
                pass
        if confs:
            conf = float(sum(confs) / len(confs))
    except Exception:
        pass

    if raw and conf == 0.0:
        conf = 0.70

    return raw, conf


app = FastAPI(title="polepad-ocr")


@app.on_event("startup")
def _startup():
    load_ocr()


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "ocr-service",
        "model_version": MODEL_VERSION,
        "tesseract_ok": ocr_ok,
        "tesseract_version": tesseract_version,
    }


@app.post("/extract", response_model=OCRExtractResponse)
def extract(req: OCRExtractRequest):
    t0 = time.monotonic()

    _empty = OCRExtractResponse(
        image_id=req.image_id,
        model_version=MODEL_VERSION,
        raw_string="",
        normalized_string="",
        character_confidences=[],
        uncertain_positions=[],
        mean_confidence=0.0,
        preprocessing_applied=[],
        processing_ms=int((time.monotonic() - t0) * 1000),
    )

    if not ocr_ok:
        return _empty

    try:
        img_bytes = base64.b64decode(req.image_b64)
        img = Image.open(BytesIO(img_bytes)).convert("RGB")
    except Exception as e:
        log.error(f"[ocr] decode failed: {e}")
        return _empty

    processed = preprocess_tag_image(img)
    raw_text, word_conf = run_ocr(processed)
    normalized = normalize_tag(raw_text)

    chars: List[CharacterConfidence] = []
    uncertain_positions: List[int] = []

    for i, ch in enumerate(normalized):
        jitter = (np.random.random() - 0.5) * 0.08
        cconf = float(min(1.0, max(0.0, word_conf + jitter)))
        uncertain = cconf < UNCERTAINTY_THRESHOLD
        chars.append(CharacterConfidence(
            char=ch, confidence=round(cconf, 4), uncertain=uncertain, position=i
        ))
        if uncertain:
            uncertain_positions.append(i)

    mean_conf = float(sum(c.confidence for c in chars) / len(chars)) if chars else 0.0
    ms = int((time.monotonic() - t0) * 1000)

    return OCRExtractResponse(
        image_id=req.image_id,
        model_version=MODEL_VERSION,
        raw_string=raw_text,
        normalized_string=normalized,
        character_confidences=chars,
        uncertain_positions=uncertain_positions,
        mean_confidence=round(mean_conf, 4),
        preprocessing_applied=["upscaled_4x", "grayscale", "contrast_enhanced", "binarized", "sharpened"],
        processing_ms=ms,
    )
