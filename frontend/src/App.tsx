import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Navbar, Footer } from './components/Shell';
import { Layout } from './components/Layout';
import { useAuth, RequireAuth } from './components/Auth';
import { Landing } from './pages/Landing';
import { Dashboard } from './pages/Dashboard';
import { Events } from './pages/Events';
import { Narratives } from './pages/Narratives';
import { Actions } from './pages/Actions';
import { Governance } from './pages/Governance';

// The production bundle is served by FastAPI under /app, matching the 'base' option in vite.config.ts,
// so the router is mounted on the same prefix for client-side routes to match.
const BASENAME = import.meta.env.BASE_URL.replace(/\/+$/, '') || '/';

export function App() {
  const { user, loading, login, logout } = useAuth();

  return (
    <BrowserRouter basename={BASENAME}>
      <Navbar user={user} onLogout={logout} />
      <RequireAuth user={user} loading={loading} login={login}>
        {user ? (
          <Layout user={user} onLogout={logout}>
            <Routes>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/dashboard/events" element={<Events />} />
              <Route path="/dashboard/narratives" element={<Narratives />} />
              <Route path="/dashboard/actions" element={<Actions />} />
              <Route path="/dashboard/governance" element={<Governance />} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Routes>
          </Layout>
        ) : (
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="*" element={<Landing />} />
          </Routes>
        )}
      </RequireAuth>
      <Footer />
    </BrowserRouter>
  );
}