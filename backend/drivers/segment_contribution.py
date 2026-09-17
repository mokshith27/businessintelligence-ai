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
# GET MONTHLY GMV MOVEMENT
# ============================================================

def get_months_with_movement(con):

    return con.execute(
        """
        SELECT
            month,
            previous_gmv,
            current_gmv,
            total_gmv_change
        FROM fact_monthly_gmv_decomposition
        ORDER BY month DESC;
        """
    ).fetchall()


# ============================================================
# STATE CONTRIBUTION
# ============================================================

def calculate_state_contribution(
    con,
    month
):

    result = con.execute(
        """
        SELECT

            customer_state,

            previous_gmv,

            current_gmv,

            gmv_change

        FROM fact_monthly_state_contribution

        WHERE month = ?

        ORDER BY gmv_change ASC;
        """,
        [month],
    )

    return result.df()


# ============================================================
# CATEGORY CONTRIBUTION
# ============================================================

def calculate_category_contribution(
    con,
    month
):

    result = con.execute(
        """
        SELECT

            category_name,

            previous_gmv,

            current_gmv,

            gmv_change

        FROM fact_monthly_category_contribution

        WHERE month = ?

        ORDER BY gmv_change ASC;
        """,
        [month],
    )

    return result.df()


# ============================================================
# SELLER CONTRIBUTION
# ============================================================

def calculate_seller_contribution(
    con,
    month
):

    result = con.execute(
        """
        WITH monthly_seller AS (

            SELECT

                DATE_TRUNC(
                    'month',
                    date
                ) AS month,

                seller_id,

                SUM(gmv) AS gmv

            FROM fact_daily_seller_kpis

            WHERE gmv IS NOT NULL

            GROUP BY
                1,
                2
        ),

        with_previous AS (

            SELECT

                month,

                seller_id,

                gmv,

                LAG(gmv)
                    OVER (
                        PARTITION BY seller_id
                        ORDER BY month
                    )
                    AS previous_gmv

            FROM monthly_seller
        )

        SELECT

            seller_id,

            previous_gmv,

            gmv AS current_gmv,

            current_gmv
            -
            previous_gmv
            AS gmv_change

        FROM with_previous

        WHERE
            month = ?
            AND previous_gmv IS NOT NULL

        ORDER BY
            gmv_change ASC;

        """,
        [month],
    )

    return result.df()


# ============================================================
# CALCULATE CONTRIBUTION SHARE
# ============================================================

def add_contribution_share(
    df,
    total_change
):

    if df.empty:
        return df

    if total_change == 0:
        df["contribution_share"] = 0.0
        return df

    df["contribution_share"] = (
        df["gmv_change"]
        / abs(total_change)
    )

    return df


# ============================================================
# SHOW DRIVER RANKING
# ============================================================

def show_driver_ranking(
    con,
    month
):

    # --------------------------------------------------------
    # Get total GMV movement
    # --------------------------------------------------------

    movement = con.execute(
        """
        SELECT
            total_gmv_change
        FROM fact_monthly_gmv_decomposition
        WHERE month = ?;
        """,
        [month],
    ).fetchone()

    if movement is None:
        print(
            f"No decomposition found for {month}"
        )
        return

    total_change = movement[0]

    print("\n" + "=" * 80)
    print(
        f"DRIVER RANKING FOR {month}"
    )
    print("=" * 80)

    print(
        f"Total GMV change: "
        f"{total_change:,.2f}"
    )

    # --------------------------------------------------------
    # State
    # --------------------------------------------------------

    state_df = calculate_state_contribution(
        con,
        month
    )

    state_df = add_contribution_share(
        state_df,
        total_change
    )

    # --------------------------------------------------------
    # Category
    # --------------------------------------------------------

    category_df = calculate_category_contribution(
        con,
        month
    )

    category_df = add_contribution_share(
        category_df,
        total_change
    )

    # --------------------------------------------------------
    # Seller
    # --------------------------------------------------------

    seller_df = calculate_seller_contribution(
        con,
        month
    )

    seller_df = add_contribution_share(
        seller_df,
        total_change
    )

    # --------------------------------------------------------
    # Print top negative drivers
    # --------------------------------------------------------

    print("\nTOP STATES CONTRIBUTING TO DECLINE")

    if not state_df.empty:

        declining = state_df[
            state_df["gmv_change"] < 0
        ].head(10)

        print(
            declining[
                [
                    "customer_state",
                    "gmv_change",
                    "contribution_share",
                ]
            ].to_string(index=False)
        )

    print("\nTOP CATEGORIES CONTRIBUTING TO DECLINE")

    if not category_df.empty:

        declining = category_df[
            category_df["gmv_change"] < 0
        ].head(10)

        print(
            declining[
                [
                    "category_name",
                    "gmv_change",
                    "contribution_share",
                ]
            ].to_string(index=False)
        )

    print("\nTOP SELLERS CONTRIBUTING TO DECLINE")

    if not seller_df.empty:

        declining = seller_df[
            seller_df["gmv_change"] < 0
        ].head(10)

        print(
            declining[
                [
                    "seller_id",
                    "gmv_change",
                    "contribution_share",
                ]
            ].to_string(index=False)
        )


# ============================================================
# BUILD DRIVER TABLE
# ============================================================

def build_driver_table(con):

    print("\n[BUILD] Candidate driver table")

    con.execute(
        """
        CREATE OR REPLACE TABLE fact_gmv_driver_candidates AS

        WITH state_drivers AS (

            SELECT

                month,

                'customer_state' AS dimension,

                customer_state AS driver,

                gmv_change

            FROM fact_monthly_state_contribution

            WHERE gmv_change IS NOT NULL
        ),

        category_drivers AS (

            SELECT

                month,

                'category' AS dimension,

                category_name AS driver,

                gmv_change

            FROM fact_monthly_category_contribution

            WHERE gmv_change IS NOT NULL
        ),

        seller_drivers AS (

            SELECT

                DATE_TRUNC(
                    'month',
                    date
                ) AS month,

                'seller' AS dimension,

                seller_id AS driver,

                SUM(gmv) -

                LAG(
                    SUM(gmv)
                ) OVER (
                    PARTITION BY seller_id
                    ORDER BY
                        DATE_TRUNC(
                            'month',
                            date
                        )
                ) AS gmv_change

            FROM fact_daily_seller_kpis

            WHERE gmv IS NOT NULL

            GROUP BY
                1,
                3
        )

        SELECT *
        FROM state_drivers

        UNION ALL

        SELECT *
        FROM category_drivers

        UNION ALL

        SELECT *
        FROM seller_drivers

        ORDER BY
            month,
            gmv_change ASC;
        """
    )

    print("[OK] Candidate driver table")


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n")
    print("=" * 80)
    print("BusinessIntelligence.ai")
    print("DRIVER CONTRIBUTION ENGINE")
    print("=" * 80)

    con = connect_database()

    try:

        build_driver_table(con)

        months = get_months_with_movement(con)

        if not months:
            print(
                "No monthly movements available."
            )
            return

        # ----------------------------------------------------
        # Analyze the most recent month
        # ----------------------------------------------------

        latest_month = months[0][0]

        show_driver_ranking(
            con,
            latest_month
        )

        print("\n" + "=" * 80)
        print("DRIVER CONTRIBUTION ENGINE COMPLETE")
        print("=" * 80)

    finally:
        con.close()


if __name__ == "__main__":
    main()