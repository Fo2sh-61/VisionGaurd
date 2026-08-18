import { useEffect, useState } from 'react';
import { useCameraGrid, useCameras } from '@/app/CameraContext';
import { getCameraCounts } from '@/services/api';
import { describeCount } from '@/services/format';
import type { Camera } from '@/types';
import { CameraFrame } from './CameraFrame';
import { CameraModal } from './CameraModal';

/** How fast tiles should refresh, given how many are on screen.
 *
 *  A few tiles can be near-live; a wall of them cannot. Every tile is an
 *  independent request, so the cost scales with the grid and the browser only
 *  runs a handful of requests to one host at a time — push it too far and the
 *  tiles start starving the page's actual API calls.
 *
 *  MJPEG would be smoother per tile but is worse here for the same reason: it
 *  holds a connection open for as long as the tile is on screen, so more than
 *  a few would exhaust the browser's connection pool and stall everything
 *  else. Polling releases the connection between frames, and the engine caches
 *  the encoded JPEG per frame, so a repeat poll of an unchanged frame is
 *  almost free. MJPEG stays where it belongs: the enlarged view, one at a time. */
function tileRefreshMs(count: number): number {
  if (count <= 4) return 200; // 5 fps — reads as live
  if (count <= 12) return 500;
  return 1_500;
}

/** How often the grid refreshes headcounts. One request for all tiles. */
const COUNT_REFRESH_MS = 1_000;

export function CamGrid({
  title,
  note,
  cameras: fromQuery,
  only = false,
}: {
  title: string;
  note?: string;
  /** Cameras from the page's own query — richer, carrying zones and boxes for
   *  that feature. Merged over the roster rather than replacing it. */
  cameras: Camera[];
  /** Show exactly these cameras and nothing else. For the one-off previews
   *  (a connection test, a single weapon frame) where the full roster would
   *  be wrong rather than merely unnecessary. */
  only?: boolean;
}) {
  const [open, setOpen] = useState<Camera | null>(null);
  const { degraded } = useCameras();

  // The grid always shows every configured camera. A page whose query failed,
  // or returned no cameras, still renders the roster — as NO SIGNAL if the
  // engine is unreachable. Cameras disappearing is never the right answer:
  // an empty page looks like the console is broken rather than the cameras.
  const merged = useCameraGrid(fromQuery);
  const cameras = only ? fromQuery : merged;
  const refreshMs = tileRefreshMs(cameras.length);
  const [counts, setCounts] = useState<Record<string, number | null>>({});

  // The camera payload is fetched once when the page runs its query, so the
  // count baked into it freezes at that instant. Polling one small endpoint
  // for the whole grid keeps every tile's number live without adding a
  // request per tile.
  useEffect(() => {
    let cancelled = false;
    const poll = () => {
      void getCameraCounts()
        .then((next) => {
          if (!cancelled) setCounts(next);
        })
        .catch(() => {
          /* a dropped poll just leaves the previous numbers up */
        });
    };
    poll();
    const timer = setInterval(poll, COUNT_REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return (
    <div className="card" style={{ padding: 20, marginTop: 14 }}>
      <div style={{ fontWeight: 700, fontSize: 15.5 }}>{title}</div>
      {note && <div style={{ fontSize: 13, color: 'var(--tx3)', marginTop: 2 }}>{note}</div>}

      {degraded && (
        <div
          role="status"
          style={{
            marginTop: 10,
            padding: '7px 11px',
            borderRadius: 8,
            fontSize: 12.5,
            background: 'color-mix(in srgb, var(--am) 14%, transparent)',
            color: 'var(--am)',
          }}
        >
          Engine unreachable — showing the last known cameras. Nothing here is live.
        </div>
      )}

      <div className="camgrid">
        {cameras.map((cam) => (
          <button type="button" key={cam.id} className="camcard" onClick={() => setOpen(cam)}>
            <CameraFrame camera={cam} refreshMs={refreshMs} />
            <div className="camcard__meta">
              <div
                style={{
                  fontSize: 12.5,
                  fontWeight: 600,
                  color: 'var(--tx)',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {cam.name}
              </div>
              <div style={{ fontSize: 11.5, color: 'var(--tx2)', marginTop: 1 }}>
                {cam.offline ? cam.status : describeCount(counts[cam.id], cam.status)}
              </div>
            </div>
          </button>
        ))}
      </div>

      {open && <CameraModal camera={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
