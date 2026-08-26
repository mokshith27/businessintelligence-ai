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
            "Run load_and_build_kpis.py first."
        )

    return duckdb.connect(str(DB_PATH), read_only=True)


# ============================================================
# SHOW TABLES
# ============================================================

def show_tables(con):
    print("\n" + "=" * 80)
    print("1. TABLES IN DUCKDB")
    print("=" * 80)

    tables = con.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'main'
        ORDER BY table_name;
        """
    ).fetchall()

    for i, (table_name,) in enumerate(tables, start=1):
        print(f"{i:2}. {table_name}")

    print(f"\nTotal tables: {len(tables)}")

    return [table_name for table_name, in tables]


# ============================================================
# ROW COUNTS
# ============================================================

def show_row_counts(con, tables):
    print("\n" + "=" * 80)
    print("2. ROW COUNTS")
    print("=" * 80)

    for table in tables:
        count = con.execute(
            f'SELECT COUNT(*) FROM "{table}"'
        ).fetchone()[0]

        print(f"{table:50} {count:>12,}")


# ============================================================
# SCHEMA INFORMATION
# ============================================================

def show_schema(con, tables):
    print("\n" + "=" * 80)
    print("3. COLUMN INFORMATION")
    print("=" * 80)

    for table in tables:

        print("\n" + "-" * 80)
        print(f"TABLE: {table}")
        print("-" * 80)

        columns = con.execute(
            f"""
            SELECT
                column_name,
                data_type,
                is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'main'
              AND table_name = ?
            ORDER BY ordinal_position;
            """,
            [table],
        ).fetchall()

        print(
            f"{'Column':40}"
            f"{'Type':25}"
            f"{'Nullable':10}"
        )

        print("-" * 75)

        for column_name, data_type, nullable in columns:
            print(
                f"{column_name:40}"
                f"{data_type:25}"
                f"{nullable:10}"
            )


# ============================================================
# SAMPLE DATA
# ============================================================

def show_samples(con, tables):
    print("\n" + "=" * 80)
    print("4. SAMPLE ROWS")
    print("=" * 80)

    for table in tables:

        print("\n" + "-" * 80)
        print(f"TABLE: {table}")
        print("-" * 80)

        result = con.execute(
            f"""
            SELECT *
            FROM "{table}"
            LIMIT 3;
            """
        )

        print(result.df().to_string(index=False))


# ============================================================
# DATE COLUMN DETECTION
# ============================================================

def find_date_columns(con, tables):
    print("\n" + "=" * 80)
    print("5. POSSIBLE DATE / TIME COLUMNS")
    print("=" * 80)

    keywords = [
        "date",
        "time",
        "timestamp",
        "purchase",
        "delivery",
        "approved",
        "carrier",
        "estimated",
        "closed",
        "first_contact",
    ]

    for table in tables:

        columns = con.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'main'
              AND table_name = ?;
            """,
            [table],
        ).fetchall()

        matches = []

        for column_name, data_type in columns:

            name_lower = column_name.lower()

            if any(
                keyword in name_lower
                for keyword in keywords
            ):
                matches.append(
                    (column_name, data_type)
                )

        if matches:

            print(f"\n{table}")

            for column_name, data_type in matches:
                print(
                    f"  - {column_name}"
                    f" [{data_type}]"
                )


# ============================================================
# IMPORTANT KEY COLUMNS
# ============================================================

def find_key_columns(con, tables):
    print("\n" + "=" * 80)
    print("6. POSSIBLE JOIN / KEY COLUMNS")
    print("=" * 80)

    key_keywords = [
        "id",
        "seller",
        "customer",
        "order",
        "product",
        "review",
        "lead",
        "mql",
    ]

    for table in tables:

        columns = con.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'main'
              AND table_name = ?;
            """,
            [table],
        ).fetchall()

        matches = []

        for column_name, data_type in columns:

            name_lower = column_name.lower()

            if (
                name_lower.endswith("_id")
                or name_lower == "id"
                or any(
                    keyword in name_lower
                    for keyword in key_keywords
                )
            ):
                matches.append(
                    (column_name, data_type)
                )

        if matches:

            print(f"\n{table}")

            for column_name, data_type in matches:
                print(
                    f"  - {column_name}"
                    f" [{data_type}]"
                )


# ============================================================
# NULL CHECK
# ============================================================

def show_null_summary(con, tables):
    print("\n" + "=" * 80)
    print("7. NULL VALUE SUMMARY")
    print("=" * 80)

    for table in tables:

        columns = con.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'main'
              AND table_name = ?
            ORDER BY ordinal_position;
            """,
            [table],
        ).fetchall()

        print(f"\n{table}")

        for (column_name,) in columns:

            null_count = con.execute(
                f"""
                SELECT COUNT(*)
                FROM "{table}"
                WHERE "{column_name}" IS NULL;
                """
            ).fetchone()[0]

            if null_count > 0:
                print(
                    f"  {column_name:40}"
                    f"{null_count:>10,} NULL"
                )


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n")
    print("=" * 80)
    print("BusinessIntelligence.ai")
    print("DUCKDB DATABASE INSPECTION")
    print("=" * 80)

    con = connect_database()

    try:

        tables = show_tables(con)

        if not tables:
            print("\nNo tables found.")
            return

        show_row_counts(con, tables)

        show_schema(con, tables)

        show_samples(con, tables)

        find_date_columns(con, tables)

        find_key_columns(con, tables)

        show_null_summary(con, tables)

        print("\n" + "=" * 80)
        print("DATABASE INSPECTION COMPLETE")
        print("=" * 80)

    finally:
        con.close()


if __name__ == "__main__":
    main()