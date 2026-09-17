"""KPI forecasting + prescriptive action simulation.

Extends the scenario engine with a forward-looking view:

1. ``forecast_series`` — weekday-seasonality + damped-trend forecast of
   a daily KPI series from ``fact_daily_kpis``, with an 80% prediction
   interval derived from residual std. Pure python — no heavy deps.

2. ``simulate_action`` — prescriptive "what if we act": applies an
   uplift (or reduction) to the forecast and reports the cumulative
   delta over the horizon in KPI units (and BRL for gmv/aov).

Served by ``GET /api/forecast/{kpi_id}`` and ``POST /api/simulation``.
"""

from __future__ import annotations

import math
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

import duckdb

from analytics.multi_kpi import DEFAULT_KPI_COLUMNS, HIGHER_IS_BETTER

# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DB_PATH = PROJECT_ROOT / "data" / "warehouse" / "businessintelligence.duckdb"

# Human-facing units for the simulation delta
KPI_UNITS = {
    "gmv": "BRL",
    "orders": "orders",
    "aov": "BRL",
    "late_delivery_rate": "rate points",
    "review_score": "score points",
}


# ============================================================
# FORECAST CORE
# ============================================================


def _trend_fit(window: list[float]) -> tuple[float, float, float]:
    """Least-squares trend over a window.

    Returns (intercept_at_last_index, slope_per_day, residual_std).
    """
    m = len(window)
    xs = list(range(m))
    mean_x = sum(xs) / m
    mean_y = sum(window) / m
    cov_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, window))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    slope = cov_xy / var_x if var_x else 0.0
    intercept = mean_y - slope * mean_x

    residuals = [y - (intercept + slope * x) for x, y in zip(xs, window)]
    resid_std = math.sqrt(sum(r * r for r in residuals) / max(1, m - 2))
    return intercept, slope, resid_std


def forecast_deseasonalized(
    series: list[float],
    horizon: int = 14,
    damping: float = 0.85,
    fit_days: int = 56,
) -> dict[str, Any]:
    """Damped-trend forecast of a (deseasonalized) daily series.

    - Linear trend fitted on the last ``fit_days`` days
    - Damped extrapolation: trend contribution sum(phi^k)
    - 80% prediction interval: residual_std * 1.28 * sqrt(k)
    """
    if len(series) < 21:
        raise ValueError(f"Need at least 21 days of history, got {len(series)}")
    if horizon < 1 or horizon > 90:
        raise ValueError("horizon must be between 1 and 90 days")

    fit_window = series[-fit_days:]
    intercept, slope, resid_std = _trend_fit(fit_window)
    last_level = intercept + slope * (len(fit_window) - 1)

    point: list[float] = []
    for k in range(1, horizon + 1):
        damped = slope * sum(damping ** i for i in range(1, k + 1))
        point.append(last_level + damped)

    z80 = 1.2816
    lower = [
        max(0.0, p - z80 * resid_std * math.sqrt(k))
        for k, p in enumerate(point, start=1)
    ]
    upper = [
        p + z80 * resid_std * math.sqrt(k)
        for k, p in enumerate(point, start=1)
    ]

    return {
        "point": point,
        "lower": lower,
        "upper": upper,
        "fit_slope_per_day": round(slope, 6),
        "residual_std": round(resid_std, 6),
        "history_days": len(series),
    }


def forecast_series(
    dates: list[Any],
    values: list[float],
    horizon: int = 14,
) -> dict[str, Any]:
    """Weekday-seasonality aware forecast of a dated daily series.

    Computes weekday multiplicative factors (when >= 8 weeks history),
    deseasonalizes, forecasts with ``forecast_deseasonalized``, then
    reseasonalizes. Returns history + forecast arrays ready for charting.
    """
    if len(values) < 21:
        raise ValueError(f"Need at least 21 days of history, got {len(values)}")

    vals = [float(v) for v in values]
    use_weekday = len(vals) >= 56

    factors: Optional[dict[int, float]] = None
    series = vals

    if use_weekday:
        overall_mean = sum(vals) / len(vals)
        if overall_mean > 0:
            weekday_sums: dict[int, float] = {}
            weekday_counts: dict[int, int] = {}
            for d, v in zip(dates, vals):
                wd = d.weekday() if hasattr(d, "weekday") else 0
                weekday_sums[wd] = weekday_sums.get(wd, 0.0) + v
                weekday_counts[wd] = weekday_counts.get(wd, 0) + 1
            factors = {
                wd: (weekday_sums[wd] / weekday_counts[wd]) / overall_mean
                for wd in weekday_sums
            }
            series = [
                v / max(
                    factors.get(d.weekday() if hasattr(d, "weekday") else 0, 1.0),
                    0.05,
                )
                for d, v in zip(dates, vals)
            ]

    base = forecast_deseasonalized(series, horizon=horizon)

    # Reseasonalize and build dated output
    last_date = dates[-1]
    forecast_dates: list[str] = []
    point: list[float] = []
    lower: list[float] = []
    upper: list[float] = []
    for k in range(horizon):
        d = last_date + timedelta(days=k + 1)
        forecast_dates.append(str(d))
        f = 1.0
        if factors and hasattr(d, "weekday"):
            f = max(factors.get(d.weekday(), 1.0), 0.05)
        point.append(base["point"][k] * f)
        lower.append(max(0.0, base["lower"][k] * f))
        upper.append(base["upper"][k] * f)

    return {
        "history_dates": [str(d) for d in dates[-56:]],
        "history_values": [round(v, 4) for v in vals[-56:]],
        "forecast_dates": forecast_dates,
        "point": [round(v, 4) for v in point],
        "lower": [round(v, 4) for v in lower],
        "upper": [round(v, 4) for v in upper],
        "method": base["method"] if False else (
            "damped linear trend (phi=0.85) on trailing window"
            + (" + weekday seasonality" if factors else "")
        ),
        "fit_slope_per_day": base["fit_slope_per_day"],
        "residual_std": base["residual_std"],
        "history_days": len(vals),
    }


def simulate_action(
    forecast_point: list[float],
    uplift_pct: float,
    higher_is_better: bool = True,
) -> dict[str, Any]:
    """Apply an action uplift to a forecast and quantify the impact.

    ``uplift_pct`` is always expressed as a BENEFIT percentage
    (e.g. +5 means the KPI improves by 5%). For "lower is better"
    KPIs the benefit is applied as a reduction.
    """
    if abs(uplift_pct) > 100:
        raise ValueError("uplift_pct must be within +-100")

    if higher_is_better:
        factor = 1.0 + uplift_pct / 100.0
    else:
        factor = 1.0 - uplift_pct / 100.0

    after = [v * factor for v in forecast_point]
    deltas = [a - b for a, b in zip(after, forecast_point)]

    return {
        "uplift_pct": uplift_pct,
        "higher_is_better": higher_is_better,
        "after": [round(v, 4) for v in after],
        "daily_delta": [round(v, 4) for v in deltas],
        "cumulative_before": round(sum(forecast_point), 4),
        "cumulative_after": round(sum(after), 4),
        "cumulative_delta": round(sum(deltas), 4),
    }


# ============================================================
# WAREHOUSE HELPERS + API PAYLOADS
# ============================================================


def load_kpi_series(
    kpi_id: str,
    db_path: Optional[Path] = None,
    last_n_days: int = 120,
) -> tuple[list[Any], list[float]]:
    """Load the daily series for a KPI id from the warehouse."""
    column = DEFAULT_KPI_COLUMNS.get(kpi_id)
    if column is None:
        raise ValueError(
            f"Unknown KPI '{kpi_id}'. Supported: {sorted(DEFAULT_KPI_COLUMNS)}"
        )

    path = db_path or DB_PATH
    if not path.exists():
        raise FileNotFoundError(f"Warehouse not found: {path}")

    # Read-write to match every other connection in the API process:
    # mixing read_only True/False on one file within a process raises
    # "different configuration than existing connections".
    con = duckdb.connect(str(path), read_only=False)
    try:
        rows = con.execute(
            f"""
            SELECT date, {column}
            FROM fact_daily_kpis
            WHERE {column} IS NOT NULL
            ORDER BY date DESC
            LIMIT ?
            """,
            [last_n_days],
        ).fetchall()
    finally:
        con.close()

    rows = list(reversed(rows))
    dates = [r[0] for r in rows]
    values = [float(r[1] or 0.0) for r in rows]
    return dates, values


def build_forecast_payload(kpi_id: str, horizon: int = 14) -> dict[str, Any]:
    """Full forecast payload for the API."""
    dates, values = load_kpi_series(kpi_id)
    forecast = forecast_series(dates, values, horizon=horizon)
    return {
        "kpi_id": kpi_id,
        "unit": KPI_UNITS.get(kpi_id, "value"),
        "horizon_days": horizon,
        **forecast,
    }


def build_simulation_payload(
    kpi_id: str,
    uplift_pct: float,
    horizon: int = 14,
) -> dict[str, Any]:
    """Forecast + prescriptive simulation payload for the API."""
    dates, values = load_kpi_series(kpi_id)
    forecast = forecast_series(dates, values, horizon=horizon)
    simulation = simulate_action(
        forecast["point"],
        uplift_pct,
        higher_is_better=HIGHER_IS_BETTER.get(kpi_id, True),
    )
    return {
        "kpi_id": kpi_id,
        "unit": KPI_UNITS.get(kpi_id, "value"),
        "horizon_days": horizon,
        "forecast": forecast,
        "simulation": simulation,
        "interpretation": (
            f"Acting on the recommended action (assumed +{uplift_pct:g}% "
            f"improvement) would change {kpi_id} by "
            f"{simulation['cumulative_delta']:+,.2f} "
            f"{KPI_UNITS.get(kpi_id, 'units')} over the next {horizon} days "
            f"({simulation['cumulative_before']:,.0f} -> "
            f"{simulation['cumulative_after']:,.0f})."
        ),
    }
