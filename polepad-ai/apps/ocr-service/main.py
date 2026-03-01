from __future__ import annotations

import base64
import os
import re
import time
import logging
from io import BytesIO
from typing import List, Tuple

import cv2
import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel
from PIL import Image
import pytesseract

import sys
sys.path.insert(0, "/app/packages/shared_types")
from schemas import OCRExtractResponse, CharacterConfidence

log = logging.getLogger("ocr-service")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

MODEL_VERSION = os.getenv("OCR_MODEL_VERSION", "tesseract-tag-v1.2.0")
UNCERTAINTY_THRESHOLD = float(os.getenv("OCR_UNCERTAINTY_THRESHOLD", "0.75"))

ocr_ok = False
tesseract_version = None

WHITELIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_/."


class OCRExtractRequest(BaseModel):
    image_id: str
    image_b64: str


def normalize_tag(s: str) -> str:
    s = (s or "").strip().upper()
    # Keep alpha-numeric tags; only normalize obvious OCR separators.
    s = s.replace("|", "1")
    s = re.sub(r"[^A-Z0-9\-_/\.]", "", s)
    return s


def preprocess_tag_image(img: Image.Image) -> tuple[Image.Image, Image.Image, List[str]]:
    steps: List[str] = []
    arr = np.array(img.convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    steps.append("grayscale")
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    steps.append("gaussian_blur")
    th = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15)
    steps.append("adaptive_threshold")
    up_bin = cv2.resize(th, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    up_gray = cv2.resize(gray, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    steps.append("upscaled_3x")
    return Image.fromarray(up_bin), Image.fromarray(up_gray), steps


def _ocr_with_config(img: Image.Image, psm: int) -> tuple[str, float, List[float]]:
    config = f"--psm {psm} --oem 3 -c tessedit_char_whitelist={WHITELIST}"
    raw = pytesseract.image_to_string(img, config=config).strip()
    data = pytesseract.image_to_data(img, config=config, output_type=pytesseract.Output.DICT)
    confs: List[float] = []
    for c in data.get("conf", []):
        try:
            ci = float(c)
            if ci >= 0:
                confs.append(min(1.0, max(0.0, ci / 100.0)))
        except Exception:
            continue
    mean_conf = float(sum(confs) / len(confs)) if confs else 0.0
    return raw, mean_conf, confs


def _candidate_score(text: str, mean_conf: float) -> float:
    norm = normalize_tag(text)
    if not norm:
        return -1.0
    has_alpha = any(ch.isalpha() for ch in norm)
    has_digit = any(ch.isdigit() for ch in norm)
    mix_bonus = 0.12 if (has_alpha and has_digit) else 0.0
    len_bonus = min(len(norm), 12) * 0.01
    return mean_conf + mix_bonus + len_bonus


def run_ocr(binary_img: Image.Image, gray_img: Image.Image) -> tuple[str, float, List[float], List[str]]:
    attempts: List[Tuple[str, float, List[float], str]] = []
    for label, img in (("binary", binary_img), ("gray", gray_img)):
        for psm in (7, 8, 6):
            raw, mean_conf, confs = _ocr_with_config(img, psm)
            attempts.append((raw, mean_conf, confs, f"ocr_{label}_psm{psm}"))

    best_raw, best_conf, best_confs, best_label = max(
        attempts,
        key=lambda item: _candidate_score(item[0], item[1]),
    )
    return best_raw, best_conf, best_confs, [best_label]


def load_ocr() -> None:
    global ocr_ok, tesseract_version
    try:
        tesseract_version = str(pytesseract.get_tesseract_version())
        ocr_ok = True
    except Exception as exc:
        ocr_ok = False
        log.warning("[ocr] Tesseract unavailable: %s", exc)


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
    empty = OCRExtractResponse(
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
        return empty
    try:
        img = Image.open(BytesIO(base64.b64decode(req.image_b64))).convert("RGB")
    except Exception:
        return empty

    processed_bin, processed_gray, steps = preprocess_tag_image(img)
    raw_text, mean_conf, confs, ocr_steps = run_ocr(processed_bin, processed_gray)
    normalized = normalize_tag(raw_text)

    chars: List[CharacterConfidence] = []
    uncertain_positions: List[int] = []
    for i, ch in enumerate(normalized):
        cconf = confs[min(i, len(confs) - 1)] if confs else mean_conf
        uncertain = cconf < UNCERTAINTY_THRESHOLD
        chars.append(CharacterConfidence(char=ch, confidence=round(cconf, 4), uncertain=uncertain, position=i))
        if uncertain:
            uncertain_positions.append(i)

    return OCRExtractResponse(
        image_id=req.image_id,
        model_version=MODEL_VERSION,
        raw_string=raw_text,
        normalized_string=normalized,
        character_confidences=chars,
        uncertain_positions=uncertain_positions,
        mean_confidence=round(mean_conf, 4),
        preprocessing_applied=steps + ocr_steps,
        processing_ms=int((time.monotonic() - t0) * 1000),
    )
