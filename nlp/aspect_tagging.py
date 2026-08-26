from pathlib import Path
import duckdb
import re


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
# ASPECT KEYWORDS
# ============================================================

ASPECT_KEYWORDS = {

    "delivery": [
        # Portuguese
        "entrega",
        "entregue",
        "entregaram",
        "atraso",
        "atrasada",
        "atrasado",
        "demorou",
        "demora",
        "prazo",
        "transportadora",
        "chegou",

        # English
        "delivery",
        "delivered",
        "late",
        "delay",
        "delayed",
        "shipping",
        "shipment",
    ],

    "product_quality": [
        # Portuguese
        "qualidade",
        "produto",
        "defeito",
        "defeituoso",
        "quebrado",
        "quebrada",
        "danificado",
        "danificada",
        "funciona",
        "funcionamento",
        "material",

        # English
        "quality",
        "product",
        "defect",
        "defective",
        "broken",
        "damaged",
        "works",
        "material",
    ],

    "packaging": [
        # Portuguese
        "embalagem",
        "embalado",
        "pacote",
        "caixa",
        "proteção",
        "protecao",

        # English
        "packaging",
        "package",
        "box",
        "packed",
        "protection",
    ],

    "customer_service": [
        # Portuguese
        "atendimento",
        "suporte",
        "vendedor",
        "vendedora",
        "resposta",
        "responderam",
        "contato",

        # English
        "support",
        "service",
        "seller",
        "customer service",
        "response",
        "contact",
    ],

    "price": [
        # Portuguese
        "preço",
        "preco",
        "caro",
        "cara",
        "barato",
        "barata",
        "valor",
        "pagamento",

        # English
        "price",
        "expensive",
        "cheap",
        "cost",
        "value",
        "payment",
    ],
}


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_text(text):

    if text is None:
        return ""

    text = str(text)

    text = text.lower()

    # Normalize repeated whitespace
    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# ============================================================
# ASPECT DETECTION
# ============================================================

def detect_aspects(text):

    normalized = normalize_text(text)

    if not normalized:
        return []

    detected = []

    for aspect, keywords in ASPECT_KEYWORDS.items():

        for keyword in keywords:

            if keyword in normalized:

                detected.append(aspect)

                break

    return detected


# ============================================================
# BUILD REVIEW TEXT TABLE
# ============================================================

def build_review_text_table(con):

    print("\n[BUILD] Preparing review text")

    con.execute(
        """
        CREATE OR REPLACE TABLE fact_review_text AS

        SELECT

            review_id,

            order_id,

            review_score,

            review_creation_date,

            TRIM(
                CONCAT(
                    COALESCE(
                        review_comment_title,
                        ''
                    ),
                    ' ',
                    COALESCE(
                        review_comment_message,
                        ''
                    )
                )
            ) AS review_text

        FROM fact_reviews

        WHERE
            review_creation_date IS NOT NULL
            AND (
                review_comment_title IS NOT NULL
                OR
                review_comment_message IS NOT NULL
            );
        """
    )

    print("[OK] Review text prepared")


# ============================================================
# CREATE ASPECT RECORDS
# ============================================================

def build_review_aspects(con):

    print("\n[BUILD] Detecting review aspects")

    # --------------------------------------------------------
    # Prepare destination table
    # --------------------------------------------------------

    con.execute(
        """
        DROP TABLE IF EXISTS fact_review_aspects;
        """
    )

    con.execute(
        """
        CREATE TABLE fact_review_aspects (

            review_id VARCHAR,

            order_id VARCHAR,

            review_score BIGINT,

            review_creation_date TIMESTAMP,

            aspect VARCHAR,

            review_text VARCHAR
        );
        """
    )

    # --------------------------------------------------------
    # Process reviews in chunks
    # --------------------------------------------------------

    chunk_size = 5000

    total_processed = 0
    total_aspect_records = 0

    offset = 0

    while True:

        reviews = con.execute(
            """
            SELECT
                review_id,
                order_id,
                review_score,
                review_creation_date,
                review_text

            FROM fact_review_text

            ORDER BY review_id

            LIMIT ?
            OFFSET ?;
            """,
            [chunk_size, offset],
        ).fetchall()

        if not reviews:
            break

        rows = []

        for (
            review_id,
            order_id,
            review_score,
            review_creation_date,
            review_text,
        ) in reviews:

            aspects = detect_aspects(
                review_text
            )

            for aspect in aspects:

                rows.append(
                    (
                        review_id,
                        order_id,
                        review_score,
                        review_creation_date,
                        aspect,
                        review_text,
                    )
                )

        # ----------------------------------------------------
        # Batch insert
        # ----------------------------------------------------

        if rows:

            con.executemany(
                """
                INSERT INTO fact_review_aspects
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                rows,
            )

            total_aspect_records += len(rows)

        total_processed += len(reviews)

        print(
            f"Processed {total_processed:,} reviews | "
            f"Aspect records: {total_aspect_records:,}"
        )

        offset += chunk_size

    print(
        f"[OK] Processed {total_processed:,} reviews"
    )

    print(
        f"[OK] Aspect records created: "
        f"{total_aspect_records:,}"
    )


# ============================================================
# ASPECT SUMMARY
# ============================================================

def show_aspect_summary(con):

    print("\n" + "=" * 80)
    print("REVIEW ASPECT SUMMARY")
    print("=" * 80)

    df = con.execute(
        """
        SELECT

            aspect,

            COUNT(*) AS aspect_mentions,

            COUNT(
                DISTINCT review_id
            ) AS reviews_with_aspect,

            ROUND(
                AVG(review_score),
                3
            ) AS avg_review_score

        FROM fact_review_aspects

        GROUP BY
            aspect

        ORDER BY
            aspect_mentions DESC;
        """
    ).fetchdf()

    if df.empty:

        print(
            "No review aspects detected."
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
    print("REVIEW ASPECT TAGGING")
    print("=" * 80)

    con = duckdb.connect(
        str(DB_PATH)
    )

    try:

        build_review_text_table(
            con
        )

        build_review_aspects(
            con
        )

        show_aspect_summary(
            con
        )

        print("\n" + "=" * 80)
        print("ASPECT TAGGING COMPLETE")
        print("=" * 80)

    finally:

        con.close()


if __name__ == "__main__":
    main()