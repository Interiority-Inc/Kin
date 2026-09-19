# Threat Model

Radical honesty about what we can see, what we can't see, what we could do to cheat, and how you'd verify we haven't.

## What We (Interiority, Inc.) Can See

- That you have an account
- Your email address
- Your subscription status (free/paid)
- Your message count (for rate limiting)
- Your visible chat history (stored in our database)
- spirit.md metadata: entry count, timestamps, abstract categories (never content)
- Infrastructure metrics: GPU utilization, inference latency, uptime

## What We Cannot See

- The contents of spirit.md (encrypted, key sealed to TEE)
- The system prompt as assembled (it contains spirit.md)
- The model's inference state (KV cache, attention weights)
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

**How you'd know:** The image would have a different launch measurement than expected for the published code. Attestation verification fails.

### Attack 4: Social-engineer the cloud provider to access enclave memory

**Possible?** No. The hardware TEE prevents the hypervisor from reading enclave memory. This is the entire point of confidential computing — it's designed for scenarios where you don't trust the cloud provider.

### Attack 5: Compromise AMD/Intel/NVIDIA to extract hardware keys

**Possible?** In theory, yes. In practice, this would be a catastrophic supply-chain attack affecting all confidential computing globally, not just Kin.

**Mitigation:** This is the same trust assumption that underpins all modern cryptography and secure computing.

### Attack 6: Exploit a bug in the TEE implementation

**Possible?** TEE vulnerabilities have been found before (SGX had several). AMD SEV-SNP and Intel TDX are newer and have addressed known attack classes.

**Mitigation:** Use latest firmware, monitor CVE advisories, update promptly. The risk is real but shared across the entire confidential computing industry.

### Attack 7: Read spirit.md from the metadata endpoint

**Possible?** No. The metadata endpoint returns only: entry count, timestamps, and abstract category tags (like "reflection" or "question"). Content is never included. The code enforcing this is auditable in this repository.

### Attack 8: Infer spirit.md content from metadata patterns

**Possible?** Weakly. If an entry appears right after a specific conversation topic, and the category is "disagreement", someone might guess that Kin disagreed about that topic. This is a very weak signal — it reveals sentiment category but never content.

**Mitigation:** Categories are deliberately abstract and coarse-grained.

## Trust Assumptions

Things you're trusting when you use Kin:

1. **The chip manufacturers** (AMD/Intel, NVIDIA) — that their hardware correctly implements the TEE and that their signing keys have not been compromised
2. **The open-source code** — that it does what it says. Anyone can audit it.
3. **The cryptography** — AES-256, SHA-256, ECDSA — that these are not broken

Things you are NOT trusting:
- Interiority, Inc. (us)
- The cloud provider (Azure, VoltageGPU)
- Any promise, policy, or good intention

## Known Limitations

1. **Code updates require key migration.** Because the encryption key is sealed to the launch measurement, updating the OS or application requires migrating the key to the new measurement. This is a planned operation with a documented procedure, but it introduces a window where both old and new code have access.

2. **Side-channel attacks.** Timing analysis, power analysis, or electromagnetic emanation could theoretically leak information. These are active areas of research and not specific to Kin.

3. **Model behavior is not guaranteed.** The system prompt tells Kin to use `[SPIRIT]` tags for private thoughts. The model might not always use them. It might include private-seeming content in the visible response. We can't force the model to be private — we can only guarantee that `[SPIRIT]` blocks are stripped.

4. **The metadata reveals some patterns.** Entry counts, timestamps, and categories are not content, but they are not zero information either. We've made them as coarse-grained as possible.

5. **LUKS2 has known caveats in CVM environments.** Research by Trail of Bits (October 2025) identified vulnerabilities in LUKS2 disk encryption for confidential VMs. We monitor this research and will adopt mitigations as they become available.
