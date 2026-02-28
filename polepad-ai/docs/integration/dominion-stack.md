# Dominion Energy Stack Integration Guide

PolePad AI is designed to plug into Dominion's existing infrastructure with **zero code changes**. All integrations are enabled via environment variables.

---

## 1. Esri ArcGIS Enterprise

**What happens:** Every confirmed asset is pushed to your ArcGIS Feature Service as a point geometry. Field teams see PolePad inspections directly in ArcGIS Field Maps or ArcGIS Pro.

**Prerequisites:**
- ArcGIS Enterprise 10.9+ or ArcGIS Online
- A Feature Layer in a Feature Service with the following fields:
  - `tag_id` (String, 64)
  - `confidence` (Double)
  - `status` (String, 20)
  - `last_inspected` (Date)
  - `asset_type` (String, 32)

**Feature Service Setup:**
```
1. Open ArcGIS Pro or ArcGIS Online
2. Create a new Feature Class (Point, WGS84 / WKID 4326)
3. Add the fields above
4. Publish as Feature Service
5. Copy the Feature Service URL (ends in /FeatureServer/0)
```

**Enable in PolePad:**
```bash
# In .env:
ARCGIS_ENABLED=true
ARCGIS_BASE_URL=https://your-arcgis-server.company.com/arcgis
ARCGIS_USERNAME=svc_polepad
ARCGIS_PASSWORD=your_service_account_password
ARCGIS_FEATURE_SERVICE_URL=https://your-arcgis-server.company.com/arcgis/rest/services/PoleAssets/FeatureServer/0
```

**What gets pushed on each confirmed asset:**
```json
{
  "geometry": { "x": -81.0456, "y": 33.9988, "spatialReference": { "wkid": 4326 } },
  "attributes": {
    "tag_id": "TP-1042-A",
    "confidence": 0.94,
    "status": "verified",
    "asset_type": "pole_wood",
    "last_inspected": "2025-02-28T14:30:00Z"
  }
}
```

---

## 2. AVEVA PI System

**What happens:** Each inspection creates a PI Event Frame. Asset attributes (vegetation contact, structural damage, etc.) write values to PI tags. Engineers can trend pole condition over time in PI Vision.

**Prerequisites:**
- PI Web API 2019 SP1+ enabled on your PI Server
- An AF Database and Element Template called `PoleInspection`
- PI tags following naming convention: `{TAG_ID}.{ATTRIBUTE}` (e.g., `TP-1042-A.vegetation_contact`)

**AF Element Template Setup:**
```
Template Name: PoleInspection
Attributes:
  - normalized_tag (String)
  - confidence (Single)
  - status (String)
  - vegetation_contact (Boolean)
  - structural_damage (Boolean)
  - last_inspection_date (DateTime)
```

**Enable in PolePad:**
```bash
PI_SYSTEM_ENABLED=true
PI_BASE_URL=https://your-pi-server.company.com/piwebapi
PI_USERNAME=svc_polepad
PI_PASSWORD=your_password
PI_DATABASE=PoleAssets
PI_ASSET_SERVER=YourAFServer
```

**What gets written per inspection:**
- New PI Event Frame: `Inspection_TP-1042-A_2025-02-28T14:30:00`
- Attribute values updated on the element

---

## 3. SAP / EpochField Work Orders

**What happens:** When PolePad detects a safety-relevant attribute (vegetation contact, structural damage, missing safety equipment), it automatically creates an SAP PM01 work order, which flows into EpochField's mobile work queue for field crews.

**Prerequisites:**
- SAP S/4HANA with PM module active
- OAuth 2.0 client credentials configured for PolePad
- Functional locations configured matching pole tag format

**Configure trigger classes:**
```bash
SAP_ENABLED=true
SAP_BASE_URL=https://your-sap-server.company.com/api
SAP_CLIENT_ID=POLEPAD_CLIENT
SAP_CLIENT_SECRET=your_client_secret
SAP_PLANT_CODE=UTIL
SAP_TRIGGER_CLASSES=vegetation_contact,structural_damage,safety_equipment_missing
```

**Work Order payload (PM01):**
```json
{
  "Plant": "UTIL",
  "OrderType": "PM01",
  "ShortDescription": "[PolePad] vegetation_contact: TP-1042-A",
  "FunctionalLocation": "TP-1042-A",
  "Priority": "2",
  "LongText": "PolePad AI detected vegetation_contact at pole TP-1042-A with 87% confidence. Image: s3://polepad-images/inspections/..."
}
```

---

## Testing Integrations

```bash
# Test ArcGIS connection
curl -X POST http://localhost:8000/api/v1/integrations/test/arcgis

# Test PI System connection  
curl -X POST http://localhost:8000/api/v1/integrations/test/pi

# Test SAP connection
curl -X POST http://localhost:8000/api/v1/integrations/test/sap
```

---

## Disabling Integrations

Set the `_ENABLED` flag to `false` (or remove the variable). The system runs fully without any integrations enabled. This is the default for local demo mode.
