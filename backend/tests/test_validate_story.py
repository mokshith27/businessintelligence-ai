"""End-to-end integration tests for validate_story.

Uses a minimal but structurally realistic insight so the tests are
self-contained and do not require generated pipeline artifacts.
"""

import pytest

from llm.narrative_validator import validate_story


@pytest.fixture
def insight():
    return {
        "kpi": {
            "currency": "BRL",
            "currency_symbol": "R$",
        },
        "movement": {
            "previous_gmv": 100000.0,
            "current_gmv": 150000.0,
            "gmv_change": 50000.0,
            "orders_change": 25.0,
            "volume_effect": 60000.0,
            "aov_effect": -10000.0,
        },
        "event": {},
        "review_evidence": {},
        "customer_experience": {},
        "drivers": [],
    }


def test_fully_grounded_story_passes(insight):
    story = (
        "The Marketplace GMV increased by R$50,000.00, from "
        "R$100,000.00 to R$150,000.00. Volume contributed 120.00% "
        "while AOV contributed 20.00%."
    )
    result = validate_story(story, insight, "executive")
    assert result["passed"] is True


def test_hallucinated_number_rejected(insight):
    story = (
        "The Marketplace GMV increased by R$50,000.00. "
        "Approximately 82% of the change is unexplained."
    )
    result = validate_story(story, insight, "executive")
    assert result["passed"] is False
    numbers = result["checks"]["numbers"]
    assert "82%" in numbers["unsupported_claims"]


def test_derived_percentage_not_in_evidence_rejected(insight):
    # 47% is not present in the evidence - only 25% order change and
    # the 120/20 decomposition percentages are allowed.
    story = (
        "The Marketplace GMV increased by R$50,000.00, which is "
        "approximately 47% of the baseline."
    )
    result = validate_story(story, insight, "executive")
    assert result["passed"] is False
    numbers = result["checks"]["numbers"]
    assert "47%" in numbers["unsupported_claims"]


def test_ok_story_with_uncertain_driver_demands_uncertainty(insight):
    insight["drivers"] = [
        {
            "driver": "SP customer state",
            "status": "WEAK",
            "action": {"decision": "INVESTIGATE"},
        }
    ]
    # Story summarizes the figure but never mentions uncertainty.
    story = (
        "The Marketplace GMV increased by R$50,000.00. The main "
        "driver was SP customer state."
    )
    result = validate_story(story, insight, "executive")
    assert result["passed"] is False
    assert result["checks"]["uncertainty"]["passed"] is False

    # Same story WITH uncertainty language passes.
    story_ok = story + " However, the evidence is limited and requires further investigation."
    result_ok = validate_story(story_ok, insight, "executive")
    assert result_ok["passed"] is True


def test_contradicted_driver_as_actionable_rejected(insight):
    insight["drivers"] = [
        {
            "driver": "promotion driver",
            "status": "CONTRADICTED",
            "action": {"decision": "DO_NOT_ACT"},
        }
    ]
    story = (
        "GMV increased by R$50,000.00. We should act on the "
        "promotion driver immediately."
    )
    result = validate_story(story, insight, "executive")
    assert result["passed"] is False
    assert result["checks"]["statuses"]["violations"]