# Getting Started

This guide walks you through a first run of **BusinessIntelligence.ai**, from a fresh
clone to a working API + dashboard.

The full feature description lives in the project [README](../README.md). This document
focuses on the practical steps.

---

## 1. Prerequisites

| Requirement | Minimum note |
|---|---|
| Python | 3.10+ recommended |
| OS | Works on Windows (PowerShell shown below) and Linux/macOS |
| Internet | Needed to download packages and the Hugging Face sentiment model |
| Groq API key | Only required for LLM narrative generation (optional for the deterministic pipeline) |

---

## 2. Create a virtual environment

```powershell
python -m venv .venv
.venv\Scripts\activate
```

On Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

---

## 3. Install dependencies

```powershell
python -m pip install -r requirements.txt
```

### Optional extras

If the review sentiment model needs tokenizer support:

```powershell
python -m pip install sentencepiece protobuf
```

Restart the environment after installing missing tokenizer dependencies.

---

## 4. Set up the Groq API key (optional, for LLM narratives)

> **Security note:** never commit a real API key. Use an environment variable or a
> local `.env` file (already listed in `.gitignore`).

```powershell
$env:GROQ_API_KEY="your_key_here"
```

If no key is provided, the deterministic pipeline still runs; only the LLM
narrative step is skipped.

---

## 5. Run the analytical pipeline

The pipeline is executed in dependency order. From the **repository root**:

```powershell
python run_pipeline.py
```

This runs, in order:

| Stage | Module |
|---|---|
| 1. Ingestion | `ingestion/load_and_build_kpis.py`, `ingestion/validate_relationships.py`, `ingestion/build_analytical_tables.py`, `ingestion/build_daily_kpis.py`, `ingestion/load_business_context.py` |
| 2. Segment / driver analysis | `drivers/segment_tables.py`, `drivers/decomposition.py`, `drivers/check_decomposition.py`, `drivers/segment_contribution.py` |
| 3. Materiality / events | `materiality/materiality_engine.py`, `materiality/event_clustering.py` |
| 4. Event driver investigation | `drivers/event_investigation.py` |
| 5. Review NLP | `nlp/aspect_tagging.py`, `nlp/sentiment.py` |
| 6. Evidence | `evidence/evidence_graph.py`, `evidence/review_evidence.py`, `evidence/confidence.py` |
| 7. Actions | `actions/action_engine.py` |
| 8. Canonical insight | `evidence/build_insight.py` |
| 9. Personas | `personas/test_personas.py` |
| 10. LLM narratives + validation | `llm/story_generator.py`, `llm/narrative_validator.py` |

> For development, prefer running individual modules instead of the full pipeline.
> Each module can be executed by name, e.g. `python materiality/materiality_engine.py`.

---

## 6. Verify the generated artifacts

After a successful run, key outputs include:

```text
data/insights/latest_insight.json
data/insights/executive_story.json
data/insights/operations_story.json
data/causal/delivery_review_causal_effect.json
data/scenarios/scenario_evaluation.json
data/feedback/calibration_report.json
```

See the README section **"Important Generated Artifacts"** for the full list.

---

## 7. Start the API

```powershell
uvicorn api.main:app --reload
```

Swagger UI:

```text
http://127.0.0.1:8000/docs
```

---

## 8. Start the dashboard

In a second terminal:

```powershell
streamlit run dashboard/app.py
```

Open:

```text
http://localhost:8501
```

---

## 9. Run validation / scenario checks

The project ships controlled validation modules you can run on their own:

```powershell
python scenarios/scenario_runner.py          # controlled scenario suite
python scenarios/sparse_history.py           # sparse-history safety check
python causal/delivery_review_effect.py      # causal analysis
python feedback/capture_and_calibrate.py     # feedback + calibration
```

---

## 10. First-run checklist

- [ ] Virtual environment created and activated
- [ ] `pip install -r requirements.txt` completed
- [ ] `python run_pipeline.py` completed without errors
- [ ] `data/insights/latest_insight.json` exists
- [ ] API responds at `http://127.0.0.1:8000/docs`
- [ ] Dashboard renders at `http://localhost:8501`
- [ ] (Optional) `GROQ_API_KEY` set before LLM steps

---

## 11. Troubleshooting

| Symptom | Fix |
|---|---|
| `GROQ_API_KEY is not set` | Set the environment variable, then rerun the LLM step |
| SentencePiece/protobuf error from the sentiment model | `pip install sentencepiece protobuf`, restart the environment |
| API returns 500 on NaN JSON values | Analytical endpoints must convert non-finite numerics to JSON-safe values |
| Sparse-history scenario says `ABSTAIN` | Expected — insufficient history prevents a reliable baseline |
| Missing `data/` artifacts in a fresh clone | Expected until the pipeline has run in that checkout |

See the README **Troubleshooting** section for more detail.

---

## 12. Where to go next

- [Architecture walkthrough](ARCHITECTURE.md) — module-by-module responsibilities
- [Contributing guide](../CONTRIBUTING.md) — how to add to the project
- [Project README](../README.md) — full feature and design documentation