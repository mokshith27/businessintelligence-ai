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
# GET EVENT
# ============================================================

def get_event(con, event_group=None):

    if event_group is None:

        result = con.execute(
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
            WHERE event_type = 'BUSINESS_MOVEMENT'
              AND investigation_priority = 'HIGH'
            ORDER BY
                event_priority_score DESC,
                event_start_date
            LIMIT 1;
            """
        ).fetchone()

    else:

        result = con.execute(
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
            WHERE event_group = ?
            """,
            [event_group],
        ).fetchone()

    return result


# ============================================================
# EVENT WINDOW
# ============================================================

def build_event_window(
    con,
    event_start,
    event_end
):

    # Number of days in event
    duration = (
        event_end - event_start
    ).days + 1

    # Equal-length immediately preceding period
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
# PERIOD KPI SUMMARY
# ============================================================

def get_period_metrics(
    con,
    start_date,
    end_date
):

    result = con.execute(
        """
        SELECT

            SUM(price) AS gmv,

            COUNT(
                DISTINCT order_id
            ) AS orders

        FROM fact_order_items_enriched

        WHERE
            CAST(
                order_purchase_timestamp AS DATE
            )
            BETWEEN ?
            AND ?;
        """,
        [start_date, end_date],
    ).fetchone()

    gmv = result[0]
    orders = result[1]

    aov = (
        gmv / orders
        if orders and gmv is not None
        else None
    )

    return {
        "gmv": gmv,
        "orders": orders,
        "aov": aov,
    }


# ============================================================
# GMV / ORDER / AOV DECOMPOSITION
# ============================================================

def decompose_change(
    previous,
    current
):

    previous_gmv = previous["gmv"]
    current_gmv = current["gmv"]

    previous_orders = previous["orders"]
    current_orders = current["orders"]

    previous_aov = previous["aov"]
    current_aov = current["aov"]

    if (
        previous_gmv is None
        or current_gmv is None
        or previous_orders == 0
        or current_orders == 0
        or previous_aov is None
        or current_aov is None
    ):
        return None

    delta_orders = (
        current_orders
        - previous_orders
    )

    delta_aov = (
        current_aov
        - previous_aov
    )

    average_aov = (
        previous_aov
        + current_aov
    ) / 2

    average_orders = (
        previous_orders
        + current_orders
    ) / 2

    volume_effect = (
        delta_orders
        * average_aov
    )

    aov_effect = (
        delta_aov
        * average_orders
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
        "previous_gmv": previous_gmv,
        "current_gmv": current_gmv,
        "gmv_change": total_change,

        "previous_orders": previous_orders,
        "current_orders": current_orders,
        "orders_change": delta_orders,

        "previous_aov": previous_aov,
        "current_aov": current_aov,
        "aov_change": delta_aov,

        "volume_effect": volume_effect,
        "aov_effect": aov_effect,
        "residual_effect": residual,
    }


# ============================================================
# SEGMENT CONTRIBUTION
# ============================================================

def get_segment_contribution(
    con,
    start_date,
    end_date,
    comparison_start,
    comparison_end,
    dimension
):

    if dimension == "customer_state":

        segment_expression = "customer_state"

    elif dimension == "category":

        segment_expression = "category_name"

    elif dimension == "seller":

        segment_expression = "seller_id"

    else:

        raise ValueError(
            f"Unsupported dimension: {dimension}"
        )

    query = f"""
        WITH current_period AS (

            SELECT

                {segment_expression}
                    AS segment,

                SUM(price) AS gmv,

                COUNT(
                    DISTINCT order_id
                ) AS orders

            FROM fact_order_items_enriched

            WHERE
                CAST(
                    order_purchase_timestamp AS DATE
                )
                BETWEEN ?
                AND ?

                AND {segment_expression} IS NOT NULL

            GROUP BY 1
        ),

        comparison_period AS (

            SELECT

                {segment_expression}
                    AS segment,

                SUM(price) AS gmv,

                COUNT(
                    DISTINCT order_id
                ) AS orders

            FROM fact_order_items_enriched

            WHERE
                CAST(
                    order_purchase_timestamp AS DATE
                )
                BETWEEN ?
                AND ?

                AND {segment_expression} IS NOT NULL

            GROUP BY 1
        )

        SELECT

            COALESCE(
                c.segment,
                p.segment
            ) AS segment,

            COALESCE(
                p.gmv,
                0
            ) AS previous_gmv,

            COALESCE(
                c.gmv,
                0
            ) AS current_gmv,

            COALESCE(
                c.gmv,
                0
            )
            -
            COALESCE(
                p.gmv,
                0
            ) AS gmv_change,

            COALESCE(
                p.orders,
                0
            ) AS previous_orders,

            COALESCE(
                c.orders,
                0
            ) AS current_orders

        FROM current_period c

        FULL OUTER JOIN comparison_period p
            ON c.segment = p.segment

        WHERE
            COALESCE(c.gmv, 0)
            !=
            COALESCE(p.gmv, 0)

        ORDER BY
            gmv_change DESC;
    """

    return con.execute(
        query,
        [
            start_date,
            end_date,
            comparison_start,
            comparison_end,
        ],
    ).fetchdf()


# ============================================================
# ADD CONTRIBUTION SHARE
# ============================================================

def add_contribution_share(
    df,
    total_change
):

    if df.empty:
        return df

    if total_change == 0:

        df["contribution_share"] = 0.0

    else:

        df["contribution_share"] = (
            df["gmv_change"]
            / abs(total_change)
        )

    return df


# ============================================================
# BUILD INVESTIGATION TABLE
# ============================================================

def build_event_investigation_table(
    con,
    event_group
):

    con.execute(
        """
        CREATE OR REPLACE TABLE fact_event_driver_investigation AS

        SELECT
            *
        FROM (
            SELECT
                ? AS event_group
        );
        """,
        [event_group],
    )


# ============================================================
# DISPLAY EVENT DECOMPOSITION
# ============================================================

def show_decomposition(
    event,
    previous,
    current
):

    decomposition = decompose_change(
        previous,
        current
    )

    print("\n" + "=" * 90)
    print("EVENT-LEVEL GMV DECOMPOSITION")
    print("=" * 90)

    if decomposition is None:

        print(
            "Unable to calculate decomposition."
        )

        return

    print(
        f"Previous GMV       : "
        f"{decomposition['previous_gmv']:,.2f}"
    )

    print(
        f"Current GMV        : "
        f"{decomposition['current_gmv']:,.2f}"
    )

    print(
        f"GMV change         : "
        f"{decomposition['gmv_change']:,.2f}"
    )

    print(
        f"\nPrevious orders    : "
        f"{decomposition['previous_orders']:,}"
    )

    print(
        f"Current orders     : "
        f"{decomposition['current_orders']:,}"
    )

    print(
        f"Orders change      : "
        f"{decomposition['orders_change']:,}"
    )

    print(
        f"\nPrevious AOV       : "
        f"{decomposition['previous_aov']:,.2f}"
    )

    print(
        f"Current AOV        : "
        f"{decomposition['current_aov']:,.2f}"
    )

    print(
        f"AOV change         : "
        f"{decomposition['aov_change']:,.2f}"
    )

    print("\nContribution effects:")

    print(
        f"Volume effect      : "
        f"{decomposition['volume_effect']:,.2f}"
    )

    print(
        f"AOV effect         : "
        f"{decomposition['aov_effect']:,.2f}"
    )

    print(
        f"Residual            : "
        f"{decomposition['residual_effect']:,.2f}"
    )


# ============================================================
# DISPLAY SEGMENT DRIVERS
# ============================================================

def show_segment_drivers(
    con,
    start_date,
    end_date,
    comparison_start,
    comparison_end,
    total_change,
    dimension,
    label
):

    df = get_segment_contribution(
        con,
        start_date,
        end_date,
        comparison_start,
        comparison_end,
        dimension,
    )

    df = add_contribution_share(
        df,
        total_change
    )

    # --------------------------------------------------------
    # Positive / negative depending on event direction
    # --------------------------------------------------------

    if total_change < 0:

        df = df.sort_values(
            "gmv_change"
        )

    else:

        df = df.sort_values(
            "gmv_change",
            ascending=False
        )

    print("\n" + "=" * 90)
    print(
        f"TOP {label.upper()} DRIVERS"
    )
    print("=" * 90)

    if df.empty:

        print(
            f"No {label.lower()} contribution data."
        )

        return df

    display_df = df.head(10).copy()

    display_df["gmv_change"] = (
        display_df["gmv_change"]
        .round(2)
    )

    display_df["contribution_share"] = (
        display_df["contribution_share"]
        .mul(100)
        .round(2)
    )

    print(
        display_df[
            [
                "segment",
                "gmv_change",
                "contribution_share",
                "previous_orders",
                "current_orders",
            ]
        ].to_string(
            index=False
        )
    )

    return df


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n")
    print("=" * 90)
    print("BusinessIntelligence.ai")
    print("EVENT DRIVER INVESTIGATION")
    print("=" * 90)

    con = connect_database()

    try:

        # ----------------------------------------------------
        # Select highest-priority real business event
        # ----------------------------------------------------

        event = get_event(con)

        if event is None:

            print(
                "No high-priority business movement event found."
            )

            return

        (
            event_group,
            event_start,
            event_end,
            anomalous_days,
            direction,
            event_type,
            investigation_priority,
            event_priority_score,
        ) = event

        print(
            f"\nSelected event: {event_group}"
        )

        print(
            f"Period: "
            f"{event_start} -> {event_end}"
        )

        print(
            f"Duration: "
            f"{anomalous_days} days"
        )

        print(
            f"Direction: "
            f"{direction}"
        )

        print(
            f"Priority: "
            f"{investigation_priority}"
        )

        print(
            f"Priority score: "
            f"{event_priority_score}"
        )

        # ----------------------------------------------------
        # Calculate comparison window
        # ----------------------------------------------------

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

        print(
            f"\nComparison period: "
            f"{comparison_start} -> "
            f"{comparison_end}"
        )

        # ----------------------------------------------------
        # Period metrics
        # ----------------------------------------------------

        current = get_period_metrics(
            con,
            event_start,
            event_end,
        )

        previous = get_period_metrics(
            con,
            comparison_start,
            comparison_end,
        )

        # ----------------------------------------------------
        # Decomposition
        # ----------------------------------------------------

        show_decomposition(
            event,
            previous,
            current,
        )

        decomposition = decompose_change(
            previous,
            current,
        )

        if decomposition is None:
            return

        total_change = (
            decomposition["gmv_change"]
        )

        # ----------------------------------------------------
        # State drivers
        # ----------------------------------------------------

        show_segment_drivers(
            con,
            event_start,
            event_end,
            comparison_start,
            comparison_end,
            total_change,
            "customer_state",
            "Customer State",
        )

        # ----------------------------------------------------
        # Category drivers
        # ----------------------------------------------------

        show_segment_drivers(
            con,
            event_start,
            event_end,
            comparison_start,
            comparison_end,
            total_change,
            "category",
            "Category",
        )

        # ----------------------------------------------------
        # Seller drivers
        # ----------------------------------------------------

        show_segment_drivers(
            con,
            event_start,
            event_end,
            comparison_start,
            comparison_end,
            total_change,
            "seller",
            "Seller",
        )

        print("\n" + "=" * 90)
        print("EVENT DRIVER INVESTIGATION COMPLETE")
        print("=" * 90)

    finally:

        con.close()


if __name__ == "__main__":
    main()