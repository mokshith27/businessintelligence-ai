import { NavLink, useNavigate } from 'react-router-dom';
import type { ReactNode } from 'react';
import type { AuthUser } from '../lib/api';

const NAV = [
  { to: '/dashboard', label: 'Overview', ico: '◆' },
  { to: '/dashboard/events', label: 'Events', ico: '⚡' },
  { to: '/dashboard/narratives', label: 'Narratives', ico: '✎' },
  { to: '/dashboard/actions', label: 'Actions', ico: '☑' },
  { to: '/dashboard/governance', label: 'Governance', ico: '⛨' },
];

export function Layout({
  user,
  onLogout,
  children,
}: {
  user: AuthUser;
  onLogout: () => void;
  children: ReactNode;
}) {
  const navigate = useNavigate();

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="sidebar-title">Console</div>
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/dashboard'}
            className={({ isActive }) => `side-link${isActive ? ' active' : ''}`}
          >
            <span className="ico">{item.ico}</span>
            {item.label}
          </NavLink>
        ))}
        <div className="user-card">
          <div className="user-name">{user.full_name ?? user.username}</div>
          <div className="user-role">{user.role}</div>
          <button
            className="logout-btn"
            onClick={() => {
              onLogout();
              navigate('/dashboard');
            }}
          >
            Log out
          </button>
        </div>
      </aside>
      <main className="main-pane">{children}</main>
    </div>
  );
}