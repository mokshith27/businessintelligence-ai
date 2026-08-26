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
            f"DuckDB database not found:\n{DB_PATH}\n\n"
            "Run the ingestion and analytical-table scripts first."
        )

    return duckdb.connect(str(DB_PATH))


# ============================================================
# SQL EXECUTOR
# ============================================================

def execute_sql(con, description, sql):

    print(f"\n[BUILD] {description}")

    con.execute(sql)

    print(f"[OK] {description}")


# ============================================================
# BUILD DAILY KPI TABLE
# ============================================================

def build_daily_kpis(con):

    execute_sql(
        con,
        "Building fact_daily_kpis",
        """
        CREATE OR REPLACE TABLE fact_daily_kpis AS

        WITH
        -- ====================================================
        -- 1. DATE SPINE
        -- ====================================================

        date_range AS (
            SELECT
                MIN(
                    CAST(order_purchase_timestamp AS DATE)
                ) AS min_date,

                MAX(
                    CAST(order_purchase_timestamp AS DATE)
                ) AS max_date

            FROM fact_orders_enriched
        ),

        dates AS (
            SELECT
                date_value AS date

            FROM date_range,

            generate_series(
                min_date,
                max_date,
                INTERVAL 1 DAY
            ) AS t(date_value)
        ),

        -- ====================================================
        -- 2. GMV + ORDERS
        --
        -- GMV is calculated at order-item grain.
        -- Orders are calculated at order grain.
        -- They are intentionally calculated separately.
        -- ====================================================

        order_kpis AS (
            SELECT

                CAST(
                    order_purchase_timestamp AS DATE
                ) AS date,

                SUM(price) AS gmv,

                COUNT(
                    DISTINCT order_id
                ) AS orders

            FROM fact_order_items_enriched

            WHERE order_purchase_timestamp IS NOT NULL

            GROUP BY 1
        ),

        -- ====================================================
        -- 3. AOV
        -- ====================================================

        order_kpis_with_aov AS (
            SELECT

                date,

                gmv,

                orders,

                CASE
                    WHEN orders > 0
                    THEN gmv / orders
                    ELSE NULL
                END AS aov

            FROM order_kpis
        ),

        -- ====================================================
        -- 4. LATE DELIVERY RATE
        --
        -- Only delivered orders with both actual and estimated
        -- delivery dates can participate.
        -- ====================================================

        delivery_kpis AS (
            SELECT

                CAST(
                    order_purchase_timestamp AS DATE
                ) AS date,

                COUNT(*) AS delivered_orders,

                COUNT_IF(
                    delivery_delay_days > 0
                ) AS late_orders,

                CASE
                    WHEN COUNT(*) > 0
                    THEN
                        COUNT_IF(
                            delivery_delay_days > 0
                        )::DOUBLE
                        / COUNT(*)
                    ELSE NULL
                END AS late_delivery_rate

            FROM fact_orders_enriched

            WHERE
                order_status = 'delivered'

                AND order_delivered_customer_date IS NOT NULL

                AND order_estimated_delivery_date IS NOT NULL

            GROUP BY 1
        ),

        -- ====================================================
        -- 5. REVIEW SCORE
        --
        -- Review score uses review creation date.
        -- Missing reviews do NOT become zero.
        -- ====================================================

        review_kpis AS (
            SELECT

                CAST(
                    review_creation_date AS DATE
                ) AS date,

                COUNT(*) AS reviews,

                AVG(
                    review_score
                ) AS review_score

            FROM fact_reviews

            WHERE
                review_creation_date IS NOT NULL

                AND review_score IS NOT NULL

            GROUP BY 1
        )

        -- ====================================================
        -- 6. MERGE ALL KPIs ONTO DATE SPINE
        -- ====================================================

        SELECT

            d.date,

            ok.gmv,

            ok.orders,

            ok.aov,

            dk.late_delivery_rate,

            rk.review_score,

            -- Supporting counts are kept because they will
            -- help the confidence/quality layer later.

            dk.delivered_orders,

            dk.late_orders,

            rk.reviews

        FROM dates d

        LEFT JOIN order_kpis_with_aov ok
            ON d.date = ok.date

        LEFT JOIN delivery_kpis dk
            ON d.date = dk.date

        LEFT JOIN review_kpis rk
            ON d.date = rk.date

        ORDER BY d.date;
        """
    )


# ============================================================
# VALIDATE DAILY KPI TABLE
# ============================================================

def validate_daily_kpis(con):

    print("\n" + "=" * 80)
    print("DAILY KPI VALIDATION")
    print("=" * 80)

    # --------------------------------------------------------
    # Row count
    # --------------------------------------------------------

    row_count = con.execute(
        """
        SELECT COUNT(*)
        FROM fact_daily_kpis;
        """
    ).fetchone()[0]

    print(f"\nNumber of daily rows: {row_count:,}")

    # --------------------------------------------------------
    # Date range
    # --------------------------------------------------------

    date_range = con.execute(
        """
        SELECT
            MIN(date),
            MAX(date)
        FROM fact_daily_kpis;
        """
    ).fetchone()

    print(f"Minimum date: {date_range[0]}")
    print(f"Maximum date: {date_range[1]}")

    # --------------------------------------------------------
    # Aggregate KPIs
    # --------------------------------------------------------

    totals = con.execute(
        """
        SELECT

            SUM(gmv) AS total_gmv,

            SUM(orders) AS total_orders,

            SUM(delivered_orders) AS delivered_orders,

            SUM(late_orders) AS late_orders

        FROM fact_daily_kpis;
        """
    ).fetchone()

    print("\nAggregate values:")
    print(f"Total GMV              : {totals[0]}")
    print(f"Total Orders           : {totals[1]}")
    print(f"Delivered Orders       : {totals[2]}")
    print(f"Late Orders            : {totals[3]}")

    # --------------------------------------------------------
    # Recalculate overall AOV independently
    # --------------------------------------------------------

    overall_aov = con.execute(
        """
        SELECT
            SUM(price)
            /
            COUNT(DISTINCT order_id)

        FROM fact_order_items_enriched;
        """
    ).fetchone()[0]

    print(f"Overall AOV            : {overall_aov}")

    # --------------------------------------------------------
    # Overall review score
    # --------------------------------------------------------

    overall_review = con.execute(
        """
        SELECT
            AVG(review_score)

        FROM fact_reviews

        WHERE review_score IS NOT NULL;
        """
    ).fetchone()[0]

    print(f"Overall Review Score   : {overall_review}")

    # --------------------------------------------------------
    # Null summary
    # --------------------------------------------------------

    print("\nKPI missing-value counts:")

    null_counts = con.execute(
        """
        SELECT
            COUNT(*) FILTER (
                WHERE gmv IS NULL
            ) AS gmv_nulls,

            COUNT(*) FILTER (
                WHERE orders IS NULL
            ) AS orders_nulls,

            COUNT(*) FILTER (
                WHERE aov IS NULL
            ) AS aov_nulls,

            COUNT(*) FILTER (
                WHERE late_delivery_rate IS NULL
            ) AS delivery_nulls,

            COUNT(*) FILTER (
                WHERE review_score IS NULL
            ) AS review_nulls

        FROM fact_daily_kpis;
        """
    ).fetchone()

    print(f"GMV null days             : {null_counts[0]}")
    print(f"Orders null days          : {null_counts[1]}")
    print(f"AOV null days             : {null_counts[2]}")
    print(f"Delivery-rate null days   : {null_counts[3]}")
    print(f"Review-score null days    : {null_counts[4]}")


# ============================================================
# SHOW SAMPLE DATA
# ============================================================

def show_sample_data(con):

    print("\n" + "=" * 80)
    print("SAMPLE DAILY KPI DATA")
    print("=" * 80)

    result = con.execute(
        """
        SELECT *
        FROM fact_daily_kpis
        ORDER BY date
        LIMIT 15;
        """
    )

    print(result.df().to_string(index=False))


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n")
    print("=" * 80)
    print("BusinessIntelligence.ai")
    print("BUILD DAILY KPI MART")
    print("=" * 80)

    con = connect_database()

    try:

        build_daily_kpis(con)

        validate_daily_kpis(con)

        show_sample_data(con)

        print("\n" + "=" * 80)
        print("DAILY KPI BUILD COMPLETE")
        print("=" * 80)

    finally:

        con.close()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()