🔌 PolePad AI
Crowd-Powered Infrastructure Verification
Computer Vision · OCR · Community Consensus · Dominion Energy Stack Compatible

What It Does
PolePad AI lets field workers photograph utility poles. The system automatically:

Detects the asset tag (pole ID number) using YOLOv8n
Reads the tag characters using Tesseract OCR with multi-pass preprocessing (highlights uncertain characters in amber)
Detects infrastructure attributes (vegetation contact, guy wires, transformers, etc.) using YOLOv8
Stores everything in a local PostgreSQL database
Lets the community confirm or dispute the AI's reading to build confidence over time

Built to feed directly into Dominion Energy's existing stack: Esri ArcGIS Enterprise, AVEVA PI System, SAP, and EpochField.

🚀 Quick Start (Fedora Podman + Docker)
From a fresh clone, run from polepad-ai/:
bash./scripts/dev-up.sh
The script auto-detects the frontend folder, uses podman-compose when available (or docker compose as fallback), starts the full stack, and prints health checks.
Then open http://localhost:3000 in your browser.
Manual commands
bash# Fedora / rootless Podman
podman-compose up -d --build

# Docker Compose
docker compose up -d --build
That's it. Everything runs locally — no cloud account, no API keys required.

Demo credentials: demo@polepad.ai / demo1234


📸 Try It Out

Go to http://localhost:3000
Click "New Inspection"
Upload any photo of a utility pole (or use the samples in docs/sample-images/)
Watch the AI detect the tag, read the number, and flag attributes
Click Confirm or Dispute on the result
See the confidence score update in real time


Architecture Overview
┌─────────────────────────────────────────────────────────────┐
│  Browser  http://localhost:3000                              │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│  FastAPI Backend  :8000                                      │
│  (api/)  ← orchestrates all services via comms/             │
└──────┬─────────────────────────────┬────────────────────────┘
       │                             │
┌──────▼──────┐             ┌────────▼────────┐
│ cv-service  │             │  ocr-service    │
│ :8001       │             │  :8002          │
│ YOLOv8n     │             │  Tesseract OCR  │
└──────┬──────┘             └────────┬────────┘
       │          results            │
       └────────────┬────────────────┘
                    │
┌───────────────────▼─────────────────────────────────────────┐
│  PostgreSQL  :5432   +   Redis  :6379                        │
│  (local Docker)                                              │
└─────────────────────────────────────────────────────────────┘
Integration Adapters (Production)
PolePad API ──► Esri ArcGIS Enterprise  (REST Feature Service)
            ──► AVEVA PI System         (AF SDK / REST)
            ──► SAP via EpochField      (Work Order sync)

Project Structure
polepad-ai/
├── apps/
│   ├── api/            # FastAPI backend — main brain
│   ├── cv-service/     # YOLOv8 detection microservice
│   ├── ocr-service/    # Tesseract OCR extraction microservice
│   └── web/            # Next.js frontend
├── packages/
│   ├── shared_types/   # Pydantic + TypeScript schemas (source of truth)
│   ├── db/             # SQLAlchemy models + Alembic migrations
│   ├── config/         # Env/config loader used by all services
│   └── comms/          # Pre-coded inter-service HTTP client (the "wiring")
├── ml/
│   ├── training/       # YOLO training scripts
│   ├── datasets/       # Dataset structure + download scripts
│   └── models/         # Versioned model weights
├── infra/
│   └── docker/         # Per-service Dockerfiles
├── docs/
│   ├── sample-images/  # Demo pole images for judges
│   └── integration/    # Dominion stack integration guides
├── scripts/            # Dev utilities, DB seed, model download
│   └── yolov8n.pt      # ← YOLO base weights (used by cv-service in demo mode)
├── docker-compose.yml  # ← THE MAIN ENTRY POINT
└── .env.example        # All config variables documented

ML Models
YOLO Detection (CV Service)
The primary model weights are located at:
scripts/yolov8n.pt
This file is the YOLOv8n pretrained checkpoint used by default in demo mode. The cv-service Dockerfile copies it to /app/yolov8n.pt inside the container:
dockerfileCOPY scripts/yolov8n.pt /app/yolov8n.pt
The docker-compose.yml sets these environment variables for the cv-service:
yamlMODEL_PATH: /app/yolov8n.pt
MODEL_VERSION: demo-v1.0.0
POLE_MATERIAL_MODEL_PATH: /app/yolov8n.pt    # same checkpoint used for pole material classification
POLE_MATERIAL_MODEL_VERSION: demo-pole-material-v1
The CV service detects 8 object classes:
Class IDLabel0asset_tag1crossarm2vegetation_contact3guy_wire4transformer5safety_equipment6structural_damage7safety_equipment_missing
Safety-relevant detections (vegetation_contact, structural_damage, safety_equipment_missing) can auto-create SAP work orders when the SAP integration is enabled.
OCR Service
The OCR service uses Tesseract OCR (via pytesseract) with a multi-pass pipeline:

Grayscale conversion → Gaussian blur → Adaptive threshold → 3× upscale
Multiple PSM modes tested (7, 8, 6) across binary and grayscale variants
Best candidate selected by a scoring function that rewards alphanumeric mix and length
Characters below the OCR_UNCERTAINTY_THRESHOLD (default 0.75) are flagged uncertain and shown in amber in the UI
Whitelist: ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_/.


Configuration
.env is optional for local compose startup; the default stack works out-of-the-box without creating it.
If you want to override defaults, copy .env.example to .env:
bashcp .env.example .env
Key variables:
VariableDefaultDescriptionDATABASE_URLpostgresql://...@postgres:5432/polepadPostgres connectionREDIS_URLredis://redis:6379Redis for job queueCV_SERVICE_URLhttp://cv-service:8001Internal CV serviceOCR_SERVICE_URLhttp://ocr-service:8002Internal OCR serviceMODEL_PATH/app/yolov8n.ptPath to YOLO weights inside containerMODEL_VERSIONdemo-v1.0.0CV model version stringDETECTION_CONFIDENCE_THRESHOLD0.45YOLO detection threshold (0.0–1.0)OCR_UNCERTAINTY_THRESHOLD0.75Character confidence below this = amberIMAGE_STORAGE_BACKENDlocallocal or s3LOCAL_IMAGE_DIR/data/imagesImage storage path (local mode)S3_ENABLEDfalseSet true + add AWS creds for S3ARCGIS_ENABLEDfalseSet true + add ArcGIS credsPI_SYSTEM_ENABLEDfalseSet true + add PI System URLSAP_ENABLEDfalseSet true + add SAP endpointNEXT_PUBLIC_API_URLhttp://localhost:8000Frontend API base URLALLOWED_ORIGINShttp://localhost:3000API CORS allow-list

Dominion Energy Integration
All integrations are opt-in via env flags. The system runs fully without them.
ArcGIS Enterprise
bashARCGIS_ENABLED=true
ARCGIS_BASE_URL=https://your-arcgis-server/arcgis
ARCGIS_USERNAME=your_user
ARCGIS_PASSWORD=your_pass
ARCGIS_FEATURE_SERVICE_URL=.../FeatureServer/0
When enabled, every confirmed asset is pushed to your ArcGIS Feature Service as a point geometry with all attributes.
AVEVA PI System
bashPI_SYSTEM_ENABLED=true
PI_BASE_URL=https://your-pi-server/piwebapi
PI_USERNAME=your_user
PI_PASSWORD=your_pass
PI_DATABASE=your_af_database
When enabled, inspection events are written as PI Events and asset attributes update PI tags.
SAP / EpochField
bashSAP_ENABLED=true
SAP_BASE_URL=https://your-sap-server/api
SAP_CLIENT_ID=your_client_id
SAP_CLIENT_SECRET=your_client_secret
SAP_TRIGGER_CLASSES=vegetation_contact,structural_damage,safety_equipment_missing
When enabled, high-severity attribute detections auto-create SAP PM01 work orders via EpochField.
See docs/integration/dominion-stack.md for full setup guides.

Development
Run Individual Services
bash# Just the database
docker compose up postgres redis

# Backend API only (with hot reload)
cd apps/api
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# CV service
cd apps/cv-service
pip install -r requirements.txt
uvicorn main:app --reload --port 8001

# OCR service
cd apps/ocr-service
pip install -r requirements.txt
uvicorn main:app --reload --port 8002

# Frontend
cd apps/web
npm install && npm run dev

Note: The OCR service requires Tesseract to be installed on your host machine:
bash# Fedora/RHEL
sudo dnf install tesseract tesseract-langpack-eng
# Ubuntu/Debian
sudo apt-get install tesseract-ocr tesseract-ocr-eng
The Dockerfile handles this automatically for containerized runs.

API Documentation

Swagger UI: http://localhost:8000/docs
ReDoc: http://localhost:8000/redoc

Database
bash# Run migrations
cd packages/db
alembic upgrade head

# Seed demo data (creates 3 demo assets + demo user)
python scripts/seed_demo.py

# Connect directly
docker exec -it polepad-postgres psql -U polepad -d polepad
Train Your Own Model
bashcd ml/training
pip install -r requirements.txt
python train.py --data ../datasets/poles-v1/dataset.yaml --epochs 100
After training, update the model path:
bashcp runs/detect/train/weights/best.pt ml/models/poles-v2/best.pt
Then update docker-compose.yml or your .env:
MODEL_PATH=/app/models/poles-v2/best.pt
MODEL_VERSION=yolov8-poles-v2.0.0
See ml/training/README.md for a full training guide including annotation tools and dataset structure.

API Quick Reference
MethodEndpointDescriptionPOST/api/v1/inspections/uploadUpload image, start inferenceGET/api/v1/jobs/{job_id}Poll job status + get resultsPOST/api/v1/inspections/{id}/validateSubmit confirm/dispute/editPOST/api/v1/inspections/{id}/editReviewer corrects fieldsPOST/api/v1/inspections/{id}/promotePromote flagged inspection to canonicalPOST/api/v1/inspections/{id}/dismissDismiss a flagged inspectionGET/api/v1/inspectionsList inspections (optional ?status= filter)GET/api/v1/assetsList all assets with consensus scoresGET/api/v1/flagsList open flags (?status=open|resolved|dismissed)POST/auth/loginGet JWT token
Full schema at http://localhost:8000/docs

Tech Stack
LayerTechnologyML DetectionYOLOv8n (Ultralytics 8.2.0)OCRTesseract OCR + pytesseract 0.3.10BackendFastAPI 0.111.0 + Python 3.11DatabasePostgreSQL 16Job QueueCelery + Redis (BackgroundTasks used in demo mode)FrontendNext.js 14ContainersDocker / Podman + ComposeGISEsri ArcGIS REST APITime SeriesAVEVA PI Web APIField ServiceSAP/EpochField REST

Inspection Pipeline
When an image is uploaded, the API runs this pipeline in a FastAPI BackgroundTask:
Upload image
    │
    ▼
YOLOv8n detection (cv-service)
    │  ├── Detect asset_tag bounding box
    │  ├── Detect attributes (vegetation, damage, etc.)
    │  └── Classify pole material (wood / metal / unknown)
    │
    ▼
Crop tag region → Tesseract OCR (ocr-service)
    │  ├── Adaptive threshold + 3× upscale preprocessing
    │  ├── Multi-pass PSM scan (PSM 6, 7, 8)
    │  └── Per-character confidence → uncertain positions
    │
    ▼
Upsert asset record
    │  ├── New tag → create Asset + ConsensusScore
    │  └── Known tag → compare fields → Flag if mismatch
    │
    ▼
Status: PROCESSED | FLAGGED | MANUAL_REVIEW | FAILED

Asset Status & Consensus Scoring
Consensus score blends AI confidence with community validations:

pending — no validations yet
active — has confirmations, composite score > 0
verified — composite ≥ 0.90 and ≥ 3 confirms
disputed — 1+ disputes, or ≥ 3 disputes
flagged — attribute mismatch with existing canonical record (reviewer action required)

The composite score formula weights AI confidence at 40% (decreasing as validations accumulate) and human signal at 60%:
ai_weight = max(0.10, 0.40 - (total_validations × 0.05))
human_signal = confirm_ratio × min(1.0, total_validations / 5)
composite = ai_weight × ai_confidence + human_weight × human_signal

Tests
bash# OCR unit tests (no services needed)
cd apps/ocr-service
pytest tests/test_ocr_tag_parsing.py -v

# End-to-end API tests (requires running Postgres)
export TEST_DATABASE_URL=postgresql+asyncpg://polepad:polepad@localhost:5432/polepad
cd apps/api
pytest tests/test_end_to_end.py -v

# Full CI (lint + tests + docker build) — see .github/workflows/ci.yml
Local Test Scripts
These scripts run against local services and are useful for debugging individual pipeline stages:
bash# Test YOLO detection on an image (no services needed)
python scripts/test_cv.py path/to/image.jpg

# Test OCR (ocr-service must be running on :8002)
python scripts/test_ocr.py path/to/image.jpg --x1 100 --y1 50 --x2 400 --y2 150

# Test vegetation detection standalone
python scripts/test_vegetation.py path/to/image.jpg

Roadmap

 Offline-first mobile app (ONNX model on device)
 ArcGIS Field Maps deep integration
 Batch video frame processing
 Automated SAP PM work order escalation
 pgvector similarity search ("find poles like this one")
 Federated learning across utility territories
 Swap demo YOLOv8n for a fine-tuned pole-specific model


USC Columbia × Dominion Energy — Hackathon 2025
Built with ❤️ for the USC-Dominion Energy infrastructure challenge.
Questions? Open an issue or ping the team.
