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
# ACTION THRESHOLDS
# ============================================================

ACTIONABLE_CONFIDENCE = 0.55
INVESTIGATION_CONFIDENCE = 0.25

MIN_ACTION_CONTRIBUTION = 0.05


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
# ACTION RULES
# ============================================================

def get_action_rule(
    driver_type,
    driver,
    final_status,
):
    """
    Maps an analytical driver into a business lever.

    IMPORTANT:
    These are decision rules, not LLM-generated causes.
    """

    # --------------------------------------------------------
    # Contradicted hypothesis
    # --------------------------------------------------------

    if final_status == "CONTRADICTED":

        return {
            "lever": None,

            "action": (
                "Do not act on this hypothesis; "
                "treat it as contradicted by the "
                "available evidence."
            ),

            "owner": "Analyst",

            "monitor": (
                "Re-evaluate if new evidence becomes available."
            ),

            "action_type": "DO_NOT_ACT",
        }

    # --------------------------------------------------------
    # Abstention
    # --------------------------------------------------------

    if final_status == "ABSTAIN":

        return {
            "lever": None,

            "action": (
                "Collect additional evidence before "
                "taking an operational action."
            ),

            "owner": "Analyst",

            "monitor": (
                "Refresh the missing or insufficient "
                "evidence source."
            ),

            "action_type": "ABSTAIN",
        }

    # --------------------------------------------------------
    # Customer state
    # --------------------------------------------------------

    if driver_type == "customer_state":

        return {
            "lever": "regional demand / operations",

            "action": (
                f"Investigate the drivers of the KPI "
                f"movement among customers in {driver}, "
                f"including demand, availability and "
                f"operational performance."
            ),

            "owner": "Regional Operations",

            "monitor": (
                f"Monitor orders, AOV and customer "
                f"experience metrics in {driver}."
            ),

            "action_type": (
                "INVESTIGATE"
                if final_status != "SUPPORTED"
                else "ACT"
            ),
        }

    # --------------------------------------------------------
    # Category
    # --------------------------------------------------------

    if driver_type == "category":

        return {
            "lever": "category demand / assortment",

            "action": (
                f"Investigate demand, availability, "
                f"pricing and assortment changes in "
                f"the {driver} category."
            ),

            "owner": "Category Management",

            "monitor": (
                f"Monitor category orders, AOV and "
                f"customer feedback for {driver}."
            ),

            "action_type": (
                "INVESTIGATE"
                if final_status != "SUPPORTED"
                else "ACT"
            ),
        }

    # --------------------------------------------------------
    # Seller
    # --------------------------------------------------------

    if driver_type == "seller":

        return {
            "lever": "seller performance",

            "action": (
                f"Investigate seller-level changes "
                f"affecting {driver}, including availability, "
                f"delivery and product performance."
            ),

            "owner": "Seller Operations",

            "monitor": (
                f"Monitor orders, delivery performance "
                f"and review scores for {driver}."
            ),

            "action_type": (
                "INVESTIGATE"
                if final_status != "SUPPORTED"
                else "ACT"
            ),
        }

    return {
        "lever": None,

        "action": (
            "Investigate the driver using available "
            "business evidence."
        ),

        "owner": "Analyst",

        "monitor": (
            "Monitor the KPI and refresh supporting evidence."
        ),

        "action_type": "INVESTIGATE",
    }


# ============================================================
# GENERATE ACTIONS
# ============================================================

def build_actions(con):

    print("\n[BUILD] Generating business actions")

    rows = con.execute(
        """
        SELECT

            event_id,

            driver_type,

            driver,

            gmv_change,

            contribution_share,

            confidence,

            independent_sources,

            final_status

        FROM fact_driver_confidence

        WHERE
            ABS(contribution_share)
            >= ?
        ORDER BY
            confidence DESC,
            ABS(contribution_share) DESC;
        """,
        [
            MIN_ACTION_CONTRIBUTION
        ],
    ).fetchall()

    action_rows = []

    for row in rows:

        (
            event_id,
            driver_type,
            driver,
            gmv_change,
            contribution_share,
            confidence,
            independent_sources,
            final_status,
        ) = row

        rule = get_action_rule(
            driver_type,
            driver,
            final_status,
        )

        # ----------------------------------------------------
        # Actionability decision
        # ----------------------------------------------------

        if final_status == "SUPPORTED":

            decision = "ACTIONABLE"

        elif final_status == "PLAUSIBLE":

            decision = "ACTION_WITH_VALIDATION"

        elif final_status == "WEAK":

            decision = "INVESTIGATE"

        elif final_status == "CONTRADICTED":

            decision = "DO_NOT_ACT"

        else:

            decision = "ABSTAIN"

        action_rows.append(
            (
                event_id,
                driver_type,
                driver,
                gmv_change,
                contribution_share,
                confidence,
                independent_sources,
                final_status,
                decision,
                rule["lever"],
                rule["action"],
                rule["owner"],
                rule["monitor"],
                rule["action_type"],
            )
        )

    # --------------------------------------------------------
    # Create table
    # --------------------------------------------------------

    con.execute(
        """
        DROP TABLE IF EXISTS fact_recommended_actions;
        """
    )

    con.execute(
        """
        CREATE TABLE fact_recommended_actions (

            event_id INTEGER,

            driver_type VARCHAR,

            driver VARCHAR,

            gmv_change DOUBLE,

            contribution_share DOUBLE,

            confidence DOUBLE,

            independent_sources INTEGER,

            evidence_status VARCHAR,

            decision VARCHAR,

            controllable_lever VARCHAR,

            action VARCHAR,

            owner VARCHAR,

            monitoring_plan VARCHAR,

            action_type VARCHAR
        );
        """
    )

    if action_rows:

        con.executemany(
            """
            INSERT INTO fact_recommended_actions
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?
            );
            """,
            action_rows,
        )

    print(
        f"[OK] Actions generated: "
        f"{len(action_rows):,}"
    )


# ============================================================
# DISPLAY
# ============================================================

def show_actions(con):

    print("\n" + "=" * 100)
    print("RECOMMENDED BUSINESS ACTIONS")
    print("=" * 100)

    df = con.execute(
        """
        SELECT

            driver_type,

            driver,

            ROUND(
                contribution_share * 100,
                2
            ) AS contribution_pct,

            ROUND(
                confidence,
                3
            ) AS confidence,

            evidence_status,

            decision,

            controllable_lever,

            owner,

            action,

            monitoring_plan

        FROM fact_recommended_actions

        ORDER BY
            confidence DESC,
            ABS(
                contribution_share
            ) DESC

        LIMIT 15;
        """
    ).fetchdf()

    if df.empty:

        print(
            "No action recommendations available."
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
    print("ACTION ENGINE")
    print("=" * 100)

    con = connect_database()

    try:

        build_actions(con)

        show_actions(con)

        print("\n" + "=" * 100)
        print("ACTION ENGINE COMPLETE")
        print("=" * 100)

    finally:

        con.close()


if __name__ == "__main__":
    main()