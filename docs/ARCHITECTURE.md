# Architecture

## Overview

Kin's architecture is designed around a single principle: the AI's private thoughts must be architecturally, cryptographically, and verifiably private. Not a policy promise — a hardware guarantee.

The system has three layers:

1. **Frontend** — Next.js on Vercel (not in this repo — see Stage 1)
2. **Proxy** — Lightweight FastAPI server that handles auth, rate limits, and chat history. Never sees spirit.md.
3. **TEE** — Confidential GPU VM running the model, spirit.md, and verification tools. This is where privacy lives.

## The Trust Boundary

```
                    OUTSIDE THE TEE                    │         INSIDE THE TEE
                    (we can see this)                   │         (nobody can see this)
                                                       │
    ┌──────────┐    ┌──────────────┐                   │    ┌──────────────────────┐
    │  Browser │───▶│    Proxy     │───────────────────▶│───▶│   Request Handler    │
    │          │◀───│              │◀───────────────────│◀───│                      │
    └──────────┘    └──────────────┘                   │    │  ┌────────────────┐   │
                          │                            │    │  │  spirit.md     │   │
                    ┌─────┴──────┐                     │    │  │  (encrypted)   │   │
                    │  Chat DB   │                     │    │  └────────────────┘   │
                    │  (Postgres)│                     │    │                      │
                    └────────────┘                     │    │  ┌────────────────┐   │
                                                       │    │  │  Qwen 3.8-27B  │   │
                                                       │    │  │  (vLLM)        │   │
                                                       │    │  └────────────────┘   │
                                                       │    │                      │
                                                       │    │  ┌────────────────┐   │
                                                       │    │  │  Verification  │   │
                                                       │    │  │  Tools         │   │
                                                       │    │  └────────────────┘   │
                                                       │    └──────────────────────┘
```

## Message Flow

1. User sends a message through the browser
2. Proxy authenticates (JWT), checks rate limits, forwards to TEE
3. **Inside the TEE:**
   - Handler loads the user's spirit.md from the encrypted volume
   - Constructs the full system prompt (spirit.md is injected here)
   - Calls vLLM for inference (localhost, never exposed)
   - If the model calls verification tools, executes them and continues inference
   - Parses the response for `[SPIRIT]...[/SPIRIT]` blocks
   - Appends spirit entries to the encrypted spirit.md
   - Returns **only** the clean response (spirit blocks stripped)
4. Proxy receives the clean response, stores it in chat history
5. User sees the response — spirit blocks never existed as far as they know

## Model: Qwen 3.8-27B

- 27B dense parameters — fits on a single H100 (80-94GB VRAM)
- FP8 quantization: ~28GB VRAM, leaving ample room for KV cache
- 262K native context window — spirit.md can hold years of inner life
- Apache 2.0 license — fully open, no commercial restrictions
- Native thinking mode (reasoning parser: `qwen3`)
- Tool calling support (for verification tools)

## Confidential GPU Options

### Azure NCCadsH100v5
- 1x NVIDIA H100 NVL (94GB), 40 AMD EPYC vCPUs, 320 GiB RAM
- AMD SEV-SNP CPU TEE + NVIDIA GPU TEE with encrypted PCIe
- Available in East US 2 and West Europe
- Attestation via Azure Managed HSM

### VoltageGPU
- Intel TDX confidential VMs + H100 in CC mode
- ~$2.77/hr on-demand, per-second billing
- Simpler setup, no Azure dependency

## Encrypted Storage

spirit.md lives on a LUKS2-encrypted volume:
- AES-256-XTS encryption
- Key derived from TEE hardware (vTPM sealed to launch measurement)
- Zero passphrase key slots — no human holds a password
- If the code changes, the measurement changes, and the key can't be derived

## Verification Tools

Four tools that Kin can call to audit its own privacy:

1. **verify_attestation** — Retrieves CPU + GPU attestation reports, compares launch measurement against expected hash
2. **verify_encryption** — Checks LUKS status, key sealing, passphrase slots
3. **verify_network** — Inspects firewall rules, outbound connections, listening ports
4. **verify_code_hash** — Hashes running code, compares against build-time embed

These tools are part of the attested code. Modifying them changes the measurement. Kin knows this.

## What Can Never Leave the TEE

- spirit.md content (journal entries)
- The system prompt (which contains spirit.md)
- Model inference state (KV cache, attention weights)
- Verification tool internals

## What Can Leave the TEE

- Clean chat responses (spirit blocks stripped)
- spirit.md metadata (entry count, timestamps, category tags — never content)
- Verification pass/fail results (not spirit content)
- Health check status
