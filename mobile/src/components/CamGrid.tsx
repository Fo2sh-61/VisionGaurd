import { useEffect, useMemo, useState } from 'react';
import { useCameraGrid, useCameras } from '@/app/CameraContext';
import { useLanguage, useT } from '@/app/LanguageContext';
import type { CameraFeature } from '@/services/api';
import { getCameraCounts } from '@/services/api';
import { describeCount } from '@/services/format';
import type { Camera } from '@/types';
import { Badge } from './ui';
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
 *  almost free. MJPEG stays where it belongs: the enlarged view, one at a time.
 *
 *  Paging feeds this the number of tiles ACTUALLY rendered, not the roster
 *  size. That is the whole reason the two belong in one component: a page of
 *  eight tiles out of two hundred should refresh like eight, and it only can
 *  if whatever does the paging is also what computes this.
 *
 *  Raised on 11 Sep 2026 from 5 / 2 / 0.67 a second, which read as a slide
 *  show next to the enlarged view. Two things make it affordable. Each tile
 *  asks for a picture sized to the tile — it used to be sent 1280 px to show
 *  at 128 px tall, and compressing that was most of what a tile cost. And
 *  the tile tells the engine its rate, so the camera decodes that fast while
 *  the tile is on screen instead of at its analytics rate (5 a second or
 *  less), which used to cap every tile whatever it asked for. Measured at
 *  1080p on the dev laptop, one tile at 15 a second now costs about what one
 *  at 5 did. The AI does not run any faster for it: models keep their own
 *  rate. */
export function tileRefreshMs(count: number): number {
  if (count <= 4) return 1_000 / 15; // 15 a second — reads as video
  if (count <= 12) return 200; // 5 a second
  return 500; // 2 a second
}

/** How often a tile's OVERLAY re-fetches, on the pages that draw one.
 *
 *  Deliberately left at the old picture rates. An overlay poll is its own
 *  request and renews a worker's boost, its boxes only change when the model
 *  runs, and tripling the knife page's polls was never the point of making
 *  the picture smoother. */
function tileBoxRefreshMs(count: number): number {
  if (count <= 4) return 200;
  if (count <= 12) return 500;
  return 1_500;
}

/** How often the grid refreshes headcounts. One request for all tiles. */
const COUNT_REFRESH_MS = 1_000;

/** The heading for cameras with no area set. Wording, so it comes from the
 *  catalogue; the camera's own `area` is data and is never translated. */
const UNPLACED = 'camera.unassignedArea';

export function CamGrid({
  title,
  note,
  cameras: fromQuery,
  only = false,
  byArea = false,
  searchable = false,
  pageSize,
  onPick,
  activeId,
  activeRef,
  feature,
  colour,
  tileOverlay = false,
  pinned,
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
  /** Group the tiles under their area headings. Off by default, because most
   *  pages are asking about one thing and a heading per camera is noise. */
  byArea?: boolean;
  /** Offer a search box over camera and area names. */
  searchable?: boolean;
  /** Show at most this many tiles at a time, with pager buttons. Unset shows
   *  everything, which is right for a handful of cameras and wrong for two
   *  hundred. */
  pageSize?: number;
  /** What clicking a tile does. Default opens the enlarged modal; the Track
   *  page takes it over so a click starts a follow instead. */
  onPick?: (camera: Camera) => void;
  /** Draw this camera as the chosen one. */
  activeId?: string;
  /** Handed the chosen camera's tile, so a page can bring it into view - the
   *  camera an alert linked to. */
  activeRef?: (element: HTMLElement | null) => void;
  /** Which overlay the enlarged view should draw. The tiles never draw one,
   *  so this only reaches the opened camera — which is exactly where it
   *  matters: the counting page must not open a face review. */
  feature?: CameraFeature;
  /** Narrow a `lost` overlay to one bag colour. */
  colour?: string;
  /** Draw the overlay on the tiles too, not only in the enlarged view.
   *
   *  Off by default and it should stay that way for most pages: a box at
   *  128px is unreadable and the poll is not free. The Knife page turns it
   *  on because a knife is the one overlay worth seeing without clicking
   *  first. Requires `feature` - a tile overlay with no feature would draw
   *  the default face boxes, which carry names. */
  tileOverlay?: boolean;
  /** Bring these cameras to the front, in this order, and badge them.
   *
   *  **The only prop that reorders the roster**, and it should stay the only
   *  one. Every other page shows the cameras in roster order on purpose: an
   *  operator learns where a tile lives and a grid that rearranged itself
   *  between polls would make that impossible. A search result is the one case
   *  where the order *is* the answer - the cameras that saw the bag are the
   *  point, and burying them on page four of the pager would be. */
  pinned?: string[];
}) {
  const t = useT();
  const { language } = useLanguage();
  const [open, setOpen] = useState<Camera | null>(null);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const { degraded } = useCameras();

  // The grid always shows every configured camera. A page whose query failed,
  // or returned no cameras, still renders the roster — as NO SIGNAL if the
  // engine is unreachable. Cameras disappearing is never the right answer:
  // an empty page looks like the console is broken rather than the cameras.
  const merged = useCameraGrid(fromQuery);
  const all = only ? fromQuery : merged;

  const needle = search.trim().toLowerCase();
  const matching = useMemo(
    () =>
      needle
        ? all.filter(
            (c) =>
              c.name.toLowerCase().includes(needle) ||
              (c.area ?? '').toLowerCase().includes(needle),
          )
        : all,
    [all, needle],
  );

  // Pinned first, and **before paging**. Sorting the visible page instead
  // would leave a camera that saw the bag sitting on page three, which is the
  // one place the operator will not look. Inside a memo because `counts`
  // repolls every second and re-sorting on each would make the tiles jump
  // under the pointer. `sort` is stable, so everything else keeps roster order.
  const ranked = useMemo(() => {
    if (!pinned?.length) return matching;
    const rank = new Map(pinned.map((id, i) => [id, i]));
    return [...matching].sort(
      (a, b) => (rank.get(a.id) ?? Infinity) - (rank.get(b.id) ?? Infinity),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matching, pinned?.join(',')]);

  const pages = pageSize ? Math.max(1, Math.ceil(ranked.length / pageSize)) : 1;
  // A narrowed search can leave the current page past the end. Clamping on
  // render rather than resetting on change keeps the pager honest without
  // yanking the operator back to page one every keystroke.
  const current = Math.min(page, pages - 1);
  const ordered = pageSize
    ? ranked.slice(current * pageSize, current * pageSize + pageSize)
    : ranked;

  const refreshMs = tileRefreshMs(ordered.length);
  const boxRefreshMs = tileBoxRefreshMs(ordered.length);
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

  const pick = (cam: Camera) => (onPick ? onPick(cam) : setOpen(cam));

  const tile = (cam: Camera) => (
    <button
      type="button"
      key={cam.id}
      ref={cam.id === activeId ? activeRef : undefined}
      className="camcard"
      onClick={() => pick(cam)}
      style={
        cam.id === activeId || pinned?.includes(cam.id)
          ? { outline: '2px solid var(--ac)', outlineOffset: 1 }
          : undefined
      }
    >
      <CameraFrame
        camera={cam}
        refreshMs={refreshMs}
        boxRefreshMs={boxRefreshMs}
        feature={tileOverlay ? feature : undefined}
        colour={colour}
        tileOverlay={tileOverlay}
      />
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
        <div style={{ fontSize: 12, color: 'var(--tx2)', marginTop: 1 }}>
          {cam.offline ? cam.status : describeCount(counts[cam.id], cam.status, language)}
        </div>
        {pinned?.includes(cam.id) && (
          <div style={{ marginTop: 4 }}>
            <Badge tone="warn">{t('camera.bagSeen')}</Badge>
          </div>
        )}
      </div>
    </button>
  );

  // Areas in the order their first camera appears, so the grid does not
  // reshuffle itself between polls.
  const areas: string[] = [];
  for (const cam of ordered) {
    const area = cam.area || UNPLACED;
    if (!areas.includes(area)) areas.push(area);
  }

  return (
    <div className="card">
      {/* Phone: the search takes its own full-width line under the title. */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: 12,
        }}
      >
        <div>
          {title && <div style={{ fontWeight: 700, fontSize: 15.5 }}>{title}</div>}
          {note && <div style={{ fontSize: 13, color: 'var(--tx3)', marginTop: 2 }}>{note}</div>}
        </div>

        {searchable && (
          <input
            type="search"
            value={search}
            placeholder={t('camera.search')}
            aria-label={t('camera.search')}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(0);
            }}
            className="input"
            style={{ flex: '1 1 100%' }}
          />
        )}
      </div>

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
          {t('camera.lastKnown')}
        </div>
      )}

      {matching.length === 0 && (
        <div style={{ marginTop: 14, fontSize: 13, color: 'var(--tx3)' }}>
          {needle
            ? t('camera.noneMatch', { search: search.trim() })
            : t('camera.noneConfigured')}
        </div>
      )}

      {byArea
        ? areas.map((area) => (
            <div key={area} style={{ marginTop: 14 }}>
              <div
                style={{
                  fontSize: 12.5,
                  fontWeight: 700,
                  letterSpacing: 0.3,
                  textTransform: 'uppercase',
                  color: 'var(--tx2)',
                  marginBottom: 2,
                }}
              >
                {area === UNPLACED ? t(UNPLACED) : area}
              </div>
              <div className="camgrid">
                {ordered.filter((c) => (c.area || UNPLACED) === area).map(tile)}
              </div>
            </div>
          ))
        : ordered.length > 0 && <div className="camgrid">{ordered.map(tile)}</div>}

      {pageSize && pages > 1 && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            marginTop: 12,
            fontSize: 12.5,
            color: 'var(--tx2)',
          }}
        >
          <button
            type="button"
            className="linkbtn"
            disabled={current === 0}
            onClick={() => setPage(current - 1)}
          >
            {t('camera.previous')}
          </button>
          <span>
            {current * pageSize + 1}–{Math.min(matching.length, (current + 1) * pageSize)} of{' '}
            {matching.length}
          </span>
          <button
            type="button"
            className="linkbtn"
            disabled={current >= pages - 1}
            onClick={() => setPage(current + 1)}
          >
            {t('camera.next')}
          </button>
        </div>
      )}

      {open && (
        <CameraModal camera={open} onClose={() => setOpen(null)} feature={feature} colour={colour} />
      )}
    </div>
  );
}
