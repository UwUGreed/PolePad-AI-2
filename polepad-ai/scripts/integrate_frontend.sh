#!/usr/bin/env bash
# file: scripts/integrate_frontend.sh
set -euo pipefail

log() { printf "\033[1;32m[ok]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[warn]\033[0m %s\n" "$*" >&2; }
die() { printf "\033[1;31m[err]\033[0m %s\n" "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage:
  scripts/integrate_frontend.sh [--no-docker] [--follow-logs]

What it does:
  - Detects frontend folder: GridstormFrontEnd/ or tyler_frontend/
  - Ensures next.config.* has output: "standalone"
  - Writes infra/docker/frontend.Dockerfile
  - Writes docker-compose.override.yml to swap web build (no manual compose edits)
  - Best-effort deep integration: copies old apps/web UI into /portal/inspect
  - Applies a couple of known Tyler fixes if those files exist
  - Runs: docker compose up -d --build (unless --no-docker)

Notes:
  - Run from repo root that contains docker-compose.yml OR from anywhere inside it.
  - Uses detached mode by default to avoid flooding your terminal.
EOF
}

NO_DOCKER=0
FOLLOW_LOGS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-docker) NO_DOCKER=1; shift ;;
    --follow-logs) FOLLOW_LOGS=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown arg: $1 (use --help)" ;;
  esac
done

find_repo_root() {
  local d="$PWD"
  while [[ "$d" != "/" ]]; do
    if [[ -f "$d/docker-compose.yml" ]]; then
      echo "$d"
      return 0
    fi
    d="$(dirname "$d")"
  done
  return 1
}

REPO_ROOT="$(find_repo_root || true)"
[[ -n "${REPO_ROOT}" ]] || die "Could not find docker-compose.yml in current/parent directories."
cd "$REPO_ROOT"
log "Repo root: $REPO_ROOT"

FRONTEND_DIR=""
if [[ -d "GridstormFrontEnd" ]]; then
  FRONTEND_DIR="GridstormFrontEnd"
elif [[ -d "tyler_frontend" ]]; then
  FRONTEND_DIR="tyler_frontend"
else
  die "No GridstormFrontEnd/ or tyler_frontend/ found in repo root."
fi
log "Using frontend: $FRONTEND_DIR"

NEXT_CONFIG=""
for f in "$FRONTEND_DIR"/next.config.ts "$FRONTEND_DIR"/next.config.js "$FRONTEND_DIR"/next.config.mjs "$FRONTEND_DIR"/next.config.cjs; do
  if [[ -f "$f" ]]; then NEXT_CONFIG="$f"; break; fi
done
[[ -n "$NEXT_CONFIG" ]] || die "No next.config.* found under $FRONTEND_DIR/"
log "Next config: $NEXT_CONFIG"

# Patch next.config.* to include output: "standalone" (best-effort, idempotent)
python3 - "$NEXT_CONFIG" <<'PY'
import re, sys
from pathlib import Path

path = Path(sys.argv[1])
s = path.read_text(encoding="utf-8", errors="ignore")
orig = s

if re.search(r"\boutput\s*:\s*['\"]standalone['\"]", s):
    print("next.config already has output: standalone")
    sys.exit(0)

# If output exists (non-standalone), force to standalone
if re.search(r"\boutput\s*:", s):
    s = re.sub(r"\boutput\s*:\s*['\"][^'\"]+['\"]", 'output: "standalone"', s, count=1)
else:
    # Insert inside obvious config object
    inserted = False
    for pat in [
        r"(const\s+nextConfig[^=]*=\s*{\s*)",
        r"(let\s+nextConfig[^=]*=\s*{\s*)",
        r"(var\s+nextConfig[^=]*=\s*{\s*)",
        r"(module\.exports\s*=\s*{\s*)",
    ]:
        s2, n = re.subn(pat, r'\1output: "standalone",\n  ', s, count=1)
        if n:
            s = s2
            inserted = True
            break

    if not inserted:
        # Safe fallback: append a minimal export. (Rarely needed.)
        s = s.rstrip() + '\n\nexport default { output: "standalone" };\n'

if s != orig:
    path.write_text(s, encoding="utf-8")
    print("Patched next.config to output: standalone")
PY
log "Patched Next config (if needed)"

# Decide npm install command based on lockfile presence
NPM_INSTALL_CMD="npm ci"
if [[ ! -f "$FRONTEND_DIR/package-lock.json" ]]; then
  warn "No package-lock.json found in $FRONTEND_DIR; using npm install"
  NPM_INSTALL_CMD="npm install"
fi

mkdir -p infra/docker
cat > infra/docker/frontend.Dockerfile <<EOF
FROM node:20-alpine AS deps
WORKDIR /app
COPY ${FRONTEND_DIR}/package*.json ./
RUN ${NPM_INSTALL_CMD}

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY ${FRONTEND_DIR}/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# harmless if unused; required by some auth setups
ENV SESSION_SECRET=dev-change-me

VOLUME ["/app/data"]

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/.next/standalone ./

EXPOSE 3000
CMD ["node","server.js"]
EOF
log "Wrote infra/docker/frontend.Dockerfile"

mkdir -p "$FRONTEND_DIR/data"

cat > docker-compose.override.yml <<EOF
services:
  web:
    build:
      context: .
      dockerfile: infra/docker/frontend.Dockerfile
    ports:
      - "3000:3000"
    environment:
      NEXT_PUBLIC_API_URL: "http://localhost:8000"
      SESSION_SECRET: "dev-change-me"
    volumes:
      - ./${FRONTEND_DIR}/data:/app/data

  api:
    environment:
      ALLOWED_ORIGINS: "http://localhost:3000"
EOF
log "Wrote docker-compose.override.yml"

# Deep integration: copy old inspection UI into /portal/inspect (best-effort)
if [[ -d "$FRONTEND_DIR/app" ]]; then
  INSPECT_SRC=""
  for candidate in \
    "apps/web/app/page.tsx" \
    "apps/web/src/app/page.tsx" \
    "apps/web/pages/index.tsx" \
    "apps/web/src/pages/index.tsx"
  do
    if [[ -f "$candidate" ]]; then INSPECT_SRC="$candidate"; break; fi
  done

  if [[ -z "$INSPECT_SRC" ]]; then
    # fallback: try any tracked apps/web/**/page.tsx
    INSPECT_SRC="$(git ls-files | grep -E '^apps/web/.*/page\.tsx$' | head -n 1 || true)"
  fi

  if [[ -n "$INSPECT_SRC" && -f "$INSPECT_SRC" ]]; then
    mkdir -p "$FRONTEND_DIR/app/portal/inspect"
    cp "$INSPECT_SRC" "$FRONTEND_DIR/app/portal/inspect/InspectClient.tsx"

    perl -pi -e 's/export default function Home\(/export default function InspectClient(/g;
                 s/export default function Page\(/export default function InspectClient(/g' \
      "$FRONTEND_DIR/app/portal/inspect/InspectClient.tsx" || true

    if [[ -f "$FRONTEND_DIR/components/RequireAuth.tsx" || -f "$FRONTEND_DIR/components/RequireAuth.jsx" ]]; then
      cat > "$FRONTEND_DIR/app/portal/inspect/page.tsx" <<'TS'
import RequireAuth from "@/components/RequireAuth";
import InspectClient from "./InspectClient";

export default async function Page() {
  return (
    <RequireAuth>
      <InspectClient />
    </RequireAuth>
  );
}
TS
    else
      cat > "$FRONTEND_DIR/app/portal/inspect/page.tsx" <<'TS'
import InspectClient from "./InspectClient";

export default function Page() {
  return <InspectClient />;
}
TS
    fi
    log "Deep integration added: /portal/inspect (source: ${INSPECT_SRC})"
  else
    warn "Could not find apps/web page.tsx to copy; skipped /portal/inspect integration."
  fi
else
  warn "$FRONTEND_DIR/app not found (not App Router?). Skipped /portal/inspect integration."
fi

# Tyler-specific fixes (safe no-ops if missing)
if [[ -f "$FRONTEND_DIR/components/LogoutButton.tsx" ]]; then
  perl -pi -e 's|/api/logout|/api/auth/logout|g' "$FRONTEND_DIR/components/LogoutButton.tsx" || true
  log "Patched LogoutButton endpoint (if present)"
fi

if [[ -f "$FRONTEND_DIR/app/api/admin/add-user/route.ts" ]]; then
  perl -pi -e 's/\baddUser\(username, password\);/await addUser(username, password);/g' \
    "$FRONTEND_DIR/app/api/admin/add-user/route.ts" || true
  log "Patched add-user await (if present)"
fi

log "Compose services detected:"
docker compose config --services | sed 's/^/  - /'

if [[ "$NO_DOCKER" -eq 1 ]]; then
  log "--no-docker set; not running docker compose"
  exit 0
fi

log "Bringing stack up (detached)..."
docker compose down -v >/dev/null 2>&1 || true
docker compose up -d --build

log "Up. Open: http://localhost:3000  (API docs: http://localhost:8000/docs)"
if [[ "$FOLLOW_LOGS" -eq 1 ]]; then
  log "Following logs (Ctrl+C to stop following):"
  docker compose logs -f web api
else
  log "To watch logs: docker compose logs -f web"
fi
