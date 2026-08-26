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
            f"DuckDB database not found:\n{DB_PATH}\n"
            "Run the ingestion script first."
        )

    return duckdb.connect(str(DB_PATH))


# ============================================================
# EXECUTE SQL
# ============================================================

def execute_sql(con, description, sql):
    print(f"\n[BUILD] {description}")

    con.execute(sql)

    print(f"[OK] {description}")


# ============================================================
# MAIN TRANSFORMATION
# ============================================================

def main():

    print("\n")
    print("=" * 80)
    print("BusinessIntelligence.ai")
    print("BUILD ANALYTICAL TABLES")
    print("=" * 80)

    con = connect_database()

    try:

        # ====================================================
        # 1. CUSTOMER DIMENSION
        # ====================================================

        execute_sql(
            con,
            "Building dim_customer",
            """
            CREATE OR REPLACE TABLE dim_customer AS
            SELECT
                customer_id,
                customer_unique_id,
                customer_zip_code_prefix,
                LOWER(TRIM(customer_city)) AS customer_city,
                UPPER(TRIM(customer_state)) AS customer_state
            FROM olist_customers_dataset;
            """
        )

        # ====================================================
        # 2. PRODUCT DIMENSION
        # ====================================================

        execute_sql(
            con,
            "Building dim_product",
            """
            CREATE OR REPLACE TABLE dim_product AS
            SELECT
                p.product_id,
                p.product_category_name,
                t.product_category_name_english,
                COALESCE(
                    t.product_category_name_english,
                    p.product_category_name,
                    'unknown'
                ) AS category_name,
                p.product_name_lenght,
                p.product_description_lenght,
                p.product_photos_qty,
                p.product_weight_g,
                p.product_length_cm,
                p.product_height_cm,
                p.product_width_cm
            FROM olist_products_dataset p
            LEFT JOIN product_category_name_translation t
                ON p.product_category_name =
                   t.product_category_name;
            """
        )

        # ====================================================
        # 3. SELLER DIMENSION
        # ====================================================

        execute_sql(
            con,
            "Building dim_seller",
            """
            CREATE OR REPLACE TABLE dim_seller AS
            SELECT
                seller_id,
                seller_zip_code_prefix,
                LOWER(TRIM(seller_city)) AS seller_city,
                UPPER(TRIM(seller_state)) AS seller_state
            FROM olist_sellers_dataset;
            """
        )

        # ====================================================
        # 4. ORDERS FACT TABLE
        # ====================================================

        execute_sql(
            con,
            "Building fact_orders",
            """
            CREATE OR REPLACE TABLE fact_orders AS
            SELECT
                order_id,
                customer_id,
                order_status,

                TRY_CAST(
                    order_purchase_timestamp
                    AS TIMESTAMP
                ) AS order_purchase_timestamp,

                TRY_CAST(
                    order_approved_at
                    AS TIMESTAMP
                ) AS order_approved_at,

                TRY_CAST(
                    order_delivered_carrier_date
                    AS TIMESTAMP
                ) AS order_delivered_carrier_date,

                TRY_CAST(
                    order_delivered_customer_date
                    AS TIMESTAMP
                ) AS order_delivered_customer_date,

                TRY_CAST(
                    order_estimated_delivery_date
                    AS TIMESTAMP
                ) AS order_estimated_delivery_date

            FROM olist_orders_dataset;
            """
        )

        # ====================================================
        # 5. ORDER ITEMS FACT TABLE
        # ====================================================

        execute_sql(
            con,
            "Building fact_order_items",
            """
            CREATE OR REPLACE TABLE fact_order_items AS
            SELECT
                order_id,
                order_item_id,
                product_id,
                seller_id,

                TRY_CAST(
                    shipping_limit_date
                    AS TIMESTAMP
                ) AS shipping_limit_date,

                price,
                freight_value

            FROM olist_order_items_dataset;
            """
        )

        # ====================================================
        # 6. PAYMENT FACT TABLE
        # ====================================================

        execute_sql(
            con,
            "Building fact_payments",
            """
            CREATE OR REPLACE TABLE fact_payments AS
            SELECT
                order_id,
                payment_sequential,
                payment_type,
                payment_installments,
                payment_value
            FROM olist_order_payments_dataset;
            """
        )

        # ====================================================
        # 7. REVIEW FACT TABLE
        # ====================================================

        execute_sql(
            con,
            "Building fact_reviews",
            """
            CREATE OR REPLACE TABLE fact_reviews AS
            SELECT
                review_id,
                order_id,
                review_score,

                NULLIF(
                    TRIM(review_comment_title),
                    ''
                ) AS review_comment_title,

                NULLIF(
                    TRIM(review_comment_message),
                    ''
                ) AS review_comment_message,

                TRY_CAST(
                    review_creation_date
                    AS TIMESTAMP
                ) AS review_creation_date,

                TRY_CAST(
                    review_answer_timestamp
                    AS TIMESTAMP
                ) AS review_answer_timestamp

            FROM olist_order_reviews_dataset;
            """
        )

        # ====================================================
        # 8. MQL FACT TABLE
        # ====================================================

        execute_sql(
            con,
            "Building fact_mql",
            """
            CREATE OR REPLACE TABLE fact_mql AS
            SELECT
                mql_id,

                TRY_CAST(
                    first_contact_date
                    AS TIMESTAMP
                ) AS first_contact_date,

                landing_page_id,
                origin

            FROM olist_marketing_qualified_leads_dataset;
            """
        )

        # ====================================================
        # 9. CLOSED DEAL FACT TABLE
        # ====================================================

        execute_sql(
            con,
            "Building fact_closed_deals",
            """
            CREATE OR REPLACE TABLE fact_closed_deals AS
            SELECT
                mql_id,
                seller_id,
                sdr_id,
                sr_id,

                TRY_CAST(
                    won_date
                    AS TIMESTAMP
                ) AS won_date,

                business_segment,
                lead_type,
                lead_behaviour_profile,
                has_company,
                has_gtin,
                average_stock,
                business_type,
                declared_product_catalog_size,
                declared_monthly_revenue

            FROM olist_closed_deals_dataset;
            """
        )

        # ====================================================
        # 10. ENRICHED ORDER ITEMS
        # ====================================================

        execute_sql(
            con,
            "Building fact_order_items_enriched",
            """
            CREATE OR REPLACE TABLE fact_order_items_enriched AS

            SELECT
                i.order_id,
                i.order_item_id,

                i.product_id,
                i.seller_id,

                i.shipping_limit_date,

                i.price,
                i.freight_value,

                o.customer_id,
                o.order_status,

                o.order_purchase_timestamp,
                o.order_approved_at,
                o.order_delivered_carrier_date,
                o.order_delivered_customer_date,
                o.order_estimated_delivery_date,

                c.customer_city,
                c.customer_state,

                s.seller_city,
                s.seller_state,

                p.category_name

            FROM fact_order_items i

            INNER JOIN fact_orders o
                ON i.order_id = o.order_id

            LEFT JOIN dim_customer c
                ON o.customer_id = c.customer_id

            LEFT JOIN dim_seller s
                ON i.seller_id = s.seller_id

            LEFT JOIN dim_product p
                ON i.product_id = p.product_id;
            """
        )

        # ====================================================
        # 11. ENRICHED ORDERS
        # ====================================================

        execute_sql(
            con,
            "Building fact_orders_enriched",
            """
            CREATE OR REPLACE TABLE fact_orders_enriched AS

            SELECT
                o.*,

                c.customer_unique_id,
                c.customer_city,
                c.customer_state,

                CASE
                    WHEN
                        o.order_status = 'delivered'
                        AND o.order_delivered_customer_date IS NOT NULL
                        AND o.order_estimated_delivery_date IS NOT NULL
                    THEN
                        DATE_DIFF(
                            'day',
                            CAST(
                                o.order_estimated_delivery_date
                                AS DATE
                            ),
                            CAST(
                                o.order_delivered_customer_date
                                AS DATE
                            )
                        )
                    ELSE NULL
                END AS delivery_delay_days

            FROM fact_orders o

            LEFT JOIN dim_customer c
                ON o.customer_id = c.customer_id;
            """
        )

        # ====================================================
        # 12. BASIC VALIDATION
        # ====================================================

        print("\n" + "=" * 80)
        print("ANALYTICAL TABLE SUMMARY")
        print("=" * 80)

        tables = con.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'main'
              AND table_name IN (
                  'dim_customer',
                  'dim_product',
                  'dim_seller',
                  'fact_orders',
                  'fact_order_items',
                  'fact_payments',
                  'fact_reviews',
                  'fact_mql',
                  'fact_closed_deals',
                  'fact_order_items_enriched',
                  'fact_orders_enriched'
              )
            ORDER BY table_name;
            """
        ).fetchall()

        for (table,) in tables:

            count = con.execute(
                f'SELECT COUNT(*) FROM "{table}"'
            ).fetchone()[0]

            print(
                f"{table:35} "
                f"{count:>12,} rows"
            )

        print("\n" + "=" * 80)
        print("ANALYTICAL TABLE BUILD COMPLETE")
        print("=" * 80)

    finally:
        con.close()


if __name__ == "__main__":
    main()