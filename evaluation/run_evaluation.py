"""Evaluation notebook: measured quality of the narrative layer.

Run:  python evaluation/run_evaluation.py

Cells:
  1. Load artifacts (stories, validations, insight, feedback)
  2. Narrative acceptance rate (validator + analyst feedback)
  3. Validator precision/recall against seeded hallucinations
  4. LLM telemetry (latency / tokens / cost per narrative)
  5. Feedback calibration (reliability bins + ECE + SVG plot)
  6. Export evaluation_report.json + slide.html

Outputs:
  data/evaluation/evaluation_report.json
  data/evaluation/slide.html
"""

from __future__ import annotations

import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from llm.narrative_validator import validate_story
from evaluation.hallucination_seeds import seed_hallucinations

# ============================================================
# PATHS
# ============================================================

INSIGHTS_DIR = PROJECT_ROOT / "data" / "insights"
FEEDBACK_DIR = PROJECT_ROOT / "data" / "feedback"
EVAL_DIR = PROJECT_ROOT / "data" / "evaluation"

REPORT_JSON = EVAL_DIR / "evaluation_report.json"
SLIDE_HTML = EVAL_DIR / "slide.html"

VALIDATOR_CHECKS = [
    "numbers",
    "statuses",
    "uncertainty",
    "currency",
    "causal_language",
    "driver_claims",
]


def read_json(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_artifacts() -> dict:
    """CELL 1 - load every artifact the evaluation needs."""
    personas = {}
    for persona in ("executive", "operations"):
        story = read_json(INSIGHTS_DIR / f"{persona}_story.json")
        validation = read_json(INSIGHTS_DIR / f"{persona}_validation.json")
        if story:
            personas[persona] = {
                "story": story.get("story", ""),
                "telemetry": story.get("telemetry", {}),
                "validation": validation or {},
            }
    return {
        "insight": read_json(INSIGHTS_DIR / "latest_insight.json") or {},
        "personas": personas,
        "feedback_records": read_json(FEEDBACK_DIR / "feedback_records.json") or [],
        "calibration_report": read_json(FEEDBACK_DIR / "calibration_report.json") or {},
    }


# ============================================================
# CELL 2 - ACCEPTANCE
# ============================================================


def compute_acceptance(artifacts: dict) -> dict:
    """Narrative acceptance: validator pass rate + analyst acceptance."""
    personas = artifacts["personas"]
    n_stories = len(personas)
    validator_passed = sum(
        1 for p in personas.values() if p["validation"].get("passed")
    )

    records = artifacts["feedback_records"]
    labels = [str(r.get("feedback_label", "")).upper() for r in records]
    n_feedback = len(labels)
    n_correct = labels.count("CORRECT")
    n_incorrect = labels.count("INCORRECT")
    n_missing = labels.count("MISSING_CONTEXT")
    definite = n_correct + n_incorrect

    return {
        "validator_pass_rate": round(validator_passed / n_stories, 4)
        if n_stories
        else None,
        "narratives_validated": n_stories,
        "feedback_count": n_feedback,
        "feedback_acceptance_rate": round(n_correct / definite, 4)
        if definite
        else None,
        "feedback_correct": n_correct,
        "feedback_incorrect": n_incorrect,
        "feedback_missing_context": n_missing,
    }


# ============================================================
# CELL 3 - HALLUCINATION EXPERIMENT
# ============================================================


def run_hallucination_experiment(artifacts: dict) -> dict:
    """Seed known defects, run the validator, score precision/recall.

    Per check c over the corpus (2 clean + N seeded stories):
      TP = seeded stories whose TARGET is c and c flagged
      FN = seeded stories whose TARGET is c and c passed
      FP = clean stories where c flagged (false accusation)
    """
    insight = artifacts["insight"]
    per_persona_runs: list[dict] = []
    confusion = {
        c: {"tp": 0, "fn": 0, "fp": 0} for c in VALIDATOR_CHECKS
    }
    seeds_total = 0
    seeds_caught_any = 0
    seeds_caught_target = 0

    for persona, art in artifacts["personas"].items():
        story = art["story"]

        # Clean run — false positives here hurt precision
        clean = validate_story(story, insight, persona)
        failed_clean = [
            c for c, r in clean["checks"].items() if not r.get("passed")
        ]
        for c in failed_clean:
            confusion[c]["fp"] += 1

        per_persona_runs.append(
            {
                "persona": persona,
                "run": "clean",
                "passed": clean["passed"],
                "failed_checks": failed_clean,
            }
        )

        # Seeded runs
        for seed in seed_hallucinations(story, insight):
            seeds_total += 1
            result = validate_story(seed["story"], insight, persona)
            failed = [
                c for c, r in result["checks"].items() if not r.get("passed")
            ]
            target = seed["target_check"]
            caught_any = len(failed) > 0
            caught_target = target in failed

            if caught_any:
                seeds_caught_any += 1
            if caught_target:
                seeds_caught_target += 1
                confusion[target]["tp"] += 1
            else:
                confusion[target]["fn"] += 1

            per_persona_runs.append(
                {
                    "persona": persona,
                    "run": seed["seed_id"],
                    "defect": seed["defect"],
                    "target_check": target,
                    "passed": result["passed"],
                    "failed_checks": failed,
                    "caught_target": caught_target,
                }
            )

    per_check = {}
    for c, m in confusion.items():
        tp, fn, fp = m["tp"], m["fn"], m["fp"]
        per_check[c] = {
            "seeded_defects": tp + fn,
            "caught": tp,
            "missed": fn,
            "false_positives_on_clean": fp,
            "recall": round(tp / (tp + fn), 4) if (tp + fn) else None,
            "precision": round(tp / (tp + fp), 4) if (tp + fp) else None,
        }

    return {
        "seeds_total": seeds_total,
        "seeds_caught_by_any_check": seeds_caught_any,
        "seeds_caught_by_target_check": seeds_caught_target,
        "overall_catch_rate": round(seeds_caught_any / seeds_total, 4)
        if seeds_total
        else None,
        "target_catch_rate": round(seeds_caught_target / seeds_total, 4)
        if seeds_total
        else None,
        "per_check": per_check,
        "runs": per_persona_runs,
    }


# ============================================================
# CELL 4 - LLM TELEMETRY
# ============================================================


def compute_telemetry(artifacts: dict) -> dict:
    """Aggregate cost/latency/token telemetry per narrative."""
    records = []
    for persona, art in artifacts["personas"].items():
        t = art.get("telemetry") or {}
        if not t:
            continue
        records.append(
            {
                "persona": persona,
                "model": t.get("model"),
                "latency_ms": t.get("latency_ms"),
                "prompt_tokens": t.get("prompt_tokens"),
                "completion_tokens": t.get("completion_tokens"),
                "total_tokens": t.get("total_tokens"),
                "model_calls": t.get("model_calls"),
                "estimated_cost_usd": t.get("estimated_cost_usd"),
            }
        )

    if not records:
        return {"narratives": 0}

    latencies = [r["latency_ms"] for r in records if r["latency_ms"]]
    costs = [r["estimated_cost_usd"] for r in records if r["estimated_cost_usd"]]
    tokens = [r["total_tokens"] for r in records if r["total_tokens"]]

    mean_latency = statistics.mean(latencies) if latencies else None
    mean_cost = statistics.mean(costs) if costs else None

    return {
        "narratives": len(records),
        "model": records[0]["model"],
        "model_calls_total": sum(r["model_calls"] or 0 for r in records),
        "mean_latency_ms": round(mean_latency, 1) if mean_latency else None,
        "max_latency_ms": round(max(latencies), 1) if latencies else None,
        "mean_total_tokens": round(statistics.mean(tokens), 1) if tokens else None,
        "total_tokens": sum(tokens),
        "mean_cost_usd": round(mean_cost, 6) if mean_cost else None,
        "total_cost_usd": round(sum(costs), 6),
        "projected_cost_per_1k_narratives_usd": round(mean_cost * 1000, 2)
        if mean_cost
        else None,
        "per_narrative": records,
    }


# ============================================================
# CELL 5 - CALIBRATION
# ============================================================

CALIBRATION_BINS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]


def compute_calibration(artifacts: dict) -> dict:
    """Reliability bins + Expected Calibration Error from feedback.

    CORRECT -> 1, INCORRECT -> 0; MISSING_CONTEXT excluded from
    accuracy (consistent with feedback/capture_and_calibrate.py).
    """
    records = artifacts["feedback_records"]
    definite = [
        r
        for r in records
        if str(r.get("feedback_label", "")).upper()
        in ("CORRECT", "INCORRECT")
        and r.get("predicted_confidence") is not None
    ]

    bins = []
    ece_numerator = 0.0
    for lo, hi in CALIBRATION_BINS:
        members = [
            r
            for r in definite
            if lo <= float(r["predicted_confidence"]) < hi
        ]
        if not members:
            continue
        mean_pred = statistics.mean(
            float(r["predicted_confidence"]) for r in members
        )
        obs_acc = statistics.mean(
            1.0 if str(r["feedback_label"]).upper() == "CORRECT" else 0.0
            for r in members
        )
        gap = abs(mean_pred - obs_acc)
        ece_numerator += len(members) / len(definite) * gap
        bins.append(
            {
                "confidence_range": f"{lo:.1f}-{hi:.1f}",
                "count": len(members),
                "mean_predicted_confidence": round(mean_pred, 3),
                "observed_accuracy": round(obs_acc, 3),
                "calibration_gap": round(mean_pred - obs_acc, 3),
            }
        )

    return {
        "definite_feedback": len(definite),
        "bins": bins,
        "ece": round(ece_numerator, 4) if definite else None,
        "policy": artifacts.get("calibration_report", {}).get(
            "calibration_policy", {}
        ),
    }


def calibration_svg(calibration: dict, width: int = 320, height: int = 260) -> str:
    """Self-contained SVG reliability diagram (no chart libraries)."""
    pad_l, pad_b, pad_t = 44, 36, 14
    plot_w, plot_h = width - pad_l - 12, height - pad_b - pad_t
    bins = calibration.get("bins", [])

    def x(v):
        return pad_l + v * plot_w

    def y(v):
        return pad_t + (1 - v) * plot_h

    parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">'
    ]
    # Axes + gridlines
    parts.append(
        f'<rect x="{pad_l}" y="{pad_t}" width="{plot_w}" height="{plot_h}" '
        'fill="#141a2e" stroke="#2a3350"/>'
    )
    for v in (0.25, 0.5, 0.75, 1.0):
        parts.append(
            f'<line x1="{x(v):.1f}" y1="{y(v):.1f}" x2="{x(1.0):.1f}" '
            f'y2="{y(v):.1f}" stroke="#2a3350" stroke-width="0.5"/>'
        )
    # Perfect-calibration diagonal
    parts.append(
        f'<line x1="{x(0):.1f}" y1="{y(0):.1f}" x2="{x(1):.1f}" '
        f'y2="{y(1):.1f}" stroke="#5b6b94" stroke-dasharray="4 3" stroke-width="1"/>'
    )
    # Observed-accuracy bars (bin width 0.2)
    for b in bins:
        lo = float(b["confidence_range"].split("-")[0])
        pred, obs = b["mean_predicted_confidence"], b["observed_accuracy"]
        bw = 0.2 * plot_w
        bx = x(lo) + 2
        parts.append(
            f'<rect x="{bx:.1f}" y="{y(obs):.1f}" width="{bw - 4:.1f}" '
            f'height="{max(1, y(0) - y(obs)):.1f}" fill="#3fa7ff" opacity="0.75"/>'
        )
        parts.append(
            f'<circle cx="{x(pred):.1f}" cy="{y(pred):.1f}" r="3.5" fill="#ffd166"/>'
        )
        parts.append(
            f'<text x="{bx + (bw - 4) / 2:.1f}" y="{height - 20}" '
            f'font-size="9" fill="#8b96b5" text-anchor="middle">{b["confidence_range"]}</text>'
        )
        parts.append(
            f'<text x="{bx + (bw - 4) / 2:.1f}" y="{height - 8}" '
            f'font-size="9" fill="#8b96b5" text-anchor="middle">n={b["count"]}</text>'
        )
    parts.append(
        f'<text x="{pad_l}" y="{pad_t - 4}" font-size="9" fill="#8b96b5">'
        'observed accuracy</text>'
    )
    parts.append(
        f'<text x="{width / 2:.0f}" y="{height - 0.5}" font-size="0"> </text>'
    )
    parts.append("</svg>")
    return "".join(parts)


# ============================================================
# CELL 6 - SLIDE + REPORT EXPORT
# ============================================================

SLIDE_CSS = """
body{margin:0;background:#0b1020;color:#e8ecf7;font-family:'Segoe UI',Arial,sans-serif}
.slide{max-width:1180px;margin:24px auto;padding:34px 42px;background:#0e1428;
border:1px solid #232c4a;border-radius:14px}
h1{font-size:26px;margin:0 0 2px} h1 .accent{color:#3fa7ff}
.sub{color:#8b96b5;font-size:13px;margin-bottom:22px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.card{background:#131a33;border:1px solid #232c4a;border-radius:10px;padding:16px 18px}
.card h2{font-size:14px;margin:0 0 10px;color:#aebadb;text-transform:uppercase;
letter-spacing:.6px}
.big{font-size:34px;font-weight:700;color:#3fa7ff}
.big.gold{color:#ffd166}.big.green{color:#4ade80}
.kv{display:flex;justify-content:space-between;font-size:13px;padding:3px 0;
border-bottom:1px dashed #232c4a;gap:12px}
.kv:last-child{border-bottom:none}
.kv b{color:#e8ecf7;text-align:right}.kv span{color:#8b96b5}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{color:#8b96b5;text-align:left;font-weight:600;padding:4px 6px;
border-bottom:1px solid #2a3350}
td{padding:4px 6px;border-bottom:1px dashed #202845}
.ok{color:#4ade80;font-weight:600}.miss{color:#f87171;font-weight:600}
.foot{margin-top:16px;color:#5b6b94;font-size:11px}
code{color:#8b96b5}
"""


def _fmt(v, suffix=""):
    return "—" if v is None else f"{v}{suffix}"


def _pct(v):
    return "—" if v is None else f"{v * 100:.0f}%"


def render_slide(report: dict) -> str:
    """Single self-contained HTML slide with every headline number."""
    hx = report["hallucination"]
    acc = report["acceptance"]
    tel = report["telemetry"]
    cal = report["calibration"]

    check_rows = "".join(
        f"<tr><td>{c}</td>"
        f"<td>{m['seeded_defects']}</td>"
        f"<td class={'ok' if m['caught'] else 'miss'}>{m['caught']}</td>"
        f"<td>{m['missed']}</td>"
        f"<td class={'ok' if not m['false_positives_on_clean'] else 'miss'}>"
        f"{m['false_positives_on_clean']}</td>"
        f"<td>{_pct(m['precision'])}</td>"
        f"<td>{_pct(m['recall'])}</td></tr>"
        for c, m in hx["per_check"].items()
    )

    tel_rows = "".join(
        f"<tr><td>{r['persona']}</td><td>{r['model']}</td>"
        f"<td>{r['latency_ms']:.0f}</td><td>{r['total_tokens']:,}</td>"
        f"<td>${r['estimated_cost_usd']:.5f}</td></tr>"
        for r in tel.get("per_narrative", [])
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>System Evaluation</title>
<style>{SLIDE_CSS}</style></head><body>
<div class="slide">
  <h1>BusinessIntelligence<span class="accent">.ai</span> — Measured, Not Asserted</h1>
  <div class="sub">Evaluation notebook · validator robustness, acceptance, LLM
telemetry, calibration · generated {report["generated_at"]} · warehouse event
{report["insight_id"]}</div>
  <div class="grid">
    <div class="card">
      <h2>Validator vs seeded hallucinations</h2>
      <div class="big green">{_pct(hx["overall_catch_rate"])}</div>
      <div class="kv"><span>defects caught (any check)</span><b>
{hx["seeds_caught_by_any_check"]}/{hx["seeds_total"]}</b></div>
      <div class="kv"><span>caught by the intended check</span><b>
{hx["seeds_caught_by_target_check"]}/{hx["seeds_total"]}</b></div>
      <div class="kv"><span>false positives on clean narratives</span><b>
{sum(m["false_positives_on_clean"] for m in hx["per_check"].values())}</b></div>
      <table style="margin-top:10px"><tr><th>check</th><th>seeds</th>
      <th>caught</th><th>missed</th><th>FP</th><th>prec</th><th>rec</th></tr>
      {check_rows}</table>
    </div>
    <div class="card">
      <h2>Narrative acceptance</h2>
      <div class="big">{_pct(acc["validator_pass_rate"])}</div>
      <div class="kv"><span>narratives validated</span><b>
{acc["narratives_validated"]}</b></div>
      <div class="kv"><span>analyst acceptance (CORRECT / definite)</span><b>
{_pct(acc["feedback_acceptance_rate"])}</b></div>
      <div class="kv"><span>feedback records</span><b>{acc["feedback_count"]}
(correct {acc["feedback_correct"]} · incorrect {acc["feedback_incorrect"]} ·
missing-context {acc["feedback_missing_context"]})</b></div>
      <h2 style="margin-top:16px">LLM telemetry</h2>
      <div class="kv"><span>model</span><b>{_fmt(tel.get("model"))}</b></div>
      <div class="kv"><span>mean latency / narrative</span><b>
{_fmt(tel.get("mean_latency_ms"))} ms</b></div>
      <div class="kv"><span>mean tokens / narrative</span><b>
{_fmt(tel.get("mean_total_tokens"))}</b></div>
      <div class="kv"><span>mean cost / narrative</span><b>
${_fmt(tel.get("mean_cost_usd"))}</b></div>
      <div class="kv"><span>projected cost / 1,000 narratives</span><b>
${_fmt(tel.get("projected_cost_per_1k_narratives_usd"))}</b></div>
      <table style="margin-top:10px"><tr><th>persona</th><th>model</th>
      <th>ms</th><th>tokens</th><th>cost</th></tr>{tel_rows}</table>
    </div>
    <div class="card">
      <h2>Confidence calibration (analyst feedback)</h2>
      <div class="kv"><span>Expected Calibration Error (ECE)</span><b>
{_fmt(cal.get("ece"))}</b></div>
      <div class="kv"><span>definite feedback samples</span><b>
{cal.get("definite_feedback", 0)}</b></div>
      <div style="margin-top:8px">{calibration_svg(cal)}</div>
      <div class="kv" style="margin-top:6px"><span>bars = observed accuracy ·
dots = mean predicted confidence · dashed = perfect calibration</span></div>
    </div>
    <div class="card">
      <h2>Governance posture</h2>
      <div class="kv"><span>LLM role</span><b>narrative synthesis only — never
computes truth</b></div>
      <div class="kv"><span>validator</span><b>6 deterministic checks, every claim
traced to the insight JSON</b></div>
      <div class="kv"><span>confidence override from small samples</span><b>
{cal.get("policy", {}).get("automatic_confidence_override", "disabled")} (gated
at ≥ {cal.get("policy", {}).get("minimum_feedback", 5)} samples)</b></div>
      <div class="kv"><span>uncertainty handling</span><b>weak/abstain drivers must
surface hedging language or the narrative is rejected</b></div>
      <div class="kv"><span>telemetry transparency</span><b>latency, tokens and
estimated cost recorded per narrative</b></div>
      <div class="foot">Reproduce: <code>python evaluation/run_evaluation.py</code>
· artifacts: <code>data/evaluation/</code></div>
    </div>
  </div>
</div>
</body></html>"""


# ============================================================
# MAIN
# ============================================================


def main() -> int:
    print("=" * 76)
    print("CELL 1 · loading artifacts")
    artifacts = load_artifacts()
    print(f"  personas: {list(artifacts['personas'])}")
    print(f"  feedback records: {len(artifacts['feedback_records'])}")

    print("CELL 2 · acceptance")
    acceptance = compute_acceptance(artifacts)
    print(f"  validator pass rate : {acceptance['validator_pass_rate']}")
    print(f"  feedback acceptance : {acceptance['feedback_acceptance_rate']}")

    print("CELL 3 · hallucination experiment")
    hx = run_hallucination_experiment(artifacts)
    print(
        f"  seeds: {hx['seeds_total']} · caught by target: "
        f"{hx['seeds_caught_by_target_check']} · caught by any: "
        f"{hx['seeds_caught_by_any_check']}"
    )
    for c, m in hx["per_check"].items():
        print(
            f"    {c:<16} seeds={m['seeded_defects']} caught={m['caught']} "
            f"fp={m['false_positives_on_clean']} "
            f"prec={m['precision']} rec={m['recall']}"
        )

    print("CELL 4 · telemetry")
    telemetry = compute_telemetry(artifacts)
    print(
        f"  mean latency: {telemetry.get('mean_latency_ms')} ms · "
        f"mean cost: ${telemetry.get('mean_cost_usd')} · "
        f"per 1k: ${telemetry.get('projected_cost_per_1k_narratives_usd')}"
    )

    print("CELL 5 · calibration")
    calibration = compute_calibration(artifacts)
    print(
        f"  ECE: {calibration.get('ece')} over "
        f"{calibration.get('definite_feedback')} definite samples"
    )

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "insight_id": artifacts["insight"].get("insight_id"),
        "acceptance": acceptance,
        "hallucination": hx,
        "telemetry": telemetry,
        "calibration": calibration,
    }

    print("CELL 6 · export")
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    SLIDE_HTML.write_text(render_slide(report), encoding="utf-8")
    print(f"  report: {REPORT_JSON}")
    print(f"  slide : {SLIDE_HTML}")
    print("=" * 76)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

