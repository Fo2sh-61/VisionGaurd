import { useEffect } from 'react';
import { Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { TABS, type TabId } from './navigation';
import { useAuth } from './AuthContext';

function tabFor(pathname: string): TabId {
  if (pathname.startsWith('/tool') || pathname.startsWith('/tools')) return 'tools';
  if (pathname.startsWith('/people')) return 'people';
  if (pathname.startsWith('/system')) return 'system';
  if (pathname.startsWith('/account')) return 'account';
  return 'home';
}

export function AppShell() {
  const { account } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    document.querySelector('.app__content')?.scrollTo(0, 0);
  }, [location.pathname]);

  if (!account) return <Navigate to="/login" replace />;

  const active = tabFor(location.pathname);

  return (
    <div className="app">
      <div className="app__content">
        <Outlet />
      </div>

      <nav className="tabbar">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`tabbar__item ${active === tab.id ? 'tabbar__item--active' : ''}`}
            onClick={() => navigate(tab.path)}
          >
            <svg width="22" height="22" viewBox="0 0 18 18" fill="none">
              <path
                d={tab.icon}
                stroke={active === tab.id ? 'var(--ac)' : 'var(--tx3)'}
                strokeWidth={active === tab.id ? 2 : 1.6}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            <span className="tabbar__label">{tab.label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
