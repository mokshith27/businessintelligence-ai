from pathlib import Path
import json

from executive import build_executive_view
from operations import build_operations_view


PROJECT_ROOT = Path(__file__).resolve().parent.parent


INSIGHT_PATH = (
    PROJECT_ROOT
    / "data"
    / "insights"
    / "latest_insight.json"
)


def main():

    if not INSIGHT_PATH.exists():

        raise FileNotFoundError(
            "latest_insight.json not found. "
            "Run build_insight.py first."
        )

    insight = json.loads(
        INSIGHT_PATH.read_text(
            encoding="utf-8"
        )
    )

    executive = build_executive_view(
        insight
    )

    operations = build_operations_view(
        insight
    )

    print("\n")
    print("=" * 90)
    print("EXECUTIVE PERSONA")
    print("=" * 90)

    print(
        json.dumps(
            executive,
            indent=2,
            ensure_ascii=False,
        )
    )

    print("\n")
    print("=" * 90)
    print("OPERATIONS PERSONA")
    print("=" * 90)

    print(
        json.dumps(
            operations,
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()