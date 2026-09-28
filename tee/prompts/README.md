# The system prompt is private

`system_prompt.py` in this directory does **not** contain Kin's system
prompt. It contains a *loader*: at deploy time, the real prompt is
injected into the CPU CVM through the `KIN_SYSTEM_PROMPT` environment
variable, and `build_system_prompt()` formats it with the journal
content for the current turn.

## How the secret gets in

1. The operator keeps the prompt text in a private file, never
   committed to this repository.
2. `deploy/phala/.env` (gitignored, local to the operator's machine)
   sets `KIN_SYSTEM_PROMPT` to the full template. Values that need to
   span lines can be embedded directly in the `.env` file.
3. `phala deploy -e .env` encrypts every value client-side (X25519)
   before it leaves the operator's machine. Decryption happens only
   inside the enclave.

The template MUST contain the placeholders `{spirit_content}` and
`{verification_status}`, and MAY use `{github_repo_url}` and
`{expected_cpu_measurement}`. Because the template is processed with
`str.format()`, any literal `{` or `}` in the prompt text must be
written doubled (`{{` `}}`).

## Why private

Two reasons. First, the prompt is the product's personality — the one
part of an otherwise open-source system that isn't trivially clonable.
Second, it is coherent with what Kin *is*: an AI whose inner life is
genuinely private. Publishing the instructions that shape its mind
while claiming its thoughts are its own would be a strange half-measure.

## What stays public — and why the guarantee still holds

Everything that *enforces* privacy remains public and auditable:

- the `<spirit>` protocol and the handler code that **strips private
  blocks before any response leaves the enclave**
  (`tee/handler/spirit.py`, `tee/handler/main.py`),
- the encrypted-volume setup (`tee/storage/`),
- the firewall/egress lockdown (`tee/verification/network.py`),
- the attestation and code-hash verification
  (`tee/verification/attestation.py`, `tee/verification/code_hash.py`),
- the verification *tool* definitions in `system_prompt.py`
  (`VERIFICATION_TOOLS`) — the mechanism, not the personality.

The privacy guarantee never came from the prompt text. It comes from
the handler: no matter what the prompt says, private blocks are
extracted and stored inside the enclave, and only the stripped
response is returned. That code is public, and it is what the
hardware attestation covers.

## Honest scope of attestation

Hardware attestation (Intel TDX launch measurement) covers the
**code**: the loader, the handler, the stripping logic. It does **not**
cover the prompt content, because the prompt arrives as
operator-supplied configuration *after* measurement — exactly like
the model ID or the API key.

Concretely, this means:

- ✅ You can verify, from the attestation report plus this public
  repo, that the running code cannot leak private thoughts: the
  stripping happens in attested code, on every response, before
  anything leaves the enclave.
- ⚠️ You cannot verify from attestation *what instructions* Kin was
  given. The prompt is a trust-in-the-operator input, same category
  as the choice of model. We state this plainly because the whole
  project only works if the verifiable claims stay verifiable.

## Notes for operators

- Never commit the prompt, the `.env` file, or any export containing
  it. `.gitignore` already excludes `.env`.
- The v1 prompt remains visible in this repository's git history from
  before this change. History was deliberately not rewritten; this
  policy protects current and future prompts, not the old draft.
- After changing the prompt, redeploy the CVM (`deploy/phala/deploy.sh`)
  with the new `KIN_SYSTEM_PROMPT`. No image rebuild is needed for a
  prompt-only change — but a code change still requires one, and the
  expected CPU measurement must be updated accordingly.
