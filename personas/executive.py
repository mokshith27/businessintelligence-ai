def build_executive_view(insight):

    movement = insight["movement"]
    event = insight["event"]
    drivers = insight["drivers"]

    # --------------------------------------------------------
    # Top actionable/meaningful drivers
    # --------------------------------------------------------

    ranked_drivers = sorted(
        drivers,
        key=lambda x: abs(
            x["observed_contribution"]["share"]
        ),
        reverse=True,
    )

    top_drivers = []

    for driver in ranked_drivers[:5]:

        top_drivers.append(
            {
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

                "confidence":
                    driver[
                        "confidence"
                    ]["overall"],

                "status":
                    driver["status"],

                "decision":
                    driver[
                        "action"
                    ]["decision"],
            }
        )

    # --------------------------------------------------------
    # Executive summary data
    # --------------------------------------------------------

    return {

        "persona":
            "executive",

        "persona_role":
            "Head of Marketplace Operations",

        "vertical":
            "Marketplace / e-commerce operations",

        "headline":

            (
                f"GMV "
                f"{'increased' if movement['gmv_change'] > 0 else 'decreased'} "
                f"by "
                f"{abs(movement['gmv_change']):,.0f} "
                f"during the event."
            ),

        "business_impact":
            movement[
                "gmv_change"
            ],

        "primary_driver":

            (
                "order volume"
                if abs(
                    movement[
                        "volume_effect"
                    ]
                )
                >= abs(
                    movement[
                        "aov_effect"
                    ]
                )
                else "AOV"
            ),

        "volume_effect":
            movement[
                "volume_effect"
            ],

        "aov_effect":
            movement[
                "aov_effect"
            ],

        "top_drivers":
            top_drivers,

        "confidence_message":

            (
                "The engine has evidence for "
                "where the movement occurred, "
                "but does not have sufficient "
                "evidence to claim a verified "
                "root cause."
            ),

        "recommended_focus":

            (
                "Prioritize investigation of the "
                "highest-contribution driver before "
                "taking a major intervention."
            ),
    }