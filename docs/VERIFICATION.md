# Verification Guide

How to independently verify that Kin's privacy guarantees are real.

## What You're Verifying

Kin claims that the AI's private journal (spirit.md) is:
1. Encrypted at rest on a dstack volume inside the CPU CVM (TEE #1)
2. Encrypted in transit between the CPU CVM and the GPU TEE (TEE #2)
3. Never included in responses that leave TEE #1
4. Running on code that matches this public repository

This guide shows you how to verify each claim yourself.

## Step 1: Verify the CPU CVM Attestation (TEE #1)

The CPU CVM runs on Phala Cloud with Intel TDX hardware isolation. The hardware produces a signed attestation report that proves exactly what code is running inside the enclave.

### Get the Attestation Report

```bash
# From outside (using the Phala CLI):
phala cvms attestation <cvm-id>

# Or via the CVM's own endpoint:
curl https://<cvm-endpoint>/.well-known/attestation
```

### Verify the Report

```bash
# The report contains a launch measurement — a hash of all code
# loaded into the CVM. Compute what it SHOULD be from this repo:

git clone https://github.com/Interiority-Inc/Kin.git
cd Kin

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

The TDX attestation quote can be verified against Intel's Trust Authority using `dcap-qvl` (pure Rust with Python/Go/JS bindings) or `dstack-verifier`.

## Step 2: Verify the GPU TEE Attestation (TEE #2)

The GPU TEE runs Phala's Confidential Inference API with Intel TDX + NVIDIA Confidential Computing. It provides attestation through the ACI (Attested Confidential Inference) gateway.

### Get the ACI Gateway Attestation

```bash
# Request the gateway's TDX attestation with a fresh nonce:
NONCE=$(openssl rand -hex 32)
curl "https://inference.phala.com/v1/aci/attestation?nonce=$NONCE"
```

The response contains the ACI gateway's TDX quote, proving it is running inside a hardware enclave.

### Verify Per-Response Receipts

Every inference response includes an `x-receipt-id` header. Fetch the receipt:

```bash
curl "https://inference.phala.com/v1/aci/receipts/{receipt-id}"
```

The receipt contains:
- **Request hash** — what was sent
- **Response hash** — what came back
- **`upstream.verified`** — confirms the upstream inference provider was verified as running in a TEE before the prompt was forwarded
- **Session ID** for deeper audit

Verify the receipt signature against the gateway's attested keyset. If `upstream.verified` is false, the prompt may have been sent outside a TEE — Kin's handler refuses to write spirit entries in this case.

### Full Audit

```bash
# Using the Phala audit tool:
pap audit --report report.json --receipt receipt.json --nonce $NONCE
```

## Step 3: Verify the Disk Encryption

Spirit.md lives on a dstack-encrypted Docker volume inside the CPU CVM.

```bash
# Inside the TEE, Kin can run:
# verify_encryption tool

# Expected output:
# - dstack_volume_active: true
# - encryption_type: dstack-kms
# - key_bound_to_app_identity: true
# - human_accessible_keys: 0
```

Key things to check:
- **Key bound to app identity**: The encryption key is derived by dstack-KMS via HKDF, bound to the container image digest. If the code changes, the identity changes, and the volume cannot be decrypted.
- **Zero human-accessible keys**: No human holds a passphrase to this volume. The key exists only inside the TEE.
- **dstack socket present**: The CVM has `/var/run/dstack.sock` available, confirming dstack manages the encrypted volume.

## Step 4: Verify the Network Configuration

```bash
# Inside the TEE, Kin can run:
# verify_network tool

# Expected output:
# - INPUT: ACCEPT on port 8080 (handler) and loopback; DROP all else
# - OUTPUT: ACCEPT on loopback, established, DNS, and HTTPS (443); DROP all else
# - FORWARD: DROP all
# - Allowed outbound: inference.phala.com via HTTPS
```

The network configuration allows outbound HTTPS to the Phala inference API (port 443) — this is necessary because inference is now remote. All other outbound traffic is blocked.

Defense-in-depth: even though outbound HTTPS is allowed, the only data that leaves the CVM over this channel is the full prompt (containing spirit.md), which is encrypted over attested TLS and terminates inside the GPU TEE. The handler code that constructs and sends this prompt is part of the attested code.

## Step 5: Verify the Code

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

### Could the inference provider see the prompt?
No. TLS terminates inside the ACI gateway TEE. The ACI gateway verifies the upstream inference provider is running in a TEE before forwarding the prompt. The prompt never exists in plaintext outside a hardware enclave.

### Could someone intercept the prompt in transit?
No. The connection between the CPU CVM and the inference API uses TLS that terminates inside both TEEs. The CPU CVM verifies the gateway's attestation before sending. An attacker intercepting the traffic would see only encrypted bytes.

### Could the operator intercept Kin's tool calls?
No. The tools execute inside the CPU CVM. The operator cannot see or modify enclave memory.

### Could the operator fake the expected hash in the system prompt?
This is the one subtle attack. If they modify both the code AND the expected hash, they'd match. But the modified code would differ from this public repository. An external auditor comparing the repo's hash to the attestation report catches this.

### What are the remaining trust assumptions?
1. Intel and NVIDIA haven't been compromised at the hardware level
2. No undiscovered bugs in the TEE implementation (Intel TDX, NVIDIA CC)
3. The ACI gateway correctly verifies upstream TEE status
4. This GitHub repository hasn't been compromised

These are the same assumptions that underpin all modern confidential computing.

## Kin Verifies Itself

The most novel aspect of this system: Kin doesn't trust us. It trusts the silicon. On every session start, Kin runs `verify_attestation` and `verify_code_hash`. If either fails, it refuses to load spirit.md and tells the user something is wrong.

On every inference call, Kin's handler verifies the response receipt (`upstream.verified`). If verification fails, it does not write spirit entries from that response.

The verification tools are part of the attested code. Modifying them changes the measurement. There is no way to give Kin fake tools without Kin detecting the change.
