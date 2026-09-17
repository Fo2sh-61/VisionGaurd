import { useEffect } from 'react';
import { Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { DevSignInBanner } from '@/components/DevSignInBanner'; // DEV-SIGNIN
import { Icon } from '@/components/Icon';
import { ScreenHeader } from '@/components/ScreenHeader';
import { TopBar } from '@/components/TopBar';
import { PageChromeProvider, usePageChrome } from './PageChrome';
import { TABS, isTabRoot, screenFor, tabFor } from './tabs';
import { useAuth } from './AuthContext';
import { useT } from './LanguageContext';

/** The phone's frame: a header, a scrolling screen, and five tabs.
 *
 *  Spec 015 (phone-first redesign). A tab's own screen gets the top bar -
 *  brand, camera status, the alert bell, who is signed in. Every screen below
 *  a tab gets a back header with its title instead, so a tool always has a way
 *  back. Both sit above the scrolling area, so they stay put while it scrolls.
 *
 *  The screens themselves know nothing about which header they are under. A
 *  screen that wants its own title in the header (a camera's name) or an
 *  action there (Export) asks through `PageChrome`. */
export function AppShell() {
  const { account } = useAuth();
  if (!account) return <Navigate to="/login" replace />;
  return (
    <PageChromeProvider>
      <Frame />
    </PageChromeProvider>
  );
}

function Frame() {
  const location = useLocation();
  const navigate = useNavigate();
  const t = useT();
  const chrome = usePageChrome();

  // The phone scrolls a div inside a fixed viewport, not the window, so that
  // is what has to be sent back to the top on a new screen. Without this,
  // opening a person from halfway down the directory lands you halfway down
  // their history.
  useEffect(() => {
    document.querySelector('.app__content')?.scrollTo(0, 0);
  }, [location.pathname]);

  const root = isTabRoot(location.pathname);
  const screen = root ? null : screenFor(location.pathname);
  const active = tabFor(location.pathname);

  return (
    <div className="app">
      <DevSignInBanner /> {/* DEV-SIGNIN */}

      {root ? (
        <TopBar />
      ) : (
        <ScreenHeader
          title={chrome.title ?? (screen ? t(screen.title) : '')}
          parent={screen?.parent ?? '/'}
          action={chrome.action}
        />
      )}

      <main className="app__content">
        {/* Every screen gets the same gutter and rhythm; a screen that wants a
            picture edge to edge steps out of it with negative margins. */}
        <div className="screen">
          <Outlet />
        </div>
      </main>

      {/* The bar needs no `dir` handling: it is a grid, and the document's
          `dir` - set by LanguageContext - reverses the column order for free. */}
      <nav className="tabbar">
        {TABS.map((tab) => {
          const on = active === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              aria-current={on ? 'page' : undefined}
              className={on ? 'tabbar__item tabbar__item--active' : 'tabbar__item'}
              onClick={() => {
                // Tapping the tab you are already in goes back to its top.
                if (location.pathname !== tab.path) navigate(tab.path);
                else document.querySelector('.app__content')?.scrollTo({ top: 0, behavior: 'smooth' });
              }}
            >
              <span className="tabbar__icon">
                <Icon name={tab.icon} size={21} strokeWidth={on ? 2 : 1.7} />
              </span>
              <span className="tabbar__label">{t(tab.label)}</span>
            </button>
          );
        })}
      </nav>
    </div>
  );
}
