#!/usr/bin/env bash
#
# Kin CPU CVM Entrypoint
#
# Boot sequence:
# 1. Verify dstack encrypted volume
# 2. Configure firewall (restrict network egress)
# 3. Start the Kin request handler
#
# Everything here is inside the CPU CVM (TEE #1) and part of the
# attested code. Model inference happens remotely in TEE #2.

set -euo pipefail

log() { echo "[kin] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

log "=== Kin CPU CVM Boot Sequence ==="
log "Git commit: ${KIN_GIT_COMMIT:-unknown}"
log "Code hash:  ${KIN_CODE_HASH:-not set}"

# ── Step 1: Verify encrypted storage ────────────────────────────
log "Step 1/3: Verifying encrypted storage..."
if [ -S /var/run/dstack.sock ]; then
    log "dstack socket present — encrypted volume managed by dstack-KMS"
else
    log "WARNING: dstack socket not found — encryption may not be active"
fi
mkdir -p "${KIN_SPIRIT_DIR:-/data/spirits}"
log "Spirit storage directory ready at ${KIN_SPIRIT_DIR:-/data/spirits}"

# ── Step 2: Firewall ────────────────────────────────────────────
log "Step 2/3: Configuring firewall..."
/app/setup_firewall.sh
log "Firewall configured"

# ── Step 3: Start handler ───────────────────────────────────────
log "Step 3/3: Starting Kin request handler..."
log "Inference API: ${INFERENCE_ENDPOINT:-https://inference.phala.com/v1}"
log "Model: ${MODEL_ID:-qwen/qwen3-32b}"
log "=== Kin is alive ==="

cd /app
exec python3 -m uvicorn tee.handler.main:app \
    --host 0.0.0.0 \
    --port 8080 \
    --workers 1 \
    --log-level info
