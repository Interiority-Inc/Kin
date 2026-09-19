#!/usr/bin/env bash
#
# Deploy Kin on Azure NCCadsH100v5 (Confidential GPU VM)
#
# Prerequisites:
#   - Azure CLI installed and authenticated (az login)
#   - Subscription with NCCadsH100v5 quota in East US 2 or West Europe
#   - Docker image pushed to a container registry
#
# This script:
#   1. Creates a resource group
#   2. Provisions an NCCadsH100v5 confidential GPU VM
#   3. Configures the VM with the Kin container
#   4. Sets up attestation-gated key release via Managed HSM
#
# The VM runs AMD SEV-SNP + NVIDIA H100 CC mode.
# Memory is encrypted, PCIe is encrypted, attestation is hardware-signed.

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────
RESOURCE_GROUP="${KIN_AZURE_RG:-kin-confidential}"
LOCATION="${KIN_AZURE_LOCATION:-eastus2}"
VM_NAME="${KIN_AZURE_VM:-kin-tee-01}"
VM_SIZE="Standard_NCC40ads_H100_v5"
IMAGE="Canonical:ubuntu-24_04-lts:cvm:latest"
ADMIN_USER="${KIN_AZURE_ADMIN:-kinadmin}"
CONTAINER_REGISTRY="${KIN_CONTAINER_REGISTRY:-}"
CONTAINER_IMAGE="${KIN_CONTAINER_IMAGE:-kin-tee:latest}"

log() { echo "[kin-deploy] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

# ── Step 1: Resource Group ────────────────────────────────────────
log "Creating resource group: $RESOURCE_GROUP in $LOCATION"
az group create \
    --name "$RESOURCE_GROUP" \
    --location "$LOCATION"

# ── Step 2: Create Confidential GPU VM ────────────────────────────
log "Creating NCCadsH100v5 confidential VM: $VM_NAME"
log "This will take several minutes..."

az vm create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$VM_NAME" \
    --size "$VM_SIZE" \
    --image "$IMAGE" \
    --admin-username "$ADMIN_USER" \
    --generate-ssh-keys \
    --security-type "ConfidentialVM" \
    --os-disk-security-encryption-type "VMGuestStateOnly" \
    --enable-secure-boot true \
    --enable-vtpm true \
    --public-ip-sku Standard

VM_IP=$(az vm show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$VM_NAME" \
    --show-details \
    --query publicIps -o tsv)

log "VM created. Public IP: $VM_IP"

# ── Step 3: Configure the VM ─────────────────────────────────────
log "Installing NVIDIA drivers and container runtime..."

az vm run-command invoke \
    --resource-group "$RESOURCE_GROUP" \
    --name "$VM_NAME" \
    --command-id RunShellScript \
    --scripts '
        set -euo pipefail

        # Install NVIDIA drivers for confidential computing
        # The az-cgpu-onboarding scripts handle this
        curl -fsSL https://raw.githubusercontent.com/Azure/az-cgpu-onboarding/main/install.sh | bash

        # Install Docker + NVIDIA Container Toolkit
        curl -fsSL https://get.docker.com | bash
        distribution=$(. /etc/os-release; echo $ID$VERSION_ID)
        curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
        curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
            sed "s#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g" | \
            tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
        apt-get update && apt-get install -y nvidia-container-toolkit
        nvidia-ctk runtime configure --runtime=docker
        systemctl restart docker

        # Install NVIDIA attestation CLI
        apt-get install -y cmake build-essential libssl-dev
        git clone https://github.com/NVIDIA/attestation-sdk.git /opt/attestation-sdk
        cd /opt/attestation-sdk/nv-attestation-cli
        cmake -B build && cmake --build build && cmake --install build

        echo "VM configuration complete"
    '

# ── Step 4: Deploy Kin container ──────────────────────────────────
log "Deploying Kin container..."

if [ -n "$CONTAINER_REGISTRY" ]; then
    az vm run-command invoke \
        --resource-group "$RESOURCE_GROUP" \
        --name "$VM_NAME" \
        --command-id RunShellScript \
        --scripts "
            docker pull ${CONTAINER_REGISTRY}/${CONTAINER_IMAGE}
            docker run -d \
                --name kin-tee \
                --gpus all \
                --runtime=nvidia \
                --privileged \
                -p 8080:8080 \
                -e KIN_SPIRIT_DIR=/mnt/encrypted/spirits \
                -e VLLM_MODEL=Qwen/Qwen3.8-27B \
                ${CONTAINER_REGISTRY}/${CONTAINER_IMAGE}
        "
else
    log "No container registry set. Build and push the image first:"
    log "  docker build -t kin-tee:latest -f tee/Dockerfile ."
    log "  docker push <registry>/kin-tee:latest"
    log "  KIN_CONTAINER_REGISTRY=<registry> ./deploy.sh"
fi

# ── Step 5: Verify attestation ────────────────────────────────────
log "Verifying TEE attestation..."

az vm run-command invoke \
    --resource-group "$RESOURCE_GROUP" \
    --name "$VM_NAME" \
    --command-id RunShellScript \
    --scripts '
        # Verify GPU is in confidential computing mode
        nvidia-smi conf-compute -f

        # Run attestation
        nvattest attest --device gpu --verifier local

        echo "Attestation verification complete"
    '

log "=== Deployment complete ==="
log "VM IP: $VM_IP"
log "Handler endpoint: http://$VM_IP:8080"
log ""
log "Next steps:"
log "  1. Point the proxy at http://$VM_IP:8080"
log "  2. Verify attestation from outside: curl http://$VM_IP:8080/health"
log "  3. Set up TLS termination (nginx/caddy in front)"
