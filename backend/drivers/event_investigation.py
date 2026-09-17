
"""
BusinessIntelligence.ai
Event-specific deterministic investigation engine.

This module is deliberately stateless:
- It does not overwrite fact_driver_confidence.
- It does not overwrite fact_recommended_actions.
- It does not call an LLM.
- It computes the selected event from warehouse data on demand.

The resulting dictionary is designed to be passed to the API and then,
optionally, to the LLM narrative layer.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parent.parent

DB_PATH = (
    PROJECT_ROOT
    / "data"
    / "warehouse"
    / "businessintelligence.duckdb"
)


# Keep these aligned with the existing confidence/action engines.
MIN_REVIEW_RECORDS = 5
HIGH_CONFIDENCE = 0.75
MODERATE_CONFIDENCE = 0.55
LOW_CONFIDENCE = 0.35
MIN_DRIVER_CONTRIBUTION = 0.05


def connect_database() -> duckdb.DuckDBPyConnection:
    """Open the governed DuckDB warehouse."""

    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"DuckDB database not found:\n{DB_PATH}"
        )

    return duckdb.connect(str(DB_PATH))


def _as_date(value: Any) -> date:
    """Normalize DuckDB date/timestamp values."""

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    return datetime.fromisoformat(
        str(value)
    ).date()


def _json_safe(value: Any) -> Any:
    """Convert common DuckDB scalar types to JSON-safe values."""

    if value is None:
        return None

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass

    return value


def get_event(
    con: duckdb.DuckDBPyConnection,
    event_id: int,
) -> dict[str, Any]:

    row = con.execute(
        """
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
        WHERE event_group = ?
        LIMIT 1;
        """,
        [event_id],
    ).fetchone()

    if row is None:
        raise ValueError(
            f"Event {event_id} not found."
        )

    (
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
        event_priority_score,
    ) = row

    start_date = _as_date(
        event_start_date
    )

    end_date = _as_date(
        event_end_date
    )

    # fact_gmv_events stores event end dates inclusively.
    duration_days = (
        end_date - start_date
    ).days + 1

    if duration_days <= 0:
        duration_days = 1

    end_exclusive = (
        end_date + timedelta(days=1)
    )

    comparison_start = (
        start_date
        - timedelta(days=duration_days)
    )

    return {
        "event_id":
            int(event_group),

        "start_date":
            start_date,

        "end_date":
            end_date,

        "end_exclusive":
            end_exclusive,

        "duration_days":
            duration_days,

        "comparison_start":
            comparison_start,

        "comparison_end":
            start_date,

        "anomalous_days":
            anomalous_days,

        "direction":
            direction,

        "event_type":
            event_type,

        "investigation_priority":
            investigation_priority,

        "peak_change":
            peak_change_abs,

        "peak_z_score":
            peak_z_score,

        "cumulative_absolute_impact":
            cumulative_absolute_impact,

        "source_coverage":
            coverage_status,

        "priority_score":
            event_priority_score,
    }


def calculate_movement(
    con: duckdb.DuckDBPyConnection,
    event: dict[str, Any],
) -> dict[str, Any]:

    start = event["start_date"]
    end_exclusive = event["end_exclusive"]
    comparison_start = event["comparison_start"]
    comparison_end = event["comparison_end"]

    # ------------------------------------------------------------
    # CURRENT PERIOD
    # ------------------------------------------------------------

    current_row = con.execute(
        """
        SELECT
            COALESCE(SUM(oi.price), 0.0) AS gmv,
            COUNT(DISTINCT o.order_id) AS orders
        FROM fact_order_items_enriched oi
        INNER JOIN fact_orders_enriched o
            ON o.order_id = oi.order_id
        WHERE
            CAST(o.order_purchase_timestamp AS DATE)
            >= ?
            AND
            CAST(o.order_purchase_timestamp AS DATE)
            < ?;
        """,
        [
            start,
            end_exclusive,
        ],
    ).fetchone()

    # ------------------------------------------------------------
    # PREVIOUS / COMPARISON PERIOD
    # ------------------------------------------------------------

    previous_row = con.execute(
        """
        SELECT
            COALESCE(SUM(oi.price), 0.0) AS gmv,
            COUNT(DISTINCT o.order_id) AS orders
        FROM fact_order_items_enriched oi
        INNER JOIN fact_orders_enriched o
            ON o.order_id = oi.order_id
        WHERE
            CAST(o.order_purchase_timestamp AS DATE)
            >= ?
            AND
            CAST(o.order_purchase_timestamp AS DATE)
            < ?;
        """,
        [
            comparison_start,
            comparison_end,
        ],
    ).fetchone()

    # ------------------------------------------------------------
    # VALIDATE RESULTS
    # ------------------------------------------------------------

    if current_row is None:
        raise RuntimeError(
            f"Could not calculate current-period movement "
            f"for event {event['event_id']}."
        )

    if previous_row is None:
        raise RuntimeError(
            f"Could not calculate comparison-period movement "
            f"for event {event['event_id']}."
        )

    current_gmv = float(
        current_row[0] or 0.0
    )

    current_orders = int(
        current_row[1] or 0
    )

    previous_gmv = float(
        previous_row[0] or 0.0
    )

    previous_orders = int(
        previous_row[1] or 0
    )

    # ------------------------------------------------------------
    # AOV
    # ------------------------------------------------------------

    previous_aov = (
        previous_gmv / previous_orders
        if previous_orders > 0
        else None
    )

    current_aov = (
        current_gmv / current_orders
        if current_orders > 0
        else None
    )

    # ------------------------------------------------------------
    # MOVEMENT
    # ------------------------------------------------------------

    gmv_change = (
        current_gmv
        - previous_gmv
    )

    orders_change = (
        current_orders
        - previous_orders
    )

    aov_change = (
        current_aov - previous_aov
        if (
            current_aov is not None
            and previous_aov is not None
        )
        else None
    )

    # ------------------------------------------------------------
    # MIDPOINT DECOMPOSITION
    # ------------------------------------------------------------

    volume_effect = (
        orders_change
        * (
            (previous_aov or 0.0)
            + (current_aov or 0.0)
        )
        / 2.0
        if (
            previous_aov is not None
            and current_aov is not None
        )
        else None
    )

    aov_effect = (
        aov_change
        * (
            previous_orders
            + current_orders
        )
        / 2.0
        if aov_change is not None
        else None
    )

    residual_effect = (
        gmv_change
        - volume_effect
        - aov_effect
        if (
            volume_effect is not None
            and aov_effect is not None
        )
        else None
    )

    return {
        "comparison_period": {
            "start":
                comparison_start,

            "end":
                comparison_end,
        },

        "previous_gmv":
            previous_gmv,

        "current_gmv":
            current_gmv,

        "gmv_change":
            gmv_change,

        "previous_orders":
            previous_orders,

        "current_orders":
            current_orders,

        "orders_change":
            orders_change,

        "previous_aov":
            previous_aov,

        "current_aov":
            current_aov,

        "aov_change":
            aov_change,

        "volume_effect":
            volume_effect,

        "aov_effect":
            aov_effect,

        "residual_effect":
            residual_effect,
    }


def _candidate_query(
    dimension: str,
) -> tuple[str, str]:

    if dimension == "customer_state":

        key_expression = "o.customer_state"

    elif dimension == "category":

        key_expression = (
            "COALESCE("
            "p.product_category_name,"
            "'unknown'"
            ")"
        )

    elif dimension == "seller":

        key_expression = "oi.seller_id"

    else:

        raise ValueError(
            f"Unsupported driver dimension: {dimension}"
        )

    query = f"""
        SELECT
            {key_expression} AS driver,

            SUM(
                CASE
                    WHEN
                        CAST(o.order_purchase_timestamp AS DATE) >= ?
                        AND CAST(o.order_purchase_timestamp AS DATE) < ?
                    THEN oi.price
                    ELSE 0
                END
            )
            -
            SUM(
                CASE
                    WHEN
                        CAST(o.order_purchase_timestamp AS DATE) >= ?
                        AND CAST(o.order_purchase_timestamp AS DATE) < ?
                    THEN oi.price
                    ELSE 0
                END
            ) AS gmv_change

        FROM fact_order_items_enriched oi

        INNER JOIN fact_orders_enriched o
            ON o.order_id = oi.order_id

        LEFT JOIN olist_products_dataset p
            ON p.product_id = oi.product_id

        WHERE
            (
                CAST(o.order_purchase_timestamp AS DATE) >= ?
                AND CAST(o.order_purchase_timestamp AS DATE) < ?
            )
            OR
            (
                CAST(o.order_purchase_timestamp AS DATE) >= ?
                AND CAST(o.order_purchase_timestamp AS DATE) < ?
            )

        GROUP BY
            1

        HAVING
            ABS(
                SUM(
                    CASE
                        WHEN
                            CAST(o.order_purchase_timestamp AS DATE) >= ?
                            AND CAST(o.order_purchase_timestamp AS DATE) < ?
                        THEN oi.price
                        ELSE 0
                    END
                )
                -
                SUM(
                    CASE
                        WHEN
                            CAST(o.order_purchase_timestamp AS DATE) >= ?
                            AND CAST(o.order_purchase_timestamp AS DATE) < ?
                        THEN oi.price
                        ELSE 0
                    END
                )
            ) > 0

        ORDER BY
            ABS(gmv_change) DESC

        LIMIT 50;
    """

    return key_expression, query


def calculate_segment_candidates(
    con: duckdb.DuckDBPyConnection,
    event: dict[str, Any],
    movement: dict[str, Any],
    dimensions: tuple[str, ...] = (
        "customer_state",
        "category",
        "seller",
    ),
    limit_per_dimension: int = 20,
) -> list[dict[str, Any]]:

    candidates: list[dict[str, Any]] = []

    start = event["start_date"]
    end_exclusive = event["end_exclusive"]
    comparison_start = event["comparison_start"]
    comparison_end = event["comparison_end"]

    total_change = float(
        movement["gmv_change"]
    )

    for dimension in dimensions:

        try:

            _, query = _candidate_query(
                dimension
            )

            params = [
                start,
                end_exclusive,
                comparison_start,
                comparison_end,
                comparison_start,
                comparison_end,
                start,
                end_exclusive,
                start,
                end_exclusive,
                comparison_start,
                comparison_end,
            ]

            rows = con.execute(
                query,
                params,
            ).fetchall()

        except Exception as exc:

            raise RuntimeError(
                f"Failed to calculate {dimension} "
                f"candidates for event "
                f"{event['event_id']}: {exc}"
            ) from exc

        for row in rows[:limit_per_dimension]:

            driver = row[0]

            if driver is None:
                continue

            gmv_change = float(
                row[1] or 0
            )

            contribution_share = (
                gmv_change / abs(total_change)
                if total_change != 0
                else 0.0
            )

            candidates.append(
                {
                    "driver_type":
                        dimension,

                    "driver":
                        str(driver),

                    "gmv_change":
                        gmv_change,

                    "contribution_share":
                        contribution_share,
                }
            )

    candidates.sort(
        key=lambda item: (
            abs(
                item["contribution_share"]
            ),
            abs(item["gmv_change"]),
        ),
        reverse=True,
    )

    return candidates[:30]


def get_review_evidence_for_driver(
    con: duckdb.DuckDBPyConnection,
    event: dict[str, Any],
    dimension: str,
    driver: str,
) -> dict[str, Any]:

    if dimension == "customer_state":

        driver_column = "customer_state"

    elif dimension == "category":

        driver_column = "category_name"

    else:

        return {
            "available":
                False,

            "event_records":
                0,

            "comparison_records":
                0,

            "event_positive_share":
                None,

            "comparison_positive_share":
                None,

            "event_negative_share":
                None,

            "comparison_negative_share":
                None,

            "directional_support":
                0.0,

            "status":
                "NOT_AVAILABLE",
        }

    rows = con.execute(
        f"""
        SELECT
            sentiment,

            SUM(
                CASE
                    WHEN
                        CAST(review_creation_date AS DATE) >= ?
                        AND CAST(review_creation_date AS DATE) < ?
                    THEN 1
                    ELSE 0
                END
            ) AS event_count,

            SUM(
                CASE
                    WHEN
                        CAST(review_creation_date AS DATE) >= ?
                        AND CAST(review_creation_date AS DATE) < ?
                    THEN 1
                    ELSE 0
                END
            ) AS comparison_count

        FROM fact_review_evidence_base

        WHERE
            {driver_column} = ?

            AND (
                (
                    CAST(review_creation_date AS DATE) >= ?
                    AND CAST(review_creation_date AS DATE) < ?
                )
                OR
                (
                    CAST(review_creation_date AS DATE) >= ?
                    AND CAST(review_creation_date AS DATE) < ?
                )
            )

        GROUP BY
            sentiment;
        """,
        [
            event["start_date"],
            event["end_exclusive"],
            event["comparison_start"],
            event["comparison_end"],
            driver,
            event["comparison_start"],
            event["comparison_end"],
            event["start_date"],
            event["end_exclusive"],
        ],
    ).fetchall()

    if not rows:

        return {
            "available":
                False,

            "event_records":
                0,

            "comparison_records":
                0,

            "event_positive_share":
                None,

            "comparison_positive_share":
                None,

            "event_negative_share":
                None,

            "comparison_negative_share":
                None,

            "directional_support":
                0.0,

            "status":
                "NO_EVIDENCE",
        }

    event_total = sum(
        int(row[1] or 0)
        for row in rows
    )

    comparison_total = sum(
        int(row[2] or 0)
        for row in rows
    )

    event_positive = sum(
        int(row[1] or 0)
        for row in rows
        if str(row[0]).lower()
        == "positive"
    )

    comparison_positive = sum(
        int(row[2] or 0)
        for row in rows
        if str(row[0]).lower()
        == "positive"
    )

    event_negative = sum(
        int(row[1] or 0)
        for row in rows
        if str(row[0]).lower()
        == "negative"
    )

    comparison_negative = sum(
        int(row[2] or 0)
        for row in rows
        if str(row[0]).lower()
        == "negative"
    )

    event_positive_share = (
        event_positive / event_total
        if event_total > 0
        else 0.0
    )

    comparison_positive_share = (
        comparison_positive / comparison_total
        if comparison_total > 0
        else 0.0
    )

    event_negative_share = (
        event_negative / event_total
        if event_total > 0
        else 0.0
    )

    comparison_negative_share = (
        comparison_negative / comparison_total
        if comparison_total > 0
        else 0.0
    )

    positive_change = (
        event_positive_share
        - comparison_positive_share
    )

    negative_change = (
        event_negative_share
        - comparison_negative_share
    )

    if event["direction"] == "POSITIVE":

        directional_support = (
            positive_change
            - negative_change
        )

    else:

        directional_support = (
            negative_change
            - positive_change
        )

    directional_support = max(
        -1.0,
        min(
            1.0,
            directional_support,
        ),
    )

    if (
        event_total >= MIN_REVIEW_RECORDS
        and comparison_total >= MIN_REVIEW_RECORDS
    ):

        if directional_support >= 0.05:

            status = "SUPPORTING"

        elif directional_support <= -0.05:

            status = "CONTRADICTING"

        else:

            status = "NEUTRAL"

    else:

        status = "INSUFFICIENT_REVIEW_DATA"

    return {
        "available":
            True,

        "event_records":
            event_total,

        "comparison_records":
            comparison_total,

        "event_positive_share":
            event_positive_share,

        "comparison_positive_share":
            comparison_positive_share,

        "event_negative_share":
            event_negative_share,

        "comparison_negative_share":
            comparison_negative_share,

        "directional_support":
            directional_support,

        "status":
            status,
    }


def get_context_evidence_for_driver(
    con: duckdb.DuckDBPyConnection,
    event: dict[str, Any],
    dimension: str,
    driver: str,
) -> dict[str, Any]:

    if dimension == "customer_state":

        result = con.execute(
            """
            SELECT
                COUNT(*) AS rows_found,
                COUNT_IF(promotion_flag = 1) AS promotion_rows,
                COUNT_IF(
                    inventory_status = 'constrained'
                ) AS constrained_rows,
                AVG(competitor_price_index)
                    AS avg_competitor_index,
                COUNT_IF(
                    external_event_flag = 1
                ) AS external_event_rows
            FROM business_context
            WHERE
                region = ?
                AND date BETWEEN ? AND ?;
            """,
            [
                driver,
                event["start_date"],
                event["end_date"],
            ],
        ).fetchone()

    elif dimension == "category":

        result = con.execute(
            """
            SELECT
                COUNT(*) AS rows_found,
                COUNT_IF(promotion_flag = 1) AS promotion_rows,
                COUNT_IF(
                    inventory_status = 'constrained'
                ) AS constrained_rows,
                AVG(competitor_price_index)
                    AS avg_competitor_index,
                COUNT_IF(
                    external_event_flag = 1
                ) AS external_event_rows
            FROM business_context
            WHERE
                category = ?
                AND date BETWEEN ? AND ?;
            """,
            [
                driver,
                event["start_date"],
                event["end_date"],
            ],
        ).fetchone()

    else:

        return {
            "available":
                False,

            "status":
                "NOT_IMPLEMENTED",
        }

    (
        rows_found,
        promotion_rows,
        constrained_rows,
        competitor_index,
        external_event_rows,
    ) = result

    if rows_found == 0:

        return {
            "available":
                False,

            "status":
                "NO_CONTEXT_EVIDENCE",
        }

    evidence_types = 0

    if promotion_rows > 0:
        evidence_types += 1

    if constrained_rows > 0:
        evidence_types += 1

    if external_event_rows > 0:
        evidence_types += 1

    if (
        competitor_index is not None
        and abs(
            float(competitor_index) - 1.0
        ) >= 0.03
    ):
        evidence_types += 1

    return {
        "available":
            True,

        "rows_found":
            int(rows_found),

        "promotion_rows":
            int(promotion_rows),

        "constrained_rows":
            int(constrained_rows),

        "avg_competitor_price_index":
            float(competitor_index)
            if competitor_index is not None
            else None,

        "external_event_rows":
            int(external_event_rows),

        "evidence_types":
            evidence_types,

        "status":
            (
                "CONTEXT_AVAILABLE"
                if evidence_types > 0
                else "NO_STRONG_CONTEXT_SIGNAL"
            ),
    }


def calculate_confidence(
    contribution_share: float,
    review: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:

    structural_score = min(
        1.0,
        abs(contribution_share) / 0.50,
    )

    if review.get("status") in {
        "SUPPORTING",
        "CONTRADICTING",
        "NEUTRAL",
    }:

        review_score = abs(
            float(
                review.get(
                    "directional_support",
                    0.0,
                )
            )
        )

    else:

        review_score = 0.0

    if context.get(
        "available",
        False,
    ):

        context_score = min(
            1.0,
            float(
                context.get(
                    "evidence_types",
                    0,
                )
            ) / 2.0,
        )

    else:

        context_score = 0.0

    independent_sources = 1

    if review.get(
        "available",
        False,
    ):
        independent_sources += 1

    if context.get(
        "available",
        False,
    ):
        independent_sources += 1

    confidence = (
        0.60 * structural_score
        + 0.20 * review_score
        + 0.20 * context_score
    )

    if review.get("status") == "CONTRADICTING":
        confidence *= 0.65

    if independent_sources == 1:
        confidence = min(
            confidence,
            0.55,
        )

    return {
        "overall":
            round(confidence, 3),

        "structural":
            round(structural_score, 3),

        "review":
            round(review_score, 3),

        "context":
            round(context_score, 3),

        "independent_sources":
            independent_sources,
    }


def determine_status(
    confidence: float,
    review: dict[str, Any],
    contribution_share: float,
) -> str:

    if abs(contribution_share) < MIN_DRIVER_CONTRIBUTION:
        return "WEAK_DRIVER"

    if (
        review.get("status")
        == "CONTRADICTING"
        and confidence < MODERATE_CONFIDENCE
    ):
        return "CONTRADICTED"

    if confidence >= HIGH_CONFIDENCE:
        return "SUPPORTED"

    if confidence >= MODERATE_CONFIDENCE:
        return "PLAUSIBLE"

    if confidence >= LOW_CONFIDENCE:
        return "WEAK"

    return "ABSTAIN"


def get_action(
    driver_type: str,
    driver: str,
    final_status: str,
) -> dict[str, Any]:

    # Keep the business rules aligned with actions/action_engine.py.
    if final_status == "CONTRADICTED":

        return {
            "decision":
                "DO_NOT_ACT",

            "lever":
                None,

            "action":
                (
                    "Do not act on this hypothesis; "
                    "treat it as contradicted by the "
                    "available evidence."
                ),

            "owner":
                "Analyst",

            "monitoring_plan":
                "Re-evaluate if new evidence becomes available.",

            "action_type":
                "DO_NOT_ACT",
        }

    if final_status == "ABSTAIN":

        return {
            "decision":
                "ABSTAIN",

            "lever":
                None,

            "action":
                (
                    "Collect additional evidence before "
                    "taking an operational action."
                ),

            "owner":
                "Analyst",

            "monitoring_plan":
                (
                    "Refresh the missing or insufficient "
                    "evidence source."
                ),

            "action_type":
                "ABSTAIN",
        }

    if final_status == "WEAK":

        decision = "INVESTIGATE"

    elif final_status == "PLAUSIBLE":

        decision = "ACTION_WITH_VALIDATION"

    elif final_status == "SUPPORTED":

        decision = "ACTIONABLE"

    else:

        decision = "ABSTAIN"

    if driver_type == "customer_state":

        lever = "regional demand / operations"

        action_text = (
            f"Investigate the drivers of the KPI movement "
            f"among customers in {driver}, including demand, "
            f"availability and operational performance."
        )

        owner = "Regional Operations"

        monitor = (
            f"Monitor orders, AOV and customer experience "
            f"metrics in {driver}."
        )

    elif driver_type == "category":

        lever = "category demand / assortment"

        action_text = (
            f"Investigate demand, availability, pricing "
            f"and assortment changes in the {driver} category."
        )

        owner = "Category Management"

        monitor = (
            f"Monitor category orders, AOV and customer "
            f"feedback for {driver}."
        )

    elif driver_type == "seller":

        lever = "seller performance"

        action_text = (
            f"Investigate seller-level changes affecting "
            f"{driver}, including availability, delivery "
            f"and product performance."
        )

        owner = "Seller Operations"

        monitor = (
            f"Monitor orders, delivery performance and "
            f"review scores for {driver}."
        )

    else:

        lever = None

        action_text = (
            "Investigate the driver using available "
            "business evidence."
        )

        owner = "Analyst"

        monitor = (
            "Monitor the KPI and refresh supporting evidence."
        )

    return {
        "decision":
            decision,

        "lever":
            lever,

        "action":
            action_text,

        "owner":
            owner,

        "monitoring_plan":
            monitor,

        "action_type":
            (
                "ACT"
                if final_status == "SUPPORTED"
                else "INVESTIGATE"
            ),
    }



# ============================================================
# EVENT-WIDE REVIEW EVIDENCE
# ============================================================

def calculate_event_review_evidence(
    con: duckdb.DuckDBPyConnection,
    event: dict[str, Any],
) -> dict[str, Any]:
    """
    Build review/aspect evidence for the selected event from the
    same event/comparison windows used by the deterministic engine.

    Reviews are linked to the commerce event through order_id and
    order_purchase_timestamp rather than relying on review_creation_date.
    This keeps review evidence aligned with the KPI event itself and makes
    every event use the same logic.
    """

    rows = con.execute(
        """
        SELECT
            r.aspect,
            LOWER(COALESCE(r.sentiment, 'neutral')) AS sentiment,

            COUNT(*) FILTER (
                WHERE
                    CAST(o.order_purchase_timestamp AS DATE)
                    >= ?
                    AND CAST(o.order_purchase_timestamp AS DATE)
                    < ?
            ) AS event_count,

            COUNT(*) FILTER (
                WHERE
                    CAST(o.order_purchase_timestamp AS DATE)
                    >= ?
                    AND CAST(o.order_purchase_timestamp AS DATE)
                    < ?
            ) AS comparison_count

        FROM fact_review_evidence_base r

        INNER JOIN fact_orders_enriched o
            ON o.order_id = r.order_id

        WHERE
            (
                CAST(o.order_purchase_timestamp AS DATE)
                >= ?
                AND CAST(o.order_purchase_timestamp AS DATE)
                < ?
            )
            OR
            (
                CAST(o.order_purchase_timestamp AS DATE)
                >= ?
                AND CAST(o.order_purchase_timestamp AS DATE)
                < ?
            )

        GROUP BY
            r.aspect,
            LOWER(COALESCE(r.sentiment, 'neutral'))

        HAVING
            COUNT(*) FILTER (
                WHERE
                    CAST(o.order_purchase_timestamp AS DATE)
                    >= ?
                    AND CAST(o.order_purchase_timestamp AS DATE)
                    < ?
            ) > 0

        ORDER BY
            r.aspect,
            event_count DESC;
        """,
        [
            event["start_date"],
            event["end_exclusive"],
            event["comparison_start"],
            event["comparison_end"],
            event["comparison_start"],
            event["comparison_end"],
            event["start_date"],
            event["end_exclusive"],
            event["start_date"],
            event["end_exclusive"],
        ],
    ).fetchall()

    aspect_map: dict[str, dict[str, Any]] = {}

    for (
        aspect,
        sentiment,
        event_count,
        comparison_count,
    ) in rows:

        aspect_key = str(aspect)

        if aspect_key not in aspect_map:

            aspect_map[aspect_key] = {
                "aspect":
                    aspect_key,

                "event_mentions":
                    0,

                "comparison_mentions":
                    0,

                "mention_change":
                    0,

                "sentiment":
                    {},
            }

        event_mentions = int(
            event_count or 0
        )

        comparison_mentions = int(
            comparison_count or 0
        )

        aspect_map[aspect_key]["event_mentions"] += (
            event_mentions
        )

        aspect_map[aspect_key]["comparison_mentions"] += (
            comparison_mentions
        )

        aspect_map[aspect_key]["mention_change"] = (
            aspect_map[aspect_key]["event_mentions"]
            - aspect_map[aspect_key]["comparison_mentions"]
        )

        aspect_map[aspect_key]["sentiment"][
            sentiment
        ] = {
            "event_mentions":
                event_mentions,

            "comparison_mentions":
                comparison_mentions,

            "mention_change":
                event_mentions
                - comparison_mentions,
        }

    aspect_summary = list(
        aspect_map.values()
    )

    aspect_summary.sort(
        key=lambda row: (
            abs(
                row["mention_change"]
            ),
            row["event_mentions"],
        ),
        reverse=True,
    )

    # Count actual review records, not aspect x sentiment groups.
    review_counts = con.execute(
        """
        SELECT
            COUNT(DISTINCT r.review_id) FILTER (
                WHERE
                    CAST(o.order_purchase_timestamp AS DATE)
                    >= ?
                    AND CAST(o.order_purchase_timestamp AS DATE)
                    < ?
            ) AS event_reviews,

            COUNT(DISTINCT r.review_id) FILTER (
                WHERE
                    CAST(o.order_purchase_timestamp AS DATE)
                    >= ?
                    AND CAST(o.order_purchase_timestamp AS DATE)
                    < ?
            ) AS comparison_reviews

        FROM fact_review_evidence_base r

        INNER JOIN fact_orders_enriched o
            ON o.order_id = r.order_id

        WHERE
            (
                CAST(o.order_purchase_timestamp AS DATE)
                >= ?
                AND CAST(o.order_purchase_timestamp AS DATE)
                < ?
            )
            OR
            (
                CAST(o.order_purchase_timestamp AS DATE)
                >= ?
                AND CAST(o.order_purchase_timestamp AS DATE)
                < ?
            );
        """,
        [
            event["start_date"],
            event["end_exclusive"],
            event["comparison_start"],
            event["comparison_end"],
            event["comparison_start"],
            event["comparison_end"],
            event["start_date"],
            event["end_exclusive"],
        ],
    ).fetchone()

    event_review_records = int(
        review_counts[0] or 0
    )

    comparison_review_records = int(
        review_counts[1] or 0
    )

    return {
        "aspect_summary":
            aspect_summary,

        "sentiment_by_aspect":
            [
                {
                    "aspect":
                        str(row[0]),

                    "sentiment":
                        str(row[1]),

                    "event_mentions":
                        int(row[2] or 0),

                    "comparison_mentions":
                        int(row[3] or 0),

                    "mention_change":
                        int(row[2] or 0)
                        - int(row[3] or 0),
                }
                for row in rows
            ],

        "record_count":
            len(rows),

        "event_review_records":
            event_review_records,

        "comparison_review_records":
            comparison_review_records,

        "source":
            "fact_review_evidence_base_joined_to_orders",

        "dynamic":
            True,
    }


# ============================================================
# EVENT-WIDE CUSTOMER EXPERIENCE
# ============================================================

def calculate_customer_experience(
    con: duckdb.DuckDBPyConnection,
    event: dict[str, Any],
) -> dict[str, Any]:
    """
    Calculate customer-experience KPIs using the exact same inclusive
    event dates and exclusive end-date convention as the movement engine.
    """

    current_late = con.execute(
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
            ) AS late_rate,

            SUM(
                CASE
                    WHEN
                        order_delivered_customer_date IS NOT NULL
                        AND delivery_delay_days > 0
                    THEN 1
                    ELSE 0
                END
            ) AS late_orders,

            SUM(
                CASE
                    WHEN
                        order_delivered_customer_date IS NOT NULL
                    THEN 1
                    ELSE 0
                END
            ) AS delivered_orders

        FROM fact_orders_enriched

        WHERE
            CAST(order_purchase_timestamp AS DATE) >= ?
            AND CAST(order_purchase_timestamp AS DATE) < ?;
        """,
        [
            event["start_date"],
            event["end_exclusive"],
        ],
    ).fetchone()

    previous_late = con.execute(
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
            ) AS late_rate,

            SUM(
                CASE
                    WHEN
                        order_delivered_customer_date IS NOT NULL
                        AND delivery_delay_days > 0
                    THEN 1
                    ELSE 0
                END
            ) AS late_orders,

            SUM(
                CASE
                    WHEN
                        order_delivered_customer_date IS NOT NULL
                    THEN 1
                    ELSE 0
                END
            ) AS delivered_orders

        FROM fact_orders_enriched

        WHERE
            CAST(order_purchase_timestamp AS DATE) >= ?
            AND CAST(order_purchase_timestamp AS DATE) < ?;
        """,
        [
            event["comparison_start"],
            event["comparison_end"],
        ],
    ).fetchone()

    current_rate = (
        float(current_late[0])
        if current_late[0] is not None
        else None
    )

    previous_rate = (
        float(previous_late[0])
        if previous_late[0] is not None
        else None
    )

    rate_change = (
        current_rate - previous_rate
        if (
            current_rate is not None
            and previous_rate is not None
        )
        else None
    )

    # Review score remains a review-observation KPI and uses the
    # review's own creation date consistently.
    review_current = con.execute(
        """
        SELECT
            AVG(review_score),
            COUNT(*)
        FROM fact_reviews
        WHERE
            CAST(review_creation_date AS DATE) >= ?
            AND CAST(review_creation_date AS DATE) < ?;
        """,
        [
            event["start_date"],
            event["end_exclusive"],
        ],
    ).fetchone()

    review_previous = con.execute(
        """
        SELECT
            AVG(review_score),
            COUNT(*)
        FROM fact_reviews
        WHERE
            CAST(review_creation_date AS DATE) >= ?
            AND CAST(review_creation_date AS DATE) < ?;
        """,
        [
            event["comparison_start"],
            event["comparison_end"],
        ],
    ).fetchone()

    current_score = (
        float(review_current[0])
        if review_current[0] is not None
        else None
    )

    previous_score = (
        float(review_previous[0])
        if review_previous[0] is not None
        else None
    )

    score_change = (
        current_score - previous_score
        if (
            current_score is not None
            and previous_score is not None
        )
        else None
    )

    return {
        "event_id":
            int(event["event_id"]),

        "event_period": {
            "start":
                event["start_date"],

            "end":
                event["end_date"],
        },

        "comparison_period": {
            "start":
                event["comparison_start"],

            "end":
                event["comparison_end"],
        },

        "late_delivery_rate": {
            "current":
                current_rate,

            "previous":
                previous_rate,

            "change":
                rate_change,

            "change_pp":
                rate_change * 100
                if rate_change is not None
                else None,

            "current_late_orders":
                int(current_late[1] or 0),

            "current_delivered_orders":
                int(current_late[2] or 0),

            "previous_late_orders":
                int(previous_late[1] or 0),

            "previous_delivered_orders":
                int(previous_late[2] or 0),
        },

        "review_score": {
            "current":
                current_score,

            "previous":
                previous_score,

            "change":
                score_change,

            "current_reviews":
                int(review_current[1] or 0),

            "previous_reviews":
                int(review_previous[1] or 0),
        },
    }


def run_event_investigation(
    event_id: int,
    con: duckdb.DuckDBPyConnection | None = None,
) -> dict[str, Any]:

    own_connection = con is None

    if own_connection:
        con = connect_database()

    try:

        event = get_event(
            con,
            event_id,
        )

        movement = calculate_movement(
            con,
            event,
        )

        candidates = calculate_segment_candidates(
            con,
            event,
            movement,
        )

        drivers: list[dict[str, Any]] = []

        for candidate in candidates:

            driver_type = candidate[
                "driver_type"
            ]

            driver = candidate[
                "driver"
            ]

            contribution_share = candidate[
                "contribution_share"
            ]

            review = get_review_evidence_for_driver(
                con,
                event,
                driver_type,
                driver,
            )

            context = get_context_evidence_for_driver(
                con,
                event,
                driver_type,
                driver,
            )

            scores = calculate_confidence(
                contribution_share,
                review,
                context,
            )

            status = determine_status(
                scores["overall"],
                review,
                contribution_share,
            )

            action = get_action(
                driver_type,
                driver,
                status,
            )

            drivers.append(
                {
                    "driver_type":
                        driver_type,

                    "driver":
                        driver,

                    "observed_contribution": {
                        "gmv_change":
                            candidate["gmv_change"],

                        "share":
                            contribution_share,
                    },

                    "evidence": {
                        "review":
                            review,

                        "context":
                            context,
                    },

                    "confidence":
                        scores,

                    "status":
                        status,

                    "action":
                        action,
                }
            )

        review_total = con.execute(
            """
            SELECT
                COUNT(*)
            FROM fact_review_evidence_base
            WHERE
                (
                    (
                        CAST(review_creation_date AS DATE)
                        >= ?
                        AND CAST(review_creation_date AS DATE)
                        < ?
                    )
                    OR
                    (
                        CAST(review_creation_date AS DATE)
                        >= ?
                        AND CAST(review_creation_date AS DATE)
                        < ?
                    )
                );
            """,
            [
                event["comparison_start"],
                event["comparison_end"],
                event["start_date"],
                event["end_exclusive"],
            ],
        ).fetchone()[0]

        context_total = con.execute(
            """
            SELECT
                COUNT(*)
            FROM business_context
            WHERE
                date BETWEEN ? AND ?;
            """,
            [
                event["start_date"],
                event["end_date"],
            ],
        ).fetchone()[0]

        action_rows = []

        for driver in drivers:

            action = driver.get(
                "action",
                {},
            )

            decision = action.get(
                "decision"
            )

            if not decision:
                continue

            action_rows.append(
                {
                    "driver_type":
                        driver["driver_type"],

                    "driver":
                        driver["driver"],

                    "contribution_share":
                        driver[
                            "observed_contribution"
                        ]["share"],

                    "confidence":
                        driver[
                            "confidence"
                        ]["overall"],

                    "evidence_status":
                        driver["status"],

                    **action,
                }
            )

        review_evidence = (
            calculate_event_review_evidence(
                con,
                event,
            )
        )

        customer_experience = (
            calculate_customer_experience(
                con,
                event,
            )
        )

        return {
            "kpi": {
                "id":
                    "marketplace_gmv",

                "name":
                    "Marketplace GMV",

                "grain":
                    "order_item",

                "primary_date":
                    "order_purchase_timestamp",

                "currency":
                    "BRL",

                "currency_symbol":
                    "R$",
            },

            "movement":
                movement,

            "event": event,

            "drivers":
                drivers,

            "actions":
                action_rows,

            "data_quality": {
                "commerce_source":
                    event["source_coverage"],

                "review_text_available":
                    review_total > 0,

                "review_evidence_records":
                    int(review_total),

                "business_context_available":
                    context_total > 0,

                "business_context_records":
                    int(context_total),
            },

            "narrative": {
                "generated":
                    False,

                "requires_llm_generation":
                    True,
            },

            "review_evidence":
                review_evidence,

            "customer_experience":
                customer_experience,
        }

    finally:

        if own_connection and con is not None:
            con.close()


if __name__ == "__main__":
    print(
        "Event investigation module loaded."
    )
    print(
        "Use run_event_investigation(event_id)."
    )
