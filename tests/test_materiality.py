"""Tests for materiality / event-clustering decisions.

These checks validate the analytical invariants. The warehouse-backed
builders are skipped on a fresh clone / CI until the pipeline has run;
the invariant helpers are pure and always run.
"""

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

WAREHOUSE_PATH = (
    PROJECT_ROOT
    / "data"
    / "warehouse"
    / "businessintelligence.duckdb"
)

requires_warehouse = pytest.mark.skipif(
    not WAREHOUSE_PATH.exists(),
    reason=(
        "DuckDB warehouse not found; run the analytical pipeline first"
    ),
)


@requires_warehouse
def test_materiality_table_exists_and_is_nonempty():
    from materiality.materiality_engine import connect_database

    con = connect_database()
    try:
        tables = [
            r[0]
            for r in con.execute("SHOW TABLES").fetchall()
        ]
        assert "fact_gmv_materiality" in tables

        count = con.execute(
            "SELECT COUNT(*) FROM fact_gmv_materiality"
        ).fetchone()[0]
        assert int(count) > 0
    finally:
        con.close()


@requires_warehouse
def test_events_table_has_detected_events():
    from drivers.event_investigation import connect_database

    con = connect_database()
    try:
        count = con.execute(
            "SELECT COUNT(*) FROM fact_gmv_events"
        ).fetchone()[0]
        assert int(count) >= 1
    finally:
        con.close()


@requires_warehouse
def test_negative_events_identified_with_impact():
    import duckdb

    from roi.roi_estimator import (
        connect_database as roi_connect,
    )

    con = roi_connect()
    try:
        negative = con.execute(
            """
            SELECT COUNT(*)
            FROM fact_gmv_events
            WHERE direction = 'NEGATIVE'
            """
        ).fetchone()[0]
        # There should be at least one negative event worth examining.
        assert int(negative) >= 1
    finally:
        con.close()


def test_materiality_publication_shape_is_json_safe():
    """A pure structural check: the published insight event block is JSON-safe."""
    import json
    from pathlib import Path

    insight_path = (
        PROJECT_ROOT
        / "data"
        / "insights"
        / "latest_insight.json"
    )

    if not insight_path.exists():
        pytest.skip("latest_insight.json not found; pipeline not run")

    insight = json.loads(
        insight_path.read_text(encoding="utf-8")
    )

    event = insight["event"]
    assert "event_id" in event
    assert "direction" in event
    assert event["direction"] in {"POSITIVE", "NEGATIVE"}
    assert "cumulative_absolute_impact" in event
    assert isinstance(event["cumulative_absolute_impact"], (int, float))