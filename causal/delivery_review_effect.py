from pathlib import Path
import json
import math
import warnings

import duckdb
import numpy as np
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.ensemble import RandomForestRegressor


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

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "causal"
)


# ============================================================
# CONFIGURATION
# ============================================================

RANDOM_STATE = 42

N_BOOTSTRAPS = 500

MIN_SAMPLE_SIZE = 1000

MIN_TREATED = 200

MIN_CONTROL = 200

MIN_OVERLAP = 0.05

MAX_STABILIZED_WEIGHT = 20.0

TRIM_LOWER = 0.01

TRIM_UPPER = 0.99


# ============================================================
# SAFE CONVERSION
# ============================================================

def safe_float(value):

    if value is None:
        return None

    value = float(value)

    if not math.isfinite(value):
        return None

    return value


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
# FIND A USABLE COLUMN
# ============================================================

def find_column(
    columns,
    candidates,
):

    lower_map = {
        column.lower(): column
        for column in columns
    }

    for candidate in candidates:

        if candidate.lower() in lower_map:

            return lower_map[
                candidate.lower()
            ]

    return None


# ============================================================
# BUILD CAUSAL DATASET
# ============================================================

def load_causal_dataset(
    con,
):
    """
    Build the causal analysis dataset by joining:

        fact_orders_enriched
            +
        fact_reviews

    Treatment:
        late_delivery

    Outcome:
        review_score

    Important:
        delivery_delay_days is NOT used as a predictor because
        it is derived from delivery timing and would leak
        post-treatment information into the causal model.
    """

    # ========================================================
    # ORDER TABLE SCHEMA
    # ========================================================

    orders_schema = con.execute(
        """
        DESCRIBE fact_orders_enriched
        """
    ).fetchdf()

    order_columns = (
        orders_schema["column_name"]
        .tolist()
    )

    # ========================================================
    # REVIEW TABLE SCHEMA
    # ========================================================

    reviews_schema = con.execute(
        """
        DESCRIBE fact_reviews
        """
    ).fetchdf()

    review_columns = (
        reviews_schema["column_name"]
        .tolist()
    )

    # ========================================================
    # FIND REQUIRED ORDER COLUMNS
    # ========================================================

    order_id_col = find_column(
        order_columns,
        [
            "order_id",
        ],
    )

    delivered_col = find_column(
        order_columns,
        [
            "order_delivered_customer_date",
            "delivered_customer_date",
        ],
    )

    estimated_col = find_column(
        order_columns,
        [
            "order_estimated_delivery_date",
            "estimated_delivery_date",
        ],
    )

    purchase_date_col = find_column(
        order_columns,
        [
            "order_purchase_timestamp",
            "purchase_timestamp",
        ],
    )

    customer_state_col = find_column(
        order_columns,
        [
            "customer_state",
        ],
    )

    seller_state_col = find_column(
        order_columns,
        [
            "seller_state",
        ],
    )

    category_col = find_column(
        order_columns,
        [
            "product_category",
            "category",
            "product_category_name",
        ],
    )

    price_col = find_column(
        order_columns,
        [
            "order_value",
            "total_price",
            "price",
            "gmv",
        ],
    )

    freight_col = find_column(
        order_columns,
        [
            "freight_value",
            "total_freight_value",
        ],
    )

    # ========================================================
    # FIND REQUIRED REVIEW COLUMNS
    # ========================================================

    review_order_id_col = find_column(
        review_columns,
        [
            "order_id",
        ],
    )

    review_score_col = find_column(
        review_columns,
        [
            "review_score",
            "score",
        ],
    )

    # ========================================================
    # REQUIRED COLUMN VALIDATION
    # ========================================================

    required = {

        "orders.order_id":
            order_id_col,

        "orders.order_delivered_customer_date":
            delivered_col,

        "orders.order_estimated_delivery_date":
            estimated_col,

        "reviews.order_id":
            review_order_id_col,

        "reviews.review_score":
            review_score_col,
    }

    missing = [
        name
        for name, column in required.items()
        if column is None
    ]

    if missing:

        raise RuntimeError(
            "The causal module cannot run because "
            "the following required columns are missing:\n"
            f"{missing}\n\n"
            f"fact_orders_enriched columns:\n"
            f"{order_columns}\n\n"
            f"fact_reviews columns:\n"
            f"{review_columns}"
        )

    # ========================================================
    # BUILD SELECT LIST
    # ========================================================

    select_parts = [

        f'o."{order_id_col}" AS order_id',

        f'r."{review_score_col}" AS review_score',

        f'o."{delivered_col}" '
        f'AS delivered_customer_date',

        f'o."{estimated_col}" '
        f'AS estimated_delivery_date',
    ]

    # --------------------------------------------------------
    # Optional PRE-TREATMENT covariates
    # --------------------------------------------------------

    if price_col:

        select_parts.append(
            f'o."{price_col}" AS order_value'
        )

    if freight_col:

        select_parts.append(
            f'o."{freight_col}" AS freight_value'
        )

    if customer_state_col:

        select_parts.append(
            f'o."{customer_state_col}" '
            f'AS customer_state'
        )

    if seller_state_col:

        select_parts.append(
            f'o."{seller_state_col}" '
            f'AS seller_state'
        )

    if category_col:

        select_parts.append(
            f'o."{category_col}" AS category'
        )

    if purchase_date_col:

        select_parts.append(
            f'o."{purchase_date_col}" '
            f'AS purchase_timestamp'
        )

    # ========================================================
    # JOIN ORDERS + REVIEWS
    # ========================================================

    query = f"""
        SELECT
            {", ".join(select_parts)}

        FROM fact_orders_enriched AS o

        INNER JOIN fact_reviews AS r

            ON o."{order_id_col}"
             = r."{review_order_id_col}"

        WHERE
            o."{delivered_col}" IS NOT NULL

            AND o."{estimated_col}" IS NOT NULL

            AND r."{review_score_col}" IS NOT NULL
    """

    df = con.execute(
        query
    ).fetchdf()

    if df.empty:

        raise RuntimeError(
            "The orders/reviews join returned zero rows."
        )

    # ========================================================
    # DATETIME CONVERSION
    # ========================================================

    df[
        "delivered_customer_date"
    ] = pd.to_datetime(
        df[
            "delivered_customer_date"
        ],
        errors="coerce",
    )

    df[
        "estimated_delivery_date"
    ] = pd.to_datetime(
        df[
            "estimated_delivery_date"
        ],
        errors="coerce",
    )

    # ========================================================
    # VALIDATE REVIEW SCORE
    # ========================================================

    df[
        "review_score"
    ] = pd.to_numeric(
        df[
            "review_score"
        ],
        errors="coerce",
    )

    df = df.dropna(
        subset=[
            "delivered_customer_date",
            "estimated_delivery_date",
            "review_score",
        ]
    ).copy()

    df = df[
        df[
            "review_score"
        ].between(
            1,
            5,
        )
    ].copy()

    # ========================================================
    # DEFINE TREATMENT
    # ========================================================
    #
    # 1 = delivered after estimated date
    # 0 = delivered on or before estimated date
    #
    # This is the treatment we are estimating.
    # ========================================================

    df[
        "late_delivery"
    ] = (
        df[
            "delivered_customer_date"
        ]
        >
        df[
            "estimated_delivery_date"
        ]
    ).astype(int)

    # ========================================================
    # PRE-TREATMENT TIME FEATURES
    # ========================================================

    if "purchase_timestamp" in df.columns:

        df[
            "purchase_timestamp"
        ] = pd.to_datetime(
            df[
                "purchase_timestamp"
            ],
            errors="coerce",
        )

        df[
            "purchase_month"
        ] = (
            df[
                "purchase_timestamp"
            ]
            .dt.month
        )

        df[
            "purchase_dow"
        ] = (
            df[
                "purchase_timestamp"
            ]
            .dt.dayofweek
        )

        # We no longer need the raw timestamp.
        df = df.drop(
            columns=[
                "purchase_timestamp"
            ]
        )

    # ========================================================
    # NUMERIC CLEANUP
    # ========================================================

    for column in [
        "order_value",
        "freight_value",
    ]:

        if column in df.columns:

            df[column] = pd.to_numeric(
                df[column],
                errors="coerce",
            )

    # ========================================================
    # IMPORTANT:
    # DO NOT USE delivery_delay_days
    # ========================================================
    #
    # If it somehow came through from the source, remove it.
    # It is post-treatment information.
    # ========================================================

    if "delivery_delay_days" in df.columns:

        df = df.drop(
            columns=[
                "delivery_delay_days"
            ]
        )

    # ========================================================
    # FINAL CLEANUP
    # ========================================================

    df = df.replace(
        [
            np.inf,
            -np.inf,
        ],
        np.nan,
    )

    return df

# ============================================================
# FEATURE SELECTION
# ============================================================

def get_features(df):

    numeric_features = []

    categorical_features = []

    for column in [
        "order_value",
        "freight_value",
        "purchase_month",
        "purchase_dow",
    ]:

        if column in df.columns:

            numeric_features.append(
                column
            )

    for column in [
        "customer_state",
        "seller_state",
        "category",
    ]:

        if column in df.columns:

            categorical_features.append(
                column
            )

    return (
        numeric_features,
        categorical_features,
    )


# ============================================================
# PROPENSITY MODEL
# ============================================================

def fit_propensity_model(
    df,
):

    numeric_features, categorical_features = (
        get_features(df)
    )

    feature_columns = (
        numeric_features
        + categorical_features
    )

    if not feature_columns:

        raise RuntimeError(
            "No usable pre-treatment covariates "
            "are available for the propensity model."
        )

    X = df[
        feature_columns
    ]

    y = df[
        "late_delivery"
    ]

    numeric_pipeline = Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(
                    strategy="median"
                ),
            ),
        ]
    )

    categorical_pipeline = Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(
                    strategy="most_frequent"
                ),
            ),

            (
                "onehot",
                OneHotEncoder(
                    handle_unknown="ignore",
                    min_frequency=10,
                ),
            ),
        ]
    )

    transformers = []

    if numeric_features:

        transformers.append(
            (
                "numeric",
                numeric_pipeline,
                numeric_features,
            )
        )

    if categorical_features:

        transformers.append(
            (
                "categorical",
                categorical_pipeline,
                categorical_features,
            )
        )

    preprocessor = ColumnTransformer(
        transformers=transformers
    )

    model = Pipeline(
        steps=[
            (
                "preprocessor",
                preprocessor,
            ),

            (
                "model",
                LogisticRegression(
                    max_iter=2000,
                    class_weight="balanced",
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )

    with warnings.catch_warnings():

        warnings.simplefilter(
            "ignore"
        )

        model.fit(
            X,
            y,
        )

    propensity = model.predict_proba(
        X
    )[:, 1]

    return (
        model,
        propensity,
        feature_columns,
    )


# ============================================================
# OVERLAP DIAGNOSTICS
# ============================================================

def overlap_diagnostics(
    treatment,
    propensity,
):

    treated = propensity[
        treatment == 1
    ]

    control = propensity[
        treatment == 0
    ]

    min_propensity = float(
        propensity.min()
    )

    max_propensity = float(
        propensity.max()
    )

    treated_min = float(
        treated.min()
    ) if len(treated) else None

    treated_max = float(
        treated.max()
    ) if len(treated) else None

    control_min = float(
        control.min()
    ) if len(control) else None

    control_max = float(
        control.max()
    ) if len(control) else None

    overlap_lower = max(
        float(
            treated.min()
        ),
        float(
            control.min()
        ),
    )

    overlap_upper = min(
        float(
            treated.max()
        ),
        float(
            control.max()
        ),
    )

    overlap_width = max(
        0.0,
        overlap_upper
        - overlap_lower,
    )

    return {

        "min_propensity":
            min_propensity,

        "max_propensity":
            max_propensity,

        "treated_min":
            treated_min,

        "treated_max":
            treated_max,

        "control_min":
            control_min,

        "control_max":
            control_max,

        "overlap_lower":
            overlap_lower,

        "overlap_upper":
            overlap_upper,

        "overlap_width":
            overlap_width,

        "acceptable_overlap":
            (
                treated_min is not None
                and control_min is not None
                and overlap_width
                >= MIN_OVERLAP
            ),
    }


# ============================================================
# TRIM EXTREME PROPENSITIES
# ============================================================

def trim_data(
    df,
    propensity,
):

    lower = max(
        TRIM_LOWER,
        float(
            np.quantile(
                propensity,
                0.01,
            )
        ),
    )

    upper = min(
        TRIM_UPPER,
        float(
            np.quantile(
                propensity,
                0.99,
            )
        ),
    )

    mask = (
        propensity >= lower
    ) & (
        propensity <= upper
    )

    trimmed_df = df.loc[
        mask
    ].copy()

    trimmed_propensity = (
        propensity[
            mask
        ]
    )

    return (
        trimmed_df,
        trimmed_propensity,
        lower,
        upper,
    )


# ============================================================
# AIPW ESTIMATE
# ============================================================

def fit_outcome_models(
    df,
):
    """
    Fit two outcome models using ONE shared preprocessing
    pipeline.

    Model 1:
        E[Y | X, treatment=1]

    Model 2:
        E[Y | X, treatment=0]

    Both models receive the exact same transformed feature
    representation.
    """

    numeric_features, categorical_features = (
        get_features(df)
    )

    feature_columns = (
        numeric_features
        + categorical_features
    )

    if not feature_columns:

        raise RuntimeError(
            "No usable covariates are available for "
            "the outcome models."
        )

    X = df[
        feature_columns
    ]

    treatment = df[
        "late_delivery"
    ].values

    y = df[
        "review_score"
    ].values

    # ========================================================
    # SHARED PREPROCESSOR
    # ========================================================

    transformers = []

    # --------------------------------------------------------
    # Numeric features
    # --------------------------------------------------------

    if numeric_features:

        numeric_pipeline = Pipeline(
            steps=[
                (
                    "imputer",
                    SimpleImputer(
                        strategy="median"
                    ),
                ),
            ]
        )

        transformers.append(
            (
                "numeric",
                numeric_pipeline,
                numeric_features,
            )
        )

    # --------------------------------------------------------
    # Categorical features
    # --------------------------------------------------------

    if categorical_features:

        categorical_pipeline = Pipeline(
            steps=[
                (
                    "imputer",
                    SimpleImputer(
                        strategy="most_frequent"
                    ),
                ),

                (
                    "onehot",
                    OneHotEncoder(
                        handle_unknown="ignore",
                        min_frequency=10,
                    ),
                ),
            ]
        )

        transformers.append(
            (
                "categorical",
                categorical_pipeline,
                categorical_features,
            )
        )

    preprocessor = ColumnTransformer(
        transformers=transformers
    )

    # ========================================================
    # FIT PREPROCESSOR ON THE COMPLETE ANALYSIS SAMPLE
    # ========================================================
    #
    # This is acceptable because preprocessing here is
    # unsupervised: no review-score information is used to
    # construct the feature representation.
    # ========================================================

    X_transformed = preprocessor.fit_transform(
        X
    )

    # ========================================================
    # CONVERT SPARSE MATRIX IF NECESSARY
    # ========================================================

    if hasattr(
        X_transformed,
        "toarray"
    ):

        X_transformed = (
            X_transformed.toarray()
        )

    # ========================================================
    # SPLIT BY TREATMENT
    # ========================================================

    treated_mask = (
        treatment == 1
    )

    control_mask = (
        treatment == 0
    )

    X_treated = (
        X_transformed[
            treated_mask
        ]
    )

    X_control = (
        X_transformed[
            control_mask
        ]
    )

    y_treated = (
        y[
            treated_mask
        ]
    )

    y_control = (
        y[
            control_mask
        ]
    )

    # ========================================================
    # CHECK
    # ========================================================

    if len(X_treated) == 0:

        raise RuntimeError(
            "No treated observations available "
            "for the treated outcome model."
        )

    if len(X_control) == 0:

        raise RuntimeError(
            "No control observations available "
            "for the control outcome model."
        )

    # ========================================================
    # OUTCOME MODELS
    # ========================================================

    outcome_model_treated = RandomForestRegressor(
        n_estimators=200,
        min_samples_leaf=20,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )

    outcome_model_control = RandomForestRegressor(
        n_estimators=200,
        min_samples_leaf=20,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )

    # ========================================================
    # FIT
    # ========================================================

    with warnings.catch_warnings():

        warnings.simplefilter(
            "ignore"
        )

        outcome_model_treated.fit(
            X_treated,
            y_treated,
        )

        outcome_model_control.fit(
            X_control,
            y_control,
        )

    # ========================================================
    # PREDICT BOTH POTENTIAL OUTCOMES FOR EVERY OBSERVATION
    # ========================================================
    #
    # Every observation uses the SAME transformed X.
    # ========================================================

    mu1 = (
        outcome_model_treated.predict(
            X_transformed
        )
    )

    mu0 = (
        outcome_model_control.predict(
            X_transformed
        )
    )

    return (
        mu1,
        mu0,
    )


def calculate_aipw(
    treatment,
    outcome,
    propensity,
    mu1,
    mu0,
):

    eps = 0.02

    propensity = np.clip(
        propensity,
        eps,
        1.0 - eps,
    )

    treated = treatment == 1

    pseudo_outcome = (
        mu1
        - mu0

        + (
            treatment
            * (
                outcome
                - mu1
            )
            / propensity
        )

        - (
            (
                1 - treatment
            )
            * (
                outcome
                - mu0
            )
            / (
                1
                - propensity
            )
        )
    )

    effect = float(
        np.mean(
            pseudo_outcome
        )
    )

    return (
        effect,
        pseudo_outcome,
    )


# ============================================================
# BOOTSTRAP CI
# ============================================================

def bootstrap_effect(
    treatment,
    outcome,
    propensity,
    mu1,
    mu0,
):

    rng = np.random.default_rng(
        RANDOM_STATE
    )

    n = len(
        outcome
    )

    estimates = []

    for _ in range(
        N_BOOTSTRAPS
    ):

        indices = rng.integers(
            0,
            n,
            size=n,
        )

        try:

            effect, _ = calculate_aipw(
                treatment[
                    indices
                ],

                outcome[
                    indices
                ],

                propensity[
                    indices
                ],

                mu1[
                    indices
                ],

                mu0[
                    indices
                ],
            )

            if math.isfinite(
                effect
            ):

                estimates.append(
                    effect
                )

        except Exception:

            continue

    if len(
        estimates
    ) < 50:

        return {

            "bootstrap_samples":
                len(estimates),

            "ci_lower":
                None,

            "ci_upper":
                None,

            "bootstrap_std":
                None,
        }

    estimates = np.asarray(
        estimates
    )

    ci_lower, ci_upper = np.percentile(
        estimates,
        [
            2.5,
            97.5,
        ],
    )

    return {

        "bootstrap_samples":
            len(estimates),

        "ci_lower":
            float(ci_lower),

        "ci_upper":
            float(ci_upper),

        "bootstrap_std":
            float(
                np.std(
                    estimates,
                    ddof=1,
                )
            ),
    }


# ============================================================
# EFFECT CLASSIFICATION
# ============================================================

def classify_effect(
    effect,
    ci_lower,
    ci_upper,
    overlap_ok,
    sample_size,
):

    if sample_size < MIN_SAMPLE_SIZE:

        return (
            "INSUFFICIENT_SAMPLE",
            0.05,
        )

    if not overlap_ok:

        return (
            "NO_CAUSAL_IDENTIFICATION",
            0.10,
        )

    if (
        ci_lower is None
        or ci_upper is None
    ):

        return (
            "UNCERTAIN",
            0.20,
        )

    # --------------------------------------------------------
    # Interval contains zero.
    # --------------------------------------------------------

    if (
        ci_lower <= 0
        <= ci_upper
    ):

        return (
            "INCONCLUSIVE",
            0.35,
        )

    # --------------------------------------------------------
    # Narrower interval and meaningful effect.
    # --------------------------------------------------------

    interval_width = (
        ci_upper
        - ci_lower
    )

    if (
        effect < 0
        and ci_upper < 0
        and interval_width < 1.0
    ):

        return (
            "CAUSAL_EVIDENCE",
            0.80,
        )

    if (
        effect > 0
        and ci_lower > 0
        and interval_width < 1.0
    ):

        return (
            "CAUSAL_EVIDENCE",
            0.80,
        )

    return (
        "SUGGESTIVE",
        0.60,
    )


# ============================================================
# BUSINESS INTERPRETATION
# ============================================================

def build_business_interpretation(
    effect,
    ci_lower,
    ci_upper,
    status,
):

    if effect is None:

        return (
            "The causal effect could not be estimated "
            "reliably from the available data."
        )

    if status == "NO_CAUSAL_IDENTIFICATION":

        return (
            "The available covariates do not provide sufficient "
            "overlap to identify a reliable causal effect. "
            "Treat the result as observational rather than causal."
        )

    if status == "INCONCLUSIVE":

        return (
            "After adjustment for observed pre-treatment factors, "
            "the estimated effect is not statistically distinguishable "
            "from zero at the bootstrap interval used by the engine."
        )

    effect_text = (
        f"{effect:.3f}"
    )

    if (
        ci_lower is not None
        and ci_upper is not None
    ):

        interval_text = (
            f"[{ci_lower:.3f}, "
            f"{ci_upper:.3f}]"
        )

    else:

        interval_text = (
            "confidence interval unavailable"
        )

    if effect < 0:

        return (
            "Under the observational adjustment assumptions, "
            "late delivery is estimated to reduce review score "
            f"by about {abs(effect):.3f} points "
            f"(95% bootstrap interval {interval_text})."
        )

    return (
        "Under the observational adjustment assumptions, "
        "late delivery is estimated to increase review score "
        f"by about {effect_text} points "
        f"(95% bootstrap interval {interval_text})."
    )


# ============================================================
# RUN ANALYSIS
# ============================================================

def run_causal_analysis(
    con,
):

    print(
        "\n[BUILD] Loading causal dataset"
    )

    df = load_causal_dataset(
        con
    )

    print(
        f"[OK] Causal observations: "
        f"{len(df):,}"
    )

    treated_count = int(
        df[
            "late_delivery"
        ].sum()
    )

    control_count = (
        len(df)
        - treated_count
    )

    print(
        f"Late deliveries     : "
        f"{treated_count:,}"
    )

    print(
        f"On-time deliveries  : "
        f"{control_count:,}"
    )

    if (
        len(df)
        < MIN_SAMPLE_SIZE
        or treated_count
        < MIN_TREATED
        or control_count
        < MIN_CONTROL
    ):

        return {

            "status":
                "INSUFFICIENT_SAMPLE",

            "confidence":
                0.05,

            "sample_size":
                len(df),

            "treated":
                treated_count,

            "control":
                control_count,

            "message":
                "Insufficient sample size for causal estimation.",
        }

    # --------------------------------------------------------
    # Propensity
    # --------------------------------------------------------

    print(
        "\n[BUILD] Fitting propensity model"
    )

    (
        propensity_model,
        propensity,
        feature_columns,
    ) = fit_propensity_model(
        df
    )

    print(
        "[OK] Propensity model fitted"
    )

    treatment = df[
        "late_delivery"
    ].values

    outcome = df[
        "review_score"
    ].values

    # --------------------------------------------------------
    # Overlap
    # --------------------------------------------------------

    overlap = overlap_diagnostics(
        treatment,
        propensity,
    )

    print(
        "\n[CHECK] Propensity overlap"
    )

    print(
        f"Range: "
        f"{overlap['min_propensity']:.4f}"
        f" -> "
        f"{overlap['max_propensity']:.4f}"
    )

    print(
        f"Overlap width: "
        f"{overlap['overlap_width']:.4f}"
    )

    print(
        f"Acceptable overlap: "
        f"{overlap['acceptable_overlap']}"
    )

    # --------------------------------------------------------
    # Trim extreme observations.
    # --------------------------------------------------------

    (
        trimmed_df,
        trimmed_propensity,
        trim_lower,
        trim_upper,
    ) = trim_data(
        df,
        propensity,
    )

    print(
        f"\n[OK] Trimmed observations: "
        f"{len(trimmed_df):,}"
    )

    treatment_trimmed = (
        trimmed_df[
            "late_delivery"
        ].values
    )

    outcome_trimmed = (
        trimmed_df[
            "review_score"
        ].values
    )

    # --------------------------------------------------------
    # Outcome models
    # --------------------------------------------------------

    print(
        "\n[BUILD] Fitting outcome models"
    )

    (
        mu1,
        mu0,
    ) = fit_outcome_models(
        trimmed_df
    )

    print(
        "[OK] Outcome models fitted"
    )

    # --------------------------------------------------------
    # AIPW
    # --------------------------------------------------------

    print(
        "\n[BUILD] Estimating doubly robust effect"
    )

    (
        effect,
        pseudo_outcome,
    ) = calculate_aipw(
        treatment_trimmed,
        outcome_trimmed,
        trimmed_propensity,
        mu1,
        mu0,
    )

    print(
        f"[OK] Estimated effect: "
        f"{effect:+.4f}"
    )

    # --------------------------------------------------------
    # Bootstrap
    # --------------------------------------------------------

    print(
        "\n[BUILD] Bootstrap uncertainty"
    )

    bootstrap = bootstrap_effect(
        treatment_trimmed,
        outcome_trimmed,
        trimmed_propensity,
        mu1,
        mu0,
    )

    print(
        f"[OK] Bootstrap samples: "
        f"{bootstrap['bootstrap_samples']}"
    )

    # --------------------------------------------------------
    # Classification
    # --------------------------------------------------------

    status, confidence = classify_effect(
        effect,
        bootstrap[
            "ci_lower"
        ],
        bootstrap[
            "ci_upper"
        ],
        overlap[
            "acceptable_overlap"
        ],
        len(trimmed_df),
    )

    interpretation = (
        build_business_interpretation(
            effect,
            bootstrap[
                "ci_lower"
            ],
            bootstrap[
                "ci_upper"
            ],
            status,
        )
    )

    # --------------------------------------------------------
    # Naive comparison
    # --------------------------------------------------------

    treated_mean = float(
        df.loc[
            df[
                "late_delivery"
            ] == 1,
            "review_score",
        ].mean()
    )

    control_mean = float(
        df.loc[
            df[
                "late_delivery"
            ] == 0,
            "review_score",
        ].mean()
    )

    naive_difference = (
        treated_mean
        - control_mean
    )

    # --------------------------------------------------------
    # Output
    # --------------------------------------------------------

    return {

        "estimand":
            "ATE",

        "treatment":
            "late_delivery",

        "outcome":
            "review_score",

        "method":
            "Doubly Robust AIPW with propensity adjustment "
            "and bootstrap uncertainty",

        "sample_size":
            len(df),

        "trimmed_sample_size":
            len(trimmed_df),

        "treated":
            treated_count,

        "control":
            control_count,

        "naive_treated_mean_review":
            treated_mean,

        "naive_control_mean_review":
            control_mean,

        "naive_difference":
            naive_difference,

        "causal_effect":
            effect,

        "bootstrap":
            bootstrap,

        "overlap":
            overlap,

        "trimming":
            {
                "lower":
                    trim_lower,

                "upper":
                    trim_upper,
            },

        "features":
            feature_columns,

        "status":
            status,

        "confidence":
            confidence,

        "interpretation":
            interpretation,

        "causal_assumptions":
            [
                "No unmeasured confounding after adjustment "
                "for included pre-treatment covariates.",

                "Positivity / overlap holds for the analyzed "
                "population.",

                "Treatment definition correctly captures "
                "late delivery.",

                "Review score is measured consistently.",

                "Observed data are representative of the "
                "target population for this estimate.",
            ],

        "limitations":
            [
                "This is observational causal inference, "
                "not a randomized experiment.",

                "Unmeasured confounding may remain.",

                "The estimated effect is conditional on the "
                "available covariates and overlap.",

                "Poor overlap causes the engine to downgrade "
                "or reject causal interpretation.",
            ],
    }


# ============================================================
# SAVE
# ============================================================

def save_result(
    result,
):

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        OUTPUT_DIR
        / "delivery_review_causal_effect.json"
    )

    path.write_text(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )

    return path


# ============================================================
# DISPLAY
# ============================================================

def display_result(
    result,
):

    print("\n")
    print("=" * 100)
    print(
        "CAUSAL EFFECT: LATE DELIVERY -> REVIEW SCORE"
    )
    print("=" * 100)

    print(
        f"\nMethod              : "
        f"{result.get('method', 'N/A')}"
    )

    print(
        f"Sample size         : "
        f"{result.get('sample_size', 0):,}"
    )

    print(
        f"Treated             : "
        f"{result.get('treated', 0):,}"
    )

    print(
        f"Control             : "
        f"{result.get('control', 0):,}"
    )

    if result.get(
        "naive_difference"
    ) is not None:

        print(
            f"\nNaive difference    : "
            f"{result['naive_difference']:+.4f}"
        )

    if result.get(
        "causal_effect"
    ) is not None:

        print(
            f"Causal ATE          : "
            f"{result['causal_effect']:+.4f}"
        )

    bootstrap = result.get(
        "bootstrap",
        {}
    )

    if bootstrap.get(
        "ci_lower"
    ) is not None:

        print(
            f"95% bootstrap CI    : "
            f"[{bootstrap['ci_lower']:.4f}, "
            f"{bootstrap['ci_upper']:.4f}]"
        )

    print(
        f"\nStatus              : "
        f"{result.get('status')}"
    )

    print(
        f"Confidence          : "
        f"{result.get('confidence')}"
    )

    print(
        f"\nInterpretation:\n"
        f"{result.get('interpretation')}"
    )

    overlap = result.get(
        "overlap",
        {}
    )

    if overlap:

        print(
            "\nOverlap diagnostics:"
        )

        print(
            f"  overlap width    : "
            f"{overlap.get('overlap_width')}"
        )

        print(
            f"  acceptable       : "
            f"{overlap.get('acceptable_overlap')}"
        )

    print(
        "\nCausal assumptions:"
    )

    for assumption in result.get(
        "causal_assumptions",
        [],
    ):

        print(
            f"  - {assumption}"
        )

    print(
        "\nLimitations:"
    )

    for limitation in result.get(
        "limitations",
        [],
    ):

        print(
            f"  - {limitation}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n")
    print("=" * 100)
    print("BusinessIntelligence.ai")
    print("CAUSAL INFERENCE ENGINE")
    print("=" * 100)

    con = connect_database()

    try:

        result = run_causal_analysis(
            con
        )

        display_result(
            result
        )

        path = save_result(
            result
        )

        print("\n")
        print("=" * 100)
        print("CAUSAL ANALYSIS COMPLETE")
        print("=" * 100)

        print(
            f"Saved: {path}"
        )

    finally:

        con.close()


if __name__ == "__main__":
    main()