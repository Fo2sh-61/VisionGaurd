import { useAccount } from '@/app/AuthContext';
import { useSite } from '@/app/SiteContext';

export function TopBar() {
  const account = useAccount();
  const { site, error, todayLabel } = useSite();

  const online = site?.camerasOnline ?? 0;
  const total = site?.camerasTotal ?? 0;
  // Before the first response, and when the engine is unreachable, say so
  // rather than showing a zero that reads like every camera is down.
  const allWell = site !== null && online === total;
  const color = error ? 'var(--bd)' : allWell ? 'var(--ac)' : 'var(--am)';

  const cameraLabel = error
    ? 'Engine unreachable'
    : !site
      ? 'Checking cameras…'
      : allWell
        ? `All ${total} cameras up`
        : `${online} of ${total} cameras up`;

  return (
    <header className="topbar">
      <div style={{ fontSize: 13, color: 'var(--tx3)' }}>{todayLabel}</div>

      <div className="topbar__right">
        <span
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
        </span>

        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.2 }}>{account.name}</div>
            <div style={{ fontSize: 11.5, color: 'var(--tx3)' }}>
              {account.role === 'admin' ? 'Administrator' : 'IT'}
            </div>
          </div>
          <div className="avatar">{account.initials}</div>
        </div>
      </div>
    </header>
  );
}
