"""Docker first-run seed: build the deterministic warehouse + insights.

Runs every step of ``run_pipeline.STEPS`` EXCEPT the LLM narrative
steps (which need a provider at runtime). The dashboard and API are
fully functional deterministically; AI narratives are generated
on-demand from the dashboard once Ollama/cloud is reachable.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(
    0,
    str(PROJECT_ROOT),
)

import run_pipeline  # noqa: E402

WAREHOUSE_PATH = (
    PROJECT_ROOT
    / "data"
    / "warehouse"
    / "businessintelligence.duckdb"
)

# Steps that require a live LLM provider are skipped at seed time.
EXCLUDED_NAMES = {
    "LLM",
}

PRINTABLE_EXCLUDED = ("Generate LLM narratives", "Validate LLM narratives")


def main() -> int:

    if WAREHOUSE_PATH.exists():

        print(
            "[seed] Warehouse already present: "
            f"{WAREHOUSE_PATH}"
        )

        return 0

    steps = run_pipeline.STEPS

    failures = []

    for index, (name, relative_path) in enumerate(
        steps,
        start=1,
    ):

        if name in PRINTABLE_EXCLUDED:

            print(
                f"\n[{index}/{len(steps)}] SKIPPED (runtime LLM): {name}"
            )

            continue

        print(
            f"\n[{index}/{len(steps)}] === {name} ==="
        )

        path = (
            PROJECT_ROOT
            / relative_path
        )

        proc = subprocess.run(
            [
                sys.executable,
                str(path),
            ],
            cwd=str(PROJECT_ROOT),
        )

        if proc.returncode != 0:

            failures.append(
                f"{name} ({relative_path}) "
                f"exit={proc.returncode}"
            )

    if failures:

        print("\n[seed] FAILURES:")

        for failure in failures:
            print(f"  - {failure}")

        return 1

    print("\n[seed] Warehouse seed complete.")

    return 0


if __name__ == "__main__":

    sys.exit(
        main()
    )