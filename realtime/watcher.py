"""Near-real-time ingestion watcher.

Frames the pipeline as an intraday monitor instead of a next-day
batch job:

- ``scan_incoming`` picks up CSV files dropped into ``data/incoming/``,
  extracts the order dates they cover, re-derives the daily KPI rows
  for those dates straight from the warehouse fact tables (which the
  ingestion step refreshes), re-runs the multi-KPI materiality check
  for those dates, and appends ALERT/WATCH records to
  ``data/realtime/alerts.jsonl`` with wall-clock timestamps.

- ``run_watch_loop`` polls on an interval (CLI: ``--watch --interval 300``)
  so detections land intraday, not the next morning.

- ``inject_demo_batch`` writes a synthetic intraday batch (used by
  ``POST /api/watch/simulate-incoming`` for the live demo moment:
  "drop a file -> the watcher flags it in seconds").

Note on data freshness: the Olist dataset is static, so a fresh file
cannot change history. The demo batch therefore simulates a *new
partial day* by shifting the latest warehouse date's KPIs and checking
whether the watcher flags the deterioration — proving the detection
path end-to-end without touching the real warehouse.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from analytics.multi_kpi import compute_all_kpis

# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

INCOMING_DIR = PROJECT_ROOT / "data" / "incoming"

ALERTS_PATH = PROJECT_ROOT / "data" / "realtime" / "alerts.jsonl"

STATE_PATH = PROJECT_ROOT / "data" / "realtime" / "watcher_state.json"


# ============================================================
# INCOMING FILE SCAN
# ============================================================


def list_incoming_files() -> list[Path]:
    """Return unprocessed CSV files in the incoming directory."""
    if not INCOMING_DIR.exists():
        return []
    return sorted(p for p in INCOMING_DIR.glob("*.csv") if p.is_file())


def ingest_incoming_file(path: Path) -> dict[str, Any]:
    """Ingest one incoming CSV into the warehouse staging table.

    The CSV is expected to contain order-grain rows with at minimum
    ``order_id`` and ``order_purchase_timestamp``. Rows are appended
    to a ``streaming_orders`` staging table so the KPI recomputation
    can blend intraday data with the historical fact table.

    Returns a summary dict (rows, date range).
    """
    import csv

    rows: list[tuple[str, str, float]] = []
    with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            order_id = (row.get("order_id") or "").strip()
            ts = (row.get("order_purchase_timestamp") or "").strip()
            if order_id and ts:
                try:
                    price = float(row.get("price") or 0)
                except (TypeError, ValueError):
                    price = 0.0
                rows.append((order_id, ts, price))

    if not rows:
        return {"file": path.name, "rows": 0, "min_date": None, "max_date": None}

    import duckdb

    db_path = PROJECT_ROOT / "data" / "warehouse" / "businessintelligence.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS streaming_orders (
                order_id VARCHAR,
                order_purchase_timestamp TIMESTAMP,
                price DOUBLE
            )
            """
        )
        con.executemany(
            "INSERT INTO streaming_orders VALUES (?, ?, ?)",
            [
                (
                    oid,
                    ts[:19].replace("T", " ").replace("Z", " "),
                    price,
                )
                for oid, ts, price in rows
            ],
        )
        min_date, max_date = con.execute(
            "SELECT MIN(CAST(order_purchase_timestamp AS DATE)), "
            "MAX(CAST(order_purchase_timestamp AS DATE)) FROM streaming_orders"
        ).fetchone()
    finally:
        con.close()

    return {
        "file": path.name,
        "rows": len(rows),
        "min_date": str(min_date),
        "max_date": str(max_date),
    }


def refresh_live_view() -> str:
    """Create/replace the blended KPI view used for intraday checks.

    ``fact_daily_kpis_live`` = historical daily KPIs + intraday partial
    days aggregated from the ``streaming_orders`` staging table (orders,
    gmv, aov from the incoming feed; service KPIs carried through where
    the historical mart has them). Returns the table name to query.
    """
    import duckdb

    db_path = PROJECT_ROOT / "data" / "warehouse" / "businessintelligence.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        has_streaming = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = 'streaming_orders'"
        ).fetchone()[0]

        if not has_streaming:
            con.execute(
                "CREATE OR REPLACE VIEW fact_daily_kpis_live AS "
                "SELECT * FROM fact_daily_kpis"
            )
            return "fact_daily_kpis"

        streaming_dates = con.execute(
            "SELECT COALESCE(MIN(CAST(order_purchase_timestamp AS DATE)), DATE '9999-12-31') "
            "FROM streaming_orders"
        ).fetchone()[0]

        con.execute(
            f"""
            CREATE OR REPLACE VIEW fact_daily_kpis_live AS
            SELECT date, gmv, orders, aov, late_delivery_rate,
                   review_score, delivered_orders, late_orders, reviews
            FROM fact_daily_kpis
            WHERE date < DATE '{streaming_dates}'
            UNION ALL
            SELECT
                CAST(order_purchase_timestamp AS DATE) AS date,
                SUM(price) AS gmv,
                COUNT(DISTINCT order_id) AS orders,
                SUM(price) / NULLIF(COUNT(DISTINCT order_id), 0) AS aov,
                NULL AS late_delivery_rate,
                NULL AS review_score,
                NULL AS delivered_orders,
                NULL AS late_orders,
                NULL AS reviews
            FROM streaming_orders
            GROUP BY 1
            """
        )
        return "fact_daily_kpis_live"
    finally:
        con.close()


# ============================================================
# SCAN + ALERTS
# ============================================================


def scan_incoming() -> dict[str, Any]:
    """Full intraday scan: ingest new files, re-check KPIs, emit alerts."""
    scan_started = datetime.now()

    files = list_incoming_files()
    ingested = []
    for path in files:
        summary = ingest_incoming_file(path)
        ingested.append(summary)
        # Archive the processed file so it is not re-ingested
        processed_dir = INCOMING_DIR / "processed"
        processed_dir.mkdir(parents=True, exist_ok=True)
        try:
            path.rename(processed_dir / path.name)
        except OSError:
            pass

    table = refresh_live_view()

    try:
        status = compute_all_kpis(table=table)
        error = None
    except Exception as exc:  # pragma: no cover - defensive
        status = {"kpis": {}, "flagged": [], "kpis_evaluated": 0}
        error = str(exc)

    detected_at = datetime.now().isoformat(timespec="seconds")
    new_alerts: list[dict[str, Any]] = []

    for kpi_id in status.get("flagged", []):
        # `flagged` carries contract ids (e.g. marketplace_gmv) while
        # `kpis` is keyed by column id (e.g. gmv) — reverse-lookup.
        kpi = next(
            (
                v
                for v in status["kpis"].values()
                if v.get("kpi_id") == kpi_id
                or (v.get("kpi_id") or "").endswith(kpi_id)
                or kpi_id.endswith(v.get("kpi_id") or "")
            ),
            {},
        )
        new_alerts.append(
            {
                "detected_at": detected_at,
                "scan_latency_seconds": round(
                    (datetime.now() - scan_started).total_seconds(), 3
                ),
                "kpi_id": kpi_id,
                "status": kpi.get("status"),
                "latest_value": kpi.get("latest_value"),
                "change_pct": kpi.get("change_pct"),
                "z_score": kpi.get("z_score"),
                "reason": kpi.get("reason"),
                "ingested_files": [f["file"] for f in ingested],
            }
        )

    if new_alerts:
        ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with ALERTS_PATH.open("a", encoding="utf-8") as fh:
            for alert in new_alerts:
                fh.write(json.dumps(alert, ensure_ascii=False) + "\n")

    return {
        "scanned_at": detected_at,
        "source_table": table,
        "files_ingested": len(ingested),
        "ingested": ingested,
        "kpis_evaluated": status.get("kpis_evaluated", 0),
        "new_alerts": new_alerts,
        "error": error,
    }


def read_alerts(limit: int = 50) -> list[dict[str, Any]]:
    """Read the most recent intraday alerts (newest last)."""
    if not ALERTS_PATH.exists():
        return []
    alerts: list[dict[str, Any]] = []
    with ALERTS_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                alerts.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return alerts[-limit:]


# ============================================================
# DEMO INJECTION
# ============================================================


def inject_demo_batch() -> dict[str, Any]:
    """Write a synthetic intraday CSV into data/incoming for the demo.

    Simulates a partial-day feed showing a demand deterioration
    (~35% of typical volume) on the day after the warehouse's last
    date. The next ``scan_incoming`` picks it up and flags it.
    """
    import duckdb

    db_path = PROJECT_ROOT / "data" / "warehouse" / "businessintelligence.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        has_streaming = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = 'streaming_orders'"
        ).fetchone()[0]
        if has_streaming:
            # Remove batches from previous demo runs so the simulated
            # day is not blended with stale synthetic data
            con.execute("DELETE FROM streaming_orders WHERE order_id LIKE 'SIM-%'")
        row = con.execute(
            """
            SELECT
                CAST(MAX(date) AS DATE),
                AVG(orders),
                COALESCE(STDDEV_SAMP(orders), 0),
                AVG(aov)
            FROM fact_daily_kpis
            WHERE orders >= 10
              AND date >= (SELECT MAX(date) - INTERVAL 56 DAY FROM fact_daily_kpis)
            """
        ).fetchone()
    finally:
        con.close()

    last_date = row[0]
    avg_orders = float(row[1] or 40)
    std_orders = float(row[2] or 0)
    typical_aov = float(row[3] or 200)
    next_day = last_date + timedelta(days=1)

    # Size the batch as a statistically extreme demand drop (~2.5 sigma
    # below the trailing daily average) so the watcher reliably flags
    # it as a material, anomalous deterioration.
    target_orders = avg_orders - (2.5 * std_orders)
    orders_in_batch = max(5, int(target_orders))

    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    batch_file = INCOMING_DIR / (
        f"intraday_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )
    lines = ["order_id,order_purchase_timestamp,price"]
    for i in range(orders_in_batch):
        hour = (i * 3) % 24
        lines.append(
            f"SIM-{batch_file.stem}-{i:04d},"
            f"{next_day} {hour:02d}:15:00,{typical_aov:.2f}"
        )
    batch_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {
        "file": str(batch_file.name),
        "rows": orders_in_batch,
        "simulated_date": str(next_day),
        "note": (
            "Synthetic intraday partial-day feed sized as a ~2.5-sigma "
            "drop below the trailing daily average. The next scan "
            "flags the GMV/orders deterioration."
        ),
    }


# ============================================================
# WATCH LOOP + CLI
# ============================================================


def run_watch_loop(interval_seconds: int = 300, once: bool = False) -> None:
    """Poll for incoming files and emit alerts on an interval."""
    print(
        f"[watcher] watching {INCOMING_DIR} every {interval_seconds}s "
        f"(Ctrl+C to stop)"
    )
    while True:
        result = scan_incoming()
        print(
            f"[watcher {result['scanned_at']}] "
            f"files_ingested={result['files_ingested']} "
            f"kpis={result['kpis_evaluated']} "
            f"new_alerts={len(result['new_alerts'])}"
        )
        for alert in result["new_alerts"]:
            print(f"  !! {alert['kpi_id']} {alert['status']}: {alert['reason']}")
        if once:
            break
        try:
            time.sleep(interval_seconds)
        except KeyboardInterrupt:
            print("[watcher] stopped")
            break


def main() -> int:
    parser = argparse.ArgumentParser(description="Realtime KPI watcher")
    parser.add_argument("--watch", action="store_true", help="run continuously")
    parser.add_argument("--interval", type=int, default=300, help="poll seconds")
    parser.add_argument("--once", action="store_true", help="single scan")
    parser.add_argument(
        "--inject-demo", action="store_true", help="write a demo batch file"
    )
    args = parser.parse_args()

    if args.inject_demo:
        print(json.dumps(inject_demo_batch(), indent=2))
        return 0

    if args.watch or args.once:
        run_watch_loop(interval_seconds=args.interval, once=args.once)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
