"""
apps/api/main.py

PolePad AI — FastAPI Backend
The main orchestration layer. All routes, DI, startup/shutdown.
"""

import os
import uuid
import base64
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, BackgroundTasks, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select, update

# Internal packages
import sys
sys.path.insert(0, "/app/packages/shared-types")
sys.path.insert(0, "/app/packages/comms")
sys.path.insert(0, "/app/packages/db")

from schemas import (
    UploadResponse, InferenceResult, ValidationRequest, ValidationResponse,
    AssetSummary, InspectionStatus, AssetStatus, ValidationAction
)
from client import ServiceBus, calculate_consensus_score
from models import Asset, Inspection, ExtractedTag, AttributeDetection, UserValidation, ConsensusScore, InspectionJob, Base

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ─────────────────────────────────────────────────────────────
# DB Setup
# ─────────────────────────────────────────────────────────────
DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_db():
    async with SessionLocal() as session:
        yield session

# ─────────────────────────────────────────────────────────────
# Service Bus (inter-service comms)
# ─────────────────────────────────────────────────────────────
bus: Optional[ServiceBus] = None

def get_bus() -> ServiceBus:
    return bus

# ─────────────────────────────────────────────────────────────
# Image Storage
# ─────────────────────────────────────────────────────────────
def save_image(image_bytes: bytes, job_id: str) -> str:
    """Save image locally or to S3. Returns storage key."""
    backend = os.getenv("IMAGE_STORAGE_BACKEND", "local")
    if backend == "s3":
        import boto3
        s3 = boto3.client("s3")
        key = f"inspections/{job_id}/raw.jpg"
        bucket = os.environ["S3_BUCKET_NAME"]
        s3.put_object(Bucket=bucket, Key=key, Body=image_bytes, ContentType="image/jpeg")
        return f"s3://{bucket}/{key}"
    else:
        import os as _os
        image_dir = os.getenv("LOCAL_IMAGE_DIR", "/data/images")
        _os.makedirs(image_dir, exist_ok=True)
        path = f"{image_dir}/{job_id}.jpg"
        with open(path, "wb") as f:
            f.write(image_bytes)
        return f"local://{path}"

def load_image(key: str) -> bytes:
    """Load image from storage key."""
    if key.startswith("s3://"):
        import boto3
        s3 = boto3.client("s3")
        parts = key[5:].split("/", 1)
        obj = s3.get_object(Bucket=parts[0], Key=parts[1])
        return obj["Body"].read()
    else:
        path = key.replace("local://", "")
        with open(path, "rb") as f:
            return f.read()

def crop_image(image_bytes: bytes, bbox: dict) -> bytes:
    """Crop image to bounding box. Returns JPEG bytes."""
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(image_bytes))
    cropped = img.crop((int(bbox["x1"]), int(bbox["y1"]), int(bbox["x2"]), int(bbox["y2"])))
    buf = io.BytesIO()
    cropped.save(buf, format="JPEG")
    return buf.getvalue()

# ─────────────────────────────────────────────────────────────
# Lifespan (startup/shutdown)
# ─────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global bus
    # Create tables if not exist (Alembic handles this in prod)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Initialize service bus from environment
    bus = ServiceBus.from_env()
    log.info("Service bus initialized")

    health = await bus.health_check()
    log.info(f"Service health: {health}")

    yield

    await bus.close()
    await engine.dispose()

# ─────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────
app = FastAPI(
    title="PolePad AI",
    description="Crowd-Powered Infrastructure Verification",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "service": "polepad-api"}

@app.get("/api/v1/services/health")
async def services_health(b: ServiceBus = Depends(get_bus)):
    return await b.health_check()

# ─────────────────────────────────────────────────────────────
# Inference Pipeline
# ─────────────────────────────────────────────────────────────
@app.post("/api/v1/inspections/upload", response_model=UploadResponse)
async def upload_inspection(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    asset_id: Optional[str] = Form(None),
    lat: Optional[float] = Form(None),
    lon: Optional[float] = Form(None),
    db: AsyncSession = Depends(get_db),
    b: ServiceBus = Depends(get_bus),
):
    """Upload an image and trigger async inference."""
    # Validate file
    if file.content_type not in ("image/jpeg", "image/png", "image/heic", "image/webp"):
        raise HTTPException(400, "Unsupported image type. Use JPEG, PNG, or WEBP.")

    image_bytes = await file.read()
    if len(image_bytes) > 20 * 1024 * 1024:
        raise HTTPException(400, "Image too large. Max 20MB.")

    job_id = str(uuid.uuid4())

    # Save image
    image_key = save_image(image_bytes, job_id)

    # Create inspection record
    inspection = Inspection(
        id=job_id,
        image_s3_key=image_key,
        asset_id=asset_id,
        status=InspectionStatus.QUEUED,
    )
    db.add(inspection)

    # Create job record
    job = InspectionJob(id=job_id, inspection_id=job_id, status="queued")
    db.add(job)
    await db.commit()

    # Run inference in background
    background_tasks.add_task(
        run_inference_pipeline,
        job_id=job_id,
        image_bytes=image_bytes,
        image_key=image_key,
        lat=lat,
        lon=lon,
        bus=b
    )

    return UploadResponse(
        job_id=job_id,
        status=InspectionStatus.QUEUED,
        poll_url=f"/api/v1/jobs/{job_id}"
    )


async def run_inference_pipeline(
    job_id: str,
    image_bytes: bytes,
    image_key: str,
    lat: Optional[float],
    lon: Optional[float],
    bus: ServiceBus
):
    """
    Full inference pipeline:
    1. YOLO detection (tags + attributes)
    2. Crop tag regions
    3. OCR each crop
    4. Store results
    5. Push to integration systems if enabled
    """
    async with SessionLocal() as db:
        try:
            # Update status
            await db.execute(
                update(Inspection).where(Inspection.id == job_id)
                .values(status=InspectionStatus.PROCESSING)
            )
            await db.commit()

            # ── Step 1: CV Detection ──────────────────────
            cv_result = await bus.cv.detect(image_bytes, job_id)

            if not cv_result.tags and not cv_result.attributes:
                await db.execute(
                    update(Inspection).where(Inspection.id == job_id)
                    .values(status=InspectionStatus.NO_TAG_DETECTED,
                            model_version_cv=cv_result.model_version,
                            flags=["no_tag_detected"])
                )
                await db.commit()
                return

            # ── Step 2: OCR each detected tag ─────────────
            ocr_results = []
            for tag_det in cv_result.tags:
                crop = crop_image(image_bytes, tag_det.bounding_box.model_dump())
                ocr_result = await bus.ocr.extract(crop, job_id, tag_det.bounding_box)
                ocr_results.append((tag_det, ocr_result))

            # ── Step 3: Compute overall confidence ────────
            confidences = []
            for tag_det, ocr_res in ocr_results:
                combined = (tag_det.detection_confidence * 0.4) + (ocr_res.mean_confidence * 0.6)
                confidences.append(combined)
            overall_conf = sum(confidences) / len(confidences) if confidences else 0.0

            # ── Step 4: Find or create asset ──────────────
            primary_tag = ocr_results[0][1].normalized_string if ocr_results else None
            asset_id = None
            if primary_tag:
                asset_result = await db.execute(
                    select(Asset).where(Asset.normalized_tag == primary_tag)
                )
                asset = asset_result.scalar_one_or_none()
                if not asset:
                    asset = Asset(
                        normalized_tag=primary_tag,
                        location_lat=lat,
                        location_lon=lon,
                        status="pending",
                        consensus_score=overall_conf * 0.4,  # AI weight only initially
                    )
                    db.add(asset)
                    await db.flush()
                    # Initialize consensus record
                    db.add(ConsensusScore(asset_id=asset.id, composite_score=overall_conf * 0.4))
                asset_id = asset.id

            # ── Step 5: Store tags and attributes ─────────
            flags = []
            for tag_det, ocr_res in ocr_results:
                db.add(ExtractedTag(
                    inspection_id=job_id,
                    raw_ocr_string=ocr_res.raw_string,
                    normalized_string=ocr_res.normalized_string,
                    character_confidences=ocr_res.character_confidences,
                    uncertain_positions=ocr_res.uncertain_positions,
                    bounding_box=tag_det.bounding_box.model_dump(),
                    ocr_confidence=ocr_res.mean_confidence,
                    detection_confidence=tag_det.detection_confidence,
                    preprocessing_flags=ocr_res.preprocessing_applied,
                ))
                if ocr_res.uncertain_positions:
                    flags.append(f"uncertain_chars_at_{ocr_res.uncertain_positions}")

            for attr in cv_result.attributes:
                db.add(AttributeDetection(
                    inspection_id=job_id,
                    class_label=attr.class_label,
                    confidence=attr.confidence,
                    bounding_box=attr.bounding_box.model_dump(),
                    is_safety_relevant=attr.is_safety_relevant,
                ))
                if attr.is_safety_relevant:
                    flags.append(f"safety_relevant:{attr.class_label}")

            # ── Step 6: Update inspection ──────────────────
            await db.execute(
                update(Inspection).where(Inspection.id == job_id).values(
                    asset_id=asset_id,
                    status=InspectionStatus.COMPLETE,
                    overall_confidence=overall_conf,
                    model_version_cv=cv_result.model_version,
                    model_version_ocr=ocr_results[0][1].model_version if ocr_results else "unknown",
                    flags=flags,
                )
            )
            await db.commit()

            # ── Step 7: Integration push (async, non-blocking) ──
            if asset_id and primary_tag:
                await _push_to_integrations(bus, primary_tag, lat, lon, overall_conf, cv_result.attributes)

            log.info(f"[pipeline] Job {job_id} complete — tag={primary_tag} confidence={overall_conf:.2f}")

        except Exception as e:
            log.exception(f"[pipeline] Job {job_id} failed: {e}")
            await db.execute(
                update(Inspection).where(Inspection.id == job_id)
                .values(status=InspectionStatus.FAILED)
            )
            await db.commit()


async def _push_to_integrations(bus, tag, lat, lon, confidence, attributes):
    """Non-blocking push to Dominion stack integrations"""
    # ArcGIS push
    if bus.arcgis and lat and lon:
        try:
            await bus.arcgis.push_asset(tag, lat, lon, {
                "tag_id": tag, "confidence": confidence, "status": "pending"
            })
        except Exception as e:
            log.warning(f"[arcgis] Push failed for {tag}: {e}")

    # SAP work orders for safety-relevant attributes
    if bus.sap:
        trigger_classes = os.getenv("SAP_TRIGGER_CLASSES", "vegetation_contact,safety_equipment_missing").split(",")
        for attr in attributes:
            if attr.is_safety_relevant and attr.class_label in trigger_classes:
                try:
                    await bus.sap.create_work_order(
                        normalized_tag=tag,
                        attribute_class=attr.class_label,
                        description=f"PolePad AI detected {attr.class_label} at pole {tag} with {attr.confidence:.0%} confidence.",
                        priority="2"
                    )
                except Exception as e:
                    log.warning(f"[sap] WO creation failed: {e}")

# ─────────────────────────────────────────────────────────────
# Job Status
# ─────────────────────────────────────────────────────────────
@app.get("/api/v1/jobs/{job_id}", response_model=InferenceResult)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Poll inference job status. When status=complete, full result is included."""
    result = await db.execute(
        select(Inspection).where(Inspection.id == job_id)
    )
    inspection = result.scalar_one_or_none()
    if not inspection:
        raise HTTPException(404, "Job not found")

    return InferenceResult(
        job_id=job_id,
        status=inspection.status,
        inspection_id=inspection.id,
        asset_id=inspection.asset_id,
        model_versions={"cv": inspection.model_version_cv, "ocr": inspection.model_version_ocr},
        overall_confidence=inspection.overall_confidence,
        flags=inspection.flags or [],
    )

# ─────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────
@app.post("/api/v1/inspections/{inspection_id}/validate", response_model=ValidationResponse)
async def validate_inspection(
    inspection_id: str,
    body: ValidationRequest,
    db: AsyncSession = Depends(get_db),
):
    """Submit a community validation (confirm/dispute/edit)."""
    # Get inspection
    result = await db.execute(select(Inspection).where(Inspection.id == inspection_id))
    inspection = result.scalar_one_or_none()
    if not inspection:
        raise HTTPException(404, "Inspection not found")

    # For MVP: use a placeholder user ID (no auth yet)
    demo_user_id = "00000000-0000-0000-0000-000000000001"

    # Check for existing validation from this user
    existing = await db.execute(
        select(UserValidation).where(
            UserValidation.inspection_id == inspection_id,
            UserValidation.user_id == demo_user_id
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "You have already validated this inspection")

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

    # Recalculate consensus
    if inspection.asset_id:
        validations = await db.execute(
            select(UserValidation).where(UserValidation.inspection_id == inspection_id)
        )
        all_v = validations.scalars().all()
        confirms = sum(1 for v in all_v if v.action == ValidationAction.CONFIRM)
        disputes = sum(1 for v in all_v if v.action == ValidationAction.DISPUTE)
        edits = sum(1 for v in all_v if v.action == ValidationAction.EDIT)

        new_score, new_status = calculate_consensus_score(
            ai_confidence=inspection.overall_confidence,
            confirm_count=confirms,
            dispute_count=disputes,
            edit_count=edits
        )

        await db.execute(
            update(Asset).where(Asset.id == inspection.asset_id)
            .values(consensus_score=new_score, status=new_status)
        )
        await db.execute(
            update(ConsensusScore).where(ConsensusScore.asset_id == inspection.asset_id)
            .values(
                confirm_count=confirms,
                dispute_count=disputes,
                edit_count=edits,
                composite_score=new_score
            )
        )
    else:
        new_score = 0.0
        new_status = "pending"

    await db.commit()

    return ValidationResponse(
        validation_id=validation.id,
        inspection_id=inspection_id,
        new_consensus_score=new_score,
        asset_status=new_status,
    )

# ─────────────────────────────────────────────────────────────
# Assets
# ─────────────────────────────────────────────────────────────
@app.get("/api/v1/assets", response_model=list[AssetSummary])
async def list_assets(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    query = select(Asset).where(Asset.deleted_at.is_(None))
    if status:
        query = query.where(Asset.status == status)
    query = query.order_by(Asset.updated_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    assets = result.scalars().all()
    return [
        AssetSummary(
            id=a.id,
            normalized_tag=a.normalized_tag,
            asset_type=a.asset_type,
            status=a.status,
            consensus_score=a.consensus_score,
            location={"lat": a.location_lat, "lon": a.location_lon} if a.location_lat else None,
        )
        for a in assets
    ]

@app.get("/api/v1/assets/{asset_id}")
async def get_asset(asset_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(404, "Asset not found")
    return asset
