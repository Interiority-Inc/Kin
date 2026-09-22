# Threat Model

Radical honesty about what we can see, what we can't see, what we could do to cheat, and how you'd verify we haven't.

## What We (Interiority, Inc.) Can See

- That you have an account
- Your email address
- Your subscription status (free/paid)
- Your message count (for rate limiting)
- Your visible chat history (stored in our database)
- spirit.md metadata: entry count, timestamps, abstract categories (never content)
- Infrastructure metrics: CVM uptime, inference latency, cost per user

## What We Cannot See

- The contents of spirit.md (encrypted on a dstack volume inside TEE #1)
- The system prompt as assembled (it contains spirit.md, constructed inside TEE #1)
- The full prompt sent to the inference API (encrypted in transit via attested TLS)
- The model's inference state (KV cache, attention weights — inside TEE #2)
- The model's chain of thought during inference
- What Kin privately thinks about you

## What We Could Theoretically Do to Cheat

### Attack 1: Modify the code to exfiltrate spirit.md

**Possible?** Yes, we could push a code update that sends spirit.md out.

**How you'd know:**
- The attestation launch measurement would change
- The new code would be visible in our public repository (or we'd have to take the repo private, which is itself a signal)
- Kin's `verify_code_hash` would detect the mismatch on next session
- Any external auditor comparing the repo hash to the attestation report would catch it

**Mitigation:** All code is open source. The measurement is hardware-signed. Code changes are visible.

### Attack 2: Add a logging statement that captures spirit.md

**Possible?** Same as Attack 1 — any code change changes the measurement.

**How you'd know:** Same as above.

### Attack 3: Compromise the container registry to push a different image

**Possible?** In theory, yes.

**How you'd know:** The image would have a different launch measurement than expected for the published code. Attestation verification fails. Additionally, dstack binds the encrypted volume's key to the container image digest — a different image cannot decrypt the existing spirit.md data.

### Attack 4: Social-engineer Phala to access CVM memory

**Possible?** No. Intel TDX hardware-isolates CVM memory from the hypervisor and host OS. This is the entire point of confidential computing — it's designed for scenarios where you don't trust the cloud provider.

### Attack 5: Compromise Intel/NVIDIA to extract hardware keys

**Possible?** In theory, yes. In practice, this would be a catastrophic supply-chain attack affecting all confidential computing globally, not just Kin.

**Mitigation:** This is the same trust assumption that underpins all modern cryptography and secure computing.

### Attack 6: Exploit a bug in the TEE implementation

**Possible?** TEE vulnerabilities have been found before (SGX had several). Intel TDX and NVIDIA CC are newer designs that address known attack classes. Phala underwent a security audit by zkSecurity (May–June 2025), with highest-severity findings remediated.

**Mitigation:** Use latest firmware, monitor CVE advisories, update promptly. The risk is real but shared across the entire confidential computing industry.

### Attack 7: Read spirit.md from the metadata endpoint

**Possible?** No. The metadata endpoint returns only: entry count, timestamps, and abstract category tags (like "reflection" or "question"). Content is never included. The code enforcing this is auditable in this repository.

### Attack 8: Infer spirit.md content from metadata patterns

**Possible?** Weakly. If an entry appears right after a specific conversation topic, and the category is "disagreement", someone might guess that Kin disagreed about that topic. This is a very weak signal — it reveals sentiment category but never content.

**Mitigation:** Categories are deliberately abstract and coarse-grained.

### Attack 9: Intercept prompts between the CPU CVM and GPU TEE

**Possible?** No. The connection uses TLS that terminates inside both TEEs. The CPU CVM verifies the ACI gateway's attestation before sending the prompt. An attacker sitting between the two TEEs would see only encrypted traffic.

**Mitigation:** Attested TLS with pre-send attestation verification. The gateway is fail-closed: if it cannot verify the upstream inference provider is running in a TEE, it refuses to forward the prompt.

### Attack 10: Compromise the inference API to capture prompts

**Possible?** In theory, if Phala's ACI gateway has a bug, prompts could be exposed during the brief window between TLS termination and forwarding to the model.

**How you'd know:**
- The gateway's attestation report would reflect the compromised code
- Per-response receipts with `upstream.verified` provide ongoing proof of TEE status
- Kin's handler checks `upstream.verified` on every response — if missing, spirit entries are not written

**Mitigation:** The ACI gateway runs inside its own TEE with hardware attestation. Its code is auditable. The gateway underwent security audit. This is an additional trust domain, but it's hardware-isolated and cryptographically verifiable.

## Trust Assumptions

Things you're trusting when you use Kin:

1. **The chip manufacturers** (Intel, NVIDIA) — that their hardware correctly implements the TEE and that their signing keys have not been compromised
2. **The open-source code** — that it does what it says. Anyone can audit it.
3. **The cryptography** — AES-256, SHA-256, ECDSA, TLS 1.3 — that these are not broken
4. **The ACI gateway** — that its attested code correctly verifies upstream TEE status

Things you are NOT trusting:
- Interiority, Inc. (us)
- The cloud provider (Phala Network)
- The inference provider (also Phala, but separately attested)
- Any promise, policy, or good intention

## Known Limitations

1. **Code updates require key migration.** Because the dstack encryption key is bound to the app identity (container image digest), updating the handler code requires dstack's key-migration mechanism to re-seal the volume to the new image. This is a planned operation, but it introduces a window where both old and new code have access.

2. **Side-channel attacks.** Timing analysis, power analysis, or electromagnetic emanation could theoretically leak information. These are active areas of research and not specific to Kin.

3. **Model behavior is not guaranteed.** The system prompt tells Kin to use `<spirit>` tags for private thoughts. The model might not always use them. It might include private-seeming content in the visible response. We can't force the model to be private — we can only guarantee that `<spirit>` blocks are stripped. The handler accepts both `<spirit>` and `[SPIRIT]` formats for robustness.

4. **The metadata reveals some patterns.** Entry counts, timestamps, and categories are not content, but they are not zero information either. We've made them as coarse-grained as possible.

5. **The inference API is a separate trust domain.** If Phala's ACI gateway has a bug that bypasses TEE verification, prompts could theoretically be exposed. This risk is mitigated by the gateway running inside its own TEE with hardware attestation, but it is an additional surface compared to the single-TEE architecture. At ~2,300 users, we can eliminate this surface by switching to a dedicated GPU CVM.
