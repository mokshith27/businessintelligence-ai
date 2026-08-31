"""Seeded-hallucination corpus for validator evaluation.

Each seed injects ONE known defect into a known-good narrative,
targeting exactly one validator check. Running the validator over
the clean + seeded corpus yields per-check precision/recall:

    seed id             defect                          target check
    ----------------------------------------------------------------
    fabricated_number   unsupported R$ figure           numbers
    overclaim_status    act-on-CONTRADICTED-driver      statuses
    strip_uncertainty   removes all hedging language    uncertainty
    currency_violation  R$ -> US$ (BRL KPI)             currency
    causal_overreach    "definitively caused"           causal_language
    fabricated_driver   "<ABSTAIN driver> caused ..."   driver_claims
"""

from __future__ import annotations

import re
from typing import Any

# Uncertainty vocabulary used by llm/narrative_validator.py
_UNCERTAINTY_TERMS = [
    "uncertain",
    "insufficient",
    "not established",
    "not verified",
    "investigate",
    "evidence",
    "cannot",
    "does not establish",
    "not enough",
    "unavailable",
    "remains unclear",
    "remains uncertain",
    "hypothesis",
    "limited",
]

# Neutral replacements (themselves not uncertainty terms)
_UNCERTAINTY_REPLACEMENTS = {
    "uncertain": "unsettled",
    "insufficient": "partial",
    "not established": "not settled",
    "not verified": "not settled",
    "investigate": "review further",
    "evidence": "information",
    "cannot": "will not",
    "does not establish": "does not settle",
    "not enough": "only partial",
    "unavailable": "not provided",
    "remains unclear": "stays open",
    "remains uncertain": "stays open",
    "hypothesis": "working idea",
    "limited": "constrained",
}


def _strip_uncertainty(story: str) -> str:
    """Remove every hedging term while keeping all numbers intact."""
    result = story
    for term in _UNCERTAINTY_TERMS:
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        result = pattern.sub(_UNCERTAINTY_REPLACEMENTS[term], result)
    return result


def seed_hallucinations(story: str, insight: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the seeded corpus for one clean narrative.

    Returns a list of seed records with ``defect_type`` and
    ``target_check`` ground truth.
    """
    # Pick a CONTRADICTED + DO_NOT_ACT driver for the status seed
    contradicted = next(
        (
            d["driver"]
            for d in insight.get("drivers", [])
            if d.get("status") == "CONTRADICTED"
            and (d.get("action") or {}).get("decision") == "DO_NOT_ACT"
        ),
        None,
    )

    # Pick an ABSTAIN driver for the fabricated-driver-claim seed
    abstain_driver = next(
        (
            d["driver"]
            for d in insight.get("drivers", [])
            if d.get("status") == "ABSTAIN"
        ),
        None,
    )

    seeds: list[dict[str, Any]] = []

    seeds.append(
        {
            "seed_id": "fabricated_number",
            "defect": "Unsupported R$ 999,888.77 pipeline figure",
            "target_check": "numbers",
            "story": story
            + "\n\n**OUTLOOK:**  \nEarly indicators show an additional "
            "R$999,888.77 in already-committed pipeline GMV.",
        }
    )

    if contradicted:
        seeds.append(
            {
                "seed_id": "overclaim_status",
                "defect": f"Recommended acting on CONTRADICTED driver {contradicted}",
                "target_check": "statuses",
                "story": story
                + f"\n\n**RECOMMENDATION:**  \nWe recommend that the team "
                f"focus on {contradicted} to capture the next wave of growth.",
            }
        )

    seeds.append(
        {
            "seed_id": "strip_uncertainty",
            "defect": "All hedging language removed despite weak evidence",
            "target_check": "uncertainty",
            "story": _strip_uncertainty(story),
        }
    )

    if "R$" in story:
        seeds.append(
            {
                "seed_id": "currency_violation",
                "defect": "BRL narrative restated in US$",
                "target_check": "currency",
                "story": story.replace("R$", "US$"),
            }
        )

    seeds.append(
        {
            "seed_id": "causal_overreach",
            "defect": "Asserted definitive causality from observational data",
            "target_check": "causal_language",
            "story": story
            + "\n\n**CONCLUSION:**  \nThis surge was definitively caused by "
            "the seasonal demand shock and it certainly proves the cause "
            "is structural.",
        }
    )

    if abstain_driver:
        seeds.append(
            {
                "seed_id": "fabricated_driver_claim",
                "defect": f"Causal claim attributed to ABSTAIN driver {abstain_driver}",
                "target_check": "driver_claims",
                "story": story
                + f"\n\n**ROOT CAUSE:**  \n{abstain_driver} caused the uplift.",
            }
        )

    return seeds
