import { NavLink } from 'react-router-dom';
import { useAccount, useAuth } from '@/app/AuthContext';
import { useCapability, type Capability } from '@/app/CapabilityContext';
import { useT, type Translate } from '@/app/LanguageContext';
import { HOME_ICON, navSectionsFor } from '@/app/navigation';
import { useSite, useSiteName } from '@/app/SiteContext';
import { useAsync, type Async } from '@/app/useAsync';
import { getAttention } from '@/services/api';
import type { AttentionItem } from '@/services/wire';
import { Logo } from './Logo';

/** How often the sidebar asks whether anything is waiting. Home's list polls
 *  at the same pace, so the two are never far apart. */
const CHECK_MS = 15_000;

interface StatusLine {
  color: string;
  glyph: string | null;
  title: string;
  lead?: string;
  /** The engine's own reason, on hover, when it gave one. */
  hint?: string;
}

/** What the foot of the sidebar says: only what the engine has told us.
 *
 *  It used to read "Campus is calm" whatever was happening — with a knife
 *  detection waiting for a human, with the engine unreachable, and on an
 *  engine whose alert feed did not exist yet. So "Nothing needs attention"
 *  now needs three things at once: the engine answered, its feed is running,
 *  and the feed is empty. Every other moment gets its own words. */
function statusLine(
  t: Translate,
  engineDown: boolean,
  feedState: Capability | null,
  feed: Async<AttentionItem[]>,
): StatusLine {
  if (engineDown) {
    return { color: 'var(--rd)', glyph: '!', title: t('topbar.engineUnreachable') };
  }
  if (feed.error) {
    return { color: 'var(--am)', glyph: '!', title: t('sidebar.failed') };
  }
  if (feed.loading || !feedState) {
    return { color: 'var(--tx3)', glyph: null, title: t('sidebar.checking') };
  }
  // An empty list from a feed that is not running is not an all-clear. The
  // live engine answers `[]` until its alert feed exists.
  if (feedState.state === 'unavailable') {
    return {
      color: 'var(--am)',
      glyph: '!',
      title: t('sidebar.off'),
      lead: t('sidebar.offLead'),
      hint: feedState.reason ?? undefined,
    };
  }
  const lead = feedState.state === 'demo' ? t('state.demoData') : undefined;
  const waiting = feed.data;
  if (waiting.length === 0) {
    return { color: 'var(--ac)', glyph: '✓', title: t('sidebar.calm'), lead };
  }
  return {
    color: waiting.some((i) => i.severity === 'critical') ? 'var(--rd)' : 'var(--am)',
    glyph: '!',
    title: waiting.length === 1
      ? t('sidebar.waitingOne')
      : t('sidebar.waiting', { count: waiting.length }),
    lead,
  };
}

/** Asks for itself rather than through `useAttention`, which turns items into
 *  Home's cards; the sidebar needs only how many there are and how bad. */
function AlertStatus() {
  const t = useT();
  const { error } = useSite();
  const feedState = useCapability('attention');
  const feed = useAsync(
    // Acknowledged items stay in the history, but somebody has dealt with them.
    () => getAttention().then((items) => items.filter((i) => !i.acknowledged)),
    [],
    [],
    CHECK_MS,
  );
  const line = statusLine(t, error !== null, feedState, feed);

  return (
    <div className="sidebar__status" role="status" title={line.hint}>
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          gap: 7,
          fontSize: 12.5,
          fontWeight: 600,
          color: line.color,
        }}
      >
        {line.glyph && (
          <span className="glyph" style={{ background: line.color }}>
            {line.glyph}
          </span>
        )}
        {line.title}
      </div>
      {line.lead && (
        <div style={{ fontSize: 12, color: 'var(--tx3)', marginTop: 3 }}>{line.lead}</div>
      )}
    </div>
  );
}

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

      <AlertStatus />

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
