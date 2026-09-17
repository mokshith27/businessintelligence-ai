"""Tests for currency validation and markdown-escape normalization.

Covers the escaped-dollar bug: small local models emit "R\\$" which
was previously read as a bare dollar sign and rejected.
"""

from llm.narrative_validator import validate_currency

BRL_INSIGHT = {
    "kpi": {
        "currency": "BRL",
        "currency_symbol": "R$",
    }
}


def test_brl_dollars_ok():
    result = validate_currency("Change of R$2,127.87 observed.", BRL_INSIGHT)
    assert result["passed"] is True
    assert result["violations"] == []


def test_bare_dollar_rejected():
    result = validate_currency("Change of $2,127.87 observed.", BRL_INSIGHT)
    assert result["passed"] is False
    assert any("'$' instead of BRL" in v for v in result["violations"])


def test_escaped_dollar_normalized():
    # Model markdown-escape: R\$3,673.91 must be treated as R$.
    result = validate_currency(
        "Change from R\\$3,673.91 to R\\$1,546.04.",
        BRL_INSIGHT,
    )
    assert result["passed"] is True
    assert result["violations"] == []


def test_usd_terminology_rejected():
    result = validate_currency("This is worth 50 US dollars.", BRL_INSIGHT)
    assert result["passed"] is False
    assert any("USD/dollar" in v for v in result["violations"])


def test_usd_abbreviation_rejected():
    result = validate_currency("Cost in USD was 20.", BRL_INSIGHT)
    assert result["passed"] is False


def test_no_currency_mentions_ok():
    result = validate_currency("No monetary claims here.", BRL_INSIGHT)
    assert result["passed"] is True