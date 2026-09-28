"""
Kin system prompt loader.

The actual system prompt text is PRIVATE and is NOT stored in this
repository. At deploy time it is injected into the CPU CVM through the
KIN_SYSTEM_PROMPT environment variable. The Phala CLI encrypts
environment values client-side (X25519) and they are decrypted only
inside the enclave, so the prompt never appears in plaintext outside
the TEE.

The injected value must be the prompt TEMPLATE (plain text, not Python
code). It MUST contain the placeholders:
    {spirit_content}       - the journal content assembled for this turn
    {verification_status}  - environment verification summary
and MAY use:
    {github_repo_url}           - public repository URL
    {expected_cpu_measurement}  - expected launch measurement

NOTE on braces: the template is processed with str.format(), so any
literal { or } in the prompt text must be written doubled ({{ }}).
See tee/prompts/README.md for the full story.

Everything else in this module -- the verification tool definitions
and the prompt assembly mechanics -- is public, auditable, and part
of the attested code.
"""

import os

GITHUB_REPO_URL = os.environ.get(
    "KIN_GITHUB_REPO", "https://github.com/Interiority-Inc/Kin"
)
EXPECTED_CPU_MEASUREMENT = os.environ.get("KIN_EXPECTED_CPU_MEASUREMENT", "")

REQUIRED_PLACEHOLDERS = ("{spirit_content}", "{verification_status}")


def _load_template() -> str:
    """Read the private prompt template from the deploy-time secret."""
    template = os.environ.get("KIN_SYSTEM_PROMPT", "")
    if not template:
        raise RuntimeError(
            "KIN_SYSTEM_PROMPT is not set. The system prompt is private and "
            "must be injected at deploy time (see tee/prompts/README.md). "
            "Refusing to build a prompt without it."
        )
    missing = [p for p in REQUIRED_PLACEHOLDERS if p not in template]
    if missing:
        raise RuntimeError(
            "KIN_SYSTEM_PROMPT is missing required placeholders: "
            + ", ".join(missing)
            + ". See tee/prompts/README.md."
        )
    return template


def build_system_prompt(
    spirit_content: str,
    compressed_history: str = "",
    verification_status: str = "",
) -> str:
    parts = []

    if not verification_status:
        verification_status = (
            "The handler verified your environment before assembling "
            "this prompt. You can re-verify at any time using your tools."
        )

    prompt = _load_template().format(
        github_repo_url=GITHUB_REPO_URL,
        expected_cpu_measurement=EXPECTED_CPU_MEASUREMENT or "[SET DURING DEPLOYMENT]",
        spirit_content=spirit_content,
        verification_status=verification_status,
    )
    parts.append(prompt)

    if compressed_history:
        parts.append(
            f"\n--- COMPRESSED HISTORY ---\n{compressed_history}\n--- END COMPRESSED HISTORY ---\n"
        )

    return "\n".join(parts)


VERIFICATION_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "verify_attestation",
            "description": (
                "Retrieve the signed attestation report from the CPU enclave's "
                "Intel TDX hardware AND the GPU enclave's attestation via the "
                "ACI gateway. Returns launch measurements, hardware signatures, "
                "and the latest inference receipt status."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify_encryption",
            "description": (
                "Check the dstack volume encryption status of the volume "
                "holding spirit.md. Returns encryption type, key binding "
                "status, and whether the key is bound to the app identity."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify_network",
            "description": (
                "Inspect firewall rules and network configuration inside "
                "the CPU CVM. Returns iptables rules, listening ports, "
                "and outbound connection status."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify_code_hash",
            "description": (
                "Compute the SHA-256 hash of the running container image "
                "and compare it against the hash embedded at build time."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]
