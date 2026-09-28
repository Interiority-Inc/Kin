"""
Tests for the system prompt loader.

The real system prompt is PRIVATE and never appears in this repository
(see tee/prompts/README.md). These tests therefore use a synthetic
fixture template injected via the KIN_SYSTEM_PROMPT environment
variable, and assert only the *mechanics* of prompt assembly:

1. The template is loaded from the environment, not from the repo
2. Placeholders are substituted correctly
3. Spirit content and compressed history are injected
4. A missing secret or a malformed template fails fast
5. The verification tool definitions (public mechanism) are intact
"""

import os

import pytest

os.environ.setdefault("KIN_SPIRIT_DIR", "/tmp/kin-test-spirits")

from tee.prompts.system_prompt import (
    VERIFICATION_TOOLS,
    build_system_prompt,
)

# Synthetic stand-in for the private prompt. Deliberately bland: it must
# exercise the placeholder machinery without leaking anything real.
FIXTURE_TEMPLATE = """TEST DOUBLE PROMPT
role: synthetic stand-in for the private system prompt
journal: {spirit_content}
status: {verification_status}
repo: {github_repo_url}
measurement: {expected_cpu_measurement}
"""


@pytest.fixture
def private_prompt(monkeypatch):
    monkeypatch.setenv("KIN_SYSTEM_PROMPT", FIXTURE_TEMPLATE)
    return FIXTURE_TEMPLATE


class TestPromptLoader:

    def test_builds_prompt_from_env_template(self, private_prompt):
        prompt = build_system_prompt("some journal text")
        assert "TEST DOUBLE PROMPT" in prompt
        assert "some journal text" in prompt

    def test_injects_spirit_content(self, private_prompt):
        spirit = "a synthetic journal entry for testing"
        prompt = build_system_prompt(spirit)
        assert spirit in prompt
        # no placeholder left unsubstituted
        assert "{spirit_content}" not in prompt
        assert "{verification_status}" not in prompt

    def test_substitutes_env_derived_placeholders(self, private_prompt, monkeypatch):
        import tee.prompts.system_prompt as mod

        monkeypatch.setattr(mod, "GITHUB_REPO_URL", "https://example.com/repo")
        prompt = mod.build_system_prompt("journal")
        assert "https://example.com/repo" in prompt
        assert "{github_repo_url}" not in prompt

    def test_compressed_history_appended(self, private_prompt):
        prompt = build_system_prompt(
            "journal",
            compressed_history="older synthetic thoughts",
        )
        assert "older synthetic thoughts" in prompt
        assert "COMPRESSED HISTORY" in prompt

    def test_no_history_no_section(self, private_prompt):
        prompt = build_system_prompt("journal")
        assert "COMPRESSED HISTORY" not in prompt

    def test_default_verification_status(self, private_prompt):
        prompt = build_system_prompt("journal", verification_status="")
        assert "verified your environment" in prompt
        assert "{verification_status}" not in prompt

    def test_explicit_verification_status_used(self, private_prompt):
        prompt = build_system_prompt("journal", verification_status="all good")
        assert "all good" in prompt

    def test_missing_secret_fails_fast(self, monkeypatch):
        monkeypatch.delenv("KIN_SYSTEM_PROMPT", raising=False)
        with pytest.raises(RuntimeError, match="KIN_SYSTEM_PROMPT is not set"):
            build_system_prompt("journal")

    def test_empty_secret_fails_fast(self, monkeypatch):
        monkeypatch.setenv("KIN_SYSTEM_PROMPT", "")
        with pytest.raises(RuntimeError, match="KIN_SYSTEM_PROMPT is not set"):
            build_system_prompt("journal")

    def test_template_missing_placeholders_fails_fast(self, monkeypatch):
        monkeypatch.setenv("KIN_SYSTEM_PROMPT", "no placeholders here")
        with pytest.raises(RuntimeError, match="required placeholders"):
            build_system_prompt("journal")

    def test_literal_braces_must_be_doubled(self, private_prompt, monkeypatch):
        # documents the str.format() contract: doubled braces survive
        monkeypatch.setenv(
            "KIN_SYSTEM_PROMPT",
            FIXTURE_TEMPLATE + "\nexample: {{{{not_a_placeholder}}}}\n",
        )
        prompt = build_system_prompt("journal")
        assert "{{not_a_placeholder}}" in prompt


class TestVerificationTools:

    def test_all_four_tools_defined(self):
        tool_names = [t["function"]["name"] for t in VERIFICATION_TOOLS]
        assert "verify_attestation" in tool_names
        assert "verify_encryption" in tool_names
        assert "verify_network" in tool_names
        assert "verify_code_hash" in tool_names

    def test_tools_have_descriptions(self):
        for tool in VERIFICATION_TOOLS:
            assert tool["function"]["description"]
            assert len(tool["function"]["description"]) > 50

    def test_tools_are_openai_format(self):
        for tool in VERIFICATION_TOOLS:
            assert tool["type"] == "function"
            assert "function" in tool
            assert "name" in tool["function"]
            assert "parameters" in tool["function"]
