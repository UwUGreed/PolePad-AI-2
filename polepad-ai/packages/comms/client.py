"""
packages/comms/client.py

Pre-coded communication layer between all PolePad services.
This is the "wiring" — import and call, don't rewrite.

Usage in api/:
    from packages.comms.client import ServiceBus
    bus = ServiceBus()
    cv_result = await bus.cv.detect(image_bytes, job_id)
    ocr_result = await bus.ocr.extract(cropped_bytes, job_id, bbox)
"""

from __future__ import annotations
import base64
import logging
import time
from typing import Optional
import httpx

# Import shared schemas — single source of truth
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared-types'))
from schemas import (
    CVDetectRequest, CVDetectResponse,
    OCRExtractRequest, OCRExtractResponse,
    BoundingBox
)

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Base HTTP Client with retry + error handling
# ─────────────────────────────────────────────────────────────

class ServiceClient:
    def __init__(self, base_url: str, service_name: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.service_name = service_name
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers={"User-Agent": "polepad-api/1.0"}
            )
        return self._client

    async def post(self, path: str, payload: dict, retries: int = 2) -> dict:
        client = await self._get_client()
        last_exc = None
        for attempt in range(retries + 1):
            try:
                t0 = time.monotonic()
                resp = await client.post(path, json=payload)
                elapsed = int((time.monotonic() - t0) * 1000)
                log.debug(f"[{self.service_name}] POST {path} → {resp.status_code} ({elapsed}ms)")
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                log.error(f"[{self.service_name}] HTTP {e.response.status_code}: {e.response.text}")
                raise ServiceError(
                    service=self.service_name,
                    code=f"HTTP_{e.response.status_code}",
                    message=e.response.text,
                    retryable=e.response.status_code >= 500
                )
            except httpx.TimeoutException as e:
                last_exc = e
                log.warning(f"[{self.service_name}] Timeout (attempt {attempt+1}/{retries+1})")
                if attempt < retries:
                    await asyncio.sleep(1.0 * (attempt + 1))
            except httpx.ConnectError as e:
                raise ServiceError(
                    service=self.service_name,
                    code="SERVICE_UNAVAILABLE",
                    message=f"Cannot reach {self.base_url}",
                    retryable=True
                )
        raise ServiceError(
            service=self.service_name,
            code="TIMEOUT",
            message=f"Service did not respond after {retries+1} attempts",
            retryable=True
        )

    async def get(self, path: str) -> dict:
        client = await self._get_client()
        resp = await client.get(path)
        resp.raise_for_status()
        return resp.json()

    async def health(self) -> bool:
        try:
            result = await self.get("/health")
            return result.get("status") == "ok"
        except Exception:
            return False

    async def close(self):
        if self._client:
            await self._client.aclose()


class ServiceError(Exception):
    def __init__(self, service: str, code: str, message: str, retryable: bool = False):
        self.service = service
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(f"[{service}] {code}: {message}")


# ─────────────────────────────────────────────────────────────
# CV Service Client
# ─────────────────────────────────────────────────────────────

class CVServiceClient(ServiceClient):
    """
    Typed client for cv-service.
    Wraps raw HTTP with schema validation.
    """

    async def detect(self, image_bytes: bytes, image_id: str) -> CVDetectResponse:
        """
        Send image to cv-service for YOLO detection.
        Returns typed CVDetectResponse with tags + attributes.
        """
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        request = CVDetectRequest(image_b64=image_b64, image_id=image_id)
        raw = await self.post("/detect", request.model_dump())
        return CVDetectResponse(**raw)

    async def batch_detect(self, images: list[tuple[bytes, str]]) -> list[CVDetectResponse]:
        """
        Detect multiple images. Runs sequentially (upgrade to /batch endpoint later).
        """
        results = []
        for image_bytes, image_id in images:
            result = await self.detect(image_bytes, image_id)
            results.append(result)
        return results


# ─────────────────────────────────────────────────────────────
# OCR Service Client
# ─────────────────────────────────────────────────────────────

class OCRServiceClient(ServiceClient):
    """
    Typed client for ocr-service.
    """

    async def extract(
        self,
        cropped_image_bytes: bytes,
        image_id: str,
        original_bbox: BoundingBox
    ) -> OCRExtractResponse:
        """
        Send cropped tag image to ocr-service.
        Returns typed OCRExtractResponse with character-level confidence.
        """
        image_b64 = base64.b64encode(cropped_image_bytes).decode("utf-8")
        request = OCRExtractRequest(
            image_b64=image_b64,
            image_id=image_id,
            original_bounding_box=original_bbox
        )
        raw = await self.post("/extract", request.model_dump())
        return OCRExtractResponse(**raw)

    async def extract_all(
        self,
        crops: list[tuple[bytes, str, BoundingBox]]
    ) -> list[OCRExtractResponse]:
        """
        Extract text from multiple tag crops.
        """
        results = []
        for img_bytes, img_id, bbox in crops:
            result = await self.extract(img_bytes, img_id, bbox)
            results.append(result)
        return results


# ─────────────────────────────────────────────────────────────
# Integration Clients (Dominion Stack)
# ─────────────────────────────────────────────────────────────

class ArcGISClient(ServiceClient):
    """
    Client for Esri ArcGIS Enterprise Feature Service.
    Pushes confirmed assets as GIS features.
    """
    def __init__(self, base_url: str, username: str, password: str, feature_service_url: str):
        super().__init__(base_url, "arcgis")
        self.username = username
        self.password = password
        self.feature_service_url = feature_service_url
        self._token: Optional[str] = None
        self._token_expiry: float = 0

    async def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry:
            return self._token
        client = await self._get_client()
        resp = await client.post("/tokens/generateToken", data={
            "username": self.username,
            "password": self.password,
            "client": "requestip",
            "expiration": 60,
            "f": "json"
        })
        data = resp.json()
        self._token = data["token"]
        self._token_expiry = time.time() + 3500
        return self._token

    async def push_asset(self, normalized_tag: str, lat: float, lon: float, attributes: dict) -> bool:
        """Push a confirmed asset to ArcGIS Feature Service"""
        if not all([lat, lon]):
            log.warning(f"[arcgis] Skipping {normalized_tag} — no GPS coordinates")
            return False
        token = await self._get_token()
        feature = {
            "geometry": {"x": lon, "y": lat, "spatialReference": {"wkid": 4326}},
            "attributes": {"tag_id": normalized_tag, **attributes}
        }
        client = await self._get_client()
        resp = await client.post(
            f"{self.feature_service_url}/addFeatures",
            data={"features": str([feature]), "f": "json", "token": token}
        )
        result = resp.json()
        success = not result.get("addResults", [{}])[0].get("error")
        if not success:
            log.error(f"[arcgis] Failed to push {normalized_tag}: {result}")
        return success

    async def update_asset(self, object_id: int, attributes: dict) -> bool:
        """Update an existing feature"""
        token = await self._get_token()
        feature = {"attributes": {"OBJECTID": object_id, **attributes}}
        client = await self._get_client()
        resp = await client.post(
            f"{self.feature_service_url}/updateFeatures",
            data={"features": str([feature]), "f": "json", "token": token}
        )
        return not resp.json().get("updateResults", [{}])[0].get("error")


class PISystemClient(ServiceClient):
    """
    Client for AVEVA PI System Web API.
    Writes inspection events and attribute values.
    """
    def __init__(self, base_url: str, username: str, password: str, database: str):
        super().__init__(base_url, "pi-system")
        self.database = database
        self.auth = (username, password)

    async def write_inspection_event(
        self,
        normalized_tag: str,
        event_data: dict,
        start_time: str
    ) -> bool:
        """Create PI Event Frame for an inspection"""
        path = f"/assetdatabases/{self.database}/eventframes"
        payload = {
            "Name": f"Inspection_{normalized_tag}_{start_time}",
            "TemplateName": "PoleInspection",
            "StartTime": start_time,
            "Values": event_data
        }
        try:
            await self.post(path, payload)
            return True
        except ServiceError as e:
            log.error(f"[pi-system] Failed to write event for {normalized_tag}: {e}")
            return False

    async def update_asset_attribute(
        self,
        normalized_tag: str,
        attribute_name: str,
        value
    ) -> bool:
        """Update a PI attribute value for an asset element"""
        path = f"/elements/path[\\\\{self.database}\\Poles\\{normalized_tag}]/attributes/{attribute_name}/value"
        payload = {"Value": value, "Timestamp": "*"}
        try:
            await self.post(path, payload)
            return True
        except ServiceError as e:
            log.warning(f"[pi-system] Attribute update failed for {normalized_tag}.{attribute_name}: {e}")
            return False


class SAPClient(ServiceClient):
    """
    Client for SAP / EpochField work order creation.
    Triggered by safety-relevant attribute detections.
    """
    def __init__(self, base_url: str, client_id: str, client_secret: str, plant: str):
        super().__init__(base_url, "sap")
        self.client_id = client_id
        self.client_secret = client_secret
        self.plant = plant
        self._access_token: Optional[str] = None
        self._token_expiry: float = 0

    async def _get_access_token(self) -> str:
        if self._access_token and time.time() < self._token_expiry:
            return self._access_token
        client = await self._get_client()
        resp = await client.post("/oauth/token", data={
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret
        })
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expiry = time.time() + data.get("expires_in", 3600) - 60
        return self._access_token

    async def create_work_order(
        self,
        normalized_tag: str,
        attribute_class: str,
        description: str,
        priority: str = "3"
    ) -> Optional[str]:
        """
        Create SAP PM work order for a safety-relevant finding.
        Returns work order number or None on failure.
        """
        token = await self._get_access_token()
        payload = {
            "Plant": self.plant,
            "OrderType": "PM01",
            "ShortDescription": f"[PolePad] {attribute_class}: {normalized_tag}",
            "FunctionalLocation": normalized_tag,
            "Priority": priority,
            "LongText": description,
            "UserStatus": "NOCO"  # Not confirmed
        }
        client = await self._get_client()
        try:
            resp = await client.post(
                "/workorders",
                json=payload,
                headers={"Authorization": f"Bearer {token}"}
            )
            resp.raise_for_status()
            order_number = resp.json().get("OrderNumber")
            log.info(f"[sap] Created work order {order_number} for {normalized_tag}")
            return order_number
        except Exception as e:
            log.error(f"[sap] Work order creation failed: {e}")
            return None


# ─────────────────────────────────────────────────────────────
# ServiceBus — unified access point used by api/
# ─────────────────────────────────────────────────────────────

class ServiceBus:
    """
    Single import for all inter-service communication.

    Usage:
        bus = ServiceBus.from_env()
        cv_result = await bus.cv.detect(image_bytes, job_id)
        ocr_result = await bus.ocr.extract(crop, job_id, bbox)
        await bus.arcgis.push_asset(tag, lat, lon, attrs)   # if enabled
    """

    def __init__(
        self,
        cv_url: str,
        ocr_url: str,
        arcgis_config: Optional[dict] = None,
        pi_config: Optional[dict] = None,
        sap_config: Optional[dict] = None,
    ):
        self.cv = CVServiceClient(cv_url, "cv-service")
        self.ocr = OCRServiceClient(ocr_url, "ocr-service")

        # Integration clients — instantiated only if configured
        self.arcgis: Optional[ArcGISClient] = None
        self.pi: Optional[PISystemClient] = None
        self.sap: Optional[SAPClient] = None

        if arcgis_config:
            self.arcgis = ArcGISClient(**arcgis_config)
            log.info("[comms] ArcGIS integration enabled")

        if pi_config:
            self.pi = PISystemClient(**pi_config)
            log.info("[comms] PI System integration enabled")

        if sap_config:
            self.sap = SAPClient(**sap_config)
            log.info("[comms] SAP integration enabled")

    @classmethod
    def from_env(cls) -> ServiceBus:
        """Create ServiceBus from environment variables (used in production)"""
        import os
        arcgis = None
        if os.getenv("ARCGIS_ENABLED", "false").lower() == "true":
            arcgis = {
                "base_url": os.environ["ARCGIS_BASE_URL"],
                "username": os.environ["ARCGIS_USERNAME"],
                "password": os.environ["ARCGIS_PASSWORD"],
                "feature_service_url": os.environ["ARCGIS_FEATURE_SERVICE_URL"],
            }
        pi = None
        if os.getenv("PI_SYSTEM_ENABLED", "false").lower() == "true":
            pi = {
                "base_url": os.environ["PI_BASE_URL"],
                "username": os.environ["PI_USERNAME"],
                "password": os.environ["PI_PASSWORD"],
                "database": os.environ["PI_DATABASE"],
            }
        sap = None
        if os.getenv("SAP_ENABLED", "false").lower() == "true":
            sap = {
                "base_url": os.environ["SAP_BASE_URL"],
                "client_id": os.environ["SAP_CLIENT_ID"],
                "client_secret": os.environ["SAP_CLIENT_SECRET"],
                "plant": os.getenv("SAP_PLANT_CODE", "UTIL"),
            }
        return cls(
            cv_url=os.environ["CV_SERVICE_URL"],
            ocr_url=os.environ["OCR_SERVICE_URL"],
            arcgis_config=arcgis,
            pi_config=pi,
            sap_config=sap,
        )

    async def health_check(self) -> dict:
        """Check all connected services"""
        return {
            "cv": await self.cv.health(),
            "ocr": await self.ocr.health(),
            "arcgis": await self.arcgis.health() if self.arcgis else "disabled",
            "pi_system": await self.pi.health() if self.pi else "disabled",
            "sap": await self.sap.health() if self.sap else "disabled",
        }

    async def close(self):
        """Cleanup all HTTP clients"""
        await self.cv.close()
        await self.ocr.close()
        if self.arcgis:
            await self.arcgis.close()
        if self.pi:
            await self.pi.close()
        if self.sap:
            await self.sap.close()


# ─────────────────────────────────────────────────────────────
# Consensus Score Calculator
# ─────────────────────────────────────────────────────────────

def calculate_consensus_score(
    ai_confidence: float,
    confirm_count: int,
    dispute_count: int,
    edit_count: int = 0
) -> tuple[float, str]:
    """
    Returns (composite_score, asset_status)

    Formula:
      - AI weight decreases as human validation accumulates
      - Human signal = ratio of confirms weighted by validation volume
    """
    total_validations = confirm_count + dispute_count + edit_count

    # AI weight decreases with more human input (min 10%)
    ai_weight = max(0.10, 0.40 - (total_validations * 0.05))
    human_weight = 1.0 - ai_weight

    # Human signal: confirm ratio × volume saturation (caps at 5 validators)
    if total_validations > 0:
        confirm_ratio = confirm_count / (confirm_count + dispute_count + edit_count)
        volume_factor = min(1.0, total_validations / 5.0)
        human_signal = confirm_ratio * volume_factor
    else:
        human_signal = 0.0

    composite = (ai_weight * ai_confidence) + (human_weight * human_signal)
    composite = round(min(1.0, max(0.0, composite)), 4)

    # Status logic
    if dispute_count >= 3:
        status = "disputed"
    elif composite >= 0.90 and confirm_count >= 3:
        status = "verified"
    elif dispute_count >= 1:
        status = "disputed"
    elif composite > 0:
        status = "active"
    else:
        status = "pending"

    return composite, status
