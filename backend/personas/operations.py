def build_operations_view(insight):

    drivers = insight["drivers"]

    ranked_drivers = sorted(
        drivers,
        key=lambda x: abs(
            x["observed_contribution"]["share"]
        ),
        reverse=True,
    )

    operational_drivers = []

    for driver in ranked_drivers[:10]:

        action = driver["action"]

        operational_drivers.append(
            {
                "driver_type":
                    driver["driver_type"],

                "driver":
                    driver["driver"],

                "contribution_pct":
                    round(
                        driver[
                            "observed_contribution"
                        ]["share"]
                        * 100,
                        2,
                    ),

                "gmv_change":
                    driver[
                        "observed_contribution"
                    ]["gmv_change"],

                "confidence":
                    driver[
                        "confidence"
                    ]["overall"],

                "evidence_status":
                    driver["status"],

                "decision":
                    action[
                        "decision"
                    ],

                "owner":
                    action["owner"],

                "action":
                    action["action"],

                "monitoring_plan":
                    action[
                        "monitoring_plan"
                    ],
            }
        )

    return {

        "persona":
            "operations",

        "event_period":
            {
                "start":
                    insight[
                        "event"
                    ]["start_date"],

                "end":
                    insight[
                        "event"
                    ]["end_date"],
            },

        "kpi":
            insight[
                "kpi"
            ]["name"],

        "drivers":
            operational_drivers,

        "data_quality":
            insight[
                "data_quality"
            ],

        "operational_guidance":

            (
                "Do not execute high-impact "
                "interventions for hypotheses "
                "marked ABSTAIN or CONTRADICTED. "
                "Use INVESTIGATE recommendations "
                "to collect the missing evidence."
            ),
    }