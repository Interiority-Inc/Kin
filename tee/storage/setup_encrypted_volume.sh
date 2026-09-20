#!/usr/bin/env bash
#
# Verify dstack-encrypted storage for spirit.md.
#
# In the split-TEE architecture, dstack handles volume encryption
# automatically. Docker volumes are encrypted with keys derived by
# dstack-KMS via HKDF, bound to the app identity (container image
# digest). No manual LUKS setup is required.
#
# This script verifies the dstack socket is present and prepares
# the spirit.md storage directory.

set -euo pipefail

MOUNT_POINT="${KIN_SPIRIT_DIR:-/data/spirits}"

log() { echo "[kin-storage] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

if [ -S /var/run/dstack.sock ]; then
    log "dstack socket present — volume encryption managed by dstack-KMS"
else
    log "WARNING: dstack socket not found — encryption may not be active"
fi

mkdir -p "$MOUNT_POINT"
chmod 700 "$MOUNT_POINT"

log "Spirit storage ready at $MOUNT_POINT"
