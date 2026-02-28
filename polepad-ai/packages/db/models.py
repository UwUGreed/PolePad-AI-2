"""
packages/db/models.py

SQLAlchemy async models for PolePad AI.
All tables are append-only / soft-deleted — no destructive updates.
"""

from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Float, Integer, Boolean, DateTime,
    ForeignKey, JSON, ARRAY, Text, UniqueConstraint, Index
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


def new_uuid():
    return str(uuid.uuid4())


class Asset(Base):
    __tablename__ = "assets"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    normalized_tag = Column(String(64), unique=True, nullable=False, index=True)
    asset_type = Column(String(32), nullable=False, default="unknown")
    location_lat = Column(Float, nullable=True)
    location_lon = Column(Float, nullable=True)
    location_h3_index = Column(String(16), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="pending")
    consensus_score = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    inspections = relationship("Inspection", back_populates="asset", order_by="Inspection.created_at.desc()")
    consensus = relationship("ConsensusScore", back_populates="asset", uselist=False)

    __table_args__ = (
        Index("ix_assets_status", "status"),
    )


class Inspection(Base):
    __tablename__ = "inspections"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    asset_id = Column(UUID(as_uuid=False), ForeignKey("assets.id"), nullable=True, index=True)
    image_s3_key = Column(String(512), nullable=False)
    image_width = Column(Integer, nullable=True)
    image_height = Column(Integer, nullable=True)
    exif_metadata = Column(JSON, nullable=True)
    model_version_cv = Column(String(32), nullable=False, default="unknown")
    model_version_ocr = Column(String(32), nullable=False, default="unknown")
    overall_confidence = Column(Float, nullable=False, default=0.0)
    status = Column(String(20), nullable=False, default="pending")
    flags = Column(ARRAY(String), nullable=True, default=[])
    inspector_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    asset = relationship("Asset", back_populates="inspections")
    tags = relationship("ExtractedTag", back_populates="inspection", cascade="all, delete-orphan")
    attributes = relationship("AttributeDetection", back_populates="inspection", cascade="all, delete-orphan")
    validations = relationship("UserValidation", back_populates="inspection")

    __table_args__ = (
        Index("ix_inspections_asset_created", "asset_id", "created_at"),
    )


class ExtractedTag(Base):
    __tablename__ = "extracted_tags"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    inspection_id = Column(UUID(as_uuid=False), ForeignKey("inspections.id"), nullable=False, index=True)
    raw_ocr_string = Column(String(128), nullable=False)
    normalized_string = Column(String(64), nullable=False)
    character_confidences = Column(JSON, nullable=False, default=[])
    uncertain_positions = Column(ARRAY(Integer), nullable=True, default=[])
    bounding_box = Column(JSON, nullable=False)
    ocr_confidence = Column(Float, nullable=False, default=0.0)
    detection_confidence = Column(Float, nullable=False, default=0.0)
    preprocessing_flags = Column(ARRAY(String), nullable=True, default=[])

    inspection = relationship("Inspection", back_populates="tags")


class AttributeDetection(Base):
    __tablename__ = "attribute_detections"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    inspection_id = Column(UUID(as_uuid=False), ForeignKey("inspections.id"), nullable=False, index=True)
    class_label = Column(String(64), nullable=False, index=True)
    confidence = Column(Float, nullable=False)
    bounding_box = Column(JSON, nullable=False)
    is_safety_relevant = Column(Boolean, nullable=False, default=False)
    sap_work_order_id = Column(String(32), nullable=True)  # Set when SAP WO is created

    inspection = relationship("Inspection", back_populates="attributes")


class UserValidation(Base):
    __tablename__ = "user_validations"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    inspection_id = Column(UUID(as_uuid=False), ForeignKey("inspections.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True)
    action = Column(String(20), nullable=False)  # confirm, dispute, edit
    corrected_tag = Column(String(64), nullable=True)
    corrected_attributes = Column(JSON, nullable=True)
    validation_confidence = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    inspection = relationship("Inspection", back_populates="validations")

    __table_args__ = (
        UniqueConstraint("inspection_id", "user_id", name="uq_validation_per_user"),
    )


class ConsensusScore(Base):
    __tablename__ = "consensus_scores"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    asset_id = Column(UUID(as_uuid=False), ForeignKey("assets.id"), unique=True, nullable=False, index=True)
    confirm_count = Column(Integer, nullable=False, default=0)
    dispute_count = Column(Integer, nullable=False, default=0)
    edit_count = Column(Integer, nullable=False, default=0)
    ai_weight = Column(Float, nullable=False, default=0.40)
    human_weight = Column(Float, nullable=False, default=0.60)
    composite_score = Column(Float, nullable=False, default=0.0)
    last_calculated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    asset = relationship("Asset", back_populates="consensus")


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    email = Column(String(256), unique=True, nullable=False, index=True)
    hashed_password = Column(String(128), nullable=False)
    display_name = Column(String(64), nullable=True)
    role = Column(String(20), nullable=False, default="community")  # community, field_inspector, admin
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class InspectionJob(Base):
    """Tracks async inference job state"""
    __tablename__ = "inspection_jobs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    inspection_id = Column(UUID(as_uuid=False), ForeignKey("inspections.id"), nullable=True)
    celery_task_id = Column(String(64), nullable=True)
    status = Column(String(20), nullable=False, default="queued")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
