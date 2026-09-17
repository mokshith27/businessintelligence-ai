from dataclasses import dataclass
from datetime import date
from typing import List


# ============================================================
# SCENARIO DEFINITION
# ============================================================

@dataclass(frozen=True)
class ScenarioDefinition:

    scenario_id: str

    name: str

    description: str

    start_date: date

    end_date: date

    ground_truth_driver: str

    expected_direction: str

    expected_action: str

    validation_rules: List[str]


# ============================================================
# CONTROLLED SCENARIOS
# ============================================================

SCENARIOS = [

    # --------------------------------------------------------
    # SCENARIO 1
    # --------------------------------------------------------

    ScenarioDefinition(

        scenario_id="SCN_001",

        name="Promotion-driven movement",

        description=(
            "Controlled scenario where a promotion-related "
            "business context is expected to explain a KPI "
            "movement."
        ),

        start_date=date(
            2018,
            2,
            2,
        ),

        end_date=date(
            2018,
            2,
            5,
        ),

        ground_truth_driver="promotion",

        expected_direction="POSITIVE",

        expected_action=(
            "Investigate or optimize the associated "
            "marketing promotion after validating "
            "incremental impact."
        ),

        validation_rules=[

            "Promotion flag should be present "
            "during the scenario.",

            "GMV movement should be measurable.",

            "Order-volume change should be evaluated.",

            "Marketing context should provide supporting "
            "evidence before recommending action.",
        ],
    ),

    # --------------------------------------------------------
    # SCENARIO 2
    # --------------------------------------------------------

    ScenarioDefinition(

        scenario_id="SCN_002",

        name="Inventory constraint",

        description=(
            "Controlled scenario where inventory constraints "
            "are expected to suppress marketplace performance."
        ),

        start_date=date(
            2018,
            6,
            6,
        ),

        end_date=date(
            2018,
            6,
            10,
        ),

        ground_truth_driver="inventory_constraint",

        expected_direction="NEGATIVE",

        expected_action=(
            "Investigate constrained inventory and prioritize "
            "replenishment for affected products or sellers."
        ),

        validation_rules=[

            "Inventory constraint should be present "
            "during the scenario.",

            "GMV movement should be evaluated.",

            "Order-volume change should be evaluated.",

            "Inventory evidence must support any "
            "replenishment recommendation.",
        ],
    ),

    # --------------------------------------------------------
    # SCENARIO 3
    # --------------------------------------------------------

    ScenarioDefinition(

        scenario_id="SCN_003",

        name="Promotion-driven movement 2",

        description=(
            "Second controlled promotion scenario used to "
            "test whether the engine behaves consistently "
            "across different periods."
        ),

        start_date=date(
            2018,
            7,
            18,
        ),

        end_date=date(
            2018,
            7,
            20,
        ),

        ground_truth_driver="promotion",

        expected_direction="POSITIVE",

        expected_action=(
            "Investigate whether the promotion created "
            "incremental demand and determine whether it "
            "should be continued or optimized."
        ),

        validation_rules=[

            "Promotion context should be present.",

            "GMV movement should be measurable.",

            "Order-volume change should be evaluated.",

            "Any marketing action should remain "
            "subject to evidence validation.",
        ],
    ),
]


# ============================================================
# HELPERS
# ============================================================

def get_scenario(
    scenario_id: str,
) -> ScenarioDefinition:

    for scenario in SCENARIOS:

        if scenario.scenario_id == scenario_id:

            return scenario

    raise ValueError(
        f"Unknown scenario_id: {scenario_id}"
    )


def get_all_scenarios():

    return SCENARIOS