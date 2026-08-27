from pathlib import Path
from datetime import timedelta
import duckdb
import sys

# ============================================================
# WINDOWS UTF-8 OUTPUT
# ============================================================

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(
        encoding="utf-8",
        errors="replace",
    )

if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(
        encoding="utf-8",
        errors="replace",
    )


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
# SCENARIO KPI
# ============================================================

def calculate_period_metrics(
    con,
    start_date,
    end_date,
):

    result = con.execute(
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
        result[0] or 0
    )

    orders = int(
        result[1] or 0
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
# CONTEXT SUMMARY
# ============================================================

def get_context_summary(
    con,
    scenario_id,
    start_date,
    end_date,
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

            AND CAST(date AS DATE)
                BETWEEN ?
                AND ?

        GROUP BY

            promotion_flag,

            marketing_campaign,

            inventory_status,

            competitor_price_index,

            external_event_flag,

            ground_truth_driver

        ORDER BY
            records DESC;
        """,
        [
            scenario_id,
            start_date,
            end_date,
        ],
    ).fetchall()

    records = []

    for row in rows:

        (
            promotion_flag,
            marketing_campaign,
            inventory_status,
            competitor_price_index,
            external_event_flag,
            ground_truth_driver,
            count,
        ) = row

        records.append(
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
                    int(count),
            }
        )

    return records


# ============================================================
# RUN ONE SCENARIO
# ============================================================

def run_scenario(
    con,
    scenario,
):

    duration = (
        scenario.end_date
        - scenario.start_date
    ).days + 1

    # --------------------------------------------------------
    # Comparison period immediately before scenario
    # --------------------------------------------------------

    comparison_end = (
        scenario.start_date
        - timedelta(days=1)
    )

    comparison_start = (
        comparison_end
        - timedelta(
            days=duration - 1
        )
    )

    # --------------------------------------------------------
    # Calculate KPI periods
    # --------------------------------------------------------

    scenario_metrics = calculate_period_metrics(
        con,
        scenario.start_date,
        scenario.end_date,
    )

    comparison_metrics = calculate_period_metrics(
        con,
        comparison_start,
        comparison_end,
    )

    # --------------------------------------------------------
    # KPI movement
    # --------------------------------------------------------

    gmv_change = (
        scenario_metrics["gmv"]
        - comparison_metrics["gmv"]
    )

    orders_change = (
        scenario_metrics["orders"]
        - comparison_metrics["orders"]
    )

    aov_change = (
        scenario_metrics["aov"]
        - comparison_metrics["aov"]
    )

    if comparison_metrics["gmv"] != 0:

        gmv_change_pct = (
            gmv_change
            / comparison_metrics["gmv"]
        ) * 100

    else:

        gmv_change_pct = None

    if comparison_metrics["orders"] != 0:

        orders_change_pct = (
            orders_change
            / comparison_metrics["orders"]
        ) * 100

    else:

        orders_change_pct = None

    # --------------------------------------------------------
    # Business context
    # --------------------------------------------------------

    context = get_context_summary(
        con,
        scenario.scenario_id,
        scenario.start_date,
        scenario.end_date,
    )

    # --------------------------------------------------------
    # Ground truth check
    # --------------------------------------------------------

    context_drivers = set()

    for record in context:

        driver = record.get(
            "ground_truth_driver"
        )

        if driver:

            context_drivers.add(
                driver
            )

    ground_truth_present = (
        scenario.ground_truth_driver
        in context_drivers
    )

    # --------------------------------------------------------
    # Direction
    # --------------------------------------------------------

    if gmv_change > 0:

        direction = "POSITIVE"

    elif gmv_change < 0:

        direction = "NEGATIVE"

    else:

        direction = "FLAT"

    return {

        "scenario_id":
            scenario.scenario_id,

        "scenario_name":
            scenario.name,

        "start_date":
            str(
                scenario.start_date
            ),

        "end_date":
            str(
                scenario.end_date
            ),

        "ground_truth_driver":
            scenario.ground_truth_driver,

        "expected_direction":
            scenario.expected_direction,

        "scenario_metrics":
            scenario_metrics,

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

        "comparison_metrics":
            comparison_metrics,

        "movement": {

            "gmv_change":
                gmv_change,

            "gmv_change_pct":
                gmv_change_pct,

            "orders_change":
                orders_change,

            "orders_change_pct":
                orders_change_pct,

            "aov_change":
                aov_change,

        },

        "observed_direction":
            direction,

        "context":
            context,

        "ground_truth_present":
            ground_truth_present,

        "ground_truth_match":
            (
                direction
                == scenario.expected_direction
            ),
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
        f"{result['scenario_id']}"
    )

    print(
        f"{result['start_date']} "
        f"-> "
        f"{result['end_date']}"
    )

    print("=" * 100)

    print(
        f"\nGround-truth driver : "
        f"{result['ground_truth_driver']}"
    )

    print(
        f"Expected direction  : "
        f"{result['expected_direction']}"
    )

    print(
        f"Observed direction  : "
        f"{result['observed_direction']}"
    )

    print("\nKPI movement")

    print(
        f"GMV change          : "
        f"{result['movement']['gmv_change']:,.2f}"
    )

    if (
        result["movement"]["gmv_change_pct"]
        is not None
    ):

        print(
            f"GMV change %        : "
            f"{result['movement']['gmv_change_pct']:+.2f}%"
        )

    print(
        f"Orders change       : "
        f"{result['movement']['orders_change']:+,}"
    )

    if (
        result["movement"]["orders_change_pct"]
        is not None
    ):

        print(
            f"Orders change %     : "
            f"{result['movement']['orders_change_pct']:+.2f}%"
        )

    print(
        f"AOV change          : "
        f"{result['movement']['aov_change']:+.2f}"
    )

    print("\nGround-truth context found:")

    print(
        f"  {result['ground_truth_present']}"
    )

    print(
        "\nGround-truth direction match:"
    )

    print(
        f"  {result['ground_truth_match']}"
    )

    print(
        "\nContext records:"
    )

    if result["context"]:

        for record in result["context"]:

            print(
                f"  {record}"
            )

    else:

        print(
            "  No business context records found."
        )
        
def print_safe(text):
    """
    Print text safely on Windows terminals.
    """
    print(
        str(text)
        .encode(
            "utf-8",
            errors="replace",
        )
        .decode(
            "utf-8",
            errors="replace",
        )
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n")
    print("=" * 100)
    print("BusinessIntelligence.ai")
    print("CONTROLLED SCENARIO RUNNER")
    print("=" * 100)

    con = connect_database()

    try:

        scenarios = get_all_scenarios()

        print(
            f"\nScenarios loaded: "
            f"{len(scenarios)}"
        )

        results = []

        for scenario in scenarios:

            result = run_scenario(
                con,
                scenario,
            )

            results.append(
                result
            )

            display_result(
                result
            )

        print("\n")
        print("=" * 100)
        print("SCENARIO RUN COMPLETE")
        print("=" * 100)

    finally:

        con.close()


if __name__ == "__main__":
    main()