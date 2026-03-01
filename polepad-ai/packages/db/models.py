"""
packages/db/models.py

SQLAlchemy async models for PolePad AI.
"""

from __future__ import annotations
import uuid
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


class County(Base):
    __tablename__ = "counties"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    state = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Asset(Base):
    __tablename__ = "assets"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    normalized_tag = Column(String(64), unique=True, nullable=False, index=True)
    asset_type = Column(String(32), nullable=False, default="unknown")
    vegetation = Column(Boolean, nullable=True)
    county_id = Column(String(64), ForeignKey("counties.id"), nullable=True, index=True)
    location_lat = Column(Float, nullable=True)
    location_lon = Column(Float, nullable=True)
    location_h3_index = Column(String(16), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="pending")
    consensus_score = Column(Float, nullable=False, default=0.0)
    last_inspection_id = Column(UUID(as_uuid=False), ForeignKey("inspections.id"), nullable=True, index=True)
    last_inspection_date = Column(DateTime(timezone=True), nullable=True)
    current_flag_id = Column(UUID(as_uuid=False), ForeignKey("flags.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    inspections = relationship("Inspection", back_populates="asset", foreign_keys="Inspection.asset_id", order_by="Inspection.created_at.desc()")
    consensus = relationship("ConsensusScore", back_populates="asset", uselist=False)
    flags = relationship("Flag", back_populates="asset", foreign_keys="Flag.asset_id")

    __table_args__ = (Index("ix_assets_status", "status"),)


class Inspection(Base):
    __tablename__ = "inspections"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    asset_id = Column(UUID(as_uuid=False), ForeignKey("assets.id"), nullable=True, index=True)
    image_s3_key = Column(String(512), nullable=False)
    original_filename = Column(String(256), nullable=True)
    image_width = Column(Integer, nullable=True)
    image_height = Column(Integer, nullable=True)
    exif_metadata = Column(JSON, nullable=True)
    model_version_cv = Column(String(64), nullable=False, default="unknown")
    model_version_ocr = Column(String(64), nullable=False, default="unknown")
    overall_confidence = Column(Float, nullable=False, default=0.0)
    status = Column(String(32), nullable=False, default="pending")
    flags = Column(ARRAY(String), nullable=True, default=[])
    inspector_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    inspection_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    uploader_user = Column(String(128), nullable=True)
    county_id = Column(String(64), ForeignKey("counties.id"), nullable=True)
    vegetation = Column(Boolean, nullable=True)
    pole_material = Column(String(32), nullable=False, default="unknown")
    normalized_tag_candidate = Column(String(64), nullable=True, index=True)
    model_prediction_label = Column(String(128), nullable=True)
    model_prediction_confidence = Column(Float, nullable=False, default=0.0)
    model_prediction_source = Column(String(32), nullable=True)
    ocr_raw_text = Column(String(256), nullable=True)
    ocr_normalized_text = Column(String(128), nullable=True)
    ocr_confidence = Column(Float, nullable=False, default=0.0)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    asset = relationship("Asset", back_populates="inspections", foreign_keys=[asset_id])
    tags = relationship("ExtractedTag", back_populates="inspection", cascade="all, delete-orphan")
    attributes = relationship("AttributeDetection", back_populates="inspection", cascade="all, delete-orphan")
    validations = relationship("UserValidation", back_populates="inspection")
    flags_rel = relationship("Flag", back_populates="inspection", foreign_keys="Flag.inspection_id")

    __table_args__ = (Index("ix_inspections_asset_created", "asset_id", "created_at"),)


class Flag(Base):
    __tablename__ = "flags"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    asset_id = Column(UUID(as_uuid=False), ForeignKey("assets.id"), nullable=False, index=True)
    inspection_id = Column(UUID(as_uuid=False), ForeignKey("inspections.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="open")
    reason = Column(String(128), nullable=False, default="canonical_mismatch")
    mismatch_fields = Column(JSON, nullable=False, default=[])
    resolved_by = Column(String(128), nullable=True)
    resolution_note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    asset = relationship("Asset", back_populates="flags", foreign_keys=[asset_id])
    inspection = relationship("Inspection", back_populates="flags_rel", foreign_keys=[inspection_id])


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
    sap_work_order_id = Column(String(32), nullable=True)

    inspection = relationship("Inspection", back_populates="attributes")


class UserValidation(Base):
    __tablename__ = "user_validations"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    inspection_id = Column(UUID(as_uuid=False), ForeignKey("inspections.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True)
    action = Column(String(20), nullable=False)
    corrected_tag = Column(String(64), nullable=True)
    corrected_attributes = Column(JSON, nullable=True)
    validation_confidence = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    inspection = relationship("Inspection", back_populates="validations")

    __table_args__ = (UniqueConstraint("inspection_id", "user_id", name="uq_validation_per_user"),)


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
    role = Column(String(20), nullable=False, default="community")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class InspectionJob(Base):
    __tablename__ = "inspection_jobs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    inspection_id = Column(UUID(as_uuid=False), ForeignKey("inspections.id"), nullable=True)
    celery_task_id = Column(String(64), nullable=True)
    status = Column(String(20), nullable=False, default="queued")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
