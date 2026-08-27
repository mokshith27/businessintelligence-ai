from pathlib import Path
import json
import re
import sys


# ============================================================
# WINDOWS / UTF-8 OUTPUT
# ============================================================

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(
        encoding="utf-8",
        errors="replace",
    )

if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(
        encoding="utf-8",
        errors="replace",
    )


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

EXECUTIVE_PATH = (
    PROJECT_ROOT
    / "data"
    / "insights"
    / "executive_story.json"
)

OPERATIONS_PATH = (
    PROJECT_ROOT
    / "data"
    / "insights"
    / "operations_story.json"
)


# ============================================================
# LOAD JSON
# ============================================================

def load_json(path):

    if not path.exists():

        raise FileNotFoundError(
            f"File not found:\n{path}"
        )

    try:

        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except json.JSONDecodeError as exc:

        raise RuntimeError(
            f"Invalid JSON file:\n{path}"
        ) from exc


# ============================================================
# PARSE NUMERIC CLAIMS
# ============================================================

def extract_numeric_claims(text):
    """
    Extract numerical expressions from narrative text while
    ignoring:

    - numbered list markers: 1., 2., 3.
    - calendar years
    - day/month date expressions such as:
        23-29 Nov 2017
        23 Nov 2017
        Nov 23-29 2017
        2017-11-23
    """

    pattern = (
        r"(?<![A-Za-z])"
        r"[-+]?\d[\d,]*(?:\.\d+)?"
        r"\s*[KkMm]?"
        r"%?"
    )

    matches = list(
        re.finditer(
            pattern,
            text,
        )
    )

    claims = []

    # Common month names / abbreviations
    months = (
        "jan",
        "january",
        "feb",
        "february",
        "mar",
        "march",
        "apr",
        "april",
        "may",
        "jun",
        "june",
        "jul",
        "july",
        "aug",
        "august",
        "sep",
        "sept",
        "september",
        "oct",
        "october",
        "nov",
        "november",
        "dec",
        "december",
    )

    for match in matches:

        raw = match.group(0).strip()

        start = match.start()
        end = match.end()

        # ----------------------------------------------------
        # Ignore numbered list markers
        #
        # Example:
        # 1. State SP
        # 2. State MG
        # ----------------------------------------------------

        if (
            end < len(text)
            and text[end] == "."
        ):

            integer_candidate = (
                raw
                .replace(",", "")
                .replace("+", "")
                .replace("-", "")
            )

            if integer_candidate.isdigit():

                continue

        # ----------------------------------------------------
        # Ignore numbers that are part of a date expression
        # ----------------------------------------------------

        context_start = max(
            0,
            start - 15,
        )

        context_end = min(
            len(text),
            end + 20,
        )

        context = (
            text[
                context_start:context_end
            ]
            .lower()
        )

        # Examples:
        #
        # 23-29 nov 2017
        # 23 nov 2017
        # nov 23-29 2017
        # 2017-11-23
        #
        # Detect month names close to the number.

        contains_month = any(
            re.search(
                rf"\b{month}\b",
                context,
            )
            for month in months
        )

        # ISO date pattern near this number.
        contains_iso_date = bool(
            re.search(
                r"\b\d{4}-\d{1,2}-\d{1,2}\b",
                context,
            )
        )

        # Date range pattern such as 23-29.
        contains_day_range = bool(
            re.search(
                r"\b\d{1,2}\s*[-–]\s*\d{1,2}\b",
                context,
            )
        )

        if (
            contains_month
            or contains_iso_date
            or contains_day_range
        ):

            # But don't accidentally discard genuine
            # business numbers simply because a month appears
            # somewhere nearby. Only do this for likely
            # calendar-sized integers.

            plain_for_date_check = (
                raw
                .replace(",", "")
                .replace("+", "")
                .replace("-", "")
                .replace("%", "")
                .replace("K", "")
                .replace("k", "")
                .replace("M", "")
                .replace("m", "")
            )

            try:

                numeric_for_date_check = float(
                    plain_for_date_check
                )

            except ValueError:

                numeric_for_date_check = None

            if (
                numeric_for_date_check is not None
                and 1 <= numeric_for_date_check <= 31
                and not raw.endswith("%")
            ):

                continue

        # ----------------------------------------------------
        # Ignore standalone years
        # ----------------------------------------------------

        plain = (
            raw
            .replace(",", "")
            .replace("%", "")
            .replace("K", "")
            .replace("k", "")
            .replace("M", "")
            .replace("m", "")
            .replace("+", "")
            .replace("-", "")
        )

        try:

            numeric = float(
                plain
            )

        except ValueError:

            continue

        if (
            1900 <= numeric <= 2100
            and "%" not in raw
            and not raw.lower().endswith("k")
            and not raw.lower().endswith("m")
        ):

            continue

        claims.append(raw)

    # Remove duplicates while preserving order.
    return list(
        dict.fromkeys(
            claims
        )
    )   


def parse_numeric_claim(raw):

    cleaned = (
        raw
        .replace(",", "")
        .replace(" ", "")
    )

    is_percent = (
        cleaned.endswith("%")
    )

    if is_percent:
        cleaned = cleaned[:-1]

    multiplier = 1.0

    if cleaned.lower().endswith("k"):

        multiplier = 1_000.0

        cleaned = cleaned[:-1]

    elif cleaned.lower().endswith("m"):

        multiplier = 1_000_000.0

        cleaned = cleaned[:-1]

    try:

        value = (
            float(cleaned)
            * multiplier
        )

    except ValueError:

        return None

    return value, is_percent


# ============================================================
# BUILD ALLOWED SOURCE FACTS
# ============================================================

def build_allowed_facts(insight):

    movement = insight.get(
        "movement",
        {}
    )

    facts = set()

    # --------------------------------------------------------
    # Core movement facts
    # --------------------------------------------------------

    for key in [
        "previous_gmv",
        "current_gmv",
        "gmv_change",
        "previous_orders",
        "current_orders",
        "orders_change",
        "previous_aov",
        "current_aov",
        "aov_change",
        "volume_effect",
        "aov_effect",
        "residual_effect",
    ]:

        value = movement.get(
            key
        )

        if value is not None:

            facts.add(
                float(value)
            )

    # --------------------------------------------------------
    # Safe derived percentages
    # --------------------------------------------------------

    previous_gmv = movement.get(
        "previous_gmv"
    )

    current_gmv = movement.get(
        "current_gmv"
    )

    previous_orders = movement.get(
        "previous_orders"
    )

    current_orders = movement.get(
        "current_orders"
    )

    previous_aov = movement.get(
        "previous_aov"
    )

    current_aov = movement.get(
        "current_aov"
    )

    if (
        previous_gmv
        is not None
        and previous_gmv != 0
        and current_gmv
        is not None
    ):

        facts.add(
            (
                (
                    current_gmv
                    - previous_gmv
                )
                /
                previous_gmv
            )
            * 100
        )

    if (
        previous_orders
        is not None
        and previous_orders != 0
        and current_orders
        is not None
    ):

        facts.add(
            (
                (
                    current_orders
                    - previous_orders
                )
                /
                previous_orders
            )
            * 100
        )

    if (
        previous_aov
        is not None
        and previous_aov != 0
        and current_aov
        is not None
    ):

        facts.add(
            (
                (
                    current_aov
                    - previous_aov
                )
                /
                previous_aov
            )
            * 100
        )

    # --------------------------------------------------------
    # Driver facts
    # --------------------------------------------------------

    for driver in insight.get(
        "drivers",
        []
    ):

        contribution = driver.get(
            "observed_contribution",
            {}
        )

        gmv_change = contribution.get(
            "gmv_change"
        )

        share = contribution.get(
            "share"
        )

        confidence = (
            driver
            .get(
                "confidence",
                {}
            )
            .get(
                "overall"
            )
        )

        if gmv_change is not None:

            facts.add(
                float(
                    gmv_change
                )
            )

        if share is not None:

            # Example:
            # 0.3365 -> 33.65
            facts.add(
                float(share) * 100
            )

        if confidence is not None:

            # Confidence can appear in either form:
            # 0.418 or 41.8%
            #
            # Keep BOTH available.

            facts.add(
                float(confidence)
            )

            facts.add(
                float(confidence) * 100
            )

    return facts


# ============================================================
# NUMERIC MATCHING
# ============================================================

def approximately_matches(
    value,
    candidates,
    tolerance_ratio=0.02,
):
    """
    Match a displayed value against analytical facts.

    For change magnitudes, the narrative may communicate
    the sign through words such as "fell" or "declined"
    instead of writing a negative numeric sign.

    Therefore both signed and absolute comparisons are allowed.
    """

    for candidate in candidates:

        tolerance = max(
            abs(candidate)
            * tolerance_ratio,
            0.01,
        )

        # Exact/signed match
        if abs(
            value - candidate
        ) <= tolerance:

            return True

        # Magnitude match
        if abs(
            abs(value) - abs(candidate)
        ) <= tolerance:

            return True

    return False

def validate_numbers(
    story,
    insight,
):

    claims = extract_numeric_claims(
        story
    )

    allowed = build_allowed_facts(
        insight
    )

    unsupported = []

    for raw_claim in claims:

        parsed = parse_numeric_claim(
            raw_claim
        )

        if parsed is None:
            continue

        value, is_percent = parsed

        # ----------------------------------------------------
        # Percentage claims
        # ----------------------------------------------------

        if is_percent:

            candidates = [
                value
                for value in allowed
            ]

        else:

            candidates = [
                value
                for value in allowed
            ]

        if not approximately_matches(
            value,
            candidates,
        ):

            unsupported.append(
                raw_claim
            )

    return {

        "passed":
            len(unsupported) == 0,

        "checked_claims":
            claims,

        "unsupported_claims":
            unsupported,
    }


# ============================================================
# STATUS VALIDATION
# ============================================================

def validate_statuses(
    story,
    insight,
):

    story_upper = story.upper()
    story_lower = story.lower()

    allowed_statuses = {
        "WEAK",
        "ABSTAIN",
        "CONTRADICTED",
        "PLAUSIBLE",
        "SUPPORTED",
        "INVESTIGATE",
        "DO_NOT_ACT",
    }

    mentioned_statuses = sorted(
        status
        for status in allowed_statuses
        if status in story_upper
    )

    violations = []

    for driver in insight.get(
        "drivers",
        []
    ):

        driver_name = str(
            driver.get(
                "driver",
                ""
            )
        ).strip()

        status = driver.get(
            "status"
        )

        action = driver.get(
            "action",
            {}
        )

        decision = action.get(
            "decision"
        )

        if not driver_name:
            continue

        if status != "CONTRADICTED":
            continue

        if decision != "DO_NOT_ACT":
            continue

        driver_lower = driver_name.lower()

        if driver_lower not in story_lower:
            continue

        # ----------------------------------------------------
        # Explicitly allowed negative statements
        # ----------------------------------------------------

        allowed_negative_patterns = [

            rf"do\s+not\s+act\s+on\s+(?:the\s+)?{re.escape(driver_lower)}",

            rf"don't\s+act\s+on\s+(?:the\s+)?{re.escape(driver_lower)}",

            rf"no\s+action\s+(?:should\s+be\s+)?taken\s+on\s+(?:the\s+)?{re.escape(driver_lower)}",

            rf"no\s+action\s+recommended\s+(?:for|on)\s+(?:the\s+)?{re.escape(driver_lower)}",

            rf"avoid\s+acting\s+on\s+(?:the\s+)?{re.escape(driver_lower)}",

            rf"should\s+not\s+act\s+on\s+(?:the\s+)?{re.escape(driver_lower)}",

            rf"shouldn't\s+act\s+on\s+(?:the\s+)?{re.escape(driver_lower)}",
        ]

        is_explicitly_non_actionable = any(
            re.search(
                pattern,
                story_lower,
            )
            for pattern in allowed_negative_patterns
        )

        if is_explicitly_non_actionable:
            continue

        # ----------------------------------------------------
        # Explicit positive action statements
        # ----------------------------------------------------

        prohibited_patterns = [

            rf"\bact\s+on\s+(?:the\s+)?{re.escape(driver_lower)}\b",

            rf"\btake\s+action\s+on\s+(?:the\s+)?{re.escape(driver_lower)}\b",

            rf"\bprioritize\s+(?:the\s+)?{re.escape(driver_lower)}\b",

            rf"\bfocus\s+on\s+(?:the\s+)?{re.escape(driver_lower)}\b",

            rf"\btarget\s+(?:the\s+)?{re.escape(driver_lower)}\b",

            rf"\bincrease\s+investment\s+in\s+(?:the\s+)?{re.escape(driver_lower)}\b",

            rf"\ballocate\s+resources\s+to\s+(?:the\s+)?{re.escape(driver_lower)}\b",

            rf"\brecommend\s+acting\s+on\s+(?:the\s+)?{re.escape(driver_lower)}\b",
        ]

        for pattern in prohibited_patterns:

            if re.search(
                pattern,
                story_lower,
            ):

                violations.append(
                    f"Contradicted driver "
                    f"'{driver_name}' was presented "
                    "as actionable."
                )

                break

    return {

        "passed":
            len(violations) == 0,

        "mentioned_statuses":
            mentioned_statuses,

        "violations":
            violations,
    }

# ============================================================
# UNCERTAINTY VALIDATION
# ============================================================

def validate_uncertainty(
    story,
    insight,
):

    uncertain_exists = any(

        driver.get(
            "status"
        )
        in {
            "WEAK",
            "ABSTAIN",
            "CONTRADICTED",
        }

        for driver in insight.get(
            "drivers",
            []
        )
    )

    uncertainty_terms = [

        "uncertain",

        "insufficient",

        "not established",

        "not verified",

        "investigate",

        "evidence",

        "cannot",

        "does not establish",

        "not enough",

        "unavailable",

        "remains unclear",

        "remains uncertain",

        "hypothesis",

        "limited",
    ]

    story_lower = story.lower()

    found = [
        term
        for term in uncertainty_terms
        if term in story_lower
    ]

    if (
        uncertain_exists
        and not found
    ):

        return {

            "passed":
                False,

            "reason":
                "Story contains uncertain evidence "
                "but does not communicate uncertainty.",
        }

    return {

        "passed":
            True,

        "reason":
            None,

        "matched_terms":
            found,
    }


# ============================================================
# CURRENCY VALIDATION
# ============================================================

def validate_currency(
    story,
    insight,
):

    kpi = insight.get(
        "kpi",
        {}
    )

    currency = (
        kpi.get(
            "currency",
            "BRL"
        )
        or "BRL"
    )

    currency_symbol = (
        kpi.get(
            "currency_symbol",
            "R$"
        )
        or "R$"
    )

    violations = []

    story_upper = story.upper()

    if currency == "BRL":

        # Detect dollar signs that are NOT part of R$.
        invalid_dollar_matches = re.findall(
            r"(?<!R)\$",
            story,
        )

        if invalid_dollar_matches:

            violations.append(
                "Narrative introduced '$' instead of BRL 'R$'."
            )

        usd_terms = [
            "USD",
            "US DOLLAR",
            "US DOLLARS",
            "DOLLAR",
            "DOLLARS",
        ]

        for term in usd_terms:

            if term in story_upper:

                violations.append(
                    "Narrative introduced USD/dollar "
                    "terminology for a BRL KPI."
                )

                break

    return {

        "passed":
            len(violations) == 0,

        "currency":
            currency,

        "currency_symbol":
            currency_symbol,

        "violations":
            violations,
    }


# ============================================================
# CAUSAL LANGUAGE VALIDATION
# ============================================================

def validate_causal_language(
    story,
    insight,
):

    story_lower = story.lower()

    forbidden_phrases = [

        "definitively caused",

        "definitely caused",

        "certainly caused",

        "proved the cause",

        "proves the cause",

        "proven cause",

        "confirmed cause",

        "disproves",

        "disproved",

        "definitively proves",

        "definitely proves",

        "certainly proves",
    ]

    found = []

    for phrase in forbidden_phrases:

        if phrase in story_lower:

            found.append(
                phrase
            )

    return {

        "passed":
            len(found) == 0,

        "forbidden_phrases":
            found,
    }


# ============================================================
# DRIVER CLAIM VALIDATION
# ============================================================

def validate_driver_claims(
    story,
    insight,
):

    story_lower = story.lower()

    violations = []

    for driver in insight.get(
        "drivers",
        []
    ):

        driver_name = str(
            driver.get(
                "driver",
                ""
            )
        ).strip()

        if not driver_name:
            continue

        status = driver.get(
            "status"
        )

        if status not in {
            "WEAK",
            "ABSTAIN",
            "CONTRADICTED",
        }:

            continue

        driver_lower = (
            driver_name.lower()
        )

        causal_patterns = [

            f"{driver_lower} caused",

            f"{driver_lower} was the cause",

            f"cause was {driver_lower}",

            f"because of {driver_lower}",

        ]

        for pattern in causal_patterns:

            if pattern in story_lower:

                violations.append(
                    f"Unsupported causal claim involving "
                    f"driver '{driver_name}' with "
                    f"status {status}."
                )

                break

    return {

        "passed":
            len(violations) == 0,

        "violations":
            violations,
    }


# ============================================================
# STORY PRESENCE
# ============================================================

def validate_story_presence(
    story
):

    if not story:
        return {
            "passed": False,
            "reason": "Story is empty.",
        }

    if not story.strip():

        return {
            "passed": False,
            "reason": "Story is empty.",
        }

    return {
        "passed": True,
        "reason": None,
    }


# ============================================================
# MASTER VALIDATION
# ============================================================

def validate_story(
    story,
    insight,
    persona,
):

    presence = (
        validate_story_presence(
            story
        )
    )

    if not presence["passed"]:

        return {

            "persona":
                persona,

            "passed":
                False,

            "checks": {

                "story_presence":
                    presence,
            },
        }

    numeric = validate_numbers(
        story,
        insight,
    )

    statuses = validate_statuses(
        story,
        insight,
    )

    uncertainty = validate_uncertainty(
        story,
        insight,
    )

    currency = validate_currency(
        story,
        insight,
    )

    causal_language = (
        validate_causal_language(
            story,
            insight,
        )
    )

    driver_claims = (
        validate_driver_claims(
            story,
            insight,
        )
    )

    checks = {

        "numbers":
            numeric,

        "statuses":
            statuses,

        "uncertainty":
            uncertainty,

        "currency":
            currency,

        "causal_language":
            causal_language,

        "driver_claims":
            driver_claims,
    }

    passed = all(
        check.get(
            "passed",
            False
        )
        for check in checks.values()
    )

    return {

        "persona":
            persona,

        "passed":
            passed,

        "checks":
            checks,
    }


# ============================================================
# SAVE VALIDATION
# ============================================================

def save_validation(
    result,
    persona,
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

    path = (
        output_dir
        / f"{persona}_validation.json"
    )

    path.write_text(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return path


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n")
    print("=" * 100)
    print("BusinessIntelligence.ai")
    print("NARRATIVE VALIDATOR")
    print("=" * 100)

    insight = load_json(
        INSIGHT_PATH
    )

    personas = [

        (
            "executive",
            EXECUTIVE_PATH,
        ),

        (
            "operations",
            OPERATIONS_PATH,
        ),
    ]

    all_passed = True

    for persona, path in personas:

        payload = load_json(
            path
        )

        story = payload.get(
            "story",
            ""
        )

        result = validate_story(
            story,
            insight,
            persona,
        )

        validation_path = save_validation(
            result,
            persona,
        )

        print(
            f"\n{persona.upper()}"
        )

        print(
            f"PASS: "
            f"{result['passed']}"
        )

        print(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
            )
        )

        print(
            f"Saved: "
            f"{validation_path}"
        )

        if not result["passed"]:

            all_passed = False

    print("\n" + "=" * 100)

    if all_passed:

        print(
            "NARRATIVE VALIDATION PASSED"
        )

    else:

        print(
            "NARRATIVE VALIDATION FOUND ISSUES"
        )

    print("=" * 100)


if __name__ == "__main__":
    main()