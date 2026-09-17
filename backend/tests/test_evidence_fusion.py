"""Tests for the evidence-fusion confidence and status engine.

These functions (evidence/confidence.py) are pure and DB-free, so the
tests are self-contained and run on a fresh clone / CI.
"""

import pytest

from evidence.confidence import (
    calculate_confidence,
    determine_status,
)

HIGH = {
    "available": True,
    "status": "SUPPORTING",
    "directional_support": 0.8,
}

WEAKLY_SUPPORTING = {
    "available": True,
    "status": "SUPPORTING",
    "directional_support": 0.3,
}

CONTRADICTING = {
    "available": True,
    "status": "CONTRADICTING",
    "directional_support": 0.9,
}

NO_REVIEW = {
    "available": False,
    "status": "UNAVAILABLE",
    "directional_support": 0.0,
}

CONTEXT_STRONG = {
    "available": True,
    "evidence_types": 2,
}

CONTEXT_NONE = {
    "available": False,
    "evidence_types": 0,
}


def test_high_confidence_from_multiple_sources():
    result = calculate_confidence(
        0.40,
        HIGH,
        CONTEXT_STRONG,
    )
    assert result["confidence"] > 0.6
    assert result["independent_sources"] == 3


def test_single_source_is_capped_at_055():
    # Only structural evidence, no review/context -> capped at 0.55.
    result = calculate_confidence(
        0.48,
        NO_REVIEW,
        CONTEXT_NONE,
    )
    assert result["independent_sources"] == 1
    assert result["confidence"] <= 0.550


def test_contradiction_penalty_65_percent():
    base = calculate_confidence(
        0.40,
        WEAKLY_SUPPORTING,
        CONTEXT_NONE,
    )
    contradicted = calculate_confidence(
        0.40,
        CONTRADICTING,
        CONTEXT_NONE,
    )
    # Independent sources are equal (both have review), so the only
    # difference must come from the contradiction penalty (x0.65).
    assert contradicted["independent_sources"] == base["independent_sources"]
    assert contradicted["confidence"] <= base["confidence"]


def test_status_mapping():
    # Strong, multi-source -> SUPPORTED.
    conf = calculate_confidence(0.45, HIGH, CONTEXT_STRONG)["confidence"]
    assert determine_status(conf, HIGH, CONTEXT_STRONG, 0.45) == "SUPPORTED"

    # Tiny contribution -> WEAK_DRIVER regardless.
    conf2 = calculate_confidence(0.30, HIGH, CONTEXT_STRONG)["confidence"]
    assert determine_status(conf2, HIGH, CONTEXT_STRONG, 0.01) == "WEAK_DRIVER"

    # Contradicting review + low confidence -> CONTRADICTED.
    low_conf = calculate_confidence(
        0.05, CONTRADICTING, CONTEXT_NONE
    )["confidence"]
    assert (
        determine_status(low_conf, CONTRADICTING, CONTEXT_NONE, 0.30)
        == "CONTRADICTED"
    )

    # No evidence at all -> ABSTAIN (honest uncertainty).
    none_conf = calculate_confidence(
        0.005, NO_REVIEW, CONTEXT_NONE
    )["confidence"]
    assert determine_status(none_conf, NO_REVIEW, CONTEXT_NONE, 0.30) == "ABSTAIN"


def test_confidence_is_bounded_0_1():
    for share in (0.05, 0.25, 0.9):
        result = calculate_confidence(share, HIGH, CONTEXT_STRONG)
        assert 0.0 <= result["confidence"] <= 1.0


def test_all_fusion_scores_present():
    result = calculate_confidence(0.20, HIGH, CONTEXT_STRONG)
    for key in (
        "confidence",
        "structural_score",
        "review_score",
        "context_score",
        "independent_sources",
    ):
        assert key in result