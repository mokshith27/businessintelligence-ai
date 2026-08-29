# Changelog

All notable changes to BusinessIntelligence.ai are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]
### Added (initial release scope)

#### KPI intelligence
- KPI semantic contracts with metric definition, grain, date field, currency, and
  governance metadata (`config/kpi_contracts/`).
- Daily KPI construction from ecommerce/order data.
- Seasonal baselines and robust anomaly scoring.
- Materiality scoring combining statistical unusualness and business impact.
- Event clustering for multi-day movements.

#### Driver investigation
- GMV decomposition into order-volume and AOV effects.
- Segment contribution analysis across customer state, category, and seller.
- Evidence-ranked driver investigation for clustered events.

#### Unstructured evidence
- Review aspect tagging.
- Aspect-level multilingual sentiment via Hugging Face.
- Review evidence comparison between event and comparison periods.

#### Evidence, confidence, and actions
- Multi-source evidence fusion into an explicit evidence graph.
- Confidence scores with `SUPPORTED`, `WEAK`, `ABSTAIN`, and `CONTRADICTED` states.
- Safe action rules that prevent unsupported high-impact interventions.

#### Causal analysis
- Observational causal analysis of `late_delivery -> review_score`.
- Propensity adjustment with doubly-robust AIPW estimation and bootstrap intervals.
- Diagnostics, assumptions, and a production status that can downgrade evidence.

#### LLM narrative generation
- Executive and operations narratives grounded in deterministic evidence.
- Narrative validator that checks numbers, statuses, uncertainty, currency, causal
  wording, and driver claims.
- LLM telemetry: latency, tokens, model calls, estimated cost.

#### Scenario testing and validation
- Controlled scenarios: promotion-driven movements, inventory constraints,
  contradictory/ambiguous cases, and sparse-history/new-KPI cases.
- Scenario scorecards for driver identification and action safety.

#### Delivery surface
- Role-based application views (Executive / Operations / Analyst).
- FastAPI service with Swagger docs and a Streamlit decision dashboard.
- Human-in-the-loop feedback with calibration reporting.

## How to add entries

- New entries go under **[Unreleased]**.
- Use plain, user-facing language; link to issues/PRs where relevant.
- This file is maintained jointly by the team (see `AUTHORS.md`).