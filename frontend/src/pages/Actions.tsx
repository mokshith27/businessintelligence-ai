import { useEffect, useState } from 'react';
import { api, type ActionsPayload } from '../lib/api';
import { fmtNumber, statusClass } from '../lib/format';

export function Actions() {
  const [payload, setPayload] = useState<ActionsPayload | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api
      .actions()
      .then(setPayload)
      .catch((e) => setErr(e.message));
  }, []);

  const byDecision = new Map<string, number>();
  payload?.actions.forEach((a) => {
    const key = a.decision ?? 'NO_DECISION';
    byDecision.set(key, (byDecision.get(key) ?? 0) + 1);
  });

  return (
    <>
      <div className="main-header">
        <h1>Recommended actions</h1>
        <p>
          Safe-action output for the latest insight. High-impact interventions are blocked when evidence is insufficient —
          the engine abstains instead of guessing.
        </p>
      </div>

      {err && <div className="auth-warn">{err}</div>}

      <div className="roi-chips" style={{ marginBottom: 18 }}>
        {[...byDecision.entries()].map(([decision, count]) => (
          <span className="chip" key={decision}>
            {decision.replace(/_/g, ' ')} <b>×{count}</b>
          </span>
        ))}
      </div>

      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Event</th>
              <th>Driver</th>
              <th>Status</th>
              <th>Share</th>
              <th>Confidence</th>
              <th>Decision</th>
              <th>Action</th>
              <th>Owner</th>
            </tr>
          </thead>
          <tbody>
            {payload?.actions.map((a, i) => (
              <tr key={`${a.event_id}-${a.driver}-${i}`}>
                <td className="ev-pri">#{a.event_id}</td>
                <td>
                  <b>{a.driver}</b>
                  <div style={{ color: 'var(--muted)', fontSize: 12 }}>{a.driver_type.replace(/_/g, ' ')}</div>
                </td>
                <td>
                  <span className={`status-chip ${statusClass(a.evidence_status)}`}>{a.evidence_status}</span>
                </td>
                <td className="ev-impact">{fmtNumber(a.contribution_share * 100)}%</td>
                <td className="ev-impact">{fmtNumber(a.confidence * 100)}%</td>
                <td className="ev-pri">{a.decision?.replace(/_/g, ' ') ?? '—'}</td>
                <td style={{ maxWidth: 360 }}>{a.action ?? '—'}</td>
                <td>{a.owner ?? '—'}</td>
              </tr>
            ))}
            {!payload && (
              <tr>
                <td colSpan={8}>
                  <div className="skel skel-line" />
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}