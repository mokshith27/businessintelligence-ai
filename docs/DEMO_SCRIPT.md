# BusinessIntelligence.ai — 3-Minute Demo Script

> **Positioning:** Decision intelligence for marketplace operations teams.
> **Buyer:** Head of Marketplace Operations (executive view), Marketplace Ops
> Team Lead (operations view), Business/Data Analyst (analyst view).
>
> **The one-line pitch:** *"Dashboards tell you what happened.
> This system tells you what to do about it — and refuses to guess when the
> evidence is thin."*

---

## Cast and screen setup (before you start)

| What | Where |
|---|---|
| API server running | `uvicorn api.main:app --port 8000` |
| Dashboard running | `streamlit run dashboard/app.py` → `http://localhost:8501` |
| Role pre-selected | **Executive** (Head of Marketplace Operations) |
| Event pre-selected | **Event 66** (negative movement, 2018-08-22 → 2018-08-27) |
| Fallback event | **Event 37** (positive movement, 2017-11-23 → 2017-11-29) |

---

## The arc (3:00 total)

```text
0:00–0:25   The hook        — a drop happens, nobody notices
0:25–0:55   Detection       — the system flags it on day 1
0:55–1:30   Investigation   — where did it happen, who is responsible
1:30–2:00   Evidence + trust — reviews fused, abstention shown
2:00–2:35   Action + plain language — safe action, validated narrative
2:35–3:00   Business impact — back-tested ROI close
```

---

## 0:00–0:25 — The hook

**On screen:** dashboard, Executive view, KPI snapshot.

**Say:**

> "It's 2am at a marketplace with thousands of sellers. GMV quietly drops
> 60% overnight. In most companies nobody sees this until the weekly
> report — five days later. Every one of those days is revenue walking
> out the door. This is BusinessIntelligence.ai: a decision-intelligence
> system for marketplace operations teams that catches this on day one,
> investigates it, and tells the team exactly what to do."

**Do:** keep the KPI snapshot on screen. Do not click yet.

---

## 0:25–0:55 — Detection

**On screen:** the event banner for the selected event ("HIGH-PRIORITY KPI
EVENT — investigation recommended").

**Say:**

> "The materiality engine compares every day against a seasonal baseline
> and only raises an event when a movement is both statistically unusual
> AND business-material. Event 66 — a six-day negative movement worth
> over a hundred thousand reais — was flagged on its **first** day. That's
> a **six-day head start** over the manual process."

**Do:** point at the event banner and the event dates. Mention that events
with sparse history are **not** flagged — the engine abstains instead, so
new-KPI noise never becomes a false alarm.

---

## 0:55–1:30 — Investigation

**On screen:** the "What explains the movement?" decomposition and the
driver table.

**Say:**

> "Detection is the easy part. The system then decomposes the movement
> into volume and AOV effects and ranks the contributing segments —
> customer states, categories, sellers — each with a confidence score
> built from multiple evidence sources."

**Do:** scroll through the driver table. Point at one strong driver and
one weak driver.

---

## 1:30–2:00 — Evidence + trust (the differentiator)

**On screen:** "Customer Review Evidence" section, then a driver marked
`ABSTAIN` / `DO_NOT_ACT`.

**Say:**

> "Here is what makes this different. The engine fuses structured
> evidence with unstructured review data — aspect-level, multilingual
> sentiment — to confirm or contradict each hypothesis. And when evidence
> is thin, it **abstains**. Look at these drivers marked ABSTAIN and
> DO_NOT_ACT: the system explicitly refuses to recommend action it cannot
> support. In an AI world full of confident nonsense, this is the
> anti-hallucination stance — for decisions."

**Do:** hover one ABSTAIN row; do not rush this — it is the judge-winning
moment.

---

## 2:00–2:35 — Action + plain language

**On screen:** the recommended action with owner and monitoring plan;
click **Generate AI Story**; the validated narrative appears.

**Say:**

> "For supported hypotheses the system recommends a safe action with an
> owner and a monitoring plan. And to close the last mile, the LLM layer
> writes the executive narrative — but watch carefully: the LLM only ever
> narrates numbers the analytical layer produced, and every claim is
> validated against the evidence before the story is shown. If validation
> fails, the narrative is rejected. The AI explains the truth; it never
> invents it."

**Do:** click Generate AI Story (~30–60 s with the local model; keep
talking over it — mention the model runs **fully locally via Ollama, no
data leaves the machine**). The green "passed all evidence-grounding
checks" banner lands on cue.

---

## 2:35–3:00 — Business impact close

**On screen:** the "Business Impact — Back-Tested ROI" panel at the top of
the Executive view.

**Say:**

> "And the so-what: back-tested on this data, the system flagged fifteen
> negative events worth over two hundred and twenty-eight thousand reais
> — and flagged them days before a human would. Applying a conservative
> ten percent recovery to the twelve actionable events, acting on the
> recommended actions could have recovered **over seventeen thousand
> reais** — with the biggest single case, Event 66, worth ten thousand on
> its own, caught six days early. Same data, same team — just earlier,
> safer decisions. That is decision intelligence for marketplace
> operations."

**Do:** let the ROI metrics sit on screen for a beat. Stop talking.

---

## Q&A ammunition

| Likely question | Answer |
|---|---|
| "Where do the ROI numbers come from?" | Deterministic back-test over `fact_gmv_events`; every assumption (10% recovery, actionable-decision definition, detection-lead counterfactual) is stated in the "Assumptions & method" expander. |
| "Is the LLM a source of truth?" | No. `llm/narrative_validator.py` checks every number, status, currency, and causal claim against the deterministic evidence; failures are rejected and retried with feedback. |
| "What if the model hallucinates?" | It does, sometimes — the validator catches it and the API retries with feedback. Rejections are a feature, shown as diagnostics. |
| "How does it abstain?" | Confidence is fused from contribution share, review evidence, and business context; below thresholds the decision engine returns ABSTAIN/DO_NOT_ACT instead of an action. |
| "What powers the LLM?" | A provider router: local Ollama (qwen3) by default — private, no API key — with Groq/OpenRouter cloud fallbacks. |
| "How would this run in production?" | The pipeline is modular (21 steps), the API is FastAPI, the warehouse is DuckDB; the same engine runs on-demand per event. |

## Rehearsal notes

- Run through it **three times**; the Generate AI Story click is the only
  live latency — fill it with the local-inference privacy line.
- If generation is rejected by the validator (rare), smile and say:
  *"and there's the validator doing its job"* — then click again.
- Do not scroll fast. Every pause on an ABSTAIN row is a trust signal.
- Total clicks in the demo: 2 (event select, Generate AI Story).