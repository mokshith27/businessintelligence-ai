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
# GOVERNED THRESHOLDS
# ============================================================

GMV_RELATIVE_THRESHOLD = 0.05
GMV_ABSOLUTE_THRESHOLD = 100000.0

Z_SCORE_THRESHOLD = 2.5

MIN_HISTORY_POINTS = 4
MIN_CURRENT_ITEM_ROWS = 10
MIN_CURRENT_ITEM_ORDERS = 10

HISTORY_WEEKS = 8


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
# BUILD SEASONAL MATERIALITY TABLE
# ============================================================

def build_gmv_materiality(con):

    print("\n[BUILD] GMV seasonal materiality analysis")

    con.execute(
        f"""
        CREATE OR REPLACE TABLE fact_gmv_materiality AS

        WITH observations AS (

            SELECT

                CAST(
                    order_purchase_timestamp AS DATE
                ) AS date,

                SUM(price) AS gmv,

                COUNT(*) AS item_rows,

                COUNT(
                    DISTINCT order_id
                ) AS item_orders,

                EXTRACT(
                    DOW FROM CAST(
                        order_purchase_timestamp AS DATE
                    )
                ) AS day_of_week

            FROM fact_order_items_enriched

            WHERE
                order_purchase_timestamp IS NOT NULL

            GROUP BY 1
        ),

        historical AS (

            SELECT

                current_obs.date,

                current_obs.gmv,

                current_obs.item_rows,

                current_obs.item_orders,

                current_obs.day_of_week,

                COUNT(
                    previous_obs.gmv
                ) AS history_points,

                MEDIAN(
                    previous_obs.gmv
                ) AS seasonal_median,

                MAD(
                    previous_obs.gmv
                ) AS seasonal_mad

            FROM observations current_obs

            LEFT JOIN observations previous_obs

                ON previous_obs.day_of_week =
                current_obs.day_of_week

                AND previous_obs.date <
                    current_obs.date

                AND previous_obs.date >=
                    current_obs.date
                    - INTERVAL '56 days'

            GROUP BY
                current_obs.date,
                current_obs.gmv,
                current_obs.item_rows,
                current_obs.item_orders,
                current_obs.day_of_week
            ),

        scored AS (

            SELECT

                date,

                gmv,

                item_rows,

                item_orders,

                history_points,

                seasonal_median,

                seasonal_mad,

                CASE

                    WHEN
                        seasonal_median IS NOT NULL
                        AND seasonal_median != 0

                    THEN
                        (
                            gmv
                            -
                            seasonal_median
                        )
                        /
                        seasonal_median

                    ELSE NULL

                END AS relative_change,

                CASE

                    WHEN
                        seasonal_mad IS NOT NULL
                        AND seasonal_mad > 0

                    THEN
                        (
                            gmv
                            -
                            seasonal_median
                        )
                        /
                        (
                            1.4826
                            *
                            seasonal_mad
                        )

                    ELSE NULL

                END AS robust_z_score

            FROM historical
        )
        SELECT

            date,

            gmv,

            history_points,
            
            item_rows,
            
            item_orders,

            seasonal_median AS baseline,

            seasonal_mad,

            relative_change,

            robust_z_score AS z_score,

            ABS(
                relative_change
            ) AS relative_change_abs,

            ABS(
                gmv - seasonal_median
            ) AS absolute_change,

            CASE

                WHEN
                    history_points >=
                    {MIN_HISTORY_POINTS}

                    AND z_score IS NOT NULL

                    AND ABS(z_score) >=
                    {Z_SCORE_THRESHOLD}

                THEN 1

                ELSE 0

            END AS statistically_unusual,

            CASE

                WHEN
                    history_points >=
                    {MIN_HISTORY_POINTS}

                    AND relative_change IS NOT NULL

                    AND ABS(relative_change) >=
                    {GMV_RELATIVE_THRESHOLD}

                    AND ABS(gmv - seasonal_median) >=
                    {GMV_ABSOLUTE_THRESHOLD}

                THEN 1

                ELSE 0

            END AS business_material,
            
            CASE
                WHEN
                    item_rows < 10
                    OR item_orders < 10
                THEN 1
                ELSE 0
            END AS sparse_observation,

            CASE

                WHEN
                    history_points <
                    {MIN_HISTORY_POINTS}

                THEN 'INSUFFICIENT_HISTORY'

                WHEN
                    item_rows < {MIN_CURRENT_ITEM_ROWS}
                    OR item_orders < {MIN_CURRENT_ITEM_ORDERS}

                THEN 'SPARSE_OBSERVATION'

                WHEN
                    z_score IS NOT NULL
                    AND ABS(z_score) >=
                        {Z_SCORE_THRESHOLD}

                    AND ABS(
                        gmv - seasonal_median
                    ) >=
                        {GMV_ABSOLUTE_THRESHOLD}

                    AND ABS(relative_change) >=
                        {GMV_RELATIVE_THRESHOLD}

                THEN 'MATERIAL'

                WHEN
                    z_score IS NOT NULL
                    AND ABS(z_score) >=
                        {Z_SCORE_THRESHOLD}

                THEN 'STATISTICALLY_UNUSUAL'

                WHEN
                    ABS(relative_change) >=
                        {GMV_RELATIVE_THRESHOLD}

                    AND ABS(
                        gmv - seasonal_median
                    ) >=
                        {GMV_ABSOLUTE_THRESHOLD}

                THEN 'BUSINESS_MATERIAL'

                ELSE 'NORMAL'

            END AS materiality_status

        FROM scored

        ORDER BY date;
        """
    )

    print("[OK] GMV seasonal materiality analysis")


# ============================================================
# PRIORITY SCORE
# ============================================================

def build_priority_score(con):

    print("\n[BUILD] Materiality priority score")

    con.execute(
        """
        CREATE OR REPLACE TABLE fact_gmv_materiality AS

        SELECT

            *,

            CASE

                WHEN
                    materiality_status =
                    'MATERIAL'

                THEN
                    LEAST(
                        1.0,

                        (
                            LEAST(
                                1.0,
                                ABS(z_score) / 5.0
                            )

                            +

                            LEAST(
                                1.0,
                                ABS(relative_change) / 0.25
                            )

                            +

                            LEAST(
                                1.0,
                                absolute_change /
                                500000.0
                            )

                        ) / 3.0

                    )

                WHEN
                    materiality_status IN (
                        'STATISTICALLY_UNUSUAL',
                        'BUSINESS_MATERIAL'
                    )

                THEN 0.50

                ELSE 0.0

            END AS priority_score

        FROM fact_gmv_materiality;
        """
    )

    print("[OK] Materiality priority score")


# ============================================================
# DISPLAY MATERIAL MOVEMENTS
# ============================================================

def show_material_movements(con):

    print("\n" + "=" * 80)
    print("MATERIAL / UNUSUAL GMV MOVEMENTS")
    print("=" * 80)

    df = con.execute(
        """
        SELECT

            date,

            ROUND(
                gmv,
                2
            ) AS gmv,

            history_points,
            item_rows,
            item_orders,

            ROUND(
                baseline,
                2
            ) AS baseline,

            ROUND(
                relative_change * 100,
                2
            ) AS relative_change_pct,

            ROUND(
                z_score,
                2
            ) AS z_score,

            ROUND(
                absolute_change,
                2
            ) AS absolute_change,

            materiality_status,

            ROUND(
                priority_score,
                3
            ) AS priority_score

        FROM fact_gmv_materiality

        WHERE
            materiality_status != 'NORMAL'

        ORDER BY
            priority_score DESC,
            date DESC

        LIMIT 20;
        """
    ).fetchdf()

    if df.empty:

        print(
            "No non-normal GMV movements detected."
        )

        return

    print(
        df.to_string(
            index=False
        )
    )


# ============================================================
# LATEST OBSERVATION
# ============================================================

def show_latest_status(con):

    print("\n" + "=" * 80)
    print("LATEST GMV OBSERVATION")
    print("=" * 80)

    df = con.execute(
        """
        SELECT

            date,

            ROUND(
                gmv,
                2
            ) AS gmv,

            history_points,

            ROUND(
                baseline,
                2
            ) AS baseline,

            ROUND(
                relative_change * 100,
                2
            ) AS relative_change_pct,

            ROUND(
                z_score,
                2
            ) AS z_score,

            materiality_status,

            ROUND(
                priority_score,
                3
            ) AS priority_score

        FROM fact_gmv_materiality

        ORDER BY
            date DESC

        LIMIT 1;
        """
    ).fetchdf()

    if df.empty:

        print(
            "No GMV observation available."
        )

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
    print("=" * 80)
    print("BusinessIntelligence.ai")
    print("MATERIALITY ENGINE")
    print("=" * 80)

    con = connect_database()

    try:

        build_gmv_materiality(con)

        build_priority_score(con)

        show_material_movements(con)

        show_latest_status(con)

        print("\n" + "=" * 80)
        print("MATERIALITY ENGINE COMPLETE")
        print("=" * 80)

    finally:

        con.close()


if __name__ == "__main__":
    main()