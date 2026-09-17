from pathlib import Path
import pandas as pd
import duckdb


# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CONTEXT_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "simulated"
    / "business_context.csv"
)

DB_PATH = (
    PROJECT_ROOT
    / "data"
    / "warehouse"
    / "businessintelligence.duckdb"
)


# ============================================================
# LOAD
# ============================================================

def main():

    print("\n")
    print("=" * 80)
    print("BusinessIntelligence.ai")
    print("LOAD BUSINESS CONTEXT")
    print("=" * 80)

    if not CONTEXT_PATH.exists():
        raise FileNotFoundError(
            f"Business context file not found:\n{CONTEXT_PATH}"
        )

    df = pd.read_csv(
        CONTEXT_PATH,
        keep_default_na=True
    )

    print(f"\nRows loaded: {len(df):,}")
    print("\nColumns:")
    for column in df.columns:
        print(f"  - {column}")

    # Parse date
    df["date"] = pd.to_datetime(
        df["date"],
        errors="coerce"
    ).dt.date

    # Normalize strings
    for column in [
        "region",
        "category",
        "marketing_campaign",
        "inventory_status",
        "ground_truth_driver",
        "scenario_id",
    ]:

        if column in df.columns:

            df[column] = (
                df[column]
                .astype("string")
                .str.strip()
            )

    # Connect
    con = duckdb.connect(
        str(DB_PATH)
    )

    try:

        con.register(
            "business_context_temp",
            df
        )

        con.execute(
            """
            CREATE OR REPLACE TABLE business_context AS

            SELECT *
            FROM business_context_temp;
            """
        )

        con.unregister(
            "business_context_temp"
        )

        print(
            "\n[OK] business_context table created"
        )

        # Show scenarios
        result = con.execute(
            """
            SELECT

                scenario_id,

                MIN(date) AS start_date,

                MAX(date) AS end_date,

                ANY_VALUE(
                    ground_truth_driver
                ) AS ground_truth_driver,

                COUNT(*) AS rows

            FROM business_context

            GROUP BY
                scenario_id

            ORDER BY
                scenario_id;
            """
        ).fetchdf()

        print("\n" + "=" * 80)
        print("SCENARIOS")
        print("=" * 80)

        print(
            result.to_string(
                index=False
            )
        )

    finally:

        con.close()

    print("\n" + "=" * 80)
    print("BUSINESS CONTEXT LOAD COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()