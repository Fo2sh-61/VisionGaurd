import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCameras } from '@/app/CameraContext';
import { useLanguage } from '@/app/LanguageContext';
import { CameraFrame, usePageVisible } from '@/components/CameraFrame';
import { getCameraCounts } from '@/services/api';
import { describeCount, formatCount } from '@/services/format';
import type { Camera } from '@/types';

/** Every camera, grouped by area (spec 015, P13-FR-047).
 *
 *  The console has no page like this: it shows cameras inside each tool, only
 *  the ones that tool uses. The phone's Cameras tab is built only from what
 *  those grids already read - the roster (`useCameras`, polled by
 *  CameraProvider) and the headcounts (`getCameraCounts`, at CamGrid's rate) -
 *  so it adds no new kind of request.
 *
 *  Honesty:
 *  - Tiles draw no boxes. Boxes carry names on some cameras, and a grid of
 *    every camera is not a screen that asked who anybody is. Boxes are one tap
 *    away, on the camera's own screen, one feature at a time.
 *  - A camera with no picture says so, with the time of its last picture;
 *    it is never shown as live. The roster does not say whether a reconnect
 *    is being tried, so neither does this screen.
 *  - A count the engine does not have is "—", never 0. */

type Filter = 'all' | 'live' | 'offline';

/** CamGrid's headcount cadence. */
const COUNT_REFRESH_MS = 1_000;

export function Cameras() {
  const { t, language } = useLanguage();
  const navigate = useNavigate();
  const { cameras, degraded, loading } = useCameras();
  const [filter, setFilter] = useState<Filter>('all');
  const [counts, setCounts] = useState<Record<string, number | null>>({});
  const pageVisible = usePageVisible();

  // Not while the phone's screen is off or the app is in the background:
  // nobody can read a number then, and the first poll back brings it up to
  // date.
  useEffect(() => {
    if (!pageVisible) return;
    let cancelled = false;
    const poll = () => {
      getCameraCounts()
        .then((next) => {
          if (!cancelled) setCounts(next);
        })
        .catch(() => {
          /* a dropped poll leaves the previous numbers up */
        });
    };
    poll();
    const timer = setInterval(poll, COUNT_REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [pageVisible]);

  const liveCount = cameras.filter((c) => !c.offline).length;
  const offlineCount = cameras.length - liveCount;

  const shown = cameras.filter((c) =>
    filter === 'all' ? true : filter === 'live' ? !c.offline : c.offline);

  // Areas in the order their first camera appears, so the list does not
  // reshuffle itself between polls.
  const areas = useMemo(() => {
    const order: string[] = [];
    for (const cam of shown) {
      const area = cam.area || '';
      if (!order.includes(area)) order.push(area);
    }
    return order;
  }, [shown]);

  const chip = (id: Filter, label: string, n: number, dot?: string) => (
    <button
      type="button"
      className={filter === id ? 'chip chip--on' : 'chip'}
      aria-pressed={filter === id}
      onClick={() => setFilter(id)}
    >
      {dot && <span className="dot" style={{ background: dot }} aria-hidden="true" />}
      <span>{label}</span>
      <span className="chip__n">{formatCount(n, language)}</span>
    </button>
  );

  return (
    <>
      <div>
        <h1 className="h1">{t('nav.tab.cameras')}</h1>
        <p className="lead">{t('phone.cameras.lead')}</p>
      </div>

      {degraded && (
        <div className="notice notice--amber" role="status">{t('camera.lastKnown')}</div>
      )}

      {cameras.length > 0 && (
        <div className="chips">
          {chip('all', t('phone.filter.all'), cameras.length)}
          {chip('live', t('phone.filter.live'), liveCount, 'var(--ac)')}
          {chip('offline', t('phone.filter.offline'), offlineCount, 'var(--rd)')}
        </div>
      )}

      {!loading && cameras.length === 0 && (
        <div className="card empty">{t('camera.noneConfigured')}</div>
      )}
      {cameras.length > 0 && shown.length === 0 && (
        <div className="card empty">{t('phone.filter.none')}</div>
      )}

      {areas.map((area) => (
        <section key={area || '—'} className="stack" aria-label={area || t('camera.unassignedArea')}>
          <div className="sechead">
            <h2 className="sechead__title" style={{ margin: 0 }}>{area || t('camera.unassignedArea')}</h2>
          </div>
          <div className="camgrid-phone">
            {shown.filter((c) => (c.area || '') === area).map((cam) => (
              <Tile
                key={cam.id}
                camera={cam}
                detail={cam.offline
                  ? t('phone.camera.lastPicture', { time: cam.time ?? '—' })
                  : describeCount(counts[cam.id], cam.status, language)}
                onOpen={() => navigate(`/cameras/${encodeURIComponent(cam.id)}`)}
              />
            ))}
          </div>
        </section>
      ))}
    </>
  );
}

/** One camera. Only the tiles on screen move - a long roster scrolled
 *  past costs nothing - and they share the screen's picture budget
 *  (`tileRefreshMs`), so however many cameras the site has, this page costs
 *  what the few in view cost. */
function Tile({ camera, detail, onOpen }: {
  camera: Camera;
  detail: string;
  onOpen: () => void;
}) {
  return (
    <button type="button" className="camtile" onClick={onOpen}>
      <CameraFrame camera={camera} detections={false} />
      <span className="stack stack--tight" style={{ gap: 1, padding: '6px 2px 0' }}>
        <span className="camtile__name">{camera.name}</span>
        <span
          className="li__sub"
          style={camera.offline ? { color: 'var(--rd)', fontWeight: 600 } : undefined}
        >
          {detail}
        </span>
      </span>
    </button>
  );
}
