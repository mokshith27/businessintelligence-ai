"""Tests for scrub_unsupported_numbers (deterministic grounding guard).

Covers the exact violation classes observed with the local model:
derived numbers ("148 mentions" = 267-119), invented values
("47.6%", "37,082.14"), forbidden record counts ("1411"), and a bare
"$" instead of the contracted BRL "R$".
"""

from llm.story_generator import scrub_unsupported_numbers


INVESTIGATION = {
    "event": {
        "event_id": 66,
        "duration_days": 6,
        "start_date": "2018-08-22",
    },
    "movement": {
        "previous_gmv": 178032.18,
        "current_gmv": 70977.64,
        "gmv_change": -107054.54,
    },
    "decomposition": {
        "volume_effect": -96926.90,
        "aov_effect": -10127.64,
        "volume_share_of_absolute_change_pct": 90.54,
        "aov_share_of_absolute_change_pct": 9.46,
    },
    "drivers": [
        {
            "name": "SP",
            "contribution_pct": -33.65,
            "evidence_status": "WEAK",
        },
        {
            "name": "RJ",
            "contribution_pct": -19.59,
            "evidence_status": "ABSTAIN",
        },
    ],
    "customer_experience": {
        "late_delivery_rate": 0.0079,
        "review_score": 4.16687,
    },
    "review_evidence": {
        "event_review_records": 178,
        "comparison_review_records": 410,
        "aspects": [
            {"aspect": "delivery", "event_mentions": 119,
             "comparison_mentions": 267},
        ],
    },
}


def test_derived_difference_sentence_removed():
    story = (
        "CUSTOMER EVIDENCE:\n"
        "Delivery mentions fell from 267 in the comparison period to "
        "119 in the event period. Delivery issues declined by 148 "
        "mentions compared with the prior window. The evidence is "
        "directional rather than causal."
    )
    cleaned = scrub_unsupported_numbers(story, INVESTIGATION)
    assert "148" not in cleaned
    assert "267" in cleaned
    assert "119" in cleaned


def test_invented_numbers_removed_but_grounded_kept():
    story = (
        "WHAT CHANGED:\n"
        "GMV moved by R$107,054.54 between the two windows. The drop "
        "represents 47.6% of monthly revenue and erased 37,082.14 in "
        "supplier value. Volume effects drove 90.54% of the change."
    )
    cleaned = scrub_unsupported_numbers(story, INVESTIGATION)
    assert "107,054.54" in cleaned
    assert "90.54%" in cleaned
    assert "47.6%" not in cleaned
    assert "37,082.14" not in cleaned


def test_record_counts_removed_even_when_in_evidence():
    story = (
        "DATA QUALITY:\n"
        "Review coverage is strong with 1,411 records available for "
        "analysis. The commerce source is authoritative for this event."
    )
    cleaned = scrub_unsupported_numbers(story, INVESTIGATION)
    assert "1,411" not in cleaned
    assert "authoritative" in cleaned


def test_rounded_review_score_is_grounded():
    story = (
        "WHAT WE KNOW:\n"
        "The review score eased to 4.17 with weak evidence for the "
        "leading driver. The late delivery rate reached 0.79%."
    )
    cleaned = scrub_unsupported_numbers(story, INVESTIGATION)
    assert "4.17" in cleaned
    assert "0.79%" in cleaned


def test_bare_dollar_normalized_to_brl():
    story = (
        "ANALYTICAL DECOMPOSITION:\n"
        "The residual effect was R$0.00 (approximately $0). Volume "
        "dominated with 90.54% of the change."
    )
    cleaned = scrub_unsupported_numbers(story, INVESTIGATION)
    assert "($0)" not in cleaned
    assert "(approximately R$0)" in cleaned


def test_reasoning_sentences_scrubbed_from_sections():
    story = (
        "TOP INVESTIGATION AREAS:\n"
        "We have to pick up to three items tied to evidence. But wait, "
        "the rules say never invent. Customer state SP shows weak "
        "evidence and warrants investigation. Why not mention the "
        "other drivers? They are abstain.\n\n"
        "DATA QUALITY:\n"
        "Review evidence records total 1,411 for this window. The "
        "commerce source is authoritative for this event."
    )
    cleaned = scrub_unsupported_numbers(story, INVESTIGATION)
    assert "We have to" not in cleaned
    assert "But wait" not in cleaned
    assert "Why not" not in cleaned
    assert "SP" in cleaned
    assert "weak" in cleaned
    assert "1,411" not in cleaned
    assert "authoritative" in cleaned


def test_narrative_uncertainty_sentence_survives():
    # "We have weak evidence ..." is legitimate narrative voice and
    # must NOT be treated as chain-of-thought.
    story = (
        "WHAT WE KNOW:\n"
        "We have weak evidence that SP state contributed to the "
        "movement. Root cause is not established."
    )
    cleaned = scrub_unsupported_numbers(story, INVESTIGATION)
    assert "We have weak evidence" in cleaned


def test_section_never_empties():
    story = (
        "NEXT STEP:\n"
        "Spend 47.6% of the budget on a campaign reaching 250 stores."
    )
    cleaned = scrub_unsupported_numbers(story, INVESTIGATION)
    assert cleaned.startswith("NEXT STEP:")
    assert "Evidence status limits" in cleaned

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


def test_all_headings_merged_on_single_lines():
    # Model wrote every heading with its body on the same line.
    story = (
        "Reasoning preamble that mentions HEADLINE and other words.\n\n"
        "HEADLINE: GMV fell 10% in the event window.\n\n"
        "WHAT CHANGED: Orders and AOV both declined.\n\n"
        "MAIN DRIVER: Volume led the decline.\n\n"
        "WHERE: SP state concentrated the drop.\n\n"
        "CUSTOMER EVIDENCE: Review mentions dipped.\n\n"
        "WHAT WE KNOW: Evidence remains weak for most drivers.\n\n"
        "NEXT STEP: Investigate SP before acting.\n"
    )
    cleaned = clean_generated_narrative(story, "executive")
    for heading in (
        "HEADLINE",
        "WHAT CHANGED",
        "MAIN DRIVER",
        "WHERE",
        "CUSTOMER EVIDENCE",
        "WHAT WE KNOW",
        "NEXT STEP",
    ):
        assert f"{heading}:" in cleaned
    assert "GMV fell 10%" in cleaned
    assert not cleaned.startswith("Reasoning")


def test_non_string_story_rejected():
    with pytest.raises(RuntimeError, match="not text"):
        clean_generated_narrative({"story": "x"}, "executive")


def test_duplicate_revised_draft_truncated():
    # Qwen3:4b emits the narrative then a "word count" audit and a
    # second "Revised draft" with duplicated headings. The cleaner must
    # keep only the final complete ordered run.
    story = (
        "We are given an event. Let's break it down.\n\n"
        "HEADLINE:\nGMV fell 10%.\n\n"
        "WHAT CHANGED:\nOrders fell.\n\n"
        "MAIN DRIVER:\nVolume fell.\n\n"
        "WHERE:\nSP state.\n\n"
        "CUSTOMER EVIDENCE:\nReviews dipped.\n\n"
        "WHAT WE KNOW:\nEvidence is weak.\n\n"
        "NEXT STEP:\nCollect more data.\n\n"
        "Now, let's check the word count.\n"
        "HEADLINE: 32 words\nWHAT CHANGED: 45 words\n"
        "Revised draft:\n\n"
        "HEADLINE:\nGMV fell 10% (a serious drop).\n\n"
        "WHAT CHANGED:\nOrders fell sharply.\n\n"
        "MAIN DRIVER:\nVolume effect dominated.\n\n"
        "WHERE:\nThe SP state dealer.\n\n"
        "CUSTOMER EVIDENCE:\nReviews dipped notably.\n\n"
        "WHAT WE KNOW:\nEvidence remains weak.\n\n"
        "NEXT STEP:\nCollect more data before acting.\n"
    )
    cleaned = clean_generated_narrative(story, "executive")
    assert cleaned.count("HEADLINE:") == 1
    assert cleaned.count("NEXT STEP:") == 1
    assert "word count" not in cleaned
    assert "Revised draft" not in cleaned


def test_missing_where_heading_recovered():
    # Model wrote "WHERE:" followed by body on the same line instead of
    # a bare heading line. The cleaner must recover the section.
    story = (
        "HEADLINE:\nGMV fell 10%.\n\n"
        "WHAT CHANGED:\nVolume grew.\n\n"
        "MAIN DRIVER:\nVolume led.\n\n"
        "WHERE: SP state and RJ warehouse.\n\n"
        "CUSTOMER EVIDENCE:\nReviews improved.\n\n"
        "WHAT WE KNOW:\nEvidence is limited.\n\n"
        "NEXT STEP:\nInvestigate further.\n"
    )
    cleaned = clean_generated_narrative(story, "executive")
    assert "WHERE:" in cleaned
    assert "SP state and RJ warehouse" in cleaned


def test_model_reasoning_preamble_stripped():
    # qwen3:4b emits visible chain-of-thought before the narrative.
    story = (
        "We are given a specific event with the event_id 66. "
        "We have to write an executive KPI story.\n"
        "Let's break down the required sections:\n"
        "1. HEADLINE: At least two full sentences...\n\n"
        "HEADLINE:\nGMV fell 10%.\n\n"
        "WHAT CHANGED:\nVolume grew.\n\n"
        "MAIN DRIVER:\nVolume led.\n\n"
        "WHERE:\nSP state.\n\n"
        "CUSTOMER EVIDENCE:\nReviews improved.\n\n"
        "WHAT WE KNOW:\nEvidence is limited.\n\n"
        "NEXT STEP:\nInvestigate further.\n"
    )
    cleaned = clean_generated_narrative(story, "executive")
    assert not cleaned.startswith("We are given")
    assert cleaned.startswith("HEADLINE:")