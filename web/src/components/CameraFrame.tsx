import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { ImgHTMLAttributes, RefObject } from 'react';
import { useT } from '@/app/LanguageContext';
import { useSite } from '@/app/SiteContext';
import type { CameraFeature } from '@/services/api';
import { getCameraDetections } from '@/services/api';
import { plateWidthTone, siteClock } from '@/services/format';
import type { PictureRect } from '@/services/frame';
import { pictureRect, tileBoxRefreshMs, tileRefreshMs } from '@/services/frame';
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
    minHeight: 121,
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
    minHeight: 380,
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

/** How long a tile waits for a picture before asking again anyway.
 *
 *  A tile asks for its next picture only once the last one has arrived, so a
 *  slow link slows the tile down instead of piling requests up behind it.
 *  This is the way out when a request never comes back at all. */
const STALLED_MS = 5_000;

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

/** How often a view re-fetches its boxes while its picture is scrolled off
 *  screen but the page still shows what they report - the phone's camera
 *  screen lists who is in view under the picture. There is no moving box to
 *  keep up with then, only a list to keep current. */
const OFF_SCREEN_REPORT_MS = 1_000;

/** Every polled tile on screen right now, across the whole page.
 *
 *  Page-wide rather than per grid, because what runs out is the browser's
 *  handful of connections to the engine, and those are shared by every tile
 *  on the screen whichever grid drew it. A tile joins while it is on screen
 *  and asking for pictures, and leaves when it scrolls away, is covered, or
 *  goes. Its rate is `tileRefreshMs` of how many are here. */
const tilesOnScreen = new Set<object>();
const tilesOnScreenListeners = new Set<() => void>();

function subscribeTilesOnScreen(listener: () => void): () => void {
  tilesOnScreenListeners.add(listener);
  return () => {
    tilesOnScreenListeners.delete(listener);
  };
}

function countTilesOnScreen(): number {
  return tilesOnScreen.size;
}

function markTileOnScreen(tile: object, on: boolean): void {
  if (on === tilesOnScreen.has(tile)) return;
  if (on) tilesOnScreen.add(tile);
  else tilesOnScreen.delete(tile);
  tilesOnScreenListeners.forEach((listener) => listener());
}

/** Whether this browser tab is in front: false while the tab is in the
 *  background, the window is minimised, or the phone's screen is off.
 *
 *  Exported for the grids' headcount polls, which have the same reason to
 *  stop. Every camera picture stops with it and starts again the moment the
 *  tab comes back. */
export function usePageVisible(): boolean {
  const [visible, setVisible] = useState(() => document.visibilityState !== 'hidden');

  useEffect(() => {
    const update = () => setVisible(document.visibilityState !== 'hidden');
    update();
    document.addEventListener('visibilitychange', update);
    return () => document.removeEventListener('visibilitychange', update);
  }, []);

  return visible;
}

/** Whether any of `element` is inside the visible part of the screen.
 *
 *  The browser's own viewport is the root, which also clips by every
 *  scrolling box on the way up: the phone scrolls a `<main>` rather than the
 *  window, and its "other cameras" strip scrolls sideways inside that, and a
 *  tile scrolled out of either is reported as off screen. Starts false, so a
 *  tile that is never scrolled to never asks for anything. */
function useOnScreen(ref: RefObject<HTMLElement | null>): boolean {
  const [onScreen, setOnScreen] = useState(false);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new IntersectionObserver((entries) => {
      setOnScreen(entries[entries.length - 1].isIntersecting);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);

  return onScreen;
}

/** The live stream's picture, which lets go of the stream when it stops
 *  showing it.
 *
 *  A browser does not stop loading an image because its element left the
 *  page: the HTML spec keeps an image fetch alive even when the element is no
 *  longer in the document. A still picture finishes anyway; an MJPEG response
 *  never does. So closing the enlarged view left its stream running until the
 *  whole page was left, and the engine, which counts an open stream as
 *  somebody watching, kept that camera reading and converting every frame for
 *  nobody — 822 a second on the recorded clip, measured 12 Sep 2026 with the
 *  view closed. The Track page's big view and enrolment's live view are this
 *  same element, so they left a stream behind too.
 *
 *  So this element owns its `src` and removes it when it stops showing the
 *  stream. `removeAttribute('src')` aborts the request and fires no event.
 *  `src = ''` aborts it too but fires `error`, which `CameraFrame` would read
 *  as a failed camera. Both were measured in Chromium, which is what this
 *  console runs on (Chrome/Edge); the spec requires the abort, but how a
 *  multipart response is torn down is each engine's own code, and Safari has
 *  an old open bug about not closing one at all.
 *
 *  React never sets `src` here, so development's StrictMode rehearsal
 *  (unmount, then mount again) puts it back instead of leaving a blank
 *  picture. A layout effect, so the address is in place before the first
 *  paint. */
function StreamImage({
  src,
  ...rest
}: { src: string } & Omit<ImgHTMLAttributes<HTMLImageElement>, 'src'>) {
  const ref = useRef<HTMLImageElement | null>(null);

  useLayoutEffect(() => {
    const img = ref.current;
    if (!img) return;
    img.src = src;
    return () => img.removeAttribute('src');
  }, [src]);

  return <img ref={ref} {...rest} />;
}

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
  paused = false,
  onCount,
  onBoxes,
  badge = 'LIVE',
  feature,
  colour,
  detections = true,
  tileOverlay = false,
  onPicture,
}: {
  camera: Camera;
  size?: Size;
  /** Use the MJPEG stream instead of polled snapshots. Enlarged view only. */
  live?: boolean;
  /** Stop asking for anything, although the tile is on screen: the page has
   *  covered it. `CamGrid` sets it while its enlarged view is open over the
   *  grid. Scrolled away and a tab in the background need no prop; the tile
   *  notices those itself.
   *
   *  There is no rate to pass. Every tile's rate comes from how many tiles
   *  are on screen (`tileRefreshMs`), so a page cannot hand one a rate worked
   *  out from a count that has since changed - which is how the phone's Home
   *  camera sat at one picture a second. */
  paused?: boolean;
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
  /** Narrow a `lost` overlay to one bag colour. Ignored by every other
   *  feature - it is part of the question this page is asking. */
  colour?: string;
  /** Draw the engine's recognition boxes over the stream. The enrolment page
   *  turns this off: those boxes carry names, and a page that is deciding who
   *  someone IS must not display the system's guess at who they are. It draws
   *  its own nameless outline instead. */
  detections?: boolean;
  /** Poll and draw the overlay on a GRID TILE, not only in the enlarged view.
   *
   *  Off everywhere by default, and it should stay that way — the comment on
   *  `wantLiveBoxes` explains why tiles are a picture and nothing more. The
   *  Knife page is the exception the owner asked for on 22 Aug 2026: a knife
   *  is the one overlay worth seeing without clicking first, because the
   *  question it answers is "is that a knife" and you should not have to open
   *  a camera to ask it.
   *
   *  It is affordable there for two reasons. The poll runs at the tiles'
   *  overlay rate (`tileBoxRefreshMs`), not the enlarged view's 100 ms, and
   *  only while the tile is on screen. And the server no longer
   *  wakes face recognition for a weapons poll, so a grid of tiles costs the
   *  knife worker's boost and nothing else. */
  tileOverlay?: boolean;
  /** Where the picture ended up inside the tile, in CSS pixels from the
   *  tile's top-left corner. A page that turns a click into a point on the
   *  picture needs it — the Track page does, because a point on the picture
   *  is the only thing the engine can hit-test. The tile and the picture are
   *  rarely the same shape, so the two are not interchangeable. */
  onPicture?: (rect: PictureRect) => void;
}) {
  const s = SCALE[size];
  const t = useT();
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

  // On screen, in a tab that is in front, and not covered by the page.
  //
  // The pictures and the stream run only while this is true, and stop the
  // moment it is not: scrolled away, the tab in the background, the phone's
  // screen off. Nobody can see a picture then, so nobody should be paying
  // for one. They start again as soon as the tile is back. (The boxes follow
  // the same rule, with one exception explained at `wantLiveBoxes`.)
  const onScreen = useOnScreen(frameRef);
  const pageVisible = usePageVisible();
  const showing = onScreen && pageVisible && !paused;

  // Counted among the tiles on screen while it is asking for pictures, and
  // its rate is the screen's budget shared by that many. A live stream is
  // not counted: it is one connection, however many frames it carries.
  const polling = usePolling && showing;
  const tile = useRef({}).current;
  useEffect(() => {
    markTileOnScreen(tile, polling);
    return () => markTileOnScreen(tile, false);
  }, [tile, polling]);
  // A tile that is not asking reads nothing, so a scroll that changes the
  // count does not re-render the hundred tiles off screen.
  const tilesShowing = useSyncExternalStore(
    subscribeTilesOnScreen,
    () => (polling ? countTilesOnScreen() : 0),
  );
  const refreshMs = tileRefreshMs(tilesShowing);

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

  // One picture in flight at a time.
  //
  // The timer used to swap the picture's address every interval whether or
  // not the last picture had arrived. At 15 a second on a slow link that is
  // a request abandoned every 67 ms and a tile that never finishes loading
  // one. Now a tick is skipped while the last picture is still on its way,
  // so the tile runs at `refreshMs` on a fast link and as fast as the link
  // allows on a slow one. Refs, not state: nothing here should re-render.
  //
  // Only while the tile is showing. A paused tile keeps its last picture;
  // nobody can see it, and it is replaced within one tick of coming back.
  const requested = useRef({ tick: 0, at: performance.now() });
  const loadedTick = useRef(-1);
  const wasPolling = useRef(false);

  useEffect(() => {
    if (!polling) {
      wasPolling.current = false;
      return;
    }
    const resumed = !wasPolling.current;
    wasPolling.current = true;
    const step = () => {
      const now = performance.now();
      const last = requested.current;
      if (loadedTick.current < last.tick && now - last.at < STALLED_MS) return;
      requested.current = { tick: last.tick + 1, at: now };
      setTick(last.tick + 1);
    };
    // Back from a pause, the picture held is as old as the pause was, so the
    // next one is asked for now rather than a tick from now. Only on coming
    // back: a new share of the budget, when another tile scrolls in or out,
    // just restarts the timer at the new rate. And not on a tile's first
    // picture, which its first render has already asked for.
    if (resumed && loadedTick.current >= 0 && performance.now() - requested.current.at > refreshMs) {
      step();
    }
    const timer = setInterval(step, refreshMs);
    return () => clearInterval(timer);
  }, [polling, refreshMs]);

  // The enlarged view polls detections, and so does a tile that explicitly
  // asked to (`tileOverlay`). Nothing else does.
  //
  // Tiles are a live picture, nothing more, unless a page has a reason. Polling
  // detections per tile used to renew that camera's *recognition* boost too, so
  // a grid of tiles pushed every camera on the page to the high rate — for
  // boxes nobody can read at 128px. The engine now boosts only the worker whose
  // overlay was actually asked for (`camera_detections` in api/app.py), so a
  // weapons tile costs the knife worker and leaves face recognition alone.
  //
  // Recognition still runs in the background at the idle rate either way, so
  // attendance is unaffected by any of this.
  //
  // And only while somebody can see what it reports. Never with the tab in
  // the background or under the enlarged view. A tile's boxes are drawn on
  // its picture and nowhere else, so they stop with the picture when it
  // scrolls away. A view whose page also shows what the poll reports
  // (`onCount`, `onBoxes`) keeps asking while that page is in front: the
  // phone's camera screen lists who is in view under the picture, and that
  // list is exactly what you scroll down to read. It asks once a second
  // then, not ten times; there is no moving box to keep up with.
  //
  // Stopping costs no analysis. Recognition, tracking, the knife and the
  // plate readers all keep working at their own background rate; the poll
  // only ever sped them up. The lost-bag search is different - it looks only
  // at cameras somebody is watching and keeps nothing - and a tile nobody can
  // see is exactly a camera nobody is watching, so it stops there too, by
  // its own rule.
  const reported = !!(onCount || onBoxes);
  const wantLiveBoxes =
    (useStream || tileOverlay) && detections && pageVisible && !paused && (onScreen || reported);
  // The enlarged view tracks a moving box at 100 ms. A tile is small and there
  // may be a screenful of them, so it polls at the grid's overlay rate, which
  // stayed where it was when the pictures sped up.
  const boxRefreshMs = useStream
    ? (onScreen ? DETECTION_REFRESH_MS : OFF_SCREEN_REPORT_MS)
    : tileBoxRefreshMs(tilesShowing);

  // When the last poll went out, and what it asked about.
  const lastBoxPoll = useRef({ question: '', at: 0 });

  useEffect(() => {
    if (!wantLiveBoxes) {
      setLiveBoxes(null);
      return;
    }

    const question = `${camera.id}|${feature ?? ''}|${colour ?? ''}`;
    let cancelled = false;
    const poll = () => {
      lastBoxPoll.current = { question, at: performance.now() };
      void getCameraDetections(camera.id, feature, colour)
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

    // Straight away for a new question - another camera, feature or colour -
    // or when the last answer is older than one interval, as after a pause.
    // A new rate alone, when another tile scrolls in or out, waits for its
    // own interval rather than sending an extra request from every tile.
    const last = lastBoxPoll.current;
    if (last.question !== question || performance.now() - last.at >= boxRefreshMs) poll();
    const timer = setInterval(poll, boxRefreshMs);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [wantLiveBoxes, boxRefreshMs, camera.id, onCount, onBoxes, feature, colour]);

  // Boxes come from live polling and from nowhere else — never from
  // `camera.boxes`.
  //
  // That fallback looked harmless and was the worst option available: the page
  // payload is fetched once, so a tile rendered a box from minutes ago frozen
  // over a live picture — showing where a face *was*, with no way for the
  // viewer to tell. Drawing nothing is honest; drawing something stale is not.
  //
  // This still holds now that a tile can poll: `tileOverlay` makes the tile
  // fetch its own current boxes, which is the opposite of reusing the page's
  // stale ones. A tile that did not ask draws nothing at all.
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
  // the last frame actually received. A paused tile stops too, so its time
  // stays with the picture it is still holding.
  const [clock, setClock] = useState(() => siteClock(tzOffsetMinutes));

  useEffect(() => {
    if (camera.offline || !showing) return;
    setClock(siteClock(tzOffsetMinutes));
    const timer = setInterval(
      () => setClock(siteClock(tzOffsetMinutes)),
      CLOCK_TICK_MS,
    );
    return () => clearInterval(timer);
  }, [camera.offline, tzOffsetMinutes, showing]);

  const timestamp = camera.offline ? (camera.time ?? '—') : clock;

  // Cache-busting: the URL is stable, so without this the browser would serve
  // the first frame forever.
  //
  // `width` asks for a picture the size the tile will show, in device pixels;
  // the engine rounds it up to one of a few sizes. Rounded up here to a step
  // of 160 as well, so dragging the window edge does not re-request the
  // picture at every pixel. Left out until the tile has been measured, which
  // gets the full picture once rather than a tiny one.
  //
  // `fps` tells the engine how often this tile will ask, so the camera
  // prepares new pictures that fast while the tile is on screen.
  const devicePixels = frameSize.width * (window.devicePixelRatio || 1);
  const requestWidth = Math.ceil(devicePixels / 160) * 160;
  const snapshotQuery =
    `t=${tick}` +
    (requestWidth > 0 ? `&width=${requestWidth}` : '') +
    `&fps=${Math.max(1, Math.round(1_000 / refreshMs))}`;

  // The picture's address moves once per tick, and only while the tile is
  // showing.
  //
  // A new address is a new request, and the rest of the address changes
  // between ticks: the tile's share of the budget whenever another tile
  // scrolls in or out, its width when the window is resized. Rebuilt on every
  // render, a scroll across a grid re-asked every tile on screen for a
  // picture at each edge it crossed, and a tile paused off screen asked
  // again every time its share changed. Held to the tick, a paused tile asks
  // for nothing. A tile that has never been on screen has no address yet, so
  // the cameras at the bottom of a long list cost nothing until they are
  // scrolled to. Set during render, so the first picture is asked for in the
  // same render that finds the tile on screen.
  //
  // Held to the camera as well as the tick. Home and the Track page hand one
  // tile a different camera without remounting it, and an address kept only
  // by tick would show the last camera's picture under the new camera's name
  // until the next tick.
  const snapshotUrl = camera.snapshotUrl ?? '';
  const [asked, setAsked] = useState<{ tick: number; from: string; src: string } | null>(null);
  const asking =
    polling && (asked === null || asked.tick !== tick || asked.from !== snapshotUrl)
      ? { tick, from: snapshotUrl, src: `${snapshotUrl}?${snapshotQuery}` }
      : asked;
  if (asking !== asked) setAsked(asking);

  // A stream is let go while it is not showing, which is the only way its
  // connection closes (see `StreamImage`), and opened again when it is.
  const frameSrc = useStream
    ? (showing ? camera.streamUrl : undefined)
    : usePolling && asking?.from === snapshotUrl
      ? asking.src
      : undefined;

  // Shared by both pictures. The stream is a separate element (`StreamImage`)
  // so it can let go of its connection, which makes a switch between stream
  // and snapshots a new element rather than a new address on the old one.
  const pictureProps: Omit<ImgHTMLAttributes<HTMLImageElement>, 'src'> = {
    alt: camera.name,
    onError: () => setImageFailed(true),
    onLoad: (e) => {
      loadedTick.current = tick;
      const { naturalWidth, naturalHeight } = e.currentTarget;
      if (naturalWidth > 0 && naturalHeight > 0) {
        setAspect(naturalWidth / naturalHeight);
      }
    },
    style: {
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
    },
  };

  return (
    // dir="ltr" is pinned here and must stay pinned, in every language.
    //
    // Everything below is positioned in physical coordinates against the
    // frame the camera actually sent — zones, the counting line, every box,
    // the badges. Right-to-left is a property of the interface; the picture
    // is evidence. Letting `dir` reach in here would mirror the overlays and
    // put a box on the wrong person, in a way that looks entirely deliberate
    // to whoever is reading it. A mirrored picture is a fabricated picture.
    //
    // Arabic text inside still reads right-to-left on its own — a camera
    // name or a person's name is a text run, and the bidi algorithm handles
    // it without any help from the container. P11-FR-009.
    <div
      className="camframe"
      dir="ltr"
      ref={frameRef}
      style={{
        // The camera's own shape, once a frame has landed. 16:9 until then, so
        // the tile does not jump from a square placeholder.
        aspectRatio: aspect ?? 16 / 9,
        minHeight: s.minHeight,
      }}
    >
      {frameSrc ? (
        useStream ? (
          <StreamImage src={frameSrc} {...pictureProps} />
        ) : (
          <img src={frameSrc} {...pictureProps} />
        )
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
                      {b.label ?? t('camera.unknownPerson')}
                    </span>
                  </>
                ) : (
                  b.label
                )}
              </span>
            )}

            {/* The aiming aid, on plate boxes only.

                Sits outside the box to its right rather than in the label,
                because it answers a different question: the label says what
                was read, this says whether the camera is close enough to
                read it at all. Green clears the comfortable line, amber
                still reads with less confidence — it is never a rejection. */}
            {b.plateWidthPx !== undefined && (
              <span
                style={{
                  position: 'absolute',
                  left: '100%',
                  top: 0,
                  marginLeft: 4,
                  fontSize: s.labelFont,
                  fontWeight: 700,
                  fontFamily: 'ui-monospace, Menlo, monospace',
                  color: BOX_COLOR[plateWidthTone(b.plateWidthPx)],
                  textShadow: '0 1px 3px rgba(0,0,0,.8)',
                  whiteSpace: 'nowrap',
                  pointerEvents: 'none',
                }}
              >
                {b.plateWidthPx}px
              </span>
            )}
          </div>
        ))}
      </div>

      {/* LIVE only while the picture really is moving: a paused tile held
          under the enlarged view is a still, and must not be badged live. */}
      {!camera.offline && badge !== null && showing && (
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
            {t('camera.noSignal')}
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
