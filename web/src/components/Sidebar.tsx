import { NavLink } from 'react-router-dom';
import { useAccount, useAuth } from '@/app/AuthContext';
import { HOME_ICON, navSectionsFor, SECTION_LABEL } from '@/app/navigation';
import { useSiteName } from '@/app/SiteContext';
import { Logo } from './Logo';

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
              <span>Home</span>
            </>
          )}
        </NavLink>

        {navSectionsFor(account.role).map((group) => (
          <div key={group.section}>
            <div className="sidebar__section">{SECTION_LABEL[group.section]}</div>
            {group.items.map((item) => (
              <NavLink key={item.id} to={item.path} className={linkClass}>
                {({ isActive }) => (
                  <>
                    <NavIcon d={item.icon} active={isActive} />
                    <span>{item.label}</span>
                  </>
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </div>

      <div style={{ flex: 1 }} />

      <div className="sidebar__status">
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 7,
            fontSize: 12.5,
            fontWeight: 600,
            color: 'var(--ac)',
            whiteSpace: 'nowrap',
          }}
        >
          <span className="glyph" style={{ background: 'var(--ac)' }}>
            ✓
          </span>
          Campus is calm
        </div>
        <div style={{ fontSize: 12, color: 'var(--tx3)', marginTop: 3 }}>Nothing urgent right now</div>
      </div>

      <button
        type="button"
        className="linkbtn linkbtn--quiet"
        style={{ padding: '8px 10px', textAlign: 'left', borderTop: '1px solid var(--line)' }}
        onClick={signOut}
      >
        Sign out
      </button>
    </nav>
  );
}
