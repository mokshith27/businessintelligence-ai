import requests
import streamlit as st
import plotly.graph_objects as go


# ============================================================
# CONFIG
# ============================================================

API_BASE_URL = "http://127.0.0.1:8000"


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="BusinessIntelligence.ai",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

def render_story(story):

    if not story:
        return

    lines = story.splitlines()

    for line in lines:

        line = line.strip()

        if not line:
            continue

        if (
            line.startswith("HEADLINE:")
            or line.startswith("WHAT CHANGED:")
            or line.startswith("MAIN DRIVER:")
            or line.startswith("WHERE:")
            or line.startswith("WHAT WE KNOW:")
            or line.startswith("NEXT STEP:")
            or line.startswith("KPI MOVEMENT:")
            or line.startswith("ANALYTICAL DECOMPOSITION:")
            or line.startswith("TOP INVESTIGATION AREAS:")
            or line.startswith("EVIDENCE:")
            or line.startswith("ACTIONS:")
            or line.startswith("DATA QUALITY:")
        ):

            heading = line.rstrip(":")

            st.markdown(
                f"### {heading}"
            )

        elif line.startswith("- "):

            st.markdown(
                line
            )

        else:

            # Escape Markdown-special characters that can
            # interfere with currency/math rendering.
            safe_line = (
                line
                .replace("$", "\\$")
            )

            st.write(
                safe_line
            )

# ============================================================
# API HELPERS
# ============================================================

# @st.cache_data(ttl=30)
def api_get(endpoint):

    try:

        response = requests.get(
            f"{API_BASE_URL}{endpoint}",
            timeout=10,
        )

        response.raise_for_status()

        return response.json()

    except requests.exceptions.RequestException as exc:

        st.error(
            f"Backend connection failed: {exc}"
        )

        return None


# ============================================================
# FORMATTING
# ============================================================

def format_brl(value):

    if value is None:
        return "—"

    value = float(value)

    sign = "-" if value < 0 else ""

    value = abs(value)

    if value >= 1_000_000:

        return f"{sign}R${value / 1_000_000:.2f}M"

    if value >= 1_000:

        return f"{sign}R${value / 1_000:.1f}K"

    return f"{sign}R${value:,.2f}"


def format_pct(value):

    if value is None:
        return "—"

    return f"{float(value):+.1f}%"


def status_badge(status):

    mapping = {

        "SUPPORTED": "🟢 SUPPORTED",

        "PLAUSIBLE": "🟡 PLAUSIBLE",

        "WEAK": "🟠 WEAK",

        "ABSTAIN": "⚪ ABSTAIN",

        "CONTRADICTED": "🔴 CONTRADICTED",

    }

    return mapping.get(
        str(status).upper(),
        str(status),
    )


# ============================================================
# LOAD DATA
# ============================================================

insight = api_get(
    "/api/insights/latest"
)

executive_story = api_get(
    "/api/insights/latest/executive"
)

operations_story = api_get(
    "/api/insights/latest/operations"
)

actions_response = api_get(
    "/api/actions"
)

telemetry = api_get(
    "/api/telemetry"
)

events_response = api_get(
    "/api/events?limit=25"
)


if insight is None:

    st.stop()


# ============================================================
# EXTRACT INSIGHT
# ============================================================

kpi = insight["kpi"]

event = insight["event"]

movement = insight["movement"]

drivers = insight.get(
    "drivers",
    []
)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.title(
        "BusinessIntelligence.ai"
    )

    st.caption(
        "KPI Intelligence → Action"
    )

    st.divider()

    persona = st.radio(
        "View",
        [
            "Executive",
            "Operations",
        ],
    )

    st.divider()

    st.subheader(
        "Current Event"
    )

    st.write(
        f"**{event['start_date']} → "
        f"{event['end_date']}**"
    )

    st.write(
        f"Priority: "
        f"**{event['investigation_priority']}**"
    )

    st.write(
        f"Direction: "
        f"**{event['direction']}**"
    )

    st.caption(
        "All values are derived from the "
        "governed analytical insight."
    )


# ============================================================
# HEADER
# ============================================================

st.title(
    "📊 BusinessIntelligence.ai"
)

st.caption(
    "From KPI movement to evidence-backed action"
)


# ============================================================
# KPI HERO
# ============================================================

change = movement["gmv_change"]

previous_gmv = movement[
    "previous_gmv"
]

current_gmv = movement[
    "current_gmv"
]

if previous_gmv != 0:

    gmv_pct = (
        change
        / previous_gmv
        * 100
    )

else:

    gmv_pct = None


col1, col2, col3, col4 = st.columns(
    4
)

with col1:

    st.metric(
        "Marketplace GMV",
        format_brl(
            current_gmv
        ),
        format_pct(
            gmv_pct
        ),
    )

with col2:

    st.metric(
        "GMV Change",
        format_brl(
            change
        ),
    )

with col3:

    st.metric(
        "Orders",
        f"{movement['current_orders']:,}",
        f"{movement['orders_change']:+,}",
    )

with col4:

    aov_change_pct = (
        movement["aov_change"]
        / movement["previous_aov"]
        * 100
        if movement["previous_aov"] != 0
        else None
    )

    st.metric(
        "AOV",
        format_brl(
            movement["current_aov"]
        ),
        format_pct(
            aov_change_pct
        ),
    )


st.divider()


# ============================================================
# EVENT BANNER
# ============================================================

if event["investigation_priority"] == "HIGH":

    st.warning(
        "HIGH-PRIORITY KPI EVENT — "
        "investigation recommended"
    )

elif event["investigation_priority"] == "MEDIUM":

    st.info(
        "MEDIUM-PRIORITY KPI EVENT"
    )


# ============================================================
# EXECUTIVE VIEW
# ============================================================

if persona == "Executive":

    st.header(
        "Executive Intelligence"
    )

    if executive_story:

        story = executive_story.get(
            "story",
            ""
        )

        safe_story = story.replace(
            "$",
            r"\$"
        )

        render_story(
            story
        )

    st.divider()

    # --------------------------------------------------------
    # Decomposition chart
    # --------------------------------------------------------

    st.subheader(
        "What explains the movement?"
    )

    volume_effect = movement[
        "volume_effect"
    ]

    aov_effect = movement[
        "aov_effect"
    ]

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=[
                "Volume",
                "AOV",
                "Net GMV Change",
            ],

            y=[
                volume_effect,
                aov_effect,
                change,
            ],

            text=[
                format_brl(
                    volume_effect
                ),

                format_brl(
                    aov_effect
                ),

                format_brl(
                    change
                ),
            ],

            textposition="auto",
        )
    )

    fig.update_layout(
        title="GMV contribution decomposition",
        yaxis_title="BRL",
        xaxis_title="Component",
        height=400,
        showlegend=False,
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
    )

    # --------------------------------------------------------
    # Top observed contributors
    # --------------------------------------------------------

    st.subheader(
        "Where did the movement occur?"
    )

    top_drivers = sorted(
        drivers,
        key=lambda d: abs(
            d["observed_contribution"]["share"]
        ),
        reverse=True,
    )[:5]

    for driver in top_drivers:

        contribution = (
            driver[
                "observed_contribution"
            ]
        )

        confidence = (
            driver[
                "confidence"
            ]["overall"]
        )

        status = driver[
            "status"
        ]

        c1, c2, c3, c4 = st.columns(
            [3, 2, 2, 2]
        )

        with c1:

            st.write(
                f"**{driver['driver']}**"
            )

        with c2:

            st.write(
                format_brl(
                    contribution[
                        "gmv_change"
                    ]
                )
            )

        with c3:

            st.write(
                f"{contribution['share'] * 100:.1f}%"
            )

        with c4:

            st.write(
                status_badge(
                    status
                )
            )

    # --------------------------------------------------------
    # Confidence
    # --------------------------------------------------------

    st.subheader(
        "How certain are we?"
    )

    weak_or_uncertain = [
        d
        for d in drivers
        if d["status"]
        in {
            "WEAK",
            "ABSTAIN",
            "CONTRADICTED",
        }
    ]

    if weak_or_uncertain:

        st.info(
            "The engine identifies where the movement "
            "occurred, but available evidence does "
            "not establish a verified root cause."
        )

    else:

        st.success(
            "Available evidence is sufficiently "
            "strong for the identified hypotheses."
        )


# ============================================================
# OPERATIONS VIEW
# ============================================================

else:

    st.header(
        "Operations Intelligence"
    )

    if operations_story:

        story = operations_story.get(
            "story",
            ""
        )

        safe_story = story.replace(
            "$",
            r"\$"
        )

        render_story(
            story
        )

    st.divider()

    # --------------------------------------------------------
    # Driver table
    # --------------------------------------------------------

    st.subheader(
        "Driver Investigation"
    )

    driver_rows = []

    for driver in drivers:

        contribution = (
            driver[
                "observed_contribution"
            ]
        )

        confidence = (
            driver[
                "confidence"
            ]
        )

        action = (
            driver[
                "action"
            ]
        )

        driver_rows.append(
            {
                "Driver":
                    driver["driver"],

                "Type":
                    driver["driver_type"],

                "GMV Change":
                    format_brl(
                        contribution[
                            "gmv_change"
                        ]
                    ),

                "Contribution":
                    f"{contribution['share'] * 100:.1f}%",

                "Confidence":
                    round(
                        confidence[
                            "overall"
                        ],
                        3,
                    ),

                "Evidence":
                    driver["status"],

                "Decision":
                    action["decision"],

                "Owner":
                    action["owner"],
            }
        )

    if driver_rows:

        st.dataframe(
            driver_rows,
            use_container_width=True,
            hide_index=True,
        )

    # --------------------------------------------------------
    # Action center
    # --------------------------------------------------------

    st.subheader(
        "Action Center"
    )

    if actions_response:

        actions = (
            actions_response.get(
                "actions",
                []
            )
        )

        actionable = [
            action
            for action in actions
            if action.get(
                "decision"
            )
            in {
                "ACTIONABLE",
                "ACTION_WITH_VALIDATION",
                "INVESTIGATE",
            }
        ]

        for action in actionable[:5]:

            decision = action[
                "decision"
            ]

            if decision == "ACTIONABLE":

                st.success(
                    f"**{action['driver']}** — "
                    f"{action['action']}"
                )

            elif decision == "INVESTIGATE":

                st.warning(
                    f"**Investigate {action['driver']}** — "
                    f"{action['action']}"
                )

            else:

                st.info(
                    f"**{action['driver']}** — "
                    f"{action['action']}"
                )

            st.caption(
                f"Owner: {action['owner']} | "
                f"Monitor: {action['monitoring_plan']}"
            )


# ============================================================
# EVIDENCE PANEL
# ============================================================

st.divider()

st.header(
    "Evidence & Governance"
)

e1, e2, e3, e4 = st.columns(
    4
)

with e1:

    st.metric(
        "Commerce Coverage",
        insight[
            "data_quality"
        ].get(
            "commerce_source",
            "UNKNOWN",
        ),
    )

with e2:

    st.metric(
        "Review Text",
        (
            "Available"
            if insight[
                "data_quality"
            ].get(
                "review_text_available",
                False,
            )
            else "Unavailable"
        ),
    )

with e3:

    st.metric(
        "Business Context",
        (
            "Available"
            if insight[
                "data_quality"
            ].get(
                "business_context_available",
                False,
            )
            else "Unavailable"
        ),
    )

with e4:

    st.metric(
        "Event Priority",
        event[
            "investigation_priority"
        ],
    )


# ============================================================
# LINEAGE
# ============================================================

with st.expander(
    "🔎 Analytical lineage"
):

    lineage = insight.get(
        "lineage",
        {}
    )

    st.write(
        "**Raw sources**"
    )

    st.write(
        lineage.get(
            "raw_sources",
            []
        )
    )

    st.write(
        "**Analytical methods**"
    )

    st.write(
        lineage.get(
            "methods",
            []
        )
    )

    st.write(
        "**Analytical tables**"
    )

    st.write(
        lineage.get(
            "analytical_tables",
            []
        )
    )


# ============================================================
# LLM GOVERNANCE
# ============================================================

with st.expander(
    "🤖 LLM governance"
):

    policy = insight.get(
        "llm_policy",
        {}
    )

    st.write(
        "**Quantitative truth source:** "
        f"{policy.get('quantitative_truth_source', 'Unknown')}"
    )

    st.write(
        "**Allowed LLM tasks:**"
    )

    st.write(
        policy.get(
            "allowed_llm_tasks",
            []
        )
    )

    st.write(
        "**Forbidden LLM tasks:**"
    )

    st.write(
        policy.get(
            "forbidden_llm_tasks",
            []
        )
    )


# ============================================================
# TELEMETRY
# ============================================================

st.divider()

with st.expander(
    "⚙️ Runtime telemetry"
):

    if telemetry:

        tc1, tc2 = st.columns(
            2
        )

        executive_telemetry = (
            telemetry.get(
                "executive",
                {}
            )
        )

        operations_telemetry = (
            telemetry.get(
                "operations",
                {}
            )
        )

        with tc1:

            st.write(
                "**Executive LLM**"
            )

            st.json(
                executive_telemetry
            )

        with tc2:

            st.write(
                "**Operations LLM**"
            )

            st.json(
                operations_telemetry
            )

        validation = (
            telemetry.get(
                "validation",
                {}
            )
        )

        if (
            validation.get(
                "executive_passed"
            )
            and validation.get(
                "operations_passed"
            )
        ):

            st.success(
                "Both narratives passed the "
                "evidence-grounding validator."
            )

        else:

            st.error(
                "Narrative validation failed."
            )


# ============================================================
# EVENT HISTORY
# ============================================================

with st.expander(
    "📈 Prior KPI events"
):

    if events_response:

        historical_events = (
            events_response.get(
                "events",
                []
            )
        )

        st.dataframe(
            historical_events,
            use_container_width=True,
            hide_index=True,
        )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "BusinessIntelligence.ai — "
    "Analytical truth is computed deterministically; "
    "the LLM is used only for evidence-grounded narrative synthesis."
)
