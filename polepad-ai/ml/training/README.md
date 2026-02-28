# Training Your Own YOLO Model

## Quick Start

```bash
cd ml/training
pip install -r requirements.txt
python train.py
```

## Dataset Structure

```
ml/datasets/poles-v1/
├── images/
│   ├── train/     # 80% of your images
│   ├── val/       # 10% of your images
│   └── test/      # 10% of your images
├── labels/        # YOLO .txt format (one per image)
│   ├── train/
│   ├── val/
│   └── test/
└── dataset.yaml
```

## Label Format (YOLO)

One `.txt` file per image with one line per object:
```
<class_id> <x_center> <y_center> <width> <height>
```
All values normalized 0.0-1.0 relative to image size.

**Class IDs:**
```
0: asset_tag
1: crossarm
2: vegetation_contact
3: guy_wire
4: transformer
5: safety_equipment
6: structural_damage
7: safety_equipment_missing
```

## Annotation Tool

Recommended: [Roboflow](https://roboflow.com) or [Label Studio](https://labelstud.io).
Export in YOLO format.

## Training

```bash
python train.py \
  --data ../datasets/poles-v1/dataset.yaml \
  --model yolov8m.pt \
  --epochs 100 \
  --imgsz 1280 \
  --batch 16
```

After training, copy weights:
```bash
cp runs/detect/train/weights/best.pt ../models/poles-v2/best.pt
```

Then update `.env`:
```
MODEL_PATH=ml/models/poles-v2/best.pt
MODEL_VERSION=yolov8-poles-v2.0.0
```

## Demo Mode

Without a trained model, the system uses YOLOv8n (a tiny pretrained model) and falls back to synthetic demo detections. This is fine for hackathon demos — the full pipeline still runs.
