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
from PIL import Image
import pytesseract

import sys
sys.path.insert(0, "/app/packages/shared_types")
from schemas import OCRExtractResponse, CharacterConfidence, OCRExtractRequest

log = logging.getLogger("ocr-service")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

MODEL_VERSION = os.getenv("OCR_MODEL_VERSION", "tesseract-tag-v1.3.0")
UNCERTAINTY_THRESHOLD = float(os.getenv("OCR_UNCERTAINTY_THRESHOLD", "0.75"))
LOW_CONFIDENCE_THRESHOLD = float(os.getenv("OCR_LOW_CONFIDENCE_THRESHOLD", "0.62"))

ocr_ok = False
tesseract_version = None

WHITELIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_/."


def normalize_tag(text: str) -> str:
    s = (text or "").strip().upper()
    s = s.replace("|", "1").replace(" ", "")
    s = re.sub(r"[^A-Z0-9\-_/\.]", "", s)
    # avoid accidental long garbage strings from OCR
    return s[:64]


def _decode_image(b64: str) -> Image.Image:
    return Image.open(BytesIO(base64.b64decode(b64))).convert("RGB")


def _deskew(gray: np.ndarray) -> tuple[np.ndarray, bool]:
    coords = np.column_stack(np.where(gray < 200))
    if len(coords) < 20:
        return gray, False
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    if abs(angle) < 1.0 or abs(angle) > 20:
        return gray, False
    h, w = gray.shape[:2]
    m = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    rotated = cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return rotated, True


def preprocess_variants(img: Image.Image) -> list[tuple[str, np.ndarray, list[str]]]:
    arr = np.array(img.convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    variants: list[tuple[str, np.ndarray, list[str]]] = []

    base_steps = ["grayscale"]
    deskewed, rotated = _deskew(gray)
    if rotated:
        base_steps.append("deskew")
    gray = deskewed

    denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(denoised)
    sharp = cv2.addWeighted(clahe, 1.5, cv2.GaussianBlur(clahe, (0, 0), 2.0), -0.5, 0)
    upscaled = cv2.resize(sharp, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)

    th_adapt = cv2.adaptiveThreshold(upscaled, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 8)
    _, th_otsu = cv2.threshold(upscaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    variants.append(("clean_adaptive", th_adapt, base_steps + ["denoise", "clahe", "sharpen", "upscale_3x", "adaptive_threshold"]))
    variants.append(("clean_otsu", th_otsu, base_steps + ["denoise", "clahe", "sharpen", "upscale_3x", "otsu_threshold"]))
    variants.append(("gray_upscaled", upscaled, base_steps + ["denoise", "clahe", "sharpen", "upscale_3x"]))
    return variants


def _ocr_with_config(img_arr: np.ndarray, psm: int) -> tuple[str, float, List[float]]:
    config = f"--psm {psm} --oem 3 -c tessedit_char_whitelist={WHITELIST}"
    pil = Image.fromarray(img_arr)
    raw = pytesseract.image_to_string(pil, config=config).strip()
    data = pytesseract.image_to_data(pil, config=config, output_type=pytesseract.Output.DICT)

    confs: List[float] = []
    for c in data.get("conf", []):
        try:
            ci = float(c)
            if ci >= 0:
                confs.append(min(1.0, max(0.0, ci / 100.0)))
        except ValueError:
            continue

    mean_conf = float(sum(confs) / len(confs)) if confs else 0.0
    return raw, mean_conf, confs


def _candidate_score(text: str, mean_conf: float) -> float:
    norm = normalize_tag(text)
    if not norm:
        return -1.0
    has_alpha = any(ch.isalpha() for ch in norm)
    has_digit = any(ch.isdigit() for ch in norm)
    mix_bonus = 0.12 if has_alpha and has_digit else 0.0
    len_bonus = min(len(norm), 16) * 0.01
    return mean_conf + mix_bonus + len_bonus


def run_staged_ocr(img: Image.Image, stage_prefix: str) -> tuple[str, float, List[float], List[str]]:
    attempts: List[Tuple[str, float, List[float], str]] = []
    for variant_name, variant_img, steps in preprocess_variants(img):
        for psm in (7, 8, 6):
            raw, mean_conf, confs = _ocr_with_config(variant_img, psm)
            label = f"{stage_prefix}:{variant_name}:psm{psm}"
            attempts.append((raw, mean_conf, confs, label + ":" + ",".join(steps)))

    best_raw, best_conf, best_confs, best_label = max(attempts, key=lambda item: _candidate_score(item[0], item[1]))
    path, step_blob = best_label.split(":", 1)
    return best_raw, best_conf, best_confs, [path] + step_blob.split(",")


def load_ocr() -> None:
    global ocr_ok, tesseract_version
    try:
        tesseract_version = str(pytesseract.get_tesseract_version())
        ocr_ok = True
        log.info("[ocr] Tesseract initialized: %s", tesseract_version)
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
        original_bounding_box=req.original_bounding_box,
    )
    if not ocr_ok:
        return empty

    try:
        primary_img = _decode_image(req.image_b64)
    except Exception:
        return empty

    raw_text, mean_conf, confs, ocr_steps = run_staged_ocr(primary_img, "crop")
    normalized = normalize_tag(raw_text)

    if (not normalized or mean_conf < LOW_CONFIDENCE_THRESHOLD) and req.fallback_image_b64:
        try:
            fallback_img = _decode_image(req.fallback_image_b64)
            fb_raw, fb_conf, fb_confs, fb_steps = run_staged_ocr(fallback_img, "full")
            if _candidate_score(fb_raw, fb_conf) > _candidate_score(raw_text, mean_conf):
                raw_text, mean_conf, confs, ocr_steps = fb_raw, fb_conf, fb_confs, fb_steps
                normalized = normalize_tag(raw_text)
        except Exception:
            pass

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
        preprocessing_applied=ocr_steps,
        processing_ms=int((time.monotonic() - t0) * 1000),
        original_bounding_box=req.original_bounding_box,
    )
