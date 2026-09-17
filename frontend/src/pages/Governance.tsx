import { useEffect, useState } from 'react';
import { api, type SecurityTestPayload } from '../lib/api';

export function Governance() {
  const [security, setSecurity] = useState<SecurityTestPayload | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api
      .securityTest()
      .then(setSecurity)
      .catch((e) => setErr(e.message));
  }, []);

  return (
    <>
      <div className="main-header">
        <h1>Governance & security</h1>
        <p>
          What each role can and cannot see — self-audited via <code style={{ color: 'var(--accent-2)' }}>GET /api/security/test</code>.
        </p>
      </div>

      {err && <div className="auth-warn">{err}</div>}

      <div className="panel">
        <h3>Security model · {security?.security_model ?? '…'}</h3>
        {security ? (
          Object.entries(security.roles).map(([role, def]) => (
            <div key={role} style={{ marginBottom: 22 }}>
              <div className="drivers-head">
                <span style={{ textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--accent-2)', fontWeight: 800, fontSize: 12 }}>
                  {role}
                </span>
              </div>
              <div className="roi-chips" style={{ marginTop: 0 }}>
                {def.visible_sections.map((s) => (
                  <span className="chip" key={s}>
                    ✓ {s.replace(/_/g, ' ')}
                  </span>
                ))}
              </div>
              <div style={{ marginTop: 10, fontSize: 13, color: 'var(--muted)' }}>Restricted fields:</div>
              <div className="roi-chips" style={{ marginTop: 6 }}>
                {def.restricted_fields.map((f) => (
                  <span className="chip" key={f} style={{ color: 'var(--bad)' }}>
                    ✕ {f.replace(/_/g, ' ')}
                  </span>
                ))}
              </div>
            </div>
          ))
        ) : (
          <>
            <div className="skel skel-line" />
            <div className="skel skel-line" style={{ width: '70%' }} />
          </>
        )}
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <h3>LLM governance policy</h3>
        <div className="kv">
          <span className="k">Quantitative truth source</span>
          <span className="v">deterministic analytical layer</span>
        </div>
        <div className="kv">
          <span className="k">Allowed LLM tasks</span>
          <span className="v">narrative synthesis · persona adaptation · explanation · uncertainty wording</span>
        </div>
        <div className="kv">
          <span className="k">Forbidden LLM tasks</span>
          <span className="v">calculating KPIs · inventing drivers · overriding confidence · creating actions</span>
        </div>
      </div>
    </>
  );
}