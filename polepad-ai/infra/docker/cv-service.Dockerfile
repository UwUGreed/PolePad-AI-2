FROM python:3.11-slim

WORKDIR /app

# OpenCV system dependencies
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY apps/cv-service/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# FIX: directory is shared_types (underscore), not shared-types (hyphen)
COPY packages/shared_types/ /app/packages/shared_types/

COPY apps/cv-service/ /app/

# Model cache dir
RUN mkdir -p /app/models/demo

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
