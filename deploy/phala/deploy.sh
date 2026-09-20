#!/usr/bin/env bash
#
# Deploy Kin CPU CVM on Phala Cloud
#
# Prerequisites:
#   npm install -g @phala/cli
#   phala login
#
# This deploys the Kin TEE handler as a Confidential Virtual Machine
# (CVM) on Phala Cloud using Intel TDX hardware isolation.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
IMAGE="ghcr.io/interiority-inc/kin-tee-handler"
TAG="${KIN_IMAGE_TAG:-latest}"

log() { echo "[kin-deploy] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

# ── Step 1: Build the container image ────────────────────────────
log "Building container image..."
docker build \
    --build-arg GIT_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo 'unknown')" \
    -f "$REPO_ROOT/tee/Dockerfile" \
    -t "$IMAGE:$TAG" \
    "$REPO_ROOT"

log "Image built: $IMAGE:$TAG"

# ── Step 2: Push to registry ─────────────────────────────────────
log "Pushing image to registry..."
docker push "$IMAGE:$TAG"
log "Image pushed"

# ── Step 3: Deploy to Phala Cloud ────────────────────────────────
log "Deploying to Phala Cloud..."

if [ ! -f "$SCRIPT_DIR/.env" ]; then
    log "ERROR: $SCRIPT_DIR/.env not found. Copy .env.example and fill in values."
    exit 1
fi

phala deploy \
    -c "$SCRIPT_DIR/docker-compose.yml" \
    -n kin-handler \
    -e "$SCRIPT_DIR/.env"

log "Deployment complete."

# ── Step 4: Verify ───────────────────────────────────────────────
log ""
log "Next steps:"
log "  1. Get your CVM ID:  phala cvms list"
log "  2. Verify attestation:  phala cvms attestation <cvm-id>"
log "  3. Check health:  curl https://<cvm-endpoint>/health"
log ""
log "To start/stop the CVM (saves compute costs):"
log "  phala cvms start <cvm-id>"
log "  phala cvms stop <cvm-id>"
