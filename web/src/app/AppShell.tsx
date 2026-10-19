import { useEffect } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { Sidebar } from '@/components/Sidebar';
import { TopBar } from '@/components/TopBar';
import { useAuth } from './AuthContext';
import { useT } from './LanguageContext';
import { useSiteReachable } from './useConnection';

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
            <SiteUnreachable />
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

/** Spec 020: said at the top of every page while the site cannot be reached,
 *  and gone with the next answer. It does not guess why (P10-FR-112): away
 *  from the factory that is usually the VPN, on site the network. */
function SiteUnreachable() {
  const t = useT();
  const reachable = useSiteReachable();
  if (reachable) return null;
  return (
    <div
      role="status"
      style={{
        padding: '11px 14px', borderRadius: 10, marginBottom: 14,
        background: 'var(--rd-bg)', color: 'var(--rd)',
        fontSize: 13.5, lineHeight: 1.45, fontWeight: 600,
      }}
    >
      {t('state.siteUnreachable')}
    </div>
  );
}
