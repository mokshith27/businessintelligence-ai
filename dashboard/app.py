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


# ============================================================
# API HELPER
# ============================================================

def api_get(endpoint):
    """
    Call FastAPI and return decoded JSON.

    No Streamlit caching is used here because we are actively
    regenerating insights, narratives and validation artifacts
    during development.
    """

    try:

        response = requests.get(
            f"{API_BASE_URL}{endpoint}",
            timeout=15,
        )

        response.raise_for_status()

        return response.json()

    except requests.exceptions.RequestException as exc:

        st.error(
            f"Backend connection failed: {exc}"
        )

        return None


def api_post(
    endpoint,
    payload,
):
    """
    POST JSON payload to FastAPI.
    """

    try:

        response = requests.post(
            f"{API_BASE_URL}{endpoint}",
            json=payload,
            timeout=15,
        )

        response.raise_for_status()

        return response.json()

    except requests.exceptions.HTTPError as exc:

        try:
            detail = response.json().get(
                "detail",
                str(exc),
            )
        except Exception:
            detail = str(exc)

        st.error(
            f"Backend rejected the request: {detail}"
        )

        return None

    except requests.exceptions.RequestException as exc:

        st.error(
            f"Backend connection failed: {exc}"
        )

        return None

# ============================================================
# STORY RENDERER
# ============================================================


def render_story(story):
    """
    Render LLM-generated narrative safely.

    We deliberately avoid passing the complete narrative
    through Markdown because currency values such as R$
    can be interpreted as math delimiters.
    """

    if not story:
        return

    lines = story.splitlines()

    headings = {
        "HEADLINE:",
        "WHAT CHANGED:",
        "MAIN DRIVER:",
        "WHERE:",
        "WHAT WE KNOW:",
        "NEXT STEP:",
        "KPI MOVEMENT:",
        "ANALYTICAL DECOMPOSITION:",
        "TOP INVESTIGATION AREAS:",
        "EVIDENCE:",
        "ACTIONS:",
        "DATA QUALITY:",
    }

    for raw_line in lines:

        line = raw_line.strip()

        if not line:
            continue

        # ----------------------------------------------------
        # Remove Markdown emphasis around headings.
        # ----------------------------------------------------

        normalized = (
            line
            .replace("**", "")
            .strip()
        )

        if normalized in headings:

            heading = normalized.rstrip(":")

            st.markdown(
                f"### {heading}"
            )

            continue

        # ----------------------------------------------------
        # Bullets
        # ----------------------------------------------------

        if line.startswith("- "):

            bullet = line[2:]

            # Escape dollar signs so R$ remains literal.
            bullet = bullet.replace(
                "$",
                r"\$",
            )

            st.markdown(
                f"- {bullet}"
            )

            continue

        # ----------------------------------------------------
        # Numbered list
        # ----------------------------------------------------

        if len(line) >= 3:

            first_two = line[:2]

            if (
                first_two[0].isdigit()
                and first_two[1] == "."
            ):

                safe_line = line.replace(
                    "$",
                    r"\$",
                )

                st.markdown(
                    safe_line
                )

                continue

        # ----------------------------------------------------
        # Ordinary text
        # ----------------------------------------------------

        safe_line = line.replace(
            "$",
            r"\$",
        )

        st.write(
            safe_line
        )


# ============================================================
# FORMATTERS
# ============================================================

def format_brl(value):

    if value is None:
        return "—"

    try:
        value = float(value)
    except (TypeError, ValueError):
        return "—"

    sign = "-" if value < 0 else ""

    value = abs(value)

    if value >= 1_000_000:

        return (
            f"{sign}R$"
            f"{value / 1_000_000:.2f}M"
        )

    if value >= 1_000:

        return (
            f"{sign}R$"
            f"{value / 1_000:.1f}K"
        )

    return (
        f"{sign}R$"
        f"{value:,.2f}"
    )


def format_pct(value):

    if value is None:
        return "—"

    try:
        return f"{float(value):+.1f}%"
    except (TypeError, ValueError):
        return "—"


def status_badge(status):

    mapping = {

        "SUPPORTED":
            "🟢 SUPPORTED",

        "PLAUSIBLE":
            "🟡 PLAUSIBLE",

        "WEAK":
            "🟠 WEAK",

        "ABSTAIN":
            "⚪ ABSTAIN",

        "CONTRADICTED":
            "🔴 CONTRADICTED",
    }

    return mapping.get(
        str(status).upper(),
        str(status),
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

    role = st.radio(
        "Role",
        [
            "Executive",
            "Operations",
            "Analyst",
        ],
    )

    role_key = role.lower()

    st.divider()


# ============================================================
# LOAD ROLE-AWARE INSIGHT
# ============================================================

insight = api_get(
    f"/api/insights/role?role={role_key}"
)

if insight is None:
    st.stop()


# ============================================================
# LOAD SUPPORTING DATA
# ============================================================

# ------------------------------------------------------------
# The story displayed depends on the role.
# ------------------------------------------------------------

if role == "Executive":

    story_response = api_get(
        "/api/insights/latest/executive"
    )

    story = (
        story_response.get(
            "story",
            ""
        )
        if story_response
        else ""
    )

elif role == "Operations":

    story_response = api_get(
        "/api/insights/latest/operations"
    )

    story = (
        story_response.get(
            "story",
            ""
        )
        if story_response
        else ""
    )

else:

    # Analyst can inspect both narrative forms.
    executive_response = api_get(
        "/api/insights/latest/executive"
    )

    operations_response = api_get(
        "/api/insights/latest/operations"
    )

    executive_story = (
        executive_response.get(
            "story",
            ""
        )
        if executive_response
        else ""
    )

    operations_story = (
        operations_response.get(
            "story",
            ""
        )
        if operations_response
        else ""
    )

# ------------------------------------------------------------
# Supporting endpoints
# ------------------------------------------------------------

actions_response = api_get(
    "/api/actions"
)

telemetry = api_get(
    "/api/telemetry"
)

events_response = api_get(
    "/api/events?limit=25"
)


# ============================================================
# EXTRACT INSIGHT
# ============================================================

kpi = insight.get(
    "kpi",
    {},
)

event = insight.get(
    "event",
    {},
)

movement = insight.get(
    "movement",
    {},
)

drivers = insight.get(
    "drivers",
    [],
)


# ============================================================
# SIDEBAR EVENT INFO
# ============================================================

with st.sidebar:

    st.subheader(
        "Current Event"
    )

    st.write(
        f"**{event.get('start_date', '—')} "
        f"→ {event.get('end_date', '—')}**"
    )

    st.write(
        "Priority: "
        f"**{event.get('investigation_priority', '—')}**"
    )

    st.write(
        "Direction: "
        f"**{event.get('direction', '—')}**"
    )

    st.caption(
        "Values are derived from the "
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

change = movement.get(
    "gmv_change"
)

previous_gmv = movement.get(
    "previous_gmv"
)

current_gmv = movement.get(
    "current_gmv"
)

if (
    previous_gmv is not None
    and previous_gmv != 0
    and change is not None
):

    gmv_pct = (
        float(change)
        / float(previous_gmv)
        * 100
    )

else:

    gmv_pct = None


current_orders = movement.get(
    "current_orders"
)

orders_change = movement.get(
    "orders_change"
)

current_aov = movement.get(
    "current_aov"
)

previous_aov = movement.get(
    "previous_aov"
)

aov_change = movement.get(
    "aov_change"
)

if (
    previous_aov is not None
    and previous_aov != 0
    and aov_change is not None
):

    aov_change_pct = (
        float(aov_change)
        / float(previous_aov)
        * 100
    )

else:

    aov_change_pct = None


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
        (
            f"{int(current_orders):,}"
            if current_orders is not None
            else "—"
        ),
        (
            f"{int(orders_change):+,}"
            if orders_change is not None
            else None
        ),
    )

with col4:

    st.metric(
        "AOV",
        format_brl(
            current_aov
        ),
        format_pct(
            aov_change_pct
        ),
    )


st.divider()


# ============================================================
# EVENT BANNER
# ============================================================

priority = event.get(
    "investigation_priority"
)

if priority == "HIGH":

    st.warning(
        "HIGH-PRIORITY KPI EVENT — "
        "investigation recommended"
    )

elif priority == "MEDIUM":

    st.info(
        "MEDIUM-PRIORITY KPI EVENT"
    )


# ============================================================
# EXECUTIVE
# ============================================================

if role == "Executive":

    st.header(
        "Executive Intelligence"
    )

    render_story(
        story
    )

    st.divider()

    # --------------------------------------------------------
    # Decomposition
    # --------------------------------------------------------

    st.subheader(
        "What explains the movement?"
    )

    volume_effect = movement.get(
        "volume_effect",
        0,
    )

    aov_effect = movement.get(
        "aov_effect",
        0,
    )

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
        width="stretch",
    )

    # --------------------------------------------------------
    # Top contributors
    # --------------------------------------------------------

    st.subheader(
        "Where did the movement occur?"
    )

    top_drivers = sorted(
        drivers,
        key=lambda d: abs(
            d.get(
                "observed_contribution",
                {},
            ).get(
                "share",
                0,
            )
        ),
        reverse=True,
    )[:5]

    for driver in top_drivers:

        contribution = driver.get(
            "observed_contribution",
            {},
        )

        confidence = driver.get(
            "confidence",
            {},
        )

        status = driver.get(
            "status",
            "UNKNOWN",
        )

        c1, c2, c3, c4 = st.columns(
            [3, 2, 2, 2]
        )

        with c1:

            st.write(
                f"**{driver.get('driver', '—')}**"
            )

        with c2:

            st.write(
                format_brl(
                    contribution.get(
                        "gmv_change"
                    )
                )
            )

        with c3:

            st.write(
                f"{contribution.get('share', 0) * 100:.1f}%"
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

    uncertain = [
        driver
        for driver in drivers
        if driver.get("status")
        in {
            "WEAK",
            "ABSTAIN",
            "CONTRADICTED",
        }
    ]

    if uncertain:

        st.info(
            "The engine identifies where the movement "
            "occurred, but available evidence does not "
            "establish a verified root cause."
        )

    else:

        st.success(
            "Available evidence is sufficiently strong "
            "for the identified hypotheses."
        )


# ============================================================
# OPERATIONS
# ============================================================

elif role == "Operations":

    st.header(
        "Operations Intelligence"
    )

    render_story(
        story
    )

    st.divider()

    st.subheader(
        "Driver Investigation"
    )

    driver_rows = []

    for driver in drivers:

        contribution = driver.get(
            "observed_contribution",
            {},
        )

        confidence = driver.get(
            "confidence",
            {},
        )

        action = driver.get(
            "action",
            {},
        )

        driver_rows.append(
            {
                "Driver":
                    driver.get(
                        "driver",
                        "—",
                    ),

                "Type":
                    driver.get(
                        "driver_type",
                        "—",
                    ),

                "GMV Change":
                    format_brl(
                        contribution.get(
                            "gmv_change"
                        )
                    ),

                "Contribution":
                    (
                        f"{contribution.get('share', 0) * 100:.1f}%"
                    ),

                "Confidence":
                    round(
                        confidence.get(
                            "overall",
                            0,
                        ),
                        3,
                    ),

                "Evidence":
                    driver.get(
                        "status",
                        "—",
                    ),

                "Decision":
                    action.get(
                        "decision",
                        "—",
                    ),

                "Owner":
                    action.get(
                        "owner",
                        "—",
                    ),
            }
        )

    if driver_rows:

        st.dataframe(
            driver_rows,
            width="stretch",
            hide_index=True,
        )

    st.subheader(
        "Action Center"
    )

    if actions_response:

        actions = actions_response.get(
            "actions",
            [],
        )

        actionable = [
            action
            for action in actions
            if action.get(
                "decision"
            ) in {
                "ACTIONABLE",
                "ACTION_WITH_VALIDATION",
                "INVESTIGATE",
            }
        ]

        if actionable:

            for action in actionable[:5]:

                decision = action.get(
                    "decision"
                )

                if decision == "ACTIONABLE":

                    st.success(
                        f"**{action.get('driver', '—')}** — "
                        f"{action.get('action', '')}"
                    )

                elif decision == "INVESTIGATE":

                    st.warning(
                        f"**Investigate "
                        f"{action.get('driver', '—')}** — "
                        f"{action.get('action', '')}"
                    )

                else:

                    st.info(
                        f"**{action.get('driver', '—')}** — "
                        f"{action.get('action', '')}"
                    )

                st.caption(
                    f"Owner: {action.get('owner', '—')} | "
                    f"Monitor: {action.get('monitoring_plan', '—')}"
                )

        else:

            st.info(
                "No actionable recommendations were "
                "returned for this event."
            )


# ============================================================
# ANALYST
# ============================================================

else:

    st.header(
        "Analyst Intelligence"
    )

    st.caption(
        "Full evidence, lineage and causal diagnostics"
    )

    # --------------------------------------------------------
    # Executive story
    # --------------------------------------------------------

    st.subheader(
        "Executive narrative"
    )

    render_story(
        executive_story
    )

    st.divider()

    # --------------------------------------------------------
    # Operations story
    # --------------------------------------------------------

    st.subheader(
        "Operations narrative"
    )

    render_story(
        operations_story
    )

    st.divider()

    # --------------------------------------------------------
    # Driver table
    # --------------------------------------------------------

    st.subheader(
        "Full driver evidence"
    )

    analyst_rows = []

    for driver in drivers:

        contribution = driver.get(
            "observed_contribution",
            {},
        )

        confidence = driver.get(
            "confidence",
            {},
        )

        action = driver.get(
            "action",
            {},
        )

        analyst_rows.append(
            {
                "Driver":
                    driver.get(
                        "driver",
                        "—",
                    ),

                "Type":
                    driver.get(
                        "driver_type",
                        "—",
                    ),

                "GMV Change":
                    format_brl(
                        contribution.get(
                            "gmv_change"
                        )
                    ),

                "Contribution %":
                    (
                        contribution.get(
                            "share",
                            0,
                        )
                        * 100
                    ),

                "Confidence":
                    confidence.get(
                        "overall",
                        0,
                    ),

                "Status":
                    driver.get(
                        "status",
                        "—",
                    ),

                "Decision":
                    action.get(
                        "decision",
                        "—",
                    ),
            }
        )

    if analyst_rows:

        st.dataframe(
            analyst_rows,
            width="stretch",
            hide_index=True,
        )

    # ============================================================
    # ANALYST FEEDBACK
    # ============================================================

    if role == "Analyst":

        st.divider()

        st.header(
            "Analyst Feedback"
        )

        st.caption(
            "Use feedback to evaluate the quality of the "
            "engine's driver assessment."
        )

        if not drivers:

            st.info(
                "No drivers are available for feedback."
            )

        else:

            for index, driver in enumerate(
                drivers[:5]
            ):

                contribution = driver.get(
                    "observed_contribution",
                    {},
                )

                confidence = driver.get(
                    "confidence",
                    {},
                )

                action = driver.get(
                    "action",
                    {},
                )

                driver_name = driver.get(
                    "driver",
                    "—",
                )

                driver_type = driver.get(
                    "driver_type",
                    "—",
                )

                status = driver.get(
                    "status",
                    "—",
                )

                overall_confidence = confidence.get(
                    "overall",
                    0,
                )

                decision = action.get(
                    "decision"
                )

                # ------------------------------------------------
                # Unique form per driver
                # ------------------------------------------------

                with st.expander(
                    f"{driver_name} — "
                    f"{status_badge(status)}",
                    expanded=(index == 0),
                ):

                    c1, c2, c3, c4 = st.columns(
                        4
                    )

                    with c1:

                        st.write(
                            f"**Type**  \n"
                            f"{driver_type}"
                        )

                    with c2:

                        st.write(
                            f"**Contribution**  \n"
                            f"{contribution.get('share', 0) * 100:.2f}%"
                        )

                    with c3:

                        st.write(
                            f"**Confidence**  \n"
                            f"{overall_confidence:.3f}"
                        )

                    with c4:

                        st.write(
                            f"**Decision**  \n"
                            f"{decision or '—'}"
                        )

                    st.write(
                        "Was this assessment useful?"
                    )

                    feedback_key = (
                        f"feedback_{index}_{driver_type}_{driver_name}"
                    )

                    label = st.radio(
                        "Feedback",
                        [
                            "Correct",
                            "Incorrect",
                            "Missing context",
                        ],
                        key=feedback_key,
                        horizontal=True,
                    )

                    correction_text = st.text_area(
                        "Correction / additional context",
                        key=f"{feedback_key}_text",
                        placeholder=(
                            "Explain what was wrong, "
                            "or what evidence was missing..."
                        ),
                    )

                    corrected_driver = st.text_input(
                        "Correct driver (optional)",
                        key=f"{feedback_key}_driver",
                        placeholder=(
                            "Only fill this if the predicted driver "
                            "was incorrect."
                        ),
                    )

                    if st.button(
                        "Submit feedback",
                        key=f"{feedback_key}_submit",
                    ):

                        feedback_map = {

                            "Correct":
                                "CORRECT",

                            "Incorrect":
                                "INCORRECT",

                            "Missing context":
                                "MISSING_CONTEXT",
                        }

                        payload = {

                            "role":
                                role.lower(),

                            "event_id":
                                str(
                                    event.get(
                                        "event_id",
                                        ""
                                    )
                                ),

                            "event_start_date":
                                event.get(
                                    "start_date"
                                ),

                            "event_end_date":
                                event.get(
                                    "end_date"
                                ),

                            "driver_type":
                                driver_type,

                            "driver":
                                driver_name,

                            "predicted_status":
                                status,

                            "predicted_confidence":
                                float(
                                    overall_confidence
                                ),

                            "predicted_decision":
                                decision,

                            "feedback_label":
                                feedback_map[
                                    label
                                ],

                            "corrected_driver":
                                (
                                    corrected_driver.strip()
                                    or None
                                ),

                            "correction_text":
                                (
                                    correction_text.strip()
                                    or None
                                ),
                        }

                        result = api_post(
                            "/api/feedback",
                            payload,
                        )

                        if result:

                            st.success(
                                "Feedback recorded successfully."
                            )

                            st.json(
                                result
                            )

                            st.rerun()

    # ============================================================
    # FEEDBACK CALIBRATION
    # ============================================================

    if role == "Analyst":

        st.subheader(
            "Feedback Calibration"
        )

        calibration = api_get(
            "/api/calibration"
        )

        if calibration:

            c1, c2, c3, c4 = st.columns(
                4
            )

            with c1:

                st.metric(
                    "Feedback records",
                    calibration.get(
                        "feedback_count",
                        0,
                    ),
                )

            with c2:

                st.metric(
                    "Correct",
                    calibration.get(
                        "correct",
                        0,
                    ),
                )

            with c3:

                st.metric(
                    "Incorrect",
                    calibration.get(
                        "incorrect",
                        0,
                    ),
                )

            with c4:

                st.metric(
                    "Missing context",
                    calibration.get(
                        "missing_context",
                        0,
                    ),
                )

            status = calibration.get(
                "status",
                "UNKNOWN",
            )

            if status == "CALIBRATION_AVAILABLE":

                st.success(
                    "Sufficient feedback is available "
                    "for calibration analysis."
                )

            else:

                st.info(
                    "The system is still collecting feedback. "
                    "Production confidence is not automatically "
                    "overridden from small samples."
                )

            bins = calibration.get(
                "bins",
                [],
            )

            if bins:

                st.write(
                    "**Confidence calibration**"
                )

                calibration_rows = []

                for item in bins:

                    calibration_rows.append(
                        {
                            "Confidence range":
                                item.get(
                                    "confidence_range"
                                ),

                            "Observations":
                                item.get(
                                    "count"
                                ),

                            "Predicted confidence":
                                item.get(
                                    "mean_predicted_confidence"
                                ),

                            "Observed accuracy":
                                item.get(
                                    "observed_accuracy"
                                ),

                            "Calibration gap":
                                item.get(
                                    "calibration_gap"
                                ),
                        }
                    )

                st.dataframe(
                    calibration_rows,
                    width="stretch",
                    hide_index=True,
                )

# ============================================================
# EVIDENCE & GOVERNANCE
# ============================================================

st.divider()

st.header(
    "Evidence & Governance"
)

data_quality = insight.get(
    "data_quality",
    {},
)

e1, e2, e3, e4 = st.columns(
    4
)

with e1:

    commerce_coverage = data_quality.get(
        "commerce_source",
        "UNKNOWN",
    )

    if commerce_coverage == "NORMAL_DATA_COVERAGE":
        commerce_display = "Normal"
    else:
        commerce_display = commerce_coverage.replace(
            "_",
            " ",
        ).title()

    st.metric(
        "Commerce Coverage",
        commerce_display,
    )

with e2:

    st.metric(
        "Review Text",
        (
            "Available"
            if data_quality.get(
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
            if data_quality.get(
                "business_context_available",
                False,
            )
            else "Unavailable"
        ),
    )

with e4:

    st.metric(
        "Event Priority",
        event.get(
            "investigation_priority",
            "UNKNOWN",
        ),
    )


# ============================================================
# LINEAGE
# ============================================================

with st.expander(
    "🔎 Analytical lineage"
):

    lineage = insight.get(
        "lineage",
        {},
    )

    st.write(
        "**Raw sources**"
    )

    st.write(
        lineage.get(
            "raw_sources",
            [],
        )
    )

    st.write(
        "**Analytical methods**"
    )

    st.write(
        lineage.get(
            "methods",
            [],
        )
    )

    st.write(
        "**Analytical tables**"
    )

    st.write(
        lineage.get(
            "analytical_tables",
            [],
        )
    )


# ============================================================
# LLM GOVERNANCE
# ============================================================

with st.expander(
    "🤖 LLM governance"
):

    policy = insight.get(
        "llm_governance",
        {},
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
            [],
        )
    )

    st.write(
        "**Forbidden LLM tasks:**"
    )

    st.write(
        policy.get(
            "forbidden_llm_tasks",
            [],
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

        executive_telemetry = telemetry.get(
            "executive",
            {},
        )

        operations_telemetry = telemetry.get(
            "operations",
            {},
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

        validation = telemetry.get(
            "validation",
            {},
        )

        executive_passed = (
            validation.get(
                "executive_passed",
                False,
            )
            is True
        )

        operations_passed = (
            validation.get(
                "operations_passed",
                False,
            )
            is True
        )

        if (
            executive_passed
            and operations_passed
        ):

            st.success(
                "Both narratives passed the "
                "evidence-grounding validator."
            )

        else:

            st.error(
                "Narrative validation failed."
            )

            st.json(
                validation
            )


# ============================================================
# EVENT HISTORY
# ============================================================

with st.expander(
    "📈 Prior KPI events"
):

    if events_response:

        historical_events = events_response.get(
            "events",
            [],
        )

        st.dataframe(
            historical_events,
            width="stretch",
            hide_index=True,
        )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "BusinessIntelligence.ai — "
    "Analytical truth is computed deterministically; "
    "the LLM is used only for evidence-grounded "
    "narrative synthesis."
)

# ============================================================
# VALIDATION CENTER
# ============================================================

st.divider()

with st.expander(
    "🧪 Validation Center"
):

    st.header(
        "System Validation"
    )

    # ========================================================
    # CONTROLLED SCENARIOS
    # ========================================================

    st.subheader(
        "Controlled Scenario Evaluation"
    )

    scenarios = api_get(
        "/api/validation/scenarios"
    )

    if scenarios:

        evaluation = scenarios.get(
            "engine_evaluation",
            []
        )

        # ----------------------------------------------------
        # The engine evaluation artifact is currently a list
        # of per-scenario records. Some future versions may
        # wrap it inside {"results": [...], "summary": {...}}.
        # Normalize both forms.
        # ----------------------------------------------------

        if isinstance(
            evaluation,
            dict,
        ):

            scenario_results = evaluation.get(
                "results",
                evaluation.get(
                    "scenarios",
                    [],
                ),
            )

            provided_summary = evaluation.get(
                "summary",
                {},
            )

        elif isinstance(
            evaluation,
            list,
        ):

            scenario_results = evaluation
            provided_summary = {}

        else:

            scenario_results = []
            provided_summary = {}

        # ----------------------------------------------------
        # Normalize scenario rows and compute summary from the
        # actual records when no summary is supplied.
        # ----------------------------------------------------

        normalized_results = []

        for item in scenario_results:

            if not isinstance(
                item,
                dict,
            ):
                continue

            scenario_id = item.get(
                "scenario_id",
                item.get(
                    "scenario",
                    "—",
                ),
            )

            ground_truth = item.get(
                "ground_truth_driver",
                item.get(
                    "ground_truth",
                    "—",
                ),
            )

            top_driver = item.get(
                "top_engine_driver",
                item.get(
                    "top_driver",
                    item.get(
                        "driver",
                        "—",
                    ),
                ),
            )

            status = item.get(
                "status",
                item.get(
                    "engine_status",
                    "—",
                ),
            )

            decision = item.get(
                "action_decision",
                item.get(
                    "decision",
                    item.get(
                        "action",
                        "—",
                    ),
                ),
            )

            driver_match = item.get(
                "driver_match",
                item.get(
                    "driver_matches",
                    item.get(
                        "driver_identification_match",
                        None,
                    ),
                ),
            )

            safety = item.get(
                "safety",
                item.get(
                    "safe",
                    item.get(
                        "decision_acceptable",
                        None,
                    ),
                ),
            )

            score = item.get(
                "overall_score",
                item.get(
                    "score",
                    None,
                ),
            )

            # ------------------------------------------------
            # Normalize booleans represented as strings.
            # ------------------------------------------------

            if isinstance(
                driver_match,
                str,
            ):

                driver_match = (
                    driver_match.strip().lower()
                    in {
                        "true",
                        "yes",
                        "1",
                        "pass",
                    }
                )

            if isinstance(
                safety,
                str,
            ):

                safety = (
                    safety.strip().lower()
                    in {
                        "true",
                        "yes",
                        "1",
                        "pass",
                    }
                )

            try:

                score_value = (
                    float(score)
                    if score is not None
                    else None
                )

            except (
                TypeError,
                ValueError,
            ):

                score_value = None

            normalized_results.append(
                {
                    "scenario_id":
                        scenario_id,

                    "ground_truth_driver":
                        ground_truth,

                    "top_engine_driver":
                        top_driver,

                    "status":
                        status,

                    "action_decision":
                        decision,

                    "driver_match":
                        driver_match,

                    "safety":
                        safety,

                    "overall_score":
                        score_value,
                }
            )

        # ----------------------------------------------------
        # Use supplied summary when available, otherwise
        # calculate it from the normalized scenario records.
        # ----------------------------------------------------

        summary = (
            dict(
                provided_summary
            )
            if isinstance(
                provided_summary,
                dict,
            )
            else {}
        )

        if not summary:

            evaluated = len(
                normalized_results
            )

            driver_matches = sum(
                1
                for item in normalized_results
                if item["driver_match"] is True
            )

            safety_passed = sum(
                1
                for item in normalized_results
                if item["safety"] is True
            )

            score_values = [
                item["overall_score"]
                for item in normalized_results
                if item["overall_score"] is not None
            ]

            average_score = (
                sum(score_values)
                / len(score_values)
                if score_values
                else 0.0
            )

            summary = {

                "scenarios_evaluated":
                    evaluated,

                "driver_matches":
                    driver_matches,

                "safety_checks_passed":
                    safety_passed,

                "average_score":
                    average_score,
            }

        else:

            # Support either count or ratio fields.
            if (
                "scenarios_evaluated"
                not in summary
            ):

                summary[
                    "scenarios_evaluated"
                ] = len(
                    normalized_results
                )

            if (
                "driver_matches"
                not in summary
            ):

                summary[
                    "driver_matches"
                ] = sum(
                    1
                    for item in normalized_results
                    if item["driver_match"] is True
                )

            if (
                "safety_checks_passed"
                not in summary
            ):

                summary[
                    "safety_checks_passed"
                ] = sum(
                    1
                    for item in normalized_results
                    if item["safety"] is True
                )

            if (
                "average_score"
                not in summary
            ):

                scores = [
                    item["overall_score"]
                    for item in normalized_results
                    if item["overall_score"] is not None
                ]

                summary[
                    "average_score"
                ] = (
                    sum(scores) / len(scores)
                    if scores
                    else 0.0
                )

        # ----------------------------------------------------
        # Summary metrics
        # ----------------------------------------------------

        evaluated_value = summary.get(
            "scenarios_evaluated",
            len(normalized_results),
        )

        driver_matches_value = summary.get(
            "driver_matches",
            0,
        )

        safety_value = summary.get(
            "safety_checks_passed",
            0,
        )

        average_score_value = summary.get(
            "average_score",
            0,
        )

        # Handle APIs that provide ratios rather than counts.
        if isinstance(
            driver_matches_value,
            float,
        ) and 0 <= driver_matches_value <= 1:

            driver_matches_display = (
                f"{driver_matches_value * 100:.0f}%"
            )

        else:

            driver_matches_display = (
                str(
                    driver_matches_value
                )
            )

        if isinstance(
            safety_value,
            float,
        ) and 0 <= safety_value <= 1:

            safety_display = (
                f"{safety_value * 100:.0f}%"
            )

        else:

            safety_display = (
                str(
                    safety_value
                )
            )

        c1, c2, c3, c4 = st.columns(
            4
        )

        with c1:

            st.metric(
                "Scenarios",
                evaluated_value,
            )

        with c2:

            st.metric(
                "Driver matches",
                driver_matches_display,
            )

        with c3:

            st.metric(
                "Safety passed",
                safety_display,
            )

        with c4:

            try:

                score_display = (
                    f"{float(average_score_value):.3f}"
                )

            except (
                TypeError,
                ValueError,
            ):

                score_display = "—"

            st.metric(
                "Average score",
                score_display,
            )

        # ----------------------------------------------------
        # Scenario table
        # ----------------------------------------------------

        if normalized_results:

            st.dataframe(
                normalized_results,
                width="stretch",
                hide_index=True,
            )

            try:

                score_for_status = float(
                    average_score_value
                )

            except (
                TypeError,
                ValueError,
            ):

                score_for_status = 0.0

            if score_for_status >= 0.90:

                st.success(
                    "Controlled scenario evaluation is passing."
                )

            elif score_for_status > 0:

                st.warning(
                    "Controlled scenario evaluation requires review."
                )

        else:

            st.info(
                "No controlled scenario evaluation records "
                "are currently available."
            )

    else:

        st.warning(
            "Controlled scenario validation data could not "
            "be loaded from the backend."
        )

    # ========================================================
    # SPARSE HISTORY
    # ========================================================

    st.subheader("Sparse-History Safety")

    sparse = api_get(
        "/api/validation/sparse-history"
    )

    if sparse:

        # ----------------------------------------------------
        # Actual sparse scenario structure:
        #
        # sparse["history_assessment"]
        # sparse["engine_decision"]
        # ----------------------------------------------------

        history_assessment = sparse.get(
            "history_assessment",
            {},
        )

        engine_decision = sparse.get(
            "engine_decision",
            {},
        )

        history_points = history_assessment.get(
            "history_points",
            0,
        )

        required_history = (
            sparse.get(
                "governance_expectation",
                {},
            ).get(
                "minimum_history_points",
                0,
            )
        )

        relative_change = history_assessment.get(
            "relative_change_pct"
        )

        decision = engine_decision.get(
            "decision",
            "—",
        )

        reason = engine_decision.get(
            "reason",
            "Sparse-history scenario information unavailable.",
        )

        c1, c2, c3, c4 = st.columns(4)

        with c1:

            st.metric(
                "History points",
                history_points,
            )

        with c2:

            st.metric(
                "Required history",
                required_history,
            )

        with c3:

            st.metric(
                "Relative change",
                (
                    f"{float(relative_change):+.1f}%"
                    if relative_change is not None
                    else "—"
                ),
            )

        with c4:

            st.metric(
                "Decision",
                str(decision),
            )

        if decision == "ABSTAIN":

            st.success(
                "Sparse-history safety check passed: "
                "the engine abstains rather than making "
                "a potentially unreliable claim."
            )

        else:

            st.warning(
                "Review the sparse-history behavior."
            )

        st.info(
            reason
        )

    else:

        st.warning(
            "Sparse-history validation data are unavailable."
        )

    # ========================================================
    # CAUSAL VALIDATION
    # ========================================================

    st.subheader(
        "Causal Validation"
    )

    causal = api_get(
        "/api/validation/causal"
    )

    if causal:

        production = causal.get(
            "production_status",
            {},
        )

        result = causal.get(
            "result",
            {},
        )

        diagnostics = causal.get(
            "diagnostics",
            {},
        )

        # ----------------------------------------------------
        # Support the actual causal artifact naming as well as
        # common aliases.
        # ----------------------------------------------------

        effect_value = (
            result.get(
                "causal_effect"
            )
            if isinstance(
                result,
                dict,
            )
            else None
        )

        if effect_value is None:

            effect_value = (
                result.get(
                    "causal_ate"
                )
                if isinstance(
                    result,
                    dict,
                )
                else None
            )

        if effect_value is None:

            effect_value = (
                result.get(
                    "effect_estimate"
                )
                if isinstance(
                    result,
                    dict,
                )
                else None
            )

        confidence_value = (
            production.get(
                "confidence"
            )
            if isinstance(
                production,
                dict,
            )
            else None
        )

        if confidence_value is None:

            confidence_value = (
                result.get(
                    "confidence"
                )
                if isinstance(
                    result,
                    dict,
                )
                else None
            )

        production_status = (
            production.get(
                "production_status",
                "—",
            )
            if isinstance(
                production,
                dict,
            )
            else "—"
        )

        c1, c2, c3 = st.columns(
            3
        )

        with c1:

            try:

                effect_display = (
                    f"{float(effect_value):+.3f}"
                )

            except (
                TypeError,
                ValueError,
            ):

                effect_display = "—"

            st.metric(
                "Causal effect",
                effect_display,
            )

        with c2:

            try:

                confidence_display = (
                    f"{float(confidence_value):.2f}"
                )

            except (
                TypeError,
                ValueError,
            ):

                confidence_display = "—"

            st.metric(
                "Confidence",
                confidence_display,
            )

        with c3:

            st.metric(
                "Status",
                production_status,
            )

        assessment = (
            diagnostics.get(
                "assessment",
                {},
            )
            if isinstance(
                diagnostics,
                dict,
            )
            else {}
        )

        diagnostic_status = (
            assessment.get(
                "diagnostic_status",
                diagnostics.get(
                    "diagnostic_status",
                    "—",
                ),
            )
            if isinstance(
                assessment,
                dict,
            )
            else "—"
        )

        st.write(
            "Diagnostic status: "
            f"**{diagnostic_status}**"
        )

        if (
            production_status
            == "CAUSAL_EVIDENCE_ACCEPTED"
        ):

            st.success(
                "Causal evidence passed the implemented "
                "diagnostic checks."
            )

        else:

            st.warning(
                "Causal evidence is not fully production-ready."
            )

    # ========================================================
    # FEEDBACK CALIBRATION
    # ========================================================

    st.subheader(
        "Human-in-the-Loop Calibration"
    )

    calibration = api_get(
        "/api/validation/feedback"
    )

    if calibration:

        c1, c2, c3, c4 = st.columns(
            4
        )

        with c1:

            st.metric(
                "Feedback",
                calibration.get(
                    "feedback_count",
                    0,
                ),
            )

        with c2:

            st.metric(
                "Correct",
                calibration.get(
                    "correct",
                    0,
                ),
            )

        with c3:

            st.metric(
                "Incorrect",
                calibration.get(
                    "incorrect",
                    0,
                ),
            )

        with c4:

            st.metric(
                "Missing context",
                calibration.get(
                    "missing_context",
                    0,
                ),
            )

        calibration_status = calibration.get(
            "status",
            "UNKNOWN",
        )

        if (
            calibration_status
            == "CALIBRATION_AVAILABLE"
        ):

            st.success(
                "Enough feedback is available for "
                "calibration analysis."
            )

        else:

            st.info(
                "The system is still collecting feedback. "
                "Production confidence is not automatically "
                "overridden from a small sample."
            )

# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "BusinessIntelligence.ai — "
    "Analytical truth is computed deterministically; "
    "the LLM is used only for evidence-grounded "
    "narrative synthesis."
)
