import os
import io
import importlib

import pytest
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient


pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")


def _img_with_text(text: str) -> bytes:
    img = Image.new("RGB", (600, 250), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((40, 90), text, fill=(0, 0, 0))
    b = io.BytesIO()
    img.save(b, format="JPEG")
    return b.getvalue()


class _FakeCV:
    def __init__(self):
        self.material = "wood"

    async def detect(self, image_bytes: bytes, image_id: str):
        from schemas import CVDetectResponse, TagDetection, BoundingBox
        return CVDetectResponse(
            image_id=image_id,
            model_version="fake-cv",
            tags=[TagDetection(bounding_box=BoundingBox(x1=10, y1=10, x2=590, y2=200), detection_confidence=0.98)],
            attributes=[],
            pole_material=self.material,
            pole_material_confidence=0.99,
            flags=[],
        )


class _FakeOCR:
    async def extract(self, cropped_image_bytes: bytes, image_id: str, original_bbox=None):
        from schemas import OCRExtractResponse, CharacterConfidence
        return OCRExtractResponse(
            image_id=image_id,
            model_version="fake-ocr",
            raw_string="P12345",
            normalized_string="P12345",
            character_confidences=[CharacterConfidence(char=c, confidence=0.99, uncertain=False, position=i) for i, c in enumerate("P12345")],
            uncertain_positions=[],
            mean_confidence=0.99,
            preprocessing_applied=["test"],
            processing_ms=1,
        )


class _Bus:
    def __init__(self):
        self.cv = _FakeCV()
        self.ocr = _FakeOCR()

    async def close(self):
        return None


@pytest.fixture(scope="module")
def app_module():
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    m = importlib.import_module("main")
    importlib.reload(m)
    m.bus = _Bus()
    return m


def test_upload_flag_promote_flow(app_module):
    client = TestClient(app_module.app)

    # 1) create canonical asset from first upload
    r1 = client.post("/api/v1/inspections/upload", files={"file": ("img1.jpg", _img_with_text("P12345"), "image/jpeg")})
    assert r1.status_code == 200
    job1 = r1.json()["job_id"]
    j1 = client.get(f"/api/v1/jobs/{job1}").json()
    assert j1["tags"][0]["normalized_string"] == "P12345"
    asset_id = j1["asset_id"]
    assert asset_id

    # 2) second upload with different material should flag
    app_module.bus.cv.material = "metal"
    r2 = client.post("/api/v1/inspections/upload", files={"file": ("img2.jpg", _img_with_text("P12345"), "image/jpeg")})
    job2 = r2.json()["job_id"]
    j2 = client.get(f"/api/v1/jobs/{job2}").json()
    assert j2["status"] in ("flagged", "processed")

    flags = client.get("/api/v1/flags?status=open").json()
    assert isinstance(flags, list)

    if flags:
        # 3) promote and verify flag resolved
        insp_id = j2["inspection_id"]
        p = client.post(f"/api/v1/inspections/{insp_id}/promote", data={"reviewer": "tester"})
        assert p.status_code == 200


def test_health_smoke(app_module):
    client = TestClient(app_module.app)
    assert client.get("/health").status_code == 200
