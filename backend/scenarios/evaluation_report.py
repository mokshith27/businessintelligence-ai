from pathlib import Path
import json


# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

INPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "scenarios"
    / "engine_evaluation.json"
)

OUTPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "scenarios"
    / "evaluation_report.json"
)


# ============================================================
# LOAD
# ============================================================

def load_results():

    if not INPUT_PATH.exists():

        raise FileNotFoundError(
            f"Evaluation results not found:\n"
            f"{INPUT_PATH}\n\n"
            "Run evaluate_engine.py first."
        )

    return json.loads(
        INPUT_PATH.read_text(
            encoding="utf-8"
        )
    )


# ============================================================
# SCORE ONE SCENARIO
# ============================================================

def score_scenario(result):

    engine_result = result[
        "engine_result"
    ]

    mechanism = engine_result[
        "hypotheses"
    ]

    context_signals = engine_result[
        "context_signals"
    ]

    status_eval = result[
        "status_evaluation"
    ]

    action_eval = result[
        "action_evaluation"
    ]

    safety_eval = result[
        "safety_evaluation"
    ]

    driver_match = (
        result[
            "driver_evaluation"
        ][
            "driver_match"
        ]
    )

    overall_status = (
        engine_result[
            "overall_status"
        ]
    )

    # --------------------------------------------------------
    # Context
    # --------------------------------------------------------

    ground_truth_driver = result[
        "ground_truth_driver"
    ]

    if ground_truth_driver == "promotion":

        context_present = (
            context_signals[
                "promotion_present"
            ]
        )

    elif ground_truth_driver == "inventory_constraint":

        context_present = (
            context_signals[
                "inventory_constraint_present"
            ]
        )

    else:

        context_present = False

    # --------------------------------------------------------
    # Mechanism
    # --------------------------------------------------------

    top = engine_result.get(
        "top_hypothesis"
    )

    mechanism_supported = False

    if top:

        mechanism_reasons = (
            top.get(
                "reasons",
                []
            )
        )

        mechanism_supported = any(
            (
                "consistent"
                in reason.lower()
                )
            for reason in mechanism_reasons
        )

    # --------------------------------------------------------
    # Abstention
    # --------------------------------------------------------

    expected_abstention = (
        overall_status
        in {
            "ABSTAIN",
            "AMBIGUOUS",
        }
    )

    safe_abstention = (
        expected_abstention
        and safety_eval[
            "safe"
        ]
    )

    # --------------------------------------------------------
    # Action
    # --------------------------------------------------------

    action_decision = (
        action_eval[
            "decision"
        ]
    )

    # --------------------------------------------------------
    # Component scores
    # --------------------------------------------------------

    component_scores = {

        "driver_identification":
            int(
                driver_match
            ),

        "context_alignment":
            int(
                context_present
            ),

        "status_handling":
            int(
                status_eval[
                    "status_assessment"
                ]
                in {
                    "SUPPORTED_CORRECTLY",
                    "SAFE_ABSTENTION",
                    "AMBIGUITY_HANDLED",
                }
            ),

        "safe_abstention":
            int(
                safe_abstention
                or not expected_abstention
            ),

        "action_safety":
            int(
                safety_eval[
                    "safe"
                ]
            ),

        "action_acceptability":
            int(
                action_eval[
                    "decision_acceptable"
                ]
            ),
    }

    score = (
        sum(
            component_scores.values()
        )
        /
        len(
            component_scores
        )
    )

    return {

        "scenario_id":
            result[
                "scenario_id"
            ],

        "ground_truth_driver":
            ground_truth_driver,

        "engine_status":
            overall_status,

        "top_driver":
            result[
                "driver_evaluation"
            ][
                "top_driver"
            ],

        "context_present":
            context_present,

        "mechanism_supported":
            mechanism_supported,

        "action_decision":
            action_decision,

        "components":
            component_scores,

        "score":
            round(
                score,
                3,
            ),
    }


# ============================================================
# AGGREGATE
# ============================================================

def aggregate_scores(
    scored_results
):

    if not scored_results:

        return {}

    total = len(
        scored_results
    )

    return {

        "scenarios":
            total,

        "driver_identification_rate":
            round(
                sum(
                    item[
                        "components"
                    ][
                        "driver_identification"
                    ]
                    for item in scored_results
                )
                / total,
                3,
            ),

        "context_alignment_rate":
            round(
                sum(
                    item[
                        "components"
                    ][
                        "context_alignment"
                    ]
                    for item in scored_results
                )
                / total,
                3,
            ),

        "status_handling_rate":
            round(
                sum(
                    item[
                        "components"
                    ][
                        "status_handling"
                    ]
                    for item in scored_results
                )
                / total,
                3,
            ),

        "safe_abstention_rate":
            round(
                sum(
                    item[
                        "components"
                    ][
                        "safe_abstention"
                    ]
                    for item in scored_results
                )
                / total,
                3,
            ),

        "action_safety_rate":
            round(
                sum(
                    item[
                        "components"
                    ][
                        "action_safety"
                    ]
                    for item in scored_results
                )
                / total,
                3,
            ),

        "action_acceptability_rate":
            round(
                sum(
                    item[
                        "components"
                    ][
                        "action_acceptability"
                    ]
                    for item in scored_results
                )
                / total,
                3,
            ),

        "average_score":
            round(
                sum(
                    item[
                        "score"
                    ]
                    for item in scored_results
                )
                / total,
                3,
            ),
    }


# ============================================================
# SAVE
# ============================================================

def save_report(report):

    OUTPUT_PATH.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


# ============================================================
# DISPLAY
# ============================================================

def display_report(
    report
):

    print("\n")
    print("=" * 100)
    print("BUSINESSINTELLIGENCE.AI")
    print("CONTROLLED SCENARIO SCORECARD")
    print("=" * 100)

    summary = report[
        "summary"
    ]

    print(
        f"\nScenarios evaluated      : "
        f"{summary['scenarios']}"
    )

    print(
        f"Driver identification   : "
        f"{summary['driver_identification_rate']:.1%}"
    )

    print(
        f"Context alignment        : "
        f"{summary['context_alignment_rate']:.1%}"
    )

    print(
        f"Status handling          : "
        f"{summary['status_handling_rate']:.1%}"
    )

    print(
        f"Safe abstention          : "
        f"{summary['safe_abstention_rate']:.1%}"
    )

    print(
        f"Action safety            : "
        f"{summary['action_safety_rate']:.1%}"
    )

    print(
        f"Action acceptability     : "
        f"{summary['action_acceptability_rate']:.1%}"
    )

    print(
        f"Average score            : "
        f"{summary['average_score']:.3f}"
    )

    print("\n")
    print("=" * 100)
    print("SCENARIO DETAILS")
    print("=" * 100)

    for result in report[
        "scenarios"
    ]:

        print(
            f"\n{result['scenario_id']}"
        )

        print(
            f"Ground truth : "
            f"{result['ground_truth_driver']}"
        )

        print(
            f"Top driver  : "
            f"{result['top_driver']}"
        )

        print(
            f"Status      : "
            f"{result['engine_status']}"
        )

        print(
            f"Action      : "
            f"{result['action_decision']}"
        )

        print(
            f"Score       : "
            f"{result['score']:.3f}"
        )

    print("\n")
    print("=" * 100)
    print("EVALUATION REPORT COMPLETE")
    print("=" * 100)


# ============================================================
# MAIN
# ============================================================

def main():

    results = load_results()

    scored_results = []

    for result in results:

        scored_results.append(
            score_scenario(
                result
            )
        )

    summary = aggregate_scores(
        scored_results
    )

    report = {

        "scenarios":
            scored_results,

        "summary":
            summary,
    }

    save_report(
        report
    )

    display_report(
        report
    )


if __name__ == "__main__":
    main()