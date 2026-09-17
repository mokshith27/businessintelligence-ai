import { useState } from 'react';
import { api, type EventNarrativePayload, type NarrativeTelemetry } from '../lib/api';
import { renderStory, fmtUsd } from '../lib/format';

export function Narratives() {
  const [payload, setPayload] = useState<EventNarrativePayload | null>(null);
  const [persona, setPersona] = useState<'executive' | 'operations'>('executive');
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [eventId, setEventId] = useState('66');

  async function generate() {
    const id = Number(eventId);
    if (!Number.isFinite(id)) {
      setErr('Enter a numeric event id.');
      return;
    }
    setErr(null);
    setLoading(true);
    setPayload(null);
    try {
      const result = await api.eventNarrative(id);
      setPayload(result);
      setPersona('executive');
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Narrative generation failed.');
    } finally {
      setLoading(false);
    }
  }

  const active = payload ? (persona === 'executive' ? payload.executive : payload.operations) : null;

  return (
    <>
      <div className="main-header">
        <h1>Narratives</h1>
        <p>
          Evidence-grounded stories generated on demand. Every quantitative claim is checked by the grounding validator
          before the narrative is accepted.
        </p>
      </div>

      <div className="panel" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <label htmlFor="event-id" style={{ fontWeight: 700, fontSize: 14 }}>
            Event id
          </label>
          <input
            id="event-id"
            value={eventId}
            onChange={(e) => setEventId(e.target.value)}
            style={{
              width: 110,
              padding: '9px 12px',
              borderRadius: 8,
              border: '1px solid var(--border)',
              background: 'var(--bg-soft)',
              color: 'var(--text)',
            }}
          />
          <button className="btn btn-primary" onClick={generate} disabled={loading}>
            {loading ? 'Generating…' : 'Generate narratives'}
          </button>
          <span style={{ color: 'var(--muted)', fontSize: 13 }}>
            Runs the investigation, prompts the LLM and validates the output. May take up to ~30s.
          </span>
        </div>
        {err && <div className="err-note">{err}</div>}
      </div>

      {payload && (
        <>
          <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
            <button
              className={`btn btn-sm ${persona === 'executive' ? 'btn-primary' : 'btn-ghost'}`}
              onClick={() => setPersona('executive')}
            >
              Executive
            </button>
            <button
              className={`btn btn-sm ${persona === 'operations' ? 'btn-primary' : 'btn-ghost'}`}
              onClick={() => setPersona('operations')}
            >
              Operations
            </button>
            <span
              className={`status-chip ${
                (persona === 'executive' ? payload.validation.executive_passed : payload.validation.operations_passed)
                  ? 'st-supported'
                  : 'st-abstain'
              }`}
              style={{ alignSelf: 'center', marginLeft: 8 }}
            >
              {(persona === 'executive' ? payload.validation.executive_passed : payload.validation.operations_passed)
                ? 'VALIDATOR PASSED'
                : 'VALIDATOR REJECTED'}
            </span>
          </div>

          <div className="panel">
            <div className="story" dangerouslySetInnerHTML={{ __html: renderStory(active?.story ?? '') }} />
          </div>

          <div className="panel" style={{ marginTop: 14 }}>
            <h3>LLM telemetry · {persona}</h3>
            <TelemetryRows t={active?.telemetry} />
          </div>
        </>
      )}

      {loading && (
        <div className="panel">
          <div className="skel skel-line" style={{ width: '40%' }} />
          <div className="skel skel-block" />
          <div className="skel skel-block" />
        </div>
      )}
    </>
  );
}

function TelemetryRows({ t }: { t?: NarrativeTelemetry }) {
  if (!t) return <div className="empty">No telemetry available.</div>;
  const rows: Array<[string, string]> = [
    ['Model', String(t.model ?? '—')],
    ['Latency', t.latency_ms != null ? `${Math.round(t.latency_ms)} ms` : '—'],
    ['Prompt tokens', String(t.prompt_tokens ?? '—')],
    ['Completion tokens', String(t.completion_tokens ?? '—')],
    ['Model calls', String(t.model_calls ?? '—')],
    ['Estimated cost', t.estimated_cost_usd != null ? fmtUsd(t.estimated_cost_usd) : '—'],
  ];
  return (
    <>
      {rows.map(([k, v]) => (
        <div className="kv" key={k}>
          <span className="k">{k}</span>
          <span className="v">{v}</span>
        </div>
      ))}
    </>
  );
}