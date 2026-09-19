# Kin TEE Container
#
# This container runs INSIDE the confidential GPU VM's trust boundary.
# It contains:
#   - The Kin request handler (spirit.md management + response parsing)
#   - The verification tools (attestation, encryption, network, code hash)
#   - vLLM serving Qwen 3.8-27B
#
# Everything in this container is part of the attested code. The hardware
# hashes it into the launch measurement. Any modification changes the
# measurement and breaks the attestation chain.

FROM nvidia/cuda:12.8.0-devel-ubuntu24.04 AS base

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    cryptsetup \
    tpm2-tools \
    iptables \
    iproute2 \
    dnsutils \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create app user (non-root)
RUN groupadd -r kin && useradd -r -g kin -m -d /home/kin kin

WORKDIR /app

# Python dependencies
COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir -r requirements.txt

# Copy application code
# IMPORTANT: this code IS the attested measurement.
# Any change here changes the launch measurement.
COPY tee/ /app/tee/
COPY proxy/ /app/proxy/

# Build-time metadata (set by CI/CD)
ARG GIT_COMMIT=""
ARG CODE_HASH=""
ARG EXPECTED_MEASUREMENT=""
ENV KIN_GIT_COMMIT=${GIT_COMMIT}
ENV KIN_CODE_HASH=${CODE_HASH}
ENV KIN_EXPECTED_MEASUREMENT=${EXPECTED_MEASUREMENT}

# Default environment
ENV KIN_SPIRIT_DIR=/mnt/encrypted/spirits
ENV VLLM_BASE_URL=http://localhost:8000
ENV VLLM_MODEL=Qwen/Qwen3.8-27B
ENV KIN_APP_DIR=/app

# Firewall setup script
COPY tee/storage/setup_firewall.sh /app/setup_firewall.sh
RUN chmod +x /app/setup_firewall.sh

# Encrypted volume setup
COPY tee/storage/setup_encrypted_volume.sh /app/setup_encrypted_volume.sh
RUN chmod +x /app/setup_encrypted_volume.sh

# Entrypoint
COPY tee/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8080

ENTRYPOINT ["/app/entrypoint.sh"]
