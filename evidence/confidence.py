from pathlib import Path
import duckdb


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


# ============================================================
# THRESHOLDS
# ============================================================

MIN_REVIEW_RECORDS = 5

HIGH_CONFIDENCE = 0.75
MODERATE_CONFIDENCE = 0.55
LOW_CONFIDENCE = 0.35

MIN_DRIVER_CONTRIBUTION = 0.05


# ============================================================
# DATABASE
# ============================================================

def connect_database():

    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"DuckDB database not found:\n{DB_PATH}"
        )

    return duckdb.connect(str(DB_PATH))


# ============================================================
# TARGET EVENT
# ============================================================

def get_target_event(con):

    return con.execute(
        """
        SELECT

            event_group,
            event_start_date,
            event_end_date,
            direction,
            event_type,
            investigation_priority

        FROM fact_gmv_events

        WHERE
            event_type = 'BUSINESS_MOVEMENT'

            AND investigation_priority = 'HIGH'

        ORDER BY
            event_priority_score DESC,
            event_start_date

        LIMIT 1;
        """
    ).fetchone()


# ============================================================
# EXTRACT OBSERVED CONTRIBUTIONS
# ============================================================

def get_candidates(con, event_id):

    rows = con.execute(
        """
        SELECT

            event_id,

            driver_type,

            driver,

            CAST(
                JSON_EXTRACT(
                    evidence_json,
                    '$.observed_contribution.gmv_change'
                ) AS DOUBLE
            ) AS gmv_change,

            CAST(
                JSON_EXTRACT(
                    evidence_json,
                    '$.observed_contribution.contribution_share'
                ) AS DOUBLE
            ) AS contribution_share

        FROM fact_evidence_records

        WHERE
            event_id = ?

        ORDER BY
            ABS(
                CAST(
                    JSON_EXTRACT(
                        evidence_json,
                        '$.observed_contribution.contribution_share'
                    ) AS DOUBLE
                )
            ) DESC;
        """,
        [event_id],
    ).fetchall()

    return rows


# ============================================================
# REVIEW EVIDENCE FOR ONE DRIVER
# ============================================================

def get_review_evidence(
    con,
    event_id,
    dimension,
    driver,
    direction
):

    rows = con.execute(
        """
        SELECT

            aspect,
            sentiment,

            SUM(
                event_count
            ) AS event_count,

            SUM(
                comparison_count
            ) AS comparison_count

        FROM fact_event_review_evidence

        WHERE
            event_id = ?

            AND dimension = ?

            AND driver = ?

        GROUP BY
            aspect,
            sentiment;
        """,
        [
            event_id,
            dimension,
            driver,
        ],
    ).fetchall()

    if not rows:

        return {
            "available": False,
            "event_records": 0,
            "comparison_records": 0,
            "event_positive_share": None,
            "comparison_positive_share": None,
            "event_negative_share": None,
            "comparison_negative_share": None,
            "directional_support": 0.0,
            "status": "NO_EVIDENCE",
        }

    event_total = sum(
        row[2]
        for row in rows
    )

    comparison_total = sum(
        row[3]
        for row in rows
    )

    event_positive = sum(
        row[2]
        for row in rows
        if str(row[1]).lower()
        == "positive"
    )

    event_negative = sum(
        row[2]
        for row in rows
        if str(row[1]).lower()
        == "negative"
    )

    comparison_positive = sum(
        row[3]
        for row in rows
        if str(row[1]).lower()
        == "positive"
    )

    comparison_negative = sum(
        row[3]
        for row in rows
        if str(row[1]).lower()
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

    # --------------------------------------------------------
    # Directional interpretation
    #
    # Positive KPI movement:
    #   more positive / fewer negative = supportive
    #
    # Negative KPI movement:
    #   more negative / fewer positive = supportive
    #
    # This is CORROBORATION, not causality.
    # --------------------------------------------------------

    if direction == "POSITIVE":

        directional_support = (
            positive_change
            - negative_change
        )

    else:

        directional_support = (
            negative_change
            - positive_change
        )

    # Keep within [-1, 1]
    directional_support = max(
        -1.0,
        min(
            1.0,
            directional_support
        )
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
        "available": True,

        "event_records": event_total,

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


# ============================================================
# BUSINESS CONTEXT EVIDENCE
# ============================================================

def get_context_evidence(
    con,
    dimension,
    driver,
    event_start,
    event_end
):

    # --------------------------------------------------------
    # State driver
    # --------------------------------------------------------

    if dimension == "customer_state":

        result = con.execute(
            """
            SELECT

                COUNT(*) AS rows_found,

                COUNT_IF(
                    promotion_flag = 1
                ) AS promotion_rows,

                COUNT_IF(
                    inventory_status = 'constrained'
                ) AS constrained_rows,

                AVG(
                    competitor_price_index
                ) AS avg_competitor_index,

                COUNT_IF(
                    external_event_flag = 1
                ) AS external_event_rows

            FROM business_context

            WHERE
                region = ?

                AND date BETWEEN ?
                AND ?;
            """,
            [
                driver,
                event_start,
                event_end,
            ],
        ).fetchone()

    # --------------------------------------------------------
    # Category driver
    # --------------------------------------------------------

    elif dimension == "category":

        result = con.execute(
            """
            SELECT

                COUNT(*) AS rows_found,

                COUNT_IF(
                    promotion_flag = 1
                ) AS promotion_rows,

                COUNT_IF(
                    inventory_status = 'constrained'
                ) AS constrained_rows,

                AVG(
                    competitor_price_index
                ) AS avg_competitor_index,

                COUNT_IF(
                    external_event_flag = 1
                ) AS external_event_rows

            FROM business_context

            WHERE
                category = ?

                AND date BETWEEN ?
                AND ?;
            """,
            [
                driver,
                event_start,
                event_end,
            ],
        ).fetchone()

    else:

        return {
            "available": False,
            "status": "NOT_IMPLEMENTED"
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
            "available": False,
            "status": "NO_CONTEXT_EVIDENCE"
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
            competitor_index - 1.0
        ) >= 0.03
    ):
        evidence_types += 1

    return {
        "available": True,

        "rows_found":
            rows_found,

        "promotion_rows":
            promotion_rows,

        "constrained_rows":
            constrained_rows,

        "avg_competitor_price_index":
            competitor_index,

        "external_event_rows":
            external_event_rows,

        "evidence_types":
            evidence_types,

        "status":
            "CONTEXT_AVAILABLE"
            if evidence_types > 0
            else "NO_STRONG_CONTEXT_SIGNAL",
    }


# ============================================================
# CONFIDENCE CALCULATION
# ============================================================

def calculate_confidence(
    contribution_share,
    review,
    context
):

    # --------------------------------------------------------
    # 1. Structural evidence
    # --------------------------------------------------------

    structural_score = min(
        1.0,
        abs(
            contribution_share
        ) / 0.50
    )

    # --------------------------------------------------------
    # 2. Review evidence
    # --------------------------------------------------------

    if (
        review["status"]
        in {
            "SUPPORTING",
            "CONTRADICTING",
            "NEUTRAL",
        }
    ):

        review_score = (
            abs(
                review[
                    "directional_support"
                ]
            )
        )

    else:

        review_score = 0.0

    # --------------------------------------------------------
    # 3. Context evidence
    # --------------------------------------------------------

    if context.get(
        "available",
        False
    ):

        context_score = min(
            1.0,
            context.get(
                "evidence_types",
                0
            ) / 2.0
        )

    else:

        context_score = 0.0

    # --------------------------------------------------------
    # 4. Evidence source count
    # --------------------------------------------------------

    independent_sources = 1

    if review.get(
        "available",
        False
    ):

        independent_sources += 1

    if context.get(
        "available",
        False
    ):

        independent_sources += 1

    # --------------------------------------------------------
    # Base confidence
    #
    # This is deliberately conservative:
    # structural contribution is strongest,
    # secondary evidence can increase confidence.
    # --------------------------------------------------------

    confidence = (

        0.60 * structural_score

        +

        0.20 * review_score

        +

        0.20 * context_score

    )

    # --------------------------------------------------------
    # Contradiction penalty
    # --------------------------------------------------------

    if (
        review["status"]
        == "CONTRADICTING"
    ):

        confidence *= 0.65

    # --------------------------------------------------------
    # Confidence cannot imply strong root cause
    # when only one evidence family exists.
    # --------------------------------------------------------

    if independent_sources == 1:

        confidence = min(
            confidence,
            0.55
        )

    return {
        "confidence":
            round(
                confidence,
                3
            ),

        "structural_score":
            round(
                structural_score,
                3
            ),

        "review_score":
            round(
                review_score,
                3
            ),

        "context_score":
            round(
                context_score,
                3
            ),

        "independent_sources":
            independent_sources,
    }


# ============================================================
# FINAL STATUS
# ============================================================

def determine_status(
    confidence,
    review,
    context,
    contribution_share
):

    # Very small contribution is not a serious candidate.
    if abs(contribution_share) < MIN_DRIVER_CONTRIBUTION:

        return "WEAK_DRIVER"

    # Explicit contradiction plus weak confidence.
    if (
        review["status"]
        == "CONTRADICTING"
        and confidence < MODERATE_CONFIDENCE
    ):

        return "CONTRADICTED"

    # Strong enough evidence from multiple sources.
    if confidence >= HIGH_CONFIDENCE:

        return "SUPPORTED"

    if confidence >= MODERATE_CONFIDENCE:

        return "PLAUSIBLE"

    if confidence >= LOW_CONFIDENCE:

        return "WEAK"

    return "ABSTAIN"


# ============================================================
# BUILD CONFIDENCE TABLE
# ============================================================

def build_confidence_table(con):

    event = get_target_event(con)

    if event is None:

        print(
            "No target event found."
        )

        return

    (
        event_id,
        event_start,
        event_end,
        direction,
        event_type,
        investigation_priority,
    ) = event

    candidates = get_candidates(
        con,
        event_id
    )

    records = []

    for (
        candidate_event_id,
        driver_type,
        driver,
        gmv_change,
        contribution_share,
    ) in candidates:

        # -----------------------------------------------
        # Review evidence currently available for:
        # customer state + category
        # -----------------------------------------------

        if driver_type in {
            "customer_state",
            "category",
        }:

            review = get_review_evidence(
                con,
                event_id,
                driver_type,
                driver,
                direction,
            )

        else:

            review = {
                "available": False,
                "status": "NOT_AVAILABLE",
                "directional_support": 0.0,
            }

        # -----------------------------------------------
        # Context evidence
        # -----------------------------------------------

        context = get_context_evidence(
            con,
            driver_type,
            driver,
            event_start,
            event_end,
        )

        # -----------------------------------------------
        # Confidence
        # -----------------------------------------------

        scores = calculate_confidence(
            contribution_share,
            review,
            context,
        )

        status = determine_status(
            scores["confidence"],
            review,
            context,
            contribution_share,
        )

        records.append(
            (
                event_id,
                driver_type,
                driver,
                gmv_change,
                contribution_share,
                review["status"],
                review.get(
                    "event_records",
                    0
                ),
                review.get(
                    "comparison_records",
                    0
                ),
                review.get(
                    "directional_support",
                    0.0
                ),
                context.get(
                    "status",
                    "UNKNOWN"
                ),
                scores["confidence"],
                scores["structural_score"],
                scores["review_score"],
                scores["context_score"],
                scores["independent_sources"],
                status,
            )
        )

    # --------------------------------------------------------
    # Save
    # --------------------------------------------------------

    con.execute(
        """
        DROP TABLE IF EXISTS
        fact_driver_confidence;
        """
    )

    con.execute(
        """
        CREATE TABLE fact_driver_confidence (

            event_id INTEGER,

            driver_type VARCHAR,

            driver VARCHAR,

            gmv_change DOUBLE,

            contribution_share DOUBLE,

            review_status VARCHAR,

            review_event_records BIGINT,

            review_comparison_records BIGINT,

            review_directional_support DOUBLE,

            context_status VARCHAR,

            confidence DOUBLE,

            structural_score DOUBLE,

            review_score DOUBLE,

            context_score DOUBLE,

            independent_sources INTEGER,

            final_status VARCHAR
        );
        """
    )

    con.executemany(
        """
        INSERT INTO fact_driver_confidence
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?
        );
        """,
        records,
    )

    print(
        f"\n[OK] Confidence records created: "
        f"{len(records):,}"
    )


# ============================================================
# DISPLAY
# ============================================================

def show_confidence(con):

    print("\n" + "=" * 100)
    print("DRIVER CONFIDENCE RESULTS")
    print("=" * 100)

    df = con.execute(
        """
        SELECT

            driver_type,

            driver,

            ROUND(
                gmv_change,
                2
            ) AS gmv_change,

            ROUND(
                contribution_share * 100,
                2
            ) AS contribution_pct,

            review_status,

            review_event_records,

            review_comparison_records,

            ROUND(
                review_directional_support,
                3
            ) AS review_support,

            context_status,

            ROUND(
                confidence,
                3
            ) AS confidence,

            independent_sources,

            final_status

        FROM fact_driver_confidence

        ORDER BY
            confidence DESC,
            ABS(
                contribution_share
            ) DESC

        LIMIT 20;
        """
    ).fetchdf()

    if df.empty:

        print(
            "No confidence results."
        )

        return

    print(
        df.to_string(
            index=False
        )
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n")
    print("=" * 100)
    print("BusinessIntelligence.ai")
    print("CONFIDENCE + ABSTENTION ENGINE")
    print("=" * 100)

    con = connect_database()

    try:

        build_confidence_table(
            con
        )

        show_confidence(
            con
        )

        print("\n" + "=" * 100)
        print("CONFIDENCE ENGINE COMPLETE")
        print("=" * 100)

    finally:

        con.close()


if __name__ == "__main__":
    main()