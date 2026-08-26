from pathlib import Path
import duckdb
import json


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

    return duckdb.connect(str(DB_PATH))


# ============================================================
# GET TARGET EVENT
# ============================================================

def get_target_event(con):

    return con.execute(
        """
        SELECT

            event_group,
            event_start_date,
            event_end_date,
            anomalous_days,
            direction,
            event_type,
            investigation_priority,
            event_priority_score,
            worst_relative_change,
            strongest_positive_change,
            peak_change_abs,
            peak_z_score,
            cumulative_absolute_impact,
            maximum_absolute_change,
            coverage_status

        FROM fact_gmv_events

        WHERE
            event_type = 'BUSINESS_MOVEMENT'

            AND investigation_priority = 'HIGH'

        ORDER BY
            event_priority_score DESC,
            event_start_date

        LIMIT 1;
        """
    ).fetchone()


# ============================================================
# EVENT DECOMPOSITION
# ============================================================

def get_decomposition(
    con,
    event_start,
    event_end
):

    duration = (
        event_end - event_start
    ).days + 1

    comparison_end = con.execute(
        """
        SELECT ?
               - INTERVAL '1 day';
        """,
        [event_start],
    ).fetchone()[0]

    comparison_start = con.execute(
        f"""
        SELECT ?
               - INTERVAL '{duration} days';
        """,
        [event_start],
    ).fetchone()[0]

    result = con.execute(
        """
        WITH current_period AS (

            SELECT

                SUM(price) AS gmv,

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
                AND ?
        ),

        previous_period AS (

            SELECT

                SUM(price) AS gmv,

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
                AND ?
        )

        SELECT

            c.gmv AS current_gmv,
            p.gmv AS previous_gmv,

            c.orders AS current_orders,
            p.orders AS previous_orders

        FROM current_period c
        CROSS JOIN previous_period p;
        """,
        [
            event_start,
            event_end,
            comparison_start,
            comparison_end,
        ],
    ).fetchone()

    (
        current_gmv,
        previous_gmv,
        current_orders,
        previous_orders,
    ) = result

    current_aov = (
        current_gmv / current_orders
        if current_orders
        else None
    )

    previous_aov = (
        previous_gmv / previous_orders
        if previous_orders
        else None
    )

    delta_orders = (
        current_orders
        - previous_orders
    )

    delta_aov = (
        current_aov
        - previous_aov
    )

    avg_aov = (
        current_aov
        + previous_aov
    ) / 2

    avg_orders = (
        current_orders
        + previous_orders
    ) / 2

    volume_effect = (
        delta_orders
        * avg_aov
    )

    aov_effect = (
        delta_aov
        * avg_orders
    )

    total_change = (
        current_gmv
        - previous_gmv
    )

    residual = (
        total_change
        - volume_effect
        - aov_effect
    )

    return {

        "comparison_period": {
            "start":
                str(comparison_start),

            "end":
                str(comparison_end),
        },

        "previous_gmv":
            float(previous_gmv),

        "current_gmv":
            float(current_gmv),

        "gmv_change":
            float(total_change),

        "previous_orders":
            int(previous_orders),

        "current_orders":
            int(current_orders),

        "orders_change":
            int(delta_orders),

        "previous_aov":
            float(previous_aov),

        "current_aov":
            float(current_aov),

        "aov_change":
            float(delta_aov),

        "volume_effect":
            float(volume_effect),

        "aov_effect":
            float(aov_effect),

        "residual_effect":
            float(residual),
    }


# ============================================================
# DRIVER RECORDS
# ============================================================

def get_drivers(
    con,
    event_id
):

    rows = con.execute(
        """
        SELECT

            c.driver_type,

            c.driver,

            c.gmv_change,
            c.contribution_share,

            c.review_status,
            c.review_event_records,
            c.review_comparison_records,
            c.review_directional_support,

            c.context_status,

            c.confidence,
            c.structural_score,
            c.review_score,
            c.context_score,

            c.independent_sources,

            c.final_status,

            a.decision,
            a.controllable_lever,
            a.action,
            a.owner,
            a.monitoring_plan,
            a.action_type

        FROM fact_driver_confidence c

        LEFT JOIN fact_recommended_actions a

            ON c.event_id = a.event_id

            AND c.driver_type =
                a.driver_type

            AND c.driver =
                a.driver

        WHERE
            c.event_id = ?

        ORDER BY
            c.confidence DESC,
            ABS(
                c.contribution_share
            ) DESC;
        """,
        [event_id],
    ).fetchall()
    drivers = []

    for row in rows:

        (
            driver_type,
            driver,
            gmv_change,
            contribution_share,

            review_status,
            review_event_records,
            review_comparison_records,
            review_directional_support,

            context_status,

            confidence,
            structural_score,
            review_score,
            context_score,

            independent_sources,

            final_status,

            decision,
            controllable_lever,
            action,
            owner,
            monitoring_plan,
            action_type,
        ) = row

        drivers.append(
            {
                "driver_type":
                    driver_type,

                "driver":
                    driver,

                "observed_contribution": {
                    "gmv_change":
                        float(gmv_change),

                    "share":
                        float(
                            contribution_share
                        ),
                },

                "evidence": {

                    "review": {
                        "status":
                            review_status,

                        "event_records":
                            int(
                                review_event_records
                                or 0
                            ),

                        "comparison_records":
                            int(
                                review_comparison_records
                                or 0
                            ),

                        "directional_support":
                            float(
                                review_directional_support
                                or 0
                            ),
                    },

                    "context": {
                        "status":
                            context_status
                    },
                },

                "confidence": {

                    "overall":
                        float(confidence),

                    "structural":
                        float(
                            structural_score
                        ),

                    "review":
                        float(
                            review_score
                        ),

                    "context":
                        float(
                            context_score
                        ),

                    "independent_sources":
                        int(
                            independent_sources
                        ),
                },

                "status":
                    final_status,

                "action": {

                    "decision":
                        decision,

                    "lever":
                        controllable_lever,

                    "action":
                        action,

                    "owner":
                        owner,

                    "monitoring_plan":
                        monitoring_plan,

                    "action_type":
                        action_type,
                },
            }
        )

    return drivers


# ============================================================
# BUILD INSIGHT
# ============================================================

def build_insight(con):

    event = get_target_event(con)

    if event is None:

        raise RuntimeError(
            "No high-priority business movement found."
        )

    (
        event_id,
        event_start,
        event_end,
        anomalous_days,
        direction,
        event_type,
        investigation_priority,
        event_priority_score,
        worst_relative_change,
        strongest_positive_change,
        peak_change_abs,
        peak_z_score,
        cumulative_absolute_impact,
        maximum_absolute_change,
        coverage_status,
    ) = event

    decomposition = get_decomposition(
        con,
        event_start,
        event_end,
    )

    drivers = get_drivers(
        con,
        event_id,
    )

    # --------------------------------------------------------
    # Data-quality assessment
    # --------------------------------------------------------

    data_quality = {

        "commerce_source":
            "NORMAL_DATA_COVERAGE"
            if coverage_status
            == "NORMAL_DATA_COVERAGE"
            else coverage_status,

        "review_text_available":
            True,

        "business_context_available":
            False,

        "notes": [
            "Business context has no overlapping "
            "scenario for this 2017 event.",
            "Root-cause interpretation therefore "
            "remains conservative."
        ],
    }

    # --------------------------------------------------------
    # Insight object
    # --------------------------------------------------------

    insight = {

        "insight_id":
            f"GMV_EVT_{int(event_id):03d}",

        "kpi": {

            "id":
                "marketplace_gmv",

            "name":
                "Marketplace GMV",

            "grain":
                "order_item",

            "primary_date":
                "order_purchase_timestamp",
        },

        "event": {

            "event_id":
                int(event_id),

            "start_date":
                str(event_start),

            "end_date":
                str(event_end),

            "duration_days":
                int(anomalous_days),

            "direction":
                direction,

            "event_type":
                event_type,

            "investigation_priority":
                investigation_priority,

            "priority_score":
                float(
                    event_priority_score
                ),

            "peak_change":
                float(
                    peak_change_abs
                ),

            "peak_z_score":
                float(
                    peak_z_score
                ),

            "cumulative_absolute_impact":
                float(
                    cumulative_absolute_impact
                ),

            "source_coverage":
                coverage_status,
        },

        "movement":
            decomposition,

        "drivers":
            drivers,

        "data_quality":
            data_quality,

        "lineage": {

            "raw_sources": [
                "olist_orders_dataset",
                "olist_order_items_dataset",
                "olist_customers_dataset",
                "olist_products_dataset",
                "olist_sellers_dataset",
                "olist_order_reviews_dataset"
            ],

            "analytical_tables": [
                "fact_orders_enriched",
                "fact_order_items_enriched",
                "fact_reviews",
                "fact_review_sentiment",
                "fact_driver_confidence",
                "fact_recommended_actions"
            ],

            "methods": [
                "seasonal robust baseline",
                "robust z-score",
                "materiality rules",
                "event clustering",
                "GMV volume/AOV decomposition",
                "segment contribution analysis",
                "aspect tagging",
                "multilingual sentiment",
                "evidence fusion"
            ],
        },

        "llm_policy": {

            "quantitative_truth_source":
                "deterministic analytical layer",

            "allowed_llm_tasks": [
                "narrative synthesis",
                "persona adaptation",
                "natural language explanation",
                "uncertainty wording"
            ],

            "forbidden_llm_tasks": [
                "calculating KPI values",
                "inventing drivers",
                "overriding confidence",
                "creating unsupported actions"
            ],
        },
    }

    return insight


# ============================================================
# SAVE INSIGHT
# ============================================================

def save_insight(
    con,
    insight
):

    insight_json = json.dumps(
        insight,
        indent=2,
        ensure_ascii=False,
    )

    con.execute(
        """
        CREATE OR REPLACE TABLE
        latest_insight AS

        SELECT
            ? AS insight_id,
            ? AS insight_json;
        """,
        [
            insight[
                "insight_id"
            ],
            insight_json,
        ],
    )

    output_dir = (
        PROJECT_ROOT
        / "data"
        / "insights"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    output_path = (
        output_dir
        / "latest_insight.json"
    )

    output_path.write_text(
        insight_json,
        encoding="utf-8",
    )

    print(
        f"\n[OK] Insight saved to:\n"
        f"{output_path}"
    )


# ============================================================
# DISPLAY
# ============================================================

def show_insight(insight):

    print("\n" + "=" * 100)
    print("CANONICAL INSIGHT")
    print("=" * 100)

    print(
        json.dumps(
            insight,
            indent=2,
            ensure_ascii=False,
        )
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n")
    print("=" * 100)
    print("BusinessIntelligence.ai")
    print("BUILD CANONICAL INSIGHT")
    print("=" * 100)

    con = connect_database()

    try:

        insight = build_insight(
            con
        )

        save_insight(
            con,
            insight
        )

        show_insight(
            insight
        )

        print("\n" + "=" * 100)
        print("CANONICAL INSIGHT COMPLETE")
        print("=" * 100)

    finally:

        con.close()


if __name__ == "__main__":
    main()