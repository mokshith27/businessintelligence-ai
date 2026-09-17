"""Multi-KPI monitoring — proves the engine generalizes beyond GMV.

Reads ``fact_daily_kpis`` (which already carries gmv, orders, aov,
late_delivery_rate and review_score per day) plus the KPI contracts in
``config/kpi_contracts/*.yaml``, and flags material movements for every
KPI using the same detection logic family as the GMV pipeline:

- current value vs a trailing N-week seasonal baseline
- relative + absolute materiality thresholds from the contract
- z-score anomaly score
- status: NORMAL / WATCH / ALERT

Output is written to ``data/insights/multi_kpi_status.json`` and served
by ``GET /api/kpis/status``.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import duckdb
import yaml

# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DB_PATH = PROJECT_ROOT / "data" / "warehouse" / "businessintelligence.duckdb"

CONTRACTS_DIR = PROJECT_ROOT / "config" / "kpi_contracts"

OUTPUT_PATH = PROJECT_ROOT / "data" / "insights" / "multi_kpi_status.json"

# KPIs monitored by default (id -> table column in fact_daily_kpis)
DEFAULT_KPI_COLUMNS = {
    "gmv": "gmv",
    "orders": "orders",
    "aov": "aov",
    "late_delivery_rate": "late_delivery_rate",
    "review_score": "review_score",
}

# Columns where a higher value is GOOD (so a rising KPI is not an alert)
HIGHER_IS_BETTER = {
    "gmv": True,
    "orders": True,
    "aov": True,
    "late_delivery_rate": False,
    "review_score": True,
}


# ============================================================
# KPI CONTRACTS
# ============================================================


def load_contracts() -> dict[str, dict[str, Any]]:
    """Load every KPI contract YAML, keyed by contract id."""
    contracts: dict[str, dict[str, Any]] = {}
    if not CONTRACTS_DIR.exists():
        return contracts
    for yaml_file in sorted(CONTRACTS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        kpi = (data or {}).get("kpi") or {}
        kpi_id = kpi.get("id")
        if kpi_id:
            contracts[kpi_id] = kpi
    return contracts


def _resolve_contract(
    kpi_id: str,
    contracts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Map a column id to its contract (review_score -> customer_review_score)."""
    if kpi_id in contracts:
        return contracts[kpi_id]
    for contract in contracts.values():
        contract_id = contract.get("id", "")
        if contract_id.endswith(kpi_id) or kpi_id in contract_id:
            return contract
    return {}


# ============================================================
# CORE DETECTION
# ============================================================


def _baseline_stats(values: list[float]) -> tuple[Optional[float], Optional[float]]:
    """Mean and sample std of a baseline window."""
    if len(values) < 2:
        return None, None
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return mean, math.sqrt(variance)


def evaluate_kpi(
    daily_rows: list[tuple],
    column: str,
    materiality: dict[str, float],
    z_threshold: float,
    baseline_weeks: int = 8,
) -> dict[str, Any]:
    """Evaluate one KPI series and return its status record.

    ``daily_rows``: list of (date, value) tuples, ascending by date.
    """
    if not daily_rows:
        return {
            "status": "NO_DATA",
            "latest_value": None,
            "change_pct": None,
            "z_score": None,
            "flagged": False,
            "reason": "no daily rows available",
        }

    latest_date, latest_value = daily_rows[-1]
    latest_value = float(latest_value or 0.0)

    # Previous-day value for the short-term change
    prev_value = float(daily_rows[-2][1] or 0.0) if len(daily_rows) > 1 else None

    # Trailing baseline window (excluding the latest day)
    window_days = baseline_weeks * 7
    baseline_values = [
        float(v or 0.0) for _, v in daily_rows[-(window_days + 1):-1]
    ]
    baseline_mean, baseline_std = _baseline_stats(baseline_values)

    # Relative change vs previous day
    change_pct = None
    if prev_value is not None and prev_value != 0:
        change_pct = (latest_value - prev_value) / abs(prev_value)

    # Z-score vs the baseline window
    z_score = None
    if baseline_mean is not None and baseline_std not in (None, 0):
        z_score = (latest_value - baseline_mean) / baseline_std

    min_rel = float(materiality.get("min_relative_change", 0.10))
    min_abs = float(materiality.get("min_absolute_change", 0.0))

    # Materiality check (short-term movement)
    material = False
    if change_pct is not None:
        material = (
            abs(change_pct) >= min_rel
            and abs(latest_value - (prev_value or 0)) >= min_abs
        )

    # Anomaly check (level shift vs baseline)
    anomalous = z_score is not None and abs(z_score) >= z_threshold

    # For "higher is worse" KPIs a positive movement is adverse; for
    # "higher is better" KPIs a negative movement is adverse.
    adverse = False
    better_up = HIGHER_IS_BETTER.get(column, True)
    if change_pct is not None and material:
        adverse = change_pct > 0 if not better_up else change_pct < 0
    elif anomalous and z_score is not None:
        # Level-shift direction: below the baseline on a higher-is-better
        # KPI is adverse, above the baseline on a lower-is-better KPI is
        # adverse (the day-over-day comparison can be misleading when
        # the previous day is a partial/empty feed).
        adverse = z_score < 0 if better_up else z_score > 0

    flagged = (material or anomalous) and adverse

    if flagged and anomalous:
        status = "ALERT"
    elif flagged or (material and adverse):
        status = "WATCH"
    else:
        status = "NORMAL"

    reason = "insufficient baseline"
    if change_pct is not None and z_score is not None:
        reason = (
            f"change {change_pct:+.2%} (threshold {min_rel:+.0%}), "
            f"z={z_score:.2f} (threshold {z_threshold})"
        )

    return {
        "status": status,
        "latest_value": round(latest_value, 6),
        "latest_date": str(latest_date),
        "previous_value": round(prev_value, 6) if prev_value is not None else None,
        "change_pct": round(change_pct, 6) if change_pct is not None else None,
        "z_score": round(z_score, 4) if z_score is not None else None,
        "baseline_mean": round(baseline_mean, 6) if baseline_mean is not None else None,
        "flagged": flagged,
        "material": material,
        "anomalous": anomalous,
        "adverse": adverse,
        "reason": reason,
    }


def compute_all_kpis(
    db_path: Optional[Path] = None,
    baseline_weeks: int = 8,
    table: str = "fact_daily_kpis",
) -> dict[str, Any]:
    """Evaluate every configured KPI and build the status payload.

    ``table`` defaults to the historical mart; the realtime watcher
    passes ``fact_daily_kpis_live`` to blend intraday staging data.
    """
    db_path = db_path or DB_PATH
    if not db_path.exists():
        raise FileNotFoundError(f"Warehouse not found: {db_path}")

    contracts = load_contracts()

    # Read-write to match every other connection in the API process:
    # mixing read_only True/False on one file within a process raises
    # "different configuration than existing connections".
    con = duckdb.connect(str(db_path), read_only=False)
    try:
        kpis: dict[str, dict[str, Any]] = {}
        for kpi_id, column in DEFAULT_KPI_COLUMNS.items():
            rows = con.execute(
                f"""
                SELECT date, {column}
                FROM {table}
                WHERE {column} IS NOT NULL
                ORDER BY date
                """
            ).fetchall()

            contract = _resolve_contract(kpi_id, contracts)
            materiality = contract.get("materiality") or {}
            z_threshold = float(
                (contract.get("anomaly") or {}).get("z_score_threshold", 2.0)
            )

            result = evaluate_kpi(
                rows,
                column,
                materiality,
                z_threshold,
                baseline_weeks=baseline_weeks,
            )

            kpis[kpi_id] = {
                "kpi_id": contract.get("id", kpi_id),
                "name": contract.get("name", kpi_id.replace("_", " ").title()),
                "formula": (contract.get("formula") or "").strip(),
                "access_roles": contract.get(
                    "access_roles", ["executive", "operations", "analyst"]
                ),
                "sensitivity": contract.get("sensitivity", "internal"),
                **result,
            }
    finally:
        con.close()

    flagged = sorted(
        (k for k in kpis.values() if k.get("flagged")),
        key=lambda k: abs(k.get("z_score") or 0),
        reverse=True,
    )

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "warehouse": str(db_path.name),
        "kpis_evaluated": len(kpis),
        "flagged_count": len(flagged),
        "kpis": kpis,
        "flagged": [k["kpi_id"] for k in flagged],
    }


def save_status(payload: dict[str, Any]) -> Path:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return OUTPUT_PATH


def main() -> int:
    payload = compute_all_kpis()
    save_status(payload)
    print(
        f"[multi-kpi] evaluated {payload['kpis_evaluated']} KPIs, "
        f"{payload['flagged_count']} flagged"
    )
    for kpi_id, kpi in payload["kpis"].items():
        print(
            f"  {kpi_id:<20} {kpi['status']:<8} value={kpi['latest_value']} "
            f"z={kpi['z_score']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
