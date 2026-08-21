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

import { useCallback, useEffect, useMemo, useState } from 'react';
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
  getFollow,
  getPathSkeleton,
  startFollow,
  startFollowRecording,
  stopFollowRecording,
} from '@/services/api';
import { formatLongDate, formatTime } from '@/services/format';
import type * as W from '@/services/wire';
import type { Camera } from '@/types';

/* ---------- evidence colours ----------
 *
 *  Fixed hex, not tokens: these sit on top of dark video and must not shift
 *  with the light/dark theme. They match --det-* in tokens.css. */
const FACE = '#3f8f74';
const CLOTH = '#5b9bd8';
const UNKNOWN = '#dfa23f';

type Mode = 'live' | 'past';

/** How often the follow is re-read. The engine is the only thing that knows
 *  where the person is; this is just how quickly the screen catches up. */
const FOLLOW_POLL_MS = 1_000;

/** Cameras shown at once in the live grid. Small on purpose: every tile is a
 *  poll, and `CamGrid` scales its refresh to the number actually on screen, so
 *  a smaller page is a faster-looking one. */
const GRID_PAGE = 8;

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
        {(['live', 'past'] as Mode[]).map((m) => (
          <button
            key={m}
            type="button"
            className={`chip-btn ${mode === m ? 'chip-btn--on' : 'chip-btn--off'}`}
            onClick={() => setMode(m)}
          >
            {m === 'live' ? 'Catch someone now' : 'Where did they go'}
          </button>
        ))}
      </div>

      {mode === 'live' ? (
        <LiveMode cameras={cameras} />
      ) : (
        <PastMode people={people} today={today} />
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

  const click = async (event: React.MouseEvent<HTMLDivElement>, camera: Camera) => {
    // Fractions of the tile, which is also how the boxes over it are
    // positioned. Matching the overlay is what matters: the operator is
    // clicking a body they can see outlined, so the click has to use the same
    // frame of reference the outline was drawn in.
    const rect = event.currentTarget.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width;
    const y = (event.clientY - rect.top) / rect.height;
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
            onClick={(e) => void click(e, watching)}
            style={{ cursor: busy ? 'progress' : 'crosshair' }}
            role="presentation"
          >
            <CameraFrame
              camera={watching}
              size="lg"
              live
              feature="track"
              badge={active?.recording?.state === 'recording' ? 'Recording' : 'LIVE'}
            />
          </div>

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
            <AnchorRow key={`${a.cameraId}-${a.at.utc}`} anchor={a} />
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

      <div
        style={{
          marginTop: 14,
          paddingTop: 12,
          borderTop: '1px solid var(--line)',
          fontSize: 12,
          color: 'var(--tx3)',
        }}
      >
        Video for each stop arrives in the next release. Until then this is the record
        of where they were, not footage of it.
      </div>
    </Card>
  );
}

/** One green stop, with the evidence that earned it on hover.
 *
 *  Rule 5: the number shown is the one the engine measured. "6 matches over 4
 *  seconds, best 0.71" is checkable; "high confidence" is not. */
function AnchorRow({ anchor }: { anchor: W.PathAnchor }) {
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
