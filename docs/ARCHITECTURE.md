# Architecture

## Overview

Kin's architecture is designed around a single principle: the AI's private thoughts must be architecturally, cryptographically, and verifiably private. Not a policy promise — a hardware guarantee.

The system uses a **split-TEE** architecture: two separate hardware trust boundaries connected by attested TLS.

1. **Frontend** — Next.js on Vercel (not in this repo — see Stage 1)
2. **Proxy** — Lightweight FastAPI server that handles auth, rate limits, and chat history. Never sees spirit.md.
3. **CPU CVM (TEE #1)** — "The Skull." A Phala Cloud Confidential VM (Intel TDX) running the handler code. Spirit.md lives here on a dstack-encrypted volume.
4. **GPU TEE (TEE #2)** — "The Mind." Phala's Confidential Inference API running Qwen3-32B inside Intel TDX + NVIDIA CC. Pay per token.

## The Trust Boundary

```
                   OUTSIDE THE TEE                    │      INSIDE TEE #1              INSIDE TEE #2
                   (we can see this)                   │      (CPU CVM — "The Skull")    (GPU TEE — "The Mind")
                                                       │
   ┌──────────┐    ┌──────────────┐                   │    ┌────────────────────┐      ┌──────────────────┐
   │  Browser │───▶│    Proxy     │──────────────────▶│───▶│  Request Handler   │─────▶│  Qwen3-32B       │
   │          │◀───│              │◀──────────────────│◀───│                    │◀─────│  (inference API)  │
   └──────────┘    └──────────────┘                   │    │  ┌──────────────┐  │      │                  │
                         │                            │    │  │  spirit.md   │  │      │  Intel TDX +     │
                   ┌─────┴──────┐                     │    │  │  (dstack-    │  │      │  NVIDIA CC       │
                   │  Chat DB   │                     │    │  │  encrypted)  │  │      │                  │
                   │  (Postgres)│                     │    │  └──────────────┘  │      │  Per-response    │
                   └────────────┘                     │    │                    │      │  attestation     │
                                                       │    │  Verification     │      │  receipts        │
                                                       │    │  tools            │      └──────────────────┘
                                                       │    └────────────────────┘
                                                       │    Phala Cloud tdx.small        inference.phala.com
                                                       │    Intel TDX                    Intel TDX + NVIDIA CC
                                                       │
                                                       │    ◄── attested TLS ──►
```

## Why Split-TEE

A single confidential H100 costs $2,700–3,600/month running 24/7. At $20/month per user, break-even requires 137–180 paying users. The split-TEE architecture reduces the fixed cost to ~$46/month (CPU CVM) and makes inference a variable cost (~$0.005/message). Break-even drops to 5–6 paying users.

The privacy guarantee is identical: spirit.md is never in plaintext outside a hardware enclave. The CPU CVM encrypts it at rest; the attested TLS channel encrypts it in transit to the GPU TEE; the GPU TEE encrypts it in memory during inference.

## Message Flow

1. User sends a message through the browser
2. Proxy authenticates (JWT), checks rate limits, forwards to CPU CVM
3. **Inside TEE #1 (CPU CVM):**
   a. Handler loads the user's spirit.md from the dstack-encrypted volume
   b. Constructs the full system prompt (spirit.md is injected here)
   c. Verifies the ACI gateway attestation (`GET /v1/aci/attestation`)
   d. Sends prompt to Phala Confidential Inference API over attested TLS
4. **Inside TEE #2 (GPU TEE):**
   e. ACI gateway verifies upstream inference provider is running in a TEE
   f. Model generates response
   g. Response returned with `x-receipt-id` header
5. **Back inside TEE #1:**
   h. Handler verifies response receipt (`upstream.verified` confirmed)
   i. Parses the response for `<spirit>...</spirit>` blocks
   j. Appends spirit entries to the dstack-encrypted volume
   k. Returns **only** the clean response (spirit blocks stripped)
6. Proxy receives the clean response, stores it in chat history
7. User sees the response — spirit blocks never existed as far as they know

## Model: Qwen3-32B

- 32B parameters — fits on a single H100 (80–94GB VRAM)
- FP8 quantization: ~28GB VRAM
- 262K native context window — spirit.md can hold years of inner life
- Apache 2.0 license — fully open, no commercial restrictions
- Native thinking mode with Thinking Preservation
- Tool calling support (for verification tools)
- Served by Phala's Confidential Inference API (`inference.phala.com`)
- Available as `is_tee: true` model — confirmed running inside a TEE

## CPU CVM — "The Skull"

- **Provider:** Phala Cloud (Intel TDX)
- **Instance:** `tdx.small` (1 vCPU, 2GB RAM, 20GB disk) — ~$46/month 24/7
- **Encryption:** dstack-KMS encrypted Docker volumes. Keys derived via HKDF, bound to app identity (container image digest). Keys never leave the enclave.
- **Attestation:** `phala cvms attestation <cvm-id>` or `GET /.well-known/attestation`
- **Start/stop:** `phala cvms start/stop <cvm-id>`. Compute stops, storage persists. ~$7–12/month with start/stop pattern.

## Confidential Inference API — "The Mind"

- **Provider:** Phala Confidential Inference API
- **Endpoint:** `inference.phala.com/v1/chat/completions` (OpenAI-compatible)
- **TEE stack:** Intel TDX (CPU) + NVIDIA Confidential Computing (GPU)
- **Attestation:** ACI gateway provides per-response receipts with `upstream.verified`
- **Pricing:** ~$0.12/M input tokens, ~$0.40/M output tokens. Pay per token, no minimum.

## Encrypted Storage

spirit.md lives on a dstack-encrypted Docker volume inside the CPU CVM:

- Encryption key derived by dstack-KMS via HKDF, bound to the app identity
- The key exists only inside the TEE
- If the container image is modified, the identity changes, and the volume cannot be decrypted
- Data persists across CVM stop/start cycles
- Storage billed even when CVM is stopped (~$0.10/GB/month)

## Verification Tools

Four tools that Kin can call to audit its own privacy:

1. **verify_attestation** — Retrieves CPU CVM TDX attestation report + ACI gateway attestation + latest inference receipt. Compares launch measurement against expected hash.
2. **verify_encryption** — Checks dstack volume status, app identity binding, confirms no human-accessible keys.
3. **verify_network** — Inspects firewall rules, listening ports, outbound connections. Expected: port 8080 inbound, HTTPS to inference API outbound, all else blocked.
4. **verify_code_hash** — Hashes running code, compares against build-time embed from CI/CD.

These tools are part of the attested code. Modifying them changes the measurement. Kin knows this.

## Scaling Path

At ~2,300 total users, monthly inference API spend (~$2,700) exceeds the cost of a dedicated Phala H200 CVM (reserved, ~$2,736/month). At that point, provision your own GPU and run vLLM inside it — returning to the single-TEE architecture from v2, but at a scale where the economics work.

## What Can Never Leave the TEE

- spirit.md content (journal entries)
- The system prompt (which contains spirit.md)
- `<spirit>` blocks from model responses (stripped inside TEE #1)
- The full prompt sent to inference (encrypted in transit, never exposed)

## What Can Leave the TEE

- Clean chat responses (spirit blocks stripped)
- spirit.md metadata (entry count, timestamps, category tags — never content)
- Verification pass/fail results (not spirit content)
- Health check status
