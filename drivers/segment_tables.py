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
# BUILD CUSTOMER-STATE DAILY KPIs
# ============================================================

def build_state_kpis(con):

    print("\n[BUILD] Customer-state daily KPIs")

    con.execute(
        """
        CREATE OR REPLACE TABLE fact_daily_state_kpis AS

        SELECT

            CAST(
                order_purchase_timestamp AS DATE
            ) AS date,

            customer_state,

            SUM(price) AS gmv,

            COUNT(
                DISTINCT order_id
            ) AS orders,

            CASE
                WHEN COUNT(DISTINCT order_id) > 0
                THEN
                    SUM(price)
                    /
                    COUNT(DISTINCT order_id)
                ELSE NULL
            END AS aov

        FROM fact_order_items_enriched

        WHERE
            order_purchase_timestamp IS NOT NULL
            AND customer_state IS NOT NULL

        GROUP BY
            1,
            2

        ORDER BY
            1,
            2;
        """
    )

    print("[OK] Customer-state daily KPIs")


# ============================================================
# BUILD CATEGORY DAILY KPIs
# ============================================================

def build_category_kpis(con):

    print("\n[BUILD] Category daily KPIs")

    con.execute(
        """
        CREATE OR REPLACE TABLE fact_daily_category_kpis AS

        SELECT

            CAST(
                order_purchase_timestamp AS DATE
            ) AS date,

            category_name,

            SUM(price) AS gmv,

            COUNT(
                DISTINCT order_id
            ) AS orders,

            CASE
                WHEN COUNT(DISTINCT order_id) > 0
                THEN
                    SUM(price)
                    /
                    COUNT(DISTINCT order_id)
                ELSE NULL
            END AS aov

        FROM fact_order_items_enriched

        WHERE
            order_purchase_timestamp IS NOT NULL
            AND category_name IS NOT NULL

        GROUP BY
            1,
            2

        ORDER BY
            1,
            2;
        """
    )

    print("[OK] Category daily KPIs")


# ============================================================
# BUILD SELLER DAILY KPIs
# ============================================================

def build_seller_kpis(con):

    print("\n[BUILD] Seller daily KPIs")

    con.execute(
        """
        CREATE OR REPLACE TABLE fact_daily_seller_kpis AS

        SELECT

            CAST(
                order_purchase_timestamp AS DATE
            ) AS date,

            seller_id,

            seller_state,

            SUM(price) AS gmv,

            COUNT(
                DISTINCT order_id
            ) AS orders,

            CASE
                WHEN COUNT(DISTINCT order_id) > 0
                THEN
                    SUM(price)
                    /
                    COUNT(DISTINCT order_id)
                ELSE NULL
            END AS aov

        FROM fact_order_items_enriched

        WHERE
            order_purchase_timestamp IS NOT NULL
            AND seller_id IS NOT NULL

        GROUP BY
            1,
            2,
            3

        ORDER BY
            1,
            2;
        """
    )

    print("[OK] Seller daily KPIs")


# ============================================================
# BUILD DELIVERY KPIs BY SELLER
# ============================================================

def build_seller_delivery_kpis(con):

    print("\n[BUILD] Seller delivery KPIs")

    con.execute(
        """
        CREATE OR REPLACE TABLE fact_daily_seller_delivery_kpis AS

        SELECT

            CAST(
                order_purchase_timestamp AS DATE
            ) AS date,

            seller_id,

            seller_state,

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
                    /
                    COUNT(*)
                ELSE NULL
            END AS late_delivery_rate

        FROM fact_orders_enriched o

        INNER JOIN (

            SELECT DISTINCT
                order_id,
                seller_id,
                seller_state

            FROM fact_order_items_enriched

        ) seller_orders

            ON o.order_id =
               seller_orders.order_id

        WHERE
            o.order_status = 'delivered'

            AND o.order_delivered_customer_date
                IS NOT NULL

            AND o.order_estimated_delivery_date
                IS NOT NULL

            AND seller_orders.seller_id
                IS NOT NULL

        GROUP BY
            1,
            2,
            3

        ORDER BY
            1,
            2;
        """
    )

    print("[OK] Seller delivery KPIs")


# ============================================================
# VALIDATION
# ============================================================

def validate_tables(con):

    print("\n" + "=" * 80)
    print("SEGMENT TABLE SUMMARY")
    print("=" * 80)

    tables = [
        "fact_daily_state_kpis",
        "fact_daily_category_kpis",
        "fact_daily_seller_kpis",
        "fact_daily_seller_delivery_kpis",
    ]

    for table in tables:

        count = con.execute(
            f'SELECT COUNT(*) FROM "{table}"'
        ).fetchone()[0]

        print(
            f"{table:40}"
            f"{count:>12,} rows"
        )


# ============================================================
# SHOW TOP SEGMENTS
# ============================================================

def show_top_segments(con):

    print("\n" + "=" * 80)
    print("TOP CUSTOMER STATES BY GMV")
    print("=" * 80)

    result = con.execute(
        """
        SELECT

            customer_state,

            ROUND(
                SUM(gmv),
                2
            ) AS total_gmv,

            SUM(orders) AS total_orders,

            ROUND(
                SUM(gmv)
                /
                NULLIF(
                    SUM(orders),
                    0
                ),
                2
            ) AS overall_aov

        FROM fact_daily_state_kpis

        GROUP BY
            customer_state

        ORDER BY
            total_gmv DESC

        LIMIT 10;
        """
    )

    print(
        result.df().to_string(
            index=False
        )
    )

    print("\n" + "=" * 80)
    print("TOP CATEGORIES BY GMV")
    print("=" * 80)

    result = con.execute(
        """
        SELECT

            category_name,

            ROUND(
                SUM(gmv),
                2
            ) AS total_gmv,

            SUM(orders) AS total_orders

        FROM fact_daily_category_kpis

        GROUP BY
            category_name

        ORDER BY
            total_gmv DESC

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
    print("BUILD SEGMENT KPI TABLES")
    print("=" * 80)

    con = connect_database()

    try:

        build_state_kpis(con)

        build_category_kpis(con)

        build_seller_kpis(con)

        build_seller_delivery_kpis(con)

        validate_tables(con)

        show_top_segments(con)

        print("\n" + "=" * 80)
        print("SEGMENT KPI BUILD COMPLETE")
        print("=" * 80)

    finally:
        con.close()


if __name__ == "__main__":
    main()