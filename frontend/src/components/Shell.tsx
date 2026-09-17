import { Link, NavLink } from 'react-router-dom';

export function Navbar({
  user,
  onLogout,
}: {
  user: { full_name: string | null; username: string; role: string } | null;
  onLogout: () => void;
}) {
  return (
    <nav className="nav">
      <div className="app-shell nav-inner">
        <Link to="/" className="brand">
          <span className="brand-mark">B</span>
          BusinessIntelligence<span className="brand-dot">.ai</span>
        </Link>
        <div className="nav-links">
          <NavLink to="/" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`} end>
            Overview
          </NavLink>
          {user ? (
            <NavLink to="/dashboard" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
              Dashboard
            </NavLink>
          ) : null}
          <Link to="/dashboard" className="nav-cta">
            {user ? 'Open console' : 'Launch console'}
          </Link>
          {user ? (
            <button className="btn btn-ghost btn-sm" onClick={onLogout}>
              Sign out
            </button>
          ) : null}
        </div>
      </div>
    </nav>
  );
}

export function Footer() {
  return (
    <footer className="footer">
      <div className="app-shell footer-inner">
        <span>
          <strong style={{ color: 'var(--text)' }}>BusinessIntelligence.ai</strong> — the analytical layer determines the
          truth; the LLM explains it.
        </span>
        <span>
          <a href="/docs" target="_blank" rel="noreferrer">
            API docs
          </a>
          {' · '}
          <a href="https://github.com/mokshith27/businessintelligence-ai" target="_blank" rel="noreferrer">
            GitHub
          </a>
        </span>
      </div>
    </footer>
  );
}