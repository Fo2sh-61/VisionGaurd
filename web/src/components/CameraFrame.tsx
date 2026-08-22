import { useEffect, useRef, useState } from 'react';
import { useSite } from '@/app/SiteContext';
import type { CameraFeature } from '@/services/api';
import { getCameraDetections } from '@/services/api';
import { siteClock } from '@/services/format';
import type { PictureRect } from '@/services/frame';
import { pictureRect } from '@/services/frame';
import type { BoxColor, Camera, DetectionBox } from '@/types';

const BOX_COLOR: Record<BoxColor, string> = {
  green: 'var(--det-green)',
  red: 'var(--det-red)',
  blue: 'var(--det-blue)',
  amber: 'var(--det-amber)',
};

type Size = 'sm' | 'lg';

const SCALE = {
  sm: {
    height: 128,
    grid: 26,
    border: 2,
    inset: 8,
    insetX: 9,
    chrome: 10.5,
    labelFont: 10,
    labelTop: -18,
    labelPad: '1px 6px',
  },
  lg: {
    height: 380,
    grid: 34,
    border: 2.5,
    inset: 12,
    insetX: 14,
    chrome: 12,
    labelFont: 12,
    labelTop: -24,
    labelPad: '2px 8px',
  },
} as const satisfies Record<Size, object>;

/** Default tile refresh. `CamGrid` overrides it based on how many tiles are on
 *  screen — see `tileRefreshMs` there. */
const SNAPSHOT_REFRESH_MS = 1_000;

/** How often the on-screen clock ticks. */
const CLOCK_TICK_MS = 1_000;

/** How often the enlarged view re-fetches detection boxes.
 *
 *  Measured, not guessed. A watched camera recognises at ~10 results/sec, so
 *  polling every 300 ms threw away two thirds of them and the box visibly
 *  stepped. 100 ms keeps up with the engine and the box tracks smoothly.
 *
 *  Each poll also renews that camera's boost server-side, so the act of
 *  watching is what pays for the higher rate. The payload is a few hundred
 *  bytes and the response is ~4 ms. */
const DETECTION_REFRESH_MS = 100;

/** A camera tile: the real frame, with whatever the engine detected drawn over it.
 *
 *  When the engine cannot supply a frame the synthetic dark room is drawn
 *  instead, so the overlays still make sense and nothing looks broken. An
 *  offline camera keeps showing its last frame under a NO SIGNAL label rather
 *  than being presented as live. */
export function CameraFrame({
  camera,
  size = 'sm',
  live = false,
  refreshMs = SNAPSHOT_REFRESH_MS,
  onCount,
  onBoxes,
  badge = 'LIVE',
  feature,
  detections = true,
  onPicture,
}: {
  camera: Camera;
  size?: Size;
  /** Use the MJPEG stream instead of polled snapshots. Enlarged view only. */
  live?: boolean;
  /** Snapshot poll interval. `CamGrid` scales this to the grid size. */
  refreshMs?: number;
  /** Called with each live headcount, so the enlarged view can show it
   *  without running a second poll of its own. */
  onCount?: (count: number | null) => void;
  /** Called with the boxes currently drawn, in the same percentages they are
   *  drawn at. The Track page uses it to tell whether the pointer is over a
   *  body, so clicking to follow feels like clicking a person rather than
   *  guessing at a spot. Same poll, no second request. */
  onBoxes?: (boxes: DetectionBox[]) => void;
  /** Replaces the LIVE chip. The tracking page shows "Recording" here, because
   *  on that screen the badge means recording is running — showing both would
   *  say two different things at once. `null` hides it entirely. */
  badge?: string | null;
  /** Which overlay to draw. Tracking ids on an attendance tile answer a
   *  question that page never asked, so the page says what it wants. */
  feature?: CameraFeature;
  /** Draw the engine's recognition boxes over the stream. The enrolment page
   *  turns this off: those boxes carry names, and a page that is deciding who
   *  someone IS must not display the system's guess at who they are. It draws
   *  its own nameless outline instead. */
  detections?: boolean;
  /** Where the picture ended up inside the tile, in CSS pixels from the
   *  tile's top-left corner. A page that turns a click into a point on the
   *  picture needs it — the Track page does, because a point on the picture
   *  is the only thing the engine can hit-test. The tile and the picture are
   *  rarely the same shape, so the two are not interchangeable. */
  onPicture?: (rect: PictureRect) => void;
}) {
  const s = SCALE[size];
  const tzOffsetMinutes = useSite().site?.tzOffsetMinutes ?? 0;
  const zone = camera.zone;
  // Keep the zone label inside the frame when the zone starts near the top edge.
  const zoneLabelInside = zone ? zone.y < 24 : false;

  const [tick, setTick] = useState(0);
  const [imageFailed, setImageFailed] = useState(false);
  const [liveBoxes, setLiveBoxes] = useState<DetectionBox[] | null>(null);

  // The tile's size, and the picture's shape.
  //
  // Every overlay the engine sends is a fraction of the PICTURE, so neither
  // can be assumed: the tile is whatever the page's grid gave it, and the
  // picture is whatever shape the camera is.
  const frameRef = useRef<HTMLDivElement | null>(null);
  const [frameSize, setFrameSize] = useState({ width: 0, height: 0 });
  const [aspect, setAspect] = useState<number | null>(null);

  const useStream = live && !!camera.streamUrl && !camera.offline;
  const usePolling = !useStream && !!camera.snapshotUrl && !imageFailed;

  // Measured, not assumed. A tile is sized by the page's grid and changes
  // with the window, and a box drawn against a stale size is a box on nobody.
  useEffect(() => {
    const element = frameRef.current;
    if (!element) return;
    const measure = () =>
      setFrameSize({ width: element.clientWidth, height: element.clientHeight });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // A different camera is a different shape. Keeping the previous one would
  // draw this camera's boxes in the last camera's frame of reference until
  // the first frame lands.
  useEffect(() => setAspect(null), [camera.id]);

  useEffect(() => {
    if (!usePolling) return;
    const timer = setInterval(() => setTick((n) => n + 1), refreshMs);
    return () => clearInterval(timer);
  }, [usePolling, refreshMs]);

  // ONLY the enlarged view polls detections.
  //
  // Tiles are a live picture, nothing more. Polling detections per tile also
  // renews that camera's recognition boost, so a grid of tiles would push every
  // camera on the page to the high rate — for boxes nobody can read at 128px.
  // Recognition still runs in the background at the idle rate, so attendance is
  // unaffected; the tiles simply stop paying for frame-accurate overlays.
  const wantLiveBoxes = useStream && detections;

  useEffect(() => {
    if (!wantLiveBoxes) {
      setLiveBoxes(null);
      return;
    }

    let cancelled = false;
    const poll = () => {
      void getCameraDetections(camera.id, feature)
        .then((result) => {
          if (cancelled) return;
          const drawn = result.boxes;
          setLiveBoxes(drawn);
          onCount?.(result.peopleCount);
          onBoxes?.(drawn);
        })
        .catch(() => {
          // A dropped poll is not worth surfacing; the next one will land and
          // the previous boxes stay on screen meanwhile.
        });
    };

    poll();
    const timer = setInterval(poll, DETECTION_REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [wantLiveBoxes, camera.id, onCount, onBoxes, feature]);

  // Boxes are drawn ONLY in the enlarged view, and only from live polling.
  //
  // Falling back to `camera.boxes` here looked harmless but was the worst
  // option available: the page payload is fetched once, so a tile rendered a
  // box from minutes ago frozen over a live picture — showing where a face
  // *was*, with no way for the viewer to tell. Drawing nothing is honest;
  // drawing something stale is not.
  //
  // Recognition still runs in the background on every attendance camera, so
  // this costs no accuracy and no attendance data. It only means a 128px
  // thumbnail is a picture rather than a picture plus an unreadable rectangle.
  const boxes = liveBoxes ?? [];

  // Overlays are fractions of this rectangle, never of the tile around it.
  // Reading them against the tile is what slid every box off the person it
  // belonged to on the people counting page, where the tile is nearly square
  // and the camera is 16:9.
  const picture = pictureRect(frameSize.width, frameSize.height, aspect);
  const { left: pictureLeft, top: pictureTop } = picture;
  const { width: pictureWidth, height: pictureHeight } = picture;

  useEffect(() => {
    onPicture?.({
      left: pictureLeft,
      top: pictureTop,
      width: pictureWidth,
      height: pictureHeight,
    });
  }, [onPicture, pictureLeft, pictureTop, pictureWidth, pictureHeight]);

  // The clock ticks only while the camera is up.
  //
  // A running clock over a frozen frame would be the exact lie the NO SIGNAL
  // rule exists to prevent — it would say "this is happening now" about a
  // picture that might be an hour old. An offline tile keeps the timestamp of
  // the last frame actually received.
  const [clock, setClock] = useState(() => siteClock(tzOffsetMinutes));

  useEffect(() => {
    if (camera.offline) return;
    setClock(siteClock(tzOffsetMinutes));
    const timer = setInterval(
      () => setClock(siteClock(tzOffsetMinutes)),
      CLOCK_TICK_MS,
    );
    return () => clearInterval(timer);
  }, [camera.offline, tzOffsetMinutes]);

  const timestamp = camera.offline ? (camera.time ?? '—') : clock;

  // Cache-busting: the URL is stable, so without this the browser would serve
  // the first frame forever.
  const frameSrc = useStream
    ? camera.streamUrl
    : usePolling
      ? `${camera.snapshotUrl}?t=${tick}`
      : undefined;

  return (
    <div className="camframe" ref={frameRef} style={{ height: s.height }}>
      {frameSrc ? (
        <img
          src={frameSrc}
          alt={camera.name}
          onError={() => setImageFailed(true)}
          onLoad={(e) => {
            const { naturalWidth, naturalHeight } = e.currentTarget;
            if (naturalWidth > 0 && naturalHeight > 0) {
              setAspect(naturalWidth / naturalHeight);
            }
          }}
          style={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            // Fitted, never cropped. `cover` filled the tile by throwing the
            // edges of the frame away, which on a counting page means people
            // who are in the number but not on the screen.
            objectFit: 'contain',
            // Dim a frame that is no longer current, so a still corridor does
            // not read as a live one.
            filter: camera.offline ? 'grayscale(1) brightness(.45)' : undefined,
          }}
        />
      ) : (
        <>
          <div
            className="camframe__grid"
            style={{ backgroundSize: `${s.grid}px ${s.grid}px` }}
          />
          <div className="camframe__floor" />
        </>
      )}

      {/* From here down, everything is positioned inside the PICTURE.

          Zones, the counting line and every box are fractions of the frame
          the camera sent. The tile around it is a different rectangle, and
          reading one as the other is what put boxes beside people instead of
          round them. */}
      <div
        className="camframe__stage"
        style={{
          left: pictureLeft,
          top: pictureTop,
          width: pictureWidth,
          height: pictureHeight,
        }}
      >
        {zone && (
          <div
            className="camframe__zone"
            style={{
              left: `${zone.x}%`,
              top: `${zone.y}%`,
              width: `${zone.w}%`,
              height: `${zone.h}%`,
              borderWidth: s.border,
            }}
          >
            <span
              className="camframe__zonelabel"
              style={{
                top: zoneLabelInside ? 3 : s.labelTop,
                left: zoneLabelInside ? 3 : -2,
                fontSize: s.labelFont,
                padding: s.labelPad,
              }}
            >
              {zone.label}
            </span>
          </div>
        )}

        {camera.countLine !== undefined && (
          <div
            className="camframe__countline"
            style={{ top: `${camera.countLine}%`, borderTopWidth: s.border }}
          />
        )}

        {boxes.map((b, i) => (
          <div
            key={i}
            className="camframe__box"
            style={{
              left: `${b.x}%`,
              top: `${b.y}%`,
              width: `${b.w}%`,
              height: `${b.h}%`,
              border: `${s.border}px solid ${BOX_COLOR[b.color]}`,
            }}
          >
            {(b.label || b.trackId) && (
              <span
                className="camframe__label"
                style={{
                  top: b.trackId ? undefined : s.labelTop,
                  bottom: b.trackId ? '100%' : undefined,
                  fontSize: s.labelFont,
                  padding: s.labelPad,
                  background: BOX_COLOR[b.color],
                  lineHeight: 1.15,
                }}
              >
                {/* Tracked bodies lead with the identity, name underneath: the id
                    is the thing that persists across cameras and is what the
                    operator is actually following. A name may not exist at all. */}
                {b.trackId ? (
                  <>
                    <span style={{ display: 'block', fontSize: s.labelFont * 1.45, fontWeight: 800 }}>
                      #{b.trackId}
                    </span>
                    <span style={{ display: 'block', fontSize: s.labelFont * 0.92 }}>
                      {b.label ?? 'Unknown person'}
                    </span>
                  </>
                ) : (
                  b.label
                )}
              </span>
            )}
          </div>
        ))}
      </div>

      {!camera.offline && badge !== null && (
        <div
          className="camframe__live"
          style={{ top: s.inset, left: s.insetX, fontSize: s.chrome }}
        >
          <span className="dot" style={{ width: 6, height: 6 }} />
          {badge}
        </div>
      )}

      {camera.offline && (
        <div className="camframe__nosignal">
          <span style={{ color: '#aab5ac', fontSize: 12, fontWeight: 700, letterSpacing: '.05em' }}>
            NO SIGNAL
          </span>
          <span style={{ color: '#77827a', fontSize: 11 }}>showing last received frame</span>
        </div>
      )}

      <div
        className="camframe__time"
        style={{ top: s.inset, right: s.insetX, fontSize: s.chrome }}
      >
        {timestamp}
      </div>
    </div>
  );
}
