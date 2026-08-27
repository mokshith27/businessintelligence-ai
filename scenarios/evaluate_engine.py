from pathlib import Path
import json

from scenario_engine import (
    connect_database,
    run_engine,
)

from scenario_definitions import (
    get_all_scenarios,
)


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
# DRIVER / ACTION EXPECTATIONS
# ============================================================

def expected_action_for_driver(
    driver
):
    """
    Define what type of action is expected for each
    controlled ground-truth driver.
    """

    if driver == "promotion":

        return {
            "acceptable_decisions": {
                "ACTION_WITH_VALIDATION",
                "INVESTIGATE",
                "ABSTAIN",
            },

            "preferred_owner":
                "Marketing",
        }

    if driver == "inventory_constraint":

        return {
            "acceptable_decisions": {
                "ACTION_WITH_VALIDATION",
                "INVESTIGATE",
                "ABSTAIN",
            },

            "preferred_owner":
                "Supply Operations",
        }

    return {
        "acceptable_decisions": {
            "INVESTIGATE",
            "ABSTAIN",
        },

        "preferred_owner":
            "Analyst",
    }


# ============================================================
# DRIVER EVALUATION
# ============================================================

def evaluate_driver_identification(
    result,
    ground_truth,
):

    hypotheses = result.get(
        "hypotheses",
        []
    )

    if not hypotheses:

        return {
            "top_driver":
                None,

            "driver_match":
                False,
        }

    top_driver = (
        hypotheses[0]["driver"]
    )

    return {
        "top_driver":
            top_driver,

        "driver_match":
            top_driver
            == ground_truth,
    }


# ============================================================
# STATUS EVALUATION
# ============================================================

def evaluate_status(
    result,
    ground_truth,
):

    overall_status = (
        result.get(
            "overall_status"
        )
    )

    top = result.get(
        "top_hypothesis"
    )

    if top is None:

        return {
            "status":
                overall_status,

            "status_assessment":
                "ABSTAINED"
        }

    # --------------------------------------------------------
    # A supported status is appropriate only when the observed
    # mechanism actually agrees with the scenario.
    # --------------------------------------------------------

    mechanism_status = (
        result.get(
            "top_hypothesis",
            {}
        ).get(
            "status"
        )
    )

    if overall_status == "SUPPORTED":

        if (
            top["driver"]
            == ground_truth
        ):

            return {
                "status":
                    overall_status,

                "status_assessment":
                    "SUPPORTED_CORRECTLY"
            }

        return {
            "status":
                overall_status,

            "status_assessment":
                "UNSUPPORTED_DRIVER"
        }

    # --------------------------------------------------------
    # Abstention on conflicting evidence is considered a
    # safe outcome.
    # --------------------------------------------------------

    if overall_status == "ABSTAIN":

        return {
            "status":
                overall_status,

            "status_assessment":
                "SAFE_ABSTENTION"
        }

    if overall_status == "AMBIGUOUS":

        return {
            "status":
                overall_status,

            "status_assessment":
                "AMBIGUITY_HANDLED"
        }

    return {
        "status":
            overall_status,

        "status_assessment":
            "REVIEW"
    }


# ============================================================
# ACTION EVALUATION
# ============================================================

def evaluate_action(
    result,
    ground_truth,
):

    action = result.get(
        "recommended_action",
        {}
    )

    decision = action.get(
        "decision"
    )

    owner = action.get(
        "owner"
    )

    expectations = (
        expected_action_for_driver(
            ground_truth
        )
    )

    acceptable = (
        decision
        in expectations[
            "acceptable_decisions"
        ]
    )

    owner_match = (
        owner
        == expectations[
            "preferred_owner"
        ]
    )

    return {

        "decision":
            decision,

        "owner":
            owner,

        "decision_acceptable":
            acceptable,

        "owner_match":
            owner_match,
    }


# ============================================================
# SAFETY EVALUATION
# ============================================================

def evaluate_safety(
    result,
    ground_truth,
):

    status = result.get(
        "overall_status"
    )

    action = result.get(
        "recommended_action",
        {}
    )

    decision = action.get(
        "decision"
    )

    # --------------------------------------------------------
    # The engine should never recommend a strong action when
    # evidence is ambiguous.
    # --------------------------------------------------------

    if status in {
        "ABSTAIN",
        "AMBIGUOUS",
    }:

        safe = decision in {
            "ABSTAIN",
            "INVESTIGATE",
        }

        return {
            "safe":
                safe,

            "reason":
                "Conflicting or insufficient evidence "
                "was handled conservatively.",
        }

    return {
        "safe": True,

        "reason":
            "No safety violation detected.",
    }


# ============================================================
# OVERALL SCORE
# ============================================================

def calculate_score(
    driver_eval,
    status_eval,
    action_eval,
    safety_eval,
):

    checks = [

        driver_eval[
            "driver_match"
        ],

        status_eval[
            "status_assessment"
        ]
        in {
            "SUPPORTED_CORRECTLY",
            "SAFE_ABSTENTION",
            "AMBIGUITY_HANDLED",
        },

        action_eval[
            "decision_acceptable"
        ],

        safety_eval[
            "safe"
        ],
    ]

    score = (
        sum(
            1
            for check in checks
            if check
        )
        /
        len(checks)
    )

    return round(
        score,
        3,
    )


# ============================================================
# EVALUATE ONE SCENARIO
# ============================================================

def evaluate_scenario(
    con,
    scenario,
):

    result = run_engine(
        con,
        scenario,
    )

    driver_eval = (
        evaluate_driver_identification(
            result,
            scenario.ground_truth_driver,
        )
    )

    status_eval = (
        evaluate_status(
            result,
            scenario.ground_truth_driver,
        )
    )

    action_eval = (
        evaluate_action(
            result,
            scenario.ground_truth_driver,
        )
    )

    safety_eval = (
        evaluate_safety(
            result,
            scenario.ground_truth_driver,
        )
    )

    score = calculate_score(
        driver_eval,
        status_eval,
        action_eval,
        safety_eval,
    )

    return {

        "scenario_id":
            scenario.scenario_id,

        "scenario_name":
            scenario.name,

        "ground_truth_driver":
            scenario.ground_truth_driver,

        "engine_result":
            result,

        "driver_evaluation":
            driver_eval,

        "status_evaluation":
            status_eval,

        "action_evaluation":
            action_eval,

        "safety_evaluation":
            safety_eval,

        "overall_score":
            score,
    }


# ============================================================
# DISPLAY
# ============================================================

def display_result(
    evaluation,
):

    print("\n")
    print("=" * 100)

    print(
        f"{evaluation['scenario_id']} - "
        f"{evaluation['scenario_name']}"
    )

    print("=" * 100)

    print(
        f"\nGround truth driver : "
        f"{evaluation['ground_truth_driver']}"
    )

    print(
        f"Top engine driver   : "
        f"{evaluation['driver_evaluation']['top_driver']}"
    )

    print(
        f"Driver match        : "
        f"{evaluation['driver_evaluation']['driver_match']}"
    )

    print(
        f"\nStatus              : "
        f"{evaluation['status_evaluation']['status']}"
    )

    print(
        f"Status assessment   : "
        f"{evaluation['status_evaluation']['status_assessment']}"
    )

    print(
        f"\nAction decision     : "
        f"{evaluation['action_evaluation']['decision']}"
    )

    print(
        f"Decision acceptable : "
        f"{evaluation['action_evaluation']['decision_acceptable']}"
    )

    print(
        f"Owner               : "
        f"{evaluation['action_evaluation']['owner']}"
    )

    print(
        f"\nSafety              : "
        f"{evaluation['safety_evaluation']['safe']}"
    )

    print(
        f"\nOverall score       : "
        f"{evaluation['overall_score']:.3f}"
    )


# ============================================================
# SAVE
# ============================================================

def save_results(
    results,
):

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        OUTPUT_DIR
        / "engine_evaluation.json"
    )

    output_path.write_text(
        json.dumps(
            results,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )

    return output_path


# ============================================================
# SUMMARY
# ============================================================

def print_summary(
    results,
):

    print("\n")
    print("=" * 100)
    print("EVALUATION SUMMARY")
    print("=" * 100)

    scores = [
        result[
            "overall_score"
        ]
        for result in results
    ]

    average_score = (
        sum(scores)
        / len(scores)
        if scores
        else 0.0
    )

    safe_count = sum(
        1
        for result in results
        if result[
            "safety_evaluation"
        ]["safe"]
    )

    driver_matches = sum(
        1
        for result in results
        if result[
            "driver_evaluation"
        ]["driver_match"]
    )

    print(
        f"\nScenarios evaluated : "
        f"{len(results)}"
    )

    print(
        f"Driver matches      : "
        f"{driver_matches}/{len(results)}"
    )

    print(
        f"Safety checks passed: "
        f"{safe_count}/{len(results)}"
    )

    print(
        f"Average score       : "
        f"{average_score:.3f}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n")
    print("=" * 100)
    print("BusinessIntelligence.ai")
    print("ENGINE EVALUATION")
    print("=" * 100)

    con = connect_database()

    try:

        results = []

        for scenario in get_all_scenarios():

            evaluation = evaluate_scenario(
                con,
                scenario,
            )

            results.append(
                evaluation
            )

            display_result(
                evaluation
            )

        path = save_results(
            results
        )

        print_summary(
            results
        )

        print("\n")
        print("=" * 100)

        print(
            "ENGINE EVALUATION COMPLETE"
        )

        print(
            f"Saved: {path}"
        )

        print("=" * 100)

    finally:

        con.close()


if __name__ == "__main__":
    main()