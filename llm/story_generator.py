from pathlib import Path
import json
import os
import re
import time
import ast
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
# Example current configuration:
# openrouter:openrouter/free
LLM_FALLBACKS = [
    item.strip()
    for item in os.getenv(
        "LLM_FALLBACKS",
        "openrouter:openrouter/free",
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

# Base URL of a local OpenAI-compatible inference server.
# Defaults to Ollama (http://localhost:11434/v1).
# LM Studio: http://localhost:1234/v1
# llama.cpp server / vLLM: their respective /v1 endpoints.
LOCAL_LLM_BASE_URL = os.getenv(
    "LLM_BASE_URL",
    "http://localhost:11434/v1",
).strip().rstrip("/")

# Request mode for the local provider:
#   - "ollama": native Ollama /api/chat with thinking disabled
#     (recommended for Qwen3; reasoning cannot be disabled on
#     Ollama's OpenAI-compatible endpoint).
#   - "openai": generic OpenAI-compatible /v1/chat/completions
#     (LM Studio, llama.cpp server, vLLM, ...).
LOCAL_LLM_API_MODE = os.getenv(
    "LLM_LOCAL_API_MODE",
    "ollama",
).strip().lower()

# Sampling temperature for the local model only.
# Qwen3 (non-thinking mode) is tuned for ~0.6-0.7; the global
# 0.1 setting makes small local models unusually terse.
LOCAL_LLM_TEMPERATURE = float(
    os.getenv(
        "LLM_LOCAL_TEMPERATURE",
        "0.6",
    )
)

# Repetition penalty for the local model. Qwen3 8B can fall into
# repeating one section until the token budget is exhausted.
# Ollama default is 1.1; 1.2-1.3 actively prevents loop stalls.
LOCAL_LLM_REPEAT_PENALTY = float(
    os.getenv(
        "LLM_LOCAL_REPEAT_PENALTY",
        "1.3",
    )
)

# Context window for the local model. The CUDA compute/KV buffers
# scale with this value, so large contexts can exhaust small-VRAM
# GPUs (e.g. 6GB laptop GPUs) at model load time.
LOCAL_LLM_NUM_CTX = int(
    os.getenv(
        "LLM_LOCAL_NUM_CTX",
        "4096",
    )
)

# Sticky CPU-inference switch for the local provider. Set to True
# after a CUDA out-of-memory failure so subsequent local requests
# run fully on CPU (slow but reliable) instead of crashing
# llama-server again.
_LOCAL_FORCE_CPU = False


def _is_vram_oom_error(error_text):
    """
    Detect GPU out-of-memory failures reported by the local
    inference server (llama-server / Ollama).
    """

    lowered = (error_text or "").lower()

    return (
        "out of memory" in lowered
        or "cuda0 buffer" in lowered
        or "cudamalloc" in lowered
        or "llama-server process has terminated" in lowered
    )


def _build_local_ollama_options(
    temperature=None,
    num_predict=None,
):
    """
    Build Ollama option overrides for local inference requests.

    VRAM-aware: once a CUDA out-of-memory error has been seen, all
    local requests force full CPU inference (num_gpu: 0) so
    generation still completes on small-VRAM GPUs.
    """

    options = {
        "temperature": (
            LOCAL_LLM_TEMPERATURE
            if temperature is None
            else temperature
        ),
        "num_predict": (
            MAX_OUTPUT_TOKENS
            if num_predict is None
            else num_predict
        ),
        "repeat_penalty": LOCAL_LLM_REPEAT_PENALTY,
        "num_ctx": LOCAL_LLM_NUM_CTX,
    }

    if _LOCAL_FORCE_CPU:
        options["num_gpu"] = 0

    return options

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

        "local_base_url":
            LOCAL_LLM_BASE_URL,

        "local_api_mode":
            LOCAL_LLM_API_MODE,

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
22. Always complete every requested section.
23. Never stop early.
24. Never spend output on hidden analysis, reasoning, or planning.
25. The final response must contain all requested headings even when a section has little or no evidence; state the limitation instead of omitting it.

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

    feedback_block = ""

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
WHAT CHANGED:
MAIN DRIVER:
WHERE:
CUSTOMER EVIDENCE:
WHAT WE KNOW:
NEXT STEP:

SECTION GUIDANCE (follow these; NEVER copy this wording into the
narrative text):

- HEADLINE: two concise sentences.
- WHAT CHANGED: explain the KPI movement and business magnitude.
- MAIN DRIVER: explain whether volume or AOV contributed more.
  Use the supplied decomposition values.
- WHERE: mention only the most important observed segment
  contribution.
- CUSTOMER EVIDENCE: summarize the supplied review evidence.
- WHAT WE KNOW: state the evidence strength and uncertainty.
  Do not claim a root cause unless explicitly supported.
- NEXT STEP: give the action actually justified by the supplied
  decision/action evidence.

IMPORTANT:
"Observed contribution" is not "causation".
Do not invent explanations for why the movement happened.
Finish every section completely.
Keep the response below approximately 220 words.
NEVER quote or copy any instruction or guidance text into the
narrative output itself.

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

    feedback_block = ""

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
ANALYTICAL DECOMPOSITION:
TOP INVESTIGATION AREAS:
EVIDENCE:
ACTIONS:
DATA QUALITY:

SECTION GUIDANCE (follow these; NEVER copy this wording into the
narrative text):

- KPI MOVEMENT: explain the movement.
- ANALYTICAL DECOMPOSITION: explain volume versus AOV.
- TOP INVESTIGATION AREAS: mention at most three high-priority
  observed contributors.
- EVIDENCE: respect the exact evidence statuses:
  SUPPORTED, PLAUSIBLE, WEAK, ABSTAIN, CONTRADICTED.
- ACTIONS: only recommend actions explicitly permitted by the
  supplied decision/action fields.
- DATA QUALITY: mention relevant limitations.

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
- NEVER quote or copy any instruction or guidance text into the
  narrative output itself.

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
Create a detailed, evidence-grounded executive KPI story for
the SELECTED EVENT.

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

Required format.

OUTPUT FORMAT — write EXACTLY these seven headings, each on its own
line, each followed by your narrative paragraph. Copy the heading
spelling verbatim (singular form, with its colon). Never pluralize,
rename, merge, or add headings. In particular the last heading is
exactly "NEXT STEP:" with no "S".

HEADLINE:
WHAT CHANGED:
MAIN DRIVER:
WHERE:
CUSTOMER EVIDENCE:
WHAT WE KNOW:
NEXT STEP:

SECTION GUIDANCE (follow these instructions; NEVER copy any of this
wording into the narrative text itself):

- HEADLINE: exactly two sentences. Sentence one states the KPI, the
  absolute BRL change and the event window. Sentence two states why
  it matters to the business.
- WHAT CHANGED: at least three sentences. Always cite the previous
  value, the current value, and the absolute change exactly as
  supplied in the movement evidence. Also cover the order-count
  change and the AOV change when they are supplied, and explain what
  the change means for the business.
- MAIN DRIVER: at least three sentences. Name which of volume or AOV
  contributed more, then cite BOTH effect values and BOTH percentage
  shares exactly as supplied, and interpret what that mix means for
  the business (orders vs basket size).
- WHERE: at least three sentences. Name every driver supplied in the
  top-contributors evidence, each with its contribution percentage
  and its evidence status (weak, insufficient, or contradicted).
- CUSTOMER EVIDENCE: at least three sentences. For the two or three
  most significant aspects, state both the event-period count and
  the comparison-period count exactly as supplied, and describe the
  direction of the change in sentiment or volume. NEVER compute or
  state the difference between two supplied counts. Do not present
  review patterns as causal proof.
- WHAT WE KNOW: at least three sentences. Summarize the evidence
  status per key driver (which are weak, which are insufficient,
  which are contradicted) and explain what remains uncertain and
  why root cause is not established.
- NEXT STEP: at least two sentences. Name the specific supplied
  action(s) and the team that owns them. Never recommend acting on a
  CONTRADICTED hypothesis.
  ABSTAIN means collect more evidence.
  WEAK means investigate rather than conclude.

LENGTH: the finished narrative should be 320 to 400 words in total.
Every section must contain real evidence-backed content; never
substitute a section with a single vague sentence.

STRICT RULES:
- Output nothing before HEADLINE.
- Output nothing after NEXT STEP.
- Every heading MUST appear exactly once.
- Never omit a heading.
- Never add extra headings.
- Never merge two headings into one.
- Write exactly one paragraph per heading, then move to the
  next heading.
- Never repeat the same section a second time.
- Never rewrite a section you have already written.
- Never output analysis, reasoning, drafts, or commentary.
- NEVER quote or copy any instruction, guidance, or template text
  from this prompt into the narrative. In particular, never write
  phrases such as "At least two full sentences", "use the supplied
  evidence", "with its colon", or "moving to the next heading".
- Never calculate a new number.
- Never invent a number.
- Only report numbers explicitly present in the evidence.
- Never compute a percentage change from two other numbers.
- Never state confidence values, thresholds, or record counts.
- CONTRADICTED = do not act.
- ABSTAIN = collect more evidence.
- WEAK = investigate, not conclude.
- Observed contribution is not causation.

LENGTH:
Aim for approximately 300 to 360 words in total. Develop each
section with the specific figures supplied; do not compress the
story into one sentence per section.

REMINDER:
The finished narrative MUST contain all seven headings in order.
Your response is INCOMPLETE unless every heading from HEADLINE
to NEXT STEP appears exactly once. Write the response from the
first heading to the last without stopping early.

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
    context = build_dynamic_event_context(
        investigation,
        max_drivers=3,
        max_review_aspects=3,
    )

    feedback_block = ""
    if validation_feedback:
        feedback_block = f"""
VALIDATION FEEDBACK:
Fix ONLY these issues:
{json.dumps(
    validation_feedback,
    indent=2,
    ensure_ascii=False,
)}
"""

    return f"""
Write the Operations KPI narrative for the SELECTED EVENT.

Use ONLY the supplied evidence.
Do not calculate, infer, combine, or invent facts.

OUTPUT FORMAT — write EXACTLY these six headings, each on its own
line, each followed by your narrative paragraph. Copy the heading
spelling verbatim (singular form, with its colon). Never pluralize,
rename, merge, or add headings.

KPI MOVEMENT:
ANALYTICAL DECOMPOSITION:
TOP INVESTIGATION AREAS:
CUSTOMER / REVIEW EVIDENCE:
ACTIONS:
DATA QUALITY:

SECTION GUIDANCE (follow these instructions; NEVER copy any of this
wording into the narrative text itself):

- KPI MOVEMENT: at least three sentences. Cite the previous value,
  the current value, and the absolute BRL change exactly as
  supplied, and state what the magnitude means for operations.
- ANALYTICAL DECOMPOSITION: at least three sentences. Cite the
  volume effect and the AOV effect with BOTH of their percentage
  shares exactly as supplied, and interpret what that mix means for
  day-to-day operations (order flow vs basket size).
- TOP INVESTIGATION AREAS: name up to three items. For each item
  give its contribution percentage and its evidence status (weak,
  insufficient, or contradicted), plus one concrete operational
  question to investigate.
- CUSTOMER / REVIEW EVIDENCE: at least three sentences. For the
  most significant aspects, state both the event-period count and
  the comparison-period count exactly as supplied and describe the
  direction of the change. NEVER compute or state the difference
  between two supplied counts. Do not present review patterns as
  causal proof.
- ACTIONS: name each supplied decision as a directive sentence
  (which team investigates or collects what, for which driver). If
  no action is justified for a driver, say so explicitly.
- DATA QUALITY: at least two sentences using ONLY supplied
  data-quality information: name the commerce source, whether review
  text is available, and whether business context is available.
  NEVER state record counts or totals.

LENGTH: the finished narrative should be 280 to 360 words in total.
Every section must contain real evidence-backed content; never
substitute a section with a single vague sentence.

STRICT RULES:
- Output nothing before KPI MOVEMENT.
- Output nothing after DATA QUALITY.
- Every heading MUST appear exactly once.
- Never omit a heading.
- Never add extra headings.
- Never output analysis, reasoning, drafts, or commentary.
- NEVER quote or copy any instruction, guidance, or template text
  from this prompt into the narrative.
- NEVER state record counts, review-count totals, confidence values,
  or thresholds, even when the evidence contains them.
- NEVER subtract two supplied numbers or state a computed difference.
- Never calculate a new number.
- Never sum or derive review counts.
- Never invent a number.
- Only report numbers explicitly present in the evidence.
- Never compute a percentage change from two other numbers.
- Never state confidence values, thresholds, or record counts.
- Do not repeat the same number unnecessarily.
- CONTRADICTED = do not act.
- ABSTAIN = collect more evidence.
- WEAK = investigate, not conclude.
- Observed contribution is not causation.

LENGTH:
Aim for approximately 250 to 320 words in total. Develop each
section with the specific figures supplied; do not compress the
story into one sentence per section.

REMINDER:
The finished narrative MUST contain all six headings in order.
Your response is INCOMPLETE unless every heading above appears
exactly once, in order. Write the response from the first heading
to the last without stopping early. Continue until you have
produced every section.

EVIDENCE:
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

    if provider == "local":

        # Local OpenAI-compatible servers (Ollama, LM Studio,
        # llama.cpp server, vLLM) need no API key. All calls are
        # made with direct HTTP inside generate_story.
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

    used_temperature = TEMPERATURE

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

        elif provider == "local":

            # Local inference uses its own sampling temperature
            # (Qwen3 non-thinking mode is tuned for ~0.6).
            used_temperature = LOCAL_LLM_TEMPERATURE

            # Local inference server. Two request modes:
            #   "ollama" -> native /api/chat with thinking disabled
            #   "openai" -> OpenAI-compatible /v1/chat/completions
            if LOCAL_LLM_API_MODE == "ollama":

                ollama_base = LOCAL_LLM_BASE_URL

                if ollama_base.endswith("/v1"):
                    ollama_base = ollama_base[:-3]

                response = requests.post(
                    f"{ollama_base}/api/chat",

                    headers={
                        "Content-Type":
                            "application/json",
                    },

                    json={
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
                            }
                        ],

                        "stream":
                            False,

                        # Qwen3 is a thinking model. Disable visible
                        # reasoning so the full token budget goes to
                        # the governed narrative.
                        "think":
                            False,

                        "options":
                            _build_local_ollama_options(),
                    },

                    # Local inference can be much slower than a
                    # hosted API, especially on CPU.
                    timeout=(10, 600),
                )

                if response.status_code >= 400:

                    raise RuntimeError(
                        "Local LLM api/chat "
                        f"HTTP {response.status_code}: "
                        f"{response.text}"
                    )

                data = response.json()

                message = (
                    data.get("message")
                    or {}
                )

                content = (
                    message.get("content")
                    or ""
                ).strip()

                # Defensive: strip any <think>...</think> blocks
                # even when thinking is disabled server-side.
                content = re.sub(
                    r"<think>.*?</think>",
                    "",
                    content,
                    flags=re.DOTALL,
                ).strip()

                if not content:

                    raise RuntimeError(
                        "Local LLM returned no visible text "
                        f"for {model}. "
                        f"done_reason={data.get('done_reason')!r}; "
                        f"response={data!r}"
                    )

                # Native Ollama usage counters.
                prompt_tokens = int(
                    data.get(
                        "prompt_eval_count",
                        0,
                    )
                    or 0
                )

                completion_tokens = int(
                    data.get(
                        "eval_count",
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

                # Generic OpenAI-compatible inference server
                # (LM Studio, llama.cpp server, vLLM, ...).
                base_url = LOCAL_LLM_BASE_URL

                response = requests.post(
                    f"{base_url}/chat/completions",

                    headers={
                        "Content-Type":
                            "application/json",
                    },

                    json={
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
                            }
                        ],

                        "temperature":
                            LOCAL_LLM_TEMPERATURE,

                        "max_tokens":
                            MAX_OUTPUT_TOKENS,

                        # Qwen3 is a thinking model. Disable visible
                        # reasoning so the full token budget goes to
                        # the governed narrative. Ollama only honors
                        # this on the OpenAI-compatible endpoint, so
                        # the local API mode must be "openai".
                        "think":
                            False,
                    },

                    # Local inference can be much slower than a
                    # hosted API, especially on CPU.
                    timeout=(10, 600),
                )

                if response.status_code >= 400:

                    raise RuntimeError(
                        "Local LLM chat/completions "
                        f"HTTP {response.status_code}: "
                        f"{response.text}"
                    )

                data = response.json()

                choices = (
                    data.get("choices")
                    or []
                )

                if not choices:

                    raise RuntimeError(
                        f"Local LLM returned no choices "
                        f"for {model}. "
                        f"response={data!r}"
                    )

                message = (
                    choices[0].get("message")
                    or {}
                )

                content = (
                    message.get("content")
                    or ""
                ).strip()

                # Qwen3 (and other thinking models) can emit
                # visible <think>...</think> blocks. Strip them
                # so only the final narrative reaches the
                # validator.
                content = re.sub(
                    r"<think>.*?</think>",
                    "",
                    content,
                    flags=re.DOTALL,
                ).strip()

                if not content:

                    raise RuntimeError(
                        "Local LLM returned no visible text "
                        f"for {model}. "
                        f"finish_reason="
                        f"{choices[0].get('finish_reason')!r}; "
                        f"response={data!r}"
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
                        "prompt_tokens",
                        0,
                    )
                    or 0
                )

                completion_tokens = int(
                    usage.get(
                        "completion_tokens",
                        0,
                    )
                    or 0
                )

                reasoning_tokens = 0

                total_tokens = (
                    prompt_tokens
                    + completion_tokens
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

    if provider == "local":
        # Local inference has no per-token API cost.
        estimated_cost = 0.0
    else:
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
                used_temperature,

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
    """
    Direct provider smoke test.

    Supported:
        - groq
        - openrouter
        - local (OpenAI-compatible server at LLM_BASE_URL)
    """

    selected_provider = (
        provider or LLM_PROVIDER
    ).strip().lower()

    selected_model = (
        model or MODEL_NAME
    ).strip()

    if selected_provider == "groq":
        client = create_provider_client("groq")

        response = (
            client
            .chat
            .completions
            .create(
                model=selected_model,
                messages=[
                    {
                        "role":
                            "user",

                        "content":
                            "Reply with exactly: GROQ_TEST_OK",
                    }
                ],
                temperature=0,
                max_tokens=64,
                reasoning_effort="low",
                include_reasoning=False,
            )
        )

        choices = getattr(
            response,
            "choices",
            None,
        )

        if not choices:
            raise RuntimeError(
                f"Groq smoke test returned no choices: {response!r}"
            )

        content = (
            getattr(
                choices[0].message,
                "content",
                None,
            )
            or ""
        ).strip()

        if not content:
            raise RuntimeError(
                f"Groq smoke test returned empty content. "
                f"response={response!r}"
            )

        return content

    if selected_provider == "openrouter":
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

                "system":
                    "Reply exactly with the requested test token.",

                "messages": [
                    {
                        "role":
                            "user",

                        "content":
                            "Reply with exactly: OPENROUTER_TEST_OK",
                    }
                ],

                "temperature":
                    0,

                "max_tokens":
                    32,

                "reasoning": {
                    "enabled":
                        False,
                },
            },

            timeout=(10, 30),
        )

        if response.status_code >= 400:
            raise RuntimeError(
                f"OpenRouter smoke test HTTP "
                f"{response.status_code}: "
                f"{response.text}"
            )

        data = response.json()

        content = "".join(
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

        if not content:
            raise RuntimeError(
                "OpenRouter smoke test returned empty visible text. "
                f"response={data!r}"
            )

        return content

    if selected_provider == "local":

        if LOCAL_LLM_API_MODE == "ollama":

            ollama_base = LOCAL_LLM_BASE_URL

            if ollama_base.endswith("/v1"):
                ollama_base = ollama_base[:-3]

            response = requests.post(
                f"{ollama_base}/api/chat",

                headers={
                    "Content-Type":
                        "application/json",
                },

                json={
                    "model":
                        selected_model,

                    "messages": [
                        {
                            "role":
                                "user",

                            "content":
                                "Reply with exactly: LOCAL_TEST_OK",
                        }
                    ],

                    "stream":
                        False,

                    "think":
                        False,

                    "options":
                        _build_local_ollama_options(
                            temperature=0,
                            num_predict=32,
                        ),
                },

                timeout=(10, 120),
            )

            if response.status_code >= 400:
                raise RuntimeError(
                    "Local LLM smoke test HTTP "
                    f"{response.status_code}: "
                    f"{response.text}"
                )

            data = response.json()

            content = (
                (
                    data.get("message")
                    or {}
                )
                .get("content", "")
                or ""
            ).strip()

            content = re.sub(
                r"<think>.*?</think>",
                "",
                content,
                flags=re.DOTALL,
            ).strip()

            if not content:
                raise RuntimeError(
                    "Local LLM smoke test returned empty content. "
                    f"response={data!r}"
                )

            return content

        base_url = LOCAL_LLM_BASE_URL

        response = requests.post(
            f"{base_url}/chat/completions",

            headers={
                "Content-Type":
                    "application/json",
            },

            json={
                "model":
                    selected_model,

                "messages": [
                    {
                        "role":
                            "user",

                        "content":
                            "Reply with exactly: LOCAL_TEST_OK",
                    }
                ],

                "temperature":
                    0,

                "max_tokens":
                    64,

                # Keep the smoke test fast and reasoning-free on
                # thinking models like Qwen3.
                "think":
                    False,
            },

            timeout=(10, 120),
        )

        if response.status_code >= 400:
            raise RuntimeError(
                "Local LLM smoke test HTTP "
                f"{response.status_code}: "
                f"{response.text}"
            )

        data = response.json()

        choices = (
            data.get("choices")
            or []
        )

        if not choices:
            raise RuntimeError(
                f"Local LLM smoke test returned no choices: "
                f"{data!r}"
            )

        content = (
            (
                choices[0].get("message")
                or {}
            )
            .get("content", "")
            or ""
        ).strip()

        content = re.sub(
            r"<think>.*?</think>",
            "",
            content,
            flags=re.DOTALL,
        ).strip()

        if not content:
            raise RuntimeError(
                "Local LLM smoke test returned empty content. "
                f"response={data!r}"
            )

        return content

    raise RuntimeError(
        "Smoke test supports groq, openrouter, and local."
    )


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

    heading_alt = "|".join(
        re.escape(h)
        for h in sorted(
            headings,
            key=len,
            reverse=True,
        )
    )

    # A strict heading must be the only thing on its line (beyond
    # optional list/number markers and bold markers).
    heading_re = re.compile(
        r"(?im)^\s*(?:[-*•·+]|\d{1,2}[.)]\s*)?"
        r"(?:\*\*|__)?\s*"
        r"("
        + heading_alt
        + r")\s*:?\s*(?:\*\*|__)?\s*$"
    )

    # Merge-tolerant preprocessing: models frequently write the heading
    # and the start of its body on one line ("HEADLINE: The GMV fell").
    # Split those into a strict heading line so one parser handles both
    # output styles. Only lines that have body text after the colon are
    # rewritten; bare heading lines are left untouched.
    merge_re = re.compile(
        r"(?im)^(\s*(?:[-*•·+]|\d{1,2}[.)]\s*)?"
        r"(?:\*\*|__)?\s*"
        r"("
        + heading_alt
        + r")\s*:)"
        r"(?=[ \t]+\S)"
    )
    normalized = merge_re.sub(
        r"\1\n",
        normalized,
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

    idx_of = {
        h.lower(): i
        for i, h in enumerate(
            headings
        )
    }

    def hidx(m):
        return idx_of.get(
            m.group(1).lower(),
        -1,
        )

    # Split the heading matches into candidate runs. A new run starts
    # whenever the first heading appears again (models emit a revised
    # draft after commenting on the first draft).
    runs = []
    cur = []
    for i, m in enumerate(
        matches
    ):
        hi = hidx(m)
        if hi == 0 and cur:
            runs.append(cur)
            cur = []
        cur.append((i, hi))
    if cur:
        runs.append(cur)

    # Total headings covered, whether it starts at the first expected
    # heading, and total CLEAN body substance. Reasoning-polluted runs
    # have huge raw bodies but little delivered narrative, so only
    # sentences that read like business narrative count toward the
    # score. Favour the last run with the best score.
    best = None
    best_score = (-1, -1, -1)
    for run in runs:
        his = [hi for _, hi in run]
        seen = len(set(his))
        first_ok = (
            1 if his and his[0] == 0 else 0
        )

        clean_chars = 0
        for pos, (i, hi) in enumerate(run):
            m = matches[i]
            nxt = (
                matches[run[pos + 1][0]].start()
                if pos + 1 < len(run)
                else len(normalized)
            )
            body = normalized[m.end():nxt]
            for part in re.split(
                r"(?<=[.!?])\s+|\n+",
                body,
            ):
                text = part.strip()
                if (
                    text
                    and not _looks_like_reasoning(text)
                ):
                    clean_chars += len(text)

        score = (seen, first_ok, clean_chars)
        if score >= best_score:
            best = run
            best_score = score
    run = best

    # Recover a heading the model merged with its body on one line
    # (e.g. "WHERE: SP state and RJ warehouse.").
    lenient_re = re.compile(
        r"(?im)^\s*(?:[-*•·+]|\d{1,2}[.)]\s*)?"
        r"(?:\*\*|__)?\s*"
        r"("
        + heading_alt
        + r")\s*:[\t ]+\S"
    )

    # Walk the chosen run and split the text into ordered sections.
    sections = []
    expected = 0
    seg_start = matches[run[0][0]].start()
    for k, (i, hi) in enumerate(run):
        m = matches[i]

        # Fill a gap: an expected heading was merged onto one line
        # (e.g. "WHERE: body text"). Take it as its own section.
        while expected < hi:
            hname = headings[expected]
            prev = matches[run[k - 1][0]] if k > 0 else None
            lo = prev.end() if prev else seg_start
            window = normalized[lo: min(m.start(), len(normalized))]
            rec = lenient_re.search(window)
            if rec and rec.group(1).lower() == hname.lower():
                body = window[rec.end():].strip()
                sections.append(f"{hname}:\n{body}")
                expected += 1
            else:
                raise RuntimeError(
                    f"{persona} narrative is incomplete. "
                    f"Expected {headings}; missing {hname}."
                )

        # Normal case: heading on its own line.
        next_start = (
            matches[run[k + 1][0]].start()
            if k + 1 < len(run)
            else len(normalized)
        )
        body = normalized[
            m.end():
            next_start
        ].strip()
        if body:
            sections.append(
                f"{headings[hi]}:\n{body}"
            )
        expected = hi + 1

    # Trailing expected headings merged onto the final line.
    while expected < len(headings):
        hname = headings[expected]
        lo = matches[run[-1][0]].end() if run else 0
        window = normalized[lo:]
        rec = lenient_re.search(window)
        if rec and rec.group(1).lower() == hname.lower():
            body = window[rec.end():].strip()
            sections.append(f"{hname}:\n{body}")
            expected += 1
        else:
            raise RuntimeError(
                f"{persona} narrative is incomplete. "
                f"Expected {headings}; missing {hname}."
            )

    cleaned = "\n\n".join(
        sections
    ).strip()

    # Some local models continue past the last required section with a
    # word-count audit, a "Revised draft", or draft commentary. Anything
    # after the first such trailing marker is not part of the narrative.
    trailer_re = re.compile(
        r"(?im)^\s*(?:"
        r"now[,:]?\s*let(?:'s|s)?|"
        r"let(?:'s|s)?\s*(?:check|count|rewrite|draft|me\s+rewrite)|"
        r"we'?ll\s+count|"
        r"word\s*count|"
        r"revised\s*draft|"
        r"draft\s*[:]|"
        r"i\s+hope|"
        r"here\s+is\s+the\s+(?:final|revised|corrected)|"
        r"the\s+word\s+count|"
        r"total\s*(?:words|[:])|"
        r"let'?s\s+draft|"
        r"i'?ll\s+revise|"
        r"revised\s+version"
        r")"
    )
    mm = trailer_re.search(cleaned)
    if mm:
        cleaned = cleaned[: mm.start()].strip()

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


def _collect_evidence_numbers(
    obj,
    acc,
    key="",
):
    """
    Walk the investigation structure and collect every numeric value
    that narratives are allowed to cite.

    Record-count fields (review_evidence_records and friends) are
    deliberately excluded: the narrative validator treats record counts
    as forbidden claims even when they are present in the evidence.
    Percent-style variants (x*100 and x/100) are added so a rate stored
    as a fraction matches its "0.79%" rendering and vice versa.
    """

    if isinstance(obj, bool) or obj is None:
        return

    if isinstance(obj, (int, float)):

        if re.search(
            r"(records|counts?|groups)$",
            key or "",
            flags=re.IGNORECASE,
        ):
            return

        value = float(obj)

        acc.add(value)
        acc.add(value * 100)
        acc.add(value / 100)

        return

    if isinstance(obj, str):

        # Only short label/date strings are scanned. Long strings can
        # be embedded JSON dumps or notes whose numbers (IDs, record
        # counts, derived figures) are NOT narrative-safe, so they are
        # skipped to keep the whitelist as strict as the validator's.
        if len(obj) > 60 or obj.lstrip()[:1] in ("{", "["):
            return

        for match in re.finditer(
            r"-?\d+(?:\.\d+)?",
            obj.replace(",", ""),
        ):

            try:

                acc.add(
                    float(match.group()),
                )

            except ValueError:
                pass

        return

    if isinstance(obj, dict):

        for child_key, child in obj.items():
            _collect_evidence_numbers(
                child,
                acc,
                str(child_key),
            )

        return

    if isinstance(obj, (list, tuple)):

        for child in obj:
            _collect_evidence_numbers(
                child,
                acc,
                key,
            )


def _token_is_grounded(
    token,
    evidence_numbers,
):
    """
    Return True when a numeric token in the narrative is backed by the
    evidence whitelist (sign-insensitive, comma-tolerant, with a small
    rounding tolerance so "4.17" matches an evidence value of 4.16687).
    """

    cleaned = token.replace(",", "").rstrip("%").rstrip(".")

    try:

        value = abs(float(cleaned))

    except ValueError:
        return True

    # Small bare integers are ordinals/counts ("top 3", "6 days") that
    # are not worth scrubbing.
    if (
        value < 11
        and "." not in cleaned
        and not token.rstrip(".").endswith("%")
    ):
        return True

    for ev in evidence_numbers:

        ev = abs(ev)

        if abs(value - ev) <= 0.005 + 0.001 * ev:
            return True

        if round(value, 2) == round(ev, 2):
            return True

    return False


# Sentence-level markers of visible chain-of-thought. Qwen3 emits its
# deliberation as ordinary text, and sections can end up interleaved
# with it. The delivered narrative must not contain model deliberation,
# so sentences carrying these markers are dropped deterministically.
_REASONING_MARKERS = (
    "we have to",
    "we must",
    "we can write",
    "we can list",
    "we'll",
    "we are to",
    "we should",
    "we need",
    "we don't know",
    "we do not know",
    "we cannot",
    "let's",
    "lets ",
    "let me",
    "let us",
    "i'll",
    "i will",
    "i think",
    "i see",
    "i need",
    "i must",
    "wait,",
    "wait ",
    "hmm",
    "okay",
    "the problem says",
    "the instructions say",
    "the instruction says",
    "the rule says",
    "the rules say",
    "per rules",
    "per the rules",
    "instruction",
    "but note",
    "but wait",
    "but the rule",
    "but per",
    "but we ",
    "why not",
    "why?",
    "so i ",
    "so we ",
    "actually",
    "alternatively",
    "example:",
    "given time",
    "not sure",
    "looks like",
    "sounds like",
    "two or more sentences",
    "three full sentences",
    "two full sentences",
    "at least two",
    "at least three",
    "sentences stating",
    "sentences that state",
    "cite the before/after",
    "cite the before and after",
    "explain whether volume",
    "explain business meaning",
    "state evidence status",
    "state the evidence strength",
    "only use the action",
    "name the most important",
    "summarize the supplied",
    "respect exact evidence",
    "important note from the data",
)


def _looks_like_reasoning(text):
    """
    Return True when a sentence reads like model chain-of-thought
    rather than delivered business narrative.
    """

    trimmed = text.strip().lstrip("-*•• ").strip()
    low = trimmed.lower()

    if "?" in trimmed:
        return True

    if " -> " in trimmed or "=>" in trimmed or " = " in trimmed:
        return True

    return any(
        marker in low
        for marker in _REASONING_MARKERS
    )


# Count phrasings that the claims extractor turns into unverifiable
# "N m"-style tokens ("148 mentions" -> claim "148 m"), plus hosted
# currency vocabulary that violates the BRL-only contract.
_COUNT_PHRASE_RE = re.compile(
    r"\b\d[\d,]*\s+(?:mentions?|reviewed|records?|rows?|entries)\b",
    flags=re.IGNORECASE,
)

_FOREIGN_CURRENCY_RE = re.compile(
    r"\b(?:USD|US\$|dollars?)\b|\$(?!\d)",
    flags=re.IGNORECASE,
)


def scrub_unsupported_numbers(
    story,
    investigation,
):
    """
    Deterministic grounding guard: remove every narrative sentence that
    cites a number the evidence does not contain.

    The LLM narrates; this layer enforces the project contract that only
    evidence-backed figures survive into the delivered story. Sentences
    are dropped (never rewritten) so no new claims are introduced, and a
    neutral evidence-status sentence keeps any section from emptying.
    """

    evidence_numbers = set()
    _collect_evidence_numbers(
        investigation,
        evidence_numbers,
    )

    token_re = re.compile(
        r"\d[\d,]*(?:\.\d+)?%?",
    )

    rebuilt = []

    for section in story.split(
        "\n\n",
    ):

        if ":\n" not in section:

            rebuilt.append(section)
            continue

        head, _, body = section.partition(
            ":\n",
        )

        parts = re.split(
            r"(?<=[.!?])\s+|\n+",
            body,
        )

        kept = []

        for part in parts:

            text = part.strip()

            if not text:
                continue

            if _looks_like_reasoning(text):
                continue

            if _COUNT_PHRASE_RE.search(
                text,
            ):
                continue

            if _FOREIGN_CURRENCY_RE.search(
                text,
            ):
                continue

            grounded = True

            for token in token_re.findall(
                text,
            ):

                if not _token_is_grounded(
                    token,
                    evidence_numbers,
                ):

                    grounded = False
                    break

            if grounded:
                kept.append(text)

        if not kept:

            kept = [
                "Evidence status limits the conclusions "
                "available for this area.",
            ]

        rebuilt.append(
            f"{head}:\n" + " ".join(kept)
        )

    cleaned = "\n\n".join(
        rebuilt,
    ).strip()

    # A bare "$" (not part of the BRL "R$" pair) violates the currency
    # contract; normalize it instead of losing the sentence.
    cleaned = re.sub(
        r"(?<![A-Za-z])\$(?=\d)",
        "R$",
        cleaned,
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

    if provider == "local":

        # Qwen3 (and other thinking models) burn output tokens on
        # visible chain-of-thought before writing the narrative, which
        # truncates the answer. "/no_think" is Qwen3's documented soft
        # switch to disable the thinking phase for this request.
        prompt = f"{prompt}\n\n/no_think"

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

    # Deterministic grounding guard: drop any sentence that cites a
    # number the investigation does not contain, and normalize a bare
    # "$" to the contracted BRL "R$". This runs before validation so
    # the delivered narrative only carries evidence-backed figures.
    result["story"] = scrub_unsupported_numbers(
        result["story"],
        investigation,
    )

    result["telemetry"]["router_elapsed_ms"] = round(
        (time.perf_counter() - started) * 1000,
        2,
    )

    return result


def _generate_persona_with_fallbacks(
    investigation,
    persona,
    candidates,
    validation_feedback=None,
):
    """
    Generate one persona using the configured provider order.

    Provider order for the current setup:
        1. Local / qwen3:8b (Ollama)

    A candidate is accepted only when:
        LLM response -> cleanup -> success

    Each candidate may be retried (CLEAN_RETRIES) after a cleanup
    failure with structural feedback, because a small local model
    can occasionally loop on one heading or omit required sections
    on a stochastic roll. Retrying the SAME candidate with feedback
    is cheaper and usually successful before exhausting candidates.

    The FastAPI validation layer remains authoritative for final
    grounding validation. Failed generation/cleanup candidates are
    then skipped in favor of the next configured candidate.

    IMPORTANT:
    Providers are NOT raced concurrently. This prevents the fallback
    provider from being called unnecessarily while the primary succeeds.
    """

    CLEAN_RETRIES = int(
        os.getenv(
            "LLM_CLEAN_RETRIES",
            "2",
        )
    )

    global _LOCAL_FORCE_CPU

    if not candidates:
        raise RuntimeError(
            f"No configured LLM candidates for {persona}."
        )

    failures = []

    for attempt, (provider, model) in enumerate(
        candidates,
        start=1,
    ):
        for retry in range(1, CLEAN_RETRIES + 1):

            if LLM_DEBUG:
                print(
                    f"[LLM ROUTER] TRY persona={persona} "
                    f"attempt={attempt} retry={retry} "
                    f"provider={provider} "
                    f"model={model}"
                )

            try:
                result = _generate_one_persona_candidate(
                    investigation,
                    persona,
                    provider,
                    model,
                    validation_feedback,
                )

                if LLM_DEBUG:
                    print(
                        f"[LLM ROUTER] GENERATED persona={persona} "
                        f"provider={provider} "
                        f"model={model}"
                    )

                return {
                    "result": result,
                    "model_route": {
                        "provider": provider,
                        "model": model,
                        "attempt": attempt,
                        "retries": retry - 1,
                        "fallback_attempts": attempt - 1,
                        "failed_candidates_before_winner": failures,
                    },
                }

            except Exception as exc:
                error_text = str(exc)

                failure = {
                    "provider": provider,
                    "model": model,
                    "error": error_text,
                }

                failures.append(failure)

                if LLM_DEBUG:
                    print(
                        f"[LLM ROUTER] FAILED persona={persona} "
                        f"provider={provider} model={model}: "
                        f"{error_text}"
                    )

                # VRAM out-of-memory: switch the local provider to
                # full CPU inference and retry this same candidate
                # immediately, instead of burning clean retries on
                # a request that would fail identically on GPU.
                if (
                    provider == "local"
                    and not _LOCAL_FORCE_CPU
                    and _is_vram_oom_error(error_text)
                ):

                    _LOCAL_FORCE_CPU = True

                    if LLM_DEBUG:
                        print(
                            "[LLM ROUTER] VRAM OOM detected for "
                            f"{model}; forcing CPU-only local "
                            "inference and retrying"
                        )

                    continue

                # Give the model structural feedback about missing
                # or extra headings so the next retry can fix it.
                if retry < CLEAN_RETRIES:
                    validation_feedback = (
                        _build_cleanup_feedback(
                            persona,
                            exc,
                        )
                    )
                    continue

                # Exhausted retries for this candidate: break to the
                # next candidate.
                break

    raise RuntimeError(
        f"All configured LLM candidates failed for {persona}. "
        + json.dumps(
            failures,
            ensure_ascii=False,
        )
    )


def _build_cleanup_feedback(
    persona,
    exc,
):
    """
    Convert a narrative-cleanup exception into structured feedback
    that the prompt can use to fix the section layout.

    The cleaner raises messages such as:
      "executive narrative is incomplete. Expected ['HEADLINE', ...];
       found ['HEADLINE', 'WHAT CHANGED']"
    """
    text = str(exc)

    if "incomplete" not in text:
        return {
            "persona": persona,
            "issue": "cleanup_failure",
            "detail": text,
        }

    expected_match = re.search(
        r"Expected (\[.*?\]);",
        text,
    )

    found_match = re.search(
        r"found (\[.*?\]).*?$",
        text,
    )

    feedback = {
        "persona": persona,
        "issue": "missing_or_repeated_headings",
        "validation": {
            "passed": False,
        },
    }

    if expected_match:
        try:
            feedback["expected_headings"] = ast.literal_eval(
                expected_match.group(1)
            )
        except (SyntaxError, ValueError):
            feedback["expected_headings_raw"] = (
                expected_match.group(1)
            )

    if found_match:
        try:
            feedback["found_headings"] = ast.literal_eval(
                found_match.group(1)
            )
        except (SyntaxError, ValueError):
            feedback["found_headings_raw"] = (
                found_match.group(1)
            )

    return feedback


def generate_event_narratives(
    investigation,
    validation_feedback=None,
):
    """
    Generate Executive and Operations narratives independently.

    Current production route:
        Local Qwen3 8B (Ollama)

    Executive and Operations run in parallel with each other.
    Within each persona, provider fallback is strictly sequential.
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

    with ThreadPoolExecutor(
        max_workers=2,
        thread_name_prefix="llm-persona",
    ) as executor:

        executive_future = executor.submit(
            _generate_persona_with_fallbacks,
            investigation,
            "executive",
            candidates,
            validation_feedback,
        )

        operations_future = executor.submit(
            _generate_persona_with_fallbacks,
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
            executive_future.cancel()
            operations_future.cancel()
            raise

    return {
        "event_id":
            event_id,

        "executive":
            executive_package["result"],

        "operations":
            operations_package["result"],

        "generated":
            True,

        "source":
            "selected_event_investigation",

        "model_route": {
            "executive":
                executive_package["model_route"],

            "operations":
                operations_package["model_route"],
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