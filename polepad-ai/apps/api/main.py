from __future__ import annotations

import os
import uuid
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, BackgroundTasks, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select, update, text

import sys
sys.path.insert(0, "/app/packages/shared_types")
sys.path.insert(0, "/app/packages/comms")
sys.path.insert(0, "/app/packages/db")

from schemas import (
    UploadResponse, InferenceResult, ValidationRequest, ValidationResponse,
    AssetSummary, InspectionStatus, ValidationAction,
    OCRExtractResponse, CharacterConfidence,
    AttributeDetection as SchemaAttributeDetection,
    BoundingBox, AttributeClass, ModelDecision,
    InspectionSummary, InspectionEditRequest, ReviewerActionResponse, FlagSummary,
)
from client import ServiceBus, calculate_consensus_score
from models import (
    Asset, Inspection, ExtractedTag,
    AttributeDetection as DBAttributeDetection,
    UserValidation, ConsensusScore, InspectionJob, Base, Flag,
)

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


def sanitize_filename(name: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]", "_", name or "upload.jpg")
    return base[:120]


def _relative_image_path(job_id: str, filename: str) -> str:
    now = datetime.now(timezone.utc)
    ext = Path(filename).suffix.lower() or ".jpg"
    safe = sanitize_filename(Path(filename).stem)
    return f"inspections/{now:%Y/%m}/{job_id}_{safe}{ext}"


def save_image(image_bytes: bytes, job_id: str, filename: str) -> str:
    image_dir = Path(os.getenv("LOCAL_IMAGE_DIR", "/data/images"))
    rel = _relative_image_path(job_id, filename)
    out = image_dir / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(image_bytes)
    return rel


def load_image(rel: str) -> bytes:
    image_dir = Path(os.getenv("LOCAL_IMAGE_DIR", "/data/images"))
    p = (image_dir / rel).resolve()
    if not str(p).startswith(str(image_dir.resolve())):
        raise HTTPException(400, "Invalid path")
    return p.read_bytes()


def crop_image(image_bytes: bytes, bbox: dict) -> bytes:
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(image_bytes))
    cropped = img.crop((int(bbox["x1"]), int(bbox["y1"]), int(bbox["x2"]), int(bbox["y2"])))
    buf = io.BytesIO()
    cropped.save(buf, format="JPEG")
    return buf.getvalue()


async def get_db():
    async with SessionLocal() as session:
        yield session


bus: Optional[ServiceBus] = None


async def ensure_schema_updates() -> None:
    async with engine.begin() as conn:
        for stmt in (
            "ALTER TABLE inspections ADD COLUMN IF NOT EXISTS model_prediction_label VARCHAR(128)",
            "ALTER TABLE inspections ADD COLUMN IF NOT EXISTS model_prediction_confidence DOUBLE PRECISION DEFAULT 0.0 NOT NULL",
            "ALTER TABLE inspections ADD COLUMN IF NOT EXISTS model_prediction_source VARCHAR(32)",
            "ALTER TABLE inspections ADD COLUMN IF NOT EXISTS ocr_raw_text VARCHAR(256)",
            "ALTER TABLE inspections ADD COLUMN IF NOT EXISTS ocr_normalized_text VARCHAR(128)",
            "ALTER TABLE inspections ADD COLUMN IF NOT EXISTS ocr_confidence DOUBLE PRECISION DEFAULT 0.0 NOT NULL",
        ):
            await conn.execute(text(stmt))


def get_bus() -> ServiceBus:
    return bus


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bus
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_schema_updates()
    bus = ServiceBus.from_env()
    yield
    await bus.close()
    await engine.dispose()


app = FastAPI(title="PolePad AI", version="1.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "polepad-api"}


@app.get("/images/{relative_path:path}")
async def image(relative_path: str):
    image_dir = Path(os.getenv("LOCAL_IMAGE_DIR", "/data/images")).resolve()
    target = (image_dir / relative_path).resolve()
    if not str(target).startswith(str(image_dir)) or not target.exists():
        raise HTTPException(404, "Image not found")
    return FileResponse(target)


@app.post("/api/v1/inspections/upload", response_model=UploadResponse)
async def upload_inspection(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    asset_id: Optional[str] = Form(None),
    lat: Optional[float] = Form(None),
    lon: Optional[float] = Form(None),
    county_id: Optional[str] = Form(None),
    uploader_user: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    b: ServiceBus = Depends(get_bus),
):
    image_bytes = await file.read()
    job_id = str(uuid.uuid4())
    rel_path = save_image(image_bytes, job_id, file.filename or "upload.jpg")

    inspection = Inspection(
        id=job_id,
        asset_id=asset_id,
        image_s3_key=rel_path,
        original_filename=file.filename,
        status=InspectionStatus.QUEUED,
        county_id=county_id,
        uploader_user=uploader_user,
    )
    db.add(inspection)
    db.add(InspectionJob(id=job_id, inspection_id=job_id, status="queued"))
    await db.commit()

    background_tasks.add_task(run_inference_pipeline, job_id, image_bytes, lat, lon, b)
    return UploadResponse(job_id=job_id, status=InspectionStatus.QUEUED, poll_url=f"/api/v1/jobs/{job_id}")


async def _upsert_asset_for_tag(db: AsyncSession, normalized_tag: str, inspection: Inspection, lat: Optional[float], lon: Optional[float]):
    found = await db.execute(select(Asset).where(Asset.normalized_tag == normalized_tag))
    asset = found.scalar_one_or_none()
    if asset is None:
        asset = Asset(
            normalized_tag=normalized_tag,
            asset_type=inspection.pole_material or "unknown",
            vegetation=inspection.vegetation,
            county_id=inspection.county_id,
            location_lat=lat,
            location_lon=lon,
            status="active",
            last_inspection_id=inspection.id,
            last_inspection_date=inspection.created_at,
        )
        db.add(asset)
        await db.flush()
        db.add(ConsensusScore(asset_id=asset.id, composite_score=inspection.overall_confidence))
        return asset, False
    return asset, True


def _mismatch_fields(asset: Asset, inspection: Inspection) -> list[str]:
    fields: list[str] = []
    if asset.asset_type not in (None, "unknown") and inspection.pole_material not in (None, "unknown") and asset.asset_type != inspection.pole_material:
        fields.append("asset_type")
    if asset.vegetation is not None and inspection.vegetation is not None and asset.vegetation != inspection.vegetation:
        fields.append("vegetation")
    if asset.county_id and inspection.county_id and asset.county_id != inspection.county_id:
        fields.append("county_id")
    return fields


async def run_inference_pipeline(job_id: str, image_bytes: bytes, lat: Optional[float], lon: Optional[float], bus: ServiceBus):
    async with SessionLocal() as db:
        try:
            await db.execute(update(Inspection).where(Inspection.id == job_id).values(status=InspectionStatus.PROCESSING))
            await db.execute(update(InspectionJob).where(InspectionJob.id == job_id).values(status="processing"))
            await db.commit()

            insp = (await db.execute(select(Inspection).where(Inspection.id == job_id))).scalar_one()
            cv_result = await bus.cv.detect(image_bytes, job_id)
            tag_det = cv_result.tags[0] if cv_result.tags else None
            if tag_det:
                crop = crop_image(image_bytes, tag_det.bounding_box.model_dump())
                ocr_result = await bus.ocr.extract(crop, job_id, tag_det.bounding_box, fallback_image_bytes=image_bytes)
            else:
                ocr_result = await bus.ocr.extract(image_bytes, job_id, None)

            vegetation = any(a.class_label == AttributeClass.VEGETATION_CONTACT for a in cv_result.attributes)
            model_decision = cv_result.primary_decision
            overall_conf = max(ocr_result.mean_confidence, (model_decision.confidence if model_decision else 0.0))

            insp.pole_material = cv_result.pole_material or "unknown"
            insp.vegetation = vegetation
            insp.model_version_cv = cv_result.model_version
            insp.model_version_ocr = ocr_result.model_version
            insp.overall_confidence = overall_conf
            insp.normalized_tag_candidate = ocr_result.normalized_string or None
            insp.model_prediction_label = model_decision.label if model_decision else None
            insp.model_prediction_confidence = model_decision.confidence if model_decision else 0.0
            insp.model_prediction_source = model_decision.source if model_decision else None
            insp.ocr_raw_text = ocr_result.raw_string or None
            insp.ocr_normalized_text = ocr_result.normalized_string or None
            insp.ocr_confidence = ocr_result.mean_confidence

            bbox_payload = tag_det.bounding_box.model_dump() if tag_det else BoundingBox(x1=0, y1=0, x2=0, y2=0).model_dump()
            db.add(ExtractedTag(
                inspection_id=job_id,
                raw_ocr_string=ocr_result.raw_string,
                normalized_string=ocr_result.normalized_string,
                character_confidences=[c.model_dump() for c in ocr_result.character_confidences],
                uncertain_positions=ocr_result.uncertain_positions,
                bounding_box=bbox_payload,
                ocr_confidence=ocr_result.mean_confidence,
                detection_confidence=tag_det.detection_confidence if tag_det else 0.0,
                preprocessing_flags=ocr_result.preprocessing_applied,
            ))

            for attr in cv_result.attributes:
                db.add(DBAttributeDetection(
                    inspection_id=job_id,
                    class_label=attr.class_label,
                    confidence=attr.confidence,
                    bounding_box=attr.bounding_box.model_dump(),
                    is_safety_relevant=attr.is_safety_relevant,
                ))

            if not ocr_result.normalized_string:
                insp.status = InspectionStatus.MANUAL_REVIEW
                await db.execute(update(InspectionJob).where(InspectionJob.id == job_id).values(status="complete"))
                await db.commit()
                return

            asset, existed = await _upsert_asset_for_tag(db, ocr_result.normalized_string, insp, lat, lon)
            insp.asset_id = asset.id

            if existed:
                mismatches = _mismatch_fields(asset, insp)
                if mismatches:
                    flag = Flag(asset_id=asset.id, inspection_id=insp.id, status="open", mismatch_fields=mismatches)
                    db.add(flag)
                    await db.flush()
                    asset.current_flag_id = flag.id
                    insp.flags = [f"mismatch:{m}" for m in mismatches]
                    insp.status = InspectionStatus.FLAGGED
                else:
                    insp.status = InspectionStatus.PROCESSED
                    asset.last_inspection_id = insp.id
                    asset.last_inspection_date = insp.created_at
                    if asset.asset_type in (None, "unknown") and insp.pole_material not in (None, "unknown"):
                        asset.asset_type = insp.pole_material
                    if asset.vegetation is None:
                        asset.vegetation = insp.vegetation
                    if not asset.county_id:
                        asset.county_id = insp.county_id
            else:
                insp.status = InspectionStatus.PROCESSED

            await db.execute(update(InspectionJob).where(InspectionJob.id == job_id).values(status="complete"))
            await db.commit()
        except Exception as e:
            log.exception("pipeline failed: %s", e)
            await db.execute(update(Inspection).where(Inspection.id == job_id).values(status=InspectionStatus.FAILED))
            await db.execute(update(InspectionJob).where(InspectionJob.id == job_id).values(status="failed", error_message=str(e)))
            await db.commit()


@app.get("/api/v1/jobs/{job_id}", response_model=InferenceResult)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    inspection = (await db.execute(select(Inspection).where(Inspection.id == job_id))).scalar_one_or_none()
    if not inspection:
        raise HTTPException(404, "Job not found")
    db_tags = (await db.execute(select(ExtractedTag).where(ExtractedTag.inspection_id == job_id))).scalars().all()
    db_attrs = (await db.execute(select(DBAttributeDetection).where(DBAttributeDetection.inspection_id == job_id))).scalars().all()

    tags_out = []
    for t in db_tags:
        char_confs = [CharacterConfidence(**c) if isinstance(c, dict) else c for c in (t.character_confidences or [])]
        tags_out.append(OCRExtractResponse(
            image_id=job_id,
            model_version=inspection.model_version_ocr,
            raw_string=t.raw_ocr_string,
            normalized_string=t.normalized_string,
            character_confidences=char_confs,
            uncertain_positions=t.uncertain_positions or [],
            mean_confidence=t.ocr_confidence,
            preprocessing_applied=t.preprocessing_flags or [],
            original_bounding_box=BoundingBox(**t.bounding_box) if t.bounding_box else None,
        ))

    attrs_out = []
    for a in db_attrs:
        attrs_out.append(SchemaAttributeDetection(
            class_label=AttributeClass(a.class_label),
            confidence=a.confidence,
            bounding_box=BoundingBox(**a.bounding_box),
            is_safety_relevant=a.is_safety_relevant,
        ))

    primary_decision = None
    if inspection.model_prediction_label:
        primary_decision = ModelDecision(
            label=inspection.model_prediction_label,
            confidence=inspection.model_prediction_confidence or 0.0,
            source=inspection.model_prediction_source or "detection",
        )

    return InferenceResult(
        job_id=job_id,
        status=inspection.status,
        inspection_id=inspection.id,
        asset_id=inspection.asset_id,
        model_versions={"cv": inspection.model_version_cv, "ocr": inspection.model_version_ocr},
        tags=tags_out,
        attributes=attrs_out,
        pole_material=inspection.pole_material,
        overall_confidence=inspection.overall_confidence,
        flags=inspection.flags or [],
        model_prediction_label=inspection.model_prediction_label,
        model_prediction_confidence=inspection.model_prediction_confidence or 0.0,
        model_prediction_source=inspection.model_prediction_source,
        ocr_raw_text=inspection.ocr_raw_text,
        ocr_normalized_text=inspection.ocr_normalized_text,
        ocr_confidence=inspection.ocr_confidence or 0.0,
        primary_decision=primary_decision,
    )


@app.post("/api/v1/inspections/{inspection_id}/validate", response_model=ValidationResponse)
async def validate_inspection(inspection_id: str, body: ValidationRequest, db: AsyncSession = Depends(get_db)):
    inspection = (await db.execute(select(Inspection).where(Inspection.id == inspection_id))).scalar_one_or_none()
    if not inspection:
        raise HTTPException(404, "Inspection not found")
    demo_user_id = "00000000-0000-0000-0000-000000000001"
    validation = UserValidation(
        inspection_id=inspection_id,
        user_id=demo_user_id,
        action=body.action,
        corrected_tag=body.corrected_tag,
        corrected_attributes=body.corrected_attributes,
        validation_confidence=body.confidence,
    )
    db.add(validation)
    await db.flush()
    new_score = 0.0
    new_status = "pending"
    if inspection.asset_id:
        vals = (await db.execute(select(UserValidation).where(UserValidation.inspection_id == inspection_id))).scalars().all()
        confirms = sum(1 for v in vals if v.action == ValidationAction.CONFIRM)
        disputes = sum(1 for v in vals if v.action == ValidationAction.DISPUTE)
        edits = sum(1 for v in vals if v.action == ValidationAction.EDIT)
        new_score, new_status = calculate_consensus_score(inspection.overall_confidence, confirms, disputes, edits)
        await db.execute(update(Asset).where(Asset.id == inspection.asset_id).values(consensus_score=new_score, status=new_status))
    await db.commit()
    return ValidationResponse(validation_id=validation.id, inspection_id=inspection_id, new_consensus_score=new_score, asset_status=new_status)


@app.get("/api/v1/assets", response_model=list[AssetSummary])
async def list_assets(db: AsyncSession = Depends(get_db)):
    assets = (await db.execute(select(Asset).order_by(Asset.created_at.desc()))).scalars().all()
    return [AssetSummary(
        id=a.id, normalized_tag=a.normalized_tag, asset_type=a.asset_type,
        vegetation=a.vegetation, county_id=a.county_id, status=a.status,
        consensus_score=a.consensus_score,
        location={"lat": a.location_lat, "lon": a.location_lon} if a.location_lat and a.location_lon else None,
    ) for a in assets]


@app.get("/api/v1/inspections", response_model=list[InspectionSummary])
async def list_inspections(status: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    q = select(Inspection)
    if status:
        q = q.where(Inspection.status == status)
    rows = (await db.execute(q.order_by(Inspection.created_at.desc()))).scalars().all()
    return [InspectionSummary(
        id=i.id, asset_id=i.asset_id, normalized_tag_candidate=i.normalized_tag_candidate,
        status=i.status, pole_material=i.pole_material, vegetation=i.vegetation,
        county_id=i.county_id, created_at=i.created_at,
    ) for i in rows]


@app.get("/api/v1/inspections/{inspection_id}", response_model=InspectionSummary)
async def get_inspection(inspection_id: str, db: AsyncSession = Depends(get_db)):
    i = (await db.execute(select(Inspection).where(Inspection.id == inspection_id))).scalar_one_or_none()
    if not i:
        raise HTTPException(404, "Inspection not found")
    return InspectionSummary(
        id=i.id, asset_id=i.asset_id, normalized_tag_candidate=i.normalized_tag_candidate,
        status=i.status, pole_material=i.pole_material, vegetation=i.vegetation,
        county_id=i.county_id, created_at=i.created_at,
    )


@app.post("/api/v1/inspections/{inspection_id}/edit", response_model=ReviewerActionResponse)
async def edit_inspection(inspection_id: str, body: InspectionEditRequest, db: AsyncSession = Depends(get_db)):
    i = (await db.execute(select(Inspection).where(Inspection.id == inspection_id))).scalar_one_or_none()
    if not i:
        raise HTTPException(404, "Inspection not found")
    if body.normalized_tag is not None:
        i.normalized_tag_candidate = body.normalized_tag
    if body.pole_material is not None:
        i.pole_material = body.pole_material
    if body.vegetation is not None:
        i.vegetation = body.vegetation
    if body.county_id is not None:
        i.county_id = body.county_id
    await db.commit()
    return ReviewerActionResponse(inspection_id=i.id, status=i.status, asset_id=i.asset_id)


@app.post("/api/v1/inspections/{inspection_id}/promote", response_model=ReviewerActionResponse)
async def promote_inspection(inspection_id: str, reviewer: str = Form("reviewer"), db: AsyncSession = Depends(get_db)):
    i = (await db.execute(select(Inspection).where(Inspection.id == inspection_id))).scalar_one_or_none()
    if not i or not i.asset_id:
        raise HTTPException(404, "Inspection or asset not found")
    asset = (await db.execute(select(Asset).where(Asset.id == i.asset_id))).scalar_one()
    asset.asset_type = i.pole_material or asset.asset_type
    asset.vegetation = i.vegetation
    asset.county_id = i.county_id
    asset.last_inspection_id = i.id
    asset.last_inspection_date = i.created_at
    i.status = InspectionStatus.PROCESSED
    flag = (await db.execute(select(Flag).where(Flag.inspection_id == i.id, Flag.status == "open"))).scalar_one_or_none()
    if flag:
        flag.status = "resolved"
        flag.resolved_by = reviewer
        flag.resolved_at = datetime.now(timezone.utc)
        asset.current_flag_id = None
    await db.commit()
    return ReviewerActionResponse(inspection_id=i.id, status=i.status, asset_id=asset.id, flag_id=flag.id if flag else None)


@app.post("/api/v1/inspections/{inspection_id}/dismiss", response_model=ReviewerActionResponse)
async def dismiss_inspection(inspection_id: str, reviewer: str = Form("reviewer"), note: str = Form(""), db: AsyncSession = Depends(get_db)):
    i = (await db.execute(select(Inspection).where(Inspection.id == inspection_id))).scalar_one_or_none()
    if not i:
        raise HTTPException(404, "Inspection not found")
    i.status = InspectionStatus.PROCESSED
    flag = (await db.execute(select(Flag).where(Flag.inspection_id == i.id, Flag.status == "open"))).scalar_one_or_none()
    if flag:
        flag.status = "dismissed"
        flag.resolved_by = reviewer
        flag.resolution_note = note
        flag.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    return ReviewerActionResponse(inspection_id=i.id, status=i.status, asset_id=i.asset_id, flag_id=flag.id if flag else None)


@app.get("/api/v1/flags", response_model=list[FlagSummary])
async def list_flags(status: str = "open", db: AsyncSession = Depends(get_db)):
    flags = (await db.execute(select(Flag).where(Flag.status == status).order_by(Flag.created_at.desc()))).scalars().all()
    return [FlagSummary(
        id=f.id, asset_id=f.asset_id, inspection_id=f.inspection_id,
        status=f.status, reason=f.reason, mismatch_fields=f.mismatch_fields or [], created_at=f.created_at,
    ) for f in flags]
