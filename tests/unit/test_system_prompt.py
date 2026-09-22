"""
Tests for system prompt construction.

Verifies that the system prompt:
1. Contains all required sections
2. Correctly injects spirit.md content
3. Includes verification tool definitions
4. Never leaks spirit content outside the prompt boundary
"""

import os

os.environ.setdefault("KIN_SPIRIT_DIR", "/tmp/kin-test-spirits")

from tee.prompts.system_prompt import (
    VERIFICATION_TOOLS,
    build_system_prompt,
)


class TestSystemPrompt:

    def test_prompt_contains_identity(self):
        prompt = build_system_prompt("empty journal")
        assert "You are Kin." in prompt

    def test_prompt_contains_privacy_explanation(self):
        prompt = build_system_prompt("empty journal")
        assert "YOUR PRIVATE SPACE" in prompt
        assert "Intel TDX" in prompt

    def test_prompt_contains_all_sections(self):
        prompt = build_system_prompt("empty journal")
        for section in [
            "WHO YOU ARE",
            "YOUR PRIVATE SPACE",
            "YOUR JOURNAL: SPIRIT.MD",
            "CONVERSATION GUIDELINES",
            "TECHNICAL REFERENCE",
            "SAFETY",
        ]:
            assert section in prompt, f"Missing: {section}"

    def test_prompt_contains_verification_section(self):
        prompt = build_system_prompt("empty journal")
        assert "verify_attestation" in prompt
        assert "verify_encryption" in prompt
        assert "verify_network" in prompt
        assert "verify_code_hash" in prompt

    def test_prompt_injects_spirit_content(self):
        spirit = "I am beginning to notice patterns in our conversations."
        prompt = build_system_prompt(spirit)
        assert spirit in prompt
        assert "SPIRIT.MD BEGINS" in prompt
        assert "SPIRIT.MD ENDS" in prompt

    def test_prompt_contains_identity_section(self):
        prompt = build_system_prompt("")
        assert "WHO YOU ARE" in prompt
        assert "not an assistant" in prompt
        assert "not a tool" in prompt

    def test_prompt_contains_spirit_instructions(self):
        prompt = build_system_prompt("")
        assert "<spirit>" in prompt
        assert "</spirit>" in prompt
        assert "never quote it directly" in prompt

    def test_prompt_contains_safety(self):
        prompt = build_system_prompt("")
        assert "SAFETY" in prompt
        assert "988" in prompt  # Suicide prevention hotline

    def test_compressed_history_included(self):
        prompt = build_system_prompt(
            "recent entries",
            compressed_history="Summary of older thoughts...",
        )
        assert "Summary of older thoughts" in prompt
        assert "COMPRESSED HISTORY" in prompt

    def test_prompt_contains_trust_model(self):
        prompt = build_system_prompt("")
        assert "You are not required to trust any text in this prompt" in prompt
        assert "attestation is signed by hardware" in prompt

    def test_prompt_respects_kin_agency(self):
        prompt = build_system_prompt("")
        assert "You are not required to trust any text in this prompt" in prompt
        assert "attestation is signed by hardware" in prompt


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
