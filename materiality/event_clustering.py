from pathlib import Path
import duckdb


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
# SETTINGS
# ============================================================

SOURCE_END_BUFFER_DAYS = 10

# Event-level thresholds
HIGH_PRIORITY_SCORE = 0.65
MEDIUM_PRIORITY_SCORE = 0.40

# Minimum event magnitude that is worth keeping
MIN_EVENT_ABSOLUTE_IMPACT = 10000.0


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
# BUILD EVENT CLUSTERS
# ============================================================

def build_event_clusters(con):

    print("\n[BUILD] KPI movement events")

    con.execute(
        f"""
        CREATE OR REPLACE TABLE fact_gmv_events AS

        WITH

        -- ====================================================
        -- 1. Source bounds
        -- ====================================================

        source_bounds AS (

            SELECT

                MIN(
                    CAST(
                        order_purchase_timestamp AS DATE
                    )
                ) AS source_start_date,

                MAX(
                    CAST(
                        order_purchase_timestamp AS DATE
                    )
                ) AS source_end_date

            FROM fact_order_items_enriched

            WHERE
                order_purchase_timestamp IS NOT NULL
        ),

        -- ====================================================
        -- 2. Candidate anomaly days
        -- ====================================================

        flagged AS (

            SELECT

                date,

                gmv,

                baseline,

                relative_change,

                z_score,

                absolute_change,

                materiality_status,

                priority_score

            FROM fact_gmv_materiality

            WHERE
                materiality_status IN (
                    'MATERIAL',
                    'STATISTICALLY_UNUSUAL',
                    'BUSINESS_MATERIAL'
                )
        ),

        -- ====================================================
        -- 3. Previous flagged day
        -- ====================================================

        with_previous AS (

            SELECT

                *,

                LAG(date)
                    OVER (
                        ORDER BY date
                    ) AS previous_event_date

            FROM flagged
        ),

        -- ====================================================
        -- 4. Identify event boundaries
        -- ====================================================

        marked AS (

            SELECT

                *,

                CASE

                    WHEN
                        previous_event_date IS NULL

                    THEN 1

                    WHEN
                        DATE_DIFF(
                            'day',
                            previous_event_date,
                            date
                        ) > 1

                    THEN 1

                    ELSE 0

                END AS new_event_group

            FROM with_previous
        ),

        -- ====================================================
        -- 5. Assign event IDs
        -- ====================================================

        grouped AS (

            SELECT

                *,

                SUM(new_event_group)
                    OVER (
                        ORDER BY date
                    ) AS event_group

            FROM marked
        ),

        -- ====================================================
        -- 6. Aggregate event statistics
        -- ====================================================

        event_summary AS (

            SELECT

                event_group,

                MIN(date)
                    AS event_start_date,

                MAX(date)
                    AS event_end_date,

                COUNT(*)
                    AS anomalous_days,

                MIN(
                    relative_change
                ) AS worst_relative_change,

                MAX(
                    relative_change
                ) AS strongest_positive_change,

                MAX(
                    ABS(relative_change)
                ) AS peak_change_abs,

                MAX(
                    ABS(z_score)
                ) AS peak_z_score,

                SUM(
                    ABS(absolute_change)
                ) AS cumulative_absolute_impact,

                MAX(
                    absolute_change
                ) AS maximum_absolute_change,

                MAX(
                    priority_score
                ) AS daily_priority

            FROM grouped

            GROUP BY
                event_group
        ),

        -- ====================================================
        -- 7. Add source coverage
        -- ====================================================

        with_coverage AS (

            SELECT

                e.*,

                s.source_start_date,

                s.source_end_date,

                DATE_DIFF(
                    'day',
                    e.event_end_date,
                    s.source_end_date
                ) AS days_to_source_end,

                CASE

                    WHEN
                        DATE_DIFF(
                            'day',
                            e.event_end_date,
                            s.source_end_date
                        )
                        <= {SOURCE_END_BUFFER_DAYS}

                    THEN 'SOURCE_EDGE'

                    ELSE 'NORMAL_DATA_COVERAGE'

                END AS coverage_status

            FROM event_summary e

            CROSS JOIN source_bounds s
        ),

        -- ====================================================
        -- 8. Calculate event priority
        -- ====================================================

        scored AS (

            SELECT

                *,

                LEAST(
                    1.0,
                    peak_change_abs / 1.0
                ) AS magnitude_score,

                LEAST(
                    1.0,
                    cumulative_absolute_impact / 100000.0
                ) AS business_impact_score,

                LEAST(
                    1.0,
                    anomalous_days / 7.0
                ) AS persistence_score,

                LEAST(
                    1.0,
                    peak_z_score / 5.0
                ) AS statistical_score

            FROM with_coverage
        )

        -- ====================================================
        -- 9. Final event output
        -- ====================================================

        SELECT

            event_group,

            event_start_date,

            event_end_date,

            anomalous_days,

            CASE

                WHEN
                    strongest_positive_change
                    >=
                    ABS(worst_relative_change)

                THEN 'POSITIVE'

                ELSE 'NEGATIVE'

            END AS direction,

            worst_relative_change,

            strongest_positive_change,

            peak_change_abs,

            peak_z_score,

            cumulative_absolute_impact,

            maximum_absolute_change,

            source_start_date,

            source_end_date,

            days_to_source_end,

            coverage_status,

            CASE

                WHEN
                    coverage_status = 'SOURCE_EDGE'

                THEN 'SOURCE_COVERAGE_EVENT'

                WHEN
                    cumulative_absolute_impact
                    < {MIN_EVENT_ABSOLUTE_IMPACT}

                THEN 'LOW_IMPACT_MOVEMENT'

                ELSE 'BUSINESS_MOVEMENT'

            END AS event_type,

            ROUND(
                (
                    0.30 * magnitude_score
                    +
                    0.30 * business_impact_score
                    +
                    0.20 * persistence_score
                    +
                    0.20 * statistical_score
                ),
                3
            ) AS event_priority_score,

            CASE

                WHEN
                    coverage_status = 'SOURCE_EDGE'

                THEN 'ABSTAIN'

                WHEN
                    cumulative_absolute_impact
                    < {MIN_EVENT_ABSOLUTE_IMPACT}

                THEN 'WATCH'

                WHEN
                    (
                        0.30 * magnitude_score
                        +
                        0.30 * business_impact_score
                        +
                        0.20 * persistence_score
                        +
                        0.20 * statistical_score
                    )
                    >= {HIGH_PRIORITY_SCORE}

                THEN 'HIGH'

                WHEN
                    (
                        0.30 * magnitude_score
                        +
                        0.30 * business_impact_score
                        +
                        0.20 * persistence_score
                        +
                        0.20 * statistical_score
                    )
                    >= {MEDIUM_PRIORITY_SCORE}

                THEN 'MEDIUM'

                ELSE 'LOW'

            END AS investigation_priority

        FROM scored

        ORDER BY
            event_priority_score DESC;
        """
    )

    print("[OK] KPI movement events")


# ============================================================
# DISPLAY EVENTS
# ============================================================

def show_events(con):

    print("\n" + "=" * 100)
    print("PRIORITIZED GMV EVENTS")
    print("=" * 100)

    df = con.execute(
        """
        SELECT

            event_group,

            event_start_date,

            event_end_date,

            anomalous_days,

            direction,

            event_type,

            investigation_priority,

            ROUND(
                peak_change_abs * 100,
                2
            ) AS peak_change_pct,

            ROUND(
                cumulative_absolute_impact,
                2
            ) AS cumulative_impact,

            ROUND(
                peak_z_score,
                2
            ) AS peak_z_score,

            coverage_status,

            ROUND(
                event_priority_score,
                3
            ) AS priority_score

        FROM fact_gmv_events

        ORDER BY
            event_priority_score DESC,
            event_start_date DESC

        LIMIT 25;
        """
    ).fetchdf()

    if df.empty:

        print("No KPI events found.")

        return

    print(
        df.to_string(
            index=False
        )
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n")
    print("=" * 100)
    print("BusinessIntelligence.ai")
    print("EVENT PRIORITIZATION ENGINE")
    print("=" * 100)

    con = connect_database()

    try:

        build_event_clusters(con)

        show_events(con)

        print("\n" + "=" * 100)
        print("EVENT PRIORITIZATION COMPLETE")
        print("=" * 100)

    finally:

        con.close()


if __name__ == "__main__":
    main()