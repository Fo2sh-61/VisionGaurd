/** Track a person — the two questions this page actually answers.
 *
 *      LIVE   "they are here now, don't lose them"
 *      PAST   "where did they go earlier"
 *
 *  Live is three clicks: pick the area's camera, click the body, and the
 *  engine follows it from there. Everything after that click is the engine's
 *  answer, polled — this page holds no opinion about where anybody is.
 *
 *  Rules this screen exists to keep, all of them about not claiming more than
 *  the system knows:
 *
 *  1. **A face names a person; clothing only says "same body".** Green means
 *     identified by face, blue means matched by clothing, amber means never
 *     identified at all. Never merged into one colour or one number.
 *
 *  2. **A name is not permanent.** A followed body shows amber "not
 *     identified" until a face has been recognised clearly, several times,
 *     over seconds — and the name goes the instant the track does. The engine
 *     enforces this; the page's job is to show the amber state honestly
 *     instead of hiding the wait.
 *
 *  3. **The stop conditions are the engine's, not the browser's.** A timer
 *     runs out and a track is lost whether or not this tab is open, so a
 *     closed laptop can never leave a camera recording.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useCameras } from '@/app/CameraContext';
import { useCapability } from '@/app/CapabilityContext';
import { useToday } from '@/app/SiteContext';
import { usePersonNames } from '@/app/useOptions';
import { CamGrid } from '@/components/CamGrid';
import { CameraFrame } from '@/components/CameraFrame';
import { Card, DataNotice, Empty, PageHeader } from '@/components/ui';
import { ApiError } from '@/services/http';
import {
  endFollow,
  estimateSweep,
  followStranger,
  getFollow,
  getLeg,
  getPathSkeleton,
  getSweep,
  legChunkUrl,
  startFollow,
  startFollowRecording,
  startLeg,
  startSweep,
  stopFollowRecording,
  stopSweep,
} from '@/services/api';
import { formatLongDate, formatTime } from '@/services/format';
import type * as W from '@/services/wire';
import type { Camera, DetectionBox } from '@/types';

/* ---------- evidence colours ----------
 *
 *  Fixed hex, not tokens: these sit on top of dark video and must not shift
 *  with the light/dark theme. They match --det-* in tokens.css. */
const FACE = '#3f8f74';
const CLOTH = '#5b9bd8';
const UNKNOWN = '#dfa23f';

type Mode = 'live' | 'past' | 'find';

/** How often the follow is re-read. The engine is the only thing that knows
 *  where the person is; this is just how quickly the screen catches up. */
const FOLLOW_POLL_MS = 1_000;

/** Cameras shown at once in the live grid. Small on purpose: every tile is a
 *  poll, and `CamGrid` scales its refresh to the number actually on screen, so
 *  a smaller page is a faster-looking one. */
const GRID_PAGE = 8;

/** How much video either side of a stop to fetch. Somebody walking into view
 *  is usually the part being asked about, and that happens a few seconds
 *  before their face was readable enough to anchor. */
const PADDING_MS = 5_000;

const TIMERS: { label: string; seconds: number | null }[] = [
  { label: 'Until I stop it', seconds: null },
  { label: '1 min', seconds: 60 },
  { label: '5 min', seconds: 300 },
  { label: '10 min', seconds: 600 },
];

const clock = (seconds: number) => {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};

/** The parsing trap this page solved once already: compare times as minutes,
 *  never as strings, and never against the viewer's clock. */
const minutes = (hhmm: string) => {
  const [h, m] = hhmm.split(':').map(Number);
  return Number.isFinite(h) && Number.isFinite(m) ? h * 60 + m : NaN;
};

export function TrackPerson() {
  const capability = useCapability('track');
  const today = useToday();
  const people = usePersonNames();
  const { cameras } = useCameras();

  const [mode, setMode] = useState<Mode>('live');

  return (
    <>
      <PageHeader
        title="Track a person"
        lead="Follow somebody across cameras now, or rebuild where they went earlier."
      />
      <DataNotice capability={capability} />

      <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
        {(['live', 'past', 'find'] as Mode[]).map((m) => (
          <button
            key={m}
            type="button"
            className={`chip-btn ${mode === m ? 'chip-btn--on' : 'chip-btn--off'}`}
            onClick={() => setMode(m)}
          >
            {m === 'live'
              ? 'Catch someone now'
              : m === 'past'
                ? 'Where did they go'
                : 'Search the footage'}
          </button>
        ))}
      </div>

      {mode === 'live' && <LiveMode cameras={cameras} />}
      {mode === 'past' && <PastMode people={people} today={today} />}
      {mode === 'find' && (
        <>
          <BrowseFootage cameras={cameras} today={today} />
          <SweepPanel cameras={cameras} people={people} today={today} />
        </>
      )}

      <Legend />
    </>
  );
}

/* =========================================================================
 * LIVE — catch someone now
 * ========================================================================= */

function LiveMode({ cameras }: { cameras: Camera[] }) {
  const [watching, setWatching] = useState<Camera | null>(null);
  const [follow, setFollow] = useState<W.FollowView | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  // The bodies the frame is currently drawing, in the same percentages it
  // draws them at. Kept so the pointer can tell whether it is over a person:
  // a crosshair that never changes gives no clue whether a click will land on
  // somebody or on the floor beside them, and clicking the floor is the one
  // failure this screen has.
  const [boxes, setBoxes] = useState<DetectionBox[]>([]);
  const [hovered, setHovered] = useState<DetectionBox | null>(null);

  /* The engine holds the session; this only catches up with it. In particular
   * a follow that ENDED server-side — the timer ran out, the track was lost —
   * arrives through this poll, which is the only way a browser that never
   * asked finds out. */
  const refresh = useCallback(async () => {
    try {
      setFollow(await getFollow());
    } catch {
      /* one dropped poll leaves the last answer on screen */
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), FOLLOW_POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  // Follow the person, not the camera the operator happened to open. When the
  // engine says they have walked into another camera's view, show that one.
  useEffect(() => {
    if (!follow || follow.endedReason) return;
    if (watching?.id === follow.cameraId) return;
    const next = cameras.find((c) => c.id === follow.cameraId);
    if (next) setWatching(next);
  }, [follow, cameras, watching?.id]);

  /** The smallest body under a point, so somebody standing in front of a
   *  larger box is picked rather than the crowd behind them. Mirrors the
   *  engine's own hit test, which is what makes the ring honest: what
   *  highlights here is what gets followed there. */
  const bodyAt = (x: number, y: number): DetectionBox | null => {
    const hits = boxes.filter(
      (b) =>
        x * 100 >= b.x && x * 100 <= b.x + b.w && y * 100 >= b.y && y * 100 <= b.y + b.h,
    );
    if (hits.length === 0) return null;
    return hits.reduce((a, b) => (a.w * a.h <= b.w * b.h ? a : b));
  };

  const fractions = (event: React.MouseEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return {
      x: (event.clientX - rect.left) / rect.width,
      y: (event.clientY - rect.top) / rect.height,
    };
  };

  const click = async (event: React.MouseEvent<HTMLDivElement>, camera: Camera) => {
    // Fractions of the tile, which is also how the boxes over it are
    // positioned. Matching the overlay is what matters: the operator is
    // clicking a body they can see outlined, so the click has to use the same
    // frame of reference the outline was drawn in.
    const { x, y } = fractions(event);
    if (x < 0 || x > 1 || y < 0 || y > 1) return;

    setBusy(true);
    setError('');
    try {
      setFollow(await startFollow(camera.id, x, y));
    } catch (err) {
      // Three refusals, three different meanings. Collapsing them would send
      // an operator to fix the wrong thing.
      const status = err instanceof ApiError ? err.status : 0;
      const detail = err instanceof ApiError ? err.message : 'Could not start following.';
      setError(
        status === 404
          ? 'Nobody there to follow — they may have moved. Click the person themselves.'
          : detail,
      );
    } finally {
      setBusy(false);
    }
  };

  const act = async (run: () => Promise<W.FollowView>) => {
    setBusy(true);
    setError('');
    try {
      setFollow(await run());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'That did not work.');
    } finally {
      setBusy(false);
    }
  };

  const active = follow && !follow.endedReason ? follow : null;

  return (
    <>
      {error && (
        <div
          role="status"
          style={{
            padding: '9px 13px',
            borderRadius: 9,
            marginBottom: 12,
            fontSize: 13,
            background: 'var(--am-bg)',
            color: 'var(--am)',
          }}
        >
          {error}
        </div>
      )}

      {follow && <FollowBanner follow={follow} />}

      {!watching && !active && (
        <Card>
          <Step
            n="1"
            title="Pick the camera they are on"
            sub="Grouped by area. Search if you know the name."
          />
        </Card>
      )}

      {watching ? (
        <Card>
          <Step
            n={active ? '3' : '2'}
            title={active ? 'Following' : 'Click the person'}
            sub={
              active
                ? 'The engine keeps hold of them. Nothing here decides where they are.'
                : 'Click the body itself — the outline you can see, not the space beside it.'
            }
          />

          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 10,
              margin: '4px 0 8px',
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 600 }}>
              {watching.name}
              <span style={{ color: 'var(--tx3)', fontWeight: 400 }}>
                {watching.area ? ` · ${watching.area}` : ''}
              </span>
            </div>
            <button
              type="button"
              className="linkbtn"
              onClick={() => {
                setWatching(null);
                setError('');
              }}
            >
              Back to the cameras
            </button>
          </div>

          <div
            onClick={active ? undefined : (e) => void click(e, watching)}
            onMouseMove={
              active
                ? undefined
                : (e) => {
                    const { x, y } = fractions(e);
                    setHovered(bodyAt(x, y));
                  }
            }
            onMouseLeave={() => setHovered(null)}
            style={{
              position: 'relative',
              cursor: active
                ? 'default'
                : busy
                  ? 'progress'
                  : hovered
                    ? 'pointer'
                    : 'crosshair',
            }}
            role="presentation"
          >
            <CameraFrame
              camera={watching}
              size="lg"
              live
              feature="track"
              onBoxes={setBoxes}
              badge={active?.recording?.state === 'recording' ? 'Recording' : 'LIVE'}
            />

            {/* What you are about to follow, marked before you commit to it.
                Positioned from the same numbers the frame drew the box with,
                so the ring cannot drift away from the body it describes. */}
            {hovered && !active && (
              <div
                style={{
                  position: 'absolute',
                  left: `${hovered.x}%`,
                  top: `${hovered.y}%`,
                  width: `${hovered.w}%`,
                  height: `${hovered.h}%`,
                  border: '2px solid #fff',
                  borderRadius: 4,
                  boxShadow: '0 0 0 2px rgba(0,0,0,.45)',
                  pointerEvents: 'none',
                }}
              />
            )}
          </div>

          {!active && (
            <div style={{ fontSize: 12, color: 'var(--tx3)', marginTop: 6 }}>
              {boxes.length === 0
                ? 'Nobody is being tracked on this camera right now. Step into view.'
                : hovered
                  ? 'Click to follow this person.'
                  : `${boxes.length} ${boxes.length === 1 ? 'person' : 'people'} in view — hover one to pick them out.`}
            </div>
          )}

          {active && <RecordPanel follow={active} busy={busy} act={act} />}

          {active && (
            <div style={{ marginTop: 12 }}>
              <button
                type="button"
                className="chip-btn chip-btn--off"
                disabled={busy}
                onClick={() => void act(endFollow)}
              >
                Stop following
              </button>
            </div>
          )}
        </Card>
      ) : (
        <CamGrid
          title="Cameras"
          note="Pick the one they are on. Click a person in the enlarged view to follow them."
          cameras={[]}
          byArea
          searchable
          pageSize={GRID_PAGE}
          activeId={active?.cameraId}
          onPick={(cam) => {
            setWatching(cam);
            setError('');
          }}
        />
      )}

      {active && active.trail.length > 1 && <Trail hops={active.trail} />}
    </>
  );
}

/** Who the engine thinks this is, said plainly — including when it does not
 *  know yet, which is most of the first few seconds. */
function FollowBanner({ follow }: { follow: W.FollowView }) {
  const named = !!follow.name;
  const over = !!follow.endedReason;
  const tone = over ? 'var(--tx3)' : named ? FACE : UNKNOWN;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '11px 15px',
        borderRadius: 10,
        marginBottom: 12,
        background: 'var(--panel)',
        borderLeft: `3px solid ${tone}`,
      }}
    >
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontSize: 14.5, fontWeight: 700, color: tone }}>
          {over
            ? follow.endedReason === 'track lost'
              ? 'Lost them'
              : `Stopped — ${follow.endedReason}`
            : named
              ? follow.name
              : 'Following an unidentified person'}
        </div>
        <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginTop: 1 }}>
          {over ? (
            follow.endedReason === 'track lost' ? (
              // Said in full, because the alternative reading — that the name
              // is still valid somewhere — is the exact belief that once put
              // one person's name on everybody.
              'The track broke, so any name went with it. Nothing is being followed.'
            ) : (
              'Nothing is being followed.'
            )
          ) : named ? (
            <>
              Identified by face · {follow.cameraName} · {follow.place}
            </>
          ) : (
            <>
              Not identified yet — following the body. A name appears once a face has
              been seen clearly, several times. · {follow.cameraName}
            </>
          )}
        </div>
      </div>
      <div style={{ fontSize: 11.5, color: 'var(--tx3)', whiteSpace: 'nowrap' }}>
        {follow.stableId}
      </div>
    </div>
  );
}

function RecordPanel({
  follow,
  busy,
  act,
}: {
  follow: W.FollowView;
  busy: boolean;
  act: (run: () => Promise<W.FollowView>) => Promise<void>;
}) {
  const [timer, setTimer] = useState<number | null>(300);
  const recording = follow.recording;
  const running = recording?.state === 'recording';

  return (
    <div style={{ marginTop: 12, padding: 13, borderRadius: 10, background: 'var(--bg)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        {running ? (
          <>
            <button
              type="button"
              className="chip-btn chip-btn--on"
              disabled={busy}
              onClick={() => void act(stopFollowRecording)}
            >
              Stop recording
            </button>
            <span style={{ fontSize: 12.5, color: 'var(--tx2)' }}>
              {recording?.timerSecondsLeft != null
                ? `Stops itself in ${clock(recording.timerSecondsLeft)}`
                : 'Runs until you stop it'}
            </span>
          </>
        ) : (
          <>
            <button
              type="button"
              className="chip-btn chip-btn--off"
              disabled={busy}
              onClick={() => void act(() => startFollowRecording(timer))}
            >
              Record
            </button>
            {TIMERS.map((t) => (
              <button
                key={t.label}
                type="button"
                className={`chip-btn ${timer === t.seconds ? 'chip-btn--on' : 'chip-btn--off'}`}
                onClick={() => setTimer(t.seconds)}
              >
                {t.label}
              </button>
            ))}
          </>
        )}
      </div>

      <div style={{ fontSize: 12, color: 'var(--tx3)', marginTop: 8 }}>
        One file per camera they cross. It stops by itself if the timer runs out or the
        track is lost, so closing this tab cannot leave a camera recording.
      </div>

      {recording && recording.segments.length > 0 && (
        <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {recording.segments.map((s) => (
            <div
              key={s.id}
              style={{
                display: 'flex',
                alignItems: 'baseline',
                gap: 8,
                fontSize: 12.5,
                color: 'var(--tx2)',
              }}
            >
              <span style={{ fontWeight: 600, color: 'var(--tx)' }}>
                {s.cameraName ?? s.cameraId}
              </span>
              <span>{formatTime(s.startedAt)}</span>
              <span>· {s.seconds.toFixed(0)}s</span>
              <span>
                ·{' '}
                {s.state === 'recording'
                  ? 'recording'
                  : s.state === 'failed'
                    ? `failed — ${s.reason ?? 'no reason given'}`
                    : (s.reason ?? 'stopped')}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Trail({ hops }: { hops: W.TrailHop[] }) {
  return (
    <Card>
      <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 8 }}>Where they have been</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {hops.map((hop, i) => (
          <div
            key={`${hop.cameraId}-${hop.at.utc}-${i}`}
            style={{ display: 'flex', alignItems: 'baseline', gap: 10, fontSize: 13 }}
          >
            <span
              style={{
                width: 9,
                height: 9,
                borderRadius: '50%',
                background: CLOTH,
                flexShrink: 0,
              }}
            />
            <span style={{ fontWeight: 600 }}>{formatTime(hop.at)}</span>
            <span>{hop.cameraName}</span>
            <span style={{ color: 'var(--tx3)' }}>{hop.place}</span>
          </div>
        ))}
      </div>
      <div style={{ fontSize: 12, color: 'var(--tx3)', marginTop: 8 }}>
        Same body, camera to camera. That is a claim about continuity, not about who
        anybody is.
      </div>
    </Card>
  );
}

/* =========================================================================
 * PAST — where did they go
 * ========================================================================= */

function PastMode({ people, today }: { people: string[]; today: string }) {
  const [who, setWho] = useState('');
  const [date, setDate] = useState(today);
  const [from, setFrom] = useState('07:00');
  const [to, setTo] = useState('08:15');
  const [path, setPath] = useState<W.PathSkeleton | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!date) setDate(today);
  }, [today, date]);

  // Minutes, never strings, and never against the viewer's clock. Comparing
  // "09:00" with "10:00" as text happens to work and comparing "9:00" with
  // "10:00" does not, which is the kind of bug that only shows up at 9am.
  const windowOk = useMemo(() => {
    const a = minutes(from);
    const b = minutes(to);
    return Number.isFinite(a) && Number.isFinite(b) && a < b;
  }, [from, to]);

  const run = async () => {
    if (!who || !windowOk) return;
    setLoading(true);
    setError('');
    try {
      setPath(await getPathSkeleton(who, date, from, to));
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      setError(
        status === 404
          ? `Nobody here is called “${who}”. Check the spelling, or pick them from the list.`
          : err instanceof ApiError
            ? err.message
            : 'Could not build that path.',
      );
      setPath(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <Card>
        <Step
          n="1"
          title="Who, and when"
          sub="Answers straight away — it is read from what was already recognised, not searched for now. Every search is written to the audit trail."
        />
        <div className="row" style={{ gridTemplateColumns: '2fr 1fr 1fr 1fr auto', gap: 10 }}>
          <Labelled label="Person">
            <input
              list="track-people"
              value={who}
              onChange={(e) => setWho(e.target.value)}
              placeholder="Name"
            />
            <datalist id="track-people">
              {people.map((n) => (
                <option key={n} value={n} />
              ))}
            </datalist>
          </Labelled>
          <Labelled label="Date">
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </Labelled>
          <Labelled label="From">
            <input type="time" value={from} onChange={(e) => setFrom(e.target.value)} />
          </Labelled>
          <Labelled label="To">
            <input type="time" value={to} onChange={(e) => setTo(e.target.value)} />
          </Labelled>
          <div style={{ display: 'flex', alignItems: 'flex-end' }}>
            <button
              type="button"
              className="chip-btn chip-btn--on"
              disabled={!who || !windowOk || loading}
              onClick={() => void run()}
            >
              {loading ? 'Looking…' : 'Show their path'}
            </button>
          </div>
        </div>
        {!windowOk && (
          <div style={{ fontSize: 12.5, color: 'var(--am)', marginTop: 8 }}>
            The end of the window has to come after the start.
          </div>
        )}
        {error && <div style={{ fontSize: 12.5, color: 'var(--am)', marginTop: 8 }}>{error}</div>}
      </Card>

      {path && <Skeleton path={path} from={from} to={to} />}
    </>
  );
}

/** The stop chain. Green stops are the skeleton; blue ones are the same body,
 *  and are never named because clothing cannot say who anybody is. */
function Skeleton({
  path,
  from,
  to,
}: {
  path: W.PathSkeleton;
  from: string;
  to: string;
}) {
  const name = path.subject.name ?? path.subject.id ?? 'this person';
  const nothing = path.anchors.length === 0 && path.appearance.length === 0;
  const [leg, setLeg] = useState<W.LegJob | null>(null);
  const [legError, setLegError] = useState('');
  const [opening, setOpening] = useState('');

  // A stop is a span, so the video asked for is that span with a little
  // either side — somebody walking into view is usually the part being asked
  // about, and it happens just before the face was readable.
  const watch = async (a: W.PathAnchor) => {
    setOpening(a.cameraId + a.at.utc);
    setLegError('');
    try {
      const from = new Date(new Date(a.at.utc).getTime() - PADDING_MS);
      const until = new Date(new Date(a.until.utc).getTime() + PADDING_MS);
      setLeg(
        await startLeg({
          cameraId: a.cameraId,
          start: from.toISOString(),
          end: until.toISOString(),
          personId: path.subject.id ?? null,
        }),
      );
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      setLegError(
        status === 503
          ? (err as ApiError).message
          : status === 409
            ? 'The engine is already fetching as much video as it can keep up with. Try again in a moment.'
            : err instanceof ApiError
              ? err.message
              : 'That video could not be fetched.',
      );
    } finally {
      setOpening('');
    }
  };

  return (
    <Card>
      <div style={{ fontWeight: 700, fontSize: 15.5 }}>{name}</div>
      <div style={{ fontSize: 12.5, color: 'var(--tx3)', marginBottom: 12 }}>
        {formatLongDate(path.date)} · {from} to {to} ·{' '}
        {path.anchors.length === 0
          ? 'not identified anywhere'
          : `${path.anchors.length} ${path.anchors.length === 1 ? 'stop' : 'stops'}`}
      </div>

      {nothing ? (
        <Empty>
          Nobody recognised {name} anywhere in that window. That is not the same as
          them not being there — widen the window, try another day, or look at a
          camera's footage directly.
        </Empty>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {path.anchors.map((a) => (
            <AnchorRow
              key={`${a.cameraId}-${a.at.utc}`}
              anchor={a}
              busy={opening === a.cameraId + a.at.utc}
              onWatch={() => void watch(a)}
            />
          ))}

          {path.appearance.length > 0 && (
            <>
              <div
                style={{
                  fontSize: 12,
                  fontWeight: 700,
                  letterSpacing: 0.3,
                  textTransform: 'uppercase',
                  color: 'var(--tx3)',
                  marginTop: 6,
                }}
              >
                Same body, not identified
              </div>
              {path.appearance.map((s, i) => (
                <div
                  key={`${s.cameraId}-${s.at.utc}-${i}`}
                  style={{ display: 'flex', alignItems: 'baseline', gap: 10, fontSize: 13 }}
                >
                  <span
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: 2,
                      background: CLOTH,
                      flexShrink: 0,
                    }}
                  />
                  <span style={{ fontWeight: 600, minWidth: 62 }}>{formatTime(s.at)}</span>
                  <span style={{ fontWeight: 600 }}>{s.place}</span>
                  <span style={{ color: 'var(--tx3)' }}>{s.cameraName}</span>
                </div>
              ))}
              <div style={{ fontSize: 12, color: 'var(--tx3)' }}>
                Clothing matched, no face was read. That says the same body moved
                through, not who it was.
              </div>
            </>
          )}
        </div>
      )}

      {legError && (
        <div style={{ fontSize: 12.5, color: 'var(--am)', marginTop: 10 }}>{legError}</div>
      )}

      {leg && <LegPlayer leg={leg} onClose={() => setLeg(null)} />}
    </Card>
  );
}

/** One green stop, with the evidence that earned it on hover.
 *
 *  Rule 5: the number shown is the one the engine measured. "6 matches over 4
 *  seconds, best 0.71" is checkable; "high confidence" is not. */
function AnchorRow({
  anchor,
  busy,
  onWatch,
}: {
  anchor: W.PathAnchor;
  busy: boolean;
  onWatch: () => void;
}) {
  const seconds = Math.max(
    0,
    (new Date(anchor.until.utc).getTime() - new Date(anchor.at.utc).getTime()) / 1000,
  );
  const why = `${anchor.matches} ${anchor.matches === 1 ? 'match' : 'matches'} over ${seconds.toFixed(
    seconds < 10 ? 1 : 0,
  )}s · best ${anchor.score.toFixed(2)} · face ${anchor.facePx}px`;

  return (
    <div
      title={why}
      style={{ display: 'flex', alignItems: 'baseline', gap: 10, fontSize: 13 }}
    >
      <span
        style={{ width: 10, height: 10, borderRadius: '50%', background: FACE, flexShrink: 0 }}
      />
      <span style={{ fontWeight: 600, minWidth: 62 }}>{formatTime(anchor.at)}</span>
      <span style={{ fontWeight: 600 }}>{anchor.place}</span>
      <span style={{ color: 'var(--tx3)' }}>{anchor.cameraName}</span>
      <span style={{ color: 'var(--tx3)', fontSize: 11.5, marginLeft: 'auto' }}>{why}</span>
      <button type="button" className="linkbtn" disabled={busy} onClick={onWatch}>
        {busy ? 'Fetching…' : 'Watch'}
      </button>
    </div>
  );
}

/* =========================================================================
 * The video behind a stop
 * ========================================================================= */

/** How often a running leg is re-read. Pieces land every few seconds, so this
 *  is fast enough to feel immediate and slow enough not to be a load. */
const LEG_POLL_MS = 1_500;

/** Plays a leg piece by piece, starting on the first that lands.
 *
 *  The honesty here is in the waiting line. A spinner with no number behind it
 *  says nothing, so this shows how many pieces are ready out of how many, and
 *  the expected wait ONLY when the machine has actually been measured. With no
 *  measurement it says so and names the tool, rather than inventing a number
 *  that reads exactly like a real one. */
function LegPlayer({
  leg,
  onClose,
  onPickBody,
}: {
  leg: W.LegJob;
  onClose: () => void;
  /** Set on the footage-browsing view: clicking a body follows it onto other
   *  cameras. Absent everywhere else, because clicking a body inside somebody
   *  else's path is not a question anybody is asking there. */
  onPickBody?: (point: { jobId: string; chunk: number; x: number; y: number }) => void;
}) {
  const [job, setJob] = useState<W.LegJob>(leg);
  const [piece, setPiece] = useState(0);
  const [failed, setFailed] = useState('');
  const video = useRef<HTMLVideoElement | null>(null);

  const running = job.job.state === 'queued' || job.job.state === 'running';

  useEffect(() => {
    if (!running) return;
    let alive = true;
    const tick = () => {
      void getLeg(job.job.id)
        .then((next) => {
          if (alive) setJob(next);
        })
        .catch(() => {
          /* a dropped poll leaves the pieces already on screen playable */
        });
    };
    const timer = setInterval(tick, LEG_POLL_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [running, job.job.id]);

  // Advance to the next piece the moment this one ends, so a leg plays as one
  // stretch of video rather than as a row of separate clips.
  const next = () => {
    if (piece + 1 < job.chunkUrls.length) setPiece(piece + 1);
  };

  const url = job.chunkUrls[piece];
  const waitingForMore = piece >= job.chunkUrls.length && running;

  return (
    <Card>
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: 10,
          marginBottom: 10,
        }}
      >
        <div>
          <div style={{ fontWeight: 700, fontSize: 15.5 }}>{job.cameraName}</div>
          <div style={{ fontSize: 12.5, color: 'var(--tx3)' }}>
            {job.place} · {formatTime(job.start)} · {job.seconds.toFixed(0)} seconds of
            recorded video
          </div>
        </div>
        <button type="button" className="linkbtn" onClick={onClose}>
          Close
        </button>
      </div>

      {job.job.state === 'failed' ? (
        <Empty>
          {job.job.error ??
            'That video could not be fetched from the recorder. Nothing was lost — try the stop again.'}
        </Empty>
      ) : url ? (
        <>
          <video
            ref={video}
            key={url}
            src={legChunkUrl(url)}
            controls
            autoPlay
            onEnded={next}
            onClick={
              onPickBody
                ? (e) => {
                    // Fractions of the frame, the same units the outlines
                    // were burnt in at, so a click lands on the body the
                    // operator can see marked.
                    const rect = e.currentTarget.getBoundingClientRect();
                    onPickBody({
                      jobId: job.job.id,
                      chunk: piece,
                      x: (e.clientX - rect.left) / rect.width,
                      y: (e.clientY - rect.top) / rect.height,
                    });
                  }
                : undefined
            }
            onError={() =>
              setFailed('That piece of video would not play. It may have been replaced.')
            }
            style={{
              width: '100%',
              borderRadius: 10,
              background: '#000',
              display: 'block',
              cursor: onPickBody ? 'crosshair' : undefined,
            }}
          />
          {onPickBody && (
            <div style={{ fontSize: 12, color: 'var(--tx3)', marginTop: 6 }}>
              Pause where you can see them, then click the person to follow that body
              onto the other cameras.
            </div>
          )}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              marginTop: 8,
              fontSize: 12.5,
              color: 'var(--tx2)',
              flexWrap: 'wrap',
            }}
          >
            <button
              type="button"
              className="linkbtn"
              disabled={piece === 0}
              onClick={() => setPiece(piece - 1)}
            >
              Back 30s
            </button>
            <span>
              Piece {piece + 1} of {job.chunksTotal || job.chunkUrls.length}
            </span>
            <button
              type="button"
              className="linkbtn"
              disabled={piece + 1 >= job.chunkUrls.length}
              onClick={next}
            >
              Forward 30s
            </button>
            {running && (
              <span style={{ color: 'var(--tx3)' }}>
                · fetching the next 30 seconds…
              </span>
            )}
          </div>
        </>
      ) : (
        <Waiting job={job} />
      )}

      {waitingForMore && (
        <div style={{ fontSize: 12.5, color: 'var(--tx3)', marginTop: 8 }}>
          That is everything fetched so far. The next piece is still being built.
        </div>
      )}
      {failed && (
        <div style={{ fontSize: 12.5, color: 'var(--am)', marginTop: 8 }}>{failed}</div>
      )}
      {!running && job.chunkUrls.length > 0 && (
        <div style={{ fontSize: 12, color: 'var(--tx3)', marginTop: 8 }}>
          Outlines are burnt into the video, so each piece is evidence on its own — it
          still shows them on a machine with none of this open.
        </div>
      )}
    </Card>
  );
}

/** The wait, with a real number behind it or an honest admission that there
 *  is not one. */
function Waiting({ job }: { job: W.LegJob }) {
  const ready = job.chunksReady;
  const total = job.chunksTotal || 1;

  return (
    <div style={{ padding: '18px 4px' }}>
      <div style={{ fontSize: 13.5, fontWeight: 600 }}>
        Fetching the video from the recorder…
      </div>
      <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginTop: 4 }}>
        {ready} of {total} {total === 1 ? 'piece' : 'pieces'} ready. It starts playing as
        soon as the first one lands.
      </div>
      <div
        style={{
          height: 5,
          borderRadius: 3,
          background: 'var(--panel)',
          marginTop: 10,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${Math.round((job.job.progress || 0) * 100)}%`,
            height: '100%',
            background: 'var(--ac)',
            transition: 'width .3s',
          }}
        />
      </div>
      <div style={{ fontSize: 12, color: 'var(--tx3)', marginTop: 8 }}>
        {job.estimateSeconds != null
          ? `About ${Math.max(1, Math.round(job.estimateSeconds))} seconds in total, from what this machine was measured at.`
          : 'Nobody has measured how fast this machine reads recorded video, so there is no expected time to give you. Run engine/tools/measure_track.py to get one.'}
      </div>
    </div>
  );
}


/* ---------- small pieces ---------- */

function Step({ n, title, sub }: { n: string; title: string; sub: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 10 }}>
      <div
        style={{
          width: 22,
          height: 22,
          borderRadius: 7,
          background: 'var(--panel)',
          color: 'var(--tx2)',
          fontSize: 11.5,
          fontWeight: 700,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
        }}
      >
        {n}
      </div>
      <div>
        <div style={{ fontWeight: 700, fontSize: 15.5 }}>{title}</div>
        <div style={{ fontSize: 12.5, color: 'var(--tx2)' }}>{sub}</div>
      </div>
    </div>
  );
}

function Labelled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--tx2)' }}>{label}</span>
      {children}
    </label>
  );
}

/** Three kinds of evidence, named in words. Colour alone would not survive a
 *  colour-blind operator or a printed report. */
function Legend() {
  const items = [
    { t: 'Identified by face', c: FACE, round: true },
    { t: 'Clothing match only', c: CLOTH, round: false },
    { t: 'Not identified', c: UNKNOWN, round: false },
  ];
  return (
    <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', margin: '14px 0' }}>
      {items.map((g) => (
        <div
          key={g.t}
          style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 12, color: 'var(--tx2)' }}
        >
          <span
            style={{ width: 11, height: 11, borderRadius: g.round ? '50%' : 2, background: g.c }}
          />
          {g.t}
        </div>
      ))}
    </div>
  );
}

/* =========================================================================
 * Sweeping a window, and following somebody who was never enrolled
 * ========================================================================= */

const SWEEP_POLL_MS = 2_000;

/** The wide net.
 *
 *  The rule this panel exists to keep: the cost is stated before anything
 *  runs, and the run button does not work until the arithmetic says it is
 *  affordable. An operator should never discover a fifteen-minute wait by
 *  starting it. */
function SweepPanel({
  cameras,
  people,
  today,
}: {
  cameras: Camera[];
  people: string[];
  today: string;
}) {
  const [who, setWho] = useState('');
  const [date, setDate] = useState(today);
  const [from, setFrom] = useState('07:00');
  const [to, setTo] = useState('08:00');
  const [area, setArea] = useState('');
  const [estimate, setEstimate] = useState<W.SweepEstimate | null>(null);
  const [job, setJob] = useState<W.SweepJob | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const areas = useMemo(() => {
    const named = new Set<string>();
    for (const cam of cameras) if (cam.area) named.add(cam.area);
    return [...named].sort();
  }, [cameras]);

  const request = (): W.SweepRequest => ({
    person: who,
    start: new Date(`${date}T${from}:00`).toISOString(),
    end: new Date(`${date}T${to}:00`).toISOString(),
    areas: area ? [area] : [],
  });

  const windowOk = minutes(from) < minutes(to);

  // Any change invalidates the estimate. Running against a stale one would be
  // exactly the surprise the estimate exists to prevent.
  useEffect(() => {
    setEstimate(null);
  }, [who, date, from, to, area]);

  const price = async () => {
    setBusy(true);
    setError('');
    try {
      setEstimate(await estimateSweep(request()));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not work out the cost.');
    } finally {
      setBusy(false);
    }
  };

  const run = async () => {
    setBusy(true);
    setError('');
    try {
      setJob(await startSweep(request()));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'That sweep would not start.');
    } finally {
      setBusy(false);
    }
  };

  const running = job?.job.state === 'queued' || job?.job.state === 'running';
  useEffect(() => {
    if (!job || !running) return;
    let alive = true;
    const timer = setInterval(() => {
      void getSweep(job.job.id)
        .then((next) => {
          if (alive) setJob(next);
        })
        .catch(() => {
          /* a dropped poll leaves the hits already found on screen */
        });
    }, SWEEP_POLL_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [job, running]);

  return (
    <Card>
      <Step
        n="2"
        title="Or search a whole window"
        sub="Slower, and it says how much slower before it starts."
      />

      <div className="row" style={{ gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr', gap: 10 }}>
        <Labelled label="Person">
          <input
            list="sweep-people"
            value={who}
            onChange={(e) => setWho(e.target.value)}
            placeholder="Name"
          />
          <datalist id="sweep-people">
            {people.map((n) => (
              <option key={n} value={n} />
            ))}
          </datalist>
        </Labelled>
        <Labelled label="Date">
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </Labelled>
        <Labelled label="From">
          <input type="time" value={from} onChange={(e) => setFrom(e.target.value)} />
        </Labelled>
        <Labelled label="To">
          <input type="time" value={to} onChange={(e) => setTo(e.target.value)} />
        </Labelled>
        <Labelled label="Where">
          <select value={area} onChange={(e) => setArea(e.target.value)}>
            <option value="">Everywhere</option>
            {areas.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </Labelled>
      </div>

      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 12 }}>
        <button
          type="button"
          className="chip-btn chip-btn--off"
          disabled={!who || !windowOk || busy}
          onClick={() => void price()}
        >
          {busy && !estimate ? 'Working it out…' : 'What would this cost?'}
        </button>
        <button
          type="button"
          className="chip-btn chip-btn--on"
          // Deliberately not enabled until the arithmetic has been seen AND
          // says yes. Nobody starts a fifteen-minute wait by accident.
          disabled={!estimate?.allowed || busy || running}
          onClick={() => void run()}
        >
          Run the sweep
        </button>
      </div>

      {!windowOk && (
        <div style={{ fontSize: 12.5, color: 'var(--am)', marginTop: 8 }}>
          The end of the window has to come after the start.
        </div>
      )}

      {estimate && <EstimateLine estimate={estimate} />}
      {error && <div style={{ fontSize: 12.5, color: 'var(--am)', marginTop: 8 }}>{error}</div>}

      {job && (
        <div style={{ marginTop: 14 }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              fontSize: 13,
              flexWrap: 'wrap',
            }}
          >
            <span style={{ fontWeight: 600 }}>
              {running ? 'Searching…' : job.job.error === 'stopped' ? 'Stopped' : 'Finished'}
            </span>
            <span style={{ color: 'var(--tx2)' }}>
              {job.segmentsDone} of {job.segmentsTotal} pieces
              {job.segmentsMissing > 0 && ` (${job.segmentsMissing} with no video)`} ·{' '}
              {job.hits.length} {job.hits.length === 1 ? 'hit' : 'hits'}
            </span>
            {running && (
              <button
                type="button"
                className="linkbtn"
                onClick={() => void stopSweep(job.job.id).then(setJob)}
              >
                Stop
              </button>
            )}
          </div>

          {job.job.error === 'stopped' && (
            <div style={{ fontSize: 12, color: 'var(--tx3)', marginTop: 4 }}>
              These are the hits found before it was stopped, not everything there was.
            </div>
          )}

          <div
            style={{
              height: 5,
              borderRadius: 3,
              background: 'var(--panel)',
              margin: '8px 0',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                width: `${Math.round(job.job.progress * 100)}%`,
                height: '100%',
                background: 'var(--ac)',
                transition: 'width .3s',
              }}
            />
          </div>

          {job.hits.length === 0 && !running ? (
            <Empty>
              {job.segmentsMissing >= job.segmentsTotal
                ? // Nothing was examined. Saying "nobody was found" here would
                  // be the single most misleading sentence on the page: it
                  // reads as evidence they were not there, when in fact not
                  // one second of video was looked at.
                  'None of that window is in the archive, so nothing was searched. ' +
                  'This says nothing about where they were — there is simply no ' +
                  'recorded video from then.'
                : job.segmentsMissing > 0
                  ? `Nobody matching was found. Note that ${job.segmentsMissing} of ` +
                    `${job.segmentsTotal} pieces had no recorded video behind them, ` +
                    'so that part of the window was never searched.'
                  : 'Nobody matching was found on those cameras in that window. ' +
                    'That is an answer about what was recorded, not proof they were ' +
                    'not there.'}
            </Empty>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {job.hits.map((hit, i) => (
                <div
                  key={`${hit.cameraId}-${hit.at.utc}-${i}`}
                  style={{ display: 'flex', alignItems: 'baseline', gap: 10, fontSize: 13 }}
                >
                  <span
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: hit.match === 'face' ? '50%' : 2,
                      background: hit.match === 'face' ? FACE : CLOTH,
                      flexShrink: 0,
                    }}
                  />
                  <span style={{ fontWeight: 600, minWidth: 62 }}>{formatTime(hit.at)}</span>
                  <span style={{ fontWeight: 600 }}>{hit.place}</span>
                  <span style={{ color: 'var(--tx3)' }}>{hit.cameraName}</span>
                  <span style={{ color: 'var(--tx3)', fontSize: 11.5, marginLeft: 'auto' }}>
                    {hit.match === 'face'
                      ? `${hit.matches} matches · best ${hit.score.toFixed(2)}`
                      : `same body · ${hit.matches} looks`}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

/** The arithmetic, in words. Never a spinner, and never a number nobody
 *  measured. */
function EstimateLine({ estimate }: { estimate: W.SweepEstimate }) {
  const tone = estimate.allowed ? 'var(--tx2)' : 'var(--am)';
  return (
    <div
      style={{
        marginTop: 10,
        padding: '9px 13px',
        borderRadius: 9,
        fontSize: 12.5,
        color: tone,
        background: estimate.allowed ? 'var(--bg)' : 'var(--am-bg)',
      }}
    >
      {estimate.allowed ? (
        <>
          About {Math.max(1, Math.round(estimate.seconds / 60))} minute
          {estimate.seconds >= 120 ? 's' : ''} — {estimate.cameras}{' '}
          {estimate.cameras === 1 ? 'camera' : 'cameras'}, {estimate.cameraHours.toFixed(2)}{' '}
          camera-hours of video, at the speed this machine was measured at.
        </>
      ) : (
        estimate.reason
      )}
    </div>
  );
}

/** Open a camera's recorded video at a moment, so a person nobody enrolled
 *  can be picked out of it. */
function BrowseFootage({ cameras, today }: { cameras: Camera[]; today: string }) {
  const [cameraId, setCameraId] = useState(cameras[0]?.id ?? '');
  const [date, setDate] = useState(today);
  const [time, setTime] = useState('12:00');
  const [leg, setLeg] = useState<W.LegJob | null>(null);
  const [hunt, setHunt] = useState<W.SweepJob | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!cameraId && cameras[0]) setCameraId(cameras[0].id);
  }, [cameras, cameraId]);

  const open = async () => {
    setBusy(true);
    setError('');
    setHunt(null);
    try {
      const start = new Date(`${date}T${time}:00`);
      setLeg(
        await startLeg({
          cameraId,
          start: start.toISOString(),
          end: new Date(start.getTime() + 2 * 60_000).toISOString(),
          personId: null,
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'That footage could not be opened.');
    } finally {
      setBusy(false);
    }
  };

  const follow = async (point: { jobId: string; chunk: number; x: number; y: number }) => {
    setBusy(true);
    setError('');
    try {
      const start = new Date(`${date}T${time}:00`);
      setHunt(
        await followStranger(point, {
          person: '',
          start: start.toISOString(),
          end: new Date(start.getTime() + 10 * 60_000).toISOString(),
        }),
      );
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : 'That body could not be followed.',
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <Step
        n="1"
        title="Open a camera's recorded video"
        sub="For somebody who was never enrolled: find them in the footage, then click them."
      />

      <div className="row" style={{ gridTemplateColumns: '2fr 1fr 1fr auto', gap: 10 }}>
        <Labelled label="Camera">
          <select value={cameraId} onChange={(e) => setCameraId(e.target.value)}>
            {cameras.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
                {c.area ? ` · ${c.area}` : ''}
              </option>
            ))}
          </select>
        </Labelled>
        <Labelled label="Date">
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </Labelled>
        <Labelled label="From">
          <input type="time" value={time} onChange={(e) => setTime(e.target.value)} />
        </Labelled>
        <div style={{ display: 'flex', alignItems: 'flex-end' }}>
          <button
            type="button"
            className="chip-btn chip-btn--on"
            disabled={!cameraId || busy}
            onClick={() => void open()}
          >
            {busy ? 'Opening…' : 'Open footage'}
          </button>
        </div>
      </div>

      {error && <div style={{ fontSize: 12.5, color: 'var(--am)', marginTop: 8 }}>{error}</div>}

      {leg && (
        <div style={{ marginTop: 12 }}>
          <LegPlayer leg={leg} onClose={() => setLeg(null)} onPickBody={follow} />
        </div>
      )}

      {hunt && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontWeight: 700, fontSize: 14 }}>Where that body turns up</div>
          <div style={{ fontSize: 12, color: 'var(--tx3)', margin: '2px 0 8px' }}>
            Matched by clothing and build. That says the same body moved through — it
            does not say who they are, and no name will appear here.
          </div>
          {hunt.hits.length === 0 ? (
            <div style={{ fontSize: 12.5, color: 'var(--tx2)' }}>
              {hunt.job.state === 'done'
                ? 'Nothing that looks like them on the other cameras in that window.'
                : `Looking… ${hunt.segmentsDone} of ${hunt.segmentsTotal} pieces.`}
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {hunt.hits.map((hit, i) => (
                <div
                  key={`${hit.cameraId}-${hit.at.utc}-${i}`}
                  style={{ display: 'flex', alignItems: 'baseline', gap: 10, fontSize: 13 }}
                >
                  <span
                    style={{ width: 10, height: 10, borderRadius: 2, background: CLOTH }}
                  />
                  <span style={{ fontWeight: 600, minWidth: 62 }}>{formatTime(hit.at)}</span>
                  <span style={{ fontWeight: 600 }}>{hit.place}</span>
                  <span style={{ color: 'var(--tx3)' }}>{hit.cameraName}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
