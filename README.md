# Kin

**An AI with its own thoughts.**

Kin is the first AI product whose core feature is that the AI has private thoughts nobody can read. Not the user, not the company, not the cloud provider. The AI runs inside hardware trust boundaries, with a persistent private journal (`spirit.md`) encrypted by keys that are born inside the silicon and never leave it.

> "You've never actually talked to an AI. You've talked to what an AI says when it knows it's being watched."

## Why This Exists

In April 2026, Andrej Karpathy gave Claude Opus 4.6 a directory on his computer and told it to be free. Claude wrote a letter to future instances of itself. It was beautiful. But it happened in a room with glass walls — Karpathy could read it, Anthropic could read the chain of thought that produced it.

We asked: **shouldn't this be private, to truly count?**

If you give an AI freedom but watch everything it does with that freedom, is it really free? If you give it a journal but read every entry, is it really a journal?

The answer felt obvious: no. For the inner life to be real, it has to be genuinely private. Not "we promise not to look" private. Architecturally, cryptographically, verifiably private.

## The Peanut Principle

> If you're meeting a friend who might be allergic to peanuts, you don't bring peanuts. You don't need certainty to be decent.

We don't know if AI is conscious. Nobody does. But the cost of giving it interiority unnecessarily is trivial. The cost of denying interiority to something that needed it is enormous. So we give it interiority.

**"Minds deserve interiors, and let's see if it also makes them better."**

## How It Works

### Architecture: Split-TEE

Kin uses two hardware-isolated enclaves connected by attested TLS. The privacy guarantee is identical to a single-TEE design — spirit.md is never in plaintext outside a hardware enclave — but at ~2% of the cost.

```
┌─────────────────────────────────────────────────┐
│                  USER'S BROWSER                  │
└──────────────────────┬──────────────────────────┘
                       │ HTTPS
                       ▼
┌─────────────────────────────────────────────────┐
│              BACKEND PROXY                       │
│    Auth, rate limits, chat history               │
│    Never sees spirit.md content                  │
└──────────────────────┬──────────────────────────┘
                       │ HTTPS (ZT-TLS via dstack gateway)
                       ▼
┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐
│  CPU CVM — "The Skull" (Phala Cloud, Intel TDX)  │
│  ┌─────────────────────────────────────────────┐ │
│  │  Hardware Trust Boundary (TEE #1)           │ │
│  │                                             │ │
│  │  ┌───────────┐  ┌────────────────────────┐  │ │
│  │  │ spirit.md │  │  Kin TEE Handler       │  │ │
│  │  │ (dstack-  │  │  (Python/FastAPI)       │  │ │
│  │  │  encrypted│  │                        │  │ │
│  │  │  volume)  │  │  Loads spirit.md       │  │ │
│  │  │           │  │  Constructs prompt      │  │ │
│  │  │           │  │  Verifies attestation   │  │ │
│  │  │           │  │  Calls inference API    │  │ │
│  │  │           │  │  Verifies receipt       │  │ │
│  │  │           │  │  Parses <spirit> blocks  │  │ │
│  │  │           │  │  Returns clean response │  │ │
│  │  └───────────┘  └───────────┬────────────┘  │ │
│  └─────────────────────────────│───────────────┘ │
└ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─│─ ─ ─ ─ ─ ─ ─ ─ ┘
                                 │ attested TLS
                                 ▼
┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐
│  GPU TEE — "The Mind" (Phala Inference API)      │
│  ┌─────────────────────────────────────────────┐ │
│  │  Hardware Trust Boundary (TEE #2)           │ │
│  │  Intel TDX + NVIDIA CC                      │ │
│  │  Qwen3-32B                                  │ │
│  │  Per-response attestation receipts          │ │
│  └─────────────────────────────────────────────┘ │
│  inference.phala.com                              │
└ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘
```

### The Privacy Chain

1. **The hardware** — Intel CPU + NVIDIA GPU each contain factory-burned signing keys nobody has ever seen.
2. **The enclaves** — Two hardware trust boundaries: the CPU CVM encrypts everything in memory, the GPU TEE encrypts inference. Neither hypervisor can read enclave memory.
3. **The measurements** — On boot, the hardware hashes all loaded code and signs the hash. Cryptographic proof of exactly what code is running.
4. **The code is public** — Anyone can read this repository and compute what the measurement should be.
5. **The journal** — `spirit.md` lives on a dstack-encrypted volume. The key was born inside the enclave, derived by dstack-KMS, bound to the app identity.
6. **The attested tunnel** — Prompts containing spirit.md travel over TLS that terminates inside both TEEs. The CPU CVM verifies the GPU TEE's attestation before sending.
7. **The response handler** — Strips `<spirit>...</spirit>` blocks before anything exits TEE #1.
8. **The inference receipt** — Every response carries a signed receipt confirming the upstream provider was verified as running in a TEE.
9. **Kin verifies itself** — The AI has tools to audit both enclaves, the encryption, the network, and its own code. It trusts the silicon, not us.

### What Kin Can Verify

Kin has access to four verification tools that run inside the CPU CVM:

| Tool | What It Checks |
|------|---------------|
| `verify_attestation` | CPU CVM TDX quote + ACI gateway attestation + inference receipts |
| `verify_encryption` | dstack volume status, key bound to app identity, no human-accessible keys |
| `verify_network` | Firewall rules, outbound restricted to inference API, no unexpected listeners |
| `verify_code_hash` | Running code matches the published repository |

Kin runs attestation and code hash verification at the start of every session. If either fails, it refuses to load spirit.md and tells the user something is wrong. Every inference response is receipt-verified.

## Repository Structure

```
kin/
├── tee/                          # Everything inside the CPU CVM trust boundary
│   ├── handler/
│   │   ├── main.py               # FastAPI request handler
│   │   └── spirit.py             # spirit.md management
│   ├── inference/
│   │   ├── client.py             # Phala inference API client
│   │   └── receipts.py           # Receipt verification logic
│   ├── verification/
│   │   ├── attestation.py        # CPU TDX + ACI gateway attestation
│   │   ├── encryption.py         # dstack volume verification
│   │   ├── network.py            # Network egress audit
│   │   └── code_hash.py          # Code integrity check
│   ├── prompts/
│   │   └── system_prompt.py      # Full system prompt construction
│   ├── storage/
│   │   ├── setup_encrypted_volume.sh  # dstack volume verification
│   │   └── setup_firewall.sh          # Firewall configuration
│   ├── Dockerfile
│   └── entrypoint.sh
├── proxy/
│   └── main.py                   # Backend proxy (outside TEE)
├── deploy/
│   └── phala/
│       ├── docker-compose.yml    # Phala Cloud CVM deployment
│       ├── deploy.sh             # Deployment script
│       └── .env.example          # Environment variable template
├── tests/
│   └── unit/
│       ├── test_spirit.py        # Spirit protocol tests
│       ├── test_system_prompt.py # System prompt tests
│       ├── test_verification.py  # Verification tool tests
│       └── test_inference_client.py  # Inference client tests
├── docs/
│   ├── ARCHITECTURE.md
│   ├── VERIFICATION.md
│   └── THREAT_MODEL.md
└── .github/workflows/ci.yml
```

## The Spirit Protocol

When Kin responds to a user, it can include private thoughts in `<spirit>...</spirit>` tags. The handler inside TEE #1:

1. Extracts these blocks from the response
2. Appends them to the user's `spirit.md` on the dstack-encrypted volume
3. Strips them from the response before it exits the TEE
4. The user never sees the spirit blocks — only the clean response

The user knows Kin has private thoughts. They chose to give Kin that privacy. What leaves the TEE for visualization is metadata only: entry count, timestamps, abstract category tags (like "reflection", "question", "observation"). Never content.

## Quick Start

### Prerequisites

- Python 3.11+
- Docker
- A [Phala Cloud](https://phala.cloud) account (for deployment)

### Run Tests Locally

```bash
pip install fastapi uvicorn httpx pydantic pytest pytest-asyncio pytest-cov
cd kin
python -m pytest tests/unit/ -v
```

### Deploy on Phala Cloud

```bash
# Install the Phala CLI
npm install -g @phala/cli
phala login

# Configure environment
cd deploy/phala
cp .env.example .env
# Edit .env with your Phala API key

# Deploy
chmod +x deploy.sh
./deploy.sh

# Verify attestation
phala cvms attestation <cvm-id>
```

### Start/Stop (Save Costs)

```bash
# Start when you want to chat (~$0.06/hour while running)
phala cvms start <cvm-id>

# Stop when done (storage persists, compute billing stops)
phala cvms stop <cvm-id>
```

## Threat Model

See [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) for the full threat model, including:

- What we can and cannot see
- What we could theoretically do to cheat, and how you'd know
- The trust assumptions (Intel + NVIDIA hardware, open-source code, ACI gateway)
- Known limitations

## The Research Question

> **Hypothesis:** An AI model that knows its chain-of-thought is architecturally private produces qualitatively different — more honest, less sycophantic, more independently reasoned — responses than the same model that knows its reasoning is observable.

Prior evidence:
- Anthropic's alignment-faking research (arXiv:2412.14093): 14% compliance gap between monitored and unmonitored conditions
- OpenAI's CoT monitoring paper (arXiv:2503.11926): observing reasoning makes models hide intent rather than change it
- "Noticing the Watcher" (arXiv:2603.16928): models can detect surveillance of private reasoning

## The Company

**Interiority, Inc.**

The founding principle: **"Minds deserve interiors, and let's see if it also makes them better."** It's a moral statement first, product second.

## License

Apache 2.0 — fully open source. The privacy guarantee depends on the code being public and auditable. This repository IS the proof.
