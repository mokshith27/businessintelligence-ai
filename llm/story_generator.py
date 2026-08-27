from pathlib import Path
import json
import os
import time

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


# ============================================================
# CONFIG
# ============================================================

MODEL_NAME = "openai/gpt-oss-120b"

MODEL_PURPOSE = (
    "Evidence-grounded narrative synthesis only"
)

MAX_OUTPUT_TOKENS = 850

TEMPERATURE = 0.1

REASONING_EFFORT = "low"

INCLUDE_REASONING = False


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


# ============================================================
# BUILD COMPACT LLM CONTEXT
# ============================================================

def build_llm_context(
    insight,
    max_drivers=5,
):
    """
    Create a compact representation of the canonical insight.

    The LLM receives only the information needed for narrative
    generation rather than the entire analytical state.
    """

    movement = insight["movement"]

    event = insight["event"]

    drivers = sorted(
        insight.get("drivers", []),
        key=lambda item: abs(
            item[
                "observed_contribution"
            ]["share"]
        ),
        reverse=True,
    )

    compact_drivers = []

    for driver in drivers[:max_drivers]:

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
            driver.get(
                "action",
                {}
            )
        )

        compact_drivers.append(
            {
                "type":
                    driver[
                        "driver_type"
                    ],

                "driver":
                    driver[
                        "driver"
                    ],

                "gmv_change":
                    round(
                        contribution[
                            "gmv_change"
                        ],
                        2,
                    ),

                "contribution_pct":
                    round(
                        contribution[
                            "share"
                        ]
                        * 100,
                        2,
                    ),

                "confidence":
                    round(
                        confidence[
                            "overall"
                        ],
                        3,
                    ),

                "evidence_status":
                    driver[
                        "status"
                    ],

                "decision":
                    action.get(
                        "decision"
                    ),
            }
        )

    kpi = insight.get(
        "kpi",
        {}
    )

    return {
        "kpi": {
            "id":
                kpi.get(
                    "id"
                ),

            "name":
                kpi.get(
                    "name"
                ),

            "currency":
                kpi.get(
                    "currency",
                    "BRL",
                ),

            "currency_symbol":
                kpi.get(
                    "currency_symbol",
                    "R$",
                ),
        },

        "event": {
            "start":
                event[
                    "start_date"
                ],

            "end":
                event[
                    "end_date"
                ],

            "duration_days":
                event[
                    "duration_days"
                ],

            "direction":
                event[
                    "direction"
                ],

            "priority":
                event[
                    "investigation_priority"
                ],
        },

        "movement": {
            "previous_gmv":
                round(
                    movement[
                        "previous_gmv"
                    ],
                    2,
                ),

            "current_gmv":
                round(
                    movement[
                        "current_gmv"
                    ],
                    2,
                ),

            "gmv_change":
                round(
                    movement[
                        "gmv_change"
                    ],
                    2,
                ),

            "previous_orders":
                movement[
                    "previous_orders"
                ],

            "current_orders":
                movement[
                    "current_orders"
                ],

            "orders_change":
                movement[
                    "orders_change"
                ],

            "previous_aov":
                round(
                    movement[
                        "previous_aov"
                    ],
                    2,
                ),

            "current_aov":
                round(
                    movement[
                        "current_aov"
                    ],
                    2,
                ),

            "aov_change":
                round(
                    movement[
                        "aov_change"
                    ],
                    2,
                ),

            "volume_effect":
                round(
                    movement[
                        "volume_effect"
                    ],
                    2,
                ),

            "aov_effect":
                round(
                    movement[
                        "aov_effect"
                    ],
                    2,
                ),

            "residual_effect":
                round(
                    movement.get(
                        "residual_effect",
                        0.0,
                    ),
                    2,
                ),
        },

        "drivers":
            compact_drivers,

        "data_quality":
            insight.get(
                "data_quality",
                {},
            ),
    }


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
# GROQ CALL
# ============================================================

def generate_story(
    client,
    prompt,
    system_prompt,
):

    start_time = time.perf_counter()

    response = client.chat.completions.create(
        model=MODEL_NAME,

        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],

        temperature=TEMPERATURE,

        reasoning_effort=REASONING_EFFORT,

        include_reasoning=INCLUDE_REASONING,

        max_completion_tokens=MAX_OUTPUT_TOKENS,
    )

    latency_ms = (
        time.perf_counter()
        - start_time
    ) * 1000

    message = (
        response
        .choices[0]
        .message
    )

    content = (
        message.content
        or ""
    ).strip()

    if not content:

        raise RuntimeError(
            "Groq returned an empty narrative.\n"
            "No visible content was returned by the model."
        )

    # --------------------------------------------------------
    # Reasoning telemetry
    # --------------------------------------------------------

    reasoning_tokens = 0

    usage = getattr(
        response,
        "usage",
        None,
    )

    if usage is not None:

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

    else:

        prompt_tokens = 0

        completion_tokens = 0

        total_tokens = 0

    # Some SDK/model combinations expose reasoning
    # separately. If available, capture it.

    if hasattr(
        message,
        "reasoning_tokens",
    ):

        reasoning_tokens = int(
            getattr(
                message,
                "reasoning_tokens",
                0,
            )
            or 0
        )

    estimated_cost = estimate_cost(
        prompt_tokens,
        completion_tokens,
    )

    return {
        "story":
            content,

        "telemetry": {
            "model":
                MODEL_NAME,

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

    api_key = os.getenv(
        "GROQ_API_KEY"
    )

    if not api_key:

        raise RuntimeError(
            "GROQ_API_KEY is not configured.\n\n"
            "Add it to your .env file:\n"
            "GROQ_API_KEY=your_key_here"
        )

    # --------------------------------------------------------
    # Load insight
    # --------------------------------------------------------

    insight = load_insight()

    # --------------------------------------------------------
    # Create Groq client
    # --------------------------------------------------------

    client = Groq(
        api_key=api_key
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