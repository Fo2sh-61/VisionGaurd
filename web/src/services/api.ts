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
  FightIncident,
  FightPlace,
  FoundDevice,
  GroupMember,
  GroupSummary,
  IntrusionWindow,
  LostHit,
  LostQuery,
  LostResult,
  PersonHistory,
  PersonType,
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
import { ApiError, SEARCH_TIMEOUT_MS, apiBase, del, get, patch, post, postFile, request } from './http';
import {
  attendanceLabel,
  attendanceStatusLine,
  attendanceTone,
  formatCount,
  formatDuration,
  formatEventTime,
  formatLongDate,
  formatMetrics,
  formatPercent,
  formatSchedule,
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

export async function getZones(): Promise<Zone[]> {
  // Disabled zones are returned too — a paused zone stays visible.
  const zones = await get<W.Zone[]>('/zones');
  return zones.map((z) => ({
    id: z.id,
    name: z.name,
    hours: formatSchedule(z.schedule),
    enabled: z.enabled,
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
    status: b.status === 'open' ? 'Open' : b.status === 'authorised' ? 'Authorised' : 'Resolved',
    tone: severityToNeutralTone(b.severity),
  }));
}

/** CHANGED: was synchronous. The engine has to be asked. */
export async function getIntrusionCameras(): Promise<Camera[]> {
  return toCameras(await get<W.CameraView[]>('/intrusion/cameras'));
}

/* ---------- fights ---------- */

export async function getFights(
  window: IntrusionWindow,
  place: FightPlace,
): Promise<FightIncident[]> {
  const fights = await get<W.FightIncident[]>('/fights', { window, place });
  return fights.map((f) => ({
    id: f.id,
    location: f.location,
    area: f.area as Exclude<FightPlace, 'Anywhere'>,
    time: formatEventTime(f.at),
    // The duration is the model's actual measurement, not a fixed string.
    meta: `${formatDuration(f.durationSeconds)} · ${f.participants} people`,
    status: f.markedNotAFight ? 'Marked not a fight' : f.reviewed ? 'Reviewed' : 'Not reviewed',
    critical: f.severity === 'critical',
  }));
}

/** The label that retrains detection, so the actor is recorded with it. */
export async function markNotAFight(id: string, actor = 'unknown'): Promise<void> {
  await post<W.FightIncident>(`/fights/${encodeURIComponent(id)}/feedback`, {
    notAFight: true,
    actor,
  });
}

/** CHANGED: was synchronous. */
export async function getFightCameras(): Promise<Camera[]> {
  return toCameras(await get<W.CameraView[]>('/fights/cameras'));
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

function guardianLine(p: W.DirectoryPerson): string {
  if (!p.guardianName) return '—';
  const relation = p.guardianRelation ? ` (${p.guardianRelation})` : '';
  const phone = p.guardianPhone ? ` · ${p.guardianPhone}` : '';
  return `${p.guardianName}${relation}${phone}`;
}

export async function getPeople(): Promise<DirectoryPerson[]> {
  const people = await get<W.DirectoryPerson[]>('/people');
  return people.map((p) => ({
    name: p.name,
    type: p.type,
    sub: personSub(p),
    guardian: guardianLine(p),
    photoOnFile: p.photoOnFile,
  }));
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

export async function removeEnrolmentPhoto(
  sessionId: string,
  photoId: string,
): Promise<W.EnrolmentSession> {
  return del<W.EnrolmentSession>(`/enrolment/sessions/${sessionId}/photos/${photoId}`);
}

export async function commitEnrolment(sessionId: string): Promise<DirectoryPerson> {
  const p = await post<W.DirectoryPerson>(`/enrolment/sessions/${sessionId}/commit`);
  return {
    name: p.name,
    type: p.type,
    sub: personSub(p),
    guardian: guardianLine(p),
    photoOnFile: p.photoOnFile,
  };
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
    bars: h.trend.map((t) => ({
      day: t.label,
      label: formatPercent(t.presentRatio),
      pct: Math.round(t.presentRatio * 100),
      tone: t.presentRatio >= 0.9 ? 'good' : t.presentRatio >= 0.6 ? 'warn' : 'bad',
    })),
    flags: h.flags.map((f) => ({
      date: formatShortDate(f.date),
      detail: f.detail,
      badge: f.kind,
      tone: severityToTone(f.severity),
    })),
  };
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
