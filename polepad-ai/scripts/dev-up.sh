#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f "GridstormFrontEnd/package.json" ]]; then
  FRONTEND_DIR="GridstormFrontEnd"
elif [[ -f "tyler_frontend/package.json" ]]; then
  FRONTEND_DIR="tyler_frontend"
else
  FRONTEND_DIR="apps/web"
fi

if command -v podman-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(podman-compose)
elif command -v docker >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
else
  echo "ERROR: Neither podman-compose nor docker compose is installed." >&2
  exit 1
fi

echo "Using frontend: $FRONTEND_DIR"
echo "Using compose command: ${COMPOSE_CMD[*]}"

FRONTEND_DIR="$FRONTEND_DIR" "${COMPOSE_CMD[@]}" up -d --build

printf '\nService URLs:\n'
echo "  Web:        http://localhost:3000"
echo "  API:        http://localhost:8000/health"
echo "  CV Service: http://localhost:8001/health"
echo "  OCR Service:http://localhost:8002/health"

printf '\nHealth checks:\n'
for url in \
  "http://localhost:8000/health" \
  "http://localhost:8001/health" \
  "http://localhost:8002/health"
do
  echo "- $url"
  curl -fsS "$url" || true
  echo
 done
