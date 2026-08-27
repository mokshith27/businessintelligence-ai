from pathlib import Path
import json
from datetime import date
from datetime import timedelta

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
        else 0
    )

    return {
        "gmv": gmv,
        "orders": orders,
        "aov": aov,
    }


# ============================================================
# CONTEXT SIGNALS
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

    results = []

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

        results.append(
            {
                "promotion_flag":
                    promotion_flag,

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
                    external_event_flag,

                "ground_truth_driver":
                    ground_truth_driver,

                "records":
                    records,
            }
        )

    return results


# ============================================================
# DRIVER MECHANISM EXPECTATIONS
# ============================================================

def expected_mechanism(
    ground_truth_driver,
):

    if ground_truth_driver == "promotion":

        return {
            "expected_gmv_direction":
                "POSITIVE",

            "expected_order_direction":
                "POSITIVE",

            "expected_aov_direction":
                "ANY",

            "description":
                "Promotion is expected to support "
                "incremental demand, primarily through "
                "higher order volume.",
        }

    if ground_truth_driver == "inventory_constraint":

        return {
            "expected_gmv_direction":
                "NEGATIVE",

            "expected_order_direction":
                "NEGATIVE",

            "expected_aov_direction":
                "ANY",

            "description":
                "Inventory constraints are expected "
                "to suppress product availability and "
                "therefore reduce order volume.",
        }

    return {
        "expected_gmv_direction":
            "ANY",

        "expected_order_direction":
            "ANY",

        "expected_aov_direction":
            "ANY",

        "description":
            "No predefined mechanism.",
    }


# ============================================================
# DIRECTION HELPER
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
# MECHANISM EVALUATION
# ============================================================

def evaluate_mechanism(
    movement,
    mechanism,
):

    observed_gmv_direction = direction(
        movement["gmv_change"]
    )

    observed_orders_direction = direction(
        movement["orders_change"]
    )

    # --------------------------------------------------------
    # GMV
    # --------------------------------------------------------

    expected_gmv = (
        mechanism[
            "expected_gmv_direction"
        ]
    )

    gmv_match = (
        expected_gmv == "ANY"
        or expected_gmv
        == observed_gmv_direction
    )

    # --------------------------------------------------------
    # Orders
    # --------------------------------------------------------

    expected_orders = (
        mechanism[
            "expected_order_direction"
        ]
    )

    orders_match = (
        expected_orders == "ANY"
        or expected_orders
        == observed_orders_direction
    )

    # --------------------------------------------------------
    # Final mechanism status
    # --------------------------------------------------------

    if (
        gmv_match
        and orders_match
    ):

        status = "SUPPORTED"

    elif (
        gmv_match
        and not orders_match
    ):

        status = "PARTIAL"

    else:

        status = "CONTRADICTED"

    return {
        "observed_gmv_direction":
            observed_gmv_direction,

        "observed_orders_direction":
            observed_orders_direction,

        "expected_gmv_direction":
            expected_gmv,

        "expected_orders_direction":
            expected_orders,

        "gmv_match":
            gmv_match,

        "orders_match":
            orders_match,

        "status":
            status,
    }


# ============================================================
# EVALUATE SCENARIO
# ============================================================

def evaluate_scenario(
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

    context = get_context(
        con,
        scenario.scenario_id,
    )

    context_match = any(
        row[
            "ground_truth_driver"
        ]
        == scenario.ground_truth_driver

        for row in context
    )

    mechanism = expected_mechanism(
        scenario.ground_truth_driver
    )

    mechanism_result = evaluate_mechanism(
        movement,
        mechanism,
    )

    # --------------------------------------------------------
    # Overall status
    # --------------------------------------------------------

    if (
        context_match
        and mechanism_result["status"]
        == "SUPPORTED"
    ):

        overall = "SUPPORTED"

    elif (
        context_match
        and mechanism_result["status"]
        == "PARTIAL"
    ):

        overall = "AMBIGUOUS"

    elif (
        context_match
        and mechanism_result["status"]
        == "CONTRADICTED"
    ):

        overall = "CONTRADICTED"

    else:

        overall = "INSUFFICIENT"

    return {

        "scenario_id":
            scenario.scenario_id,

        "scenario_name":
            scenario.name,

        "ground_truth_driver":
            scenario.ground_truth_driver,

        "expected_direction":
            scenario.expected_direction,

        "context_match":
            context_match,

        "current_metrics":
            current,

        "comparison_metrics":
            previous,

        "movement":
            movement,

        "mechanism":
            mechanism,

        "mechanism_evaluation":
            mechanism_result,

        "overall_result":
            overall,
    }


# ============================================================
# SAVE RESULTS
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
        / "scenario_evaluation.json"
    )

    path.write_text(
        json.dumps(
            results,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )

    return path


# ============================================================
# DISPLAY
# ============================================================

def display_result(
    result,
):

    print("\n")
    print("=" * 100)

    print(
        f"{result['scenario_id']} — "
        f"{result['scenario_name']}"
    )

    print("=" * 100)

    print(
        f"\nGround truth driver : "
        f"{result['ground_truth_driver']}"
    )

    print(
        f"Expected direction  : "
        f"{result['expected_direction']}"
    )

    movement = result[
        "movement"
    ]

    print(
        f"\nGMV change          : "
        f"{movement['gmv_change']:+,.2f}"
    )

    print(
        f"Orders change       : "
        f"{movement['orders_change']:+,}"
    )

    print(
        f"AOV change          : "
        f"{movement['aov_change']:+,.2f}"
    )

    print(
        f"\nContext match       : "
        f"{result['context_match']}"
    )

    mechanism = result[
        "mechanism_evaluation"
    ]

    print(
        f"GMV mechanism match : "
        f"{mechanism['gmv_match']}"
    )

    print(
        f"Order mechanism     : "
        f"{mechanism['orders_match']}"
    )

    print(
        f"Mechanism status    : "
        f"{mechanism['status']}"
    )

    print(
        f"\nOVERALL RESULT      : "
        f"{result['overall_result']}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n")
    print("=" * 100)
    print("BusinessIntelligence.ai")
    print("SCENARIO EVALUATION ENGINE")
    print("=" * 100)

    con = connect_database()

    try:

        results = []

        for scenario in get_all_scenarios():

            result = evaluate_scenario(
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

        print(
            "SCENARIO EVALUATION COMPLETE"
        )

        print(
            f"Saved: {path}"
        )

        print("=" * 100)

    finally:

        con.close()


if __name__ == "__main__":
    main()