import { NavLink } from 'react-router-dom';
import { useAccount, useAuth } from '@/app/AuthContext';
import { useT } from '@/app/LanguageContext';
import { HOME_ICON, navSectionsFor } from '@/app/navigation';
import { useSiteName } from '@/app/SiteContext';
import { Logo } from './Logo';

/* The alert status that sat at the foot of this sidebar is the bell in the
   top bar now (`AlertBell`): it said how many things needed attention and
   could not be opened. */

function NavIcon({ d, active }: { d: string; active: boolean }) {
  return (
    <svg width="17" height="17" viewBox="0 0 18 18" fill="none" style={{ flexShrink: 0 }}>
      <path
        d={d}
        stroke={active ? 'var(--ac)' : 'var(--tx3)'}
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function Sidebar() {
  const siteName = useSiteName();
  const account = useAccount();
  const { signOut } = useAuth();
  const t = useT();

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    isActive ? 'navlink navlink--active' : 'navlink';

  return (
    <nav className="sidebar">
      <div className="sidebar__brand">
        <Logo />
        <div>
          <div style={{ fontWeight: 700, fontSize: 15, letterSpacing: '-.01em' }}>VisionGuard AI</div>
          {siteName && (
            <div style={{ fontSize: 11, color: 'var(--tx3)', lineHeight: 1.2 }}>{siteName}</div>
          )}
        </div>
      </div>

      <div className="sidebar__nav">
        <NavLink to="/" end className={linkClass}>
          {({ isActive }) => (
            <>
              <NavIcon d={HOME_ICON} active={isActive} />
              <span>{t('nav.home')}</span>
            </>
          )}
        </NavLink>

        {navSectionsFor(account.role).map((group) => (
          <div key={group.section}>
            <div className="sidebar__section">{t(`nav.section.${group.section}`)}</div>
            {group.items.map((item) => (
              <NavLink key={item.id} to={item.path} className={linkClass}>
                {({ isActive }) => (
                  <>
                    <NavIcon d={item.icon} active={isActive} />
                    <span>{t(`nav.${item.id}.label`)}</span>
                  </>
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </div>

      <div style={{ flex: 1 }} />

      <button
        type="button"
        className="linkbtn linkbtn--quiet"
        style={{ padding: '8px 10px', textAlign: 'start', borderTop: '1px solid var(--line)' }}
        onClick={signOut}
      >
        {t('action.signOut')}
      </button>
    </nav>
  );
}
