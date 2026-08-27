from pathlib import Path
import json
import math

import duckdb

from fastapi import FastAPI, HTTPException


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


# ============================================================
# HELPERS
# ============================================================

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

        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except json.JSONDecodeError:

        raise HTTPException(
            status_code=500,
            detail=f"Invalid JSON: {path.name}",
        )
        
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

    return read_json(
        INSIGHT_PATH
    )


# ============================================================
# EXECUTIVE STORY
# ============================================================

@app.get("/api/insights/latest/executive")
def executive_story():

    return read_json(
        EXECUTIVE_STORY_PATH
    )


# ============================================================
# OPERATIONS STORY
# ============================================================

@app.get("/api/insights/latest/operations")
def operations_story():

    return read_json(
        OPERATIONS_STORY_PATH
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

    return {
        "executive": executive,
        "operations": operations,
    }


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

    return {

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
    }


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