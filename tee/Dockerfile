# Kin CPU CVM Container
#
# This container runs INSIDE the Phala Cloud CPU CVM (Intel TDX).
# It contains:
#   - The Kin request handler (spirit.md management + response parsing)
#   - The verification tools (attestation, encryption, network, code hash)
#
# Model inference happens remotely via the Phala Confidential Inference
# API (TEE #2). This container does NOT run the model.
#
# Everything in this container is part of the attested code. The hardware
# hashes it into the launch measurement. Any modification changes the
# measurement and breaks the attestation chain.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    iptables \
    iproute2 \
    dnsutils \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r kin && useradd -r -g kin -m -d /home/kin kin

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tee/ /app/tee/
COPY proxy/ /app/proxy/

ARG GIT_COMMIT=""
ARG CODE_HASH=""
ARG EXPECTED_MEASUREMENT=""
ENV KIN_GIT_COMMIT=${GIT_COMMIT}
ENV KIN_CODE_HASH=${CODE_HASH}
ENV KIN_EXPECTED_CPU_MEASUREMENT=${EXPECTED_MEASUREMENT}

ENV KIN_SPIRIT_DIR=/data/spirits
ENV INFERENCE_ENDPOINT=https://inference.phala.com/v1
ENV MODEL_ID=qwen/qwen3-32b
ENV KIN_APP_DIR=/app

COPY tee/storage/setup_firewall.sh /app/setup_firewall.sh
RUN chmod +x /app/setup_firewall.sh

COPY tee/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8080

ENTRYPOINT ["/app/entrypoint.sh"]
