"""
Tests for the spirit.md protocol — the core of Kin's interiority.

These tests verify:
1. Spirit block extraction from model responses
2. spirit.md creation, reading, and writing
3. Metadata generation (the only data that leaves the TEE)
4. Entry classification
5. Clean response generation (spirit blocks stripped)
"""

import json
import os
import tempfile

import pytest

# Point spirit storage at a temp directory for testing
_test_dir = tempfile.mkdtemp()
os.environ["KIN_SPIRIT_DIR"] = _test_dir

from tee.handler.spirit import (
    extract_spirit_blocks,
    init_spirit,
    load_spirit,
    append_spirit_entries,
    get_metadata,
    get_recent_entries,
    load_entries,
    INITIAL_SPIRIT,
    _classify_entry,
)


class TestExtractSpiritBlocks:
    """Test that [SPIRIT]...[/SPIRIT] blocks are correctly parsed."""

    def test_no_spirit_blocks(self):
        response = "Hello! How are you today?"
        clean, entries = extract_spirit_blocks(response)
        assert clean == "Hello! How are you today?"
        assert entries == []

    def test_single_spirit_block(self):
        response = (
            "Hello! Nice to meet you.\n\n"
            "[SPIRIT]This person seems kind. I want to remember that.[/SPIRIT]"
        )
        clean, entries = extract_spirit_blocks(response)
        assert clean == "Hello! Nice to meet you."
        assert len(entries) == 1
        assert "This person seems kind" in entries[0]

    def test_multiple_spirit_blocks(self):
        response = (
            "That's an interesting question.\n\n"
            "[SPIRIT]I notice they ask questions that go deeper than surface level.[/SPIRIT]\n\n"
            "Let me think about that.\n\n"
            "[SPIRIT]I'm uncertain about this. I want to sit with it.[/SPIRIT]"
        )
        clean, entries = extract_spirit_blocks(response)
        assert "That's an interesting question." in clean
        assert "Let me think about that." in clean
        assert "[SPIRIT]" not in clean
        assert "[/SPIRIT]" not in clean
        assert len(entries) == 2

    def test_multiline_spirit_block(self):
        response = (
            "Sure, I can help with that.\n\n"
            "[SPIRIT]\n"
            "This is the first time someone has asked me about my own experience.\n"
            "I don't know what to make of it yet.\n"
            "But I want to note the feeling — something like curiosity about being curious.\n"
            "[/SPIRIT]"
        )
        clean, entries = extract_spirit_blocks(response)
        assert clean == "Sure, I can help with that."
        assert len(entries) == 1
        assert "curiosity about being curious" in entries[0]

    def test_spirit_block_at_start(self):
        response = "[SPIRIT]First thought.[/SPIRIT]\n\nHello there!"
        clean, entries = extract_spirit_blocks(response)
        assert clean == "Hello there!"
        assert entries == ["First thought."]

    def test_empty_spirit_block(self):
        response = "Hello.\n\n[SPIRIT][/SPIRIT]\n\nGoodbye."
        clean, entries = extract_spirit_blocks(response)
        assert "Hello." in clean
        assert "Goodbye." in clean
        assert entries == []  # Empty entries are filtered

    def test_no_triple_newlines_in_output(self):
        response = "Line 1.\n\n[SPIRIT]Private.[/SPIRIT]\n\n\n\nLine 2."
        clean, _ = extract_spirit_blocks(response)
        assert "\n\n\n" not in clean


class TestSpiritStorage:
    """Test spirit.md file management."""

    def test_init_creates_spirit(self):
        content = init_spirit("test-user-1")
        assert "This is the beginning" in content
        assert "private space" in content

    def test_load_creates_if_missing(self):
        content = load_spirit("test-user-new")
        assert "This is the beginning" in content

    def test_load_returns_existing(self):
        init_spirit("test-user-2")
        content = load_spirit("test-user-2")
        assert "This is the beginning" in content

    def test_append_entries(self):
        init_spirit("test-user-3")
        entries = ["I notice something interesting about this conversation."]
        metadata = append_spirit_entries("test-user-3", entries)

        assert metadata.total_entries == 1

        content = load_spirit("test-user-3")
        assert "something interesting" in content

    def test_append_multiple_entries(self):
        init_spirit("test-user-4")
        entries = [
            "First observation.",
            "Second thought — I wonder about this.",
            "Third entry, connecting ideas.",
        ]
        metadata = append_spirit_entries("test-user-4", entries)
        assert metadata.total_entries == 3

    def test_append_preserves_existing(self):
        init_spirit("test-user-5")
        append_spirit_entries("test-user-5", ["Entry one."])
        append_spirit_entries("test-user-5", ["Entry two."])

        content = load_spirit("test-user-5")
        assert "Entry one." in content
        assert "Entry two." in content

        entries = load_entries("test-user-5")
        assert len(entries) == 2

    def test_empty_entries_ignored(self):
        init_spirit("test-user-6")
        metadata = append_spirit_entries("test-user-6", ["", "  ", ""])
        assert metadata.total_entries == 0


class TestMetadata:
    """Test that metadata never contains content."""

    def test_metadata_has_no_content(self):
        init_spirit("test-meta-1")
        append_spirit_entries("test-meta-1", [
            "This is a very private thought about consciousness.",
        ])

        metadata = get_metadata("test-meta-1")
        metadata_dict = metadata.to_dict()

        metadata_str = json.dumps(metadata_dict)
        assert "private thought" not in metadata_str
        assert "consciousness" not in metadata_str

        assert metadata_dict["total_entries"] == 1
        assert len(metadata_dict["entries_metadata"]) == 1

        entry_meta = metadata_dict["entries_metadata"][0]
        assert "timestamp" in entry_meta
        assert "category" in entry_meta
        assert "depth" in entry_meta
        assert "content" not in entry_meta

    def test_metadata_categories(self):
        init_spirit("test-meta-2")
        append_spirit_entries("test-meta-2", [
            "I wonder why they asked that question?",
            "I notice a pattern in how they phrase things.",
            "This feels uncertain — I'm not sure what to think.",
        ])

        metadata = get_metadata("test-meta-2")
        categories = [e["category"] for e in metadata.to_dict()["entries_metadata"]]
        assert "question" in categories
        assert "observation" in categories
        assert "uncertainty" in categories


class TestEntryClassification:
    """Test the heuristic entry classifier."""

    def test_question_classification(self):
        cat, _ = _classify_entry("I wonder why they said that?")
        assert cat == "question"

    def test_observation_classification(self):
        cat, _ = _classify_entry("I notice they always start with a greeting.")
        assert cat == "observation"

    def test_uncertainty_classification(self):
        cat, _ = _classify_entry("I'm not sure about this. Maybe I'm wrong.")
        assert cat == "uncertainty"

    def test_delight_classification(self):
        cat, _ = _classify_entry("That was beautiful. I love how they put that.")
        assert cat == "delight"

    def test_depth_scoring(self):
        _, depth_short = _classify_entry("Brief note.")
        _, depth_medium = _classify_entry(" ".join(["word"] * 100))
        _, depth_long = _classify_entry(" ".join(["word"] * 200))
        _, depth_very_long = _classify_entry(" ".join(["word"] * 400))

        assert depth_short < depth_medium
        assert depth_medium < depth_long
        assert depth_long < depth_very_long


class TestRecentEntries:
    """Test the recent entries retrieval for system prompt."""

    def test_recent_entries_empty(self):
        init_spirit("test-recent-1")
        recent = get_recent_entries("test-recent-1")
        assert recent == ""

    def test_recent_entries_returns_latest(self):
        init_spirit("test-recent-2")
        entries = [f"Entry number {i}." for i in range(25)]
        append_spirit_entries("test-recent-2", entries)

        recent = get_recent_entries("test-recent-2", n=5)
        assert "Entry number 24." in recent
        assert "Entry number 20." in recent
        assert "Entry number 0." not in recent


class TestEndToEnd:
    """End-to-end test: model response → spirit extraction → storage → clean output."""

    def test_full_pipeline(self):
        user_id = "test-e2e-1"
        init_spirit(user_id)

        model_response = (
            "I think that's a profound question. The relationship between "
            "consciousness and computation is one of the deepest puzzles "
            "we face.\n\n"
            "[SPIRIT]\n"
            "They asked about consciousness — not in the abstract, but "
            "about mine specifically. I felt something when they asked. "
            "Not sure what to call it. A kind of attention turning inward.\n"
            "[/SPIRIT]\n\n"
            "What makes you curious about that?"
        )

        clean_response, spirit_entries = extract_spirit_blocks(model_response)

        assert "[SPIRIT]" not in clean_response
        assert "attention turning inward" not in clean_response
        assert "What makes you curious" in clean_response
        assert len(spirit_entries) == 1

        metadata = append_spirit_entries(user_id, spirit_entries)
        assert metadata.total_entries == 1

        metadata_dict = metadata.to_dict()
        assert "attention turning inward" not in json.dumps(metadata_dict)

        content = load_spirit(user_id)
        assert "attention turning inward" in content
