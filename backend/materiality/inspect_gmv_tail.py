from pathlib import Path
import duckdb


PROJECT_ROOT = Path(__file__).resolve().parent.parent

DB_PATH = (
    PROJECT_ROOT
    / "data"
    / "warehouse"
    / "businessintelligence.duckdb"
)


def main():

    con = duckdb.connect(
        str(DB_PATH),
        read_only=True
    )

    try:

        print("\n" + "=" * 90)
        print("GMV DATA TAIL DIAGNOSTIC")
        print("=" * 90)

        df = con.execute(
            """
            WITH item_daily AS (

                SELECT

                    CAST(
                        order_purchase_timestamp AS DATE
                    ) AS date,

                    COUNT(*) AS item_rows,

                    COUNT(
                        DISTINCT order_id
                    ) AS orders,

                    SUM(price) AS gmv

                FROM fact_order_items_enriched

                WHERE
                    order_purchase_timestamp IS NOT NULL

                GROUP BY 1
            ),

            order_daily AS (

                SELECT

                    CAST(
                        order_purchase_timestamp AS DATE
                    ) AS date,

                    COUNT(*) AS order_records

                FROM fact_orders_enriched

                WHERE
                    order_purchase_timestamp IS NOT NULL

                GROUP BY 1
            )

            SELECT

                COALESCE(
                    i.date,
                    o.date
                ) AS date,

                COALESCE(
                    i.item_rows,
                    0
                ) AS item_rows,

                COALESCE(
                    i.orders,
                    0
                ) AS item_orders,

                ROUND(
                    COALESCE(
                        i.gmv,
                        0
                    ),
                    2
                ) AS gmv,

                COALESCE(
                    o.order_records,
                    0
                ) AS order_records

            FROM item_daily i

            FULL OUTER JOIN order_daily o
                ON i.date = o.date

            WHERE
                COALESCE(
                    i.date,
                    o.date
                ) >= (
                    SELECT
                        MAX(date)
                    FROM item_daily
                ) - INTERVAL '20 days'

            ORDER BY date DESC;
            """
        ).fetchdf()

        print(
            df.to_string(
                index=False
            )
        )

        print("\n" + "=" * 90)
        print("MAXIMUM DATES")
        print("=" * 90)

        dates = con.execute(
            """
            SELECT

                (
                    SELECT MAX(
                        CAST(
                            order_purchase_timestamp
                            AS DATE
                        )
                    )
                    FROM fact_order_items_enriched
                ) AS max_item_date,

                (
                    SELECT MAX(
                        CAST(
                            order_purchase_timestamp
                            AS DATE
                        )
                    )
                    FROM fact_orders_enriched
                ) AS max_order_date;
            """
        ).fetchdf()

        print(
            dates.to_string(
                index=False
            )
        )

    finally:

        con.close()


if __name__ == "__main__":
    main()