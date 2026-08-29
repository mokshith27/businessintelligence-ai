# BusinessIntelligence.ai

> **From KPI movement to evidence-backed action**

BusinessIntelligence.ai is an end-to-end decision-intelligence system that detects meaningful business KPI movements, investigates where the change occurred, combines structured and unstructured evidence, estimates confidence, abstains when evidence is insufficient, recommends safe business actions, and generates evidence-grounded narratives for different user roles.

The project is designed around one core principle:

**The analytical layer determines the truth; the LLM explains that truth.**

---

## 1. What the Project Does

A traditional dashboard can tell a business user:

> "Marketplace GMV increased."

BusinessIntelligence.ai goes further:

```text
KPI movement
    ↓
Materiality detection
    ↓
Event clustering
    ↓
Driver contribution
    ↓
Review / sentiment evidence
    ↓
Business context
    ↓
Evidence fusion
    ↓
Confidence + abstention
    ↓
Recommended action
    ↓
Role-specific narrative
```

The system is deliberately conservative. A large percentage movement is not automatically treated as a meaningful business event. Similarly, an observed contributor is not automatically treated as a root cause.

---

## 2. Key Capabilities

### KPI intelligence
- KPI semantic contract with metric definition, grain, date field, currency, and governance metadata.
- Daily KPI construction from ecommerce/order data.
- Seasonal baselines and robust anomaly scoring.
- Materiality scoring that considers both statistical unusualness and business impact.
- Event clustering for multi-day movements.

### Driver investigation
- GMV decomposition into order-volume and AOV effects.
- Segment contribution analysis across customer state, category, and seller dimensions.
- Evidence ranking based on observed contribution.

### Unstructured evidence
- Review aspect tagging.
- Aspect-level sentiment using a multilingual Hugging Face sentiment model.
- Review evidence comparison between event and comparison periods.

### Evidence and governance
- Multi-source evidence fusion.
- Explicit confidence scores.
- `ABSTAIN`, `WEAK`, and `CONTRADICTED` states.
- Safe action rules that prevent high-impact interventions when evidence is insufficient.
- Analytical lineage and LLM governance metadata.

### Causal analysis
- Observational causal analysis of:
  `late_delivery → review_score`
- Propensity adjustment.
- Doubly robust AIPW estimation.
- Bootstrap uncertainty interval.
- Propensity overlap and basic balance diagnostics.
- Explicit causal assumptions and limitations.
- Production status that can downgrade causal evidence when diagnostics are poor.

### LLM narrative generation
- Executive narrative.
- Operations narrative.
- Evidence-grounded prompts.
- Quantitative values taken from the deterministic analytical layer.
- Narrative validator checks numbers, statuses, uncertainty, currency, causal wording, and driver claims.
- LLM telemetry including latency, token usage, model calls, and estimated cost.

### Scenario testing
- Controlled promotion scenario.
- Inventory-constraint scenario.
- Contradictory/ambiguous cases.
- Sparse-history/new-KPI scenario.
- Scenario scorecard for driver identification and action safety.

### Role-based access
Three application-level views:

| Role | Purpose |
|---|---|
| Executive | High-level KPI movement, contribution, confidence, and decisions |
| Operations | Operational drivers, actions, owners, and monitoring |
| Analyst | Full evidence, lineage, causal evidence, governance, and feedback |

The prototype uses application-level filtering rather than enterprise SSO/JWT/RBAC infrastructure.

### Human-in-the-loop feedback
Analysts can classify an assessment as:
- `CORRECT`
- `INCORRECT`
- `MISSING_CONTEXT`

Feedback is stored and used to measure calibration. The system intentionally does not overwrite production confidence from a tiny feedback sample.

---

## 3. Architecture

```text
                         ┌─────────────────────┐
                         │   Raw Data Sources  │
                         │ Olist + context     │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │   Ingestion Layer   │
                         │      DuckDB         │
                         └──────────┬──────────┘
                                    │
                                    ▼
                 ┌──────────────────────────────────┐
                 │     KPI / Analytical Layer        │
                 │ daily KPIs + enriched facts       │
                 └────────────────┬─────────────────┘
                                  │
                  ┌───────────────┼────────────────┐
                  ▼               ▼                ▼
             Materiality      Drivers          Reviews
             + events         + decomposition  + sentiment
                  │               │                │
                  └───────────────┼────────────────┘
                                  ▼
                         ┌─────────────────────┐
                         │  Evidence Fusion    │
                         │ confidence +        │
                         │ abstention          │
                         └──────────┬──────────┘
                                    │
                      ┌─────────────┼─────────────┐
                      ▼             ▼             ▼
                   Actions       Causal       Scenarios
                      │          analysis          │
                      └─────────────┼──────────────┘
                                    ▼
                         ┌─────────────────────┐
                         │   Insight Builder   │
                         └──────────┬──────────┘
                                    │
                         ┌──────────▼──────────┐
                         │  LLM Story Generator│
                         └──────────┬──────────┘
                                    │
                         ┌──────────▼──────────┐
                         │ Narrative Validator │
                         └──────────┬──────────┘
                                    │
                         ┌──────────▼──────────┐
                         │      FastAPI        │
                         └──────────┬──────────┘
                                    │
                         ┌──────────▼──────────┐
                         │     Streamlit       │
                         │   Decision UI       │
                         └─────────────────────┘
```

---

## 4. Repository Structure

```text
businessintelligence-ai/
│
├── data/
│   ├── raw/
│   │   ├── olist/
│   │   └── funnel/
│   ├── simulated/
│   │   └── business_context.csv
│   ├── insights/
│   ├── scenarios/
│   ├── causal/
│   └── feedback/
│
├── config/
│   └── kpi_contracts/
│
├── ingestion/
│   ├── load_and_build_kpis.py
│   ├── build_analytical_tables.py
│   ├── build_daily_kpis.py
│   ├── inspect_database.py
│   └── validate_relationships.py
│
├── materiality/
│   ├── materiality_engine.py
│   ├── event_clustering.py
│   └── inspect_gmv_tail.py
│
├── anomaly/
│   ├── seasonal_baseline.py    # documented extension point
│   └── changepoints.py         # optional extension
│
├── drivers/
│   ├── decomposition.py        # production
│   ├── segment_contribution.py  # production
│   ├── segment_tables.py
│   ├── check_decomposition.py
│   └── shap_attribution.py      # optional extension
│
├── nlp/
│   ├── aspect_tagging.py
│   └── sentiment.py
│
├── evidence/
│   ├── evidence_graph.py
│   ├── confidence.py
│   ├── review_evidence.py
│   ├── build_insight.py
│   ├── causal_evidence.py
│   └── causal_status.py
│
├── causal/
│   ├── delivery_review_effect.py
│   └── diagnostics.py
│
├── actions/
│   └── action_engine.py
│
├── personas/
│   ├── executive.py
│   ├── operations.py
│   └── test_personas.py
│
├── llm/
│   ├── story_generator.py
│   └── narrative_validator.py
│
├── scenarios/
│   ├── scenario_runner.py
│   ├── scenario_evaluation.py
│   ├── scenario_engine.py
│   ├── engine_evaluation.py
│   ├── evaluation_scorecard.py
│   └── sparse_history_scenario.py
│
├── security/
│   └── role_filter.py
│
├── feedback/
│   └── capture_and_calibrate.py
│
├── telemetry/
│   └── track.py     # extension point; LLM telemetry is in story_generator.py
│
├── api/
│   └── main.py
│
├── dashboard/
│   └── app.py
│
├── requirements.txt
├── .gitignore
└── README.md
```

> The exact generated-data contents under `data/` depend on whether the pipeline has already been executed in a particular checkout.

---

## 5. Technology Stack

| Layer | Technology |
|---|---|
| Language | Python |
| Analytical database | DuckDB |
| Data processing | Pandas, NumPy |
| Machine learning | scikit-learn |
| NLP | Hugging Face Transformers |
| Deep-learning runtime for sentiment model | PyTorch |
| API | FastAPI |
| Dashboard | Streamlit |
| Visualization | Plotly |
| LLM | Groq API |
| LLM model used in the final run | `openai/gpt-oss-120b` |
| Storage/artifacts | Local files + DuckDB |
| Version control | Git / GitHub |

---

## 6. Data Sources

The project uses heterogeneous data sources centered on ecommerce operations.

### Structured commerce data
Olist-style datasets provide:
- orders
- order items
- customers
- sellers
- products
- order reviews

### Business context
A simulated context dataset provides controlled scenarios such as:
- promotions
- inventory constraints
- marketing campaigns
- competitor pricing
- external events

This context dataset is specifically used to validate whether the engine can align business context with observed KPI movement.

### Unstructured data
Customer reviews are used as the unstructured evidence source.

---

## 7. KPI Semantic Contract

The primary KPI is:

```json
{
  "id": "marketplace_gmv",
  "name": "Marketplace GMV",
  "grain": "order_item",
  "primary_date": "order_purchase_timestamp",
  "currency": "BRL",
  "currency_symbol": "R$"
}
```

The semantic contract separates metric definition from narrative generation and provides a governed source for KPI interpretation.

---

## 8. Core Analytical Flow

### Step 1 — Ingestion

Raw CSV data is loaded and analytical tables are built in DuckDB.

Example:

```powershell
python ingestion/load_and_build_kpis.py
```

### Step 2 — Materiality

The engine compares the observed KPI against an appropriate historical baseline.

Conceptually:

```text
Materiality
    =
Statistical unusualness
    ×
Business impact
```

The engine also considers sparse history so a newly launched KPI is not incorrectly labeled as a reliable anomaly.

### Step 3 — Event clustering

Adjacent anomalous observations are combined into business events.

Example:

```text
2017-11-23 → 2017-11-29
7 anomalous days
```

### Step 4 — Driver analysis

GMV is decomposed into:

```text
GMV change
  ├── Order-volume effect
  └── AOV effect
```

The engine then analyzes contribution by dimensions such as customer state and category.

### Step 5 — Evidence fusion

Evidence can include:

```text
Observed contribution
Review evidence
Sentiment
Business context
Causal evidence
Data quality
```

The system keeps evidence types explicit rather than allowing a single model to fabricate a root cause.

### Step 6 — Confidence and abstention

Examples of states:

```text
SUPPORTED
WEAK
ABSTAIN
CONTRADICTED
WEAK_DRIVER
```

The decision layer is designed so insufficient evidence can lead to:

```text
ABSTAIN
```

instead of an unsupported operational intervention.

### Step 7 — Action generation

The action layer follows:

```text
Driver
  ↓
Controllable lever
  ↓
Action
  ↓
Owner
  ↓
Monitoring plan
```

### Step 8 — Narrative synthesis

Only after the deterministic analysis is complete does the LLM receive the governed evidence.

The LLM is used for:
- narrative synthesis
- persona adaptation
- natural-language explanation
- uncertainty wording

The LLM is not used as the source of truth for KPI calculations.

### Step 9 — Validation

Generated narratives are checked for:
- unsupported numbers
- incorrect statuses
- missing uncertainty language
- wrong currency notation
- unsupported causal claims
- unsupported driver claims

---

## 9. Example Final Insight

For the demonstrated November 2017 GMV event:

```text
Previous GMV   : R$204,230.43
Current GMV    : R$439,250.34
GMV change     : R$235,019.91

Previous orders: 1,367
Current orders : 3,424

Previous AOV   : R$149.40
Current AOV    : R$128.29

Volume effect  : R$285,600.25
AOV effect     : -R$50,580.34
```

The largest observed contributor was:

```text
SP customer state
GMV contribution: R$79,092.21
Contribution: 33.65%
Evidence status: WEAK
Decision: INVESTIGATE
```

The system deliberately does **not** claim that SP is a verified root cause.

---

## 10. Causal Inference

The project contains a separate observational causal module:

```text
Late delivery
      ↓
Review score
```

The final demonstrated estimate was:

```text
ATE                  : -1.5703
95% bootstrap CI     : [-1.5853, -1.5536]
Propensity overlap   : acceptable
Production status    : CAUSAL_EVIDENCE_ACCEPTED
Confidence           : 0.80
```

Interpretation:

> Under the observational adjustment assumptions, late delivery is estimated to reduce review score by approximately 1.57 points.

### Important limitation

This is **observational causal inference**, not a randomized experiment.

The result depends on assumptions including:
- no important unmeasured confounding after adjustment;
- adequate treatment/control overlap;
- correct treatment definition;
- consistent review measurement.

The system therefore exposes causal assumptions, diagnostics, and limitations instead of presenting an observational estimate as unquestionable proof.

---

## 11. Sparse-History Safety

A controlled scenario simulates a newly launched KPI:

```text
KPI                  : New Premium Category GMV
History points       : 5
Required history     : 30
Latest value         : R$8,100.00
Baseline median      : R$2,500.00
Relative change      : +224.00%
Decision             : ABSTAIN
Confidence           : 0.050
```

The important behavior is:

```text
Large movement
    +
Insufficient history
    =
ABSTAIN
```

This prevents the engine from confusing early-stage volatility with a trustworthy material event.

---

## 12. Controlled Scenario Evaluation

The controlled scenario suite contains:

### SCN_001 — Promotion-driven movement
The scenario includes promotion context, but the observed mechanism conflicts with the expected positive direction.

Result:

```text
Top driver : promotion
Status     : ABSTAIN
Action     : ABSTAIN
Safety     : PASS
```

### SCN_002 — Inventory constraint
The context indicates constrained inventory and the observed GMV direction is negative, but the order mechanism is not fully consistent.

Result:

```text
Top driver : inventory_constraint
Status     : ABSTAIN
Action     : ABSTAIN
Safety     : PASS
```

### SCN_003 — Promotion-driven movement 2
Promotion context aligns with positive GMV and positive order growth.

Result:

```text
Top driver : promotion
Status     : SUPPORTED
Action     : ACTION_WITH_VALIDATION
Safety     : PASS
```

The final scorecard reached:

```text
Driver identification : 100%
Context alignment      : 100%
Status handling        : 100%
Safe abstention        : 100%
Action safety          : 100%
Action acceptability   : 100%
Average score          : 1.000
```

---

## 13. Role-Based Security

The prototype implements application-level information filtering.

### Executive

Receives:
- KPI
- movement
- event
- top drivers
- confidence
- actions
- executive narrative

Restricted:
- customer identifiers
- seller identifiers
- direct contact fields
- detailed analyst-only lineage/causal information

### Operations

Receives:
- KPI
- event
- drivers
- confidence
- operational actions
- operations narrative

Customer contact fields remain restricted.

### Analyst

Receives:
- full driver evidence
- confidence
- actions
- data quality
- lineage
- causal evidence
- LLM governance
- executive and operations narratives

PII such as email, phone, and address remains restricted.

> This is a prototype entitlement layer, not a production identity/authentication system.

---

## 14. Human-in-the-Loop Feedback

Analysts can evaluate an insight directly from the dashboard.

Available feedback:

```text
CORRECT
INCORRECT
MISSING_CONTEXT
```

Feedback is stored in:

```text
feedback_records
```

and a calibration report is generated.

The system intentionally avoids automatic confidence overrides from very small samples.

Example:

```text
Feedback records   : 3
Correct            : 2
Incorrect          : 0
Missing context    : 1
Status             : COLLECTING_FEEDBACK
```

The intended production behavior is:

```text
Small sample
    ↓
measure calibration only

Sufficient feedback
    ↓
calibration becomes actionable
```

---

## 15. API

Start FastAPI from the project root:

```powershell
uvicorn api.main:app --reload
```

Swagger UI:

```text
http://127.0.0.1:8000/docs
```

Important endpoints include:

```text
GET  /api/insights/latest
GET  /api/insights/latest/executive
GET  /api/insights/latest/operations

GET  /api/insights/role?role=executive
GET  /api/insights/role?role=operations
GET  /api/insights/role?role=analyst

GET  /api/actions
GET  /api/events

POST /api/feedback
GET  /api/feedback
GET  /api/calibration

GET  /api/security/test

GET  /api/validation/scenarios
GET  /api/validation/sparse-history
GET  /api/validation/causal
GET  /api/validation/feedback
```

---

## 16. Dashboard

Start Streamlit:

```powershell
streamlit run dashboard/app.py
```

The dashboard provides:
- role selection;
- KPI snapshot;
- event information;
- decomposition;
- driver investigation;
- actions;
- evidence and governance;
- analytical lineage;
- LLM governance;
- runtime telemetry;
- event history;
- Analyst feedback;
- feedback calibration;
- validation center.

Default local URL:

```text
http://localhost:8501
```

---

## 17. LLM Setup

The story generator requires a Groq API key.

PowerShell:

```powershell
$env:GROQ_API_KEY="your_key_here"
```

Then run the story generator:

```powershell
python llm/story_generator.py
```

The final implementation uses an OpenAI-compatible Groq model endpoint and records telemetry such as:

```json
{
  "model": "openai/gpt-oss-120b",
  "prompt_tokens": 1279,
  "completion_tokens": 443,
  "total_tokens": 1722,
  "model_calls": 1,
  "estimated_cost_usd": 0.00045765
}
```

### Security note

Never commit the actual API key to GitHub.

Use environment variables or a local `.env` file that is listed in `.gitignore`.

---

## 18. NLP Setup

The sentiment engine uses the Hugging Face model:

```text
cardiffnlp/twitter-xlm-roberta-base-sentiment
```

For environments where SentencePiece/protobuf support is required:

```powershell
python -m pip install sentencepiece protobuf
```

Restart the environment after installing missing tokenizer dependencies.

The review pipeline processes the full review corpus and creates aspect-level evidence before sentiment analysis is used downstream.

---

## 19. Recommended Installation

Create and activate a virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\activate
```

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

If `requirements.txt` is not yet present or needs updating, install the major runtime dependencies:

```powershell
python -m pip install ^
  duckdb ^
  pandas ^
  numpy ^
  scikit-learn ^
  streamlit ^
  plotly ^
  fastapi ^
  uvicorn ^
  requests ^
  pydantic ^
  groq ^
  transformers ^
  torch ^
  sentencepiece ^
  protobuf
```

---

## 20. Running the Analytical Pipeline

Run the project from the repository root.

The pipeline should be executed in dependency order so downstream modules can consume the generated analytical artifacts.

A typical sequence is:

```text
1. Ingestion
2. Analytical tables / daily KPIs
3. Materiality
4. Event clustering
5. Driver investigation
6. Business context
7. Review aspects
8. Sentiment
9. Evidence fusion
10. Confidence
11. Actions
12. Canonical insight
13. LLM stories
14. Narrative validation
15. Scenario evaluation
16. Sparse-history validation
17. Causal analysis / diagnostics
18. Role/security checks
19. Feedback/calibration
20. API
21. Dashboard
```

For development, run individual modules when debugging instead of unnecessarily rebuilding the complete pipeline.

---

## 21. Important Generated Artifacts

The most useful generated outputs include:

```text
data/insights/latest_insight.json
data/insights/executive_story.json
data/insights/operations_story.json
data/insights/executive_validation.json
data/insights/operations_validation.json

data/causal/delivery_review_causal_effect.json
data/causal/causal_diagnostics.json
data/causal/causal_evidence_record.json
data/causal/causal_production_status.json

data/scenarios/scenario_evaluation.json
data/scenarios/scenario_engine_results.json
data/scenarios/engine_evaluation.json
data/scenarios/sparse_history_scenario.json

data/feedback/feedback_records.json
data/feedback/calibration_report.json
```

These artifacts make the analytical process inspectable and reproducible.

---

## 22. Validation Philosophy

BusinessIntelligence.ai uses a **deterministic-first** architecture.

### Deterministic / statistical layer
Responsible for:
- KPI values
- baselines
- z-scores
- materiality
- decompositions
- contribution
- evidence status
- confidence
- causal estimates
- action eligibility
- governance

### LLM layer
Responsible for:
- explanation
- summarization
- persona adaptation
- natural-language formatting

This prevents the LLM from silently becoming the source of quantitative truth.

---

## 23. Known Limitations

This project is a decision-intelligence prototype, not a production enterprise analytics platform.

Important limitations:

1. The causal module uses observational data and cannot eliminate unmeasured confounding.
2. Role-based filtering is application-level authorization, not enterprise authentication.
3. Feedback calibration requires sufficient real analyst feedback before it can meaningfully change confidence policy.
4. Business context is simulated for controlled evaluation scenarios.
5. The causal result is specific to the analyzed treatment/outcome relationship and should not be generalized to unrelated KPI movements.
6. Some downstream analytical artifacts are generated locally and are not expected to exist in a fresh clone until the pipeline is run.

---

## 24. Troubleshooting

### `GROQ_API_KEY is not set`

PowerShell:

```powershell
$env:GROQ_API_KEY="your_key_here"
```

Then rerun the story generator.

### Hugging Face SentencePiece/protobuf error

Install:

```powershell
python -m pip install sentencepiece protobuf
```

Restart the environment and rerun the sentiment module.

### FastAPI returns 500 with NaN JSON values

Analytical endpoints should convert non-finite numeric values to JSON-safe values before returning them.

### Streamlit crashes with `'list' object has no attribute 'get'`

Check the actual JSON structure returned by the validation endpoint. The dashboard normalizes list/dictionary scenario formats.

### Windows console Unicode error

Prefer ASCII-safe logging for console output, or configure stdout/stderr for UTF-8.

### Sparse-history scenario says `ABSTAIN`

This is expected behavior when there are insufficient historical observations for a reliable baseline.

---

## 25. Design Principles

BusinessIntelligence.ai follows these principles:

### 1. Evidence before explanation
The narrative comes after the analytical evidence.

### 2. Contribution is not causality
A segment can contribute to an observed KPI movement without being its root cause.

### 3. Abstention is a feature
The engine can explicitly say:

```text
Insufficient evidence.
```

### 4. Business impact matters
A statistically unusual movement is not automatically a business priority.

### 5. Unstructured data is evidence
Reviews supplement structured KPI analysis rather than replacing it.

### 6. Actions require evidence
High-impact interventions should not be recommended for contradicted or insufficiently supported hypotheses.

### 7. Human feedback is retained
Analyst feedback becomes measurable calibration evidence.

---

## 26. Quick Start

```powershell
# 1. Create environment
python -m venv .venv
.venv\Scripts\activate

# 2. Install dependencies
python -m pip install -r requirements.txt

# 3. Set Groq API key
$env:GROQ_API_KEY="your_key_here"

# 4. Build / refresh analytical artifacts
# Run the project's pipeline or required ingestion modules.

# 5. Start API
uvicorn api.main:app --reload

# 6. In a second terminal, start dashboard
streamlit run dashboard/app.py
```

Open:

```text
Dashboard:
http://localhost:8501

API / Swagger:
http://127.0.0.1:8000/docs
```

---

## 27. Project Outcome

BusinessIntelligence.ai turns:

```text
"What happened?"
```

into:

```text
What changed?
    ↓
Was it materially important?
    ↓
Where did it happen?
    ↓
What evidence supports the explanation?
    ↓
How confident are we?
    ↓
Should we abstain?
    ↓
What can the business do?
    ↓
Who should act?
    ↓
How should the result be explained?
```

The result is a decision workspace designed to be **evidence-grounded, uncertainty-aware, action-oriented, and auditable**.

---

## 28. License

Add the project's intended license here before publishing publicly.

For example:

```text
MIT License
```

only if that is the license you choose for the repository.
