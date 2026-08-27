from pathlib import Path
import json
import math

import duckdb
import numpy as np
import pandas as pd


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

CAUSAL_RESULT_PATH = (
    PROJECT_ROOT
    / "data"
    / "causal"
    / "delivery_review_causal_effect.json"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "causal"
)


# ============================================================
# CONFIG
# ============================================================

PROPENSITY_LOW = 0.05
PROPENSITY_HIGH = 0.95

SMALL_SAMPLE_THRESHOLD = 500

SMD_WARNING = 0.20


# ============================================================
# LOAD CAUSAL RESULT
# ============================================================

def load_result():

    if not CAUSAL_RESULT_PATH.exists():

        raise FileNotFoundError(
            f"Causal result not found:\n"
            f"{CAUSAL_RESULT_PATH}"
        )

    return json.loads(
        CAUSAL_RESULT_PATH.read_text(
            encoding="utf-8"
        )
    )


# ============================================================
# DATABASE
# ============================================================

def connect_database():

    if not DB_PATH.exists():

        raise FileNotFoundError(
            f"DuckDB database not found:\n"
            f"{DB_PATH}"
        )

    return duckdb.connect(
        str(DB_PATH)
    )


# ============================================================
# LOAD DIAGNOSTIC DATA
# ============================================================

def load_diagnostic_data(
    con,
):

    query = """
        SELECT

            o.order_id,

            o.order_purchase_timestamp,

            o.order_delivered_customer_date,

            o.order_estimated_delivery_date,

            o.customer_state,

            r.review_score

        FROM fact_orders_enriched AS o

        INNER JOIN fact_reviews AS r

            ON o.order_id = r.order_id

        WHERE

            o.order_delivered_customer_date IS NOT NULL

            AND o.order_estimated_delivery_date IS NOT NULL

            AND r.review_score IS NOT NULL;
    """

    df = con.execute(
        query
    ).fetchdf()

    if df.empty:

        raise RuntimeError(
            "No rows available for causal diagnostics."
        )

    df[
        "delivered"
    ] = pd.to_datetime(
        df[
            "order_delivered_customer_date"
        ],
        errors="coerce",
    )

    df[
        "estimated"
    ] = pd.to_datetime(
        df[
            "order_estimated_delivery_date"
        ],
        errors="coerce",
    )

    df = df.dropna(
        subset=[
            "delivered",
            "estimated",
            "review_score",
        ]
    ).copy()

    df[
        "late_delivery"
    ] = (
        df["delivered"]
        >
        df["estimated"]
    ).astype(int)

    df["purchase_timestamp"] = pd.to_datetime(
        df[
            "order_purchase_timestamp"
        ],
        errors="coerce",
    )

    df["purchase_month"] = (
        df[
            "purchase_timestamp"
        ]
        .dt.month
    )

    df["purchase_dow"] = (
        df[
            "purchase_timestamp"
        ]
        .dt.dayofweek
    )

    return df


# ============================================================
# STANDARDIZED MEAN DIFFERENCE
# ============================================================

def standardized_mean_difference(
    treated,
    control,
):

    treated = np.asarray(
        treated,
        dtype=float,
    )

    control = np.asarray(
        control,
        dtype=float,
    )

    treated_mean = np.mean(
        treated
    )

    control_mean = np.mean(
        control
    )

    pooled_sd = np.sqrt(
        (
            np.var(
                treated,
                ddof=1,
            )
            +
            np.var(
                control,
                ddof=1,
            )
        )
        / 2
    )

    if pooled_sd == 0:

        return 0.0

    return (
        (
            treated_mean
            - control_mean
        )
        / pooled_sd
    )


# ============================================================
# BASIC BALANCE
# ============================================================

def evaluate_basic_balance(
    df,
):

    treated = df[
        df["late_delivery"] == 1
    ]

    control = df[
        df["late_delivery"] == 0
    ]

    balance = {}

    # --------------------------------------------------------
    # Month
    # --------------------------------------------------------

    balance[
        "purchase_month"
    ] = standardized_mean_difference(
        treated[
            "purchase_month"
        ].fillna(
            treated[
                "purchase_month"
            ].median()
        ),
        control[
            "purchase_month"
        ].fillna(
            control[
                "purchase_month"
            ].median()
        ),
    )

    # --------------------------------------------------------
    # Day of week
    # --------------------------------------------------------

    balance[
        "purchase_dow"
    ] = standardized_mean_difference(
        treated[
            "purchase_dow"
        ].fillna(
            treated[
                "purchase_dow"
            ].median()
        ),
        control[
            "purchase_dow"
        ].fillna(
            control[
                "purchase_dow"
            ].median()
        ),
    )

    return balance


# ============================================================
# PROPENSITY DIAGNOSTICS
# ============================================================

def propensity_diagnostics(
    result,
):

    overlap = result.get(
        "overlap",
        {}
    )

    min_propensity = overlap.get(
        "min_propensity"
    )

    max_propensity = overlap.get(
        "max_propensity"
    )

    overlap_width = overlap.get(
        "overlap_width"
    )

    acceptable = (
        min_propensity is not None
        and max_propensity is not None
        and overlap_width is not None
        and overlap_width > 0.10
        and min_propensity >= 0.01
        and max_propensity <= 0.99
    )

    return {

        "min_propensity":
            min_propensity,

        "max_propensity":
            max_propensity,

        "overlap_width":
            overlap_width,

        "acceptable":
            acceptable,
    }


# ============================================================
# SAMPLE DIAGNOSTICS
# ============================================================

def sample_diagnostics(
    df,
):

    treated = int(
        df[
            "late_delivery"
        ].sum()
    )

    control = (
        len(df)
        - treated
    )

    review_mean = float(
        df[
            "review_score"
        ].mean()
    )

    review_std = float(
        df[
            "review_score"
        ].std()
    )

    return {

        "total":
            len(df),

        "treated":
            treated,

        "control":
            control,

        "review_mean":
            review_mean,

        "review_std":
            review_std,

        "sufficient_total":
            len(df)
            >= SMALL_SAMPLE_THRESHOLD,

        "sufficient_treated":
            treated
            >= SMALL_SAMPLE_THRESHOLD,

        "sufficient_control":
            control
            >= SMALL_SAMPLE_THRESHOLD,
    }


# ============================================================
# CAUSAL RESULT SANITY CHECK
# ============================================================

def evaluate_causal_result(
    result,
    sample,
    propensity,
    balance,
):

    issues = []
    warnings = []

    # --------------------------------------------------------
    # Sample
    # --------------------------------------------------------

    if not sample[
        "sufficient_total"
    ]:

        issues.append(
            "Total causal sample is small."
        )

    if not sample[
        "sufficient_treated"
    ]:

        issues.append(
            "Treated group is too small."
        )

    if not sample[
        "sufficient_control"
    ]:

        issues.append(
            "Control group is too small."
        )

    # --------------------------------------------------------
    # Propensity overlap
    # --------------------------------------------------------

    if not propensity[
        "acceptable"
    ]:

        issues.append(
            "Propensity-score overlap is insufficient."
        )

    # --------------------------------------------------------
    # Basic balance
    # --------------------------------------------------------

    for feature, smd in balance.items():

        if abs(smd) > SMD_WARNING:

            warnings.append(
                f"{feature} has standardized "
                f"mean difference {smd:+.3f}."
            )

    # --------------------------------------------------------
    # Causal status
    # --------------------------------------------------------

    original_status = result.get(
        "status"
    )

    original_confidence = result.get(
        "confidence"
    )

    if issues:

        diagnostic_status = (
            "CAUSAL_RESULT_REQUIRES_REVIEW"
        )

        diagnostic_confidence = min(
            float(
                original_confidence
                or 0.0
            ),
            0.40,
        )

    elif warnings:

        diagnostic_status = (
            "CAUSAL_RESULT_WITH_BALANCE_WARNING"
        )

        diagnostic_confidence = min(
            float(
                original_confidence
                or 0.0
            ),
            0.65,
        )

    else:

        diagnostic_status = (
            "CAUSAL_RESULT_DIAGNOSTICALLY_ACCEPTABLE"
        )

        diagnostic_confidence = float(
            original_confidence
            or 0.0
        )

    return {

        "original_status":
            original_status,

        "original_confidence":
            original_confidence,

        "diagnostic_status":
            diagnostic_status,

        "diagnostic_confidence":
            diagnostic_confidence,

        "issues":
            issues,

        "warnings":
            warnings,
    }


# ============================================================
# BUILD DIAGNOSTIC REPORT
# ============================================================

def build_report(
    result,
    df,
):

    sample = sample_diagnostics(
        df
    )

    propensity = propensity_diagnostics(
        result
    )

    balance = evaluate_basic_balance(
        df
    )

    assessment = evaluate_causal_result(
        result,
        sample,
        propensity,
        balance,
    )

    return {

        "causal_result":
            {
                "effect":
                    result.get(
                        "causal_effect"
                    ),

                "ci_lower":
                    result.get(
                        "bootstrap",
                        {},
                    ).get(
                        "ci_lower"
                    ),

                "ci_upper":
                    result.get(
                        "bootstrap",
                        {},
                    ).get(
                        "ci_upper"
                    ),
            },

        "sample":
            sample,

        "propensity":
            propensity,

        "basic_balance":
            balance,

        "assessment":
            assessment,
    }


# ============================================================
# DISPLAY
# ============================================================

def display_report(
    report,
):

    print("\n")
    print("=" * 100)
    print("BusinessIntelligence.ai")
    print("CAUSAL DIAGNOSTICS")
    print("=" * 100)

    sample = report[
        "sample"
    ]

    print(
        f"\nSample size      : "
        f"{sample['total']:,}"
    )

    print(
        f"Treated          : "
        f"{sample['treated']:,}"
    )

    print(
        f"Control          : "
        f"{sample['control']:,}"
    )

    propensity = report[
        "propensity"
    ]

    print(
        "\nPropensity overlap"
    )

    print(
        f"Minimum          : "
        f"{propensity['min_propensity']:.4f}"
    )

    print(
        f"Maximum          : "
        f"{propensity['max_propensity']:.4f}"
    )

    print(
        f"Overlap width    : "
        f"{propensity['overlap_width']:.4f}"
    )

    print(
        f"Acceptable       : "
        f"{propensity['acceptable']}"
    )

    print(
        "\nBasic balance"
    )

    for feature, smd in report[
        "basic_balance"
    ].items():

        print(
            f"  {feature:<20} "
            f"SMD = {smd:+.4f}"
        )

    assessment = report[
        "assessment"
    ]

    print(
        "\nDiagnostic status : "
        f"{assessment['diagnostic_status']}"
    )

    print(
        "Diagnostic confidence : "
        f"{assessment['diagnostic_confidence']:.3f}"
    )

    if assessment[
        "issues"
    ]:

        print(
            "\nIssues:"
        )

        for issue in assessment[
            "issues"
        ]:

            print(
                f"  - {issue}"
            )

    if assessment[
        "warnings"
    ]:

        print(
            "\nWarnings:"
        )

        for warning in assessment[
            "warnings"
        ]:

            print(
                f"  - {warning}"
            )


# ============================================================
# SAVE
# ============================================================

def save_report(
    report,
):

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        OUTPUT_DIR
        / "causal_diagnostics.json"
    )

    path.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return path


# ============================================================
# MAIN
# ============================================================

def main():

    result = load_result()

    con = connect_database()

    try:

        df = load_diagnostic_data(
            con
        )

        report = build_report(
            result,
            df,
        )

        display_report(
            report
        )

        path = save_report(
            report
        )

        print("\n")
        print("=" * 100)
        print(
            "CAUSAL DIAGNOSTICS COMPLETE"
        )
        print("=" * 100)

        print(
            f"Saved: {path}"
        )

    finally:

        con.close()


if __name__ == "__main__":
    main()