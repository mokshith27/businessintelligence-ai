"""Tests for the back-tested business-impact (ROI) estimator.

The estimator needs the DuckDB warehouse, so warehouse-dependent tests
are skipped on fresh clones / CI until the pipeline has been run.
"""

from pathlib import Path

import pytest

from roi.roi_estimator import (
    ACTIONABLE_DECISIONS,
    DEFAULT_RECOVERY_RATE,
    MAX_RECOVERY_RATE,
    analyze_event,
    run_backtest,
)

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


def test_actionable_decisions_are_defined():
    assert "INVESTIGATE" in ACTIONABLE_DECISIONS
    assert "ACTION_WITH_VALIDATION" in ACTIONABLE_DECISIONS
    assert "ABSTAIN" not in ACTIONABLE_DECISIONS
    assert "DO_NOT_ACT" not in ACTIONABLE_DECISIONS


def test_recovery_rate_bounds_are_conservative():
    assert 0.0 < DEFAULT_RECOVERY_RATE < MAX_RECOVERY_RATE
    assert MAX_RECOVERY_RATE <= 0.25


@requires_warehouse
def test_analyze_event_flags_negative_event():
    from drivers.event_investigation import connect_database

    con = connect_database()

    try:
        result = analyze_event(
            con,
            66,
        )
    finally:
        con.close()

    assert result["event_id"] == 66
    assert result["at_risk_gmv"] > 0
    assert result["detection_lead_days"] == result["anomalous_days"]

    if result["actionable"]:
        assert result["estimated_recoverable_gmv"] == pytest.approx(
            result["at_risk_gmv"] * DEFAULT_RECOVERY_RATE,
            rel=1e-6,
        )
    else:
        assert result["estimated_recoverable_gmv"] == 0.0


@requires_warehouse
def test_backtest_summary_is_self_consistent():
    result = run_backtest(
        event_limit=3,
    )

    summary = result["summary"]

    assert summary["events_analyzed"] >= 1
    assert summary["events_analyzed"] == (
        summary["actionable_events"]
        + summary["abstained_events"]
    )

    # Recoverable value can never exceed at-risk value.
    assert (
        summary["estimated_recoverable_gmv"]
        <= summary["total_at_risk_gmv"]
    )

    assert (
        summary["estimated_recoverable_gmv_upper"]
        >= summary["estimated_recoverable_gmv"]
    )

    # Every event carries its assumptions for auditability.
    assert "recovery_rate" in result["assumptions"]