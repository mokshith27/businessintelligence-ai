from pathlib import Path
from datetime import datetime, timezone
import json
import uuid

import duckdb
import pandas as pd


# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

DB_PATH = (
    PROJECT_ROOT
    / "data"
    / "warehouse"
    / "businessintelligence.duckdb"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "feedback"
)

FEEDBACK_JSON = (
    OUTPUT_DIR
    / "feedback_records.json"
)

CALIBRATION_JSON = (
    OUTPUT_DIR
    / "calibration_report.json"
)


# ============================================================
# CONFIGURATION
# ============================================================

MIN_FEEDBACK_FOR_CALIBRATION = 5

CONFIDENCE_BINS = [
    (0.00, 0.20),
    (0.20, 0.40),
    (0.40, 0.60),
    (0.60, 0.80),
    (0.80, 1.01),
]


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


def ensure_feedback_table(
    con,
):

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS feedback_records (

            feedback_id VARCHAR,

            created_at TIMESTAMP,

            role VARCHAR,

            event_id VARCHAR,

            event_start_date DATE,

            event_end_date DATE,

            driver_type VARCHAR,

            driver VARCHAR,

            predicted_status VARCHAR,

            predicted_confidence DOUBLE,

            predicted_decision VARCHAR,

            feedback_label VARCHAR,

            corrected_driver VARCHAR,

            correction_text VARCHAR

        );
        """
    )


# ============================================================
# VALIDATION
# ============================================================

VALID_LABELS = {
    "CORRECT",
    "INCORRECT",
    "MISSING_CONTEXT",
}


def validate_feedback(
    feedback_label,
):

    label = (
        str(feedback_label)
        .strip()
        .upper()
    )

    if label not in VALID_LABELS:

        raise ValueError(
            "feedback_label must be one of: "
            "CORRECT, INCORRECT, MISSING_CONTEXT"
        )

    return label


# ============================================================
# CAPTURE
# ============================================================

def capture_feedback(
    con,
    *,
    role,
    event_id,
    event_start_date,
    event_end_date,
    driver_type,
    driver,
    predicted_status,
    predicted_confidence,
    predicted_decision,
    feedback_label,
    corrected_driver=None,
    correction_text=None,
):

    feedback_label = validate_feedback(
        feedback_label
    )

    if predicted_confidence is not None:

        predicted_confidence = float(
            predicted_confidence
        )

        if not (
            0.0
            <= predicted_confidence
            <= 1.0
        ):

            raise ValueError(
                "predicted_confidence must be between 0 and 1."
            )

    feedback_id = str(
        uuid.uuid4()
    )

    created_at = datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )

    con.execute(
        """
        INSERT INTO feedback_records (
            feedback_id,
            created_at,
            role,
            event_id,
            event_start_date,
            event_end_date,
            driver_type,
            driver,
            predicted_status,
            predicted_confidence,
            predicted_decision,
            feedback_label,
            corrected_driver,
            correction_text
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            feedback_id,
            created_at,
            str(role),
            str(event_id),
            event_start_date,
            event_end_date,
            driver_type,
            driver,
            predicted_status,
            predicted_confidence,
            predicted_decision,
            feedback_label,
            corrected_driver,
            correction_text,
        ],
    )

    return feedback_id


# ============================================================
# LOAD FEEDBACK
# ============================================================

def load_feedback(
    con,
):

    return con.execute(
        """
        SELECT
            *
        FROM feedback_records
        ORDER BY created_at DESC
        """
    ).fetchdf()


# ============================================================
# BINARY CORRECTNESS
# ============================================================

def feedback_is_correct(
    label,
):

    return (
        str(label).upper()
        == "CORRECT"
    )


# ============================================================
# CONFIDENCE BINS
# ============================================================

def confidence_bin(
    value,
):

    if value is None:
        return "UNKNOWN"

    value = float(value)

    for lower, upper in CONFIDENCE_BINS:

        if (
            lower
            <= value
            < upper
        ):

            return (
                f"{lower:.1f}"
                f"-"
                f"{min(upper, 1.0):.1f}"
            )

    return "UNKNOWN"


# ============================================================
# CALIBRATION REPORT
# ============================================================

def build_calibration_report(
    df,
):

    if df.empty:

        return {

            "status":
                "NO_FEEDBACK",

            "feedback_count":
                0,

            "message":
                "No analyst feedback has been recorded yet.",

            "bins":
                [],
        }

    df = df.copy()

    # --------------------------------------------------------
    # CORRECTNESS
    #
    # MISSING_CONTEXT is deliberately NOT treated as correct
    # or incorrect. It means the analyst believes the evidence
    # was insufficient or incomplete.
    # --------------------------------------------------------

    df["is_correct"] = (
        df[
            "feedback_label"
        ]
        == "CORRECT"
    )

    df["confidence_bin"] = (
        df[
            "predicted_confidence"
        ]
        .apply(
            confidence_bin
        )
    )

    # --------------------------------------------------------
    # Overall statistics
    # --------------------------------------------------------

    total = len(df)

    correct = int(
        (
            df[
                "feedback_label"
            ]
            == "CORRECT"
        ).sum()
    )

    incorrect = int(
        (
            df[
                "feedback_label"
            ]
            == "INCORRECT"
        ).sum()
    )

    missing_context = int(
        (
            df[
                "feedback_label"
            ]
            == "MISSING_CONTEXT"
        ).sum()
    )

    definite_feedback = (
        correct
        + incorrect
    )

    empirical_accuracy = (
        correct / definite_feedback
        if definite_feedback > 0
        else None
    )

    # --------------------------------------------------------
    # Confidence-bin calibration
    # --------------------------------------------------------

    bins = []

    definite_df = df[
        df[
            "feedback_label"
        ].isin(
            [
                "CORRECT",
                "INCORRECT",
            ]
        )
    ].copy()

    for lower, upper in CONFIDENCE_BINS:

        mask = (
            definite_df[
                "predicted_confidence"
            ].notna()
            &
            (
                definite_df[
                    "predicted_confidence"
                ] >= lower
            )
            &
            (
                definite_df[
                    "predicted_confidence"
                ] < upper
            )
        )

        subset = definite_df[
            mask
        ]

        if subset.empty:

            continue

        count = len(
            subset
        )

        observed_accuracy = float(
            subset[
                "is_correct"
            ].mean()
        )

        mean_predicted_confidence = float(
            subset[
                "predicted_confidence"
            ].mean()
        )

        calibration_gap = (
            observed_accuracy
            - mean_predicted_confidence
        )

        bins.append(
            {
                "confidence_range":
                    f"{lower:.1f}-{min(upper, 1.0):.1f}",

                "count":
                    count,

                "mean_predicted_confidence":
                    round(
                        mean_predicted_confidence,
                        4,
                    ),

                "observed_accuracy":
                    round(
                        observed_accuracy,
                        4,
                    ),

                "calibration_gap":
                    round(
                        calibration_gap,
                        4,
                    ),
            }
        )

    # --------------------------------------------------------
    # Driver-level calibration
    # --------------------------------------------------------

    driver_groups = []

    for driver, group in definite_df.groupby(
        [
            "driver_type",
            "driver",
        ]
    ):

        count = len(
            group
        )

        observed_accuracy = float(
            group[
                "is_correct"
            ].mean()
        )

        mean_confidence = float(
            group[
                "predicted_confidence"
            ].mean()
        )

        driver_groups.append(
            {
                "driver_type":
                    driver[0],

                "driver":
                    driver[1],

                "feedback_count":
                    count,

                "mean_confidence":
                    round(
                        mean_confidence,
                        4,
                    ),

                "observed_accuracy":
                    round(
                        observed_accuracy,
                        4,
                    ),

                "calibration_gap":
                    round(
                        observed_accuracy
                        - mean_confidence,
                        4,
                    ),
            }
        )

    # --------------------------------------------------------
    # Readiness
    # --------------------------------------------------------

    if total < MIN_FEEDBACK_FOR_CALIBRATION:

        calibration_status = (
            "COLLECTING_FEEDBACK"
        )

    else:

        calibration_status = (
            "CALIBRATION_AVAILABLE"
        )

    return {

        "status":
            calibration_status,

        "feedback_count":
            total,

        "correct":
            correct,

        "incorrect":
            incorrect,

        "missing_context":
            missing_context,

        "definite_feedback":
            definite_feedback,

        "empirical_accuracy":
            (
                round(
                    empirical_accuracy,
                    4,
                )
                if empirical_accuracy
                is not None
                else None
            ),

        "bins":
            bins,

        "driver_calibration":
            driver_groups,

        "calibration_policy":
            {
                "minimum_feedback":
                    MIN_FEEDBACK_FOR_CALIBRATION,

                "automatic_confidence_override":
                    False,

                "reason":
                    (
                        "Feedback is used first to measure "
                        "calibration. Production confidence "
                        "is not automatically overwritten "
                        "from small feedback samples."
                    ),
            },
    }


# ============================================================
# SAVE
# ============================================================

def save_json(
    path,
    data,
):

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )


def save_feedback_records(
    df,
):

    if df.empty:

        records = []

    else:

        records = (
            df.to_dict(
                orient="records"
            )
        )

    save_json(
        FEEDBACK_JSON,
        records,
    )


def save_calibration_report(
    report,
):

    save_json(
        CALIBRATION_JSON,
        report,
    )


# ============================================================
# DEMO FEEDBACK
# ============================================================

def create_demo_feedback(
    con,
):

    ensure_feedback_table(
        con
    )

    existing = con.execute(
        """
        SELECT COUNT(*)
        FROM feedback_records
        """
    ).fetchone()[0]

    if existing > 0:

        print(
            f"[INFO] Existing feedback records: "
            f"{existing}"
        )

        return

    # --------------------------------------------------------
    # Three deliberately different examples.
    # These are DEMO records, so we mark the role as
    # demonstration.
    # --------------------------------------------------------

    capture_feedback(
        con,
        role="analyst_demo",
        event_id="37",
        event_start_date="2017-11-23",
        event_end_date="2017-11-29",
        driver_type="customer_state",
        driver="SP",
        predicted_status="WEAK",
        predicted_confidence=0.418,
        predicted_decision="INVESTIGATE",
        feedback_label="CORRECT",
        corrected_driver=None,
        correction_text=(
            "Observed contribution was useful, but "
            "investigation was appropriate."
        ),
    )

    capture_feedback(
        con,
        role="analyst_demo",
        event_id="37",
        event_start_date="2017-11-23",
        event_end_date="2017-11-29",
        driver_type="customer_state",
        driver="RJ",
        predicted_status="CONTRADICTED",
        predicted_confidence=0.171,
        predicted_decision="DO_NOT_ACT",
        feedback_label="CORRECT",
        corrected_driver=None,
        correction_text=(
            "Evidence supported not acting on RJ."
        ),
    )

    capture_feedback(
        con,
        role="analyst_demo",
        event_id="37",
        event_start_date="2017-11-23",
        event_end_date="2017-11-29",
        driver_type="category",
        driver="health_beauty",
        predicted_status="ABSTAIN",
        predicted_confidence=0.101,
        predicted_decision="ABSTAIN",
        feedback_label="MISSING_CONTEXT",
        corrected_driver=None,
        correction_text=(
            "Need campaign and inventory context "
            "before assessing this category."
        ),
    )

    print(
        "[OK] Demo feedback records created"
    )


# ============================================================
# DISPLAY
# ============================================================

def display_report(
    report,
):

    print("\n")
    print("=" * 100)
    print("BusinessIntelligence.ai")
    print("FEEDBACK & CALIBRATION ENGINE")
    print("=" * 100)

    print(
        f"\nStatus              : "
        f"{report['status']}"
    )

    print(
        f"Feedback records    : "
        f"{report['feedback_count']}"
    )

    print(
        f"Correct             : "
        f"{report['correct']}"
    )

    print(
        f"Incorrect           : "
        f"{report['incorrect']}"
    )

    print(
        f"Missing context     : "
        f"{report['missing_context']}"
    )

    if report[
        "empirical_accuracy"
    ] is not None:

        print(
            f"Empirical accuracy  : "
            f"{report['empirical_accuracy']:.3f}"
        )

    print(
        "\nConfidence calibration:"
    )

    if report["bins"]:

        for item in report[
            "bins"
        ]:

            print(
                f"  {item['confidence_range']:<10} "
                f"n={item['count']:<4} "
                f"pred={item['mean_predicted_confidence']:.3f} "
                f"obs={item['observed_accuracy']:.3f} "
                f"gap={item['calibration_gap']:+.3f}"
            )

    else:

        print(
            "  No sufficient calibration observations."
        )

    print(
        "\nDriver calibration:"
    )

    for item in report[
        "driver_calibration"
    ]:

        print(
            f"  {item['driver_type']:<18} "
            f"{item['driver']:<25} "
            f"n={item['feedback_count']:<4} "
            f"pred={item['mean_confidence']:.3f} "
            f"obs={item['observed_accuracy']:.3f}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n")
    print("=" * 100)
    print("BusinessIntelligence.ai")
    print("FEEDBACK ENGINE")
    print("=" * 100)

    con = connect_database()

    try:

        ensure_feedback_table(
            con
        )

        # ----------------------------------------------------
        # Demo records.
        #
        # These are only inserted when the table is empty.
        # Remove this call once you begin collecting real
        # analyst feedback from the dashboard.
        # ----------------------------------------------------

        # create_demo_feedback(
        #     con
        # )

        df = load_feedback(
            con
        )

        report = build_calibration_report(
            df
        )

        save_feedback_records(
            df
        )

        save_calibration_report(
            report
        )

        display_report(
            report
        )

        print("\n")
        print("=" * 100)
        print(
            "FEEDBACK ENGINE COMPLETE"
        )
        print("=" * 100)

        print(
            f"Feedback saved: {FEEDBACK_JSON}"
        )

        print(
            f"Calibration saved: {CALIBRATION_JSON}"
        )

    finally:

        con.close()


if __name__ == "__main__":
    main()