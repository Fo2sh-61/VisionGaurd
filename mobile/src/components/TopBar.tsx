import { useNavigate } from 'react-router-dom';
import { useAccount } from '@/app/AuthContext';
import { useT } from '@/app/LanguageContext';
import { useSite } from '@/app/SiteContext';
import { useAlertFeed } from '@/app/useAlertFeed';
import { Icon } from './Icon';
import { Logo } from './Logo';

/** The top of every tab: who the product is, whether the cameras are up, the
 *  alert bell, and who is signed in (spec 015, P13-FR-043).
 *
 *  The camera sentence and its colour are the console's top bar's, word for
 *  word (`web/src/components/TopBar.tsx`): before the first answer it says it
 *  is checking, and with the engine gone it says so - never a zero that reads
 *  as every camera being down.
 *
 *  The bell's number comes from `useAlertFeed`, the same hook the console's
 *  bell reads, so the two apps count the same things. Tapping it opens the
 *  phone's alerts screen, which is where "seen" happens. */
export function TopBar() {
  const t = useT();
  const account = useAccount();
  const navigate = useNavigate();
  const { site, error } = useSite();
  const { marker, label, rings, line } = useAlertFeed(false);

  const online = site?.camerasOnline ?? 0;
  const total = site?.camerasTotal ?? 0;
  const allWell = site !== null && online === total;
  // The console uses `--bd` here, which the palette never defined, so its
  // unreachable state falls back to the text colour. The phone says it in red.
  const color = error ? 'var(--rd)' : allWell ? 'var(--ac)' : 'var(--am)';
  const cameraLabel = error
    ? t('topbar.engineUnreachable')
    : !site
      ? t('topbar.checkingCameras')
      : allWell
        ? t('topbar.allCamerasUp', { total })
        : t('topbar.someCamerasUp', { online, total });

  return (
    <header className="topbar">
      <div className="topbar__brand">
        <Logo size={34} />
        <div style={{ minWidth: 0 }}>
          <div className="topbar__name">VisionGuard</div>
          <div className="topbar__status" style={{ color }} role="status">
            <span className="dot" style={{ background: color }} aria-hidden="true" />
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{cameraLabel}</span>
          </div>
        </div>
      </div>

      <button
        type="button"
        className="iconbtn"
        aria-label={label}
        title={line.title}
        onClick={() => navigate('/alerts')}
      >
        <span key={rings} className={rings > 0 ? 'bell-ring' : undefined} style={{ display: 'inline-flex' }}>
          <Icon name="bell" size={22} />
        </span>
        {marker && (
          <span className="iconbtn__marker" style={{ background: marker.color }}>{marker.text}</span>
        )}
      </button>

      <button
        type="button"
        className="initials"
        aria-label={`${account.name} · ${t(account.role === 'admin' ? 'role.admin' : 'role.it')}`}
        onClick={() => navigate('/more')}
      >
        <span aria-hidden="true">{account.initials}</span>
      </button>
    </header>
  );
}
