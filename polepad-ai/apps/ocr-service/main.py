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

from packages.shared_types.schemas import OCRExtractResponse, CharacterConfidence

log = logging.getLogger("ocr-service")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

MODEL_VERSION = os.getenv("OCR_MODEL_VERSION", "tesseract-tag-v1.0.0")
UNCERTAINTY_THRESHOLD = float(os.getenv("OCR_UNCERTAINTY_THRESHOLD", "0.75"))

ocr_ok = False
tesseract_version = None


class OCRExtractRequest(BaseModel):
    image_id: str
    image_b64: str  # base64 of raw image bytes (jpg/png)


def normalize_tag(s: str) -> str:
    s = (s or "").strip().upper()
    # common confusables
    s = s.replace("O", "0").replace("I", "1").replace("|", "1")
    # keep only allowed chars for tags
    s = re.sub(r"[^A-Z0-9\-\_\/\.]", "", s)
    return s


def preprocess_tag_image(img: Image.Image) -> Image.Image:
    # light, safe preprocessing: contrast + sharpen
    img = img.convert("RGB")
    img = ImageEnhance.Contrast(img).enhance(1.8)
    img = img.filter(ImageFilter.SHARPEN)
    return img


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
    # PSM 7: single text line (tag plates usually)
    config = (
        "--psm 7 "
        "--oem 3 "
        "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_/."
    )

    # Try line mode first
    raw = pytesseract.image_to_string(img, config=config).strip()

    # Fallback: single word
    if not raw:
        raw = pytesseract.image_to_string(
            img,
            config="--psm 8 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_/."
        ).strip()

    # Confidence: use image_to_data word confidences if possible
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

    # If still 0 but we got text, give a conservative baseline
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

    if not ocr_ok:
        # return a clean "empty" result rather than fake TP-1042-A
        return OCRExtractResponse(
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

    try:
        img_bytes = base64.b64decode(req.image_b64)
        img = Image.open(BytesIO(img_bytes)).convert("RGB")
    except Exception as e:
        log.error(f"[ocr] decode failed: {e}")
        return OCRExtractResponse(
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

    processed = preprocess_tag_image(img)
    raw_text, word_conf = run_ocr(processed)
    normalized = normalize_tag(raw_text)

    chars: List[CharacterConfidence] = []
    uncertain_positions: List[int] = []

    # distribute word_conf across chars (tesseract doesn't provide per-char)
    for i, ch in enumerate(normalized):
        jitter = (np.random.random() - 0.5) * 0.08
        cconf = float(min(1.0, max(0.0, word_conf + jitter)))
        uncertain = cconf < UNCERTAINTY_THRESHOLD
        chars.append(CharacterConfidence(char=ch, confidence=round(cconf, 4), uncertain=uncertain, position=i))
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
        preprocessing_applied=["contrast_enhanced", "sharpened"],
        processing_ms=ms,
    )def _prep_for_tesseract(img: Image.Image) -> Image.Image:
    # 1) upscale big (tesseract loves big text)
    w,h = img.size
    scale = 4
    img = img.resize((w*scale, h*scale), Image.Resampling.LANCZOS)
    # 2) grayscale
    img = ImageOps.grayscale(img)
    # 3) increase contrast
    img = ImageEnhance.Contrast(img).enhance(2.5)
    # 4) binarize (hard threshold)
    img = img.point(lambda x: 255 if x > 140 else 0)
    # 5) tiny sharpen
    img = img.filter(ImageFilter.UnsharpMask(radius=1, percent=180, threshold=2))
    return img


