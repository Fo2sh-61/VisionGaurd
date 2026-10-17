import { useEffect } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { Sidebar } from '@/components/Sidebar';
import { TopBar } from '@/components/TopBar';
import { useAuth } from './AuthContext';

export function AppShell() {
  const { account } = useAuth();
  const location = useLocation();

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [location.pathname]);

  if (!account) return <Navigate to="/login" replace />;

  return (
    <div className="shell">
      <Sidebar />
      <div className="shell__main">
        <TopBar />
        <main className="shell__body">
          <div className="page">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
