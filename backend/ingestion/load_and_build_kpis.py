from pathlib import Path
import sys
import pandas as pd
import duckdb


# ============================================================
# PROJECT PATHS
# ============================================================

# ingestion/load_and_build_kpis.py
# parent = ingestion/
# parent.parent = businessintelligence-ai/

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = PROJECT_ROOT / "data"
RAW_OLIST_DIR = DATA_DIR / "raw" / "olist"
RAW_FUNNEL_DIR = DATA_DIR / "raw" / "funnel"

DB_DIR = PROJECT_ROOT / "data" / "warehouse"
DB_PATH = DB_DIR / "businessintelligence.duckdb"


# ============================================================
# EXPECTED FILES
# ============================================================

OLIST_FILES = [
    "olist_orders_dataset",
    "olist_order_items_dataset",
    "olist_order_payments_dataset",
    "olist_order_reviews_dataset",
    "olist_customers_dataset",
    "olist_products_dataset",
    "olist_sellers_dataset",
    "olist_geolocation_dataset",
    "product_category_name_translation",
]

FUNNEL_FILES = [
    "olist_marketing_qualified_leads_dataset",
    "olist_closed_deals_dataset",
]


# ============================================================
# FILE FINDER
# ============================================================

def find_data_file(directory: Path, base_name: str) -> Path | None:
    """
    Finds either a CSV or Excel file with the requested base name.

    Examples:
        olist_orders_dataset.csv
        olist_orders_dataset.xlsx
        olist_orders_dataset.xls
    """

    extensions = [".csv", ".xlsx", ".xls"]

    for extension in extensions:
        candidate = directory / f"{base_name}{extension}"

        if candidate.exists():
            return candidate

    return None


# ============================================================
# FILE READER
# ============================================================

def read_data_file(file_path: Path) -> pd.DataFrame:
    """
    Reads CSV or Excel files into a pandas DataFrame.
    """

    suffix = file_path.suffix.lower()

    print(f"\nReading: {file_path.name}")

    if suffix == ".csv":
        df = pd.read_csv(file_path)

    elif suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(file_path)

    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    return df


# ============================================================
# BASIC DATA PROFILE
# ============================================================

def profile_dataframe(name: str, df: pd.DataFrame) -> None:
    """
    Prints useful information about a dataframe.
    """

    print("\n" + "=" * 70)
    print(f"TABLE: {name}")
    print("=" * 70)

    print(f"Rows        : {len(df):,}")
    print(f"Columns     : {len(df.columns)}")

    print("\nColumns:")
    for column in df.columns:
        print(f"  - {column}")

    print("\nMissing values:")
    missing = df.isna().sum()

    missing = missing[missing > 0]

    if missing.empty:
        print("  No missing values")
    else:
        for column, count in missing.items():
            percentage = count / len(df) * 100

            print(
                f"  - {column}: "
                f"{count:,} ({percentage:.2f}%)"
            )

    print("\nDuplicate rows:")
    print(f"  {df.duplicated().sum():,}")

    print("\nData types:")
    print(df.dtypes.to_string())


# ============================================================
# TABLE NAME CLEANER
# ============================================================

def normalize_table_name(file_path: Path) -> str:
    """
    Converts a filename into a clean DuckDB table name.
    """

    return file_path.stem.lower().replace("-", "_")


# ============================================================
# LOAD DATAFRAME INTO DUCKDB
# ============================================================

def load_dataframe_to_duckdb(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
    df: pd.DataFrame,
) -> None:
    """
    Registers a pandas dataframe and creates/replaces
    a DuckDB table from it.
    """

    temporary_view = f"{table_name}_temp"

    connection.register(temporary_view, df)

    connection.execute(
        f"""
        CREATE OR REPLACE TABLE "{table_name}" AS
        SELECT *
        FROM "{temporary_view}"
        """
    )

    connection.unregister(temporary_view)


# ============================================================
# PROCESS ONE DIRECTORY
# ============================================================

def process_directory(
    connection: duckdb.DuckDBPyConnection,
    directory: Path,
    expected_files: list[str],
) -> None:

    if not directory.exists():
        print(f"\nERROR: Directory not found: {directory}")
        return

    print("\n" + "#" * 70)
    print(f"PROCESSING DIRECTORY: {directory}")
    print("#" * 70)

    for base_name in expected_files:

        file_path = find_data_file(directory, base_name)

        if file_path is None:
            print(
                f"\nWARNING: Could not find "
                f"{base_name}.csv/.xlsx/.xls"
            )
            continue

        try:
            df = read_data_file(file_path)

            table_name = normalize_table_name(file_path)

            profile_dataframe(table_name, df)

            load_dataframe_to_duckdb(
                connection,
                table_name,
                df,
            )

            print(
                f"\nLoaded successfully into DuckDB as:"
                f" {table_name}"
            )

        except Exception as error:
            print(
                f"\nERROR while processing "
                f"{file_path.name}:"
            )

            print(error)


# ============================================================
# SHOW DUCKDB TABLES
# ============================================================

def show_database_tables(
    connection: duckdb.DuckDBPyConnection
) -> None:

    print("\n" + "=" * 70)
    print("DUCKDB TABLES")
    print("=" * 70)

    result = connection.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'main'
        ORDER BY table_name
        """
    ).fetchall()

    if not result:
        print("No tables found.")
        return

    for row in result:
        print(f"  - {row[0]}")


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n")
    print("=" * 70)
    print("BusinessIntelligence.ai")
    print("DATA INGESTION PIPELINE")
    print("=" * 70)

    # --------------------------------------------------------
    # Create warehouse directory
    # --------------------------------------------------------

    DB_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Connect to DuckDB
    # --------------------------------------------------------

    print(f"\nDuckDB database:")
    print(DB_PATH)

    connection = duckdb.connect(
        str(DB_PATH)
    )

    try:

        # ----------------------------------------------------
        # Olist commerce data
        # ----------------------------------------------------

        process_directory(
            connection=connection,
            directory=RAW_OLIST_DIR,
            expected_files=OLIST_FILES,
        )

        # ----------------------------------------------------
        # Olist marketing funnel data
        # ----------------------------------------------------

        process_directory(
            connection=connection,
            directory=RAW_FUNNEL_DIR,
            expected_files=FUNNEL_FILES,
        )

        # ----------------------------------------------------
        # Final database inspection
        # ----------------------------------------------------

        show_database_tables(connection)

        print("\n" + "=" * 70)
        print("INGESTION COMPLETE")
        print("=" * 70)

    finally:

        connection.close()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        print("\nPipeline interrupted by user.")
        sys.exit(1)

    except Exception as error:
        print("\nPipeline failed.")
        print(error)
        sys.exit(1)
