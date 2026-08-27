from pathlib import Path
import json
import sys

# ============================================================
# WINDOWS UTF-8 OUTPUT
# ============================================================

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(
        encoding="utf-8",
        errors="replace",
    )

if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(
        encoding="utf-8",
        errors="replace",
    )


# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

INSIGHT_PATH = (
    PROJECT_ROOT
    / "data"
    / "insights"
    / "latest_insight.json"
)

CAUSAL_PATH = (
    PROJECT_ROOT
    / "data"
    / "causal"
    / "causal_production_status.json"
)


# ============================================================
# ROLE DEFINITIONS
# ============================================================

ROLE_PERMISSIONS = {

    "executive": {

        "allowed_sections": {
            "kpi",
            "movement",
            "event",
            "top_drivers",
            "confidence",
            "actions",
            "executive_story",
            "llm_governance",
        },

        "restricted_fields": {

            "customer_id",
            "customer_unique_id",
            "seller_id",
            "email",
            "phone",
            "address",
        },

        "max_driver_count":
            5,
    },

    "operations": {

        "allowed_sections": {
            "kpi",
            "movement",
            "event",
            "top_drivers",
            "confidence",
            "actions",
            "operational_story",
            "llm_governance",
        },

        "restricted_fields": {

            "customer_id",
            "customer_unique_id",
            "email",
            "phone",
            "address",
        },

        "max_driver_count":
            10,
    },

    "analyst": {

        "allowed_sections": {
            "kpi",
            "movement",
            "event",
            "top_drivers",
            "confidence",
            "actions",
            "executive_story",
            "operational_story",
            "lineage",
            "data_quality",
            "causal",
            "llm_governance",
        },

        "restricted_fields": {

            "email",
            "phone",
            "address",
        },

        "max_driver_count":
            100,
    },
}


# ============================================================
# LOAD DATA
# ============================================================

def load_json(
    path,
):

    if not path.exists():

        raise FileNotFoundError(
            f"File not found:\n{path}"
        )

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


# ============================================================
# FIELD SANITIZATION
# ============================================================

def sanitize_record(
    record,
    restricted_fields,
):

    if not isinstance(
        record,
        dict,
    ):

        return record

    sanitized = {}

    for key, value in record.items():

        key_lower = (
            str(key).lower()
        )

        if key_lower in {
            str(field).lower()
            for field in restricted_fields
        }:

            continue

        # ----------------------------------------------------
        # Recursively sanitize nested dictionaries
        # ----------------------------------------------------

        if isinstance(
            value,
            dict,
        ):

            sanitized[key] = (
                sanitize_record(
                    value,
                    restricted_fields,
                )
            )

        # ----------------------------------------------------
        # Recursively sanitize lists
        # ----------------------------------------------------

        elif isinstance(
            value,
            list,
        ):

            sanitized[key] = [

                sanitize_record(
                    item,
                    restricted_fields,
                )
                if isinstance(
                    item,
                    dict,
                )
                else item

                for item in value
            ]

        else:

            sanitized[key] = value

    return sanitized


# ============================================================
# DRIVER FILTER
# ============================================================

def filter_drivers(
    drivers,
    role,
):

    permissions = ROLE_PERMISSIONS[
        role
    ]

    max_count = permissions[
        "max_driver_count"
    ]

    restricted_fields = permissions[
        "restricted_fields"
    ]

    filtered = []

    for driver in drivers[:
        max_count
    ]:

        filtered.append(
            sanitize_record(
                driver,
                restricted_fields,
            )
        )

    return filtered


# ============================================================
# ROLE VIEW
# ============================================================

def build_role_view(
    insight,
    role,
    causal_status=None,
):

    role = role.lower()

    if role not in ROLE_PERMISSIONS:
        raise ValueError(
            f"Unsupported role: {role}"
        )

    permissions = ROLE_PERMISSIONS[role]

    allowed = permissions[
        "allowed_sections"
    ]

    restricted_fields = permissions[
        "restricted_fields"
    ]

    view = {}

    # ========================================================
    # BASIC SECTIONS
    # ========================================================

    if "kpi" in allowed:

        view["kpi"] = sanitize_record(
            insight.get(
                "kpi",
                {},
            ),
            restricted_fields,
        )

    if "movement" in allowed:

        view["movement"] = sanitize_record(
            insight.get(
                "movement",
                {},
            ),
            restricted_fields,
        )

    if "event" in allowed:

        view["event"] = sanitize_record(
            insight.get(
                "event",
                {},
            ),
            restricted_fields,
        )

    # ========================================================
    # DRIVERS
    # ========================================================

    drivers = insight.get(
        "drivers",
        [],
    )

    filtered_drivers = filter_drivers(
        drivers,
        role,
    )

    if "top_drivers" in allowed:

        view["drivers"] = filtered_drivers

    # ========================================================
    # DERIVE CONFIDENCE FROM DRIVERS
    # ========================================================

    if "confidence" in allowed:

        confidence_records = []

        for driver in filtered_drivers:

            confidence = driver.get(
                "confidence",
                {},
            )

            confidence_records.append(
                {
                    "driver_type":
                        driver.get(
                            "driver_type"
                        ),

                    "driver":
                        driver.get(
                            "driver"
                        ),

                    "overall":
                        confidence.get(
                            "overall"
                        ),

                    "structural":
                        confidence.get(
                            "structural"
                        ),

                    "review":
                        confidence.get(
                            "review"
                        ),

                    "context":
                        confidence.get(
                            "context"
                        ),

                    "independent_sources":
                        confidence.get(
                            "independent_sources"
                        ),

                    "status":
                        driver.get(
                            "status"
                        ),
                }
            )

        view["confidence"] = (
            confidence_records
        )

    # ========================================================
    # DERIVE ACTIONS FROM DRIVERS
    # ========================================================

    if "actions" in allowed:

        action_records = []

        for driver in filtered_drivers:

            action = driver.get(
                "action",
                {},
            )

            if not action:
                continue

            action_records.append(
                {
                    "driver_type":
                        driver.get(
                            "driver_type"
                        ),

                    "driver":
                        driver.get(
                            "driver"
                        ),

                    "decision":
                        action.get(
                            "decision"
                        ),

                    "lever":
                        action.get(
                            "lever"
                        ),

                    "action":
                        action.get(
                            "action"
                        ),

                    "owner":
                        action.get(
                            "owner"
                        ),

                    "monitoring_plan":
                        action.get(
                            "monitoring_plan"
                        ),

                    "action_type":
                        action.get(
                            "action_type"
                        ),
                }
            )

        view["actions"] = (
            action_records
        )

    # ========================================================
    # DATA QUALITY
    # ========================================================

    if "data_quality" in allowed:

        view["data_quality"] = sanitize_record(
            insight.get(
                "data_quality",
                {},
            ),
            restricted_fields,
        )

    # ========================================================
    # LINEAGE
    # ========================================================

    if "lineage" in allowed:

        view["lineage"] = sanitize_record(
            insight.get(
                "lineage",
                {},
            ),
            restricted_fields,
        )

    # ========================================================
    # CAUSAL
    # ========================================================

    if (
        "causal" in allowed
        and causal_status is not None
    ):

        view["causal"] = sanitize_record(
            causal_status,
            restricted_fields,
        )

    # ========================================================
    # LLM GOVERNANCE
    # ========================================================
    #
    # The current latest_insight.json does not contain
    # llm_policy, so provide the governed policy explicitly.
    # This is policy metadata, not analytical data.
    # ========================================================

    if "llm_governance" in allowed:

        view["llm_governance"] = {

            "quantitative_truth_source":
                "deterministic analytical layer",

            "allowed_llm_tasks": [

                "narrative synthesis",
                "persona adaptation",
                "natural language explanation",
                "uncertainty wording",
            ],

            "forbidden_llm_tasks": [

                "calculating KPI values",
                "overriding analytical results",
                "inventing causal relationships",
                "overriding confidence or abstention",
                "fabricating evidence",
            ],
        }

    # ========================================================
    # SECURITY METADATA
    # ========================================================

    view["_security"] = {

        "role":
            role,

        "restricted_fields":
            sorted(
                restricted_fields
            ),

        "allowed_sections":
            sorted(
                allowed
            ),
    }

    return view

# ============================================================
# SECURITY TEST
# ============================================================

def test_role_filter():

    print("\n")
    print("=" * 100)
    print("BusinessIntelligence.ai")
    print("ROLE-BASED SECURITY TEST")
    print("=" * 100)

    insight = load_json(
        INSIGHT_PATH
    )

    causal_status = None

    if CAUSAL_PATH.exists():

        causal_status = load_json(
            CAUSAL_PATH
        )

    for role in [
        "executive",
        "operations",
        "analyst",
    ]:

        view = build_role_view(
            insight,
            role,
            causal_status,
        )

        print("\n")
        print(
            f"ROLE: "
            f"{role.upper()}"
        )

        print(
            "-" * 60
        )

        print(
            "Visible sections:"
        )

        for section in view:

            if not section.startswith(
                "_"
            ):

                print(f"  [OK] {section}")

        print(
            "\nRestricted fields:"
        )

        for field in view[
            "_security"
        ][
            "restricted_fields"
        ]:

            print(f"  [RESTRICTED] {field}")


# ============================================================
# MAIN
# ============================================================

def main():

    test_role_filter()

    print("\n")
    print("=" * 100)
    print(
        "ROLE FILTER COMPLETE"
    )
    print("=" * 100)


if __name__ == "__main__":
    main()