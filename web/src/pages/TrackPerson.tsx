/** Track a person — following one person across cameras.
 *
 *  Built from design/15-8 design/VisionGuard.dc.html. Seven states, one flow:
 *
 *      form ──┬─► ambig ──► live ──► stop ──► done
 *             └─► mancam ──► manper ──┘
 *
 *  Three rules the design exists to enforce, all of them about not claiming
 *  more than the system knows:
 *
 *  1. **A face names a person; clothing only says "same body".** Green means
 *     identified by face, blue means matched by clothing, amber means never
 *     identified at all. They are never merged into one number or one colour,
 *     and the legend spells all three out in words.
 *
 *  2. **A prediction is not a sighting.** The next-camera pulse is a guess
 *     drawn from where cameras sit on the floor plan, and the label under the
 *     tile says exactly that, in words, rather than relying on the colour.
 *
 *  3. **The operator resolves ambiguity, not the software.** When several
 *     cameras could hold the person, all of them are offered as alternatives
 *     and nothing records until one is chosen.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useAccount } from '@/app/AuthContext';
import { useCameras } from '@/app/CameraContext';
import { useToday } from '@/app/SiteContext';
import { usePersonNames } from '@/app/useOptions';
import { CameraFrame } from '@/components/CameraFrame';
import { Card, PageHeader } from '@/components/ui';
import { correctIdentity, getLiveTracking, trackPerson } from '@/services/api';
import type * as W from '@/services/wire';
import type { Camera, TrackResult } from '@/types';

/* ---------- evidence colours ----------
 *
 *  Fixed hex, not tokens: these sit on top of dark video and must not shift
 *  with the light/dark theme. They match --det-* in tokens.css. */
const FACE = '#3f8f74';
const CLOTH = '#5b9bd8';
const UNKNOWN = '#dfa23f';

/** How long a stop has to be before returning to a camera counts as a new visit. */
type Mode = 'live' | 'past';
type Stage = null | 'ambig' | 'live' | 'stop' | 'done' | 'mancam' | 'manper';

interface Subject {
  id: string;
  name: string;
  /** Identified by face. False means we are following a body, not a person. */
  identified: boolean;
  source: 'directory' | 'camera';
}

interface TrailStop {
  cameraId: string;
  atSeconds: number;
  kind: 'start' | 'cloth';
}

const clock = (seconds: number) => {
  const m = Math.floor(seconds / 60);
  const s = String(Math.floor(seconds % 60)).padStart(2, '0');
  return `${m}:${s}`;
};

const wallClock = (base: Date, offsetSeconds: number) => {
  const t = new Date(base.getTime() + offsetSeconds * 1000);
  return t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
};

const initials = (name: string) =>
  name.split(' ').map((w) => w[0]).join('').slice(0, 2).toUpperCase();

const minutes = (hhmm: string) => {
  const [h, m] = hhmm.split(':').map(Number);
  return (h || 0) * 60 + (m || 0);
};

/** Cameras nearest this one on the floor plan.
 *
 *  Prediction is distance-based (the operator's choice), so proximity on the
 *  plan is the whole model. Until the map editor exists, "nearest" degrades to
 *  "the other cameras in the list" — which is honest rather than clever, and
 *  the tile label never claims more than a guess either way. */
function neighboursOf(cameras: Camera[], cameraId: string): Camera[] {
  const others = cameras.filter((c) => c.id !== cameraId);
  return others.slice(0, 4);
}

export function TrackPerson() {
  const account = useAccount();
  const today = useToday();
  const people = usePersonNames();
  const { cameras } = useCameras();

  const [mode, setMode] = useState<Mode>('past');
  const [stage, setStage] = useState<Stage>(null);
  const [subject, setSubject] = useState<Subject | null>(null);
  const [error, setError] = useState('');

  const [date, setDate] = useState('');
  const [from, setFrom] = useState('07:00');
  const [to, setTo] = useState('08:15');

  const [result, setResult] = useState<TrackResult | null>(null);
  const [loading, setLoading] = useState(false);

  const [currentCam, setCurrentCam] = useState('');
  const [pickCam, setPickCam] = useState('');
  const [elapsed, setElapsed] = useState(0);
  const [trail, setTrail] = useState<TrailStop[]>([]);
  const [note, setNote] = useState('');
  const [savedOk, setSavedOk] = useState(true);
  const [startedAt, setStartedAt] = useState<Date>(() => new Date());

  /* ---------- what the tracker can actually see ----------
   *
   *  Polled, not invented. `following` is the appearance id the operator chose;
   *  everything on the live view is derived from where the engine currently
   *  reports that id, so the screen follows the tracker rather than a local
   *  guess about it. */
  const [liveState, setLiveState] = useState<W.LiveTracking | null>(null);
  const [following, setFollowing] = useState<string | null>(null);

  const polling = stage === 'ambig' || stage === 'live';
  useEffect(() => {
    if (!polling) return;
    let alive = true;
    const tick = () => {
      void getLiveTracking()
        .then((next) => { if (alive) setLiveState(next); })
        .catch(() => { /* a dropped poll is not worth clearing the screen for */ });
    };
    tick();
    const id = window.setInterval(tick, 1000);
    return () => { alive = false; window.clearInterval(id); };
  }, [polling]);

  /** Where the followed identity is right now, if the tracker still has it. */
  const seenNow = useMemo(
    () => liveState?.identities.find((i) => i.stableId === following) ?? null,
    [liveState, following],
  );

  /* The camera follows the identity by itself. That is the entire point: the
   * operator picked a body, and the body moving to another camera should move
   * the view, not require them to notice and click. */
  useEffect(() => {
    if (stage !== 'live' || !seenNow) return;
    setCurrentCam((current) => {
      if (current === seenNow.cameraId) return current;
      setTrail((t) =>
        t.some((x) => x.cameraId === seenNow.cameraId && x.kind !== 'start')
          ? t
          : [...t, { cameraId: seenNow.cameraId, atSeconds: elapsed, kind: 'cloth' }],
      );
      return seenNow.cameraId;
    });
  }, [stage, seenNow, elapsed]);

  const timer = useRef<number | null>(null);
  const stopClock = useCallback(() => {
    if (timer.current !== null) {
      window.clearInterval(timer.current);
      timer.current = null;
    }
  }, []);
  useEffect(() => stopClock, [stopClock]);

  // Two separate things, deliberately. `nowLabel` is for reading — it follows
  // the operator's locale, so it may well be "08:02 PM". `nowMinutes` is for
  // comparing, and is taken straight off the Date. Parsing the label back into
  // a number silently read "08:02 PM" as 8:02am and let a window that includes
  // right now pass validation.
  const nowDate = new Date();
  const nowLabel = nowDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const nowMinutes = nowDate.getHours() * 60 + nowDate.getMinutes();
  const selectedDate = date || today;

  const cam = useMemo(
    () => cameras.find((c) => c.id === currentCam) ?? cameras[0],
    [cameras, currentCam],
  );
  const manCam = useMemo(
    () => cameras.find((c) => c.id === pickCam) ?? cameras[0],
    [cameras, pickCam],
  );

  const visited = useMemo(() => trail.map((t) => t.cameraId), [trail]);

  /** The camera the person is expected to enter next.
   *
   *  First neighbour they have not already been seen on — walking back the way
   *  you came is possible but it is not the thing worth flagging. */
  const predicted = useMemo(() => {
    if (!cam) return undefined;
    const nbs = neighboursOf(cameras, cam.id);
    return nbs.find((c) => !visited.includes(c.id)) ?? nbs[0];
  }, [cameras, cam, visited]);

  /* ---------- starting ---------- */

  function chooseByName(name: string) {
    const unknown = name.startsWith('Unknown') || name === 'DHL courier';
    // #p1, #p2 … keyed off the directory position. A slug of the name gave
    // "#layl", which is neither an id nor a name and reads as a glitch. The
    // real appearance id replaces this once live tracking is wired to the
    // engine's stable ids.
    const index = people.indexOf(name);
    setSubject({
      id: `#p${index >= 0 ? index + 1 : 1}`,
      name: unknown ? 'Unknown person' : name,
      identified: !unknown,
      source: 'directory',
    });
    setError('');
  }

  /** A past window has to be genuinely past, and start before it ends. */
  function windowIsBad(): boolean {
    if (minutes(to) >= nowMinutes || minutes(from) >= nowMinutes) {
      setError(
        `That window includes right now (${nowLabel}). A past search must end ` +
          'before now — to follow someone at this moment, switch to "Live — right now".',
      );
      return true;
    }
    if (minutes(from) >= minutes(to)) {
      setError('The start time has to come before the end time.');
      return true;
    }
    setError('');
    return false;
  }

  const runPast = useCallback(async () => {
    if (!subject) return;
    setLoading(true);
    try {
      // The audit row is written server-side before the answer comes back.
      setResult(await trackPerson({ who: subject.name, date: selectedDate, from, to }, account.name));
    } finally {
      setLoading(false);
    }
  }, [subject, selectedDate, from, to, account.name]);

  function start() {
    if (!subject) {
      setError('Choose who you are following first.');
      return;
    }
    if (mode === 'past') {
      if (windowIsBad()) return;
      void runPast();
      return;
    }
    stopClock();
    setNote('');
    setStage('ambig');
  }

  function runClock() {
    stopClock();
    setElapsed(0);
    timer.current = window.setInterval(() => setElapsed((e) => e + 1), 1000);
  }

  function confirmCandidate(cameraId: string, stableId?: string) {
    if (stableId) setFollowing(stableId);
    setCurrentCam(cameraId);
    setTrail([{ cameraId, atSeconds: 0, kind: 'start' }]);
    setStartedAt(new Date());
    setNote('');
    setStage('live');
    runClock();
  }

  function switchCamera(cameraId: string) {
    setCurrentCam(cameraId);
    setTrail((t) => [...t, { cameraId, atSeconds: elapsed, kind: 'cloth' }]);
  }

  function notThisPerson() {
    stopClock();
    // Tell the engine, not just the screen. It issues a fresh identity so the
    // wrong name does not travel forward onto the next camera.
    if (following) void correctIdentity(following).catch(() => {});
    setFollowing(null);
    setNote(
      'Match rejected. Recording stopped and that clip was discarded — the system has been told it was wrong. Choose the right one, or cancel.',
    );
    setStage('ambig');
  }

  function close() {
    stopClock();
    setStage(null);
    setNote('');
    setResult(null);
    setFollowing(null);
  }

  /* ---------- derived view data ---------- */

  const identified = seenNow ? seenNow.match === 'face' : (subject?.identified ?? false);
  // The appearance id the engine issued. This is the number that survives
  // leaving the frame and changing camera, so it is what the screen shows.
  const shownId = following ? `#${following}` : (subject?.id ?? '#?');
  const shownName = seenNow?.name ?? (identified ? subject?.name : null) ?? 'Unknown person';

  /** The bodies the tracker is actually holding, offered as alternatives.
   *
   *  Real appearance ids, not a guess from the camera list. When the tracker
   *  can see nobody the list is empty and the page says so, which is the
   *  honest answer — inventing candidates would have the operator confirm a
   *  person who is not there. */
  const candidates = useMemo(() => {
    const found = liveState?.identities ?? [];
    return found.slice(0, 4).map((identity, i) => ({
      identity,
      camera: cameras.find((c) => c.id === identity.cameraId),
      letter: ['A', 'B', 'C', 'D'][i],
      confidence: identity.match === 'face' ? 'Fairly sure' : 'Not sure',
      why:
        identity.match === 'face'
          ? `A face match named this body ${identity.name ? `as ${identity.name}` : ''}.`.trim()
          : 'Following clothing colour and build only — no face has been matched to this body.',
      neighbours: neighboursOf(cameras, identity.cameraId),
    }));
  }, [liveState, cameras]);

  const livePath = useMemo(
    () =>
      trail
        .slice()
        .reverse()
        .map((stop) => {
          const isStart = stop.kind === 'start';
          const byFace = isStart && identified;
          const camera = cameras.find((c) => c.id === stop.cameraId);
          return {
            key: `${stop.cameraId}-${stop.atSeconds}`,
            time: wallClock(startedAt, stop.atSeconds),
            place: camera?.name ?? stop.cameraId,
            kind: byFace ? 'Face match' : isStart ? 'No face match' : 'Clothing match',
            detail: isStart
              ? identified
                ? 'Where tracking started — identity confirmed'
                : 'Where tracking started — identity never confirmed'
              : 'Face not visible — clothing colour and build only',
            colour: byFace ? FACE : isStart ? UNKNOWN : CLOTH,
            round: byFace,
          };
        }),
    [trail, identified, cameras, startedAt],
  );

  const camerasSoFar = new Set(visited).size;

  /* ---------- render ---------- */

  const showForm = stage === null;

  return (
    <>
      <PageHeader
        title="Track a person"
        lead="Rebuild where someone went across campus, for investigations only."
      />

      <div className="notice notice--amber">
        <span style={{ fontWeight: 700 }}>⚑</span>
        Every tracking search is recorded in the audit log with your name, and is visible to all
        administrators.
      </div>

      {showForm && (
        <Card>
          <Step n="1" title="Who are you following?" sub="One person at a time. Choose them by name, or point at them on a camera." />
          <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap', margin: '0 0 6px 32px' }}>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--tx2)' }}>
                By name, from the directory
              </span>
              <select
                className="input"
                value={subject?.source === 'directory' ? subject.name : ''}
                onChange={(e) => chooseByName(e.target.value)}
              >
                <option value="">Choose someone…</option>
                {people.map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </label>
            <div style={{ fontSize: 12.5, color: 'var(--tx3)', fontWeight: 600, paddingBottom: 13 }}>or</div>
            <button
              type="button"
              className="chip-btn chip-btn--off"
              style={{ height: 42 }}
              onClick={() => { stopClock(); setNote(''); setStage('mancam'); }}
            >
              Point at them on a camera
            </button>
          </div>

          {subject && <SubjectChip subject={subject} where={manCam?.name} />}

          <div style={{ height: 1, background: 'var(--line)', margin: '18px 0' }} />
          <Step
            n="2"
            title="When?"
            sub={`Right now is ${nowLabel}. Following live and rebuilding a past path are different jobs — pick one.`}
          />

          <div style={{ marginLeft: 32 }}>
            <div style={{ display: 'inline-flex', gap: 4, padding: 4, background: 'var(--bg)', borderRadius: 11, marginBottom: 14 }}>
              {(['live', 'past'] as Mode[]).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => { setMode(m); setError(''); setStage(null); setResult(null); }}
                  style={{
                    padding: '8px 16px', borderRadius: 8, fontSize: 13.5, fontWeight: 600,
                    cursor: 'pointer', whiteSpace: 'nowrap', border: 'none',
                    background: mode === m ? 'var(--card)' : 'transparent',
                    color: mode === m ? 'var(--tx)' : 'var(--tx3)',
                    boxShadow: mode === m ? 'var(--sh)' : 'none',
                  }}
                >
                  {m === 'live' ? 'Live — right now' : 'A past time'}
                </button>
              ))}
            </div>

            {mode === 'past' ? (
              <>
                <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                  <Labelled label="Date">
                    <input className="input" type="date" value={selectedDate} onChange={(e) => setDate(e.target.value)} />
                  </Labelled>
                  <Labelled label="From">
                    <input className="input" type="time" value={from} onChange={(e) => { setFrom(e.target.value); setError(''); }} />
                  </Labelled>
                  <Labelled label="To">
                    <input className="input" type="time" value={to} onChange={(e) => { setTo(e.target.value); setError(''); }} />
                  </Labelled>
                </div>
                <div style={{ fontSize: 12.5, color: 'var(--tx3)', marginTop: 8 }}>
                  A past search has to end before {nowLabel}. Recorded footage only — nothing is streaming.
                </div>
              </>
            ) : (
              <div style={{ fontSize: 13, color: 'var(--tx2)', lineHeight: 1.5 }}>
                Picks them up from this moment and records while you watch. There is no past footage
                in this mode, and no end time — you stop it yourself.
              </div>
            )}

            {error && (
              <div style={{
                display: 'flex', gap: 9, background: 'var(--am-bg)', color: 'var(--am)',
                borderRadius: 10, padding: '11px 14px', fontSize: 13, fontWeight: 600,
                lineHeight: 1.45, marginTop: 12,
              }}>
                {error}
              </div>
            )}

            <div style={{ marginTop: 18 }}>
              <button
                type="button"
                onClick={start}
                disabled={loading}
                style={{
                  height: 44, padding: '0 24px', border: 'none', borderRadius: 10,
                  background: mode === 'past' ? 'var(--ac)' : 'var(--rd)',
                  color: '#fff', fontWeight: 600, fontSize: 14.5, cursor: 'pointer',
                }}
              >
                {loading ? 'Building…' : mode === 'past' ? 'Build path' : 'Start following'}
              </button>
            </div>
          </div>
        </Card>
      )}

      {!showForm && subject && (
        <Card tight>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
            <Avatar subject={subject} />
            <div style={{ flex: 1, minWidth: 180 }}>
              <IdLine subject={subject} />
              <div style={{ fontSize: 12, color: 'var(--tx2)' }}>
                {mode === 'past'
                  ? `Recorded footage · ${from} to ${to}`
                  : `Live, from ${nowLabel} onwards`}
              </div>
            </div>
            <button type="button" className="chip-btn chip-btn--off" onClick={close}>
              Change who or when
            </button>
          </div>
        </Card>
      )}

      {/* ---------- pick a camera ---------- */}
      {stage === 'mancam' && (
        <>
          <Card>
            <div style={{ fontWeight: 700, fontSize: 19, letterSpacing: '-.01em' }}>
              Choose the camera you want to look at.
            </div>
            <div style={{ fontSize: 13.5, color: 'var(--tx2)', marginTop: 3 }}>
              {mode === 'past'
                ? `Open a recorded camera at ${to} and point at the person yourself, instead of searching by name.`
                : 'Open a live camera and point at the person yourself, instead of searching by name.'}
            </div>
          </Card>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(196px,1fr))', gap: 11, marginBottom: 14 }}>
            {cameras.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => { setPickCam(c.id); setStage('manper'); }}
                style={{ padding: 0, border: '1px solid var(--line)', borderRadius: 11, overflow: 'hidden', background: 'var(--card)', cursor: 'pointer', textAlign: 'left' }}
              >
                <CameraFrame camera={c} size="sm" />
                <div style={{ padding: '8px 11px' }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--tx)' }}>{c.name}</div>
                  <div style={{ fontSize: 11, color: 'var(--tx3)', marginTop: 1 }}>{c.status}</div>
                </div>
              </button>
            ))}
          </div>
          <Centre><button type="button" className="chip-btn chip-btn--off" onClick={close}>Cancel</button></Centre>
        </>
      )}

      {/* ---------- pick a person in the frame ---------- */}
      {stage === 'manper' && manCam && (
        <>
          <Card>
            <div style={{ fontWeight: 700, fontSize: 19, letterSpacing: '-.01em' }}>
              {mode === 'past'
                ? 'Click the person you want to follow through the recording.'
                : 'Click the person you want to follow.'}
            </div>
            <div style={{ fontSize: 13.5, color: 'var(--tx2)', marginTop: 3 }}>
              {manCam.name} · {mode === 'past' ? `recorded at ${to} · nothing is streaming` : 'live · nobody is being followed yet, and nothing is recording'}
            </div>
          </Card>
          <Card>
            <CameraFrame camera={manCam} size="lg" live={mode !== 'past'} feature="track" />
            <div style={{ fontSize: 12.5, color: 'var(--tx3)', marginTop: 9 }}>
              Green means identified by face. Amber means not identified — following the body only.
            </div>
          </Card>
          <Card>
            <div style={{ fontWeight: 700, fontSize: 15.5, marginBottom: 2 }}>People in this frame</div>
            <div style={{ fontSize: 12.5, color: 'var(--tx3)', marginBottom: 12 }}>
              Pick the one you want to follow.
            </div>
            {(manCam.boxes ?? []).length === 0 && (
              <div className="empty">Nobody is in view on this camera right now.</div>
            )}
            {(manCam.boxes ?? []).map((box, i) => {
              const known = !!box.label && !box.label.startsWith('Unknown');
              const name = known ? box.label! : 'Unknown person';
              return (
                <div key={`${box.x}-${i}`} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '11px 0', borderTop: '1px solid var(--line)' }}>
                  <div style={{
                    width: 34, height: 34, borderRadius: '50%', flexShrink: 0,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontWeight: 700, fontSize: 13,
                    background: known ? 'var(--chip)' : 'var(--am-bg)',
                    color: known ? 'var(--ac2)' : 'var(--am)',
                  }}>
                    {known ? initials(name) : '?'}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                      <span style={{ fontSize: 15, fontWeight: 700 }}>#{i + 1}</span>
                      <span style={{ fontSize: 14, fontWeight: 600, color: known ? 'var(--tx2)' : 'var(--am)' }}>{name}</span>
                    </div>
                    <div style={{ fontSize: 12.5, color: 'var(--tx2)' }}>
                      {known
                        ? 'Identified by face — matched against the school directory'
                        : 'Not identified by face — the system can only follow the body'}
                    </div>
                  </div>
                  <button
                    type="button"
                    className="chip-btn chip-btn--on"
                    onClick={() => {
                      setSubject({ id: `#${i + 1}`, name, identified: known, source: 'camera' });
                      if (mode === 'past') { setStage(null); void runPast(); return; }
                      confirmCandidate(manCam.id);
                    }}
                  >
                    {mode === 'past' ? 'Build their path' : 'Follow this person'}
                  </button>
                </div>
              );
            })}
          </Card>
          <Centre>
            <button type="button" className="chip-btn chip-btn--off" onClick={() => setStage('mancam')}>Choose a different camera</button>
            <button type="button" className="chip-btn chip-btn--off" onClick={close}>Cancel</button>
          </Centre>
        </>
      )}

      {/* ---------- which camera is it? ---------- */}
      {stage === 'ambig' && (
        <>
          <Card>
            <div style={{ fontWeight: 700, fontSize: 19, letterSpacing: '-.01em' }}>
              The system found more than one possible match. Choose the right one.
            </div>
            <div style={{ fontSize: 13.5, color: 'var(--tx2)', marginTop: 3 }}>
              Nothing is recorded until you choose. These are alternatives — only one of them is the
              person you asked for.
            </div>
            {note && (
              <div style={{ display: 'flex', gap: 9, background: 'var(--am-bg)', color: 'var(--am)', borderRadius: 10, padding: '10px 14px', fontSize: 13, fontWeight: 600, marginTop: 12 }}>
                {note}
              </div>
            )}
          </Card>

          {candidates.length === 0 && (
            <Card>
              <div className="empty">
                {liveState && !liveState.running
                  ? `Tracking is not running: ${liveState.reason ?? 'unknown reason'}`
                  : 'Nobody is in view on any tracked camera. Walk into shot and this fills in.'}
              </div>
            </Card>
          )}
          {candidates.map((c, i) => (
            <div key={c.identity.stableId}>
              {i > 0 && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, margin: '2px 0 10px' }}>
                  <div style={{ flex: 1, height: 1, background: 'var(--line)' }} />
                  <div style={{ fontSize: 11.5, fontWeight: 700, letterSpacing: '.14em', color: 'var(--tx3)' }}>OR</div>
                  <div style={{ flex: 1, height: 1, background: 'var(--line)' }} />
                </div>
              )}
              <Card>
                <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1.3fr) minmax(0,1fr)', gap: 18, alignItems: 'start' }}>
                  {c.camera && <CameraFrame camera={c.camera} size="sm" badge={null} />}
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 9 }}>
                      <div style={{ width: 24, height: 24, borderRadius: 7, background: 'var(--panel)', color: 'var(--tx2)', fontSize: 12, fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        {c.letter}
                      </div>
                      <div style={{ fontWeight: 700, fontSize: 15.5 }}>{c.identity.cameraName}</div>
                    </div>
                    <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginBottom: 8 }}>Cameras next to this one</div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 7, marginBottom: 12 }}>
                      {c.neighbours.map((nb) => (
                        <div key={nb.id} style={{ border: '1px solid var(--line)', borderRadius: 8, padding: '5px 7px', fontSize: 10.5, fontWeight: 600, color: 'var(--tx2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {nb.name}
                        </div>
                      ))}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
                      <span style={{ fontSize: 12.5, color: 'var(--tx2)' }}>How sure the system is</span>
                      <span style={{
                        fontSize: 12.5, fontWeight: 700, padding: '3px 10px', borderRadius: 8,
                        background: c.confidence === 'Fairly sure' ? 'var(--chip)' : 'var(--am-bg)',
                        color: c.confidence === 'Fairly sure' ? 'var(--ac2)' : 'var(--am)',
                      }}>
                        {c.confidence}
                      </span>
                    </div>
                    <div style={{ fontSize: 12.5, color: 'var(--tx2)', lineHeight: 1.45, marginBottom: 14 }}>{c.why}</div>
                    <button
                      type="button"
                      onClick={() => confirmCandidate(c.identity.cameraId, c.identity.stableId)}
                      style={{ width: '100%', height: 42, border: 'none', borderRadius: 10, background: 'var(--ac)', color: '#fff', fontWeight: 600, fontSize: 14, cursor: 'pointer' }}
                    >
                      This is them
                    </button>
                  </div>
                </div>
              </Card>
            </div>
          ))}
          <Centre><button type="button" className="chip-btn chip-btn--off" onClick={close}>None of these — cancel</button></Centre>
        </>
      )}

      {/* ---------- following ---------- */}
      {stage === 'live' && subject && cam && (
        <>
          <Card tight>
            <div style={{ display: 'flex', alignItems: 'center', gap: 15, flexWrap: 'wrap' }}>
              <Avatar subject={subject} large />
              <div style={{ flex: 1, minWidth: 230 }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 9, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 19, fontWeight: 800, letterSpacing: '-.01em' }}>{shownId}</span>
                  <span style={{ fontSize: 15, fontWeight: 600, color: identified ? 'var(--tx2)' : 'var(--am)' }}>
                    {shownName}
                  </span>
                  <span style={{
                    fontSize: 12, fontWeight: 700, padding: '3px 10px', borderRadius: 8,
                    background: identified ? 'var(--chip)' : 'var(--am-bg)',
                    color: identified ? 'var(--ac2)' : 'var(--am)',
                  }}>
                    {identified ? 'Identified by face' : 'Not identified by face'}
                  </span>
                </div>
                <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginTop: 2 }}>
                  {identified
                    ? 'Face match confirmed. Clothing is used only to keep hold of the body between cameras.'
                    : 'Following clothing colour and build only. This is not a confirmed identity and must not be treated as one.'}
                </div>
              </div>
              <div style={{ display: 'flex', gap: 18, whiteSpace: 'nowrap' }}>
                <Stat label="Recording" value={clock(elapsed)} mono />
                <Stat label="Cameras so far" value={String(camerasSoFar)} />
              </div>
              <div style={{ display: 'flex', gap: 9 }}>
                <button
                  type="button"
                  onClick={notThisPerson}
                  style={{ height: 42, padding: '0 17px', border: '1.5px solid var(--am)', borderRadius: 10, background: 'var(--card)', color: 'var(--am)', fontWeight: 600, fontSize: 13.5, cursor: 'pointer' }}
                >
                  Not this person
                </button>
                <button
                  type="button"
                  onClick={() => { stopClock(); setStage('stop'); }}
                  style={{ height: 42, padding: '0 19px', border: 'none', borderRadius: 10, background: 'var(--rd)', color: '#fff', fontWeight: 600, fontSize: 13.5, cursor: 'pointer' }}
                >
                  Stop tracking
                </button>
              </div>
            </div>
          </Card>

          <Card>
            <div style={{ position: 'relative' }}>
              {/* Recording, not LIVE — on this screen the badge means one
                  thing, and two badges would claim two different things. */}
              <CameraFrame camera={cam} size="lg" live badge="RECORDING" feature="track" />
              {/* ID big, name underneath — the design's rule. */}
              {/* No box overlay here on purpose. CameraFrame already draws the
                  tracked bodies from /cameras/{id}/detections, ids and all, and
                  drawing a second one from /tracking/live put two boxes on the
                  same person that drifted apart between polls. */}
            </div>
            <div style={{ fontSize: 12.5, color: 'var(--tx3)', marginTop: 9 }}>
              {!seenNow
                ? 'Out of view — the tracker is holding this identity, waiting for them to reappear.'
                : identified
                  ? 'Green box: identity confirmed by face.'
                  : 'Amber box: nobody has been identified — following a body, not a person.'}
            </div>
          </Card>

          <Card>
            <div style={{ fontWeight: 700, fontSize: 15.5 }}>Cameras next to {cam.name}</div>
            <div style={{ fontSize: 12.5, color: 'var(--tx3)', marginTop: 2 }}>
              Click any camera to make it the main view. A slow green pulse marks where the system
              expects them to walk next — a guess, not a sighting, and the label underneath says so
              in words.
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,minmax(0,1fr))', gap: 11, marginTop: 14, alignItems: 'start' }}>
              {neighboursOf(cameras, cam.id).map((nb) => {
                const isNext = predicted?.id === nb.id;
                const seen = visited.includes(nb.id);
                return (
                  <button
                    key={nb.id}
                    type="button"
                    onClick={() => switchCamera(nb.id)}
                    style={{
                      padding: 0, textAlign: 'left', cursor: 'pointer', borderRadius: 11,
                      overflow: 'hidden', background: 'var(--card)',
                      border: `2px solid ${isNext ? '#5cae91' : 'var(--line)'}`,
                      animation: isNext ? 'vg-nextcam 2s ease-in-out infinite' : 'none',
                    }}
                  >
                    <CameraFrame camera={nb} size="sm" badge={null} />
                    <div style={{ padding: '8px 11px' }}>
                      <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--tx)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {nb.name}
                      </div>
                      <div style={{ fontSize: 11, fontWeight: 600, marginTop: 1, minHeight: 26, color: isNext ? 'var(--ac)' : 'var(--tx3)' }}>
                        {isNext ? 'Predicted next — not a sighting' : seen ? 'Seen earlier' : 'No sighting'}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </Card>

          <Card>
            <div style={{ fontWeight: 700, fontSize: 15.5, marginBottom: 3 }}>Path so far</div>
            <Legend />
            <div style={{ position: 'relative', paddingLeft: 26 }}>
              <div style={{ position: 'absolute', left: 7, top: 6, bottom: 6, width: 2, background: 'var(--line)' }} />
              {livePath.map((p) => (
                <div key={p.key} style={{ position: 'relative', paddingBottom: 18 }}>
                  <span style={{
                    position: 'absolute', left: -24, top: 4, width: 12, height: 12,
                    borderRadius: p.round ? '50%' : 2, background: p.colour,
                    border: '2.5px solid var(--card)', boxSizing: 'content-box',
                  }} />
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{p.time} — {p.place}</div>
                  <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginTop: 1 }}>{p.kind} · {p.detail}</div>
                </div>
              ))}
            </div>
          </Card>
        </>
      )}

      {/* ---------- save the clip ---------- */}
      {stage === 'stop' && (
        <Card>
          <div style={{ fontWeight: 700, fontSize: 19, letterSpacing: '-.01em' }}>Save this clip?</div>
          <div style={{ fontSize: 13.5, color: 'var(--tx2)', margin: '3px 0 16px' }}>
            Tracking has ended. The clip exists only until you decide — discarding removes the video,
            the search itself stays in the audit log.
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,minmax(0,1fr))', gap: 12, marginBottom: 18 }}>
            <Tile label="Length" value={`${Math.floor(elapsed / 60)}m ${elapsed % 60}s`} />
            <Tile label="Cameras" value={String(camerasSoFar)} />
            <Tile label="Started" value={wallClock(startedAt, 0)} />
          </div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button
              type="button"
              onClick={() => { setSavedOk(true); setStage('done'); }}
              style={{ height: 44, padding: '0 24px', border: 'none', borderRadius: 10, background: 'var(--ac)', color: '#fff', fontWeight: 600, fontSize: 14.5, cursor: 'pointer' }}
            >
              Save clip
            </button>
            <button type="button" className="chip-btn chip-btn--off" style={{ height: 44 }} onClick={() => { setSavedOk(false); setStage('done'); }}>
              Discard
            </button>
          </div>
        </Card>
      )}

      {/* ---------- done ---------- */}
      {stage === 'done' && (
        <Card>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14 }}>
            <div style={{
              width: 36, height: 36, borderRadius: '50%', flexShrink: 0,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: savedOk ? 'var(--chip)' : 'var(--panel)',
              color: savedOk ? 'var(--ac2)' : 'var(--tx2)',
            }}>
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d={savedOk ? 'M4 9.5 L7.5 13 L14 5' : 'M5 5 L13 13 M13 5 L5 13'} />
              </svg>
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 700, fontSize: 16.5 }}>{savedOk ? 'Clip saved' : 'Clip discarded'}</div>
              <div style={{ fontSize: 13.5, color: 'var(--tx2)', marginTop: 2 }}>
                {savedOk
                  ? `${Math.floor(elapsed / 60)}m ${elapsed % 60}s across ${camerasSoFar} ${camerasSoFar === 1 ? 'camera' : 'cameras'}, saved to the investigation record with your name.`
                  : 'The video has been deleted. The search itself remains in the audit log.'}
              </div>
              <div style={{ display: 'flex', gap: 10, marginTop: 14 }}>
                <button type="button" className="chip-btn chip-btn--on" onClick={() => { setNote(''); setStage('ambig'); }}>Follow again</button>
                <button type="button" className="chip-btn chip-btn--off" onClick={close}>Close</button>
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* ---------- a past path ---------- */}
      {showForm && result && (
        <Card>
          <div style={{ fontWeight: 700, fontSize: 21, letterSpacing: '-.01em' }}>{result.heading}</div>
          <div style={{ fontSize: 13.5, color: 'var(--tx2)', margin: '2px 0 14px' }}>{result.sub}</div>
          <Legend />
          <div style={{ position: 'relative', paddingLeft: 26 }}>
            <div style={{ position: 'absolute', left: 7, top: 6, bottom: 6, width: 2, background: 'var(--line)' }} />
            {result.path.map((stop, i) => (
              <div key={`${stop.time}-${stop.place}-${i}`} style={{ position: 'relative', paddingBottom: 18 }}>
                <span style={{
                  position: 'absolute', left: -24, top: 4, width: 12, height: 12,
                  borderRadius: stop.match === 'face' ? '50%' : 2,
                  background: stop.match === 'face' ? FACE : CLOTH,
                  border: '2.5px solid var(--card)', boxSizing: 'content-box',
                }} />
                <div style={{ fontWeight: 600, fontSize: 14 }}>
                  {stop.time}{stop.until && stop.until !== stop.time ? ` – ${stop.until}` : ''} — {stop.place}
                </div>
                <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginTop: 1 }}>{stop.detail}</div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {showForm && !result && !loading && (
        <div style={{ textAlign: 'center', padding: '52px 20px', color: 'var(--tx3)', fontSize: 14.5 }}>
          Choose a person and a time window.
        </div>
      )}
    </>
  );
}

/* ---------- small pieces ---------- */

function Step({ n, title, sub }: { n: string; title: string; sub: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 10 }}>
      <div style={{ width: 22, height: 22, borderRadius: 7, background: 'var(--panel)', color: 'var(--tx2)', fontSize: 11.5, fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
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

function Avatar({ subject, large = false }: { subject: Subject; large?: boolean }) {
  const size = large ? 42 : 30;
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%', flexShrink: 0,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontWeight: 700, fontSize: large ? 15 : 12.5,
      background: subject.identified ? 'var(--chip)' : 'var(--am-bg)',
      color: subject.identified ? 'var(--ac2)' : 'var(--am)',
    }}>
      {subject.identified ? initials(subject.name) : '?'}
    </div>
  );
}

function IdLine({ subject }: { subject: Subject }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
      <span style={{ fontSize: 14, fontWeight: 700 }}>{subject.id}</span>
      <span style={{ fontSize: 14, fontWeight: 600, color: subject.identified ? 'var(--ac2)' : 'var(--am)' }}>
        {subject.identified ? subject.name : 'Unknown person'}
      </span>
    </div>
  );
}

function SubjectChip({ subject, where }: { subject: Subject; where?: string }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10, margin: '12px 0 0 32px',
      padding: '10px 14px', borderRadius: 10,
      background: subject.identified ? 'var(--chip)' : 'var(--am-bg)',
    }}>
      <Avatar subject={subject} />
      <div style={{ minWidth: 0 }}>
        <IdLine subject={subject} />
        <div style={{ fontSize: 12, color: 'var(--tx2)' }}>
          {subject.identified
            ? subject.source === 'camera'
              ? `Identified by face, picked on ${where ?? 'a camera'}`
              : 'Identified by face, from the directory'
            : 'Never identified by face — only clothing colour and build can be followed'}
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <div style={{ fontSize: 11.5, color: 'var(--tx3)' }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 700, fontFamily: mono ? 'ui-monospace,Menlo,monospace' : undefined }}>
        {value}
      </div>
    </div>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ background: 'var(--bg)', borderRadius: 10, padding: '13px 15px' }}>
      <div style={{ fontSize: 12.5, color: 'var(--tx2)' }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700 }}>{value}</div>
    </div>
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
    <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', margin: '8px 0 14px' }}>
      {items.map((g) => (
        <div key={g.t} style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 12, color: 'var(--tx2)' }}>
          <span style={{ width: 11, height: 11, borderRadius: g.round ? '50%' : 2, background: g.c }} />
          {g.t}
        </div>
      ))}
    </div>
  );
}

function Centre({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', gap: 10, marginBottom: 14 }}>
      {children}
    </div>
  );
}
