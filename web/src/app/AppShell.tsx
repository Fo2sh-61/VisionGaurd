import { useEffect } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { DevSignInBanner } from '@/components/DevSignInBanner'; // DEV-SIGNIN
import { Sidebar } from '@/components/Sidebar';
import { TopBar } from '@/components/TopBar';
import { useAuth } from './AuthContext';
import { ToastProvider } from './ToastContext';

export function AppShell() {
  const { account } = useAuth();
  const location = useLocation();

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [location.pathname]);

  if (!account) return <Navigate to="/login" replace />;

  return (
    <ToastProvider>
      <div className="shell">
        <Sidebar />
        <div className="shell__main">
          <DevSignInBanner /> {/* DEV-SIGNIN */}
          <TopBar />
          <main className="shell__body">
            <div className="page">
              <Outlet />
            </div>
          </main>
        </div>
      </div>
    </ToastProvider>
  );
}
