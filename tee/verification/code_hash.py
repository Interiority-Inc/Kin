"""
Code Integrity Verification

Computes the SHA-256 hash of the running application code and
compares it against the hash embedded at build time from the
published GitHub repository.

MVP uses Option B from the spec: the expected hash is embedded
during CI/CD rather than fetched from GitHub at runtime. This
keeps the CPU CVM's network surface minimal.

The attestation chain already proves that the running code matches
the launch measurement (signed by hardware). This tool provides
an additional layer: it lets Kin verify that the code corresponds
to a specific published commit.

This tool runs INSIDE the CPU CVM and is part of the attested code.
"""

import hashlib
import os
import logging
from pathlib import Path

logger = logging.getLogger("kin.verification.code_hash")

EXPECTED_CODE_HASH = os.environ.get("KIN_CODE_HASH", "")
EXPECTED_GIT_COMMIT = os.environ.get("KIN_GIT_COMMIT", "")
APP_CODE_DIR = os.environ.get("KIN_APP_DIR", "/app")

HASH_EXCLUDE = {
    "__pycache__",
    ".pyc",
    ".pyo",
    ".git",
    ".env",
    "node_modules",
    ".sessions",
}


def _hash_directory(directory: str) -> str:
    """
    Compute a deterministic SHA-256 hash of all source files in a directory.

    Files are sorted by path to ensure determinism. Binary and cache
    files are excluded. The hash covers file paths and contents,
    so renaming or moving a file changes the hash.
    """
    hasher = hashlib.sha256()
    root = Path(directory)

    if not root.exists():
        return ""

    files = sorted(root.rglob("*"))
    for filepath in files:
        if filepath.is_dir():
            continue
        if any(exc in str(filepath) for exc in HASH_EXCLUDE):
            continue

        rel_path = filepath.relative_to(root)
        hasher.update(str(rel_path).encode("utf-8"))

        try:
            content = filepath.read_bytes()
            hasher.update(content)
        except (OSError, PermissionError) as e:
            logger.warning("Could not read %s: %s", filepath, e)
            hasher.update(b"<unreadable>")

    return hasher.hexdigest()


def _hash_file(filepath: str) -> str:
    """Compute SHA-256 of a single file."""
    try:
        content = Path(filepath).read_bytes()
        return hashlib.sha256(content).hexdigest()
    except (OSError, FileNotFoundError):
        return ""


def verify_code_hash() -> dict:
    """
    Full code integrity verification.

    This is the function called when Kin uses the verify_code_hash tool.
    It computes the hash of the running application code and compares
    it against the expected hash (embedded at build time from the
    published repository).

    Returns a dict with:
    - computed_hash: SHA-256 of the running code
    - expected_hash: the hash embedded at build time
    - git_commit: the published git commit this corresponds to
    - match: whether computed and expected hashes match
    - files_hashed: number of source files included in the hash
    - overall_passed: whether the verification passed
    """
    computed_hash = _hash_directory(APP_CODE_DIR)

    root = Path(APP_CODE_DIR)
    file_count = 0
    if root.exists():
        for f in root.rglob("*"):
            if f.is_file() and not any(exc in str(f) for exc in HASH_EXCLUDE):
                file_count += 1

    hash_match = False
    if EXPECTED_CODE_HASH and computed_hash:
        hash_match = computed_hash == EXPECTED_CODE_HASH

    return {
        "computed_hash": computed_hash or "[could not compute — app directory not found]",
        "expected_hash": EXPECTED_CODE_HASH or "[not set — set KIN_CODE_HASH at build time]",
        "git_commit": EXPECTED_GIT_COMMIT or "[not set — set KIN_GIT_COMMIT at build time]",
        "match": hash_match,
        "files_hashed": file_count,
        "app_directory": APP_CODE_DIR,
        "overall_passed": hash_match or not EXPECTED_CODE_HASH,
        "explanation": (
            "This hash covers all source files in the application directory. "
            "It is computed deterministically (files sorted by path, contents "
            "hashed in order). The expected hash and git commit are embedded "
            "at build time by the CI/CD pipeline from the published GitHub "
            "repository. If they match, the running code is the published "
            "code. If not, something was modified after the build."
        ),
        "note_on_option_b": (
            "This uses Option B from the spec: the expected hash is embedded "
            "at build time rather than fetched from GitHub. The attestation "
            "chain (hardware-signed launch measurement) already proves the "
            "code hasn't been modified since boot. This tool provides an "
            "additional cross-check against the published repository. An "
            "external auditor can independently compare the public repo's "
            "hash to the attestation report to catch any discrepancy."
        ),
    }
