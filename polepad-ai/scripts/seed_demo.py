"""
scripts/seed_demo.py

Seeds the database with demo data so judges can immediately
explore the UI without uploading images.
Run: python scripts/seed_demo.py
"""

import asyncio
import os
import sys
sys.path.insert(0, "/app/packages/db")
sys.path.insert(0, "/app/packages/shared_types")

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from models import Base, Asset, Inspection, ExtractedTag, AttributeDetection, ConsensusScore, User, InspectionJob
from passlib.context import CryptContext

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://polepad:polepad@localhost:5432/polepad")
engine = create_async_engine(DATABASE_URL)
SessionLocal = async_sessionmaker(engine)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

DEMO_ASSETS = [
    {
        "id": "11111111-1111-1111-1111-111111111101",
        "normalized_tag": "TP-1042-A",
        "asset_type": "pole_wood",
        "location_lat": 33.9988,
        "location_lon": -81.0456,
        "status": "verified",
        "consensus_score": 0.94,
        "confirms": 5, "disputes": 0, "edits": 1,
        "attributes": [
            {"class": "vegetation_contact", "confidence": 0.87, "safety": True},
        ],
        "tag": {"raw": "TP-1O42-A", "normalized": "TP-1042-A", "confidence": 0.91, "uncertain": [3]},
    },
    {
        "id": "11111111-1111-1111-1111-111111111102",
        "normalized_tag": "DE-5507-C",
        "asset_type": "pole_steel",
        "location_lat": 34.0012,
        "location_lon": -81.0391,
        "status": "active",
        "consensus_score": 0.72,
        "confirms": 2, "disputes": 0, "edits": 0,
        "attributes": [
            {"class": "guy_wire", "confidence": 0.91, "safety": False},
            {"class": "transformer", "confidence": 0.79, "safety": False},
        ],
        "tag": {"raw": "DE-5507-C", "normalized": "DE-5507-C", "confidence": 0.95, "uncertain": []},
    },
    {
        "id": "11111111-1111-1111-1111-111111111103",
        "normalized_tag": "UT-3391-B",
        "asset_type": "pole_wood",
        "location_lat": 33.9966,
        "location_lon": -81.0512,
        "status": "disputed",
        "consensus_score": 0.38,
        "confirms": 1, "disputes": 2, "edits": 1,
        "attributes": [
            {"class": "structural_damage", "confidence": 0.82, "safety": True},
        ],
        "tag": {"raw": "UT-3391-B", "normalized": "UT-3391-B", "confidence": 0.68, "uncertain": [5, 6]},
    },
]

DEMO_USER = {
    "id": "00000000-0000-0000-0000-000000000001",
    "email": "demo@polepad.ai",
    "password": "demo1234",
    "display_name": "Demo User",
    "role": "field_inspector",
}


async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as db:
        # Create demo user
        existing_user = await db.get(User, DEMO_USER["id"])
        if not existing_user:
            user = User(
                id=DEMO_USER["id"],
                email=DEMO_USER["email"],
                hashed_password=pwd_context.hash(DEMO_USER["password"]),
                display_name=DEMO_USER["display_name"],
                role=DEMO_USER["role"],
            )
            db.add(user)
            print(f"✅ Created demo user: {DEMO_USER['email']} / {DEMO_USER['password']}")

        for a_data in DEMO_ASSETS:
            existing = await db.get(Asset, a_data["id"])
            if existing:
                print(f"⏭  Asset {a_data['normalized_tag']} already exists")
                continue

            # Create asset
            asset = Asset(
                id=a_data["id"],
                normalized_tag=a_data["normalized_tag"],
                asset_type=a_data["asset_type"],
                location_lat=a_data["location_lat"],
                location_lon=a_data["location_lon"],
                status=a_data["status"],
                consensus_score=a_data["consensus_score"],
            )
            db.add(asset)
            await db.flush()

            # Create inspection
            insp_id = a_data["id"].replace("1111-1111-1111-1", "2222-2222-2222-2")
            inspection = Inspection(
                id=insp_id,
                asset_id=asset.id,
                image_s3_key=f"inspections/demo_{asset.normalized_tag}.jpg",
                status="complete",
                model_version_cv="yolov8-poles-demo-v1.0.0",
                model_version_ocr="paddleocr-tag-demo-v1.0.0",
                overall_confidence=a_data["tag"]["confidence"],
                flags=[f"uncertain_chars_at_{a_data['tag']['uncertain']}"] if a_data["tag"]["uncertain"] else [],
            )
            db.add(inspection)
            await db.flush()

            # Create extracted tag
            char_confs = []
            for i, ch in enumerate(a_data["tag"]["normalized"]):
                is_uncertain = i in a_data["tag"]["uncertain"]
                char_confs.append({
                    "char": ch,
                    "confidence": 0.65 if is_uncertain else 0.95,
                    "uncertain": is_uncertain,
                    "position": i
                })

            db.add(ExtractedTag(
                inspection_id=insp_id,
                raw_ocr_string=a_data["tag"]["raw"],
                normalized_string=a_data["tag"]["normalized"],
                character_confidences=char_confs,
                uncertain_positions=a_data["tag"]["uncertain"],
                bounding_box={"x1": 120, "y1": 45, "x2": 380, "y2": 110},
                ocr_confidence=a_data["tag"]["confidence"],
                detection_confidence=0.92,
            ))

            # Create attribute detections
            for attr in a_data["attributes"]:
                db.add(AttributeDetection(
                    inspection_id=insp_id,
                    class_label=attr["class"],
                    confidence=attr["confidence"],
                    bounding_box={"x1": 50, "y1": 200, "x2": 400, "y2": 600},
                    is_safety_relevant=attr["safety"],
                ))

            # Create consensus score
            db.add(ConsensusScore(
                asset_id=asset.id,
                confirm_count=a_data["confirms"],
                dispute_count=a_data["disputes"],
                edit_count=a_data["edits"],
                composite_score=a_data["consensus_score"],
            ))

            print(f"✅ Seeded asset: {a_data['normalized_tag']} ({a_data['status']})")

        await db.commit()

    print("\n🎉 Demo data seeded successfully!")
    print(f"   Login: {DEMO_USER['email']} / {DEMO_USER['password']}")
    print("   Open: http://localhost:3000\n")


if __name__ == "__main__":
    asyncio.run(seed())
