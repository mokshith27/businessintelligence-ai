# Architecture Walkthrough

This document maps each module in the repository to its responsibility and its key
files. The high-level flow diagram is in the [README](../README.md).

**Core principle:** the analytical layer determines the truth; the LLM explains that
truth.

---

## 1. High-level flow

```text
Raw Data Sources (Olist + simulated context)
        |
        v
Ingestion Layer (DuckDB)
        |
        v
KPI / Analytical Layer (daily KPIs + enriched facts)
        |
   +----+----+----+
   |    |    |    |
Materiality Drivers Reviews
+events  +decomp  +sentiment
   |    |    |    |
   +----+----+----+
        |
        v
Evidence Fusion (confidence + abstention)
        |
   +----+----+----+
   |    |    |    |
Actions  Causal  Scenarios
   |    |    |    |
   +----+----+----+
        |
        v
Insight Builder -> LLM Story Generator -> Narrative Validator
        |
        v
FastAPI -> Streamlit Decision UI
```

---

## 2. Module map

| Module | Responsibility | Key files |
|---|---|---|
| `ingestion/` | Load raw CSVs, validate relationships, build analytical tables, build the daily KPI mart | `load_and_build_kpis.py`, `validate_relationships.py`, `build_analytical_tables.py`, `build_daily_kpis.py`, `load_business_context.py` |
| `config/` | Governed KPI semantic contracts and LLM configuration | `kpi_contracts/*.yaml`, `llm_config.yaml` |
| `materiality/` | Detect materially important KPI movements and cluster them into events | `materiality_engine.py`, `event_clustering.py` |
| `anomaly/` | Seasonal baselines and changepoint detection used by materiality | `seasonal_baseline.py`, `changepoints.py` |
| `drivers/` | GMV decomposition, segment contribution, and event investigation | `decomposition.py`, `check_decomposition.py`, `segment_tables.py`, `segment_contribution.py`, `event_investigation.py`, `shap_attribution.py` |
| `nlp/` | Unstructured evidence: review aspect tagging and multilingual sentiment | `aspect_tagging.py`, `sentiment.py` |
| `evidence/` | Multi-source evidence fusion, confidence/abstention, insight canonicalization | `evidence_graph.py`, `review_evidence.py`, `confidence.py`, `build_insight.py`, `causal_evidence.py`, `causal_status.py` |
| `actions/` | Safe action generation tied to controllable levers and owners | `action_engine.py` |
| `personas/` | Role-specific narrative shaping plus deterministic persona tests | `executive.py`, `operations.py`, `test_personas.py` |
| `llm/` | Evidence-grounded story generation and strict narrative validation | `story_generator.py`, `narrative_validator.py` |
| `causal/` | Observational causal analysis (late_delivery -> review_score) with diagnostics | `delivery_review_effect.py`, `diagnostics.py` |
| `scenarios/` | Controlled scenario suite, sparse-history safety, and evaluation scorecards | `scenario_engine.py`, `scenario_runner.py`, `scenario_definitions.py`, `sparse_history.py`, `evaluate_engine.py`, `validate_scenarios.py`, `evaluation_report.py` |
| `security/` | Application-level role filtering (Executive / Operations / Analyst) | `role_filter.py` |
| `feedback/` | Human-in-the-loop feedback capture and calibration measurement | `capture_and_calibrate.py` |
| `telemetry/` | Runtime tracking for LLM calls, latency, tokens, and cost | `track.py` |
| `api/` | FastAPI surface exposing insights, actions, validation, and feedback | `main.py` |
| `dashboard/` | Streamlit decision UI with role selection and validation center | `app.py` |

---

## 3. Data flow details

### Ingestion
Raw CSV data (Olist order data plus a simulated `business_context.csv`) is loaded into
DuckDB. Relationship validation runs before analytical tables and daily KPIs are built,
so downstream modules consume consistent, governed artifacts.

### Materiality
The engine compares observed KPI values against a seasonal/historical baseline:

```text
Materiality = Statistical unusualness x Business impact
```

Sparse-history KPIs are not treated as reliably anomalous.

### Drivers
GMV change is decomposed into order-volume and AOV effects, then attributed across
segments (customer state, category, seller). Contribution is explicitly **not**
treated as root-cause proof.

### Evidence and confidence
Structured contributions, review evidence, sentiment, business context, and causal
evidence are fused into an explicit evidence graph. Confidence and abstention states
(`SUPPORTED`, `WEAK`, `ABSTAIN`, `CONTRADICTED`) guard every recommendation.

### LLM narrative
The LLM only receives the governed evidence produced by the deterministic layer. A
validator then checks numbers, statuses, uncertainty language, currency, causal
wording, and driver claims in the generated narrative.

### Delivery
The canonical insight is served through FastAPI and rendered by Streamlit with
role-based filtering applied at the application layer.

---

## 4. Design invariants

1. **Deterministic-first** — KPI math never depends on an LLM.
2. **Contribution is not causality** — segments can contribute without being a cause.
3. **Abstention is a feature** — low-confidence evidence leads to `ABSTAIN`, not guesses.
4. **Everything is inspectable** — outputs land as JSON artifacts under `data/`.
5. **Role-aware** — Executive, Operations, and Analyst views differ by entitlement.