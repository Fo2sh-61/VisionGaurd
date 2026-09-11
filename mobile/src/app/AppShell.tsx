import { useEffect } from 'react';
import { Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { DevSignInBanner } from '@/components/DevSignInBanner'; // DEV-SIGNIN
import { TABS, tabFor } from './tabs';
import { useAuth } from './AuthContext';
import { useT } from './LanguageContext';

/** The phone's chrome: a scrolling screen with a tab bar under it.
 *
 *  Deliberately not the console's shell. `web/src/app/AppShell.tsx` puts a
 *  sidebar beside a top bar; neither fits a hand, and the phone's design
 *  replaced both with five tabs long before this app was real.
 *
 *  What it shares with the console is the part that matters: it renders
 *  `<Outlet/>` and nothing else. Every page below it is a byte copy of the
 *  console's page and knows nothing about which shell it is inside — which is
 *  the whole reason the copy was cheap.
 */
export function AppShell() {
  const { account } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const t = useT();

  // The console scrolls the window; the phone scrolls a div inside a fixed
  // viewport, so that is what has to be sent back to the top on a new screen.
  // Without this, opening a person from halfway down the directory lands you
  // halfway down their history.
  useEffect(() => {
    document.querySelector('.app__content')?.scrollTo(0, 0);
  }, [location.pathname]);

  if (!account) return <Navigate to="/login" replace />;

  const active = tabFor(location.pathname);

  return (
    <div className="app">
      <DevSignInBanner /> {/* DEV-SIGNIN */}
      <div className="app__content">
        <Outlet />
      </div>

      {/* The bar itself needs no `dir` handling: it is a flex row, and the
          document's `dir` — set by LanguageContext — reverses flex order for
          free. Setting it here as well would reverse it twice and put Arabic
          back in English order. */}
      <nav className="tabbar">
        {TABS.map((tab) => {
          const on = active === tab.id;
          const label = t(tab.label);
          return (
            <button
              key={tab.id}
              type="button"
              aria-current={on ? 'page' : undefined}
              aria-label={label}
              className={`tabbar__item ${on ? 'tabbar__item--active' : ''}`}
              onClick={() => navigate(tab.path)}
            >
              <svg width="22" height="22" viewBox="0 0 18 18" fill="none" aria-hidden="true">
                <path
                  d={tab.icon}
                  stroke={on ? 'var(--ac)' : 'var(--tx3)'}
                  strokeWidth={on ? 2 : 1.6}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              <span className="tabbar__label">{label}</span>
            </button>
          );
        })}
      </nav>
    </div>
  );
}
