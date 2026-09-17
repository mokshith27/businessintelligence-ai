import { useEffect, useState } from 'react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Cell,
} from 'recharts';
import { api, type KpiStatusPayload, type RoiSummary, type ActionsPayload } from '../lib/api';
import { fmtMoney, fmtDate, fmtNumber, fmtPctRaw } from '../lib/format';

export function Dashboard() {
  const [kpis, setKpis] = useState<KpiStatusPayload | null>(null);
  const [roi, setRoi] = useState<RoiSummary | null>(null);
  const [actions, setActions] = useState<ActionsPayload | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.kpiStatus().then(setKpis).catch((e) => setErr(e.message));
    api.roiSummary().then(setRoi).catch(() => undefined);
    api.actions().then(setActions).catch(() => undefined);
  }, []);

  const topActions = actions?.actions.slice(0, 5) ?? [];

  return (
    <>
      <div className="main-header">
        <button className="btn btn-ghost btn-sm refresh-btn" onClick={() => window.location.reload()}>
          ↻ Refresh
        </button>
        <h1>Overview</h1>
        <p>Live KPI governance, back-tested business impact and recommended actions.</p>
      </div>

      {err && <div className="auth-warn">API error: {err}</div>}

      <div className="main-subhead">KPI status</div>
      <div className="kpi-strip">
        {kpis
          ? Object.entries(kpis.kpis).map(([key, k]) => (
              <div className="kpi-card" key={key}>
                <div className="kpi-top">
                  <span className="kpi-name">{k.name}</span>
                  <span className={`badge ${k.flagged ? 'badge-alert' : 'badge-normal'}`}>{k.status}</span>
                </div>
                <div className="kpi-value">{fmtPctRaw(k.change_pct)}</div>
                <div className="kpi-meta">
                  z = {k.z_score.toFixed(2)} · {fmtDate(k.latest_date)}
                </div>
              </div>
            ))
          : [0, 1, 2, 3, 4].map((i) => <div className="skel skel-card" key={i} />)}
      </div>

      <div className="main-subhead">Business impact (deterministic back-test)</div>
      <div className="panel">
        {roi ? (
          <>
            <div className="roi-hero">
              <span className="big">{fmtMoney(roi.summary.estimated_recoverable_gmv)}</span>
              <span className="lbl">
                estimated recoverable GMV (range up to {fmtMoney(roi.summary.estimated_recoverable_gmv_upper)})
              </span>
            </div>
            <div className="roi-chips">
              <span className="chip">
                <b>{roi.summary.events_analyzed}</b> negative events analyzed
              </span>
              <span className="chip">
                <b>{roi.summary.actionable_events}</b> actionable · <b>{roi.summary.abstained_events}</b> abstained
              </span>
              <span className="chip">
                <b>{fmtMoney(roi.summary.total_at_risk_gmv)}</b> total GMV at risk
              </span>
              <span className="chip">
                <b>{roi.summary.average_detection_lead_days}</b> avg detection lead (days)
              </span>
            </div>
          </>
        ) : (
          <div className="skel skel-block" />
        )}
      </div>

      <div className="panel-grid-2">
        <div className="panel">
          <h3>Top events by GMV at risk</h3>
          {roi ? (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={roi.events.slice(0, 8)} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
                <XAxis dataKey="event_id" stroke="#6b7fa8" fontSize={12} tickLine={false} axisLine={false} />
                <YAxis
                  stroke="#6b7fa8"
                  fontSize={12}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v) => fmtMoney(Number(v))}
                  width={70}
                />
                <Tooltip
                  cursor={{ fill: 'rgba(59,130,246,0.08)' }}
                  content={({ active, payload, label }) =>
                    active && payload?.length ? (
                      <div className="chart-tip">
                        <div className="t">Event #{String(label)}</div>
                        At-risk GMV: <b>{fmtMoney(Number(payload[0].value))}</b>
                      </div>
                    ) : null
                  }
                />
                <Bar dataKey="at_risk_gmv" radius={[6, 6, 0, 0]}>
                  {roi.events.slice(0, 8).map((e) => (
                    <Cell key={e.event_id} fill={e.actionable ? '#3b82f6' : '#fbbf24'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="skel skel-block" />
          )}
          <div className="table-note">
            <span style={{ color: '#3b82f6' }}>■</span> actionable event · <span style={{ color: '#fbbf24' }}>■</span>{' '}
            abstained
          </div>
        </div>

        <div className="panel">
          <h3>Top recommended actions</h3>
          {topActions.length > 0 ? (
            topActions.map((a, i) => (
              <div key={`${a.event_id}-${a.driver}-${i}`}>
                <div className="drivers-head">
                  <span>
                    <b>
                      {a.driver_type === 'customer_state' ? 'State' : a.driver_type === 'category' ? 'Category' : a.driver_type}:
                    </b>{' '}
                    {a.driver} <span style={{ color: 'var(--muted)' }}>· event #{a.event_id}</span>
                  </span>
                  <span className="share">{fmtNumber(a.contribution_share * 100)}%</span>
                </div>
                <div className="conf-bar">
                  <div className="conf-fill" style={{ width: `${Math.round(a.confidence * 100)}%` }} />
                </div>
                <div className="kv">
                  <span className="k">Decision</span>
                  <span className="v">{a.decision ?? '—'}</span>
                </div>
                <div className="kv">
                  <span className="k">Owner</span>
                  <span className="v">{a.owner ?? '—'}</span>
                </div>
              </div>
            ))
          ) : (
            <div className="empty">No recommended actions available yet.</div>
          )}
        </div>
      </div>
    </>
  );
}