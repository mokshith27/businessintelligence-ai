from pathlib import Path
import json
import os
import re
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
from groq import Groq


# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

INSIGHT_PATH = (
    PROJECT_ROOT
    / "data"
    / "insights"
    / "latest_insight.json"
)


load_dotenv()

# ============================================================
# CONFIG
# ============================================================

LLM_PROVIDER = os.getenv(
    "LLM_PROVIDER",
    "groq",
).strip().lower()

MODEL_NAME = os.getenv(
    "LLM_MODEL",
    "openai/gpt-oss-120b",
).strip()

# Comma-separated provider:model candidates.
# Example free configuration:
# openrouter:nvidia/nemotron-3-ultra-550b-a55b:free,
# openrouter:google/gemma-4-31b-it:free,
# openrouter:openrouter/free
LLM_FALLBACKS = [
    item.strip()
    for item in os.getenv(
        "LLM_FALLBACKS",
        "",
    ).split(",")
    if item.strip()
]

MODEL_PURPOSE = (
    "Evidence-grounded narrative synthesis only"
)

MAX_OUTPUT_TOKENS = int(
    os.getenv(
        "LLM_MAX_OUTPUT_TOKENS",
        "800",
    )
)

TEMPERATURE = float(
    os.getenv(
        "LLM_TEMPERATURE",
        "0.1",
    )
)

REASONING_EFFORT = os.getenv(
    "LLM_REASONING_EFFORT",
    "low",
)

INCLUDE_REASONING = False

LLM_DEBUG = os.getenv(
    "LLM_DEBUG",
    "true",
).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def get_llm_configuration():
    """
    Return the effective LLM configuration loaded when this module starts.
    API keys are never returned.
    """
    return {
        "provider":
            LLM_PROVIDER,

        "model":
            MODEL_NAME,

        "fallbacks":
            LLM_FALLBACKS.copy(),

        "openrouter_key_configured":
            bool(
                os.getenv(
                    "OPENROUTER_API_KEY"
                )
            ),

        "groq_key_configured":
            bool(
                os.getenv(
                    "GROQ_API_KEY"
                )
            ),

        "openai_key_configured":
            bool(
                os.getenv(
                    "OPENAI_API_KEY"
                )
            ),

        "anthropic_key_configured":
            bool(
                os.getenv(
                    "ANTHROPIC_API_KEY"
                )
            ),
    }


# ============================================================
# COST ESTIMATION
# ============================================================
#
# These are ESTIMATED prices used for project telemetry.
# Verify current Groq pricing before final submission.
# ============================================================

INPUT_PRICE_PER_MILLION = 0.15
OUTPUT_PRICE_PER_MILLION = 0.60


def estimate_cost(
    prompt_tokens,
    completion_tokens,
    input_price=INPUT_PRICE_PER_MILLION,
    output_price=OUTPUT_PRICE_PER_MILLION,
):
    """
    Estimate LLM API cost in USD.

    This is telemetry only. It is not used for model logic.
    """

    input_cost = (
        prompt_tokens
        / 1_000_000
        * input_price
    )

    output_cost = (
        completion_tokens
        / 1_000_000
        * output_price
    )

    return round(
        input_cost + output_cost,
        8,
    )


# ============================================================
# LOAD INSIGHT
# ============================================================

def load_insight():

    if not INSIGHT_PATH.exists():

        raise FileNotFoundError(
            "latest_insight.json not found.\n"
            f"Expected location:\n{INSIGHT_PATH}\n\n"
            "Run:\n"
            "python evidence/build_insight.py"
        )

    try:

        insight = json.loads(
            INSIGHT_PATH.read_text(
                encoding="utf-8"
            )
        )

    except json.JSONDecodeError as exc:

        raise RuntimeError(
            f"Invalid JSON in:\n{INSIGHT_PATH}"
        ) from exc

    return insight


def safe_round(value, digits=2):
    """Null-safe numeric rounding for sparse event evidence."""
    if value is None:
        return None

    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


# ============================================================
# BUILD COMPACT LLM CONTEXT
# ============================================================

def build_llm_context(
    insight,
    max_drivers=5,
):
    """Create a compact JSON-safe context for the selected event."""

    insight = insight or {}

    movement = (
        insight.get("movement", {})
        or {}
    )

    event = (
        insight.get("event", {})
        or {}
    )

    raw_drivers = (
        insight.get("drivers", [])
        or []
    )

    def driver_share(item):
        contribution = (
            item.get(
                "observed_contribution",
                {},
            )
            or {}
        )

        try:
            return abs(
                float(
                    contribution.get(
                        "share"
                    )
                )
            )
        except (
            TypeError,
            ValueError,
        ):
            return 0.0

    drivers = sorted(
        raw_drivers,
        key=driver_share,
        reverse=True,
    )

    compact_drivers = []

    for driver in drivers[:max_drivers]:

        contribution = (
            driver.get(
                "observed_contribution",
                {},
            )
            or {}
        )

        confidence = (
            driver.get(
                "confidence",
                {},
            )
            or {}
        )

        action = (
            driver.get(
                "action",
                {},
            )
            or {}
        )

        share = contribution.get(
            "share"
        )

        contribution_pct = (
            float(share) * 100
            if share is not None
            else None
        )

        compact_drivers.append(
            {
                "type":
                    driver.get(
                        "driver_type"
                    ),

                "driver":
                    driver.get(
                        "driver"
                    ),

                "gmv_change":
                    safe_round(
                        contribution.get(
                            "gmv_change"
                        ),
                        2,
                    ),

                "contribution_pct":
                    safe_round(
                        contribution_pct,
                        2,
                    ),

                "confidence":
                    safe_round(
                        confidence.get(
                            "overall"
                        ),
                        3,
                    ),

                "evidence_status":
                    driver.get(
                        "status"
                    ),

                "decision":
                    action.get(
                        "decision"
                    ),
            }
        )

    actions = []

    for action in (
        insight.get(
            "actions",
            [],
        )
        or []
    )[:8]:

        contribution_share = action.get(
            "contribution_share"
        )

        actions.append(
            {
                "driver_type":
                    action.get(
                        "driver_type"
                    ),

                "driver":
                    action.get(
                        "driver"
                    ),

                "contribution_pct":
                    safe_round(
                        (
                            float(
                                contribution_share
                            ) * 100
                            if contribution_share is not None
                            else None
                        ),
                        2,
                    ),

                "confidence":
                    safe_round(
                        action.get(
                            "confidence"
                        ),
                        3,
                    ),

                "evidence_status":
                    action.get(
                        "evidence_status"
                    ),

                "decision":
                    action.get(
                        "decision"
                    ),

                "owner":
                    action.get(
                        "owner"
                    ),

                "action":
                    action.get(
                        "action"
                    ),
            }
        )

    kpi = (
        insight.get(
            "kpi",
            {},
        )
        or {}
    )

    return make_json_serializable(
        {
            "kpi": {
                "id":
                    kpi.get("id"),

                "name":
                    kpi.get("name"),

                "currency":
                    kpi.get(
                        "currency",
                        "BRL",
                    )
                    or "BRL",

                "currency_symbol":
                    kpi.get(
                        "currency_symbol",
                        "R$",
                    )
                    or "R$",
            },

            "event": {
                "event_id":
                    event.get("event_id"),

                "start":
                    event.get("start_date"),

                "end":
                    event.get("end_date"),

                "duration_days":
                    event.get("duration_days"),

                "direction":
                    event.get("direction"),

                "priority":
                    event.get(
                        "investigation_priority"
                    ),

                "event_type":
                    event.get("event_type"),

                "source_coverage":
                    event.get(
                        "source_coverage"
                    ),
            },

            "movement": {
                "previous_gmv":
                    safe_round(
                        movement.get(
                            "previous_gmv"
                        ),
                        2,
                    ),

                "current_gmv":
                    safe_round(
                        movement.get(
                            "current_gmv"
                        ),
                        2,
                    ),

                "gmv_change":
                    safe_round(
                        movement.get(
                            "gmv_change"
                        ),
                        2,
                    ),

                "previous_orders":
                    movement.get(
                        "previous_orders"
                    ),

                "current_orders":
                    movement.get(
                        "current_orders"
                    ),

                "orders_change":
                    movement.get(
                        "orders_change"
                    ),

                "previous_aov":
                    safe_round(
                        movement.get(
                            "previous_aov"
                        ),
                        2,
                    ),

                "current_aov":
                    safe_round(
                        movement.get(
                            "current_aov"
                        ),
                        2,
                    ),

                "aov_change":
                    safe_round(
                        movement.get(
                            "aov_change"
                        ),
                        2,
                    ),

                "volume_effect":
                    safe_round(
                        movement.get(
                            "volume_effect"
                        ),
                        2,
                    ),

                "aov_effect":
                    safe_round(
                        movement.get(
                            "aov_effect"
                        ),
                        2,
                    ),

                "residual_effect":
                    safe_round(
                        movement.get(
                            "residual_effect"
                        ),
                        2,
                    ),
            },

            "drivers":
                compact_drivers,

            "actions":
                actions,

            "review_evidence":
                (
                    insight.get(
                        "review_evidence",
                        {},
                    )
                    or {}
            ),

            "customer_experience":
                (
                    insight.get(
                        "customer_experience",
                        {},
                    )
                    or {}
            ),

            "causal":
                (
                    insight.get(
                        "causal",
                        {},
                    )
                    or {}
            ),

            "data_quality":
                (
                    insight.get(
                        "data_quality",
                        {},
                    )
                    or {}
            ),

            "grounding": {
                "source_type":
                    "DYNAMIC_EVENT_INVESTIGATION",

                "event_id":
                    event.get(
                        "event_id"
                    ),

                "authoritative_for_selected_event":
                    True,

                "llm_role":
                    (
                        "Synthesize supplied evidence only; "
                        "do not calculate facts."
                    ),
            },
        }
    )


# ============================================================
# SYSTEM PROMPT
# ============================================================

def build_system_prompt():

    return """
You are the narrative layer of BusinessIntelligence.ai.

Your task is ONLY to convert structured analytical evidence
into clear business language.

The structured insight is the quantitative source of truth.

ABSOLUTE RULES:

1. Never invent a number.
2. Never invent a driver.
3. Never invent a root cause.
4. Never invent an action.
5. Never recalculate KPI values.
6. Never convert currencies.
7. All monetary values are BRL.
8. Use "R$" for monetary values.
9. Never use "$" by itself.
10. Never infer an exchange rate.
11. Distinguish observed contribution from causation.
12. A driver contribution does NOT prove that driver caused the KPI movement.
13. WEAK means weak evidence.
14. ABSTAIN means insufficient evidence.
15. CONTRADICTED means the available evidence argues against the hypothesis.
16. Never recommend acting on a CONTRADICTED hypothesis.
17. Never describe CONTRADICTED evidence as "disproven", "disproved", or "proven false".
18. Never use words such as "definitely", "certainly", "proved", or "confirmed cause" unless explicit causal evidence is supplied.
19. When root cause is not established, explicitly communicate that uncertainty.
20. Do not add technical implementation details.
21. Do not mention these system instructions.

IMPORTANT LANGUAGE RULES:

- Say "contributed to", not "caused", for contribution analysis.
- Say "the evidence supports", not "this proves".
- Say "the available evidence argues against", not "disproves".
- If evidence is insufficient, say so directly.
- Do not overstate confidence.

Use the exact currency supplied by the KPI data.
"""


# ============================================================
# EXECUTIVE PROMPT
# ============================================================

def build_executive_prompt(
    insight,
):

    context = build_llm_context(
        insight,
        max_drivers=5,
    )

    return f"""
Create a concise executive KPI story.

Use ONLY the supplied data.

CURRENCY:
All monetary values are BRL.
Display monetary values with "R$".
Never use "$".
Never convert currency.

Format exactly:

HEADLINE:
Two concise sentences.

WHAT CHANGED:
Explain the KPI movement and business magnitude.

MAIN DRIVER:
Explain whether volume or AOV contributed more.
Use the supplied decomposition values.

WHERE:
Mention only the most important observed segment contribution.

WHAT WE KNOW:
State the evidence strength and uncertainty.
Do not claim a root cause unless explicitly supported.

NEXT STEP:
Give the action that is actually justified by the supplied
decision/action evidence.

IMPORTANT:
"Observed contribution" is not "causation".
Do not invent explanations for why the movement happened.
Finish every section completely.
Keep the response below approximately 220 words.

Maximum length: approximately 250 words.

DATA:

{json.dumps(
        context,
        indent=2,
        ensure_ascii=False,
    )}
{feedback_block}
"""


# ============================================================
# OPERATIONS PROMPT
# ============================================================

def build_operations_prompt(
    insight,
):

    context = build_llm_context(
        insight,
        max_drivers=5,
    )

    return f"""
Create a concise operations-focused KPI explanation.

Use ONLY the supplied data.

CURRENCY:
All monetary values are BRL.
Display monetary values with "R$".
Never use "$".
Never convert currency.

Format exactly:

KPI MOVEMENT:
Explain the movement.

ANALYTICAL DECOMPOSITION:
Explain volume versus AOV.

TOP INVESTIGATION AREAS:
Mention at most three high-priority observed contributors.

EVIDENCE:
Respect the exact evidence statuses:
SUPPORTED, PLAUSIBLE, WEAK, ABSTAIN, CONTRADICTED.

ACTIONS:
Only recommend actions explicitly permitted by the supplied
decision/action fields.

DATA QUALITY:
Mention relevant limitations.

IMPORTANT:
- Never invent a root cause.
- Never change confidence.
- Never change evidence status.
- CONTRADICTED means do not act.
- ABSTAIN means collect more evidence.
- WEAK means investigate rather than conclude.
- Observed contribution is not causation.
- Never say that CONTRADICTED evidence "disproves" a hypothesis.
- Finish every section completely.
- Prefer concise sentences over repeating numbers.
- Do not repeat the same KPI value more than once unless necessary.
- Keep the response below approximately 280 words.

Maximum length: approximately 300 words.
Do not create a large table.

DATA:

{json.dumps(
        context,
        indent=2,
        ensure_ascii=False,
    )}
"""


# ============================================================
# JSON-SAFE CONTEXT
# ============================================================

def make_json_serializable(value):
    """
    Recursively convert dates, NumPy scalars, dictionaries and
    sequences into values accepted by json.dumps().
    """

    if value is None:
        return None

    if isinstance(
        value,
        (str, int, float, bool),
    ):
        return value

    if isinstance(
        value,
        (Path,),
    ):
        return str(value)

    # datetime/date/Pandas Timestamp-like objects.
    if hasattr(value, "isoformat") and callable(value.isoformat):
        try:
            return value.isoformat()
        except Exception:
            pass

    # NumPy/Pandas scalar values.
    if hasattr(value, "item"):
        try:
            return make_json_serializable(
                value.item()
            )
        except Exception:
            pass

    if isinstance(value, dict):
        return {
            str(key): make_json_serializable(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [
            make_json_serializable(item)
            for item in value
        ]

    # Last-resort string conversion for uncommon scalar objects.
    return str(value)


# ============================================================
# DYNAMIC EVENT PROMPTS
# ============================================================

def build_dynamic_event_context(
    investigation,
    max_drivers=6,
    max_review_aspects=6,
):
    """
    Normalize a stateless selected-event investigation into a compact,
    fully JSON-safe evidence package for the narrative layer.

    All derived percentages used in the prompt are computed here rather
    than asking the LLM to calculate them.
    """

    context = build_llm_context(
        investigation,
        max_drivers=max_drivers,
    )

    event = investigation.get(
        "event",
        {},
    )

    movement = investigation.get(
        "movement",
        {},
    )

    # --------------------------------------------------------
    # Event metadata
    # --------------------------------------------------------

    context["event"]["event_id"] = event.get(
        "event_id"
    )

    context["event"]["event_type"] = event.get(
        "event_type"
    )

    context["event"]["source_coverage"] = event.get(
        "source_coverage"
    )

    context["event"]["anomalous_days"] = event.get(
        "anomalous_days"
    )

    context["event"]["peak_z_score"] = event.get(
        "peak_z_score"
    )

    # --------------------------------------------------------
    # Deterministic decomposition ratios
    # --------------------------------------------------------

    gmv_change = float(
        movement.get(
            "gmv_change",
            0,
        )
        or 0
    )

    volume_effect = movement.get(
        "volume_effect"
    )

    aov_effect = movement.get(
        "aov_effect"
    )

    volume_share_pct = None
    aov_share_pct = None

    if abs(gmv_change) > 1e-12:

        if volume_effect is not None:
            volume_share_pct = round(
                abs(float(volume_effect))
                / abs(gmv_change)
                * 100,
                2,
            )

        if aov_effect is not None:
            aov_share_pct = round(
                abs(float(aov_effect))
                / abs(gmv_change)
                * 100,
                2,
            )

    context["decomposition"] = {
        "volume_effect":
            volume_effect,

        "aov_effect":
            aov_effect,

        "residual_effect":
            movement.get(
                "residual_effect",
                0.0,
            ),

        "volume_share_of_absolute_change_pct":
            volume_share_pct,

        "aov_share_of_absolute_change_pct":
            aov_share_pct,
    }

    # --------------------------------------------------------
    # Review evidence
    # --------------------------------------------------------

    review = investigation.get(
        "review_evidence",
        {},
    )

    aspect_rows = []

    for aspect in review.get(
        "aspect_summary",
        [],
    ):

        sentiment = aspect.get(
            "sentiment",
            {},
        )

        positive = sentiment.get(
            "positive",
            {},
        )

        negative = sentiment.get(
            "negative",
            {},
        )

        neutral = sentiment.get(
            "neutral",
            {},
        )

        aspect_rows.append(
            {
                "aspect":
                    aspect.get(
                        "aspect"
                    ),

                "event_mentions":
                    int(
                        aspect.get(
                            "event_mentions",
                            0,
                        )
                        or 0
                    ),

                "comparison_mentions":
                    int(
                        aspect.get(
                            "comparison_mentions",
                            0,
                        )
                        or 0
                    ),

                "mention_change":
                    int(
                        aspect.get(
                            "mention_change",
                            0,
                        )
                        or 0
                    ),

                "positive_event":
                    int(
                        positive.get(
                            "event_mentions",
                            0,
                        )
                        or 0
                    ),

                "positive_comparison":
                    int(
                        positive.get(
                            "comparison_mentions",
                            0,
                        )
                        or 0
                    ),

                "negative_event":
                    int(
                        negative.get(
                            "event_mentions",
                            0,
                        )
                        or 0
                    ),

                "negative_comparison":
                    int(
                        negative.get(
                            "comparison_mentions",
                            0,
                        )
                        or 0
                    ),

                "neutral_event":
                    int(
                        neutral.get(
                            "event_mentions",
                            0,
                        )
                        or 0
                    ),

                "neutral_comparison":
                    int(
                        neutral.get(
                            "comparison_mentions",
                            0,
                        )
                        or 0
                    ),
            }
        )

    aspect_rows.sort(
        key=lambda row: (
            abs(
                row["mention_change"]
            ),
            row["event_mentions"],
        ),
        reverse=True,
    )

    context["review_evidence"] = {
        # `record_count` is the number of aspect x sentiment groups.
        "aspect_sentiment_groups":
            review.get(
                "record_count",
                0,
            ),

        # These are the actual underlying evidence-row counts.
        "event_review_records":
            review.get(
                "event_review_records",
                0,
            ),

        "comparison_review_records":
            review.get(
                "comparison_review_records",
                0,
            ),

        "source":
            review.get(
                "source",
                "unknown",
            ),

        "dynamic":
            bool(
                review.get(
                    "dynamic",
                    False,
                )
            ),

        "aspects":
            aspect_rows[:max_review_aspects],
    }

    # --------------------------------------------------------
    # Customer experience
    # --------------------------------------------------------

    experience = investigation.get(
        "customer_experience",
        {},
    )

    # Only add if available. This keeps the batch generator unaffected.
    if experience:

        context["customer_experience"] = (
            make_json_serializable(
                experience
            )
        )

    # --------------------------------------------------------
    # Explicit grounding metadata
    # --------------------------------------------------------

    context["grounding"] = {
        "source_type":
            "DYNAMIC_EVENT_INVESTIGATION",

        "event_id":
            event.get(
                "event_id"
            ),

        "authoritative_for_selected_event":
            True,

        "llm_role":
            "Synthesize supplied evidence only; do not calculate facts.",
    }

    return make_json_serializable(
        context
    )


def build_dynamic_executive_prompt(
    investigation,
    validation_feedback=None,
):
    """
    Executive narrative prompt for an arbitrary selected event.
    """

    context = build_dynamic_event_context(
        investigation,
        max_drivers=6,
        max_review_aspects=6,
    )

    feedback_block = ""
    if validation_feedback:
        feedback_block = f"""

VALIDATION FEEDBACK FROM A PREVIOUS ATTEMPT:
The previous narrative did not pass grounding validation.
Correct ONLY the issues listed below. Do not invent new facts.

{json.dumps(
            validation_feedback,
            indent=2,
            ensure_ascii=False,
        )}
"""

    return f"""
Create a concise executive KPI story for the SELECTED EVENT.

Use ONLY the supplied structured evidence package.

This is an event-specific investigation. The package marked
DYNAMIC_EVENT_INVESTIGATION is authoritative for this event.

Do NOT use information from another event, stored narrative,
outside knowledge, or unstated assumptions.

IMPORTANT:
- Do not calculate new KPI values.
- Use supplied decomposition percentages when available.
- Do not say review evidence is unavailable when
  grounding.review_evidence contains records.
- "aspect_sentiment_groups" is NOT the number of reviews.
- When reporting review volume, use event_review_records or
  comparison_review_records.
- Review evidence describes observed customer feedback patterns;
  it does NOT establish causation.
- If source coverage is SOURCE_EDGE or priority is ABSTAIN,
  explicitly communicate the limitation.
- Never force a root-cause conclusion when the evidence is weak.

CURRENCY:
All monetary values are BRL.
Display monetary values with "R$".
Never use "$".
Never convert currency.

Required format:

HEADLINE:
Two concise sentences.

WHAT CHANGED:
Explain the selected event's KPI movement and magnitude.

MAIN DRIVER:
Explain whether volume or AOV contributed more, using the
supplied decomposition and supplied decomposition percentages.

WHERE:
Mention the most important observed contributor only when
material.

CUSTOMER EVIDENCE:
Use the supplied review/aspect evidence when available.
Mention meaningful changes in review mentions or sentiment,
but do not present them as causal proof.

WHAT WE KNOW:
Respect exact evidence statuses.
Explain uncertainty when root cause is not established.

NEXT STEP:
Use only the supplied action/decision evidence.
Never recommend acting on a CONTRADICTED hypothesis.
ABSTAIN means collect more evidence.
WEAK means investigate rather than conclude.

Keep the response below approximately 250 words.

SELECTED EVENT EVIDENCE:
{json.dumps(
        context,
        indent=2,
        ensure_ascii=False,
    )}
{feedback_block}
"""


def build_dynamic_operations_prompt(
    investigation,
    validation_feedback=None,
):
    """
    Operations narrative prompt for an arbitrary selected event.
    """

    context = build_dynamic_event_context(
        investigation,
        max_drivers=6,
        max_review_aspects=6,
    )

    feedback_block = ""
    if validation_feedback:
        feedback_block = f"""

VALIDATION FEEDBACK FROM A PREVIOUS ATTEMPT:
The previous narrative did not pass grounding validation.
Correct ONLY the issues listed below. Do not invent new facts.

{json.dumps(
            validation_feedback,
            indent=2,
            ensure_ascii=False,
        )}
"""

    return f"""
Create a concise operations-focused explanation for the
SELECTED EVENT.

Use ONLY the supplied structured evidence package.

This is an event-specific investigation. The package marked
DYNAMIC_EVENT_INVESTIGATION is authoritative for this event.

Do NOT use information from another event or a previously
generated narrative.

Required format:

KPI MOVEMENT:
Explain the movement.

ANALYTICAL DECOMPOSITION:
Explain volume versus AOV using the supplied values and
supplied decomposition percentages.

TOP INVESTIGATION AREAS:
Mention at most three material observed contributors.

CUSTOMER / REVIEW EVIDENCE:
Use the supplied aspect and sentiment evidence when available.
Describe observed changes such as increases/decreases in
negative or positive mentions. Do not claim those observations
caused the KPI movement.

ACTIONS:
Only describe decisions/actions that are explicitly supplied.

DATA QUALITY:
Mention relevant limitations, including missing context or
source-edge coverage.

RULES:
- Never invent a root cause.
- Never claim a segment caused the KPI movement.
- Never change confidence or evidence status.
- CONTRADICTED means do not act.
- ABSTAIN means collect more evidence.
- WEAK means investigate rather than conclude.
- Observed contribution is not causation.
- Do not calculate alternative metrics.
- Use supplied percentages rather than performing new arithmetic.
- Do not say customer/review evidence is unavailable when it
  is supplied in the evidence package.
- Do not describe the aspect/sentiment group count as the number
  of review records. Use the explicit event_review_records field.
- Keep the response below approximately 300 words.

SELECTED EVENT EVIDENCE:
{json.dumps(
        context,
        indent=2,
        ensure_ascii=False,
    )}
{feedback_block}
"""


def parse_model_target(
    provider,
    model,
):
    """Return normalized provider/model pair."""

    provider = (
        provider or "groq"
    ).strip().lower()

    model = (
        model or ""
    ).strip()

    if not model:
        raise ValueError(
            "LLM model name is empty."
        )

    return provider, model


def configured_model_candidates():
    """
    Build ordered primary + fallback model candidates.

    The primary candidate is always tried first.
    Duplicate provider/model pairs are removed while preserving order.
    """

    candidates = [
        (
            LLM_PROVIDER,
            MODEL_NAME,
        )
    ]

    for item in LLM_FALLBACKS:

        if ":" not in item:
            continue

        provider, model = item.split(
            ":",
            1,
        )

        candidates.append(
            (
                provider.strip().lower(),
                model.strip(),
            )
        )

    result = []
    seen = set()

    for provider, model in candidates:

        provider, model = parse_model_target(
            provider,
            model,
        )

        key = (
            provider,
            model,
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(key)

    return result


def create_provider_client(
    provider,
):
    """
    Create a provider client.

    OpenRouter is handled with direct HTTP in generate_story because
    Nemotron 3 Ultra is documented on OpenRouter's Anthropic Messages
    endpoint (/api/v1/messages), not only the OpenAI chat-completions path.
    """

    load_dotenv()

    provider = (
        provider or ""
    ).strip().lower()

    if provider == "openrouter":

        if not os.getenv(
            "OPENROUTER_API_KEY"
        ):
            raise RuntimeError(
                "OPENROUTER_API_KEY is not configured."
            )

        # No SDK client is required for OpenRouter Messages API.
        return None

    if provider == "groq":

        api_key = os.getenv(
            "GROQ_API_KEY"
        )

        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not configured."
            )

        return Groq(
            api_key=api_key
        )

    if provider == "openai":

        from openai import OpenAI

        api_key = os.getenv(
            "OPENAI_API_KEY"
        )

        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not configured."
            )

        return OpenAI(
            api_key=api_key
        )

    if provider == "anthropic":

        from anthropic import Anthropic

        api_key = os.getenv(
            "ANTHROPIC_API_KEY"
        )

        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not configured."
            )

        return Anthropic(
            api_key=api_key
        )

    raise RuntimeError(
        "Unsupported LLM provider: "
        f"{provider}"
    )


def generate_story(
    client,
    prompt,
    system_prompt,
    provider=None,
    model=None,
):
    """
    Generate one narrative.

    OpenRouter uses the Anthropic Messages-compatible endpoint so that
    Nemotron 3 Ultra receives the API format documented for that route.
    Other providers use their native/OpenAI-compatible SDKs.
    """

    provider = (
        provider or LLM_PROVIDER
    ).strip().lower()

    model = (
        model or MODEL_NAME
    ).strip()

    start_time = time.perf_counter()

    if LLM_DEBUG:

        print(
            f"[LLM] START provider={provider} "
            f"model={model}"
        )

    try:

        if provider == "openrouter":

            api_key = os.getenv(
                "OPENROUTER_API_KEY"
            )

            if not api_key:
                raise RuntimeError(
                    "OPENROUTER_API_KEY is not configured."
                )

            response = requests.post(
                "https://openrouter.ai/api/v1/messages",

                headers={
                    "Authorization":
                        f"Bearer {api_key}",

                    "Content-Type":
                        "application/json",

                    "HTTP-Referer":
                        "http://localhost:8501",

                    "X-Title":
                        "BusinessIntelligence.ai",
                },

                json={
                    "model":
                        model,

                    "system":
                        system_prompt,

                    "messages": [
                        {
                            "role":
                                "user",

                            "content":
                                prompt,
                        }
                    ],

                    "temperature":
                        TEMPERATURE,

                    "max_tokens":
                        MAX_OUTPUT_TOKENS,

                    "reasoning": {
                        "enabled":
                            False
                    },
                },

                timeout=(10, 45),
            )

            if response.status_code >= 400:

                raise RuntimeError(
                    "OpenRouter Messages API "
                    f"HTTP {response.status_code}: "
                    f"{response.text}"
                )

            data = response.json()

            content_parts = []

            for block in (
                data.get(
                    "content",
                    [],
                )
                or []
            ):

                if (
                    isinstance(
                        block,
                        dict,
                    )
                    and block.get(
                        "type"
                    ) == "text"
                ):

                    content_parts.append(
                        block.get(
                            "text",
                            "",
                        )
                    )

            content = "".join(
                content_parts
            ).strip()

            if not content:

                raise RuntimeError(
                    "OpenRouter returned no visible text "
                    f"for {model}. "
                    f"stop_reason={data.get('stop_reason')!r}; "
                    f"usage={data.get('usage')!r}; "
                    f"response_type={data.get('type')!r}"
                )

            usage = (
                data.get(
                    "usage",
                    {},
                )
                or {}
            )

            prompt_tokens = int(
                usage.get(
                    "input_tokens",
                    0,
                )
                or 0
            )

            completion_tokens = int(
                usage.get(
                    "output_tokens",
                    0,
                )
                or 0
            )

            reasoning_tokens = int(
                usage.get(
                    "reasoning_tokens",
                    0,
                )
                or 0
            )

            total_tokens = (
                prompt_tokens
                + completion_tokens
                + reasoning_tokens
            )

        elif provider == "anthropic":

            response = client.messages.create(
                model=model,

                system=system_prompt,

                messages=[
                    {
                        "role":
                            "user",

                        "content":
                            prompt,
                    }
                ],

                temperature=TEMPERATURE,

                max_tokens=MAX_OUTPUT_TOKENS,
            )

            parts = []

            for block in (
                getattr(
                    response,
                    "content",
                    [],
                )
                or []
            ):

                if getattr(
                    block,
                    "type",
                    None,
                ) == "text":

                    parts.append(
                        getattr(
                            block,
                            "text",
                            "",
                        )
                    )

            content = "".join(
                parts
            ).strip()

            usage = getattr(
                response,
                "usage",
                None,
            )

            prompt_tokens = int(
                getattr(
                    usage,
                    "input_tokens",
                    0,
                )
                or 0
            )

            completion_tokens = int(
                getattr(
                    usage,
                    "output_tokens",
                    0,
                )
                or 0
            )

            reasoning_tokens = 0

            total_tokens = (
                prompt_tokens
                + completion_tokens
            )

        else:

            request_kwargs = {
                "model":
                    model,

                "messages": [
                    {
                        "role":
                            "system",

                        "content":
                            system_prompt,
                    },

                    {
                        "role":
                            "user",

                        "content":
                            prompt,
                    },
                ],

                "temperature":
                    TEMPERATURE,

                "max_tokens":
                    MAX_OUTPUT_TOKENS,
            }

            if provider == "groq":

                request_kwargs[
                    "reasoning_effort"
                ] = REASONING_EFFORT

                request_kwargs[
                    "include_reasoning"
                ] = INCLUDE_REASONING

            response = (
                client
                .chat
                .completions
                .create(
                    **request_kwargs
                )
            )

            choices = getattr(
                response,
                "choices",
                None,
            )

            if not choices:

                raise RuntimeError(
                    f"{provider}:{model} returned "
                    "no completion choices."
                )

            message = (
                choices[0]
                .message
            )

            content = (
                getattr(
                    message,
                    "content",
                    None,
                )
                or ""
            ).strip()

            usage = getattr(
                response,
                "usage",
                None,
            )

            prompt_tokens = int(
                getattr(
                    usage,
                    "prompt_tokens",
                    0,
                )
                or 0
            )

            completion_tokens = int(
                getattr(
                    usage,
                    "completion_tokens",
                    0,
                )
                or 0
            )

            total_tokens = int(
                getattr(
                    usage,
                    "total_tokens",
                    0,
                )
                or 0
            )

            reasoning_tokens = 0

        if not content:

            raise RuntimeError(
                f"{provider}:{model} returned empty narrative content."
            )

    except Exception as exc:

        if LLM_DEBUG:

            print(
                f"[LLM] FAIL provider={provider} "
                f"model={model}: {exc}"
            )

        raise

    latency_ms = (
        time.perf_counter()
        - start_time
    ) * 1000

    estimated_cost = estimate_cost(
        prompt_tokens,
        completion_tokens,
    )

    if LLM_DEBUG:

        print(
            f"[LLM] SUCCESS provider={provider} "
            f"model={model} "
            f"tokens={total_tokens} "
            f"latency_ms={latency_ms:.0f}"
        )

    return {
        "story":
            content,

        "telemetry": {
            "provider":
                provider,

            "model":
                model,

            "model_purpose":
                MODEL_PURPOSE,

            "latency_ms":
                round(
                    latency_ms,
                    2,
                ),

            "prompt_tokens":
                prompt_tokens,

            "completion_tokens":
                completion_tokens,

            "reasoning_tokens":
                reasoning_tokens,

            "total_tokens":
                total_tokens,

            "model_calls":
                1,

            "reasoning_effort":
                REASONING_EFFORT,

            "reasoning_included":
                INCLUDE_REASONING,

            "temperature":
                TEMPERATURE,

            "max_completion_tokens":
                MAX_OUTPUT_TOKENS,

            "estimated_cost_usd":
                estimated_cost,

            "cost_is_estimate":
                True,
        },
    }


def smoke_test_provider(
    provider=None,
    model=None,
):
    """Direct test for the configured provider/model."""

    selected_provider = (
        provider or LLM_PROVIDER
    ).strip().lower()

    selected_model = (
        model or MODEL_NAME
    ).strip()

    if selected_provider != "openrouter":
        raise RuntimeError(
            "This smoke test is intended for OpenRouter."
        )

    api_key = os.getenv(
        "OPENROUTER_API_KEY"
    )

    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not configured."
        )

    response = requests.post(
        "https://openrouter.ai/api/v1/messages",

        headers={
            "Authorization":
                f"Bearer {api_key}",

            "Content-Type":
                "application/json",

            "HTTP-Referer":
                "http://localhost:8501",

            "X-Title":
                "BusinessIntelligence.ai",
        },

        json={
            "model":
                selected_model,

            "max_tokens":
                64,

            "temperature":
                0,

            "messages": [
                {
                    "role":
                        "user",

                    "content":
                        "Reply with exactly: "
                        "OPENROUTER_TEST_OK",
                }
            ],

            "reasoning": {
                "enabled":
                    False
            },
        },

        timeout=60,
    )

    if response.status_code >= 400:

        raise RuntimeError(
            f"OpenRouter smoke test HTTP "
            f"{response.status_code}: "
            f"{response.text}"
        )

    data = response.json()

    return "".join(
        block.get(
            "text",
            "",
        )
        for block in (
            data.get(
                "content",
                [],
            )
            or []
        )
        if (
            isinstance(block, dict)
            and block.get("type") == "text"
        )
    ).strip()


def clean_generated_narrative(
    story,
    persona,
):
    """
    Remove model meta-reasoning and keep only the requested business
    narrative sections. Incomplete narratives are rejected.
    """

    if not isinstance(
        story,
        str,
    ):
        raise RuntimeError(
            "Generated narrative is not text."
        )

    story = story.strip()

    if not story:
        raise RuntimeError(
            "Generated narrative is empty."
        )

    if persona == "executive":

        headings = [
            "HEADLINE",
            "WHAT CHANGED",
            "MAIN DRIVER",
            "WHERE",
            "CUSTOMER EVIDENCE",
            "WHAT WE KNOW",
            "NEXT STEP",
        ]

    else:

        headings = [
            "KPI MOVEMENT",
            "ANALYTICAL DECOMPOSITION",
            "TOP INVESTIGATION AREAS",
            "CUSTOMER / REVIEW EVIDENCE",
            "ACTIONS",
            "DATA QUALITY",
        ]

    normalized = story.replace(
        "\r\n",
        "\n",
    )

    heading_re = re.compile(
        r"(?im)^\s*(?:\*\*|__)?\s*"
        r"(" +
        "|".join(
            re.escape(h)
            for h in headings
        ) +
        r")\s*:?\s*(?:\*\*|__)?\s*$"
    )

    matches = list(
        heading_re.finditer(
            normalized
        )
    )

    if not matches:

        raise RuntimeError(
            f"{persona} narrative contains no required sections."
        )

    # Ignore all text before the first actual output heading.
    normalized = normalized[
        matches[0].start():
    ]

    matches = list(
        heading_re.finditer(
            normalized
        )
    )

    sections = []

    for index, match in enumerate(matches):

        title = match.group(1)

        expected_index = None

        for i, heading in enumerate(
            headings
        ):

            if heading.lower() == title.lower():

                expected_index = i
                break

        if expected_index is None:
            continue

        next_start = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(normalized)
        )

        body = normalized[
            match.end():
            next_start
        ].strip()

        if body:

            sections.append(
                f"{headings[expected_index]}:\n{body}"
            )

    # Require every section in order.
    found_names = [
        section.split(
            ":\n",
            1
        )[0]
        for section in sections
    ]

    if found_names != headings:

        raise RuntimeError(
            f"{persona} narrative is incomplete. "
            f"Expected {headings}; found {found_names}."
        )

    cleaned = "\n\n".join(
        sections
    ).strip()

    forbidden_meta = (
        "The user wants me",
        "Let me analyze",
        "Let's analyze",
        "Let's parse the evidence",
        "Thinking Process:",
        "Constraint Check",
        "Draft:",
        "I need to",
        "I should",
        "Now I need",
    )

    lowered = cleaned.lower()

    for phrase in forbidden_meta:

        if phrase.lower() in lowered:

            raise RuntimeError(
                f"{persona} narrative contains "
                "model meta-commentary."
            )

    return cleaned


def _generate_one_persona_candidate(
    investigation,
    persona,
    provider,
    model,
    validation_feedback=None,
):
    """
    Generate, clean, and return one persona narrative.

    This function is intentionally self-contained so candidates can run
    concurrently without sharing mutable provider state.
    """

    started = time.perf_counter()

    client = create_provider_client(
        provider
    )

    system_prompt = build_system_prompt()

    if persona == "executive":

        prompt = build_dynamic_executive_prompt(
            investigation,
            validation_feedback,
        )

    else:

        prompt = build_dynamic_operations_prompt(
            investigation,
            validation_feedback,
        )

    result = generate_story(
        client,
        prompt,
        system_prompt,
        provider=provider,
        model=model,
    )

    result["story"] = clean_generated_narrative(
        result["story"],
        persona,
    )

    result["telemetry"]["router_elapsed_ms"] = round(
        (time.perf_counter() - started) * 1000,
        2,
    )

    return result


def _race_persona_candidates(
    investigation,
    persona,
    candidates,
    validation_feedback=None,
):
    """
    Run all configured candidates concurrently for one persona.

    The first candidate that produces a valid cleaned narrative wins.
    A slow or failed model therefore does not block a faster fallback.
    """

    if not candidates:
        raise RuntimeError(
            f"No configured LLM candidates for {persona}."
        )

    failures = []
    winner = None

    max_workers = len(candidates)

    with ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix=f"llm-{persona}",
    ) as executor:

        future_map = {
            executor.submit(
                _generate_one_persona_candidate,
                investigation,
                persona,
                provider,
                model,
                validation_feedback,
            ): (
                provider,
                model,
            )
            for provider, model in candidates
        }

        for future in as_completed(
            future_map
        ):

            provider, model = future_map[
                future
            ]

            try:

                result = future.result()

                winner = (
                    provider,
                    model,
                    result,
                )

                # Do not wait for slower candidates. Futures that have not
                # started are cancelled; already-running HTTP requests may
                # finish in the background but their results are ignored.
                for other in future_map:

                    if other is not future:
                        other.cancel()

                if LLM_DEBUG:

                    print(
                        f"[LLM ROUTER] WINNER persona={persona} "
                        f"provider={provider} model={model}"
                    )

                break

            except Exception as exc:

                error_text = str(exc)

                failures.append(
                    {
                        "provider":
                            provider,

                        "model":
                            model,

                        "error":
                            error_text,
                    }
                )

                if LLM_DEBUG:

                    print(
                        f"[LLM ROUTER] FAILED persona={persona} "
                        f"provider={provider} model={model}: "
                        f"{error_text}"
                    )

    if winner is None:

        raise RuntimeError(
            f"All configured LLM candidates failed for "
            f"{persona}. "
            + json.dumps(
                failures,
                ensure_ascii=False,
            )
        )

    provider, model, result = winner

    return {
        "result":
            result,

        "model_route": {
            "provider":
                provider,

            "model":
                model,

            "parallel_candidates":
                len(candidates),

            "failed_candidates_before_winner":
                failures,
        },
    }


def generate_event_narratives(
    investigation,
    validation_feedback=None,
):
    """
    Generate Executive + Operations narratives using concurrent candidate
    racing.

    IMPORTANT:
    - Candidates are NOT tried serially.
    - A slow/failed primary therefore does not add its timeout to the
      successful fallback.
    - Executive and Operations race independently.
    - The first successful, cleaned narrative wins for each persona.
    """

    load_dotenv()

    event_id = (
        investigation
        .get("event", {})
        .get("event_id")
    )

    if event_id is None:

        raise ValueError(
            "Selected-event investigation is missing event_id."
        )

    candidates = configured_model_candidates()

    if not candidates:

        raise RuntimeError(
            "No LLM candidates are configured."
        )

    # Two persona races are also independent. This means Operations does not
    # wait for Executive, and vice versa.
    with ThreadPoolExecutor(
        max_workers=2,
        thread_name_prefix="llm-persona",
    ) as executor:

        executive_future = executor.submit(
            _race_persona_candidates,
            investigation,
            "executive",
            candidates,
            validation_feedback,
        )

        operations_future = executor.submit(
            _race_persona_candidates,
            investigation,
            "operations",
            candidates,
            validation_feedback,
        )

        try:

            executive_package = (
                executive_future.result()
            )

            operations_package = (
                operations_future.result()
            )

        except Exception:

            # Ensure the other task is no longer queued before propagating.
            executive_future.cancel()
            operations_future.cancel()
            raise

    executive = executive_package[
        "result"
    ]

    operations = operations_package[
        "result"
    ]

    return {
        "event_id":
            event_id,

        "executive":
            executive,

        "operations":
            operations,

        "generated":
            True,

        "source":
            "selected_event_investigation",

        "model_route": {
            "executive":
                executive_package[
                    "model_route"
                ],

            "operations":
                operations_package[
                    "model_route"
                ],
        },
    }



# ============================================================
# SAVE STORY
# ============================================================

def save_story(
    persona,
    insight,
    result,
):

    output_dir = (
        PROJECT_ROOT
        / "data"
        / "insights"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = {

        "insight_id":
            insight[
                "insight_id"
            ],

        "persona":
            persona,

        "story":
            result[
                "story"
            ],

        "telemetry":
            result[
                "telemetry"
            ],
    }

    output_path = (
        output_dir
        / f"{persona}_story.json"
    )

    output_path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return output_path


# ============================================================
# PRINT TELEMETRY
# ============================================================

def print_telemetry(
    persona,
    telemetry,
):

    print(
        f"\n{persona.upper()} TELEMETRY"
    )

    print(
        f"Model              : "
        f"{telemetry['model']}"
    )

    print(
        f"Purpose            : "
        f"{telemetry['model_purpose']}"
    )

    print(
        f"Latency            : "
        f"{telemetry['latency_ms']} ms"
    )

    print(
        f"Prompt tokens      : "
        f"{telemetry['prompt_tokens']}"
    )

    print(
        f"Completion tokens  : "
        f"{telemetry['completion_tokens']}"
    )

    print(
        f"Total tokens       : "
        f"{telemetry['total_tokens']}"
    )

    print(
        f"Estimated cost     : "
        f"${telemetry['estimated_cost_usd']:.8f}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n")
    print("=" * 100)
    print("BusinessIntelligence.ai")
    print("LLM STORY GENERATOR")
    print("=" * 100)

    # --------------------------------------------------------
    # Load environment
    # --------------------------------------------------------

    load_dotenv()

    # --------------------------------------------------------
    # Load insight
    # --------------------------------------------------------

    insight = load_insight()

    # --------------------------------------------------------
    # Create configured primary-provider client
    # --------------------------------------------------------

    primary_provider, primary_model = (
        configured_model_candidates()[0]
    )

    client = create_provider_client(
        primary_provider
    )

    system_prompt = (
        build_system_prompt()
    )

    # ========================================================
    # EXECUTIVE
    # ========================================================

    print(
        "\n[LLM] Generating executive story..."
    )

    executive = generate_story(
        client,
        build_executive_prompt(
            insight
        ),
        system_prompt,
        provider=primary_provider,
        model=primary_model,
    )

    executive_path = save_story(
        "executive",
        insight,
        executive,
    )

    print(
        f"[OK] Executive story saved: "
        f"{executive_path}"
    )

    # ========================================================
    # OPERATIONS
    # ========================================================

    print(
        "\n[LLM] Generating operations story..."
    )

    operations = generate_story(
        client,
        build_operations_prompt(
            insight
        ),
        system_prompt,
        provider=primary_provider,
        model=primary_model,
    )

    operations_path = save_story(
        "operations",
        insight,
        operations,
    )

    print(
        f"[OK] Operations story saved: "
        f"{operations_path}"
    )

    # ========================================================
    # STORIES
    # ========================================================

    print("\n" + "=" * 100)
    print("EXECUTIVE STORY")
    print("=" * 100)

    print(
        executive["story"]
    )

    print("\n" + "=" * 100)
    print("OPERATIONS STORY")
    print("=" * 100)

    print(
        operations["story"]
    )

    # ========================================================
    # TELEMETRY
    # ========================================================

    print("\n" + "=" * 100)
    print("LLM TELEMETRY")
    print("=" * 100)

    print(
        json.dumps(
            {
                "executive":
                    executive[
                        "telemetry"
                    ],

                "operations":
                    operations[
                        "telemetry"
                    ],
            },
            indent=2,
        )
    )

    print_telemetry(
        "executive",
        executive[
            "telemetry"
        ],
    )

    print_telemetry(
        "operations",
        operations[
            "telemetry"
        ],
    )

    print("\n" + "=" * 100)
    print("LLM STORY GENERATION COMPLETE")
    print("=" * 100)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
