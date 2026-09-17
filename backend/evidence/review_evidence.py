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
# DATABASE
# ============================================================

def connect_database():

    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"DuckDB database not found:\n{DB_PATH}"
        )

    return duckdb.connect(str(DB_PATH))


# ============================================================
# TARGET EVENT
# ============================================================

def get_target_event(con):

    return con.execute(
        """
        SELECT
            event_group,
            event_start_date,
            event_end_date
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
# PERIODS
# ============================================================

def get_periods(
    event_start,
    event_end
):

    duration = (
        event_end - event_start
    ).days + 1

    comparison_end = (
        event_start
        - duckdb.execute(
            "SELECT INTERVAL '1 day'"
        ).fetchone()[0]
    )

    comparison_start = (
        event_start
        - duckdb.execute(
            f"SELECT INTERVAL '{duration} days'"
        ).fetchone()[0]
    )

    return (
        event_start,
        event_end,
        comparison_start,
        comparison_end,
    )


# ============================================================
# BUILD BASE REVIEW-EVIDENCE TABLE
# ============================================================

def build_review_evidence_base(con):

    print(
        "\n[BUILD] Building review evidence base"
    )

    con.execute(
        """
        CREATE OR REPLACE TABLE
        fact_review_evidence_base AS

        SELECT DISTINCT

            rs.review_id,

            rs.order_id,

            rs.review_score,

            rs.review_creation_date,

            rs.aspect,

            rs.sentiment,

            rs.sentiment_confidence,

            c.customer_state,

            oi.category_name

        FROM fact_review_sentiment rs

        LEFT JOIN fact_orders o
            ON rs.order_id = o.order_id

        LEFT JOIN dim_customer c
            ON o.customer_id = c.customer_id

        LEFT JOIN (

            SELECT DISTINCT
                order_id,
                category_name
            FROM fact_order_items_enriched
            WHERE category_name IS NOT NULL

        ) oi
            ON rs.order_id = oi.order_id

        WHERE
            rs.review_creation_date IS NOT NULL;
        """
    )

    print(
        "[OK] Review evidence base created"
    )


# ============================================================
# SENTIMENT SUMMARY
# ============================================================

def get_sentiment_summary(
    con,
    dimension,
    target,
    event_start,
    event_end,
    comparison_start,
    comparison_end,
):

    if dimension == "customer_state":

        filter_column = "customer_state"

    elif dimension == "category":

        filter_column = "category_name"

    else:

        raise ValueError(
            f"Unsupported dimension: {dimension}"
        )

    query = f"""
        WITH event_reviews AS (

            SELECT *

            FROM fact_review_evidence_base

            WHERE
                {filter_column} = ?

                AND CAST(
                    review_creation_date AS DATE
                )
                BETWEEN ?
                AND ?
        ),

        comparison_reviews AS (

            SELECT *

            FROM fact_review_evidence_base

            WHERE
                {filter_column} = ?

                AND CAST(
                    review_creation_date AS DATE
                )
                BETWEEN ?
                AND ?
        ),

        event_summary AS (

            SELECT

                aspect,

                sentiment,

                COUNT(*) AS count_records,

                AVG(
                    sentiment_confidence
                ) AS avg_confidence,

                AVG(
                    review_score
                ) AS avg_review_score

            FROM event_reviews

            GROUP BY
                aspect,
                sentiment
        ),

        comparison_summary AS (

            SELECT

                aspect,

                sentiment,

                COUNT(*) AS count_records,

                AVG(
                    sentiment_confidence
                ) AS avg_confidence,

                AVG(
                    review_score
                ) AS avg_review_score

            FROM comparison_reviews

            GROUP BY
                aspect,
                sentiment
        )

        SELECT

            COALESCE(
                e.aspect,
                c.aspect
            ) AS aspect,

            COALESCE(
                e.sentiment,
                c.sentiment
            ) AS sentiment,

            COALESCE(
                e.count_records,
                0
            ) AS event_count,

            COALESCE(
                c.count_records,
                0
            ) AS comparison_count,

            COALESCE(
                e.count_records,
                0
            )
            -
            COALESCE(
                c.count_records,
                0
            ) AS count_change,

            e.avg_confidence AS event_confidence,

            c.avg_confidence AS comparison_confidence,

            e.avg_review_score AS event_avg_score,

            c.avg_review_score AS comparison_avg_score

        FROM event_summary e

        FULL OUTER JOIN comparison_summary c

            ON e.aspect = c.aspect
            AND e.sentiment = c.sentiment

        ORDER BY
            ABS(
                COALESCE(
                    e.count_records,
                    0
                )
                -
                COALESCE(
                    c.count_records,
                    0
                )
            ) DESC;
    """

    return con.execute(
        query,
        [
            target,
            event_start,
            event_end,
            target,
            comparison_start,
            comparison_end,
        ],
    ).fetchdf()


# ============================================================
# SENTIMENT SHARE BY ASPECT
# ============================================================

def get_aspect_sentiment_change(
    con,
    dimension,
    target,
    event_start,
    event_end,
    comparison_start,
    comparison_end,
):

    if dimension == "customer_state":

        filter_column = "customer_state"

    elif dimension == "category":

        filter_column = "category_name"

    else:

        raise ValueError(
            f"Unsupported dimension: {dimension}"
        )

    query = f"""
        WITH event_aspects AS (

            SELECT

                aspect,

                sentiment,

                COUNT(*) AS count_records

            FROM fact_review_evidence_base

            WHERE
                {filter_column} = ?

                AND CAST(
                    review_creation_date AS DATE
                )
                BETWEEN ?
                AND ?

            GROUP BY
                aspect,
                sentiment
        ),

        comparison_aspects AS (

            SELECT

                aspect,

                sentiment,

                COUNT(*) AS count_records

            FROM fact_review_evidence_base

            WHERE
                {filter_column} = ?

                AND CAST(
                    review_creation_date AS DATE
                )
                BETWEEN ?
                AND ?

            GROUP BY
                aspect,
                sentiment
        )

        SELECT

            COALESCE(
                e.aspect,
                c.aspect
            ) AS aspect,

            COALESCE(
                e.sentiment,
                c.sentiment
            ) AS sentiment,

            COALESCE(
                e.count_records,
                0
            ) AS event_count,

            COALESCE(
                c.count_records,
                0
            ) AS comparison_count

        FROM event_aspects e

        FULL OUTER JOIN comparison_aspects c

            ON e.aspect = c.aspect
            AND e.sentiment = c.sentiment

        ORDER BY
            aspect,
            sentiment;
    """

    df = con.execute(
        query,
        [
            target,
            event_start,
            event_end,
            target,
            comparison_start,
            comparison_end,
        ],
    ).fetchdf()

    return df


# ============================================================
# BUILD EVENT REVIEW EVIDENCE
# ============================================================

def build_event_review_evidence(
    con,
    event_group,
    event_start,
    event_end,
):

    (
        event_start,
        event_end,
        comparison_start,
        comparison_end,
    ) = get_periods(
        event_start,
        event_end,
    )

    print("\n" + "=" * 90)
    print("REVIEW EVIDENCE FOR EVENT")
    print("=" * 90)

    print(
        f"Event period: "
        f"{event_start} -> {event_end}"
    )

    print(
        f"Comparison period: "
        f"{comparison_start} -> {comparison_end}"
    )

    # --------------------------------------------------------
    # Top customer-state candidates
    # --------------------------------------------------------

    states = con.execute(
        """
        SELECT
            driver
        FROM fact_evidence_records
        WHERE
            event_id = ?
            AND driver_type = 'customer_state'
        ORDER BY
            ABS(
                CAST(
                    JSON_EXTRACT(
                        evidence_json,
                        '$.observed_contribution.gmv_change'
                    ) AS DOUBLE
                )
            ) DESC
        LIMIT 5;
        """,
        [event_group],
    ).fetchall()

    # --------------------------------------------------------
    # State evidence
    # --------------------------------------------------------

    all_records = []

    for (state,) in states:

        df = get_aspect_sentiment_change(
            con,
            "customer_state",
            state,
            event_start,
            event_end,
            comparison_start,
            comparison_end,
        )

        if df.empty:
            continue

        df["event_id"] = int(
            event_group
        )

        df["dimension"] = (
            "customer_state"
        )

        df["driver"] = state

        all_records.append(df)

    # --------------------------------------------------------
    # Category candidates
    # --------------------------------------------------------

    categories = con.execute(
        """
        SELECT
            driver
        FROM fact_evidence_records
        WHERE
            event_id = ?
            AND driver_type = 'category'
        ORDER BY
            ABS(
                CAST(
                    JSON_EXTRACT(
                        evidence_json,
                        '$.observed_contribution.gmv_change'
                    ) AS DOUBLE
                )
            ) DESC
        LIMIT 5;
        """,
        [event_group],
    ).fetchall()

    # --------------------------------------------------------
    # Category evidence
    # --------------------------------------------------------

    for (category,) in categories:

        df = get_aspect_sentiment_change(
            con,
            "category",
            category,
            event_start,
            event_end,
            comparison_start,
            comparison_end,
        )

        if df.empty:
            continue

        df["event_id"] = int(
            event_group
        )

        df["dimension"] = (
            "category"
        )

        df["driver"] = category

        all_records.append(df)

    # --------------------------------------------------------
    # Combine
    # --------------------------------------------------------

    if not all_records:

        con.execute(
            """
            CREATE OR REPLACE TABLE
            fact_event_review_evidence AS

            SELECT
                NULL::INTEGER AS event_id,
                NULL::VARCHAR AS dimension,
                NULL::VARCHAR AS driver,
                NULL::VARCHAR AS aspect,
                NULL::VARCHAR AS sentiment,
                NULL::BIGINT AS event_count,
                NULL::BIGINT AS comparison_count,
                NULL::BIGINT AS count_change

            WHERE FALSE;
            """
        )

        print(
            "[WARNING] No review evidence found"
        )

        return

    import pandas as pd

    combined = pd.concat(
        all_records,
        ignore_index=True
    )

    con.register(
        "review_evidence_temp",
        combined
    )

    con.execute(
        """
        CREATE OR REPLACE TABLE
        fact_event_review_evidence AS

        SELECT *
        FROM review_evidence_temp;
        """
    )

    con.unregister(
        "review_evidence_temp"
    )

    print(
        f"[OK] Review evidence records: "
        f"{len(combined):,}"
    )


# ============================================================
# DISPLAY
# ============================================================

def show_review_evidence(con):

    print("\n" + "=" * 90)
    print("REVIEW SENTIMENT CHANGES")
    print("=" * 90)

    # First inspect the actual table columns.
    columns = con.execute(
        """
        SELECT
            column_name
        FROM information_schema.columns
        WHERE
            table_schema = 'main'
            AND table_name = 'fact_event_review_evidence'
        ORDER BY ordinal_position;
        """
    ).fetchall()

    actual_columns = [
        row[0]
        for row in columns
    ]

    print("\nEvidence table columns:")
    print(actual_columns)

    # Fetch everything for now.
    # This avoids assuming a column exists while we validate
    # the DataFrame -> DuckDB schema.
    df = con.execute(
        """
        SELECT *
        FROM fact_event_review_evidence
        ORDER BY
            dimension,
            driver,
            aspect,
            sentiment;
        """
    ).fetchdf()

    if df.empty:

        print(
            "\nNo review evidence available."
        )

        return

    print("\nReview evidence:")

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
    print("=" * 90)
    print("BusinessIntelligence.ai")
    print("REVIEW EVIDENCE ENGINE")
    print("=" * 90)

    con = connect_database()

    try:

        event = get_target_event(con)

        if event is None:

            print(
                "No high-priority business event found."
            )

            return

        (
            event_group,
            event_start,
            event_end,
        ) = event

        build_review_evidence_base(
            con
        )

        build_event_review_evidence(
            con,
            event_group,
            event_start,
            event_end,
        )

        show_review_evidence(
            con
        )

        print("\n" + "=" * 90)
        print("REVIEW EVIDENCE ENGINE COMPLETE")
        print("=" * 90)

    finally:

        con.close()


if __name__ == "__main__":
    main()