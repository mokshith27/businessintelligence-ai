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
# DATABASE CONNECTION
# ============================================================

def connect_database():

    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"DuckDB database not found:\n{DB_PATH}"
        )

    return duckdb.connect(str(DB_PATH))


# ============================================================
# DECOMPOSITION LOGIC
# ============================================================

def calculate_gmv_decomposition(
    previous_gmv,
    previous_orders,
    previous_aov,
    current_gmv,
    current_orders,
    current_aov,
):
    """
    Decompose the change in GMV into:

        1. Order-volume effect
        2. AOV effect
        3. Interaction effect

    We use a symmetric decomposition so the result does not
    depend on whether we consider volume or AOV first.
    """

    if (
        previous_orders is None
        or previous_aov is None
        or current_orders is None
        or current_aov is None
    ):
        return None

    # --------------------------------------------------------
    # Changes
    # --------------------------------------------------------

    delta_orders = current_orders - previous_orders
    delta_aov = current_aov - previous_aov

    # --------------------------------------------------------
    # Volume effect
    #
    # Average AOV across the two periods × change in orders
    # --------------------------------------------------------

    average_aov = (
        previous_aov + current_aov
    ) / 2

    volume_effect = (
        delta_orders
        * average_aov
    )

    # --------------------------------------------------------
    # AOV effect
    #
    # Average number of orders × change in AOV
    # --------------------------------------------------------

    average_orders = (
        previous_orders + current_orders
    ) / 2

    aov_effect = (
        delta_aov
        * average_orders
    )

    # --------------------------------------------------------
    # Interaction / residual
    # --------------------------------------------------------

    total_change = (
        current_gmv
        - previous_gmv
    )

    residual = (
        total_change
        - volume_effect
        - aov_effect
    )

    # --------------------------------------------------------
    # Percentage contribution
    # --------------------------------------------------------

    if total_change != 0:

        volume_contribution = (
            volume_effect
            / abs(total_change)
        )

        aov_contribution = (
            aov_effect
            / abs(total_change)
        )

        residual_contribution = (
            residual
            / abs(total_change)
        )

    else:

        volume_contribution = 0.0
        aov_contribution = 0.0
        residual_contribution = 0.0

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

        "volume_contribution": volume_contribution,
        "aov_contribution": aov_contribution,
        "residual_contribution": residual_contribution,
    }


# ============================================================
# BUILD MONTHLY DECOMPOSITION TABLE
# ============================================================

def build_monthly_decomposition(con):

    print("\n[BUILD] Monthly GMV decomposition")

    con.execute(
        """
        CREATE OR REPLACE TABLE fact_monthly_gmv_decomposition AS

        WITH monthly AS (

            SELECT

                DATE_TRUNC(
                    'month',
                    date
                ) AS month,

                SUM(gmv) AS gmv,

                SUM(orders) AS orders,

                CASE
                    WHEN SUM(orders) > 0
                    THEN
                        SUM(gmv)
                        /
                        SUM(orders)
                    ELSE NULL
                END AS aov

            FROM fact_daily_kpis

            WHERE gmv IS NOT NULL

            GROUP BY 1
        ),

        with_previous AS (

            SELECT

                month,

                gmv,

                orders,

                aov,

                LAG(gmv)
                    OVER (
                        ORDER BY month
                    )
                    AS previous_gmv,

                LAG(orders)
                    OVER (
                        ORDER BY month
                    )
                    AS previous_orders,

                LAG(aov)
                    OVER (
                        ORDER BY month
                    )
                    AS previous_aov

            FROM monthly
        )

        SELECT

            month,

            previous_gmv,
            gmv AS current_gmv,

            previous_orders,
            orders AS current_orders,

            previous_aov,
            aov AS current_aov,

            gmv - previous_gmv
                AS total_gmv_change,

            orders - previous_orders
                AS order_change,

            aov - previous_aov
                AS aov_change,

            (
                (orders - previous_orders)
                *
                (
                    previous_aov + aov
                )
                / 2
            ) AS volume_effect,

            (
                (aov - previous_aov)
                *
                (
                    previous_orders + orders
                )
                / 2
            ) AS aov_effect,

            (
                (gmv - previous_gmv)
                -
                (
                    (orders - previous_orders)
                    *
                    (
                        previous_aov + aov
                    )
                    / 2
                )
                -
                (
                    (aov - previous_aov)
                    *
                    (
                        previous_orders + orders
                    )
                    / 2
                )
            ) AS residual_effect

        FROM with_previous

        WHERE
            previous_gmv IS NOT NULL
            AND previous_orders IS NOT NULL
            AND previous_aov IS NOT NULL

        ORDER BY month;
        """
    )

    print("[OK] Monthly GMV decomposition")


# ============================================================
# BUILD SEGMENT CONTRIBUTION TO GMV CHANGE
# ============================================================

def build_monthly_state_contribution(con):

    print("\n[BUILD] State-level GMV contribution")

    con.execute(
        """
        CREATE OR REPLACE TABLE fact_monthly_state_contribution AS

        WITH monthly_state AS (

            SELECT

                DATE_TRUNC(
                    'month',
                    date
                ) AS month,

                customer_state,

                SUM(gmv) AS gmv

            FROM fact_daily_state_kpis

            WHERE
                gmv IS NOT NULL

                AND customer_state IS NOT NULL

            GROUP BY
                1,
                2
        ),

        with_previous AS (

            SELECT

                month,

                customer_state,

                gmv,

                LAG(gmv)
                    OVER (
                        PARTITION BY customer_state
                        ORDER BY month
                    )
                    AS previous_gmv

            FROM monthly_state
        )

        SELECT

            month,

            customer_state,

            previous_gmv,

            gmv AS current_gmv,

            current_gmv
            -
            previous_gmv
            AS gmv_change

        FROM with_previous

        WHERE previous_gmv IS NOT NULL

        ORDER BY
            month,
            gmv_change ASC;
        """
    )

    print("[OK] State-level GMV contribution")


# ============================================================
# BUILD MONTHLY CATEGORY CONTRIBUTION
# ============================================================

def build_monthly_category_contribution(con):

    print("\n[BUILD] Category-level GMV contribution")

    con.execute(
        """
        CREATE OR REPLACE TABLE fact_monthly_category_contribution AS

        WITH monthly_category AS (

            SELECT

                DATE_TRUNC(
                    'month',
                    date
                ) AS month,

                category_name,

                SUM(gmv) AS gmv

            FROM fact_daily_category_kpis

            WHERE
                gmv IS NOT NULL

                AND category_name IS NOT NULL

            GROUP BY
                1,
                2
        ),

        with_previous AS (

            SELECT

                month,

                category_name,

                gmv,

                LAG(gmv)
                    OVER (
                        PARTITION BY category_name
                        ORDER BY month
                    )
                    AS previous_gmv

            FROM monthly_category
        )

        SELECT

            month,

            category_name,

            previous_gmv,

            gmv AS current_gmv,

            current_gmv
            -
            previous_gmv
            AS gmv_change

        FROM with_previous

        WHERE
            previous_gmv IS NOT NULL

        ORDER BY
            month,
            gmv_change ASC;
        """
    )

    print("[OK] Category-level GMV contribution")


# ============================================================
# SHOW RECENT DECOMPOSITION
# ============================================================

def show_recent_decomposition(con):

    print("\n" + "=" * 80)
    print("RECENT MONTHLY GMV DECOMPOSITION")
    print("=" * 80)

    result = con.execute(
        """
        SELECT

            month,

            ROUND(
                previous_gmv,
                2
            ) AS previous_gmv,

            ROUND(
                current_gmv,
                2
            ) AS current_gmv,

            ROUND(
                total_gmv_change,
                2
            ) AS gmv_change,

            ROUND(
                volume_effect,
                2
            ) AS volume_effect,

            ROUND(
                aov_effect,
                2
            ) AS aov_effect,

            ROUND(
                residual_effect,
                2
            ) AS residual_effect

        FROM fact_monthly_gmv_decomposition

        ORDER BY month DESC

        LIMIT 10;
        """
    )

    print(
        result.df().to_string(
            index=False
        )
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n")
    print("=" * 80)
    print("BusinessIntelligence.ai")
    print("GMV DRIVER DECOMPOSITION")
    print("=" * 80)

    con = connect_database()

    try:

        build_monthly_decomposition(con)

        build_monthly_state_contribution(con)

        build_monthly_category_contribution(con)

        show_recent_decomposition(con)

        print("\n" + "=" * 80)
        print("GMV DECOMPOSITION COMPLETE")
        print("=" * 80)

    finally:
        con.close()


if __name__ == "__main__":
    main()