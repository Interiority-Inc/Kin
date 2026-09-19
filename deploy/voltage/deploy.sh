#!/usr/bin/env bash
#
# Deploy Kin on VoltageGPU (Confidential H100 VM)
#
# VoltageGPU provides Intel TDX confidential VMs with NVIDIA H100
# in CC mode. All instances run on confidential infrastructure.
# Per-second billing, no minimum commitment.
#
# Prerequisites:
#   - VoltageGPU account and API key
#   - Docker image pushed to a container registry
#
# Pricing (as of 2026):
#   - H100 (80GB): ~$2.77/hr
#   - H200 (141GB): ~$4.07/hr

set -euo pipefail

VOLTAGE_API_KEY="${VOLTAGE_API_KEY:-}"
VOLTAGE_API_URL="https://api.voltagegpu.com/v1"
GPU_TYPE="${KIN_GPU_TYPE:-h100}"
CONTAINER_IMAGE="${KIN_CONTAINER_IMAGE:-kin-tee:latest}"
CONTAINER_REGISTRY="${KIN_CONTAINER_REGISTRY:-}"

log() { echo "[kin-voltage] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

if [ -z "$VOLTAGE_API_KEY" ]; then
    log "FATAL: Set VOLTAGE_API_KEY environment variable"
    log "Get your API key at: https://voltagegpu.com/console"
    exit 1
fi

# ── Step 1: Check pricing and availability ────────────────────────
log "Checking VoltageGPU pricing..."
curl -sf https://voltagegpu.com/api/pricing/snapshot | python3 -c "
import json, sys
data = json.load(sys.stdin)
for gpu in data.get('gpus', []):
    if '${GPU_TYPE}' in gpu.get('name', '').lower():
        print(f\"  {gpu['name']}: \${gpu.get('price_per_hour', 'N/A')}/hr\")
        print(f\"  Available: {gpu.get('available', 'unknown')}\")
" 2>/dev/null || log "Could not fetch pricing"

# ── Step 2: Provision confidential VM ─────────────────────────────
log "Provisioning VoltageGPU $GPU_TYPE instance..."

INSTANCE_ID=$(curl -sf \
    -H "Authorization: Bearer $VOLTAGE_API_KEY" \
    -H "Content-Type: application/json" \
    -d "{
        \"gpu_type\": \"$GPU_TYPE\",
        \"gpu_count\": 1,
        \"image\": \"ubuntu-24.04-cuda-12.8\",
        \"confidential\": true,
        \"startup_script\": \"#!/bin/bash\\ncurl -fsSL https://get.docker.com | bash\\napt-get install -y nvidia-container-toolkit\\nnvidia-ctk runtime configure --runtime=docker\\nsystemctl restart docker\"
    }" \
    "$VOLTAGE_API_URL/instances" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")

log "Instance provisioned: $INSTANCE_ID"

# ── Step 3: Wait for instance to be ready ─────────────────────────
log "Waiting for instance to boot..."

MAX_WAIT=300
WAITED=0
while true; do
    STATUS=$(curl -sf \
        -H "Authorization: Bearer $VOLTAGE_API_KEY" \
        "$VOLTAGE_API_URL/instances/$INSTANCE_ID" \
        | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])")

    if [ "$STATUS" = "running" ]; then
        break
    fi

    if [ $WAITED -ge $MAX_WAIT ]; then
        log "FATAL: Instance did not become ready in ${MAX_WAIT}s"
        exit 1
    fi

    sleep 10
    WAITED=$((WAITED + 10))
done

INSTANCE_IP=$(curl -sf \
    -H "Authorization: Bearer $VOLTAGE_API_KEY" \
    "$VOLTAGE_API_URL/instances/$INSTANCE_ID" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['ip'])")

log "Instance ready. IP: $INSTANCE_IP"

# ── Step 4: Deploy Kin container ──────────────────────────────────
log "Deploying Kin container..."

ssh -o StrictHostKeyChecking=no "root@$INSTANCE_IP" << 'DEPLOY_SCRIPT'
set -euo pipefail

# Pull and run the Kin container
docker run -d \
    --name kin-tee \
    --gpus all \
    --runtime=nvidia \
    --privileged \
    -p 8080:8080 \
    -e KIN_SPIRIT_DIR=/mnt/encrypted/spirits \
    -e VLLM_MODEL=Qwen/Qwen3.8-27B \
    ${CONTAINER_REGISTRY:+$CONTAINER_REGISTRY/}${CONTAINER_IMAGE}

# Wait for the handler to be ready
echo "Waiting for Kin to start..."
until curl -sf http://localhost:8080/health > /dev/null; do
    sleep 5
done
echo "Kin is ready"
DEPLOY_SCRIPT

# ── Step 5: Verify ────────────────────────────────────────────────
log "Verifying deployment..."
curl -sf "http://$INSTANCE_IP:8080/health" || log "WARNING: Health check failed"

log "=== Deployment complete ==="
log "Instance: $INSTANCE_ID"
log "IP: $INSTANCE_IP"
log "Handler: http://$INSTANCE_IP:8080"
log "GPU: $GPU_TYPE (Intel TDX confidential mode)"
log ""
log "To tear down: curl -X DELETE -H 'Authorization: Bearer \$VOLTAGE_API_KEY' $VOLTAGE_API_URL/instances/$INSTANCE_ID"
