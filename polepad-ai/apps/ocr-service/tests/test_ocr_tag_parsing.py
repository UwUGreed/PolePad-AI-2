import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location("ocr_main", Path(__file__).resolve().parents[1] / "main.py")
ocr_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ocr_main)


def test_normalize_tag_keeps_letters_and_numbers():
    assert ocr_main.normalize_tag("  p12a-45  ") == "P12A-45"


def test_candidate_score_prefers_alphanumeric_mix():
    numeric = ocr_main._candidate_score("123456", 0.90)
    alnum = ocr_main._candidate_score("P12345", 0.90)
    assert alnum > numeric
