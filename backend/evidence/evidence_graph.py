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
# SELECT EVENT
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
            event_priority_score

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
# GET EVENT DRIVER CONTRIBUTIONS
# ============================================================

def get_event_driver_candidates(
    con,
    event_group
):

    # --------------------------------------------------------
    # Event information
    # --------------------------------------------------------

    event = con.execute(
        """
        SELECT

            event_start_date,
            event_end_date

        FROM fact_gmv_events

        WHERE event_group = ?;
        """,
        [event_group],
    ).fetchone()

    if event is None:
        return []

    event_start, event_end = event

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

    # --------------------------------------------------------
    # Total GMV change
    # --------------------------------------------------------

    total_change = con.execute(
        """
        WITH current_period AS (

            SELECT
                SUM(price) AS gmv

            FROM fact_order_items_enriched

            WHERE
                CAST(
                    order_purchase_timestamp AS DATE
                )
                BETWEEN ?
                AND ?
        ),

        previous_period AS (

            SELECT
                SUM(price) AS gmv

            FROM fact_order_items_enriched

            WHERE
                CAST(
                    order_purchase_timestamp AS DATE
                )
                BETWEEN ?
                AND ?
        )

        SELECT
            current_period.gmv
            -
            previous_period.gmv

        FROM current_period
        CROSS JOIN previous_period;
        """,
        [
            event_start,
            event_end,
            comparison_start,
            comparison_end,
        ],
    ).fetchone()[0]

    # --------------------------------------------------------
    # Customer-state candidates
    # --------------------------------------------------------

    states = con.execute(
        """
        WITH current_period AS (

            SELECT

                customer_state,
                SUM(price) AS gmv

            FROM fact_order_items_enriched

            WHERE
                CAST(
                    order_purchase_timestamp AS DATE
                )
                BETWEEN ?
                AND ?

                AND customer_state IS NOT NULL

            GROUP BY 1
        ),

        previous_period AS (

            SELECT

                customer_state,
                SUM(price) AS gmv

            FROM fact_order_items_enriched

            WHERE
                CAST(
                    order_purchase_timestamp AS DATE
                )
                BETWEEN ?
                AND ?

                AND customer_state IS NOT NULL

            GROUP BY 1
        )

        SELECT

            COALESCE(
                c.customer_state,
                p.customer_state
            ) AS driver,

            COALESCE(c.gmv, 0)
            -
            COALESCE(p.gmv, 0)
            AS gmv_change

        FROM current_period c

        FULL OUTER JOIN previous_period p

            ON c.customer_state =
               p.customer_state

        WHERE
            COALESCE(c.gmv, 0)
            !=
            COALESCE(p.gmv, 0)

        ORDER BY
            ABS(
                COALESCE(c.gmv, 0)
                -
                COALESCE(p.gmv, 0)
            ) DESC

        LIMIT 10;
        """,
        [
            event_start,
            event_end,
            comparison_start,
            comparison_end,
        ],
    ).fetchall()

    # --------------------------------------------------------
    # Category candidates
    # --------------------------------------------------------

    categories = con.execute(
        """
        WITH current_period AS (

            SELECT

                category_name,
                SUM(price) AS gmv

            FROM fact_order_items_enriched

            WHERE
                CAST(
                    order_purchase_timestamp AS DATE
                )
                BETWEEN ?
                AND ?

                AND category_name IS NOT NULL

            GROUP BY 1
        ),

        previous_period AS (

            SELECT

                category_name,
                SUM(price) AS gmv

            FROM fact_order_items_enriched

            WHERE
                CAST(
                    order_purchase_timestamp AS DATE
                )
                BETWEEN ?
                AND ?

                AND category_name IS NOT NULL

            GROUP BY 1
        )

        SELECT

            COALESCE(
                c.category_name,
                p.category_name
            ) AS driver,

            COALESCE(c.gmv, 0)
            -
            COALESCE(p.gmv, 0)
            AS gmv_change

        FROM current_period c

        FULL OUTER JOIN previous_period p

            ON c.category_name =
               p.category_name

        WHERE
            COALESCE(c.gmv, 0)
            !=
            COALESCE(p.gmv, 0)

        ORDER BY
            ABS(
                COALESCE(c.gmv, 0)
                -
                COALESCE(p.gmv, 0)
            ) DESC

        LIMIT 10;
        """,
        [
            event_start,
            event_end,
            comparison_start,
            comparison_end,
        ],
    ).fetchall()

    # --------------------------------------------------------
    # Create evidence records
    # --------------------------------------------------------

    evidence = []

    for driver, change in states:

        share = (
            change / abs(total_change)
            if total_change != 0
            else 0.0
        )

        evidence.append(
            {
                "event_id": int(event_group),

                "driver_type":
                    "customer_state",

                "driver":
                    str(driver),

                "observed_contribution":
                    {
                        "gmv_change":
                            float(change),

                        "contribution_share":
                            float(share),
                    },

                "period":
                    {
                        "start":
                            str(event_start),

                        "end":
                            str(event_end),
                    },

                "comparison_period":
                    {
                        "start":
                            str(comparison_start),

                        "end":
                            str(comparison_end),
                    },

                "context":
                    {
                        "matched":
                            False,

                        "reason":
                            "Context matching not yet evaluated.",
                    },

                "status":
                    "HYPOTHESIS",
            }
        )

    for driver, change in categories:

        share = (
            change / abs(total_change)
            if total_change != 0
            else 0.0
        )

        evidence.append(
            {
                "event_id": int(event_group),

                "driver_type":
                    "category",

                "driver":
                    str(driver),

                "observed_contribution":
                    {
                        "gmv_change":
                            float(change),

                        "contribution_share":
                            float(share),
                    },

                "period":
                    {
                        "start":
                            str(event_start),

                        "end":
                            str(event_end),
                    },

                "comparison_period":
                    {
                        "start":
                            str(comparison_start),

                        "end":
                            str(comparison_end),
                    },

                "context":
                    {
                        "matched":
                            False,

                        "reason":
                            "Context matching not yet evaluated.",
                    },

                "status":
                    "HYPOTHESIS",
            }
        )

    return evidence


# ============================================================
# SAVE EVIDENCE
# ============================================================

def save_evidence(
    con,
    evidence
):

    # JSON string is useful because this object will eventually
    # be passed to the LLM.

    rows = [
        (
            item["event_id"],
            item["driver_type"],
            item["driver"],
            json.dumps(
                item
            ),
        )
        for item in evidence
    ]

    con.execute(
        """
        CREATE OR REPLACE TABLE
        fact_evidence_records AS

        SELECT

            *
        FROM (
            VALUES

        """
        +
        ",".join(
            ["(?, ?, ?, ?)" for _ in rows]
        )
        +
        """
        )

        AS t(
            event_id,
            driver_type,
            driver,
            evidence_json
        );
        """,
        [
            value
            for row in rows
            for value in row
        ],
    )


# ============================================================
# DISPLAY
# ============================================================

def show_evidence(evidence):

    print("\n" + "=" * 90)
    print("EVIDENCE RECORDS")
    print("=" * 90)

    for item in evidence[:10]:

        print("\nDriver:")
        print(
            f"  {item['driver_type']}: "
            f"{item['driver']}"
        )

        print(
            "GMV contribution:"
        )

        print(
            f"  Change: "
            f"{item['observed_contribution']['gmv_change']:,.2f}"
        )

        print(
            f"  Share: "
            f"{item['observed_contribution']['contribution_share'] * 100:.2f}%"
        )

        print(
            f"Status: {item['status']}"
        )

        print(
            f"Context: "
            f"{item['context']['reason']}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n")
    print("=" * 90)
    print("BusinessIntelligence.ai")
    print("EVIDENCE FUSION FOUNDATION")
    print("=" * 90)

    con = connect_database()

    try:

        event = get_target_event(con)

        if event is None:

            print(
                "No high-priority business event found."
            )

            return

        event_group = event[0]

        evidence = get_event_driver_candidates(
            con,
            event_group
        )

        save_evidence(
            con,
            evidence
        )

        show_evidence(
            evidence
        )

        print(
            "\nEvidence records created: "
            f"{len(evidence):,}"
        )

        print("\n" + "=" * 90)
        print("EVIDENCE FOUNDATION COMPLETE")
        print("=" * 90)

    finally:

        con.close()


if __name__ == "__main__":
    main()