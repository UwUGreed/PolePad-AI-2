from __future__ import annotations
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


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
    MANUAL_REVIEW = "manual_review"
    FLAGGED = "flagged"
    PROCESSED = "processed"


class ValidationAction(str, Enum):
    CONFIRM = "confirm"
    DISPUTE = "dispute"
    EDIT = "edit"


class AttributeClass(str, Enum):
    VEGETATION_CONTACT = "vegetation_contact"
    GUY_WIRE = "guy_wire"
    CROSSARM = "crossarm"
    TRANSFORMER = "transformer"
    SAFETY_EQUIPMENT = "safety_equipment"
    STRUCTURAL_DAMAGE = "structural_damage"
    SAFETY_EQUIPMENT_MISSING = "safety_equipment_missing"


class BoundingBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float
    width: float = 0
    height: float = 0

    def model_post_init(self, __context):
        self.width = self.x2 - self.x1
        self.height = self.y2 - self.y1


class GeoPoint(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None


class CVDetectRequest(BaseModel):
    image_b64: str
    image_id: str


class TagDetection(BaseModel):
    bounding_box: BoundingBox
    detection_confidence: float = Field(..., ge=0.0, le=1.0)


class AttributeDetection(BaseModel):
    class_label: AttributeClass
    confidence: float = Field(..., ge=0.0, le=1.0)
    bounding_box: BoundingBox
    is_safety_relevant: bool = False




class ModelDecision(BaseModel):
    label: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    source: str = "detection"
    class_index: Optional[int] = None
    bounding_box: Optional[BoundingBox] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class CVDetectResponse(BaseModel):
    image_id: str
    model_version: str
    tags: List[TagDetection] = Field(default_factory=list)
    attributes: List[AttributeDetection] = Field(default_factory=list)
    pole_material: str = "unknown"
    pole_material_confidence: float = 0.0
    processing_ms: int = 0
    flags: List[str] = Field(default_factory=list)
    primary_decision: Optional[ModelDecision] = None


class OCRExtractRequest(BaseModel):
    image_b64: str
    image_id: str
    original_bounding_box: Optional[BoundingBox] = None
    fallback_image_b64: Optional[str] = None


class CharacterConfidence(BaseModel):
    char: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    uncertain: bool = False
    position: int


class OCRExtractResponse(BaseModel):
    image_id: str
    model_version: str
    raw_string: str
    normalized_string: str
    character_confidences: List[CharacterConfidence]
    uncertain_positions: List[int] = Field(default_factory=list)
    mean_confidence: float
    preprocessing_applied: List[str] = Field(default_factory=list)
    processing_ms: int = 0
    original_bounding_box: Optional[BoundingBox] = None


class UploadResponse(BaseModel):
    job_id: str
    status: str
    poll_url: str


class InferenceResult(BaseModel):
    job_id: str
    status: str
    inspection_id: Optional[str] = None
    asset_id: Optional[str] = None
    model_versions: dict
    tags: List[OCRExtractResponse] = Field(default_factory=list)
    attributes: List[AttributeDetection] = Field(default_factory=list)
    pole_material: str = "unknown"
    overall_confidence: float = 0.0
    flags: List[str] = Field(default_factory=list)
    model_prediction_label: Optional[str] = None
    model_prediction_confidence: float = 0.0
    model_prediction_source: Optional[str] = None
    ocr_raw_text: Optional[str] = None
    ocr_normalized_text: Optional[str] = None
    ocr_confidence: float = 0.0
    primary_decision: Optional[ModelDecision] = None


class ValidationRequest(BaseModel):
    action: ValidationAction
    corrected_tag: Optional[str] = None
    corrected_attributes: Optional[dict] = None
    confidence: Optional[float] = None


class ValidationResponse(BaseModel):
    validation_id: str
    inspection_id: str
    new_consensus_score: float
    asset_status: str


class AssetSummary(BaseModel):
    id: str
    normalized_tag: str
    asset_type: str
    vegetation: Optional[bool] = None
    county_id: Optional[str] = None
    status: str
    consensus_score: float
    location: Optional[GeoPoint] = None


class InspectionSummary(BaseModel):
    id: str
    asset_id: Optional[str] = None
    normalized_tag_candidate: Optional[str] = None
    status: str
    pole_material: str
    vegetation: Optional[bool] = None
    county_id: Optional[str] = None
    created_at: datetime


class FlagSummary(BaseModel):
    id: str
    asset_id: str
    inspection_id: str
    status: str
    reason: str
    mismatch_fields: List[str] = Field(default_factory=list)
    created_at: datetime


class InspectionEditRequest(BaseModel):
    normalized_tag: Optional[str] = None
    pole_material: Optional[str] = None
    vegetation: Optional[bool] = None
    county_id: Optional[str] = None


class ReviewerActionResponse(BaseModel):
    inspection_id: str
    status: str
    asset_id: Optional[str] = None
    flag_id: Optional[str] = None

