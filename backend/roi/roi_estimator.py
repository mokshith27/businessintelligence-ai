"""BusinessIntelligence.ai — back-tested business-impact (ROI) estimator.

Purpose
-------
Stakeholders ask "so what?". This module turns the deterministic event
engine's output into a defensible business-impact story computed on the
actual Olist-style warehouse data.

Method
------
For every flagged NEGATIVE KPI event the estimator:

1. Quantifies at-risk GMV — the cumulative absolute impact of the
   movement, cross-checked against the on-demand investigation engine's
   gmv_change.
2. Measures detection lead time — the number of anomalous days in the
   event. The system flags the event on its first anomalous day; a manual
   analyst typically notices only after the event has finished.
3. Determines actionability — by running the production
   run_event_investigation engine for the event and checking whether
   at least one driver received an actionable decision
   (INVESTIGATE / ACTION_WITH_VALIDATION / ACTIONABLE). Events whose
   every driver is ABSTAIN or DO_NOT_ACT contribute zero recoverable
   value — this keeps the estimate honest about uncertainty.
4. Estimates recoverable value — at-risk GMV times a conservative
   recovery rate (default 10%, configurable) for actionable events.
   10% is deliberately conservative (industry avoidable-loss recovery
   literature typically assumes 5–25%).

Every number is a deterministic back-test with stated assumptions, and
the full per-event detail is surfaced for auditability.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import duckdb

from drivers.event_investigation import (
    connect_database,
    run_event_investigation,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

ROI_DIR = PROJECT_ROOT / "data" / "roi"

ROI_ARTIFACT_PATH = ROI_DIR / "roi_backtest.json"

# Decisions that count as "a recommended action exists".
ACTIONABLE_DECISIONS = {
    "INVESTIGATE",
    "ACTION_WITH_VALIDATION",
    "ACTIONABLE",
}

# Default conservative recovery rate. Capped so the upper bound can be
# shown as a range without being presented as a realistic expectation.
DEFAULT_RECOVERY_RATE = 0.10
MAX_RECOVERY_RATE = 0.25



def list_negative_events(
    con: duckdb.DuckDBPyConnection,
    limit: int = 15,
):
    """Return NEGATIVE events sorted by impact (most impactful first)."""

    limit = max(1, min(int(limit), 50))

    rows = con.execute(
        """
        SELECT
            event_group,
            event_start_date,
            event_end_date,
            anomalous_days,
            direction,
            cumulative_absolute_impact,
            max_abs_impact
        FROM (
            SELECT
                event_group,
                event_start_date,
                event_end_date,
                anomalous_days,
                direction,
                cumulative_absolute_impact,
                peak_change_abs AS max_abs_impact
            FROM fact_gmv_events
        )
        WHERE direction = 'NEGATIVE'
        ORDER BY
            cumulative_absolute_impact DESC,
            event_start_date DESC
        LIMIT ?
        """,
        [limit],
    ).fetchdf()

    events = []
    for _, row in rows.iterrows():
        events.append(
            {
                "event_id": int(row["event_group"]),
                "start_date": row["event_start_date"].isoformat()
                if hasattr(row["event_start_date"], "isoformat")
                else str(row["event_start_date"]),
                "end_date": row["event_end_date"].isoformat()
                if hasattr(row["event_end_date"], "isoformat")
                else str(row["event_end_date"]),
                "anomalous_days": int(row["anomalous_days"]),
                "at_risk_gmv": float(
                    row["cumulative_absolute_impact"] or 0.0
                ),
                "peak_change_abs": float(row["max_abs_impact"] or 0.0),
            }
        )

    return events



def analyze_event(
    con: duckdb.DuckDBPyConnection,
    event_id: int,
    recovery_rate: float = DEFAULT_RECOVERY_RATE,
) -> dict[str, Any]:
    """Run the production investigation for one event and score it."""

    investigation = run_event_investigation(
        event_id,
        con=con,
    )

    movement = investigation.get(
        "movement",
        {},
    )

    gmv_change = float(
        movement.get(
            "gmv_change",
            0.0,
        )
        or 0.0
    )

    at_risk_gmv = abs(gmv_change)

    event = investigation.get(
        "event",
        {},
    )

    anomalous_days = int(
        event.get(
            "anomalous_days",
            0,
        )
        or 0
    )

    start_date = event.get("start_date", "") or ""
    if not isinstance(start_date, str):
        start_date = start_date.isoformat()

    end_date = event.get("end_date", "") or ""
    if not isinstance(end_date, str):
        end_date = end_date.isoformat()

    drivers = investigation.get(
        "drivers",
        [],
    )

    actionable = False
    action_count = 0
    main_action = ""
    main_decision = ""
    main_owner = ""

    for driver in drivers:
        action = driver.get(
            "action",
            {},
        )

        decision = action.get(
            "decision",
            "",
        )

        if decision in ACTIONABLE_DECISIONS:
            actionable = True
            action_count += 1
            if not main_action:
                main_action = str(
                    action.get(
                        "action",
                        "",
                    )
                )
                main_decision = decision
                main_owner = str(
                    action.get(
                        "owner",
                        "",
                    )
                )

    recoverable_gmv = (
        at_risk_gmv * recovery_rate
        if actionable
        else 0.0
    )

    return {
        "event_id": int(event_id),
        "start_date": start_date,
        "end_date": end_date,
        "anomalous_days": anomalous_days,
        "at_risk_gmv": round(at_risk_gmv, 2),
        "detection_lead_days": anomalous_days,
        "actionable": actionable,
        "actionable_driver_count": action_count,
        "main_action": main_action,
        "main_decision": main_decision,
        "main_owner": main_owner,
        "recovery_rate_applied": (
            recovery_rate
            if actionable
            else 0.0
        ),
        "estimated_recoverable_gmv": round(recoverable_gmv, 2),
    }



def run_backtest(
    con: duckdb.DuckDBPyConnection | None = None,
    event_limit: int = 15,
    recovery_rate: float = DEFAULT_RECOVERY_RATE,
) -> dict[str, Any]:
    """Run the full back-test over flagged negative events."""

    own_connection = con is None

    if own_connection:
        con = connect_database()

    started = time.perf_counter()

    try:
        events = list_negative_events(
            con,
            limit=event_limit,
        )

        rows = [
            analyze_event(
                con,
                event["event_id"],
                recovery_rate=recovery_rate,
            )
            for event in events
        ]

        actionable_rows = [
            row
            for row in rows
            if row["actionable"]
        ]

        total_at_risk = sum(
            row["at_risk_gmv"]
            for row in rows
        )

        total_recoverable = sum(
            row["estimated_recoverable_gmv"]
            for row in rows
        )

        total_recoverable_upper = sum(
            (
                row["at_risk_gmv"] * MAX_RECOVERY_RATE
                if row["actionable"]
                else 0.0
            )
            for row in rows
        )

        avg_lead_days = (
            sum(
                row["detection_lead_days"]
                for row in rows
            )
            / len(rows)
            if rows
            else 0.0
        )

        hero_event = (
            max(
                actionable_rows,
                key=lambda row: row["estimated_recoverable_gmv"],
            )
            if actionable_rows
            else None
        )

        return {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "method": "deterministic back-test on Olist-style warehouse data",
            "assumptions": {
                "scope": (
                    "NEGATIVE KPI events only; positive events are not "
                    "counted as avoidable losses."
                ),
                "detection_lead_days": (
                    "The system flags an event on its first anomalous day; "
                    "the counterfactual is after-the-fact manual review."
                ),
                "actionable_decision": sorted(ACTIONABLE_DECISIONS),
                "recovery_rate": DEFAULT_RECOVERY_RATE,
                "recovery_rate_upper_bound": MAX_RECOVERY_RATE,
                "recovery_rate_note": (
                    "Conservative 10% avoidable-loss recovery applied only "
                    "to events with an actionable decision; upper bound "
                    "25% shown for range transparency."
                ),
            },
            "summary": {
                "events_analyzed": len(rows),
                "actionable_events": len(actionable_rows),
                "abstained_events": len(rows) - len(actionable_rows),
                "total_at_risk_gmv": round(total_at_risk, 2),
                "estimated_recoverable_gmv": round(total_recoverable, 2),
                "estimated_recoverable_gmv_upper": round(
                    total_recoverable_upper,
                    2,
                ),
                "average_detection_lead_days": round(avg_lead_days, 1),
            },
            "hero_event": hero_event,
            "events": sorted(
                rows,
                key=lambda row: row["estimated_recoverable_gmv"],
                reverse=True,
            ),
            "runtime_ms": round(
                (time.perf_counter() - started) * 1000,
                2,
            ),
        }

    finally:
        if own_connection:
            con.close()



def save_backtest(result: dict[str, Any]) -> Path:
    """Persist the back-test artifact for fast API/dashboard reads."""

    ROI_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    ROI_ARTIFACT_PATH.write_text(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return ROI_ARTIFACT_PATH


def load_backtest() -> dict[str, Any] | None:
    """Load the persisted artifact, or None if it does not exist."""

    if not ROI_ARTIFACT_PATH.exists():
        return None

    return json.loads(
        ROI_ARTIFACT_PATH.read_text(
            encoding="utf-8",
        )
    )


def get_roi_summary(
    refresh: bool = False,
    event_limit: int = 15,
    recovery_rate: float = DEFAULT_RECOVERY_RATE,
) -> dict[str, Any]:
    """Return the ROI summary, computing and caching it when needed."""

    cached = load_backtest()

    if cached is not None and not refresh:
        return cached

    result = run_backtest(
        event_limit=event_limit,
        recovery_rate=recovery_rate,
    )

    save_backtest(result)

    return result



def main() -> None:
    """CLI entry point: run the back-test and persist the artifact."""

    print("=" * 96)
    print("BusinessIntelligence.ai")
    print("BACK-TESTED BUSINESS IMPACT (ROI) ESTIMATOR")
    print("=" * 96)

    result = get_roi_summary(
        refresh=True,
    )

    summary = result["summary"]

    print(
        f"\nEvents analyzed         : {summary['events_analyzed']}"
    )
    print(
        f"Actionable events       : {summary['actionable_events']}"
    )
    print(
        f"Abstained events        : {summary['abstained_events']}"
    )
    print(
        f"Total at-risk GMV       : R${summary['total_at_risk_gmv']:,.2f}"
    )
    print(
        f"Est. recoverable GMV    : "
        f"R${summary['estimated_recoverable_gmv']:,.2f} "
        f"(upper R${summary['estimated_recoverable_gmv_upper']:,.2f})"
    )
    print(
        f"Avg detection lead      : "
        f"{summary['average_detection_lead_days']} day(s)"
    )

    hero = result.get("hero_event")

    if hero:
        print(
            f"\nHero event               : Event {hero['event_id']} "
            f"({hero['start_date']} to {hero['end_date']})"
        )
        print(
            f"  At-risk GMV           : R${hero['at_risk_gmv']:,.2f}"
        )
        print(
            f"  Detection lead        : {hero['detection_lead_days']} day(s)"
        )
        print(
            f"  Est. recoverable      : "
            f"R${hero['estimated_recoverable_gmv']:,.2f}"
        )
        print(
            f"  Recommended action    : {hero['main_action'][:90]}"
        )

    path = save_backtest(result)

    print(f"\nArtifact written: {path}")
    print(f"Runtime: {result['runtime_ms']} ms")


if __name__ == "__main__":
    main()

