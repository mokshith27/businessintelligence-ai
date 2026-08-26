from pathlib import Path
import duckdb
import torch

from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
)


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
# MODEL
# ============================================================

MODEL_NAME = (
    "cardiffnlp/twitter-xlm-roberta-base-sentiment"
)


# ============================================================
# DATABASE
# ============================================================

def connect_database():

    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"DuckDB database not found:\n{DB_PATH}"
        )

    return duckdb.connect(
        str(DB_PATH)
    )


# ============================================================
# LOAD MODEL
# ============================================================

def load_model():

    print("\n[MODEL] Loading tokenizer...")

    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_NAME,
        use_fast=False
    )

    print("[MODEL] Loading sentiment model...")

    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_NAME
    )

    device = (
        torch.device("cuda")
        if torch.cuda.is_available()
        else torch.device("cpu")
    )

    model.to(device)
    model.eval()

    print(
        f"[MODEL] Device: {device}"
    )

    return tokenizer, model, device


# ============================================================
# SENTIMENT LABELS
# ============================================================

def get_label_mapping(model):

    mapping = {}

    for index, label in model.config.id2label.items():

        mapping[int(index)] = label

    return mapping


# ============================================================
# PREDICT SENTIMENT
# ============================================================

def predict_batch(
    texts,
    tokenizer,
    model,
    device,
    label_mapping,
):
    """
    Returns:

        label
        confidence
    """

    encoded = tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=256,
        return_tensors="pt",
    )

    encoded = {
        key: value.to(device)
        for key, value in encoded.items()
    }

    with torch.no_grad():

        outputs = model(
            **encoded
        )

    probabilities = torch.softmax(
        outputs.logits,
        dim=1
    )

    confidence, predictions = (
        probabilities.max(dim=1)
    )

    results = []

    for index in range(
        len(texts)
    ):

        predicted_index = (
            int(predictions[index])
        )

        results.append(
            (
                label_mapping[
                    predicted_index
                ],
                float(
                    confidence[index]
                ),
            )
        )

    return results


# ============================================================
# BUILD SENTIMENT TABLE
# ============================================================

def build_sentiment_table(
    con,
    tokenizer,
    model,
    device,
    label_mapping,
):

    print("\n[BUILD] Aspect-level sentiment")

    # --------------------------------------------------------
    # Recreate table
    # --------------------------------------------------------

    con.execute(
        """
        DROP TABLE IF EXISTS
        fact_review_sentiment;
        """
    )

    con.execute(
        """
        CREATE TABLE fact_review_sentiment (

            review_id VARCHAR,

            order_id VARCHAR,

            review_score BIGINT,

            review_creation_date TIMESTAMP,

            aspect VARCHAR,

            review_text VARCHAR,

            sentiment VARCHAR,

            sentiment_confidence DOUBLE
        );
        """
    )

    # --------------------------------------------------------
    # Process in batches
    # --------------------------------------------------------

    batch_size = 64

    offset = 0

    total_processed = 0

    while True:

        rows = con.execute(
            """
            SELECT

                review_id,
                order_id,
                review_score,
                review_creation_date,
                aspect,
                review_text

            FROM fact_review_aspects

            ORDER BY
                review_id

            LIMIT ?
            OFFSET ?;
            """,
            [
                batch_size,
                offset,
            ],
        ).fetchall()

        if not rows:
            break

        texts = [
            row[5]
            for row in rows
        ]

        predictions = predict_batch(
            texts,
            tokenizer,
            model,
            device,
            label_mapping,
        )

        insert_rows = []

        for row, prediction in zip(
            rows,
            predictions,
        ):

            (
                sentiment,
                confidence,
            ) = prediction

            insert_rows.append(
                (
                    row[0],
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                    row[5],
                    sentiment,
                    confidence,
                )
            )

        con.executemany(
            """
            INSERT INTO fact_review_sentiment
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?
            );
            """,
            insert_rows,
        )

        total_processed += len(rows)

        offset += batch_size

        print(
            f"Processed "
            f"{total_processed:,} "
            f"aspect records"
        )

    print(
        "[OK] Sentiment classification complete"
    )


# ============================================================
# SENTIMENT SUMMARY
# ============================================================

def show_sentiment_summary(con):

    print("\n" + "=" * 80)
    print("ASPECT SENTIMENT SUMMARY")
    print("=" * 80)

    df = con.execute(
        """
        SELECT

            aspect,

            sentiment,

            COUNT(*) AS records,

            ROUND(
                AVG(
                    sentiment_confidence
                ),
                3
            ) AS avg_confidence,

            ROUND(
                AVG(review_score),
                3
            ) AS avg_review_score

        FROM fact_review_sentiment

        GROUP BY
            aspect,
            sentiment

        ORDER BY
            aspect,
            records DESC;
        """
    ).fetchdf()

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
    print("ASPECT-LEVEL SENTIMENT ENGINE")
    print("=" * 80)

    con = connect_database()

    try:

        tokenizer, model, device = (
            load_model()
        )

        label_mapping = (
            get_label_mapping(
                model
            )
        )

        print(
            "\nModel labels:"
        )

        print(
            label_mapping
        )

        build_sentiment_table(
            con,
            tokenizer,
            model,
            device,
            label_mapping,
        )

        show_sentiment_summary(
            con
        )

        print("\n" + "=" * 80)
        print("SENTIMENT ENGINE COMPLETE")
        print("=" * 80)

    finally:

        con.close()


if __name__ == "__main__":
    main()