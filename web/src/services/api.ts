/** The one place the UI talks to "the system".
 *
 *  Every function here now calls the engine over HTTP. The signatures are the
 *  same ones the pages have always used, so `pages/` did not change — the
 *  engine returns structured data and `format.ts` renders it into the shapes
 *  in `@/types`.
 *
 *  Start the engine:  python engine/tools/serve.py
 *  Point at it:       web/.env.local -> VITE_API_BASE=http://127.0.0.1:8000
 *
 *  Three signatures had to change, because the originals could not carry the
 *  data the engine needs. They are marked CHANGED below. */

import type {
  AttendanceDay,
  AttendanceQuery,
  AttendanceResult,
  AttendanceRow,
  Breach,
  Camera,
  CameraSource,
  CountArea,
  CountBar,
  CountQuery,
  DetectionBox,
  CountResult,
  DirectoryPerson,
  FoundDevice,
  GroupMember,
  GroupSummary,
  IntrusionWindow,
  LostHit,
  LostQuery,
  LostResult,
  PersonHistory,
  PersonType,
  Recording,
  RecordingResult,
  SystemHealth,
  TrackQuery,
  TrackResult,
  User,
  WeaponDetection,
  WeaponWindow,
  Zone,
} from '@/types';
import * as W from './wire';

/** Which overlay a page wants on a camera. One camera, different questions. */
export type CameraFeature = 'attendance' | 'track' | 'counting' | 'intrusion' | 'weapons';
import { ApiError, SEARCH_TIMEOUT_MS, apiBase, assetUrl, del, get, patch, post, postFile, request, setSessionToken } from './http';
import type { Account } from '@/app/AuthContext';
import type { Role } from '@/types';
import {
  attendanceLabel,
  attendanceStatusLine,
  attendanceTone,
  formatCount,
  formatEventTime,
  formatLongDate,
  formatMetrics,
  formatDuration,
  formatShortDate,
  formatTime,
  matchLabel,
  severityToNeutralTone,
  severityToTone,
  toCamera,
  toDetectionBox,
  toCameras,
} from './format';

/* ---------- site ---------- */

/** School name, the site's today, and the live camera tally.
 *  Fetched once by `SiteProvider`; pages read it from `useSite()`. */
export const getSite = () => get<W.SiteInfo>('/site');

/** Just the overlay boxes for one camera.
 *
 *  The enlarged view polls this several times a second so the boxes track a
 *  moving face on the MJPEG stream. It is deliberately separate from the full
 *  camera payload, which carries names, zones and timestamps that do not
 *  change nearly that often.
 *
 *  `feature` picks the overlay. The same camera answers a different question on
 *  each page — attendance wants faces, tracking wants appearance ids, counting
 *  wants unlabelled bodies — so the caller says which it is asking. */
export async function getCameraDetections(
  cameraId: string,
  feature?: CameraFeature,
): Promise<{ boxes: DetectionBox[]; peopleCount: number | null }> {
  const result = await get<W.CameraDetections>(
    `/cameras/${encodeURIComponent(cameraId)}/detections`,
    feature ? { feature } : undefined,
  );
  return {
    boxes: result.boxes.map(toDetectionBox),
    peopleCount: result.peopleCount ?? null,
  };
}

/** Every configured camera and its current state.
 *
 *  The roster, not a query result — `CameraProvider` polls this so the grid is
 *  populated on every page regardless of what that page's own request did. */
export async function getCameras(): Promise<Camera[]> {
  return toCameras(await get<W.CameraView[]>('/cameras'));
}

/** Add a camera. It starts being watched immediately and appears everywhere. */
export async function addCamera(params: {
  name: string;
  source: string;
  kind?: 'NVR' | 'DVR' | 'IP camera' | 'RTSP';
  area?: string;
  fps?: number;
  features?: string[];
  username?: string;
  password?: string;
}): Promise<CameraSource> {
  const s = await post<W.CameraSource>('/sources', params);
  return {
    id: s.id, name: s.name, type: s.type, ip: s.ip,
    channels: s.channels, status: s.status,
  };
}

/** Stop watching a camera. Events already recorded against it are kept. */
export async function removeCamera(id: string): Promise<void> {
  await request<void>(`/sources/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

/** Live headcount for every camera, in one request.
 *
 *  One call for the whole grid rather than one per tile, so the cost does not
 *  grow with the number of cameras on screen. `null` for a camera means no
 *  recent measurement — not zero. */
export const getCameraCounts = () => get<Record<string, number | null>>('/cameras/counts');

/* ---------- attendance ---------- */

export async function getAttendance(query: AttendanceQuery): Promise<AttendanceResult> {
  const subject = query.mode === 'person' ? query.person : query.group;
  const result = await get<W.AttendanceResult>('/attendance', {
    mode: query.mode,
    subject: subject ?? 'Grade 8',
    date: query.date,
  });

  const cameras = toCameras(result.cameras);
  const stats = formatMetrics(result.metrics);

  if (result.mode === 'person') {
    const days: AttendanceDay[] = result.days.map((d) => ({
      date: formatShortDate(d.date),
      where: d.location ?? '—',
      time: d.seenAt ? formatTime(d.seenAt) : '—',
      status: attendanceLabel(d.status),
      tone: attendanceTone(d.status),
    }));
    const firstSeen = result.days.find((d) => d.seenAt);
    return {
      mode: 'person',
      heading: firstSeen
        ? `${result.subject} arrived at ${formatTime(firstSeen.seenAt)}`
        : `${result.subject} was not seen`,
      sub: firstSeen?.location
        ? `Recognised at ${firstSeen.location}`
        : formatLongDate(result.date),
      stats,
      days,
      cameras,
    };
  }

  const rows: AttendanceRow[] = result.records.map((r) => ({
    name: r.person.name ?? 'Unknown',
    status: attendanceLabel(r.status),
    tone: attendanceTone(r.status),
    time: r.seenAt ? formatTime(r.seenAt) : '—',
  }));

  return {
    mode: 'group',
    heading: `${formatCount(result.present)} of ${formatCount(result.expected)} arrived`,
    sub: `${result.subject} · ${formatLongDate(result.date)}`,
    stats,
    rows,
    cameras,
  };
}

/** Download the register for one day as a CSV.
 *
 *  Exports exactly what the page is showing, including absences — a register
 *  that omits the people it did not see is not a register. Each row carries
 *  the confidence and the camera that made the identification, so a disputed
 *  mark can be traced back to the evidence. */
export async function exportAttendance(query: AttendanceQuery): Promise<void> {
  const subject = query.mode === 'person' ? query.person : query.group;
  const url = new URL(`${apiBase}/attendance/export`);
  url.searchParams.set('mode', query.mode);
  url.searchParams.set('subject', subject ?? 'Everyone');
  url.searchParams.set('date', query.date);

  const response = await fetch(url.toString());
  if (!response.ok) {
    throw new ApiError(`Export failed (${response.status})`, response.status, true);
  }

  // Read the filename the engine chose so the file is named after the day and
  // group rather than after the endpoint.
  const disposition = response.headers.get('Content-Disposition') ?? '';
  const named = /filename="([^"]+)"/.exec(disposition)?.[1];
  const blob = await response.blob();
  const href = URL.createObjectURL(blob);

  const link = document.createElement('a');
  link.href = href;
  link.download = named ?? `attendance-${query.date}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoking immediately can cancel the download in some browsers.
  setTimeout(() => URL.revokeObjectURL(href), 10_000);
}

/* ---------- people counting ---------- */

export async function getCount(query: CountQuery): Promise<CountResult> {
  const result = await get<W.CountResult>('/count', {
    place: query.place,
    when: query.when,
  });

  const areas: CountArea[] = result.areas.map((a) => ({
    name: a.name,
    value: a.count,
    capacity: a.capacity,
    pct: Math.round((a.count / a.capacity) * 100),
    tone: severityToTone(a.severity),
    x: a.x * 100,
    y: a.y * 100,
    w: a.w * 100,
    h: a.h * 100,
    live: a.live,
  }));

  // Bar height is relative to the tallest bar — a rendering concern, so the
  // engine sends counts and the percentage is computed here.
  const peak = Math.max(1, ...result.bars.map((b) => b.value));
  const bars: CountBar[] | undefined = result.bars.length
    ? result.bars.map((b) => ({
        label: b.label,
        value: b.value,
        pct: Math.round((b.value / peak) * 100),
        // Each area's share of the whole bar, so the segments stack to the
        // bar's own height rather than each being scaled independently.
        parts: (b.parts ?? []).map((p) => ({
          name: p.name,
          value: p.value,
          live: p.live,
          pct: b.value ? Math.round((p.value / b.value) * 100) : 0,
        })),
      }))
    : undefined;

  const capacity = result.capacity ?? 0;
  const pct = capacity ? Math.round((result.count / capacity) * 100) : 0;

  return {
    place: result.place,
    heading: `${formatCount(result.count)} people in the ${result.place.toLowerCase()}`,
    sub: capacity
      ? `${pct}% of safe capacity (${capacity})${result.deduplicated ? ' · counted once across overlapping cameras' : ''}`
      : `Measured ${formatTime(result.measuredAt)}`,
    stats: formatMetrics(result.metrics),
    barsTitle: result.barsTitle ?? undefined,
    bars,
    areas,
    cameras: toCameras(result.cameras),
  };
}

/* ---------- intrusion ---------- */

/** Every camera, each with its restricted-area toggle.
 *
 *  Switched-off cameras are returned too — the toggle is how you tell, and a
 *  camera that vanished when switched off would take its history with it. */
export async function getZones(): Promise<Zone[]> {
  const zones = await get<W.Zone[]>('/zones');
  return zones.map((z) => ({
    id: z.id,
    name: z.name,
    enabled: z.enabled,
    detectionsToday: z.breachesToday,
  }));
}

export async function setZoneEnabled(id: string, enabled: boolean): Promise<void> {
  await patch<W.Zone>(`/zones/${encodeURIComponent(id)}`, { enabled });
}

export async function getBreaches(window: IntrusionWindow): Promise<Breach[]> {
  const breaches = await get<W.Breach[]>('/breaches', { window });
  return breaches.map((b) => ({
    id: b.id,
    zone: b.zoneName,
    time: formatEventTime(b.at),
    who: b.subject.name
      ? `Matched: ${b.subject.name}${b.subject.type ? ` (${b.subject.type})` : ''}`
      : 'Unidentified person',
    status: b.status === 'open' ? 'Still there' : b.status === 'authorised' ? 'Authorised' : 'Left',
    tone: severityToNeutralTone(b.severity),
    people: b.people ?? 1,
    duration: formatDuration(b.dwellSeconds),
    // Same-origin, through the same helper the camera streams use. A <video>
    // cannot send an Authorization header, so an absolute engine URL would
    // play for nobody — that is the trap that once blacked out every stream.
    clipUrl: assetUrl(b.clip?.url),
    clipReason: b.clipReason ?? undefined,
  }));
}

/** CHANGED: was synchronous. The engine has to be asked. */
export async function getIntrusionCameras(): Promise<Camera[]> {
  return toCameras(await get<W.CameraView[]>('/intrusion/cameras'));
}

/* ---------- weapons ---------- */

function weaponStatus(d: W.WeaponDetection): string {
  if (d.verdict === 'confirmed') return 'Confirmed — police notified';
  if (d.verdict === 'dismissed') {
    return d.dismissalReason ? `False alarm — ${d.dismissalReason}` : 'False alarm';
  }
  return 'Awaiting review';
}

export async function getWeaponDetections(window: WeaponWindow): Promise<WeaponDetection[]> {
  // Dismissed detections come back too. False alarms stay in the history.
  const detections = await get<W.WeaponDetection[]>('/weapons/detections', { window });
  return detections.map((d) => ({
    id: d.id,
    time: formatEventTime(d.at),
    location: d.location,
    item: d.item,
    status: weaponStatus(d),
    tone:
      d.verdict === 'confirmed' ? 'bad' : d.verdict === 'dismissed' ? 'neutral' : 'warn',
  }));
}

/** NEW: the human gate. Nothing downstream fires until this is called — the
 *  detector alone never notifies, calls or locks anything. */
export async function reviewWeapon(
  id: string,
  verdict: 'confirmed' | 'dismissed',
  actor: string,
  reason?: string,
): Promise<WeaponDetection> {
  const d = await post<W.WeaponDetection>(`/weapons/${encodeURIComponent(id)}/review`, {
    verdict,
    actor,
    reason,
  });
  return {
    id: d.id,
    time: formatEventTime(d.at),
    location: d.location,
    item: d.item,
    status: weaponStatus(d),
    tone: d.verdict === 'confirmed' ? 'bad' : 'neutral',
  };
}

/** CHANGED: was synchronous. */
export async function getWeaponCameras(): Promise<Camera[]> {
  return toCameras(await get<W.CameraView[]>('/weapons/cameras'));
}

/* ---------- lost items ---------- */

export async function searchLostItem(query: LostQuery): Promise<LostResult> {
  // Runs over stored footage, so it gets the long timeout. The UI's
  // "Searching footage…" state covers it.
  const result = await post<W.LostResult>(
    '/lost-items/search',
    {
      item: query.item,
      colour: query.colour === 'Any' ? null : query.colour,
      area: query.area,
      since: query.since,
    },
    undefined,
    SEARCH_TIMEOUT_MS,
  );

  const label = `${query.colour === 'Any' ? '' : `${query.colour.toLowerCase()} `}${query.item.toLowerCase()}`;
  const hits: LostHit[] = result.hits.map((h) => ({
    camera: h.cameraName,
    time: formatTime(h.at),
    confidence: Math.round(h.confidence * 100),
    strong: h.confidence >= 0.8,
    note: h.note ?? '',
  }));

  return {
    label,
    sub: `Searching for a ${label} · ${(query.area ?? '').toLowerCase()} · ${(query.since ?? '').toLowerCase()}`,
    hits,
    searched: result.job.state === 'done',
    cameras: result.cameras.map((c, i) =>
      toCamera(c, result.hits[i] ? `${Math.round(result.hits[i].confidence * 100)}% match · ${formatTime(result.hits[i].at)}` : undefined),
    ),
  };
}

/* ---------- track a person ---------- */

export async function trackPerson(query: TrackQuery, actor = 'unknown'): Promise<TrackResult> {
  const result = await post<W.TrackResult>(
    '/track',
    {
      who: query.who,
      date: query.date,
      start: query.from,
      end: query.to,
    },
    { actor },
  );

  return {
    who: result.subject.name ?? query.who,
    heading: `${result.subject.name ?? query.who} · ${result.sightings} sightings`,
    sub: `${formatLongDate(result.date)} · ${query.from} to ${query.to}`,
    stats: formatMetrics(result.metrics),
    path: result.path.map((stop) => ({
      time: formatTime(stop.at),
      place: stop.place,
      detail: `${stop.cameraName} · ${matchLabel(stop.match, stop.confidence)}`,
      match: stop.match,
      confidence: stop.confidence,
      until: stop.until ? formatTime(stop.until) : undefined,
    })),
    cameras: result.cameras.map((c, i) =>
      toCamera(
        c,
        result.path[i]
          ? matchLabel(result.path[i].match, result.path[i].confidence)
          : undefined,
      ),
    ),
  };
}

/** The audit row is written by the engine INSIDE /track, before the result is
 *  returned — ordering the UI cannot guarantee on its own. Kept for signature
 *  compatibility; `trackPerson(query, actor)` is the real path. */
export async function recordTrackSearch(_query: TrackQuery, _actor: string): Promise<void> {
  /* no-op: /track audits server-side and returns the auditId as the receipt */
}

/* ---------- system + users ---------- */

/** What the console can honestly show right now, and why not otherwise.
 *
 *  Every page that renders a number checks this first. A page cannot tell an
 *  empty register from a broken one — both arrive as zero rows — and guessing
 *  misleads either way: a real empty day read as a fault, or a dead subsystem
 *  read as "nobody came".
 *
 *  Never throws. If the engine cannot be reached at all, everything is
 *  unavailable for that reason, which is exactly what the screen should say. */
export async function getCapabilities(): Promise<W.Capability[]> {
  try {
    return await get<W.Capability[]>('/system/capabilities');
  } catch (err) {
    return [{
      key: 'engine',
      name: 'The engine',
      state: 'unavailable',
      reason: `The console cannot reach the engine (${
        err instanceof Error ? err.message : 'no response'
      }). Nothing on this page is live.`,
    }];
  }
}

export async function getSystemHealth(): Promise<SystemHealth> {
  const health = await get<W.SystemHealth>('/system/health');

  const broken = health.pipeline.filter((p) => !p.healthy);
  const offline = health.camerasTotal - health.camerasOnline;
  const parts: string[] = [];
  if (offline > 0) {
    parts.push(`${offline} ${offline === 1 ? 'camera is' : 'cameras are'} not being analysed`);
  }
  parts.push(...broken.map((p) => `${p.name}: ${p.detail.toLowerCase()}`));

  return {
    camerasOnline: health.camerasOnline,
    camerasTotal: health.camerasTotal,
    summary: parts.length
      ? `${parts.join('; ')}.`
      : 'Everything is recording and being analysed.',
    stats: formatMetrics(health.metrics),
    recorders: health.recorders.map((r) => ({
      id: r.id,
      name: r.name,
      cameras: r.cameras,
      online: r.online,
    })),
    pipeline: health.pipeline.map((p) => ({
      name: p.name,
      detail: p.detail,
      status: p.healthy ? 'Healthy' : 'Needs attention',
      // A stage the engine calls unhealthy must not be drawn green. The
      // severity says how bad; `healthy` alone would flatten warn and bad
      // into one colour.
      tone: p.healthy ? ('good' as const) : severityToTone(p.severity),
      action: p.restartable ? 'Restart' : undefined,
    })),
    cameras: toCameras(health.cameras),
  };
}

export async function getUsers(): Promise<User[]> {
  const users = await get<W.User[]>('/users');
  return users.map((u) => ({
    id: u.id,
    name: u.name,
    role: u.role,
    email: u.email,
    lastActive: u.lastActive ? formatEventTime(u.lastActive) : '—',
  }));
}

/* ---------- people directory ---------- */

function personSub(p: W.DirectoryPerson): string {
  return p.detail ?? p.group ?? '';
}

/** "Recognised · 3 photos", or why not.
 *
 *  "Photo on file" was always a statement about capability wearing the words
 *  of paperwork — nobody reading it could tell it meant "the cameras can find
 *  this person". This says the thing itself, and how well. */
function recognitionLine(p: W.DirectoryPerson): string {
  if (!p.photoOnFile) return 'Cannot be recognised — no face on file';
  const photos = p.photos ?? 0;
  if (photos <= 0) return 'Recognised';
  return `Recognised · ${photos} ${photos === 1 ? 'photo' : 'photos'}`;
}

/** "Main entrance · Today, 7:42am", or "Not seen yet".
 *
 *  Never a dash. A value the system does not have is stated in words, so the
 *  reader knows it was looked for and genuinely is not there — which is a
 *  different fact from a column nobody ever filled in. */
function lastSeenLine(p: W.DirectoryPerson): string {
  if (!p.lastSeen) return 'Not seen yet';
  const when = formatEventTime(p.lastSeen);
  return p.lastCamera ? `${p.lastCamera} · ${when}` : when;
}

function toDirectoryPerson(p: W.DirectoryPerson): DirectoryPerson {
  const status = p.attendanceToday ?? null;
  return {
    id: p.id,
    name: p.name,
    type: p.type,
    sub: personSub(p),
    photoOnFile: p.photoOnFile,
    recognition: recognitionLine(p),
    // Empty, not a placeholder: the row simply drops the line rather than
    // printing a shrug where a date belongs.
    enrolled: p.enrolledAt ? `Enrolled ${formatEventTime(p.enrolledAt)}` : '',
    lastSeen: lastSeenLine(p),
    // Nothing recording attendance is not the same as being absent, so the
    // row says nothing at all rather than guessing.
    today: status ? attendanceLabel(status) : '',
    todayTone: status ? attendanceTone(status) : 'neutral',
  };
}

export async function getPeople(): Promise<DirectoryPerson[]> {
  const people = await get<W.DirectoryPerson[]>('/people');
  return people.map(toDirectoryPerson);
}

/** Remove someone from the system.
 *
 *  Deletes their directory entry and every face vector behind it, so the
 *  cameras stop naming them from the next frame. Admin-only, enforced on the
 *  server whatever this console believes, and written to the audit trail
 *  before anything is deleted. */
export async function removePerson(personId: string): Promise<void> {
  await del<void>(`/people/${encodeURIComponent(personId)}`);
}

/* ---------- live tracking ----------
 *
 *  The appearance id is what this returns and what the page follows. It holds
 *  through someone leaving a frame and coming back, and through moving to
 *  another camera, with or without a face ever being seen. */

export const getLiveTracking = () => get<W.LiveTracking>('/tracking/live');

/** "That body is not who you say it is." Issues a fresh identity so the
 *  mistake does not travel forward. The sightings themselves are kept. */
export async function correctIdentity(stableId: string): Promise<void> {
  await post<void>(`/tracking/${encodeURIComponent(stableId)}/correct`);
}

/* ---------- the path behind somebody ----------
 *
 *  One indexed read on the engine, so this answers immediately. Empty anchors
 *  is an ANSWER — nobody was identified in that window — and is not the same
 *  as the 503 that means the engine cannot look at all. */

export const getPathSkeleton = (
  person: string,
  date: string,
  from?: string,
  to?: string,
) =>
  get<W.PathSkeleton>(`/path/${encodeURIComponent(person)}`, {
    date,
    start: from,
    end: to,
  });

/* ---------- following one person, live ----------
 *
 *  Three refusals, three meanings, and the page must not collapse them:
 *    503  tracking is not running at all
 *    404  nobody is standing where you clicked — retryable, they moved
 *    409  a follow is already open, and the message names it
 *
 *  `ApiError.status` carries them through, so the caller decides what to say. */

/** Follow whichever body is under that point. Fractions of the frame. */
export const startFollow = (cameraId: string, x: number, y: number) =>
  post<W.FollowView>('/tracking/follow', { cameraId, x, y });

/** The follow as it stands. Returns null when nothing is being followed —
 *  including when the engine ended it by itself, which is how a timer running
 *  out or a lost track reaches a page that never asked. */
export async function getFollow(): Promise<W.FollowView | null> {
  try {
    return await get<W.FollowView>('/tracking/follow');
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export const endFollow = () => del<W.FollowView>('/tracking/follow');

/** Record the followed person, one segment per camera they cross.
 *
 *  `timerSeconds` null means "until somebody presses stop". Either way the
 *  engine stops it on its own if the track is lost, so this cannot leak. */
export const startFollowRecording = (timerSeconds: number | null) =>
  post<W.FollowView>('/tracking/follow/record', { timerSeconds });

export const stopFollowRecording = () => del<W.FollowView>('/tracking/follow/record');

/* ---------- enrolment ----------
 *
 *  Nothing here reaches the gallery until `commitEnrolment`. A session that is
 *  abandoned — the operator closes the tab half way — leaves no trace, so there
 *  is never a half-enrolled person who fails recognition for reasons nobody can
 *  see on screen.
 *
 *  These return the raw wire type rather than a rendered shape. The Enrolment
 *  Studio is the only consumer and it needs the numbers themselves: a score
 *  bar, a pixel count, an angle. */

export async function startEnrolment(person: {
  name: string;
  type: PersonType;
  group?: string;
  detail?: string;
  personId?: string;
}): Promise<W.EnrolmentSession> {
  return post<W.EnrolmentSession>('/enrolment/sessions', {
    name: person.name,
    type: person.type,
    group: person.group || null,
    detail: person.detail || null,
    personId: person.personId || null,
  });
}

export async function getEnrolment(sessionId: string): Promise<W.EnrolmentSession> {
  return get<W.EnrolmentSession>(`/enrolment/sessions/${sessionId}`);
}

/** Assess one photo. A rejected photo comes back 200 with `usable: false` and a
 *  reason — the operator has to read why, next to the thumbnail. */
export async function addEnrolmentPhoto(
  sessionId: string,
  file: Blob,
  filename?: string,
): Promise<W.EnrolmentSession> {
  return postFile<W.EnrolmentSession>(
    `/enrolment/sessions/${sessionId}/photos`,
    file,
    filename,
  );
}

/** Grab the camera's current frame instead of uploading a file.
 *
 *  Enrolling from the entrance camera at its real mounting angle and lighting
 *  produces markedly better recognition than a laptop webcam, because the
 *  enrolment then matches the conditions the person will actually be seen in. */
export async function captureEnrolmentPhoto(
  sessionId: string,
  cameraId: string,
): Promise<W.EnrolmentSession> {
  return post<W.EnrolmentSession>(
    `/enrolment/sessions/${sessionId}/capture`,
    undefined,
    { camera_id: cameraId },
  );
}

/** The faces in the enrolment camera's current frame, for the live overlay.
 *
 *  Polled a few times a second while a session is open, and only then —
 *  nothing runs on the engine when nobody is on the page. Carries geometry
 *  and nothing else: an enrolment preview never names who it can see. */
export async function getEnrolmentPreview(
  cameraId: string,
): Promise<W.EnrolmentPreview> {
  return get<W.EnrolmentPreview>(`/enrolment/preview/${encodeURIComponent(cameraId)}`);
}

export async function removeEnrolmentPhoto(
  sessionId: string,
  photoId: string,
): Promise<W.EnrolmentSession> {
  return del<W.EnrolmentSession>(`/enrolment/sessions/${sessionId}/photos/${photoId}`);
}

export async function commitEnrolment(sessionId: string): Promise<DirectoryPerson> {
  const p = await post<W.DirectoryPerson>(`/enrolment/sessions/${sessionId}/commit`);
  return toDirectoryPerson(p);
}

export async function cancelEnrolment(sessionId: string): Promise<void> {
  await del<void>(`/enrolment/sessions/${sessionId}`);
}

export async function getGroups(): Promise<GroupSummary[]> {
  const groups = await get<W.GroupSummary[]>('/groups');
  return groups.map((g) => ({
    name: g.name,
    count: g.classes
      ? `${formatCount(g.people)} students · ${g.classes} classes`
      : `${formatCount(g.people)} people`,
    here: g.here,
  }));
}

export async function getGroup(
  name: string,
): Promise<{ summary: GroupSummary; roster: GroupMember[] }> {
  const detail = await get<W.GroupDetail>(`/groups/${encodeURIComponent(name)}`);
  const g = detail.summary;
  return {
    summary: {
      name: g.name,
      count: g.classes
        ? `${formatCount(g.people)} students · ${g.classes} classes`
        : `${formatCount(g.people)} people`,
      here: g.here,
    },
    roster: detail.roster.map((r) => ({
      name: r.person.name ?? 'Unknown',
      sub: r.location ?? '',
      status: attendanceStatusLine(r.status, r.seenAt),
      tone: attendanceTone(r.status),
    })),
  };
}

export async function getHistory(name: string): Promise<PersonHistory> {
  const h = await get<W.PersonHistory>(`/people/${encodeURIComponent(name)}/history`);
  return {
    name: h.person.name,
    sub: personSub(h.person),
    heading: `${h.presentDays} of ${h.totalDays} days present`,
    lead: h.periodLabel,
    stats: formatMetrics(h.metrics),
    // One person on one day is here or not, so the bar is full or empty and
    // the colour carries the rest. A percentage per day would have read as
    // "60% present on Tuesday", which means nothing for one child.
    bars: h.trend.map((t) => ({
      date: t.date,
      day: t.label,
      label: attendanceLabel(t.status),
      pct: t.status === 'absent' ? 0 : 100,
      tone: attendanceTone(t.status),
    })),
    flags: h.flags.map((f) => ({
      date: formatShortDate(f.date),
      detail: f.detail,
      badge: f.kind,
      tone: severityToTone(f.severity),
    })),
  };
}

/* ---------- recording ----------
 *
 *  Started and stopped by a person, and it records from the moment the button
 *  is pressed — nothing is buffered, so the seconds before the press do not
 *  exist. The screens that sit next to an alert have to say so.
 *
 *  A refusal arrives as ok:false with a reason rather than an error status,
 *  because the operator reads it next to the button they just pressed. These
 *  three never throw for that case; they throw only when the engine cannot be
 *  reached at all. */

function toRecording(r: W.Recording): Recording {
  return {
    id: r.id,
    cameraId: r.cameraId,
    cameraName: r.cameraName ?? null,
    state: r.state,
    startedAt: formatTime(r.startedAt),
    seconds: Math.round(r.seconds),
    frames: r.frames,
    file: r.file ?? null,
    reason: r.reason ?? null,
    maxSeconds: r.maxSeconds,
  };
}

function toRecordingResult(result: W.RecordingResult): RecordingResult {
  return {
    ok: result.ok,
    recording: result.recording ? toRecording(result.recording) : null,
    reason: result.reason ?? null,
  };
}

export async function getRecording(cameraId: string): Promise<RecordingResult> {
  return toRecordingResult(
    await get<W.RecordingResult>(`/cameras/${encodeURIComponent(cameraId)}/recording`),
  );
}

export async function startRecording(
  cameraId: string,
  actor: string,
): Promise<RecordingResult> {
  return toRecordingResult(
    await post<W.RecordingResult>(
      `/cameras/${encodeURIComponent(cameraId)}/recording`,
      undefined,
      { actor },
    ),
  );
}

export async function stopRecording(
  cameraId: string,
  actor: string,
): Promise<RecordingResult> {
  return toRecordingResult(
    await del<W.RecordingResult>(
      `/cameras/${encodeURIComponent(cameraId)}/recording`,
      { actor },
    ),
  );
}

/* ---------- camera sources (onboarding) ---------- */

/** CHANGED: was synchronous. */
export async function getCameraSources(): Promise<CameraSource[]> {
  const sources = await get<W.CameraSource[]>('/sources');
  return sources.map((s) => ({
    id: s.id,
    name: s.name,
    type: s.type,
    ip: s.ip,
    channels: s.channels,
    status: s.status,
  }));
}

/** CHANGED: was synchronous. */
export async function getAreaOptions(): Promise<string[]> {
  return get<string[]>('/sources/areas');
}

export async function scanNetwork(): Promise<FoundDevice[]> {
  const found = await post<W.FoundDevice[]>('/sources/scan');
  return found.map((d) => ({
    name: d.name,
    ip: d.ip,
    channels: d.channels,
    duplicate: d.duplicate,
    added: d.added,
  }));
}

/** CHANGED: takes the connection details.
 *
 *  The original took no arguments, so the host and password the operator typed
 *  never left the component. They have to reach the engine for this to work. */
export async function connectDvr(params: {
  host: string;
  port?: number;
  username: string;
  password: string;
  name?: string;
  area?: string;
}): Promise<{ channels: number }> {
  const result = await post<W.DvrConnectResult>('/sources/dvr', params);
  return { channels: result.channels.length };
}

/** CHANGED: takes the source to test, for the same reason as `connectDvr`.
 *
 *  A failed test comes back as a normal result with `offline: true` rather than
 *  a thrown error, so the page can render the failure inline. */
export async function testConnection(params: {
  source: string;
  username?: string;
  password?: string;
}): Promise<Camera> {
  const result = await post<W.TestConnectionResult>('/sources/test', params);

  if (!result.ok || !result.camera) {
    return {
      id: 'test-frame',
      name: 'Test frame',
      status: result.error ?? 'Could not connect',
      offline: true,
      boxes: [],
    };
  }

  const latency = result.latencyMs ? ` · ${Math.round(result.latencyMs)}ms` : '';
  return toCamera(result.camera, `Connection OK${latency}`);
}

/* ---------- home ---------- */

export async function getAttention(): Promise<W.AttentionItem[]> {
  return get<W.AttentionItem[]>('/attention');
}

export async function acknowledgeAttention(id: string, actor: string): Promise<void> {
  await post<W.AttentionItem>(`/attention/${encodeURIComponent(id)}/ack`, { actor });
}

/* ---------- settings ---------- */

export const getSchoolProfile = () => get<W.SchoolProfile>('/settings/school');
export const getAlertRules = () => get<W.AlertRule[]>('/settings/alerts');
export const getDeliveryTargets = () => get<W.DeliveryTarget[]>('/settings/delivery');

/* ---------- auth ---------- */

/** Sign in. Returns the account the server says you are.
 *
 *  The token is handed to the http layer for the Authorization header; the
 *  engine also sets an HttpOnly cookie, which is what the MJPEG streams and a
 *  page refresh rely on. Nothing is written to localStorage: the old build
 *  kept the role there and believed it. */
export async function signIn(email: string, password: string): Promise<Account> {
  const result = await post<W.LoginResult>('/auth/login', { email, password });
  setSessionToken(result.token);
  return toAccount(result.user);
}

export async function signOut(): Promise<void> {
  try {
    await post<{ ok: boolean }>('/auth/logout');
  } finally {
    // Drop the local token even if the call failed. The server row is what
    // truly ends the session, but this browser must not keep presenting it.
    setSessionToken(null);
  }
}

/** Who the server says we are. Throws 401 when nobody is signed in. */
export async function getMe(): Promise<Account> {
  return toAccount(await get<W.Account>('/auth/me'));
}

function toAccount(wire: W.Account): Account {
  return {
    id: wire.id,
    name: wire.name,
    email: wire.email,
    role: wire.role as Role,
    initials: wire.initials,
  };
}
