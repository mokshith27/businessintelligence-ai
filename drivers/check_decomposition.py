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

        print("\n" + "=" * 80)
        print("GMV DECOMPOSITION CHECK")
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
                ) AS total_change,

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
                ) AS residual_effect,

                ROUND(
                    volume_effect
                    + aov_effect
                    + residual_effect,
                    2
                ) AS reconstructed_change

            FROM fact_monthly_gmv_decomposition

            ORDER BY month DESC

            LIMIT 15;
            """
        )

        print(
            result.df().to_string(
                index=False
            )
        )

        print("\n" + "=" * 80)
        print("RECONSTRUCTION ERROR")
        print("=" * 80)

        check = con.execute(
            """
            SELECT
                MAX(
                    ABS(
                        total_gmv_change
                        -
                        (
                            volume_effect
                            + aov_effect
                            + residual_effect
                        )
                    )
                ) AS max_error

            FROM fact_monthly_gmv_decomposition;
            """
        ).fetchone()[0]

        print(f"Maximum reconstruction error: {check}")

    finally:
        con.close()


if __name__ == "__main__":
    main()