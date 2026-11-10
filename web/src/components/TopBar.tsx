import { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAccount, useAuth } from '@/app/AuthContext';
import { useLanguage } from '@/app/LanguageContext';
import { useSite } from '@/app/SiteContext';
import { useTheme } from '@/app/ThemeContext';
import { LANGUAGES } from '@/i18n';
import { AlertBell } from './AlertBell';

/** The name and avatar are a button now: Health, Settings, Accounts (admin),
 *  language, theme and Sign out (spec 022 FR-106). Accounts is here and not in
 *  the sidebar on purpose. The menu closes the way the alert bell does: on
 *  Escape, on a click outside, and when the page changes. */
function UserMenu() {
  const account = useAccount();
  const { signOut } = useAuth();
  const { language, setLanguage, t } = useLanguage();
  const { dark, toggle } = useTheme();
  const navigate = useNavigate();
  const { key: visit } = useLocation();

  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  useEffect(() => setOpen(false), [visit]);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setOpen(false);
      button.current?.focus();
    };
    document.addEventListener('pointerdown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  function go(path: string) {
    setOpen(false);
    navigate(path);
  }

  return (
    <div ref={root} className="usermenu">
      <button
        ref={button}
        type="button"
        className="usermenu__button"
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={t('menu.open')}
        onClick={() => setOpen((v) => !v)}
      >
        <span style={{ textAlign: 'end' }}>
          <span style={{ display: 'block', fontSize: 13, fontWeight: 600, lineHeight: 1.2 }}>
            {account.name}
          </span>
          <span style={{ display: 'block', fontSize: 11.5, color: 'var(--tx3)' }}>
            {t(account.role === 'admin' ? 'role.admin' : 'role.it')}
          </span>
        </span>
        <span className="avatar">{account.initials}</span>
      </button>

      {open && (
        <div className="usermenu__panel" role="menu" aria-label={t('menu.open')}>
          <button type="button" role="menuitem" className="usermenu__item" onClick={() => go('/system')}>
            {t('nav.system.label')}
          </button>
          <button type="button" role="menuitem" className="usermenu__item" onClick={() => go('/settings')}>
            {t('nav.settings.label')}
          </button>
          {account.role === 'admin' && (
            <button type="button" role="menuitem" className="usermenu__item" onClick={() => go('/users')}>
              {t('nav.users.label')}
            </button>
          )}

          <div className="usermenu__sep" />
          <div className="usermenu__row">
            <span>{t('settings.language')}</span>
            <span style={{ display: 'flex', gap: 6 }}>
              {LANGUAGES.map((k) => (
                <button
                  key={k}
                  type="button"
                  className={`chip-btn ${language === k ? 'chip-btn--on' : 'chip-btn--off'}`}
                  aria-pressed={language === k}
                  onClick={() => setLanguage(k)}
                >
                  {t(`settings.language.${k}`)}
                </button>
              ))}
            </span>
          </div>
          <button type="button" role="menuitem" className="usermenu__item" onClick={toggle}>
            {t(dark ? 'menu.theme.light' : 'menu.theme.dark')}
          </button>

          <div className="usermenu__sep" />
          <button
            type="button"
            role="menuitem"
            className="usermenu__item usermenu__item--danger"
            onClick={() => { setOpen(false); void signOut(); }}
          >
            {t('action.signOut')}
          </button>
        </div>
      )}
    </div>
  );
}

export function TopBar() {
  const { site, error, todayLabel } = useSite();
  const { t } = useLanguage();

  const online = site?.camerasOnline ?? 0;
  const total = site?.camerasTotal ?? 0;
  // Before the first response, and when the engine is unreachable, say so
  // rather than showing a zero that reads like every camera is down.
  const allWell = site !== null && online === total;
  const color = error ? 'var(--bd)' : allWell ? 'var(--ac)' : 'var(--am)';

  const cameraLabel = error
    ? t('topbar.engineUnreachable')
    : !site
      ? t('topbar.checkingCameras')
      : allWell
        ? t('topbar.allCamerasUp', { total })
        : t('topbar.someCamerasUp', { online, total });

  return (
    <header className="topbar">
      <div style={{ fontSize: 13, color: 'var(--tx3)' }}>{todayLabel}</div>

      <div className="topbar__right">
        {/* Opens System health, where the cameras are listed. */}
        <Link
          to="/system"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            fontSize: 12.5,
            fontWeight: 600,
            color,
            whiteSpace: 'nowrap',
            flexShrink: 0,
          }}
        >
          <span className="glyph" style={{ background: color }}>
            {allWell ? '✓' : '!'}
          </span>
          {cameraLabel}
        </Link>

        <AlertBell />

        <UserMenu />
      </div>
    </header>
  );
}
