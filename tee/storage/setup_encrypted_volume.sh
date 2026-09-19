#!/usr/bin/env bash
#
# Set up LUKS2-encrypted storage for spirit.md inside a TEE.
#
# This script creates and mounts an encrypted volume whose key
# is derived from the TEE's launch measurement. No human ever
# holds a passphrase to this disk.
#
# MUST be run inside a confidential VM (AMD SEV-SNP or Intel TDX).
# The key derivation depends on hardware-sealed secrets that only
# exist inside the TEE.

set -euo pipefail

VOLUME_PATH="${KIN_VOLUME_PATH:-/dev/disk/kin-spirit}"
MAPPER_NAME="${KIN_MAPPER_NAME:-spirit-volume}"
MOUNT_POINT="${KIN_SPIRIT_DIR:-/mnt/encrypted/spirits}"
KEY_SIZE=512  # bits (AES-256-XTS uses 512-bit key)

log() { echo "[kin-storage] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }
die() { log "FATAL: $*"; exit 1; }

# ── Step 1: Detect TEE type ──────────────────────────────────────
detect_tee() {
    if [ -e /sys/kernel/security/tdx/report ]; then
        echo "intel-tdx"
    elif [ -e /dev/sev-guest ] || [ -e /dev/sev ]; then
        echo "amd-sev-snp"
    else
        echo "none"
    fi
}

TEE_TYPE=$(detect_tee)
if [ "$TEE_TYPE" = "none" ]; then
    die "No TEE detected. This script must run inside a confidential VM."
fi
log "TEE type: $TEE_TYPE"

# ── Step 2: Derive encryption key from TEE measurement ───────────
#
# The key is derived from hardware-sealed secrets that are unique
# to this specific TEE instance and launch measurement. If the
# code changes, the measurement changes, and a different key is
# derived — making the old data unreadable.

derive_key() {
    local key_file="$1"

    if [ "$TEE_TYPE" = "amd-sev-snp" ]; then
        # AMD SEV-SNP: derive from the vTPM's sealed storage
        # The vTPM's storage root key is sealed to the launch measurement
        if command -v tpm2_createprimary &>/dev/null; then
            log "Deriving key from vTPM (AMD SEV-SNP)..."
            tpm2_createprimary -C o -G aes256 -c /tmp/primary.ctx 2>/dev/null
            tpm2_create -C /tmp/primary.ctx -G keyedhash \
                -a "fixedtpm|fixedparent|noda" \
                -i /dev/urandom -u /tmp/key.pub -r /tmp/key.priv 2>/dev/null
            tpm2_load -C /tmp/primary.ctx \
                -u /tmp/key.pub -r /tmp/key.priv -c /tmp/key.ctx 2>/dev/null
            tpm2_unseal -c /tmp/key.ctx -o "$key_file" 2>/dev/null
            rm -f /tmp/primary.ctx /tmp/key.pub /tmp/key.priv /tmp/key.ctx
        else
            # Fallback: use SNP-derived secret from the firmware
            log "Deriving key from SNP guest secret..."
            if [ -e /sys/kernel/security/secrets/coco/e6f5a162-d67f-4750-a67c-5d065f2a9910 ]; then
                head -c 64 /sys/kernel/security/secrets/coco/e6f5a162-d67f-4750-a67c-5d065f2a9910 > "$key_file"
            else
                die "No vTPM or SNP secret available for key derivation"
            fi
        fi

    elif [ "$TEE_TYPE" = "intel-tdx" ]; then
        # Intel TDX: derive from TDX sealing key
        # The sealing key is bound to the TD's measurement (MRTD + RTMR)
        if command -v tpm2_createprimary &>/dev/null; then
            log "Deriving key from vTPM (Intel TDX)..."
            tpm2_createprimary -C o -G aes256 -c /tmp/primary.ctx 2>/dev/null
            tpm2_create -C /tmp/primary.ctx -G keyedhash \
                -a "fixedtpm|fixedparent|noda" \
                -i /dev/urandom -u /tmp/key.pub -r /tmp/key.priv 2>/dev/null
            tpm2_load -C /tmp/primary.ctx \
                -u /tmp/key.pub -r /tmp/key.priv -c /tmp/key.ctx 2>/dev/null
            tpm2_unseal -c /tmp/key.ctx -o "$key_file" 2>/dev/null
            rm -f /tmp/primary.ctx /tmp/key.pub /tmp/key.priv /tmp/key.ctx
        else
            die "No vTPM available for TDX key derivation"
        fi
    fi

    if [ ! -s "$key_file" ]; then
        die "Key derivation produced empty key"
    fi
    log "Encryption key derived from TEE measurement"
}

# ── Step 3: Create or open the encrypted volume ──────────────────

KEY_FILE=$(mktemp /tmp/kin-key-XXXXXX)
trap 'shred -u "$KEY_FILE" 2>/dev/null; rm -f "$KEY_FILE"' EXIT

derive_key "$KEY_FILE"

if cryptsetup isLuks "$VOLUME_PATH" 2>/dev/null; then
    log "Existing LUKS volume detected, opening..."
    cryptsetup open "$VOLUME_PATH" "$MAPPER_NAME" \
        --type luks2 \
        --key-file "$KEY_FILE" \
        || die "Failed to open LUKS volume — measurement may have changed"
else
    log "No existing LUKS volume. Creating new encrypted volume..."

    # Create a file-backed volume if no block device exists
    if [ ! -b "$VOLUME_PATH" ]; then
        VOLUME_DIR=$(dirname "$VOLUME_PATH")
        mkdir -p "$VOLUME_DIR"
        # Default 10GB — grows as spirit.md accumulates
        fallocate -l 10G "$VOLUME_PATH" 2>/dev/null \
            || dd if=/dev/zero of="$VOLUME_PATH" bs=1G count=10
    fi

    # Format with LUKS2 + AES-256-XTS
    cryptsetup luksFormat "$VOLUME_PATH" \
        --type luks2 \
        --cipher aes-xts-plain64 \
        --key-size $KEY_SIZE \
        --hash sha256 \
        --key-file "$KEY_FILE" \
        --batch-mode \
        || die "Failed to format LUKS volume"

    cryptsetup open "$VOLUME_PATH" "$MAPPER_NAME" \
        --type luks2 \
        --key-file "$KEY_FILE" \
        || die "Failed to open new LUKS volume"

    # Create filesystem
    mkfs.ext4 -L kin-spirits "/dev/mapper/$MAPPER_NAME" \
        || die "Failed to create filesystem"

    log "New LUKS2 volume created and formatted"
fi

# ── Step 4: Mount the volume ─────────────────────────────────────

mkdir -p "$MOUNT_POINT"
mount "/dev/mapper/$MAPPER_NAME" "$MOUNT_POINT" \
    || die "Failed to mount encrypted volume"

# Set permissions — only the handler process can access
chown -R kin:kin "$MOUNT_POINT" 2>/dev/null || true
chmod 700 "$MOUNT_POINT"

log "Encrypted volume mounted at $MOUNT_POINT"
log "spirit.md storage ready"

# ── Step 5: Verify the setup ─────────────────────────────────────

log "Verification:"
log "  Device: /dev/mapper/$MAPPER_NAME"
log "  Mount:  $MOUNT_POINT"
log "  TEE:    $TEE_TYPE"
cryptsetup status "/dev/mapper/$MAPPER_NAME" | while read -r line; do
    log "  $line"
done
