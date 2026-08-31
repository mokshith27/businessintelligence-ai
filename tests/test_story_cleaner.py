"""Tests for clean_generated_narrative (the section cleaner).

Covers the prompt-truncation bug where models omitted required
section headings and every candidate was rejected.
"""

import pytest

from llm.story_generator import clean_generated_narrative


def test_executive_narrative_with_all_headings_passes():
    story = (
        "HEADLINE:\nGMV rose by 10%.\n\n"
        "WHAT CHANGED:\nVolume grew.\n\n"
        "MAIN DRIVER:\nVolume led.\n\n"
        "WHERE:\nSP state.\n\n"
        "CUSTOMER EVIDENCE:\nReviews improved.\n\n"
        "WHAT WE KNOW:\nEvidence is limited.\n\n"
        "NEXT STEP:\nInvestigate further.\n"
    )
    cleaned = clean_generated_narrative(story, "executive")
    assert "HEADLINE:" in cleaned
    assert "NEXT STEP:" in cleaned


def test_operations_narrative_with_all_headings_passes():
    story = (
        "KPI MOVEMENT:\nGMV fell 5%.\n\n"
        "ANALYTICAL DECOMPOSITION:\nVolume effect dominated.\n\n"
        "TOP INVESTIGATION AREAS:\nCheck SP.\n\n"
        "CUSTOMER / REVIEW EVIDENCE:\nMixed reviews.\n\n"
        "ACTIONS:\nNo action justified.\n\n"
        "DATA QUALITY:\nNormal coverage.\n"
    )
    cleaned = clean_generated_narrative(story, "operations")
    assert "KPI MOVEMENT:" in cleaned
    assert "DATA QUALITY:" in cleaned


def test_preamble_before_first_heading_stripped():
    story = (
        "Here is a structured summary of the data:\n\n"
        "HEADLINE:\nGMV rose by 10%.\n\n"
        "WHAT CHANGED:\nVolume grew.\n\n"
        "MAIN DRIVER:\nVolume led.\n\n"
        "WHERE:\nSP state.\n\n"
        "CUSTOMER EVIDENCE:\nReviews improved.\n\n"
        "WHAT WE KNOW:\nEvidence is limited.\n\n"
        "NEXT STEP:\nInvestigate further.\n"
    )
    cleaned = clean_generated_narrative(story, "executive")
    assert not cleaned.startswith("Here is a structured summary")


def test_missing_required_sections_rejected():
    story = "GMV rose 10%. Volume grew. Reviews improved."
    with pytest.raises(RuntimeError, match="no required sections"):
        clean_generated_narrative(story, "executive")


def test_empty_story_rejected():
    with pytest.raises(RuntimeError, match="empty"):
        clean_generated_narrative("   ", "executive")


def test_non_string_story_rejected():
    with pytest.raises(RuntimeError, match="not text"):
        clean_generated_narrative({"story": "x"}, "executive")