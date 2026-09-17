from pathlib import Path
import subprocess
import sys
import os
import time


# ============================================================
# PROJECT ROOT
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent


# ============================================================
# PIPELINE STEPS
# ============================================================
#
# IMPORTANT:
# These are the actual filenames currently present
# in your project.
#
# Optional / diagnostic / presentation modules are intentionally
# NOT part of the core analytical pipeline.
# ============================================================

STEPS = [

    # --------------------------------------------------------
    # 1. INGESTION
    # --------------------------------------------------------

    (
        "Load raw data and build initial KPIs",
        "ingestion/load_and_build_kpis.py",
    ),

    (
        "Validate relationships",
        "ingestion/validate_relationships.py",
    ),

    (
        "Build analytical tables",
        "ingestion/build_analytical_tables.py",
    ),

    (
        "Build daily KPI mart",
        "ingestion/build_daily_kpis.py",
    ),

    (
        "Load business context",
        "ingestion/load_business_context.py",
    ),


    # --------------------------------------------------------
    # 2. SEGMENT / DRIVER ANALYSIS
    # --------------------------------------------------------

    (
        "Build segment KPI tables",
        "drivers/segment_tables.py",
    ),

    (
        "GMV decomposition",
        "drivers/decomposition.py",
    ),

    (
        "Validate decomposition",
        "drivers/check_decomposition.py",
    ),

    (
        "Driver contribution analysis",
        "drivers/segment_contribution.py",
    ),


    # --------------------------------------------------------
    # 3. MATERIALITY / EVENTS
    # --------------------------------------------------------

    (
        "GMV materiality analysis",
        "materiality/materiality_engine.py",
    ),

    (
        "Event clustering",
        "materiality/event_clustering.py",
    ),


    # --------------------------------------------------------
    # 4. EVENT DRIVER INVESTIGATION
    # --------------------------------------------------------

    (
        "Event driver investigation",
        "drivers/event_investigation.py",
    ),


    # --------------------------------------------------------
    # 5. REVIEW NLP
    # --------------------------------------------------------

    (
        "Review aspect tagging",
        "nlp/aspect_tagging.py",
    ),

    (
        "Review sentiment analysis",
        "nlp/sentiment.py",
    ),


    # --------------------------------------------------------
    # 6. EVIDENCE
    # --------------------------------------------------------

    (
        "Build evidence foundation",
        "evidence/evidence_graph.py",
    ),

    (
        "Build review evidence",
        "evidence/review_evidence.py",
    ),

    (
        "Confidence and abstention",
        "evidence/confidence.py",
    ),


    # --------------------------------------------------------
    # 7. ACTIONS
    # --------------------------------------------------------

    (
        "Generate recommended actions",
        "actions/action_engine.py",
    ),


    # --------------------------------------------------------
    # 8. CANONICAL INSIGHT
    # --------------------------------------------------------

    (
        "Build canonical insight",
        "evidence/build_insight.py",
    ),


    # --------------------------------------------------------
    # 9. PERSONAS
    # --------------------------------------------------------
    #
    # The persona test is deterministic and useful as a
    # pipeline validation step.
    # --------------------------------------------------------

    (
        "Build and test personas",
        "personas/test_personas.py",
    ),


    # --------------------------------------------------------
    # 10. LLM
    # --------------------------------------------------------

    (
        "Generate LLM narratives",
        "llm/story_generator.py",
    ),

    (
        "Validate LLM narratives",
        "llm/narrative_validator.py",
    ),
]


# ============================================================
# UTILITIES
# ============================================================

def print_header(title):

    print("\n")
    print("=" * 100)
    print(f"BusinessIntelligence.ai")
    print(title)
    print("=" * 100)


def validate_pipeline_files():

    missing_files = []

    for name, relative_path in STEPS:

        path = PROJECT_ROOT / relative_path

        if not path.exists():

            missing_files.append(
                relative_path
            )

    if missing_files:

        print("\n[ERROR] Missing pipeline files:")

        for path in missing_files:

            print(
                f"  - {path}"
            )

        raise SystemExit(1)


def run_step(
    step_number,
    total_steps,
    name,
    relative_path,
):

    print("\n")
    print("-" * 100)

    print(
        f"[STEP {step_number}/{total_steps}] "
        f"{name}"
    )

    print(
        f"Script: {relative_path}"
    )

    print("-" * 100)

    script_path = (
        PROJECT_ROOT
        / relative_path
    )

    start_time = time.perf_counter()

    # --------------------------------------------------------
    # UTF-8 on Windows
    #
    # This helps prevent the cp1252 Unicode errors we've
    # encountered previously.
    # --------------------------------------------------------

    env = os.environ.copy()

    env["PYTHONUTF8"] = "1"

    env["PYTHONIOENCODING"] = (
        "utf-8"
    )

    try:

        result = subprocess.run(

            [
                sys.executable,
                "-u",
                str(script_path),
            ],

            cwd=str(
                PROJECT_ROOT
            ),

            env=env,

            check=False,
        )

    except KeyboardInterrupt:

        print(
            "\n\n[STOPPED] Pipeline interrupted by user."
        )

        raise SystemExit(130)

    elapsed = (
        time.perf_counter()
        - start_time
    )

    if result.returncode != 0:

        print("\n")
        print(
            "=" * 100
        )

        print(
            f"[FAILED] {name}"
        )

        print(
            f"Exit code: "
            f"{result.returncode}"
        )

        print(
            f"Execution time: "
            f"{elapsed:.2f} seconds"
        )

        print(
            "=" * 100
        )

        raise SystemExit(
            result.returncode
        )

    print("\n")
    print(
        f"[OK] {name}"
    )

    print(
        f"Execution time: "
        f"{elapsed:.2f} seconds"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print_header(
        "FULL INTELLIGENCE PIPELINE"
    )

    print(
        f"\nProject root:\n"
        f"{PROJECT_ROOT}"
    )

    print(
        f"\nPipeline steps: "
        f"{len(STEPS)}"
    )

    # --------------------------------------------------------
    # Validate all files BEFORE starting
    # --------------------------------------------------------

    print(
        "\n[CHECK] Validating pipeline files..."
    )

    validate_pipeline_files()

    print(
        "[OK] All pipeline files exist."
    )

    # --------------------------------------------------------
    # Run
    # --------------------------------------------------------

    total_steps = len(STEPS)

    pipeline_start = (
        time.perf_counter()
    )

    for index, (
        name,
        relative_path,
    ) in enumerate(
        STEPS,
        start=1,
    ):

        run_step(
            index,
            total_steps,
            name,
            relative_path,
        )

    total_time = (
        time.perf_counter()
        - pipeline_start
    )

    # --------------------------------------------------------
    # Complete
    # --------------------------------------------------------

    print_header(
        "FULL PIPELINE COMPLETE"
    )

    print(
        f"\nTotal execution time: "
        f"{total_time:.2f} seconds"
    )

    print(
        f"Steps completed: "
        f"{total_steps}/{total_steps}"
    )

    print(
        "\nLatest insight:"
    )

    insight_path = (
        PROJECT_ROOT
        / "data"
        / "insights"
        / "latest_insight.json"
    )

    if insight_path.exists():

        print(
            f"  {insight_path}"
        )

    else:

        print(
            "  [WARNING] latest_insight.json "
            "was not found."
        )

    print(
        "\nNarratives:"
    )

    for persona in [
        "executive",
        "operations",
    ]:

        path = (
            PROJECT_ROOT
            / "data"
            / "insights"
            / f"{persona}_story.json"
        )

        if path.exists():

            print(
                f"  [OK] {path}"
            )

        else:

            print(
                f"  [MISSING] {path}"
            )

    print(
        "\nNarrative validation:"
    )

    for persona in [
        "executive",
        "operations",
    ]:

        path = (
            PROJECT_ROOT
            / "data"
            / "insights"
            / f"{persona}_validation.json"
        )

        if path.exists():

            print(
                f"  [OK] {path}"
            )

        else:

            print(
                f"  [MISSING] {path}"
            )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()