from pathlib import Path
import json


# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

CAUSAL_RESULT_PATH = (
    PROJECT_ROOT
    / "data"
    / "causal"
    / "delivery_review_causal_effect.json"
)

OUTPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "causal"
    / "causal_evidence_record.json"
)


# ============================================================
# LOAD CAUSAL RESULT
# ============================================================

def load_causal_result():

    if not CAUSAL_RESULT_PATH.exists():

        raise FileNotFoundError(
            f"Causal result not found:\n"
            f"{CAUSAL_RESULT_PATH}"
        )

    return json.loads(
        CAUSAL_RESULT_PATH.read_text(
            encoding="utf-8"
        )
    )


# ============================================================
# BUILD EVIDENCE RECORD
# ============================================================

def build_causal_evidence(
    result,
):

    status = result.get(
        "status"
    )

    confidence = result.get(
        "confidence",
        0.0
    )

    effect = result.get(
        "causal_effect"
    )

    bootstrap = result.get(
        "bootstrap",
        {}
    )

    ci_lower = bootstrap.get(
        "ci_lower"
    )

    ci_upper = bootstrap.get(
        "ci_upper"
    )

    treatment = result.get(
        "treatment"
    )

    outcome = result.get(
        "outcome"
    )

    return {

        "evidence_type":
            "CAUSAL_OBSERVATIONAL",

        "treatment":
            treatment,

        "outcome":
            outcome,

        "effect_estimate":
            effect,

        "confidence":
            confidence,

        "interval":
            {
                "lower":
                    ci_lower,

                "upper":
                    ci_upper,
            },

        "status":
            status,

        "interpretation":
            result.get(
                "interpretation"
            ),

        "method":
            result.get(
                "method"
            ),

        "sample_size":
            result.get(
                "sample_size"
            ),

        "treated":
            result.get(
                "treated"
            ),

        "control":
            result.get(
                "control"
            ),

        "overlap":
            result.get(
                "overlap",
                {}
            ),

        "assumptions":
            result.get(
                "causal_assumptions",
                []
            ),

        "limitations":
            result.get(
                "limitations",
                []
            ),
    }


# ============================================================
# SAVE
# ============================================================

def save_record(
    record,
):

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_PATH.write_text(
        json.dumps(
            record,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


# ============================================================
# DISPLAY
# ============================================================

def display_record(
    record,
):

    print("\n")
    print("=" * 100)
    print("BusinessIntelligence.ai")
    print("CAUSAL EVIDENCE ADAPTER")
    print("=" * 100)

    print(
        f"\nEvidence type      : "
        f"{record['evidence_type']}"
    )

    print(
        f"Treatment          : "
        f"{record['treatment']}"
    )

    print(
        f"Outcome            : "
        f"{record['outcome']}"
    )

    print(
        f"Effect estimate    : "
        f"{record['effect_estimate']:+.4f}"
    )

    print(
        f"Confidence         : "
        f"{record['confidence']:.3f}"
    )

    print(
        f"Status             : "
        f"{record['status']}"
    )

    interval = record[
        "interval"
    ]

    print(
        f"95% bootstrap CI   : "
        f"[{interval['lower']:.4f}, "
        f"{interval['upper']:.4f}]"
    )

    print(
        "\nInterpretation:"
    )

    print(
        record[
            "interpretation"
        ]
    )


# ============================================================
# MAIN
# ============================================================

def main():

    result = load_causal_result()

    record = build_causal_evidence(
        result
    )

    display_record(
        record
    )

    save_record(
        record
    )

    print("\n")
    print("=" * 100)
    print("CAUSAL EVIDENCE COMPLETE")
    print("=" * 100)

    print(
        f"Saved: {OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()