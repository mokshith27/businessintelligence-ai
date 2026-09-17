from pathlib import Path
import json


# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

CAUSAL_EVIDENCE_PATH = (
    PROJECT_ROOT
    / "data"
    / "causal"
    / "causal_evidence_record.json"
)

DIAGNOSTICS_PATH = (
    PROJECT_ROOT
    / "data"
    / "causal"
    / "causal_diagnostics.json"
)

OUTPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "causal"
    / "causal_production_status.json"
)


# ============================================================
# LOAD
# ============================================================

def load_json(path):

    if not path.exists():

        raise FileNotFoundError(
            f"Required file not found:\n{path}"
        )

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


# ============================================================
# DETERMINE PRODUCTION STATUS
# ============================================================

def determine_status(
    evidence,
    diagnostics,
):

    evidence_status = evidence.get(
        "status"
    )

    diagnostic_status = diagnostics.get(
        "assessment",
        {},
    ).get(
        "diagnostic_status"
    )

    diagnostic_confidence = diagnostics.get(
        "assessment",
        {},
    ).get(
        "diagnostic_confidence",
        0.0
    )

    # --------------------------------------------------------
    # Causal evidence unavailable
    # --------------------------------------------------------

    if evidence_status in {
        "INSUFFICIENT_SAMPLE",
        "NO_CAUSAL_IDENTIFICATION",
        "INCONCLUSIVE",
        "UNCERTAIN",
    }:

        return {

            "production_status":
                "CAUSAL_NOT_ACTIONABLE",

            "confidence":
                0.0,

            "decision":
                "DO_NOT_USE_FOR_CAUSAL_ACTION",

            "reason":
                (
                    "The causal estimate does not provide "
                    "sufficient evidence for action."
                ),
        }

    # --------------------------------------------------------
    # Diagnostics require review
    # --------------------------------------------------------

    if diagnostic_status == (
        "CAUSAL_RESULT_REQUIRES_REVIEW"
    ):

        return {

            "production_status":
                "CAUSAL_CAVEAT",

            "confidence":
                min(
                    float(
                        diagnostic_confidence
                    ),
                    0.40,
                ),

            "decision":
                "DO_NOT_USE_FOR_HIGH_IMPACT_ACTION",

            "reason":
                (
                    "The causal estimate has diagnostic "
                    "concerns and should not drive a "
                    "high-impact intervention."
                ),
        }

    # --------------------------------------------------------
    # Balance warning
    # --------------------------------------------------------

    if diagnostic_status == (
        "CAUSAL_RESULT_WITH_BALANCE_WARNING"
    ):

        return {

            "production_status":
                "CAUSAL_WITH_CAVEAT",

            "confidence":
                min(
                    float(
                        diagnostic_confidence
                    ),
                    0.65,
                ),

            "decision":
                "SUPPORT_INVESTIGATION",

            "reason":
                (
                    "The causal estimate is informative "
                    "but diagnostics contain balance warnings."
                ),
        }

    # --------------------------------------------------------
    # Clean enough for production evidence
    # --------------------------------------------------------

    if diagnostic_status == (
        "CAUSAL_RESULT_DIAGNOSTICALLY_ACCEPTABLE"
    ):

        return {

            "production_status":
                "CAUSAL_EVIDENCE_ACCEPTED",

            "confidence":
                min(
                    float(
                        diagnostic_confidence
                    ),
                    0.80,
                ),

            "decision":
                "SUPPORT_ACTION",

            "reason":
                (
                    "The causal estimate passed the "
                    "implemented overlap and basic balance "
                    "diagnostics."
                ),
        }

    # --------------------------------------------------------
    # Safe default
    # --------------------------------------------------------

    return {

        "production_status":
            "CAUSAL_CAVEAT",

        "confidence":
            0.20,

        "decision":
            "INVESTIGATE",

        "reason":
            "Causal evidence status is not sufficiently established.",
    }


# ============================================================
# BUILD PRODUCTION RECORD
# ============================================================

def build_status():

    evidence = load_json(
        CAUSAL_EVIDENCE_PATH
    )

    diagnostics = load_json(
        DIAGNOSTICS_PATH
    )

    status = determine_status(
        evidence,
        diagnostics,
    )

    result = {

        "treatment":
            evidence.get(
                "treatment"
            ),

        "outcome":
            evidence.get(
                "outcome"
            ),

        "effect_estimate":
            evidence.get(
                "effect_estimate"
            ),

        "confidence":
            status[
                "confidence"
            ],

        "production_status":
            status[
                "production_status"
            ],

        "decision":
            status[
                "decision"
            ],

        "reason":
            status[
                "reason"
            ],

        "diagnostic_status":
            diagnostics.get(
                "assessment",
                {},
            ).get(
                "diagnostic_status"
            ),
    }

    return result


# ============================================================
# DISPLAY
# ============================================================

def display_status(
    result,
):

    print("\n")
    print("=" * 100)
    print("BusinessIntelligence.ai")
    print("CAUSAL PRODUCTION STATUS")
    print("=" * 100)

    print(
        f"\nTreatment          : "
        f"{result['treatment']}"
    )

    print(
        f"Outcome            : "
        f"{result['outcome']}"
    )

    print(
        f"Effect estimate    : "
        f"{result['effect_estimate']:+.4f}"
    )

    print(
        f"Production status  : "
        f"{result['production_status']}"
    )

    print(
        f"Confidence         : "
        f"{result['confidence']:.3f}"
    )

    print(
        f"Decision           : "
        f"{result['decision']}"
    )

    print(
        f"\nReason:\n"
        f"{result['reason']}"
    )


# ============================================================
# SAVE
# ============================================================

def save_status(
    result,
):

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_PATH.write_text(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return OUTPUT_PATH


# ============================================================
# MAIN
# ============================================================

def main():

    result = build_status()

    display_status(
        result
    )

    path = save_status(
        result
    )

    print("\n")
    print("=" * 100)
    print("CAUSAL PRODUCTION STATUS COMPLETE")
    print("=" * 100)

    print(
        f"Saved: {path}"
    )


if __name__ == "__main__":
    main()