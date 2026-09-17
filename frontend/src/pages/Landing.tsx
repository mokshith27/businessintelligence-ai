import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, type KpiStatusPayload, type RoiSummary, type EventsPayload } from '../lib/api';
import { fmtMoney, fmtDate, fmtPctRaw } from '../lib/format';

const CAPABILITIES = [
  {
    ico: '📈',
    title: 'KPI Intelligence',
    text: 'Seasonal robust baselines and materiality scoring combine statistical unusualness with real business impact — so a big percentage move is not automatically a meaningful event.',
  },
  {
    ico: '🔍',
    title: 'Driver Investigation',
    text: 'GMV decomposed into volume and AOV effects, plus segment contribution analysis across state, category and seller dimensions — ranked by observed contribution.',
  },
  {
    ico: '💬',
    title: 'Unstructured Evidence',
    text: 'Review aspect tagging and multilingual aspect-level sentiment are compared between event and comparison periods as independent evidence.',
  },
  {
    ico: '🧾',
    title: 'Evidence Fusion & Governance',
    text: 'Multi-source fusion with explicit confidence. Insufficient evidence always produces an explicit ABSTAIN — never a confident guess.',
  },
  {
    ico: '🤖',
    title: 'Grounded LLM Narratives',
    text: 'Every number in a narrative comes from the deterministic layer. A validator checks values, statuses and causal wording before anything is shown.',
  },
  {
    ico: '🎯',
    title: 'Validated Decisions',
    text: 'Safe-action rules block high-impact interventions on weak evidence, and scenario scorecards prove driver identification and abstention behavior.',
  },
];

const PIPELINE = [
  { n: '01', t: 'Detect', d: 'Seasonal baseline + robust z-score on daily KPIs' },
  { n: '02', t: 'Investigate', d: 'Volume/AOV decomposition + segment contributions' },
  { n: '03', t: 'Fuse evidence', d: 'Review sentiment + business context + structure' },
  { n: '04', t: 'Score confidence', d: 'Explicit ABSTAIN when evidence is insufficient' },
  { n: '05', t: 'Recommend', d: 'Safe actions with owner + monitoring plan' },
  { n: '06', t: 'Explain', d: 'Role-specific, validator-grounded narratives' },
];

export function Landing() {
  const [kpis, setKpis] = useState<KpiStatusPayload | null>(null);
  const [roi, setRoi] = useState<RoiSummary | null>(null);
  const [events, setEvents] = useState<EventsPayload | null>(null);
  const [degraded, setDegraded] = useState(false);

  useEffect(() => {
    api.kpiStatus().then(setKpis).catch(() => setDegraded(true));
    api.roiSummary().then(setRoi).catch(() => setDegraded(true));
    api.events(10).then(setEvents).catch(() => setDegraded(true));
  }, []);

  return (
    <>
      <header className="hero">
        <div className="app-shell">
          <span className="eyebrow">
            <span className="pulse" /> Live decision-intelligence engine
          </span>
          <h1>
            From KPI movement to <span className="grad">evidence-backed action.</span>
          </h1>
          <p className="hero-sub">
            BusinessIntelligence.ai detects meaningful marketplace KPI movements on their first anomalous day, investigates
            where the change occurred, fuses structured and unstructured evidence — and abstains when the evidence is
            insufficient.
          </p>
          <div className="hero-actions">
            <Link to="/dashboard" className="btn btn-primary">
              Open the live console →
            </Link>
            <a href="#pipeline" className="btn btn-ghost">
              How it works
            </a>
          </div>
          <div className="hero-stats">
            <div className="stat-card">
              <div className="stat-num">{roi ? fmtMoney(roi.summary.estimated_recoverable_gmv) : 'R$17.5k'}</div>
              <div className="stat-label">Recoverable GMV (back-tested)</div>
            </div>
            <div className="stat-card">
              <div className="stat-num">{roi ? fmtMoney(roi.summary.total_at_risk_gmv) : 'R$228k'}</div>
              <div className="stat-label">GMV at risk across flagged events</div>
            </div>
            <div className="stat-card">
              <div className="stat-num plain">
                {roi ? `${roi.summary.average_detection_lead_days}` : '1.5'}
                <span style={{ fontSize: 16, color: 'var(--muted)' }}> days</span>
              </div>
              <div className="stat-label">Average detection lead vs manual review</div>
            </div>
            <div className="stat-card">
              <div className="stat-num">{kpis ? `${kpis.kpis_evaluated}` : '5'}</div>
              <div className="stat-label">KPIs under governance contracts</div>
            </div>
          </div>
        </div>
      </header>

      <section className="section" id="capabilities">
        <div className="app-shell">
          <div className="section-head">
            <h2>Everything a marketplace ops team needs</h2>
            <p>
              One deterministic pipeline powers three role-based views — Executive, Operations and Analyst — enforced
              end-to-end with JWT authentication.
            </p>
          </div>
          <div className="cap-grid">
            {CAPABILITIES.map((c) => (
              <div className="cap-card" key={c.title}>
                <div className="cap-icon">{c.ico}</div>
                <h3>{c.title}</h3>
                <p>{c.text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="section" id="pipeline" style={{ paddingTop: 0 }}>
        <div className="app-shell">
          <div className="section-head">
            <h2>The decision pipeline</h2>
            <p>Detect → investigate → decide → explain. The analytical layer determines the truth; the LLM explains it.</p>
          </div>
          <div className="pipeline">
            {PIPELINE.map((p) => (
              <div className="pipe-step" key={p.n}>
                <div className="n">{p.n}</div>
                <div className="t">{p.t}</div>
                <div className="d">{p.d}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="section" style={{ paddingTop: 0 }}>
        <div className="app-shell">
          <div className="section-head">
            <h2>Live KPI status</h2>
            <p>
              Pulled straight from the warehouse-backed API.
              {degraded && ' Some panels need the local DuckDB warehouse to be built.'}
            </p>
          </div>
          <div className="kpi-strip">
            {kpis
              ? Object.entries(kpis.kpis).map(([key, k]) => (
                  <div className="kpi-card" key={key}>
                    <div className="kpi-top">
                      <span className="kpi-name">{k.name}</span>
                      <span className={`badge ${k.flagged ? 'badge-alert' : 'badge-normal'}`}>{k.status}</span>
                    </div>
                    <div className="kpi-value">{fmtPctRaw(k.change_pct)}</div>
                    <div className="kpi-meta">z = {k.z_score.toFixed(2)} vs seasonal baseline</div>
                  </div>
                ))
              : [0, 1, 2, 3, 4].map((i) => <div className="skel skel-card" key={i} />)}
          </div>

          <div className="main-subhead" style={{ marginTop: 40 }}>
            Latest flagged events
          </div>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Event</th>
                  <th>Window</th>
                  <th>Direction</th>
                  <th>Anomalous days</th>
                  <th>Impact</th>
                  <th>Priority</th>
                </tr>
              </thead>
              <tbody>
                {events
                  ? events.events.slice(0, 6).map((e) => (
                      <tr key={e.event_group}>
                        <td className="ev-pri">#{e.event_group}</td>
                        <td>
                          {fmtDate(e.event_start_date)} → {fmtDate(e.event_end_date)}
                        </td>
                        <td>
                          <span className={`ev-dir ${e.direction === 'POSITIVE' ? 'ev-pos' : 'ev-neg'}`}>{e.direction}</span>
                        </td>
                        <td>{e.anomalous_days}</td>
                        <td className="ev-impact">{fmtMoney(e.cumulative_absolute_impact)}</td>
                        <td className="ev-pri">{(e.event_priority_score * 100).toFixed(0)}%</td>
                      </tr>
                    ))
                  : (
                      <tr>
                        <td colSpan={6}>
                          <div className="skel skel-line" />
                        </td>
                      </tr>
                    )}
              </tbody>
            </table>
          </div>
          {events && (
            <div className="table-note">
              Showing the 6 highest-priority events of {events.count}. Open the console to investigate any of them.
            </div>
          )}
        </div>
      </section>

      <div className="app-shell">
        <div className="cta-band">
          <div>
            <h2>Sign in and investigate your first event in under a minute.</h2>
            <p>
              One-click demo users for the Executive, Operations and Analyst personas. JWT-authenticated, role-filtered,
              fully grounded.
            </p>
          </div>
          <Link to="/dashboard" className="btn btn-primary">
            Launch console →
          </Link>
        </div>
      </div>
    </>
  );
}