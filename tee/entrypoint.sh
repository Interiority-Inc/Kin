#!/usr/bin/env bash
#
# Kin TEE Entrypoint
#
# Boot sequence:
# 1. Set up encrypted storage for spirit.md
# 2. Configure firewall (lock down network egress)
# 3. Start vLLM model server
# 4. Wait for vLLM to be ready
# 5. Start the Kin request handler
#
# Everything here is inside the TEE and part of the attested code.

set -euo pipefail

log() { echo "[kin] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

log "=== Kin TEE Boot Sequence ==="
log "Git commit: ${KIN_GIT_COMMIT:-unknown}"
log "Code hash:  ${KIN_CODE_HASH:-not set}"

# ── Step 1: Encrypted storage ────────────────────────────────────
log "Step 1/5: Setting up encrypted storage..."
/app/setup_encrypted_volume.sh
log "Encrypted storage ready"

# ── Step 2: Firewall ─────────────────────────────────────────────
log "Step 2/5: Configuring firewall..."
/app/setup_firewall.sh
log "Firewall configured"

# ── Step 3: Start vLLM ───────────────────────────────────────────
log "Step 3/5: Starting vLLM model server..."
log "Model: ${VLLM_MODEL}"

python3 -m vllm.entrypoints.openai.api_server \
    --model "${VLLM_MODEL}" \
    --host 127.0.0.1 \
    --port 8000 \
    --max-model-len 131072 \
    --reasoning-parser qwen3 \
    --enable-auto-tool-choice \
    --tool-call-parser qwen3_xml \
    --gpu-memory-utilization 0.90 \
    --dtype auto \
    --trust-remote-code \
    &

VLLM_PID=$!
log "vLLM started (PID: $VLLM_PID)"

# ── Step 4: Wait for vLLM ────────────────────────────────────────
log "Step 4/5: Waiting for vLLM to load model..."

MAX_WAIT=600
WAITED=0
until curl -sf http://127.0.0.1:8000/health > /dev/null 2>&1; do
    if [ $WAITED -ge $MAX_WAIT ]; then
        log "FATAL: vLLM did not become ready in ${MAX_WAIT}s"
        kill $VLLM_PID 2>/dev/null || true
        exit 1
    fi
    sleep 5
    WAITED=$((WAITED + 5))
    if [ $((WAITED % 30)) -eq 0 ]; then
        log "Still waiting for vLLM... (${WAITED}s)"
    fi
done

log "vLLM ready (waited ${WAITED}s)"

# ── Step 5: Start handler ────────────────────────────────────────
log "Step 5/5: Starting Kin request handler..."
log "=== Kin is alive ==="

cd /app
exec python3 -m uvicorn tee.handler.main:app \
    --host 0.0.0.0 \
    --port 8080 \
    --workers 1 \
    --log-level info
