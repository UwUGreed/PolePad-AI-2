"""
packages/shared-types/schemas.py

Single source of truth for all data contracts.
Used by: api, cv-service, ocr-service, comms package.
TypeScript equivalents auto-generated via scripts/gen_ts_types.py
"""

from __future__ import annotations
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field, UUID4
from datetime import datetime


# ─────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────

class AssetStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    VERIFIED = "verified"
    DISPUTED = "disputed"
    DECOMMISSIONED = "decommissioned"

class InspectionStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"
    NO_TAG_DETECTED = "no_tag_detected"
    LOW_QUALITY = "low_quality"

class ValidationAction(str, Enum):
    CONFIRM = "confirm"
    DISPUTE = "dispute"
    EDIT = "edit"

class AssetType(str, Enum):
    POLE_WOOD = "pole_wood"
    POLE_STEEL = "pole_steel"
    POLE_CONCRETE = "pole_concrete"
    CROSSARM = "crossarm"
    TRANSFORMER = "transformer"
    UNKNOWN = "unknown"

class AttributeClass(str, Enum):
    VEGETATION_CONTACT = "vegetation_contact"
    GUY_WIRE = "guy_wire"
    CROSSARM = "crossarm"
    TRANSFORMER = "transformer"
    SAFETY_EQUIPMENT = "safety_equipment"
    STRUCTURAL_DAMAGE = "structural_damage"
    SAFETY_EQUIPMENT_MISSING = "safety_equipment_missing"


# ─────────────────────────────────────────────────────────────
# Geometry
# ─────────────────────────────────────────────────────────────

class BoundingBox(BaseModel):
    x1: float = Field(..., description="Left pixel coordinate")
    y1: float = Field(..., description="Top pixel coordinate")
    x2: float = Field(..., description="Right pixel coordinate")
    y2: float = Field(..., description="Bottom pixel coordinate")
    width: float = Field(default=0)
    height: float = Field(default=0)

    def model_post_init(self, __context):
        object.__setattr__(self, "width", self.x2 - self.x1)
        object.__setattr__(self, "height", self.y2 - self.y1)

class GeoPoint(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None


# ─────────────────────────────────────────────────────────────
# CV Service Contracts
# ─────────────────────────────────────────────────────────────

class CVDetectRequest(BaseModel):
    """POST /detect on cv-service"""
    image_b64: str = Field(..., description="Base64-encoded image bytes")
    image_id: str = Field(..., description="Job or image UUID for tracing")

class TagDetection(BaseModel):
    """A single detected asset tag region"""
    bounding_box: BoundingBox
    detection_confidence: float = Field(..., ge=0.0, le=1.0)

class AttributeDetection(BaseModel):
    """A single infrastructure attribute detection"""
    class_label: AttributeClass
    confidence: float = Field(..., ge=0.0, le=1.0)
    bounding_box: BoundingBox
    is_safety_relevant: bool = False

class CVDetectResponse(BaseModel):
    """Response from cv-service /detect"""
    image_id: str
    model_version: str
    tags: List[TagDetection] = Field(default_factory=list)
    attributes: List[AttributeDetection] = Field(default_factory=list)
    processing_ms: int = 0
    flags: List[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# OCR Service Contracts
# ─────────────────────────────────────────────────────────────

class OCRExtractRequest(BaseModel):
    """POST /extract on ocr-service"""
    image_b64: str = Field(..., description="Base64-encoded cropped tag image")
    image_id: str
    original_bounding_box: BoundingBox = Field(..., description="Position in original image for reference")

class CharacterConfidence(BaseModel):
    char: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    uncertain: bool = False
    position: int

class OCRExtractResponse(BaseModel):
    """Response from ocr-service /extract"""
    image_id: str
    model_version: str
    raw_string: str
    normalized_string: str
    character_confidences: List[CharacterConfidence]
    uncertain_positions: List[int] = Field(default_factory=list)
    mean_confidence: float
    preprocessing_applied: List[str] = Field(default_factory=list)
    processing_ms: int = 0


# ─────────────────────────────────────────────────────────────
# API ↔ Frontend Contracts
# ─────────────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    """Returned immediately after image upload"""
    job_id: str
    status: InspectionStatus
    poll_url: str

class InferenceResult(BaseModel):
    """Full inference result — returned when job is complete"""
    job_id: str
    status: InspectionStatus
    inspection_id: Optional[str] = None
    asset_id: Optional[str] = None
    model_versions: dict = Field(default_factory=dict)
    tags: List[OCRExtractResponse] = Field(default_factory=list)
    attributes: List[AttributeDetection] = Field(default_factory=list)
    overall_confidence: float = 0.0
    flags: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    created_at: Optional[datetime] = None

class ValidationRequest(BaseModel):
    """POST /inspections/{id}/validate"""
    action: ValidationAction
    corrected_tag: Optional[str] = Field(None, max_length=64)
    corrected_attributes: Optional[List[dict]] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)

class ValidationResponse(BaseModel):
    validation_id: str
    inspection_id: str
    new_consensus_score: float
    asset_status: AssetStatus

class AssetSummary(BaseModel):
    """Lightweight asset for list views"""
    id: str
    normalized_tag: str
    asset_type: AssetType
    status: AssetStatus
    consensus_score: float
    location: Optional[GeoPoint] = None
    last_inspection_at: Optional[datetime] = None
    inspection_count: int = 0

class AssetDetail(AssetSummary):
    """Full asset with inspection history"""
    inspections: List[InferenceResult] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# Integration Contracts (Dominion Stack)
# ─────────────────────────────────────────────────────────────

class ArcGISFeature(BaseModel):
    """Mapped to ArcGIS Feature Service point layer"""
    geometry: dict  # {"x": lon, "y": lat, "spatialReference": {"wkid": 4326}}
    attributes: dict  # all asset fields

class PIEventData(BaseModel):
    """Mapped to AVEVA PI Event Frame"""
    element_path: str  # e.g. \\AF_SERVER\PolePad\Poles\TP-1042-A
    event_name: str
    start_time: datetime
    attributes: dict  # PI tag name → value

class SAPWorkOrderRequest(BaseModel):
    """SAP PM work order creation payload"""
    plant: str
    order_type: str
    short_description: str
    equipment_id: str  # normalized_tag as functional location
    priority: str = "3"
    long_text: str = ""


# ─────────────────────────────────────────────────────────────
# Standard Error Envelope
# ─────────────────────────────────────────────────────────────

class APIError(BaseModel):
    code: str
    message: str
    request_id: Optional[str] = None
    retryable: bool = False
    details: dict = Field(default_factory=dict)

class ErrorResponse(BaseModel):
    error: APIError
