import { useEffect, useState } from 'react';
import { api, type EventsPayload, type GmvEvent, type InvestigationPayload } from '../lib/api';
import { fmtMoney, fmtDate, fmtNumber, fmtPct, statusClass } from '../lib/format';

export function Events() {
  const [events, setEvents] = useState<EventsPayload | null>(null);
  const [selected, setSelected] = useState<GmvEvent | null>(null);
  const [investigation, setInvestigation] = useState<InvestigationPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api
      .events(30)
      .then(setEvents)
      .catch((e) => setErr(e.message));
  }, []);

  async function open(ev: GmvEvent) {
    setSelected(ev);
    setInvestigation(null);
    setErr(null);
    setLoading(true);
    try {
      const result = await api.eventInvestigation(ev.event_group);
      setInvestigation(result);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Investigation failed.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <div className="main-header">
        <h1>Events</h1>
        <p>Flagged KPI movements ranked by priority. Click a row to run the full deterministic investigation.</p>
      </div>

      {err && <div className="auth-warn">{err}</div>}

      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Event</th>
              <th>Window</th>
              <th>Direction</th>
              <th>Days</th>
              <th>Peak change</th>
              <th>z-score</th>
              <th>Cumulative impact</th>
              <th>Priority</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {events?.events.map((e) => (
              <tr key={e.event_group} onClick={() => open(e)}>
                <td className="ev-pri">#{e.event_group}</td>
                <td>
                  {fmtDate(e.event_start_date)} → {fmtDate(e.event_end_date)}
                </td>
                <td>
                  <span className={`ev-dir ${e.direction === 'POSITIVE' ? 'ev-pos' : 'ev-neg'}`}>{e.direction}</span>
                </td>
                <td>{e.anomalous_days}</td>
                <td className="ev-impact">{fmtPct(e.peak_change_abs)}</td>
                <td className="ev-impact">{e.peak_z_score.toFixed(1)}</td>
                <td className="ev-impact">{fmtMoney(e.cumulative_absolute_impact)}</td>
                <td className="ev-pri">{(e.event_priority_score * 100).toFixed(0)}%</td>
                <td className="ev-open">Investigate →</td>
              </tr>
            ))}
            {!events && (
              <tr>
                <td colSpan={9}>
                  <div className="skel skel-line" />
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {selected && (
        <>
          <div className="main-subhead" style={{ marginTop: 32 }}>
            Investigation · event #{selected.event_group}
          </div>
          {loading ? (
            <div className="panel">
              <div className="skel skel-line" style={{ width: '50%' }} />
              <div className="skel skel-block" />
              <div className="skel skel-block" />
            </div>
          ) : investigation ? (
            <EventDetail data={investigation} />
          ) : null}
        </>
      )}
    </>
  );
}

function EventDetail({ data }: { data: InvestigationPayload }) {
  const m = data.movement;
  const drivers = [...data.drivers].sort((a, b) => b.observed_contribution.share - a.observed_contribution.share);
  const topDrivers = drivers.slice(0, 8);

  const movementRows: Array<[string, string, string | null]> = [
    ['Previous GMV', fmtMoney(m.previous_gmv), null],
    ['Current GMV', fmtMoney(m.current_gmv), null],
    ['GMV change', fmtMoney(m.gmv_change), m.gmv_change >= 0 ? 'pos' : 'neg'],
    ['Orders', `${fmtNumber(m.previous_orders)} → ${fmtNumber(m.current_orders)}`, null],
    ['AOV change', fmtMoney(m.aov_change), m.aov_change >= 0 ? 'pos' : 'neg'],
    ['Volume effect', fmtMoney(m.volume_effect), m.volume_effect >= 0 ? 'pos' : 'neg'],
    ['AOV effect', fmtMoney(m.aov_effect), m.aov_effect >= 0 ? 'pos' : 'neg'],
  ];

  const ev = data.event;

  return (
    <>
      <div className="panel-grid-2">
        <div className="panel">
          <h3>
            Event window {fmtDate(String(ev.start_date))} → {fmtDate(String(ev.end_date))}{' '}
            <span className={`status-chip ${ev.direction === 'POSITIVE' ? 'st-supported' : 'st-contradicted'}`}>
              {ev.direction}
            </span>{' '}
            <span className="status-chip st-other">{String(ev.investigation_priority)}</span>
          </h3>
          {movementRows.map(([k, v, cls]) => (
            <div className="kv" key={k}>
              <span className="k">{k}</span>
              <span className={`v ${cls ?? ''}`}>{v}</span>
            </div>
          ))}
        </div>

        <div className="panel">
          <h3>Data quality & lineage</h3>
          {data.data_quality
            ? Object.entries(data.data_quality)
                .filter(([, v]) => typeof v === 'string' || typeof v === 'boolean')
                .map(([k, v]) => (
                  <div className="kv" key={k}>
                    <span className="k">{k.replace(/_/g, ' ')}</span>
                    <span className="v">{String(v)}</span>
                  </div>
                ))
            : null}
          {data.lineage && Array.isArray(data.lineage.methods) ? (
            <div className="roi-chips">
              {(data.lineage.methods as string[]).map((meth) => (
                <span className="chip" key={meth}>
                  {meth}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      </div>

      <div className="main-subhead">Driver contributions (top {topDrivers.length})</div>
      <div className="panel">
        {topDrivers.map((d, i) => (
          <div key={`${d.driver_type}-${d.driver}-${i}`} style={{ marginBottom: 18 }}>
            <div className="drivers-head">
              <span>
                <b>
                  {d.driver_type.replace(/_/g, ' ')}: {d.driver}
                </b>{' '}
                <span className={`status-chip ${statusClass(d.status)}`}>{d.status}</span>
              </span>
              <span className="share">
                {fmtMoney(d.observed_contribution.gmv_change)} · {fmtNumber(d.observed_contribution.share * 100)}%
              </span>
            </div>
            <div className="conf-bar">
              <div className="conf-fill" style={{ width: `${Math.round(d.observed_contribution.share * 100)}%` }} />
            </div>
            <div style={{ display: 'flex', gap: 18, marginTop: 8, flexWrap: 'wrap' }}>
              <span className="chip">
                Confidence <b>{fmtNumber(d.confidence.overall * 100)}%</b>
              </span>
              <span className="chip">
                Review evidence{' '}
                <b>
                  {d.evidence.review ? d.evidence.review.status : 'NONE'} ({d.evidence.review?.event_records ?? 0} recs)
                </b>
              </span>
              <span className="chip">
                Sources <b>{d.confidence.independent_sources}</b>
              </span>
              {d.action.decision ? (
                <span className="chip">
                  Decision <b>{d.action.decision}</b> · owner <b>{d.action.owner ?? '—'}</b>
                </span>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}