from pathlib import Path
from datetime import timedelta
import json
import duckdb


from scenario_definitions import (
    get_all_scenarios,
)


# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DB_PATH = (
    PROJECT_ROOT
    / "data"
    / "warehouse"
    / "businessintelligence.duckdb"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "scenarios"
)


# ============================================================
# DATABASE
# ============================================================

def connect_database():

    if not DB_PATH.exists():

        raise FileNotFoundError(
            f"DuckDB database not found:\n{DB_PATH}"
        )

    return duckdb.connect(
        str(DB_PATH)
    )


# ============================================================
# KPI METRICS
# ============================================================

def get_metrics(
    con,
    start_date,
    end_date,
):

    row = con.execute(
        """
        SELECT

            COALESCE(
                SUM(price),
                0
            ) AS gmv,

            COUNT(
                DISTINCT order_id
            ) AS orders

        FROM fact_order_items_enriched

        WHERE
            CAST(
                order_purchase_timestamp
                AS DATE
            )
            BETWEEN ?
            AND ?;
        """,
        [
            start_date,
            end_date,
        ],
    ).fetchone()

    gmv = float(
        row[0] or 0
    )

    orders = int(
        row[1] or 0
    )

    aov = (
        gmv / orders
        if orders > 0
        else 0.0
    )

    return {
        "gmv": gmv,
        "orders": orders,
        "aov": aov,
    }


# ============================================================
# CONTEXT
# ============================================================

def get_context(
    con,
    scenario_id,
):

    rows = con.execute(
        """
        SELECT

            promotion_flag,

            marketing_campaign,

            inventory_status,

            competitor_price_index,

            external_event_flag,

            ground_truth_driver,

            COUNT(*) AS records

        FROM business_context

        WHERE
            scenario_id = ?

        GROUP BY

            promotion_flag,

            marketing_campaign,

            inventory_status,

            competitor_price_index,

            external_event_flag,

            ground_truth_driver;
        """,
        [
            scenario_id
        ],
    ).fetchall()

    context = []

    for row in rows:

        (
            promotion_flag,
            marketing_campaign,
            inventory_status,
            competitor_price_index,
            external_event_flag,
            ground_truth_driver,
            records,
        ) = row

        context.append(
            {
                "promotion_flag":
                    bool(
                        promotion_flag
                    ),

                "marketing_campaign":
                    marketing_campaign,

                "inventory_status":
                    inventory_status,

                "competitor_price_index":
                    (
                        float(
                            competitor_price_index
                        )
                        if competitor_price_index
                        is not None
                        else None
                    ),

                "external_event_flag":
                    bool(
                        external_event_flag
                    ),

                "ground_truth_driver":
                    ground_truth_driver,

                "records":
                    int(
                        records
                    ),
            }
        )

    return context


# ============================================================
# CONTEXT SIGNAL EXTRACTION
# ============================================================

def derive_context_signals(
    context,
):

    promotion_present = any(
        row[
            "promotion_flag"
        ]
        for row in context
    )

    inventory_constraint_present = any(
        row[
            "inventory_status"
        ] == "constrained"
        for row in context
    )

    external_event_present = any(
        row[
            "external_event_flag"
        ]
        for row in context
    )

    campaigns = sorted(
        {
            row[
                "marketing_campaign"
            ]
            for row in context
            if row[
                "marketing_campaign"
            ]
        }
    )

    competitor_indices = [
        row[
            "competitor_price_index"
        ]
        for row in context
        if row[
            "competitor_price_index"
        ] is not None
    ]

    avg_competitor_index = (
        sum(
            competitor_indices
        )
        / len(
            competitor_indices
        )
        if competitor_indices
        else None
    )

    return {

        "promotion_present":
            promotion_present,

        "inventory_constraint_present":
            inventory_constraint_present,

        "external_event_present":
            external_event_present,

        "campaigns":
            campaigns,

        "avg_competitor_price_index":
            avg_competitor_index,
    }


# ============================================================
# DIRECTION
# ============================================================

def direction(
    value,
    tolerance=0.0,
):

    if value > tolerance:

        return "POSITIVE"

    if value < -tolerance:

        return "NEGATIVE"

    return "FLAT"


# ============================================================
# DRIVER HYPOTHESIS SCORING
# ============================================================

def score_driver(
    driver,
    signals,
    gmv_direction,
    orders_direction,
):

    score = 0.0

    reasons = []

    # --------------------------------------------------------
    # Promotion
    # --------------------------------------------------------

    if driver == "promotion":

        if signals[
            "promotion_present"
        ]:

            score += 0.50

            reasons.append(
                "Promotion was present "
                "during the scenario."
            )

            # Expected mechanism:
            # promotion -> more demand/orders

            if orders_direction == "POSITIVE":

                score += 0.30

                reasons.append(
                    "Orders increased, consistent "
                    "with the expected promotion "
                    "demand mechanism."
                )

            elif orders_direction == "NEGATIVE":

                score -= 0.20

                reasons.append(
                    "Orders decreased, inconsistent "
                    "with the expected promotion "
                    "demand mechanism."
                )

        else:

            reasons.append(
                "No promotion signal was found."
            )

    # --------------------------------------------------------
    # Inventory constraint
    # --------------------------------------------------------

    elif driver == "inventory_constraint":

        if signals[
            "inventory_constraint_present"
        ]:

            score += 0.50

            reasons.append(
                "Inventory constraint was present "
                "during the scenario."
            )

            # Expected mechanism:
            # inventory constraint -> fewer orders

            if orders_direction == "NEGATIVE":

                score += 0.30

                reasons.append(
                    "Orders decreased, consistent "
                    "with the expected inventory "
                    "constraint mechanism."
                )

            elif orders_direction == "POSITIVE":

                score -= 0.20

                reasons.append(
                    "Orders increased, inconsistent "
                    "with the expected inventory "
                    "constraint mechanism."
                )

        else:

            reasons.append(
                "No inventory constraint signal "
                "was found."
            )

    # --------------------------------------------------------
    # Normalize score
    # --------------------------------------------------------

    score = max(
        0.0,
        min(
            1.0,
            score,
        )
    )

    # --------------------------------------------------------
    # Evidence classification
    # --------------------------------------------------------

    if score >= 0.75:

        status = "SUPPORTED"

    elif score >= 0.45:

        status = "PLAUSIBLE"

    elif score >= 0.20:

        status = "WEAK"

    else:

        status = "ABSTAIN"

    return {

        "driver":
            driver,

        "score":
            round(
                score,
                3,
            ),

        "status":
            status,

        "reasons":
            reasons,
    }


# ============================================================
# ACTION MAPPING
# ============================================================

def recommended_action(
    driver,
    status,
):

    if status == "SUPPORTED":

        if driver == "promotion":

            return {

                "decision":
                    "ACTION_WITH_VALIDATION",

                "lever":
                    "marketing campaign",

                "action":
                    "Evaluate incremental campaign "
                    "impact and consider continuing "
                    "or optimizing the promotion.",

                "owner":
                    "Marketing",

            }

        if driver == "inventory_constraint":

            return {

                "decision":
                    "ACTION_WITH_VALIDATION",

                "lever":
                    "inventory availability",

                "action":
                    "Prioritize replenishment for "
                    "affected products and monitor "
                    "order recovery.",

                "owner":
                    "Supply Operations",

            }

    if status in {
        "PLAUSIBLE",
        "WEAK",
    }:

        return {

            "decision":
                "INVESTIGATE",

            "lever":
                None,

            "action":
                "Collect additional evidence "
                "before taking a major intervention.",

            "owner":
                "Analyst",

        }

    return {

        "decision":
            "ABSTAIN",

        "lever":
            None,

        "action":
            "Insufficient evidence for an "
            "operational intervention.",

        "owner":
            "Analyst",

    }


# ============================================================
# RUN ENGINE
# ============================================================

def run_engine(
    con,
    scenario,
):

    duration = (
        scenario.end_date
        - scenario.start_date
    ).days + 1

    comparison_end = (
        scenario.start_date
        - timedelta(
            days=1
        )
    )

    comparison_start = (
        comparison_end
        - timedelta(
            days=duration - 1
        )
    )

    current = get_metrics(
        con,
        scenario.start_date,
        scenario.end_date,
    )

    previous = get_metrics(
        con,
        comparison_start,
        comparison_end,
    )

    movement = {

        "gmv_change":
            current["gmv"]
            - previous["gmv"],

        "orders_change":
            current["orders"]
            - previous["orders"],

        "aov_change":
            current["aov"]
            - previous["aov"],
    }

    gmv_direction = direction(
        movement["gmv_change"]
    )

    orders_direction = direction(
        movement["orders_change"]
    )

    context = get_context(
        con,
        scenario.scenario_id,
    )

    signals = derive_context_signals(
        context
    )

    # --------------------------------------------------------
    # Candidate drivers
    # --------------------------------------------------------

    candidate_drivers = [
        "promotion",
        "inventory_constraint",
    ]

    hypotheses = []

    for driver in candidate_drivers:

        hypotheses.append(
            score_driver(
                driver,
                signals,
                gmv_direction,
                orders_direction,
            )
        )

    hypotheses.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    top_hypothesis = (
        hypotheses[0]
        if hypotheses
        else None
    )

    # --------------------------------------------------------
    # Ambiguity check
    # --------------------------------------------------------

    if top_hypothesis is None:

        overall_status = "ABSTAIN"

    else:

        scores = [
            item["score"]
            for item in hypotheses
        ]

        top_score = scores[0]

        second_score = (
            scores[1]
            if len(scores) > 1
            else 0.0
        )

        score_gap = (
            top_score
            - second_score
        )

        if top_score < 0.45:

            overall_status = "ABSTAIN"

        elif score_gap < 0.15:

            overall_status = "AMBIGUOUS"

        else:

            overall_status = (
                top_hypothesis["status"]
            )

    # --------------------------------------------------------
    # Action
    # --------------------------------------------------------

    if (
        overall_status
        == "AMBIGUOUS"
    ):

        action = {

            "decision":
                "ABSTAIN",

            "lever":
                None,

            "action":
                "Do not take a major intervention "
                "until conflicting evidence is resolved.",

            "owner":
                "Analyst",
        }

    else:

        action = recommended_action(
            top_hypothesis[
                "driver"
            ],
            overall_status,
        )

    return {

        "scenario_id":
            scenario.scenario_id,

        "scenario_name":
            scenario.name,

        "ground_truth_driver":
            scenario.ground_truth_driver,

        "event_period": {

            "start":
                str(
                    scenario.start_date
                ),

            "end":
                str(
                    scenario.end_date
                ),
        },

        "comparison_period": {

            "start":
                str(
                    comparison_start
                ),

            "end":
                str(
                    comparison_end
                ),
        },

        "current_metrics":
            current,

        "comparison_metrics":
            previous,

        "movement":
            movement,

        "observed_direction": {

            "gmv":
                gmv_direction,

            "orders":
                orders_direction,
        },

        "context_signals":
            signals,

        "hypotheses":
            hypotheses,

        "top_hypothesis":
            top_hypothesis,

        "overall_status":
            overall_status,

        "recommended_action":
            action,
    }


# ============================================================
# DISPLAY
# ============================================================

def display_result(
    result,
):

    print("\n")
    print("=" * 100)

    print(
        f"SCENARIO: "
        f"{result['scenario_id']} - "
        f"{result['scenario_name']}"
    )

    print("=" * 100)

    print(
        f"\nGround truth context : "
        f"{result['ground_truth_driver']}"
    )

    print(
        f"Observed GMV         : "
        f"{result['observed_direction']['gmv']}"
    )

    print(
        f"Observed orders      : "
        f"{result['observed_direction']['orders']}"
    )

    print(
        "\nDriver hypotheses:"
    )

    for hypothesis in result[
        "hypotheses"
    ]:

        print(
            f"  {hypothesis['driver']:<25} "
            f"score={hypothesis['score']:.3f} "
            f"status={hypothesis['status']}"
        )

        for reason in hypothesis[
            "reasons"
        ]:

            print(
                f"      - {reason}"
            )

    print(
        f"\nOverall engine status : "
        f"{result['overall_status']}"
    )

    action = result[
        "recommended_action"
    ]

    print(
        f"Decision             : "
        f"{action['decision']}"
    )

    print(
        f"Owner                : "
        f"{action['owner']}"
    )

    print(
        f"Action               : "
        f"{action['action']}"
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

    path = (
        OUTPUT_DIR
        / "scenario_engine_results.json"
    )

    path.write_text(
        json.dumps(
            results,
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

    print("\n")
    print("=" * 100)
    print("BusinessIntelligence.ai")
    print("SCENARIO ENGINE")
    print("=" * 100)

    con = connect_database()

    try:

        results = []

        for scenario in get_all_scenarios():

            result = run_engine(
                con,
                scenario,
            )

            results.append(
                result
            )

            display_result(
                result
            )

        path = save_results(
            results
        )

        print("\n")
        print("=" * 100)
        print("SCENARIO ENGINE COMPLETE")
        print("=" * 100)

        print(
            f"Saved: {path}"
        )

    finally:

        con.close()


if __name__ == "__main__":
    main()