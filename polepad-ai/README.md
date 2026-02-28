# 🔌 PolePad AI

**Crowd-Powered Infrastructure Verification**  
*Computer Vision · OCR · Community Consensus · Dominion Energy Stack Compatible*

---

## What It Does

PolePad AI lets field workers photograph utility poles. The system automatically:
1. **Detects** the asset tag (pole ID number) using YOLOv8
2. **Reads** the tag characters using OCR (highlights uncertain ones in amber)
3. **Detects** infrastructure attributes (vegetation contact, guy wires, transformers, etc.)
4. **Stores** everything in a local PostgreSQL database
5. **Lets the community confirm or dispute** the AI's reading to build confidence over time

Built to feed directly into **Dominion Energy's existing stack**: Esri ArcGIS Enterprise, AVEVA PI System, SAP, and EpochField.

---

## 🚀 Run It In 3 Commands (Demo / Judge Mode)

**Prerequisites:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running.

```bash
git clone https://github.com/your-org/polepad-ai.git
cd polepad-ai
docker compose up --build
```

Then open **http://localhost:3000** in your browser.

That's it. Everything runs locally — no cloud account, no API keys required.

> **Demo credentials:** `demo@polepad.ai` / `demo1234`

---

## 📸 Try It Out

1. Go to **http://localhost:3000**
2. Click **"New Inspection"**
3. Upload any photo of a utility pole (or use the samples in `docs/sample-images/`)
4. Watch the AI detect the tag, read the number, and flag attributes
5. Click **Confirm** or **Dispute** on the result
6. See the confidence score update in real time

---

## Architecture Overview

```
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
│ YOLOv8      │             │  PaddleOCR      │
└──────┬──────┘             └────────┬────────┘
       │          results            │
       └────────────┬────────────────┘
                    │
┌───────────────────▼─────────────────────────────────────────┐
│  PostgreSQL  :5432   +   Redis  :6379                        │
│  (local Docker)                                              │
└─────────────────────────────────────────────────────────────┘
```

### Integration Adapters (Production)
```
PolePad API ──► Esri ArcGIS Enterprise  (REST Feature Service)
            ──► AVEVA PI System         (AF SDK / REST)
            ──► SAP via EpochField      (Work Order sync)
```

---

## Project Structure

```
polepad-ai/
├── apps/
│   ├── api/            # FastAPI backend — main brain
│   ├── cv-service/     # YOLOv8 detection microservice
│   ├── ocr-service/    # PaddleOCR extraction microservice
│   └── web/            # Next.js frontend
├── packages/
│   ├── shared-types/   # Pydantic + TypeScript schemas (source of truth)
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
├── docker-compose.yml  # ← THE MAIN ENTRY POINT
└── .env.example        # All config variables documented
```

---

## Configuration

Copy `.env.example` to `.env` (already done for local demo mode):

```bash
cp .env.example .env
```

Key variables:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql://...@postgres:5432/polepad` | Postgres connection |
| `REDIS_URL` | `redis://redis:6379` | Redis for job queue |
| `CV_SERVICE_URL` | `http://cv-service:8001` | Internal CV service |
| `OCR_SERVICE_URL` | `http://ocr-service:8002` | Internal OCR service |
| `S3_ENABLED` | `false` | Set `true` + add AWS creds for S3 |
| `ARCGIS_ENABLED` | `false` | Set `true` + add ArcGIS creds |
| `PI_SYSTEM_ENABLED` | `false` | Set `true` + add PI System URL |
| `SAP_ENABLED` | `false` | Set `true` + add SAP endpoint |
| `MODEL_PATH` | `ml/models/demo/best.pt` | Path to YOLO weights |

---

## Dominion Energy Integration

All integrations are **opt-in via env flags**. The system runs fully without them.

### ArcGIS Enterprise
```bash
ARCGIS_ENABLED=true
ARCGIS_BASE_URL=https://your-arcgis-server/arcgis
ARCGIS_USERNAME=your_user
ARCGIS_PASSWORD=your_pass
ARCGIS_FEATURE_SERVICE_URL=.../FeatureServer/0
```
When enabled, every confirmed asset is pushed to your ArcGIS Feature Service as a point geometry with all attributes.

### AVEVA PI System
```bash
PI_SYSTEM_ENABLED=true
PI_BASE_URL=https://your-pi-server/piwebapi
PI_USERNAME=your_user
PI_PASSWORD=your_pass
PI_DATABASE=your_af_database
```
When enabled, inspection events are written as PI Events and asset attributes update PI tags.

### SAP / EpochField
```bash
SAP_ENABLED=true
SAP_BASE_URL=https://your-sap-server/api
SAP_CLIENT_ID=your_client_id
SAP_CLIENT_SECRET=your_client_secret
```
When enabled, high-severity attribute detections (vegetation contact, safety issues) auto-create SAP work orders.

See `docs/integration/` for full setup guides.

---

## Development

### Run Individual Services

```bash
# Just the database
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
```

### API Documentation
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

### Database
```bash
# Run migrations
cd packages/db
alembic upgrade head

# Seed demo data
python scripts/seed_demo.py

# Connect directly
docker exec -it polepad-postgres psql -U polepad -d polepad
```

### Train Your Own Model
```bash
cd ml/training
pip install -r requirements.txt
python train.py --data ../datasets/poles-v1/dataset.yaml --epochs 100
```
See `ml/training/README.md` for full training guide.

---

## API Quick Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/inspections/upload` | Upload image, start inference |
| `GET` | `/api/v1/jobs/{job_id}` | Poll job status + get results |
| `POST` | `/api/v1/inspections/{id}/validate` | Submit confirm/dispute/edit |
| `GET` | `/api/v1/assets` | List all assets with consensus scores |
| `GET` | `/api/v1/assets/{id}/history` | Full inspection timeline |
| `POST` | `/auth/login` | Get JWT token |

Full schema at http://localhost:8000/docs

---

## Tech Stack

| Layer | Technology |
|---|---|
| ML Detection | YOLOv8 (Ultralytics) |
| OCR | PaddleOCR 2.7 |
| Backend | FastAPI + Python 3.11 |
| Database | PostgreSQL 16 |
| Job Queue | Celery + Redis |
| Frontend | Next.js 14 |
| Containers | Docker + Compose |
| GIS | Esri ArcGIS REST API |
| Time Series | AVEVA PI Web API |
| Field Service | SAP/EpochField REST |

---

## Roadmap

- [ ] Offline-first mobile app (ONNX model on device)
- [ ] ArcGIS Field Maps deep integration
- [ ] Batch video frame processing
- [ ] Automated SAP PM work order escalation
- [ ] pgvector similarity search ("find poles like this one")
- [ ] Federated learning across utility territories

---

## USC Columbia × Dominion Energy — Hackathon 2025

Built with ❤️ for the USC-Dominion Energy infrastructure challenge.  
Questions? Open an issue or ping the team.
