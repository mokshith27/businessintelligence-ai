"""Tests for the narrative validator's numeric-claim extraction.

Covers the hex-like identifier bug: seller/order IDs such as
955fee9216a65b617aa5c0531780ce60 contain digit runs that must NOT
be extracted as numeric claims.
"""

from llm.narrative_validator import extract_numeric_claims


def test_hex_identifier_digits_are_ignored():
    text = (
        "Seller 955fee9216a65b617aa5c0531780ce60 drove "
        "R$2,127.87 (-35.48%) with 28% fewer orders."
    )
    claims = extract_numeric_claims(text)
    # Hash fragments (955, 216, 5, 17, 531780...) must not appear.
    for fragment in ("955", "216", "17", "531780"):
        assert fragment not in claims
    # Real numbers must still be extracted.
    assert "2,127.87" in claims
    assert "-35.48%" in claims
    assert "28%" in claims


def test_two_hex_identifiers_ignored():
    text = (
        "Sellers 955fee9216a65b617aa5c0531780ce60 and "
        "c70c1b0d8ca86052f45a432a38b73958 contributed R$1,546.04."
    )
    claims = extract_numeric_claims(text)
    assert "1,546.04" in claims
    for fragment in ("955", "216", "17", "531780", "6052", "3958", "0"):
        assert fragment not in claims


def test_pure_numbers_are_never_masked():
    text = "Orders went from 39 to 11 with a reduction of 28%."
    claims = extract_numeric_claims(text)
    assert "39" in claims
    assert "11" in claims
    assert "28%" in claims


def test_numbered_list_markers_ignored():
    text = "1. Check SP state. 2. Check MG state."
    claims = extract_numeric_claims(text)
    assert "1" not in claims
    assert "2" not in claims


def test_calendar_years_ignored():
    text = "During 2017 the market moved."
    claims = extract_numeric_claims(text)
    assert "2017" not in claims


def test_percentages_and_decimals_preserved():
    text = "AOV effect was +R$1,158.66 (54.45%); volume was -96.73%."
    claims = extract_numeric_claims(text)
    assert "1,158.66" in claims
    assert "54.45%" in claims
    assert "-96.73%" in claims