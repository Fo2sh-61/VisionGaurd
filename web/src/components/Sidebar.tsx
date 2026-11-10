import { NavLink } from 'react-router-dom';
import { useAccount } from '@/app/AuthContext';
import { useLanguage } from '@/app/LanguageContext';
import { HOME_ICON, navSectionsFor } from '@/app/navigation';
import { useSiteName } from '@/app/SiteContext';
import { useAlertFeed } from '@/app/useAlertFeed';
import { useNavBadges } from '@/app/useNavBadges';
import { formatCount } from '@/services/format';
import type { ToolId } from '@/types';
import { Logo } from './Logo';

/* The card at the foot says what the bell says, in words: "Site is calm" only
   when the alert feed answered, is running and is empty; otherwise it says
   what it cannot know (`useAlertFeed` decides, one rule for both). Sign out
   lives in the user menu in the top bar now. */

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
  const { language, t } = useLanguage();
  const badges = useNavBadges();
  const { feed, line, items } = useAlertFeed(false);
  const calm = feed === 'ready' && items.length === 0;

  // The number says how many; the tooltip and screen readers say of what.
  const badgeTitle = (id: ToolId, count: number) =>
    id === 'attendance' ? t('nav.badge.attendance', { count: formatCount(count, language) })
      : id === 'vehicles' ? t('nav.badge.vehicles', { count: formatCount(count, language) })
        : id === 'intrusion' ? t('nav.badge.zones', { count: formatCount(count, language) })
          : id === 'stations' ? t('nav.badge.stations', { count: formatCount(count, language) })
            : undefined;

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    isActive ? 'navlink navlink--active' : 'navlink';

  return (
    <nav className="sidebar">
      <div className="sidebar__brand">
        <Logo />
        <div>
          <div style={{ fontWeight: 700, fontSize: 15, letterSpacing: '-.01em' }}>VisionGuard</div>
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
            {group.section === 'system' && (
              <div className="sidebar__section">{t('nav.section.system')}</div>
            )}
            {group.items.map((item) => {
              const count = badges[item.id];
              return (
                <NavLink key={item.id} to={item.path} className={linkClass}>
                  {({ isActive }) => (
                    <>
                      <NavIcon d={item.icon} active={isActive} />
                      <span>{t(`nav.${item.id}.label`)}</span>
                      {count !== undefined && count > 0 && (
                        <span className="navlink__badge" title={badgeTitle(item.id, count)}>
                          {formatCount(count, language)}
                        </span>
                      )}
                    </>
                  )}
                </NavLink>
              );
            })}
          </div>
        ))}
      </div>

      <div style={{ flex: 1 }} />

      <div className="sidebar__status">
        <div className="sidebar__status-title" style={{ color: calm ? 'var(--ac)' : line.color }}>
          {calm
            ? <span className="dot" style={{ background: 'var(--ac)' }} />
            : line.glyph && <span className="glyph" style={{ background: line.color }}>{line.glyph}</span>}
          {calm ? t('sidebar.calm') : line.title}
        </div>
        {calm && <div className="sidebar__status-sub">{t('sidebar.calmSub')}</div>}
      </div>
    </nav>
  );
}
