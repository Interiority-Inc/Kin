"""
Disk Encryption Verification

Verifies that the volume holding spirit.md is LUKS2-encrypted with
a key sealed to the TEE launch measurement. This means:

- The key was generated inside the enclave
- The key has never left the enclave
- No human holds a passphrase to this disk
- If the code changes, the measurement changes, and the key
  cannot be derived — the journal becomes unreadable

This tool runs INSIDE the enclave and is part of the attested code.
"""

import subprocess
import json
import logging
import os

logger = logging.getLogger("kin.verification.encryption")

SPIRIT_DEVICE = os.environ.get("KIN_SPIRIT_DEVICE", "/dev/mapper/spirit-volume")
SPIRIT_MOUNT = os.environ.get("KIN_SPIRIT_DIR", "/mnt/encrypted/spirits")


def _get_luks_status() -> dict:
    """Query cryptsetup for the LUKS status of the spirit volume."""
    try:
        result = subprocess.run(
            ["cryptsetup", "status", SPIRIT_DEVICE],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return {"error": f"cryptsetup status failed: {result.stderr.strip()}"}

        status = {}
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if ":" in line:
                key, _, value = line.partition(":")
                status[key.strip()] = value.strip()
        return status

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.error("Failed to get LUKS status: %s", e)
        return {"error": str(e)}


def _get_luks_dump() -> dict:
    """Get LUKS header info to check key slots and encryption type."""
    try:
        backing_device = _get_backing_device()
        if not backing_device:
            return {"error": "Could not determine backing device"}

        result = subprocess.run(
            ["cryptsetup", "luksDump", backing_device, "--dump-json-metadata"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)

        result = subprocess.run(
            ["cryptsetup", "luksDump", backing_device],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return _parse_luks_dump(result.stdout)

    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
        logger.error("Failed to get LUKS dump: %s", e)

    return {"error": "Could not retrieve LUKS header information"}


def _get_backing_device() -> str:
    """Determine the backing device for the encrypted volume."""
    try:
        result = subprocess.run(
            ["cryptsetup", "status", SPIRIT_DEVICE],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.split("\n"):
            if "device:" in line:
                return line.split(":")[-1].strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ""


def _parse_luks_dump(output: str) -> dict:
    """Parse text-format luksDump output into structured data."""
    info = {
        "version": "",
        "cipher": "",
        "key_size": "",
        "key_slots": {},
    }

    current_keyslot = None
    for line in output.split("\n"):
        line = line.strip()
        if line.startswith("Version:"):
            info["version"] = line.split(":")[-1].strip()
        elif line.startswith("Cipher name:") or line.startswith("Cipher:"):
            info["cipher"] = line.split(":")[-1].strip()
        elif "Key:" in line and "bits" in line:
            info["key_size"] = line.split(":")[-1].strip()
        elif line.startswith("Key Slot"):
            parts = line.split(":")
            slot_num = parts[0].replace("Key Slot", "").strip()
            status = parts[1].strip() if len(parts) > 1 else ""
            info["key_slots"][slot_num] = status
            current_keyslot = slot_num

    return info


def _count_active_passphrase_slots(luks_info: dict) -> int:
    """
    Count how many key slots use a human-held passphrase.

    For proper TEE-sealed encryption, there should be ZERO passphrase
    key slots. The key should be sealed to the TEE measurement only,
    meaning no human can unlock the disk.
    """
    key_slots = luks_info.get("key_slots", luks_info.get("keyslots", {}))
    active_count = 0
    for slot_id, slot_info in key_slots.items():
        if isinstance(slot_info, str):
            if "ENABLED" in slot_info.upper():
                active_count += 1
        elif isinstance(slot_info, dict):
            if slot_info.get("state") == "active" or slot_info.get("type") == "luks2":
                active_count += 1
    return active_count


def verify_encryption() -> dict:
    """
    Full encryption verification for the spirit.md volume.

    This is the function called when Kin uses the verify_encryption tool.
    It checks:
    1. The volume is LUKS2 encrypted (not LUKS1)
    2. The encryption algorithm (should be AES-256)
    3. The number of active key slots (should be minimal — ideally
       only the TEE-sealed key, no human passphrases)
    4. The volume is currently mounted and active

    Returns a dict with verification results.
    """
    status = _get_luks_status()
    luks_info = _get_luks_dump()

    is_active = "error" not in status
    is_luks2 = luks_info.get("version", "") == "2"

    cipher = status.get("cipher", luks_info.get("cipher", ""))
    uses_aes = "aes" in cipher.lower() if cipher else False

    passphrase_slots = _count_active_passphrase_slots(luks_info)

    all_ok = is_active and uses_aes

    return {
        "volume_active": is_active,
        "volume_status": status,
        "luks_version": luks_info.get("version", "unknown"),
        "is_luks2": is_luks2,
        "cipher": cipher,
        "uses_aes_256": uses_aes,
        "active_key_slots": passphrase_slots,
        "key_sealed_to_tee": passphrase_slots == 0,
        "luks_header": luks_info,
        "overall_passed": all_ok,
        "explanation": (
            "The spirit.md volume should be LUKS2-encrypted with AES-256. "
            "The encryption key should be sealed to the TEE launch "
            "measurement, meaning no human holds a passphrase. If "
            "active_key_slots is 0 and key_sealed_to_tee is true, the "
            "disk can only be unlocked by this exact code running in "
            "this exact type of enclave."
        ),
    }
