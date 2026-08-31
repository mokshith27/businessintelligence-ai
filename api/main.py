from pathlib import Path
import json
import math
import re
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


from drivers.event_investigation import (
    run_event_investigation,
)

from llm.story_generator import (
    generate_event_narratives,
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
# EVENT INVESTIGATION
# ============================================================

# ============================================================
# EVENT INVESTIGATION
# ============================================================

@app.get("/api/insights/event/{event_id}")
def event_investigation(
    event_id: int,
):
    """
    Run the selected event through the same deterministic pipeline
    used by the narrative endpoint.

    Every event is handled identically and calculated on demand.
    """

    try:

        result = run_event_investigation(
            int(event_id)
        )

        return make_json_safe(
            result
        )

    except ValueError as exc:

        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    except HTTPException:
        raise

    except Exception as exc:

        print(
            f"[ERROR] /api/insights/event/{event_id}: {exc}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


# ============================================================
# ON-DEMAND EVENT NARRATIVE
# ============================================================

@app.post("/api/insights/event/{event_id}/narrative")
def event_narrative(
    event_id: int,
):
    """
    Generate and validate an event-specific narrative.

    The deterministic investigation is built ONCE and used for both
    LLM attempts, so the model and validator always see the same facts.

    No event-specific hardcoding exists.
    """

    try:

        investigation = run_event_investigation(
            int(event_id)
        )

        validation_feedback = None
        last_result = None

        # Three validation attempts. A small local model
        # (qwen3:1.7b) occasionally hallucinates a number that is not
        # in the evidence; the validator rejects it and the retry
        # receives the violations as feedback. Two attempts left the
        # dashboard rejection warning too frequent.
        for attempt in range(3):

            narratives = generate_event_narratives(
                investigation,
                validation_feedback,
            )

            executive_story = narratives.get(
                "executive",
                {},
            )

            operations_story = narratives.get(
                "operations",
                {},
            )

            executive_validation = validate_dynamic_story(
                executive_story.get(
                    "story",
                    "",
                ),
                investigation,
                "executive",
            )

            operations_validation = validate_dynamic_story(
                operations_story.get(
                    "story",
                    "",
                ),
                investigation,
                "operations",
            )

            overall_passed = (
                executive_validation.get(
                    "available",
                    False,
                )
                and
                operations_validation.get(
                    "available",
                    False,
                )
                and
                executive_validation.get(
                    "passed",
                    False,
                )
                and
                operations_validation.get(
                    "passed",
                    False,
                )
            )

            last_result = {
                "event_id":
                    int(event_id),

                "event":
                    investigation.get(
                        "event",
                        {},
                    ),

                "executive": {
                    "story":
                        executive_story.get(
                            "story",
                            "",
                        ),

                    "telemetry":
                        executive_story.get(
                            "telemetry",
                            {},
                        ),

                    "validation":
                        executive_validation,
                },

                "operations": {
                    "story":
                        operations_story.get(
                            "story",
                            "",
                        ),

                    "telemetry":
                        operations_story.get(
                            "telemetry",
                            {},
                        ),

                    "validation":
                        operations_validation,
                },

                "validation": {
                    "passed":
                        overall_passed,

                    "executive_passed":
                        executive_validation.get(
                            "passed",
                            False,
                        ),

                    "operations_passed":
                        operations_validation.get(
                            "passed",
                            False,
                        ),

                    "validator_available":
                        (
                            executive_validation.get(
                                "available",
                                False,
                            )
                            and
                            operations_validation.get(
                                "available",
                                False,
                            )
                        ),

                    "attempts":
                        attempt + 1,
                },

                "source":
                    "selected_event_dynamic_investigation",

                "persisted":
                    False,
            }

            if overall_passed:

                return make_json_safe(
                    last_result
                )

            validation_feedback = {
                "executive":
                    executive_validation,

                "operations":
                    operations_validation,
            }

        return make_json_safe(
            last_result
        )

    except ValueError as exc:

        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    except HTTPException:
        raise

    except Exception as exc:

        error_text = str(exc)

        # Groq/OpenAI-compatible providers use 429 for rate limits.
        # Surface this honestly instead of hiding it as a backend 500.
        if (
            "429" in error_text
            or "rate_limit_exceeded" in error_text
            or "tokens per day" in error_text
            or "tokens per minute" in error_text
        ):

            retry_match = re.search(
                r"try again in ([^.]*)",
                error_text,
                flags=re.IGNORECASE,
            )

            retry_hint = (
                retry_match.group(1)
                if retry_match
                else "a short while"
            )

            raise HTTPException(
                status_code=429,
                detail=(
                    "LLM provider rate limit reached. "
                    f"Retry after approximately {retry_hint}. "
                    "No deterministic investigation data was lost."
                ),
            )

        print(
            f"[ERROR] /api/insights/event/"
            f"{event_id}/narrative: {exc}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


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
                    final_status
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
                    final_status
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



def validate_dynamic_story(
    story: str,
    investigation: dict,
    persona: str,
) -> dict:
    """
    Run the project's actual narrative validator.

    The validator is located at:
        llm/narrative_validator.py

    and exposes:
        validate_story(story, insight, persona)
    """

    try:

        from llm.narrative_validator import (
            validate_story,
        )

    except Exception as exc:

        return {
            "available":
                False,

            "passed":
                False,

            "persona":
                persona,

            "error":
                (
                    "Could not import "
                    "llm.narrative_validator.validate_story: "
                    f"{exc}"
                ),
        }

    try:

        result = validate_story(
            story,
            investigation,
            persona,
        )

        return {
            "available":
                True,

            **result,
        }

    except Exception as exc:

        return {
            "available":
                True,

            "passed":
                False,

            "persona":
                persona,

            "error":
                str(exc),
        }


# ============================================================
# CUSTOMER EXPERIENCE KPIs
# ============================================================

@app.get("/api/customer-experience-kpis")
def customer_experience_kpis(
    event_id: int | None = None,
):
    """
    Return event-period and comparison-period values for:

        1. Late Delivery Rate
        2. Review Score

    Event dates are resolved from fact_gmv_events.
    Late delivery rate is:

        late delivered orders / delivered orders

    where delivery_delay_days > 0 identifies a late delivery.

    Review score is the average review_score by
    review_creation_date for the corresponding periods.
    """

    con = get_connection()

    try:

        # ----------------------------------------------------
        # Resolve the event window.
        # fact_gmv_events stores the event identifier as event_group.
        # ----------------------------------------------------

        if event_id is None:

            event_row = con.execute(
                """
                SELECT
                    event_group,
                    event_start_date,
                    event_end_date
                FROM fact_gmv_events
                ORDER BY
                    event_priority_score DESC,
                    event_start_date DESC
                LIMIT 1;
                """
            ).fetchone()

        else:

            event_row = con.execute(
                """
                SELECT
                    event_group,
                    event_start_date,
                    event_end_date
                FROM fact_gmv_events
                WHERE
                    event_group = ?
                LIMIT 1;
                """,
                [event_id],
            ).fetchone()

        if event_row is None:

            raise HTTPException(
                status_code=404,
                detail=(
                    f"Event {event_id} not found."
                    if event_id is not None
                    else "No KPI event found."
                ),
            )

        resolved_event_id = event_row[0]
        event_start = event_row[1]
        event_end = event_row[2]

        from datetime import timedelta

        event_end_exclusive = (
            event_end + timedelta(days=1)
        )

        # ----------------------------------------------------
        # Event end date is inclusive in fact_gmv_events.
        # Therefore duration is start -> event_end + 1.
        # ----------------------------------------------------

        duration_days = con.execute(
            """
            SELECT
                date_diff(
                    'day',
                    CAST(? AS DATE),
                    CAST(? AS DATE)
                ) + 1;
            """,
            [event_start, event_end],
        ).fetchone()[0]

        if duration_days is None or duration_days <= 0:
            duration_days = 1

        comparison_start = con.execute(
            """
            SELECT
                CAST(? AS DATE) - (? * INTERVAL '1 day');
            """,
            [event_start, duration_days],
        ).fetchone()[0]

        comparison_end = event_start

        # ----------------------------------------------------
        # Late-delivery rate
        # ----------------------------------------------------

        late_delivery = con.execute(
            """
            SELECT

                SUM(
                    CASE
                        WHEN
                            order_delivered_customer_date IS NOT NULL
                            AND delivery_delay_days > 0
                        THEN 1
                        ELSE 0
                    END
                )::DOUBLE
                /
                NULLIF(
                    SUM(
                        CASE
                            WHEN
                                order_delivered_customer_date IS NOT NULL
                            THEN 1
                            ELSE 0
                        END
                    ),
                    0
                ) AS current_rate,

                SUM(
                    CASE
                        WHEN
                            order_delivered_customer_date IS NOT NULL
                            AND delivery_delay_days > 0
                        THEN 1
                        ELSE 0
                    END
                ) AS current_late_orders,

                SUM(
                    CASE
                        WHEN
                            order_delivered_customer_date IS NOT NULL
                        THEN 1
                        ELSE 0
                    END
                ) AS current_delivered_orders

            FROM fact_orders_enriched

            WHERE
                order_purchase_timestamp >= ?
                AND order_purchase_timestamp < ?;
            """,
            [event_start, event_end_exclusive],
        ).fetchone()

        previous_late_delivery = con.execute(
            """
            SELECT

                SUM(
                    CASE
                        WHEN
                            order_delivered_customer_date IS NOT NULL
                            AND delivery_delay_days > 0
                        THEN 1
                        ELSE 0
                    END
                )::DOUBLE
                /
                NULLIF(
                    SUM(
                        CASE
                            WHEN
                                order_delivered_customer_date IS NOT NULL
                            THEN 1
                            ELSE 0
                        END
                    ),
                    0
                ) AS previous_rate,

                SUM(
                    CASE
                        WHEN
                            order_delivered_customer_date IS NOT NULL
                            AND delivery_delay_days > 0
                        THEN 1
                        ELSE 0
                    END
                ) AS previous_late_orders,

                SUM(
                    CASE
                        WHEN
                            order_delivered_customer_date IS NOT NULL
                        THEN 1
                        ELSE 0
                    END
                ) AS previous_delivered_orders

            FROM fact_orders_enriched

            WHERE
                order_purchase_timestamp >= ?
                AND order_purchase_timestamp < ?;
            """,
            [comparison_start, comparison_end],
        ).fetchone()

        current_delivery_rate = (
            float(late_delivery[0])
            if late_delivery[0] is not None
            else None
        )

        previous_delivery_rate = (
            float(previous_late_delivery[0])
            if previous_late_delivery[0] is not None
            else None
        )

        delivery_change = (
            current_delivery_rate - previous_delivery_rate
            if (
                current_delivery_rate is not None
                and previous_delivery_rate is not None
            )
            else None
        )

        delivery_change_pp = (
            delivery_change * 100
            if delivery_change is not None
            else None
        )

        # ----------------------------------------------------
        # Review score
        #
        # Use review_creation_date because review_score belongs
        # to the review observation itself.
        # ----------------------------------------------------

        review_row = con.execute(
            """
            SELECT
                AVG(review_score) AS current_score,
                COUNT(*) AS current_reviews
            FROM fact_reviews
            WHERE
                review_creation_date >= ?
                AND review_creation_date < ?;
            """,
            [event_start, event_end],
        ).fetchone()

        previous_review_row = con.execute(
            """
            SELECT
                AVG(review_score) AS previous_score,
                COUNT(*) AS previous_reviews
            FROM fact_reviews
            WHERE
                review_creation_date >= ?
                AND review_creation_date < ?;
            """,
            [comparison_start, comparison_end],
        ).fetchone()

        current_review_score = (
            float(review_row[0])
            if review_row[0] is not None
            else None
        )

        previous_review_score = (
            float(previous_review_row[0])
            if previous_review_row[0] is not None
            else None
        )

        review_score_change = (
            current_review_score - previous_review_score
            if (
                current_review_score is not None
                and previous_review_score is not None
            )
            else None
        )

        return make_json_safe(
            {
                "event_id":
                    int(resolved_event_id),

                "event_period": {
                    "start":
                        event_start,

                    "end":
                        event_end,
                },

                "comparison_period": {
                    "start":
                        comparison_start,

                    "end":
                        comparison_end,
                },

                "late_delivery_rate": {
                    "current":
                        current_delivery_rate,

                    "previous":
                        previous_delivery_rate,

                    "change":
                        delivery_change,

                    "change_pp":
                        delivery_change_pp,

                    "current_late_orders":
                        late_delivery[1],

                    "current_delivered_orders":
                        late_delivery[2],

                    "previous_late_orders":
                        previous_late_delivery[1],

                    "previous_delivered_orders":
                        previous_late_delivery[2],
                },

                "review_score": {
                    "current":
                        current_review_score,

                    "previous":
                        previous_review_score,

                    "change":
                        review_score_change,

                    "current_reviews":
                        review_row[1],

                    "previous_reviews":
                        previous_review_row[1],
                },
            }
        )

    except HTTPException:
        raise

    except Exception as exc:

        print(
            f"[ERROR] /api/customer-experience-kpis: {exc}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )

    finally:

        con.close()


# ============================================================
# REVIEW EVIDENCE
# ============================================================

@app.get("/api/review-evidence")
def review_evidence(
    event_id: int | None = None,
):
    """
    Return review evidence from the same dynamic selected-event engine
    used by the dashboard and LLM.
    """

    if event_id is None:

        event_response = events(
            limit=1
        )

        available_events = event_response.get(
            "events",
            [],
        )

        if not available_events:

            return make_json_safe(
                {
                    "event_id":
                        None,

                    "aspect_count":
                        0,

                    "sentiment_record_count":
                        0,

                    "aspect_summary":
                        [],

                    "sentiment_by_aspect":
                        [],
                }
            )

        event_id = int(
            available_events[0][
                "event_group"
            ]
        )

    try:

        investigation = run_event_investigation(
            int(event_id)
        )

        return make_json_safe(
            investigation.get(
                "review_evidence",
                {},
            )
        )

    except ValueError as exc:

        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    except Exception as exc:

        print(
            f"[ERROR] /api/review-evidence: {exc}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


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
# BUSINESS IMPACT (BACK-TESTED ROI)
# ============================================================

@app.get("/api/roi/summary")
def roi_summary(
    refresh: bool = False,
):
    """
    Return the back-tested business-impact (ROI) summary.

    The estimator runs the production event-investigation engine over
    flagged NEGATIVE KPI events and quantifies:

    - at-risk GMV per event (cumulative absolute impact);
    - detection lead time (days the system flags the event earlier
      than after-the-fact manual review);
    - actionability from the evidence-gated decision engine;
    - estimated recoverable GMV under a conservative recovery rate.

    Results are cached to data/roi/roi_backtest.json. Pass
    ?refresh=true to recompute from the warehouse.
    """

    try:

        from roi.roi_estimator import get_roi_summary

        result = get_roi_summary(
            refresh=bool(refresh),
        )

        return make_json_safe(result)

    except FileNotFoundError as exc:

        raise HTTPException(
            status_code=503,
            detail=(
                "Warehouse not found. Run the analytical pipeline "
                f"first: {exc}"
            ),
        )

    except Exception as exc:

        print(f"[ERROR] /api/roi/summary: {exc}")

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


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
