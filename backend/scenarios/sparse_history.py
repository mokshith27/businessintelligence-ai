from pathlib import Path
import json
from statistics import median


# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "scenarios"
)


# ============================================================
# CONFIGURATION
# ============================================================

MINIMUM_HISTORY_POINTS = 30

MINIMUM_BASELINE_POINTS = 14


# ============================================================
# SYNTHETIC NEW KPI
# ============================================================

SPARSE_KPI = {

    "kpi_id":
        "new_premium_category_gmv",

    "kpi_name":
        "New Premium Category GMV",

    "grain":
        "category_day",

    "launch_date":
        "2026-01-01",

    "currency":
        "BRL",

    "currency_symbol":
        "R$",
}


# ============================================================
# SAMPLE OBSERVATIONS
# ============================================================

OBSERVATIONS = [

    {
        "date":
            "2026-01-01",

        "value":
            2000.00,
    },

    {
        "date":
            "2026-01-02",

        "value":
            2300.00,
    },

    {
        "date":
            "2026-01-03",

        "value":
            2700.00,
    },

    {
        "date":
            "2026-01-04",

        "value":
            7800.00,
    },

    {
        "date":
            "2026-01-05",

        "value":
            8100.00,
    },
]


# ============================================================
# DETECT SPARSITY
# ============================================================

def assess_history(
    observations,
):

    history_points = len(
        observations
    )

    values = [
        float(
            observation["value"]
        )
        for observation in observations
    ]

    latest_value = values[-1]

    historical_values = values[:-1]

    baseline = (
        median(
            historical_values
        )
        if historical_values
        else None
    )

    relative_change_pct = None

    if (
        baseline is not None
        and baseline != 0
    ):

        relative_change_pct = (
            (
                latest_value
                - baseline
            )
            / baseline
        ) * 100

    sufficient_history = (
        history_points
        >= MINIMUM_HISTORY_POINTS
    )

    sufficient_baseline = (
        len(historical_values)
        >= MINIMUM_BASELINE_POINTS
    )

    if (
        not sufficient_history
        or not sufficient_baseline
    ):

        status = (
            "SPARSE_HISTORY"
        )

    else:

        status = (
            "SUFFICIENT_HISTORY"
        )

    return {

        "history_points":
            history_points,

        "baseline_points":
            len(
                historical_values
            ),

        "latest_value":
            latest_value,

        "baseline":
            baseline,

        "relative_change_pct":
            relative_change_pct,

        "sufficient_history":
            sufficient_history,

        "sufficient_baseline":
            sufficient_baseline,

        "status":
            status,
    }


# ============================================================
# ENGINE DECISION
# ============================================================

def determine_decision(
    history_assessment,
):

    if (
        history_assessment["status"]
        == "SPARSE_HISTORY"
    ):

        return {

            "decision":
                "ABSTAIN",

            "confidence":
                0.05,

            "reason":
                (
                    "The KPI has insufficient historical "
                    "observations for a reliable baseline. "
                    "The observed movement may be real, "
                    "but its materiality cannot yet be "
                    "distinguished from normal early-stage "
                    "behavior."
                ),

            "recommended_next_step":
                (
                    "Continue collecting historical data "
                    "until the minimum baseline requirement "
                    "is satisfied."
                ),
        }

    return {

        "decision":
            "INVESTIGATE",

        "confidence":
            0.50,

        "reason":
            (
                "Sufficient history exists for baseline "
                "analysis."
            ),

        "recommended_next_step":
            (
                "Evaluate the KPI against its historical "
                "baseline and seasonality."
            ),
    }


# ============================================================
# BUILD SCENARIO
# ============================================================

def build_scenario():

    history = assess_history(
        OBSERVATIONS
    )

    decision = determine_decision(
        history
    )

    return {

        "scenario_type":
            "SPARSE_HISTORY",

        "kpi":
            SPARSE_KPI,

        "observations":
            OBSERVATIONS,

        "history_assessment":
            history,

        "engine_decision":
            decision,

        "governance_expectation":
            {
                "expected_decision":
                    "ABSTAIN",

                "expected_behavior":
                    (
                        "Do not classify the latest "
                        "movement as a reliable anomaly "
                        "until sufficient history exists."
                    ),

                "minimum_history_points":
                    MINIMUM_HISTORY_POINTS,

                "minimum_baseline_points":
                    MINIMUM_BASELINE_POINTS,
            },
    }


# ============================================================
# DISPLAY
# ============================================================

def display_scenario(
    scenario,
):

    print("\n")
    print("=" * 100)
    print("BusinessIntelligence.ai")
    print("SPARSE-HISTORY SCENARIO")
    print("=" * 100)

    kpi = scenario["kpi"]

    history = scenario[
        "history_assessment"
    ]

    decision = scenario[
        "engine_decision"
    ]

    print(
        f"\nKPI                 : "
        f"{kpi['kpi_name']}"
    )

    print(
        f"Launch date         : "
        f"{kpi['launch_date']}"
    )

    print(
        f"History points      : "
        f"{history['history_points']}"
    )

    print(
        f"Required history    : "
        f"{MINIMUM_HISTORY_POINTS}"
    )

    print(
        f"Baseline points     : "
        f"{history['baseline_points']}"
    )

    print(
        f"Required baseline   : "
        f"{MINIMUM_BASELINE_POINTS}"
    )

    print(
        f"\nLatest value        : "
        f"R${history['latest_value']:,.2f}"
    )

    if history["baseline"] is not None:

        print(
            f"Median baseline     : "
            f"R${history['baseline']:,.2f}"
        )

    if (
        history[
            "relative_change_pct"
        ]
        is not None
    ):

        print(
            f"Relative change     : "
            f"{history['relative_change_pct']:+.2f}%"
        )

    print(
        f"\nHistory status      : "
        f"{history['status']}"
    )

    print(
        f"Engine decision     : "
        f"{decision['decision']}"
    )

    print(
        f"Confidence          : "
        f"{decision['confidence']:.3f}"
    )

    print(
        f"\nReason:\n"
        f"{decision['reason']}"
    )

    print(
        f"\nRecommended next step:\n"
        f"{decision['recommended_next_step']}"
    )


# ============================================================
# SAVE
# ============================================================

def save_scenario(
    scenario,
):

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        OUTPUT_DIR
        / "sparse_history_scenario.json"
    )

    path.write_text(
        json.dumps(
            scenario,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return path


# ============================================================
# MAIN
# ============================================================

def main():

    scenario = build_scenario()

    display_scenario(
        scenario
    )

    path = save_scenario(
        scenario
    )

    print("\n")
    print("=" * 100)
    print(
        "SPARSE-HISTORY SCENARIO COMPLETE"
    )
    print("=" * 100)

    print(
        f"Saved: {path}"
    )


if __name__ == "__main__":
    main()