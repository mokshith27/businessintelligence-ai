from pathlib import Path
import json
import math
from datetime import date, datetime
from typing import Optional

import duckdb
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from security.role_filter import (
    CAUSAL_PATH,
    build_role_view,
)

from feedback.capture_and_calibrate import (
    ensure_feedback_table,
    capture_feedback,
    load_feedback,
    build_calibration_report,
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

INSIGHT_PATH = (
    PROJECT_ROOT
    / "data"
    / "insights"
    / "latest_insight.json"
)

EXECUTIVE_STORY_PATH = (
    PROJECT_ROOT
    / "data"
    / "insights"
    / "executive_story.json"
)

OPERATIONS_STORY_PATH = (
    PROJECT_ROOT
    / "data"
    / "insights"
    / "operations_story.json"
)

EXECUTIVE_VALIDATION_PATH = (
    PROJECT_ROOT
    / "data"
    / "insights"
    / "executive_validation.json"
)

OPERATIONS_VALIDATION_PATH = (
    PROJECT_ROOT
    / "data"
    / "insights"
    / "operations_validation.json"
)

SCENARIO_ENGINE_PATH = (
    PROJECT_ROOT
    / "data"
    / "scenarios"
    / "scenario_engine_results.json"
)

SCENARIO_EVALUATION_PATH = (
    PROJECT_ROOT
    / "data"
    / "scenarios"
    / "scenario_evaluation.json"
)

ENGINE_EVALUATION_PATH = (
    PROJECT_ROOT
    / "data"
    / "scenarios"
    / "engine_evaluation.json"
)

SPARSE_HISTORY_PATH = (
    PROJECT_ROOT
    / "data"
    / "scenarios"
    / "sparse_history_scenario.json"
)

CAUSAL_RESULT_PATH = (
    PROJECT_ROOT
    / "data"
    / "causal"
    / "delivery_review_causal_effect.json"
)

CAUSAL_DIAGNOSTICS_PATH = (
    PROJECT_ROOT
    / "data"
    / "causal"
    / "causal_diagnostics.json"
)

CAUSAL_STATUS_PATH = (
    PROJECT_ROOT
    / "data"
    / "causal"
    / "causal_production_status.json"
)

CALIBRATION_PATH = (
    PROJECT_ROOT
    / "data"
    / "feedback"
    / "calibration_report.json"
)

# ============================================================
# DATABASE HELPERS
# ============================================================

def connect_database():
    """
    Return a read-write DuckDB connection.

    Feedback endpoints need a writable connection because they
    create/insert feedback records. Analytical endpoints can use
    get_connection() below for read-only access.
    """

    if not DB_PATH.exists():
        raise HTTPException(
            status_code=500,
            detail=f"DuckDB database not found: {DB_PATH}",
        )

    try:
        return duckdb.connect(
            str(DB_PATH),
            read_only=False,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not open DuckDB: {exc}",
        )


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="BusinessIntelligence.ai",
    description=(
        "KPI intelligence-to-action API"
    ),
    version="1.0.0",
)


@app.get("/api/insights/role")
def role_based_insight(
    role: str = Query(
        "executive",
        description=(
            "Allowed values: executive, operations, analyst"
        ),
    )
):

    allowed_roles = {
        "executive",
        "operations",
        "analyst",
    }

    role = role.lower().strip()

    if role not in allowed_roles:

        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid role. "
                "Use: executive, operations, analyst."
            ),
        )

    insight = read_json(
        INSIGHT_PATH
    )

    causal_status = None

    if CAUSAL_PATH.exists():

        causal_status = read_json(
            CAUSAL_PATH
        )

    filtered_view = build_role_view(
        insight,
        role,
        causal_status,
    )

    return make_json_safe(
        filtered_view
    )


@app.get("/api/security/test")
def security_test():

    insight = read_json(
        INSIGHT_PATH
    )

    causal_status = None

    if CAUSAL_PATH.exists():

        causal_status = read_json(
            CAUSAL_PATH
        )

    results = {}

    for role in [
        "executive",
        "operations",
        "analyst",
    ]:

        filtered = build_role_view(
            insight,
            role,
            causal_status,
        )

        results[role] = {

            "visible_sections":
                [
                    key
                    for key in filtered
                    if not key.startswith("_")
                ],

            "restricted_fields":
                filtered[
                    "_security"
                ][
                    "restricted_fields"
                ],
        }

    return make_json_safe(
        {
            "security_model":
                "application-level role filtering",

            "roles":
                results,
        }
    )

# ============================================================
# HELPERS
# ============================================================

def make_json_safe(value):
    """
    Convert pandas / NumPy / DuckDB values into
    standard JSON-serializable Python values.
    """

    if value is None:
        return None

    # datetime / date
    if isinstance(value, (datetime, date)):
        return value.isoformat()

    # float NaN / infinity
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value

    # pandas Timestamp / NumPy scalar support without
    # requiring direct NumPy imports.
    if hasattr(value, "item"):
        try:
            return make_json_safe(
                value.item()
            )
        except Exception:
            pass

    # pandas Timestamp-like objects
    if hasattr(value, "isoformat") and not isinstance(value, str):
        try:
            return value.isoformat()
        except Exception:
            pass

    # dictionaries
    if isinstance(value, dict):
        return {
            str(key): make_json_safe(val)
            for key, val in value.items()
        }

    # lists / tuples
    if isinstance(value, (list, tuple)):
        return [
            make_json_safe(item)
            for item in value
        ]

    # fallback
    return value


class FeedbackRequest(BaseModel):

    role: str

    event_id: str

    event_start_date: Optional[str] = None

    event_end_date: Optional[str] = None

    driver_type: str

    driver: str

    predicted_status: str

    predicted_confidence: float

    predicted_decision: Optional[str] = None

    feedback_label: str

    corrected_driver: Optional[str] = None

    correction_text: Optional[str] = None


@app.post("/api/feedback")
def submit_feedback(
    feedback: FeedbackRequest
):

    con = connect_database()

    try:

        ensure_feedback_table(
            con
        )

        feedback_id = capture_feedback(
            con,

            role=feedback.role,

            event_id=feedback.event_id,

            event_start_date=(
                feedback.event_start_date
            ),

            event_end_date=(
                feedback.event_end_date
            ),

            driver_type=(
                feedback.driver_type
            ),

            driver=(
                feedback.driver
            ),

            predicted_status=(
                feedback.predicted_status
            ),

            predicted_confidence=(
                feedback.predicted_confidence
            ),

            predicted_decision=(
                feedback.predicted_decision
            ),

            feedback_label=(
                feedback.feedback_label
            ),

            corrected_driver=(
                feedback.corrected_driver
            ),

            correction_text=(
                feedback.correction_text
            ),
        )

        return make_json_safe(
            {
                "success": True,
                "feedback_id": feedback_id,
                "message": "Feedback recorded successfully.",
            }
        )

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:

        print(
            f"[ERROR] /api/feedback POST: {exc}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )

    finally:

        con.close()


@app.get("/api/feedback")
def get_feedback():

    con = connect_database()

    try:

        ensure_feedback_table(
            con
        )

        df = load_feedback(
            con
        )

        records = (
            df.to_dict(
                orient="records"
            )
            if not df.empty
            else []
        )

        return make_json_safe(
            {
                "feedback": records
            }
        )

    except Exception as exc:

        print(
            f"[ERROR] /api/feedback: {exc}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )

    finally:

        con.close()


@app.get("/api/calibration")
def get_calibration():

    con = connect_database()

    try:

        ensure_feedback_table(
            con
        )

        df = load_feedback(
            con
        )

        report = build_calibration_report(
            df
        )

        return make_json_safe(
            report
        )

    except Exception as exc:

        print(
            f"[ERROR] /api/calibration: {exc}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )

    finally:

        con.close()

@app.get("/api/validation/scenarios")
def get_scenario_validation():

    return make_json_safe(
        {
            "engine":
                optional_json_file(
                    SCENARIO_ENGINE_PATH
                ),

            "evaluation":
                optional_json_file(
                    SCENARIO_EVALUATION_PATH
                ),

            "engine_evaluation":
                optional_json_file(
                    ENGINE_EVALUATION_PATH
                ),
        }
    )

@app.get("/api/validation/sparse-history")
def get_sparse_history():

    result = optional_json_file(
        SPARSE_HISTORY_PATH
    )

    if result is None:

        raise HTTPException(
            status_code=404,
            detail="Sparse-history scenario not found.",
        )

    return result

@app.get("/api/validation/causal")
def get_causal_validation():

    return make_json_safe(
        {
            "result":
                optional_json_file(
                    CAUSAL_RESULT_PATH
                ),

            "diagnostics":
                optional_json_file(
                    CAUSAL_DIAGNOSTICS_PATH
                ),

            "production_status":
                optional_json_file(
                    CAUSAL_STATUS_PATH
                ),
        }
    )

@app.get("/api/validation/feedback")
def get_feedback_validation():

    result = optional_json_file(
        CALIBRATION_PATH
    )

    if result is None:

        raise HTTPException(
            status_code=404,
            detail="Calibration report not found.",
        )

    return result



def get_connection():

    if not DB_PATH.exists():

        raise HTTPException(
            status_code=500,
            detail=(
                "DuckDB database not found."
            ),
        )

    return duckdb.connect(
        str(DB_PATH),
        read_only=True,
    )


def read_json(path):

    if not path.exists():

        raise HTTPException(
            status_code=404,
            detail=f"File not found: {path.name}",
        )

    try:

        return make_json_safe(
            json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
        )

    except json.JSONDecodeError:

        raise HTTPException(
            status_code=500,
            detail=f"Invalid JSON: {path.name}",
        )

def optional_json_file(path):
    """
    Return JSON contents when available.
    Return None when the artifact does not exist.
    """

    if not path.exists():
        return None

    try:
        return make_json_safe(
            json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
        )

    except Exception as exc:

        print(
            f"[ERROR] Could not read {path}: {exc}"
        )

        return None



def sanitize_value(value):
    """
    Convert values returned by Pandas/DuckDB into strict JSON-safe
    Python values.

    NaN and Infinity are converted to None.
    """

    if value is None:
        return None

    # Handle floats, including NaN and +/- infinity.
    if isinstance(value, float):

        if not math.isfinite(value):
            return None

        return value

    # Handle nested dictionaries.
    if isinstance(value, dict):

        return {
            key: sanitize_value(val)
            for key, val in value.items()
        }

    # Handle lists/tuples.
    if isinstance(value, (list, tuple)):

        return [
            sanitize_value(item)
            for item in value
        ]

    return value


def dataframe_records(df):
    """
    Convert a DuckDB/Pandas DataFrame to JSON-safe records.
    """

    records = df.to_dict(
        orient="records"
    )

    return sanitize_value(
        records
    )


# ============================================================
# HEALTH
# ============================================================

@app.get("/api/health")
def health():

    return {
        "status": "ok",
        "service": "BusinessIntelligence.ai",
    }


# ============================================================
# LATEST INSIGHT
# ============================================================

@app.get("/api/insights/latest")
def latest_insight():

    return make_json_safe(
        read_json(
            INSIGHT_PATH
        )
    )


# ============================================================
# EXECUTIVE STORY
# ============================================================

@app.get("/api/insights/latest/executive")
def executive_story():

    return make_json_safe(
        read_json(
            EXECUTIVE_STORY_PATH
        )
    )


# ============================================================
# OPERATIONS STORY
# ============================================================

@app.get("/api/insights/latest/operations")
def operations_story():

    return make_json_safe(
        read_json(
            OPERATIONS_STORY_PATH
        )
    )


# ============================================================
# VALIDATION
# ============================================================

@app.get("/api/insights/latest/validation")
def validation():

    executive = read_json(
        EXECUTIVE_VALIDATION_PATH
    )

    operations = read_json(
        OPERATIONS_VALIDATION_PATH
    )

    return make_json_safe(
        {
            "executive": executive,
            "operations": operations,
        }
    )


# ============================================================
# KPI LIST
# ============================================================

@app.get("/api/kpis")
def kpis():

    con = get_connection()

    try:

        tables = con.execute(
            """
            SELECT
                table_name
            FROM information_schema.tables
            WHERE
                table_schema = 'main'
            ORDER BY
                table_name;
            """
        ).fetchall()

        table_names = [
            row[0]
            for row in tables
        ]

        return {
            "available_tables":
                table_names,
        }

    finally:

        con.close()


# ============================================================
# EVENTS
# ============================================================

@app.get("/api/events")
def events(
    limit: int = 20,
):

    limit = max(
        1,
        min(
            limit,
            100,
        ),
    )

    con = get_connection()

    try:

        result = con.execute(
            f"""
            SELECT

                event_group,

                event_start_date,

                event_end_date,

                anomalous_days,

                direction,

                event_type,

                investigation_priority,

                peak_change_abs,

                cumulative_absolute_impact,

                peak_z_score,

                coverage_status,

                event_priority_score

            FROM fact_gmv_events

            ORDER BY
                event_priority_score DESC,
                event_start_date DESC

            LIMIT {limit};
            """
        ).fetchdf()

        return {
            "count":
                len(result),

            "events":
                dataframe_records(
                    result
                ),
        }

    finally:

        con.close()


# ============================================================
# DRIVERS
# ============================================================

@app.get("/api/drivers")
def drivers(
    event_id: int | None = None,
):

    con = get_connection()

    try:

        if event_id is None:

            result = con.execute(
                """
                SELECT

                    event_id,

                    driver_type,

                    driver,

                    ROUND(
                        gmv_change,
                        2
                    ) AS gmv_change,

                    ROUND(
                        contribution_share,
                        4
                    ) AS contribution_share,

                    ROUND(
                        confidence,
                        3
                    ) AS confidence,

                    final_status,

                    decision

                FROM fact_driver_confidence

                ORDER BY
                    confidence DESC,
                    ABS(
                        contribution_share
                    ) DESC

                LIMIT 100;
                """
            ).fetchdf()

        else:

            result = con.execute(
                """
                SELECT

                    event_id,

                    driver_type,

                    driver,

                    ROUND(
                        gmv_change,
                        2
                    ) AS gmv_change,

                    ROUND(
                        contribution_share,
                        4
                    ) AS contribution_share,

                    ROUND(
                        confidence,
                        3
                    ) AS confidence,

                    final_status,

                    decision

                FROM fact_driver_confidence

                WHERE
                    event_id = ?

                ORDER BY
                    confidence DESC,
                    ABS(
                        contribution_share
                    ) DESC;
                """,
                [event_id],
            ).fetchdf()

        return {
            "count":
                len(result),

            "drivers":
                dataframe_records(
                    result
                ),
        }
    finally:

        con.close()


# ============================================================
# ACTIONS
# ============================================================

@app.get("/api/actions")
def actions(
    event_id: int | None = None,
):

    con = get_connection()

    try:

        if event_id is None:

            result = con.execute(
                """
                SELECT

                    event_id,

                    driver_type,

                    driver,

                    contribution_share,

                    confidence,

                    evidence_status,

                    decision,

                    controllable_lever,

                    action,

                    owner,

                    monitoring_plan

                FROM fact_recommended_actions

                ORDER BY
                    confidence DESC

                LIMIT 100;
                """
            ).fetchdf()

        else:

            result = con.execute(
                """
                SELECT

                    event_id,

                    driver_type,

                    driver,

                    contribution_share,

                    confidence,

                    evidence_status,

                    decision,

                    controllable_lever,

                    action,

                    owner,

                    monitoring_plan

                FROM fact_recommended_actions

                WHERE
                    event_id = ?

                ORDER BY
                    confidence DESC;
                """,
                [event_id],
            ).fetchdf()

        return {
            "count":
                len(result),

            "actions":
                dataframe_records(
                    result
                ),
        }

    finally:

        con.close()


# ============================================================
# TELEMETRY
# ============================================================

@app.get("/api/telemetry")
def telemetry():

    executive = read_json(
        EXECUTIVE_STORY_PATH
    )

    operations = read_json(
        OPERATIONS_STORY_PATH
    )

    executive_validation = read_json(
        EXECUTIVE_VALIDATION_PATH
    )

    operations_validation = read_json(
        OPERATIONS_VALIDATION_PATH
    )

    return make_json_safe({

        "executive":
            executive.get(
                "telemetry",
                {}
            ),

        "operations":
            operations.get(
                "telemetry",
                {}
            ),

        "validation": {

            "executive_passed":
                executive_validation.get(
                    "passed",
                    False
                ),

            "operations_passed":
                operations_validation.get(
                    "passed",
                    False
                ),
        },
    })


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():

    return {
        "application":
            "BusinessIntelligence.ai",

        "status":
            "running",

        "documentation":
            "/docs",
    }
