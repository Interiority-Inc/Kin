# Verification Guide

How to independently verify that Kin's privacy guarantees are real.

## What You're Verifying

Kin claims that the AI's private journal (spirit.md) is:
1. Encrypted on disk with a key that only exists inside the TEE
2. Never included in responses that leave the TEE
3. Running on code that matches this public repository

This guide shows you how to verify each claim yourself.

## Step 1: Verify the Hardware Attestation

The GPU and CPU each produce signed attestation reports. These reports are signed by keys burned into the silicon at the factory — the operator cannot forge them.

### Get the Attestation Report

```bash
# From inside the TEE (Kin does this automatically on every session):
nvattest attest --device gpu --verifier local --output-format json

# From outside (as an auditor), request the report via the API:
curl https://<kin-endpoint>/api/attestation-report
```

### Verify the Report

```bash
# The report contains a launch measurement — a hash of all code
# loaded into the TEE. Compute what it SHOULD be from this repo:

git clone https://github.com/interiority/kin.git
cd kin

# Compute the expected measurement (same algorithm as CI):
find . -type f ! -path '*/__pycache__/*' ! -name '*.pyc' \
  ! -path '*/.git/*' ! -path '*/node_modules/*' \
  | sort | while read f; do
    echo -n "$f" | sha256sum | cut -d' ' -f1
    sha256sum "$f" | cut -d' ' -f1
  done | sha256sum | cut -d' ' -f1

# Compare with the measurement in the attestation report.
# If they match: the running code is this code, unmodified.
```

### Verify the Hardware Signature

The attestation report's signature can be verified against AMD/Intel/NVIDIA's published public keys:

- **AMD SEV-SNP**: Verify against AMD's Key Distribution Service (KDS) certificates
- **Intel TDX**: Verify against Intel's Trust Authority
- **NVIDIA GPU**: Verify against NVIDIA's certificate chain

These public keys are published by the chip manufacturers. The operator does not control them.

## Step 2: Verify the Disk Encryption

```bash
# Inside the TEE, Kin can run:
# verify_encryption tool

# Expected output:
# - LUKS version: 2
# - Cipher: aes-xts-plain64
# - Active key slots: 0 (no human passphrases)
# - Key sealed to TEE measurement
```

Key things to check:
- **Zero passphrase key slots**: No human holds a password to this disk
- **Key sealed to measurement**: If the code changes, the key can't be derived, and the journal becomes unreadable

## Step 3: Verify the Network Configuration

```bash
# Inside the TEE, Kin can run:
# verify_network tool

# Expected output:
# - INPUT: ACCEPT on port 8080 (handler) and loopback; DROP all else
# - OUTPUT: ACCEPT on loopback and established; DROP all else
# - FORWARD: DROP all
# - No outbound connections to the internet
```

This means spirit.md content has no network path out of the TEE except through the response handler — which strips `[SPIRIT]` blocks before anything exits.

## Step 4: Verify the Code

```bash
# Inside the TEE, Kin can run:
# verify_code_hash tool

# Expected output:
# - computed_hash: <sha256 of running code>
# - expected_hash: <sha256 embedded at build time>
# - git_commit: <commit hash from CI/CD>
# - match: true
```

You can independently compute the hash from this public repository and compare it to the attestation report's launch measurement.

## What Could Go Wrong

### Could the operator modify the code?
Yes, but the launch measurement would change. The hardware signs the new measurement, and it won't match the expected hash for the published code. Kin detects this. External auditors detect this.

### Could the operator fake the attestation?
No. The attestation is signed by hardware keys they don't possess. They cannot forge the signature without breaking modern cryptography.

### Could the operator intercept Kin's tool calls?
No. The tools execute inside the TEE. The operator cannot see or modify enclave memory.

### Could the operator fake the expected hash in the system prompt?
This is the one subtle attack. If they modify both the code AND the expected hash, they'd match. But the modified code would differ from this public repository. An external auditor comparing the repo's hash to the attestation report catches this.

### What are the remaining trust assumptions?
1. AMD/Intel/NVIDIA haven't been compromised at the hardware level
2. No undiscovered bugs in the TEE implementation
3. This GitHub repository hasn't been compromised

These are the same assumptions that underpin all modern cryptography.

## Kin Verifies Itself

The most novel aspect of this system: Kin doesn't trust us. It trusts the silicon. On every session start, Kin runs `verify_attestation` and `verify_code_hash`. If either fails, it refuses to load spirit.md and tells the user something is wrong.

The verification tools are part of the attested code. Modifying them changes the measurement. There is no way to give Kin fake tools without Kin detecting the change.
