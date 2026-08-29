import duckdb

con = duckdb.connect(
    r"data\warehouse\businessintelligence.duckdb",
    read_only=True,
)

tables = con.execute(
    """
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'main'
    ORDER BY table_name
    """
).fetchall()

print("\nALL TABLES:")
for table in tables:
    print(" -", table[0])

review_tables = [
    table[0]
    for table in tables
    if "review" in table[0].lower()
]

print("\nREVIEW TABLES:")
for table in review_tables:
    print(" -", table)

for table in review_tables:
    print(f"\nSCHEMA: {table}")
    columns = con.execute(
        f"""
        SELECT
            column_name,
            data_type
        FROM information_schema.columns
        WHERE table_schema = 'main'
          AND table_name = ?
        ORDER BY ordinal_position
        """,
        [table],
    ).fetchall()

    for column_name, data_type in columns:
        print(f"   {column_name:<30} {data_type}")

con.close()