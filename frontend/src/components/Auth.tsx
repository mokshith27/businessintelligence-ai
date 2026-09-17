import { useEffect, useState, type ReactNode } from 'react';
import { api, getToken, setToken, clearToken, type AuthUser, ApiError } from '../lib/api';

interface AuthState {
  user: AuthUser | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

export function useAuth(): AuthState {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    // Restore session from a persisted JWT, if any.
    if (getToken()) {
      api
        .me()
        .then((me) => {
          if (!cancelled) {
            setUser({ username: me.username, role: me.role, full_name: me.full_name });
          }
        })
        .catch(() => {
          clearToken();
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    } else {
      setLoading(false);
    }
    return () => {
      cancelled = true;
    };
  }, []);

  async function login(username: string, password: string): Promise<void> {
    const resp = await api.login(username, password).catch((err) => {
      if (err instanceof ApiError && err.status === 401) {
        throw new Error('Invalid username or password.');
      }
      throw new Error('Could not reach the API. Is the backend running?');
    });
    setToken(resp.access_token);
    setUser(resp.user);
  }

  function logout(): void {
    clearToken();
    setUser(null);
  }

  return { user, loading, login, logout };
}

export function RequireAuth({
  user,
  loading,
  login,
  children,
}: {
  user: AuthUser | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  children: ReactNode;
}) {
  if (loading) {
    return (
      <div className="login-wrap">
        <div style={{ width: 320 }}>
          <div className="skel skel-line" style={{ width: '60%' }} />
          <div className="skel skel-block" />
          <div className="skel skel-line" style={{ width: '40%' }} />
        </div>
      </div>
    );
  }
  if (!user) return <LoginScreen login={login} />;
  return <>{children}</>;
}

function LoginScreen({ login }: { login: (username: string, password: string) => Promise<void> }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(u: string, p: string) {
    setError(null);
    setBusy(true);
    try {
      await login(u, p);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <div className="login-card">
        <h1>Sign in</h1>
        <p className="login-sub">
          Role-based decision intelligence. Your role is derived from the signed JWT — not a selector.
        </p>
        {error && <div className="login-error">{error}</div>}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit(username, password);
          }}
        >
          <div className="login-field">
            <label htmlFor="username">Username</label>
            <input
              id="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="e.g. maria.exec"
              autoComplete="username"
            />
          </div>
          <div className="login-field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="current-password"
            />
          </div>
          <button className="btn btn-primary login-btn" type="submit" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
        <div className="login-demo">
          <div className="login-demo-label">One-click demo users</div>
          <div className="login-demo-btns">
            <button className="demo-btn" disabled={busy} onClick={() => submit('maria.exec', 'demo-exec-2026')}>
              <span>maria.exec</span>
              <span className="role">Executive</span>
            </button>
            <button className="demo-btn" disabled={busy} onClick={() => submit('joao.ops', 'demo-ops-2026')}>
              <span>joao.ops</span>
              <span className="role">Operations</span>
            </button>
            <button className="demo-btn" disabled={busy} onClick={() => submit('ana.analyst', 'demo-analyst-2026')}>
              <span>ana.analyst</span>
              <span className="role">Analyst</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}