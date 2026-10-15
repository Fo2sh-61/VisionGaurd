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
  AddCameraOutcome,
  DvrConnectResult,
  EditCameraResult,
  FallEntry,
  FallsStatus,
  FallWindow,
  CountArea,
  CountBar,
  CountQuery,
  DetectionBox,
  CountResult,
  DirectoryPerson,
  ScanResult,
  GroupMember,
  GroupSummary,
  IntrusionWindow,
  PersonHistory,
  PersonType,
  Recording,
  RecordingResult,
  SystemHealth,
  User,
  WeaponDetection,
  WeaponWindow,
  Zone,
} from '@/types';
import * as W from './wire';

/** Which overlay a page wants on a camera. One camera, different questions. */
export type CameraFeature =
  'attendance' | 'track' | 'counting' | 'intrusion' | 'weapons' | 'lost' | 'vehicles' | 'falls';
import { ApiError, apiBase, assetUrl, del, download, get, patch, post, postFile, request, setSessionToken } from './http';
import type { Account } from '@/app/AuthContext';
import { translate, type Language } from '@/i18n';
import type { Role, Tone } from '@/types';
import {
  attendanceLabel,
  attendanceStatusLine,
  attendanceTone,
  formatClock,
  formatCount,
  formatEventTime,
  formatLongDate,
  formatMetrics,
  formatDuration,
  formatPercent,
  formatShortDate,
  formatTime,
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
  colour?: string,
): Promise<{ boxes: DetectionBox[]; peopleCount: number | null }> {
  const result = await get<W.CameraDetections>(
    `/cameras/${encodeURIComponent(cameraId)}/detections`,
    feature ? { feature, ...(colour ? { colour } : {}) } : undefined,
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
export async function getCameras(lang: Language): Promise<Camera[]> {
  return toCameras(await get<W.CameraView[]>('/cameras'), lang);
}

/** One engine `CameraSource` as the console holds it.
 *
 *  In one place because four calls return this shape and they must not drift.
 *  `?? undefined` throughout: the engine sends null for absent, TypeScript
 *  wants undefined for optional, and mixing the two is how a field ends up
 *  rendering as the word "null". */
function toSource(s: W.CameraSource): CameraSource {
  return {
    id: s.id,
    name: s.name,
    type: s.type,
    ip: s.ip,
    channels: s.channels,
    status: s.status,
    area: s.area ?? undefined,
    lastError: s.lastError ?? undefined,
    features: s.features,
    faces: s.faces,
    enabled: s.enabled,
    gate: s.gate ?? undefined,
    direction: s.direction ?? undefined,
    fps: s.fps,
    rotate: s.rotate,
    fromConfig: s.fromConfig,
  };
}

/** Add a camera. It starts being watched immediately and appears everywhere. */
export async function addCamera(params: {
  name: string;
  source: string;
  kind?: 'NVR' | 'DVR' | 'IP camera' | 'RTSP';
  area?: string;
  fps?: number;
  features?: string[];
  faces?: boolean;
  gate?: number;
  direction?: string;
  username?: string;
  password?: string;
}): Promise<CameraSource> {
  return toSource(await post<W.CameraSource>('/sources', params));
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

export async function getAttendance(
  query: AttendanceQuery,
  lang: Language,
): Promise<AttendanceResult> {
  const subject = query.mode === 'person' ? query.person : query.group;
  const result = await get<W.AttendanceResult>('/attendance', {
    mode: query.mode,
    subject: subject ?? 'Grade 8',
    date: query.date,
  });

  const cameras = toCameras(result.cameras, lang);
  const stats = formatMetrics(result.metrics, lang);

  if (result.mode === 'person') {
    const days: AttendanceDay[] = result.days.map((d) => ({
      date: formatShortDate(d.date, lang),
      where: d.location ?? '—',
      time: d.seenAt ? formatTime(d.seenAt, lang) : '—',
      status: attendanceLabel(d.status, lang),
      tone: attendanceTone(d.status),
    }));
    const firstSeen = result.days.find((d) => d.seenAt);
    return {
      mode: 'person',
      heading: firstSeen
        ? `${result.subject} arrived at ${formatTime(firstSeen.seenAt, lang)}`
        : `${result.subject} was not seen`,
      sub: firstSeen?.location
        ? `Recognised at ${firstSeen.location}`
        : formatLongDate(result.date, lang),
      stats,
      days,
      cameras,
    };
  }

  const rows: AttendanceRow[] = result.records.map((r) => ({
    name: r.person.name ?? 'Unknown',
    status: attendanceLabel(r.status, lang),
    tone: attendanceTone(r.status),
    time: r.seenAt ? formatTime(r.seenAt, lang) : '—',
  }));

  return {
    mode: 'group',
    heading: `${formatCount(result.present, lang)} of ${formatCount(result.expected, lang)} arrived`,
    sub: `${result.subject} · ${formatLongDate(result.date, lang)}`,
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

export async function getCount(query: CountQuery, lang: Language): Promise<CountResult> {
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
    heading: `${formatCount(result.count, lang)} people in the ${result.place.toLowerCase()}`,
    sub: capacity
      ? `${pct}% of safe capacity (${capacity})${result.deduplicated ? ' · counted once across overlapping cameras' : ''}`
      : `Measured ${formatTime(result.measuredAt, lang)}`,
    stats: formatMetrics(result.metrics, lang),
    barsTitle: result.barsTitle ?? undefined,
    bars,
    areas,
    cameras: toCameras(result.cameras, lang),
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

export async function getBreaches(
  window: IntrusionWindow,
  lang: Language,
): Promise<Breach[]> {
  const breaches = await get<W.Breach[]>('/breaches', { window });
  return breaches.map((b) => ({
    id: b.id,
    zone: b.zoneName,
    time: formatEventTime(b.at, lang),
    who: b.subject.name
      ? `Matched: ${b.subject.name}${b.subject.type ? ` (${b.subject.type})` : ''}`
      : 'Unidentified person',
    status: b.status === 'open' ? 'Still there' : b.status === 'authorised' ? 'Authorised' : 'Left',
    tone: severityToNeutralTone(b.severity),
    people: b.people ?? 1,
    duration: formatDuration(b.dwellSeconds, lang),
    // Same-origin, through the same helper the camera streams use. A <video>
    // cannot send an Authorization header, so an absolute engine URL would
    // play for nobody — that is the trap that once blacked out every stream.
    clipUrl: assetUrl(b.clip?.url),
    clipReason: b.clipReason ?? undefined,
  }));
}

/** CHANGED: was synchronous. The engine has to be asked. */
export async function getIntrusionCameras(lang: Language): Promise<Camera[]> {
  return toCameras(await get<W.CameraView[]>('/intrusion/cameras'), lang);
}

/* ---------- weapons ---------- */

/** What the entry says it is. Plain sentences, built here — the engine sends
 *  a verdict and a flag, never a sentence.
 *
 *  There used to be a "Confirmed — police notified" here. Nobody is notified
 *  by anything in this product: the review endpoint is the only thing that
 *  fans out and it fans out to nothing yet. It was deleted rather than
 *  reworded, because a sentence promising a call that is not happening is the
 *  most dangerous thing this page could say. */
function weaponStatus(d: W.WeaponDetection, lang: Language): string {
  if (d.verdict === 'confirmed') {
    const who = d.reviewedBy ? ` by ${d.reviewedBy}` : '';
    const when = d.reviewedAt ? ` · ${formatEventTime(d.reviewedAt, lang)}` : '';
    return `Confirmed${who}${when}`;
  }
  if (d.verdict === 'dismissed') {
    return d.dismissalReason ? `False alarm — ${d.dismissalReason}` : 'False alarm';
  }
  // No `endedAt` means the knife has not left view yet, which is a different
  // and more urgent thing than an incident waiting for somebody to look at it.
  return d.endedAt ? 'Awaiting review' : 'Still in view';
}

function weaponTone(d: W.WeaponDetection): Tone {
  if (d.verdict === 'confirmed') return 'bad';
  if (d.verdict === 'dismissed') return 'neutral';
  return 'warn';
}

function toWeapon(d: W.WeaponDetection, lang: Language): WeaponDetection {
  return {
    id: d.id,
    camera: d.cameraName,
    area: d.location,
    time: formatEventTime(d.at, lang),
    duration: formatDuration(d.seconds ?? 0, lang),
    confidence: formatPercent(d.confidence, lang),
    status: weaponStatus(d, lang),
    tone: weaponTone(d),
    verdict: d.verdict,
    reviewer: d.reviewedBy ?? undefined,
    reviewedAt: d.reviewedAt ? formatEventTime(d.reviewedAt, lang) : undefined,
    running: !d.endedAt,
    cut: d.endReason === 'limit',
    // Only a saved video has a `clip`; everything else carries a reason
    // instead, which the page shows where the button would have been.
    clipUrl: d.clip?.url ?? undefined,
    clipReason: d.clipReason ?? undefined,
  };
}

export async function getWeaponDetections(
  window: WeaponWindow,
  lang: Language,
): Promise<WeaponDetection[]> {
  // Dismissed detections come back too. False alarms stay in the history.
  const detections = await get<W.WeaponDetection[]>('/weapons/detections', { window });
  return detections.map((d) => toWeapon(d, lang));
}

/** The human gate. Nothing downstream fires until this is called — the
 *  detector alone never notifies, calls or locks anything.
 *
 *  No `actor`: the engine records the signed-in account from the session.
 *  Sending a name would let a caller review as somebody else, and the server
 *  ignores it anyway. */
export async function reviewWeapon(
  id: string,
  verdict: 'confirmed' | 'dismissed',
  lang: Language,
  reason?: string,
): Promise<WeaponDetection> {
  return toWeapon(
    await post<W.WeaponDetection>(`/weapons/${encodeURIComponent(id)}/review`, {
      verdict,
      reason,
    }),
    lang,
  );
}

/** CHANGED: was synchronous. */
export async function getWeaponCameras(lang: Language): Promise<Camera[]> {
  return toCameras(await get<W.CameraView[]>('/weapons/cameras'), lang);
}

/* ---------- falls ---------- */

/** What happened, in the reader's language. The engine sends an end reason,
 *  a verdict and two times; the sentence is built here, never there. */
function fallOutcome(d: W.FallEntry, lang: Language): { outcome: string; tone: Tone } {
  if (d.verdict === 'not_a_fall') {
    return { outcome: translate(lang, 'falls.outcome.notAFall'), tone: 'neutral' };
  }
  if (!d.endedAt) {
    return d.alertedAt
      ? { outcome: translate(lang, 'falls.outcome.down'), tone: 'bad' }
      : { outcome: translate(lang, 'falls.outcome.downNotYet'), tone: 'warn' };
  }
  switch (d.endReason) {
    case 'got_up':
      // Down shorter than the rule: listed, and it never raised anything.
      return d.alertedAt
        ? { outcome: translate(lang, 'falls.outcome.gotUp'), tone: 'good' }
        : { outcome: translate(lang, 'falls.outcome.gotUpQuickly'), tone: 'neutral' };
    case 'left_view':
      return { outcome: translate(lang, 'falls.outcome.leftView'), tone: 'warn' };
    case 'switched_off':
      return { outcome: translate(lang, 'falls.outcome.switchedOff'), tone: 'neutral' };
    default:
      return { outcome: translate(lang, 'falls.outcome.engineStopped'), tone: 'neutral' };
  }
}

function toFall(d: W.FallEntry, lang: Language): FallEntry {
  const { outcome, tone } = fallOutcome(d, lang);
  const by = d.verdict === 'not_a_fall' && d.reviewedBy
    ? translate(lang, 'falls.by.marked', { name: d.reviewedBy })
    : d.responder
      ? translate(lang, 'falls.by.went', { name: d.responder })
      : undefined;
  return {
    id: d.id,
    cameraId: d.cameraId,
    camera: d.cameraName,
    area: d.location,
    time: formatEventTime(d.at, lang),
    sinceClock: formatClock(d.at) ?? '',
    downSinceMs: new Date(d.at.utc).getTime(),
    duration: formatDuration(d.seconds ?? 0, lang),
    seconds: d.seconds ?? 0,
    confidence: formatPercent(d.confidence, lang),
    outcome,
    tone,
    by,
    running: !d.endedAt,
    alerted: Boolean(d.alertedAt),
    notAFall: d.verdict === 'not_a_fall',
    responder: d.responder ?? undefined,
    respondedAtMs: d.respondedAt ? new Date(d.respondedAt.utc).getTime() : undefined,
    clipUrl: d.clip?.url ?? undefined,
    clipReason: d.clipReason ?? undefined,
  };
}

/** Every fall in the period, people still down included. Nothing is hidden:
 *  "not a fall" stays, saying so. */
export async function getFalls(window: FallWindow, lang: Language): Promise<FallEntry[]> {
  const entries = await get<W.FallEntry[]>('/falls/entries', { window });
  return entries.map((d) => toFall(d, lang));
}

/** Everybody down right now, whatever period the history shows. The live
 *  cards and the all-clear are built from this and never from the history:
 *  a period picked for reading back must not hide somebody on the floor now. */
export async function getFallsNow(lang: Language): Promise<FallEntry[]> {
  const entries = await get<W.FallEntry[]>('/falls/now');
  return entries.map((d) => toFall(d, lang));
}

export async function getFallsStatus(): Promise<FallsStatus> {
  return get<W.FallsStatus>('/falls/status');
}

/** "I'm on my way". Optional; the engine signs it with the session's account.
 *  A 409 says why it could not be recorded - they already got up, or somebody
 *  else is already going - and that reason is what the page shows. */
export async function respondToFall(id: string, lang: Language): Promise<FallEntry> {
  return toFall(await post<W.FallEntry>(`/falls/${encodeURIComponent(id)}/respond`, {}), lang);
}

export async function undoFallResponse(id: string, lang: Language): Promise<FallEntry> {
  return toFall(await del<W.FallEntry>(`/falls/${encodeURIComponent(id)}/respond`), lang);
}

/** "Not a fall". Optional, signed, and final: the entry stays, saying so. */
export async function markNotAFall(id: string, lang: Language): Promise<FallEntry> {
  return toFall(await post<W.FallEntry>(`/falls/${encodeURIComponent(id)}/not-a-fall`, {}), lang);
}

export async function getFallCameras(lang: Language): Promise<Camera[]> {
  return toCameras(await get<W.CameraView[]>('/falls/cameras'), lang);
}

/* ---------- vehicle gate ---------- */

/** The six Live tiles.
 *
 *  Counts arrive nullable on purpose. A null is not "zero we could not
 *  fetch" — it is the engine declining to claim a measurement it did not
 *  make, and `reason` says which. The page renders the reason, never a 0. */
export async function getVehicleSummary(): Promise<W.GateSummary> {
  return get<W.GateSummary>('/vehicles/summary');
}


/** Every pass recorded, newest first.
 *
 *  Back on the console after 28 Aug. Removing the list left an entry-only
 *  gate with nowhere at all to see its own recorded cars — "inside now" needs
 *  an exit camera to pair against, so on a single-camera gate it can only
 *  print the reason it cannot answer. */
export async function getVehiclePasses(
  filters: {
    limit?: number; plate?: string; gate?: number;
    direction?: string; status?: string; day?: string;
  } = {},
): Promise<W.VehiclePass[]> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== '' && value !== null) {
      query.set(key, String(value));
    }
  }
  const suffix = query.toString();
  return get<W.VehiclePass[]>(`/vehicles/passes${suffix ? `?${suffix}` : ''}`);
}

/** Remove one pass, with its photograph and plate crop. Administrator only.
 *
 *  Permanent — "inside now" and the visit lists are computed from the pass
 *  table, so a row kept hidden would go on answering questions after somebody
 *  deleted it. The audit entry is written before the row goes and cannot
 *  itself be deleted. */
export async function deleteVehiclePass(id: string): Promise<void> {
  await del<{ ok: boolean }>(`/vehicles/passes/${encodeURIComponent(id)}`);
}

/** Gate cameras only. A camera with no gate number is not watching a gate. */
export async function getVehicleCameras(lang: Language): Promise<Camera[]> {
  return toCameras(await get<W.CameraView[]>('/vehicles/cameras'), lang);
}

/** Every read attempt, including the ones that came to nothing.
 *
 *  The pass log holds successes by construction, so it cannot tell a camera
 *  that is too far away from a model that is failing from a subsystem that
 *  never started. This can, which is why it is worth a poll of its own.
 *
 *  Polling this also *boosts* the reader, the same way a tile overlay poll
 *  does — so watching the card is what makes the reader run fast enough for
 *  three frames to agree. Stop polling and it goes back to idle within
 *  seconds. */
export async function getVehicleReader(): Promise<W.GateReaderNow> {
  return get<W.GateReaderNow>('/vehicles/reader');
}

/** A photograph of the plate a gate camera is reading right now.
 *
 *  The `bust` argument is a cache-buster: the picture changes as the car
 *  moves, and a browser reusing the last car's crop would be showing
 *  something stale as though it were live. */
export function vehicleCropUrl(cameraId: string, bust: number): string {
  return assetUrl(
    `/vehicles/cameras/${encodeURIComponent(cameraId)}/crop?t=${bust}`) ?? '';
}

/** What a plate may contain, and which characters the reader confuses.
 *
 *  Fetched once and reused: it is a property of the alphabet and the model,
 *  not of any gate, so it does not change while somebody is looking at it. */
export async function getPlateAlphabet(): Promise<W.PlateAlphabet> {
  return get<W.PlateAlphabet>('/vehicles/alphabet');
}

/** Type in a plate after looking at the photograph.
 *
 *  Administrator only — this rewrites what the log says a car was. From then
 *  on the correction outranks the reader: an automatic amendment as the car
 *  approaches will not overwrite it. */
export async function correctVehiclePlate(
  passId: string, plate: string,
): Promise<W.VehiclePass> {
  return patch<W.VehiclePass>(
    `/vehicles/passes/${encodeURIComponent(passId)}/plate`, { plate });
}

/** Today's passes still waiting for a person. */
export async function getVehicleAlerts(): Promise<W.GateAlert[]> {
  return get<W.GateAlert[]>('/vehicles/alerts');
}

/** Clear one alert, under the name of whoever cleared it.
 *
 *  The one write under `/vehicles` a guard may make — the person at the gate
 *  is a guard, and an alert only an admin can clear piles up all shift until
 *  nobody reads it. `actionTaken` distinguishes "I dealt with it" from "not
 *  worth acting on"; both are recorded, and neither can be undone. */
export async function dismissVehicleAlert(
  passId: string, actionTaken = false,
): Promise<void> {
  await post<{ ok: boolean }>(
    `/vehicles/alerts/${encodeURIComponent(passId)}/dismiss`,
    undefined, { action_taken: actionTaken });
}

/** The register. A guard may read it; only an admin may change it. */
export async function getVehicleRegister(
  q = '', category = '',
): Promise<W.RegisteredVehicle[]> {
  const query = new URLSearchParams();
  if (q) query.set('q', q);
  if (category && category !== 'all') query.set('category', category);
  const suffix = query.toString();
  return get<W.RegisteredVehicle[]>(`/vehicles/register${suffix ? `?${suffix}` : ''}`);
}

export async function addVehicle(
  body: W.VehicleRegistration,
): Promise<W.RegisteredVehicle> {
  return post<W.RegisteredVehicle>('/vehicles/register', body);
}

export async function editVehicle(
  id: string, body: W.VehicleRegistration,
): Promise<W.RegisteredVehicle> {
  return patch<W.RegisteredVehicle>(`/vehicles/register/${encodeURIComponent(id)}`, body);
}

/** Remove an entry. The car's PASSES are kept — see the confirmation text. */
export async function removeVehicle(id: string): Promise<void> {
  await del<{ ok: boolean }>(`/vehicles/register/${encodeURIComponent(id)}`);
}

export async function importVehicles(file: File): Promise<W.VehicleImportResult> {
  // `postFile` sets the multipart body and a 30s timeout — a two-thousand-row
  // spreadsheet is slower than a normal request and must not be cut off
  // half-loaded, which would be the partial import nobody can see.
  return postFile<W.VehicleImportResult>('/vehicles/import', file, file.name);
}

/** Today, gate by gate.
 *
 *  An empty list is not "no gates" — it is the engine declining to total up
 *  what it is not watching. `getVehicleSummary().reason` has the words. */
export async function getVehicleGates(day = ''): Promise<W.GateTotals[]> {
  return get<W.GateTotals[]>(`/vehicles/gates${day ? `?day=${day}` : ''}`);
}

/** One day's entries and exits by hour — the traffic chart.
 *
 *  Hours with nothing in them are absent rather than zero, and a day nothing
 *  drove through is an empty list. A row of flat bars would be a drawing of
 *  data that does not exist. */
export async function getVehicleTraffic(day = ''): Promise<W.TrafficHour[]> {
  return get<W.TrafficHour[]>(`/vehicles/traffic${day ? `?day=${day}` : ''}`);
}

/** Cars seen entering today and not seen leaving.
 *
 *  Derived from the passes on every request, never stored, so it cannot drift
 *  out of step with the log it is computed from.
 *
 *  **Takes no day, deliberately.** "Inside now" is only ever now — asking it
 *  about last Tuesday is asking who was inside at a moment that has passed,
 *  which the pass log cannot answer and this must not pretend to. */
export async function getVehiclesInside(): Promise<W.VehicleVisit[]> {
  return get<W.VehicleVisit[]>('/vehicles/inside');
}

/** Today's completed visits. `inferred` marks an exit nobody actually saw. */
export async function getVehicleVisits(day = ''): Promise<W.VehicleVisit[]> {
  return get<W.VehicleVisit[]>(`/vehicles/visits${day ? `?day=${day}` : ''}`);
}

/** The photograph kept with one pass, for a visit row's thumbnail.
 *
 *  404 once the image has aged out at thirty days — the pass itself is kept
 *  for ever, so the row stays and only the picture goes. Call this only where
 *  the visit says it has one. */
export function vehiclePassSnapshotUrl(passId: string): string {
  // `assetUrl` is nullable because it takes paths the engine may not have
  // sent. This path is built here from an id the caller already has, so it
  // always exists — the `?? ''` is unreachable and only satisfies the type.
  return assetUrl(`/vehicles/passes/${encodeURIComponent(passId)}/snapshot`) ?? '';
}

/** The most recent register import, or null if there has never been one.
 *
 *  404 from the engine means "nobody has ever imported anything", which is a
 *  fact about a fresh register rather than a failure — so it comes back as
 *  null and the console draws no line at all. A row of zeros would read as a
 *  failed import rather than as an import that never happened. */
export async function getVehicleLastImport(): Promise<W.VehicleImportRun | null> {
  try {
    return await get<W.VehicleImportRun>('/vehicles/import/last');
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}


/** Download the pass log as a CSV.
 *
 *  A POST, and not by accident. The engine writes the audit entry before it
 *  builds the file, and a GET that writes is a GET that lies about being
 *  safe. It is also why only an administrator can call it. */
export async function exportVehiclePasses(
  filters: {
    plate?: string; gate?: number; direction?: string; status?: string;
    day?: string;
  } = {},
): Promise<void> {
  const query: Record<string, string> = {};
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== '' && value !== null) query[key] = String(value);
  }
  await download('/vehicles/export', {
    method: 'POST',
    query,
    fallbackName: 'vehicle-passes.csv',
  });
}

/* ---------- track a person ----------
 *
 *  RETIRED. `trackPerson()` called `POST /track`, which rebuilt a path out of
 *  every stored sighting — including the single-frame recognitions that were
 *  never good enough to claim. The Track page now asks `GET /path/{person}`
 *  instead, which reads the anchor table: only stops whose evidence cleared
 *  the bar were ever written there, so a wrong leg cannot come back by
 *  construction. See `getPathSkeleton` above.
 *
 *  The engine keeps serving /track — wire changes here are additive only, and
 *  something outside this repo may still be asking. Nothing in this console
 *  does. */

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

export async function getSystemHealth(lang: Language): Promise<SystemHealth> {
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
    camerasDisabled: health.camerasDisabled ?? 0,
    summary: parts.length
      ? `${parts.join('; ')}.`
      : 'Everything is recording and being analysed.',
    stats: formatMetrics(health.metrics, lang),
    // Left undefined, never defaulted to an empty projection: a machine with
    // nothing running has no share to report, and zeros would read as a
    // machine with room to spare.
    capacity: health.capacity
      ? {
          gpuMsPerSecond: health.capacity.gpuMsPerSecond,
          gpuBudgetMs: health.capacity.gpuBudgetMs,
          cpuMsPerSecond: health.capacity.cpuMsPerSecond,
          cpuBudgetMs: health.capacity.cpuBudgetMs,
          cores: health.capacity.cores,
          unplacedMsPerSecond: health.capacity.unplacedMsPerSecond ?? 0,
          allMeasured: health.capacity.allMeasured !== false,
          // The readings sit on the projection they check. Absent, not 0,
          // when the engine could not ask the driver or the OS.
          gpuPercent: health.gpuPercent ?? undefined,
          gpuMemoryUsedMb: health.gpuMemoryUsedMb ?? undefined,
          gpuMemoryTotalMb: health.gpuMemoryTotalMb ?? undefined,
          cpuMachinePercent: health.cpuMachinePercent ?? undefined,
          // psutil reports a process as a sum over cores; the machine has
          // `cores` of them, so this is its share of the whole.
          cpuEnginePercent:
            health.cpuPercent != null && health.capacity.cores > 0
              ? health.cpuPercent / health.capacity.cores
              : undefined,
          gpuBusyMsPerSecond: health.capacity.gpuBusyMsPerSecond ?? 0,
          cpuBusyMsPerSecond: health.capacity.cpuBusyMsPerSecond ?? 0,
          windowSeconds: health.capacity.windowSeconds ?? 5,
          rows: health.capacity.rows.map((r) => ({
            name: r.name,
            // The engine sends null when a worker could not say which
            // processor it uses. That becomes 'unplaced' here rather than
            // being folded into either pool, because a row charged to the
            // wrong budget makes both totals wrong.
            pool: r.pool === 'gpu' || r.pool === 'cpu' ? r.pool : ('unplaced' as const),
            device: r.device ?? undefined,
            cameras: r.cameras,
            framesPerSecond: r.framesPerSecond ?? undefined,
            msPerFrame: r.msPerFrame,
            measured: r.measured,
            msPerSecond: r.msPerSecond ?? undefined,
            onDemand: r.onDemand === true,
            shared: r.shared === true,
            busyMsPerSecond: r.busyMsPerSecond ?? 0,
            analysedPerSecond: r.analysedPerSecond ?? 0,
          })),
        }
      : undefined,
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
      workers: p.workers?.map((w) => ({
        name: w.name,
        cameras: w.cameras,
        framesProcessed: w.framesProcessed,
        lastInferenceMs: w.lastInferenceMs,
        queueDepth: w.queueDepth,
        queueMax: w.queueMax,
        framesDropped: w.framesDropped,
        // The engine omits `behind` when it could not read a counter. Absent
        // is not the same as false, but the row only ever draws a warning,
        // so treating unknown as "no warning" is the honest direction to
        // round in - the stage detail still names anything genuinely behind.
        behind: w.behind === true,
      })),
    })),
    cameras: toCameras(health.cameras, lang),
  };
}

export async function getUsers(lang: Language): Promise<User[]> {
  const users = await get<W.User[]>('/users');
  return users.map((u) => ({
    id: u.id,
    name: u.name,
    role: u.role,
    email: u.email,
    lastActive: u.lastActive ? formatEventTime(u.lastActive, lang) : '—',
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
function lastSeenLine(p: W.DirectoryPerson, lang: Language): string {
  if (!p.lastSeen) return 'Not seen yet';
  const when = formatEventTime(p.lastSeen, lang);
  return p.lastCamera ? `${p.lastCamera} · ${when}` : when;
}

function toDirectoryPerson(p: W.DirectoryPerson, lang: Language): DirectoryPerson {
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
    enrolled: p.enrolledAt ? `Enrolled ${formatEventTime(p.enrolledAt, lang)}` : '',
    lastSeen: lastSeenLine(p, lang),
    // Nothing recording attendance is not the same as being absent, so the
    // row says nothing at all rather than guessing.
    today: status ? attendanceLabel(status, lang) : '',
    todayTone: status ? attendanceTone(status) : 'neutral',
  };
}

export async function getPeople(lang: Language): Promise<DirectoryPerson[]> {
  const people = await get<W.DirectoryPerson[]>('/people');
  return people.map((p) => toDirectoryPerson(p, lang));
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

/* ---------- sweeping a window ---------- */

/** What that sweep would cost. Nothing runs and nobody is looked at, which is
 *  why this one is not audited. */
export const estimateSweep = (req: W.SweepRequest) =>
  post<W.SweepEstimate>('/path/sweep/estimate', req);

/** Run it. 422 when the same estimate says it is too big — the message
 *  carries the arithmetic, so the operator can narrow the window. */
export const startSweep = (req: W.SweepRequest) => post<W.SweepJob>('/path/sweep', req);

export const getSweep = (jobId: string) =>
  get<W.SweepJob>(`/path/sweep/${encodeURIComponent(jobId)}`);

/** Stop it. Stopped means stopped: the hits so far are what it found, never
 *  presented as everything there was. */
export const stopSweep = (jobId: string) =>
  del<W.SweepJob>(`/path/sweep/${encodeURIComponent(jobId)}`);

/** Follow a body clicked in a chunk onto other cameras. Every hit comes back
 *  as APPEARANCE and carries no name — clothing is not an identification. */
export const followStranger = (
  point: { jobId: string; chunk: number; x: number; y: number },
  sweep: W.SweepRequest,
) => post<W.SweepJob>('/path/sweep/stranger', { point, sweep });

/* ---------- the video behind a stop ---------- */

/** Queue the recorded video for one stop. Returns straight away with a job. */
export const startLeg = (req: W.LegRequest) => post<W.LegJob>('/path/legs', req);

/** Poll a leg. `chunkUrls` grows as pieces land. */
export const getLeg = (jobId: string) =>
  get<W.LegJob>(`/path/legs/${encodeURIComponent(jobId)}`);

/** Absolute URL for a chunk, so a `<video>` can play it directly. */
export const legChunkUrl = (path: string) => assetUrl(path) ?? path;

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

export async function commitEnrolment(
  sessionId: string,
  lang: Language,
): Promise<DirectoryPerson> {
  const p = await post<W.DirectoryPerson>(`/enrolment/sessions/${sessionId}/commit`);
  return toDirectoryPerson(p, lang);
}

export async function cancelEnrolment(sessionId: string): Promise<void> {
  await del<void>(`/enrolment/sessions/${sessionId}`);
}

export async function getGroups(lang: Language): Promise<GroupSummary[]> {
  const groups = await get<W.GroupSummary[]>('/groups');
  return groups.map((g) => ({
    name: g.name,
    count: g.classes
      ? `${formatCount(g.people, lang)} students · ${g.classes} classes`
      : `${formatCount(g.people, lang)} people`,
    here: g.here,
  }));
}

export async function getGroup(
  name: string,
  lang: Language,
): Promise<{ summary: GroupSummary; roster: GroupMember[] }> {
  const detail = await get<W.GroupDetail>(`/groups/${encodeURIComponent(name)}`);
  const g = detail.summary;
  return {
    summary: {
      name: g.name,
      count: g.classes
        ? `${formatCount(g.people, lang)} students · ${g.classes} classes`
        : `${formatCount(g.people, lang)} people`,
      here: g.here,
    },
    roster: detail.roster.map((r) => ({
      name: r.person.name ?? translate(lang, 'person.unknown'),
      sub: r.location ?? '',
      status: attendanceStatusLine(r.status, r.seenAt, lang),
      tone: attendanceTone(r.status),
    })),
  };
}

export async function getHistory(name: string, lang: Language): Promise<PersonHistory> {
  const h = await get<W.PersonHistory>(`/people/${encodeURIComponent(name)}/history`);
  return {
    name: h.person.name,
    sub: personSub(h.person),
    heading: `${h.presentDays} of ${h.totalDays} days present`,
    lead: h.periodLabel,
    stats: formatMetrics(h.metrics, lang),
    // One person on one day is here or not, so the bar is full or empty and
    // the colour carries the rest. A percentage per day would have read as
    // "60% present on Tuesday", which means nothing for one child.
    bars: h.trend.map((t) => ({
      date: t.date,
      day: t.label,
      label: attendanceLabel(t.status, lang),
      pct: t.status === 'absent' ? 0 : 100,
      tone: attendanceTone(t.status),
    })),
    flags: h.flags.map((f) => ({
      date: formatShortDate(f.date, lang),
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

function toRecording(r: W.Recording, lang: Language): Recording {
  return {
    id: r.id,
    cameraId: r.cameraId,
    cameraName: r.cameraName ?? null,
    state: r.state,
    startedAt: formatTime(r.startedAt, lang),
    seconds: Math.round(r.seconds),
    frames: r.frames,
    file: r.file ?? null,
    reason: r.reason ?? null,
    maxSeconds: r.maxSeconds,
  };
}

function toRecordingResult(result: W.RecordingResult, lang: Language): RecordingResult {
  return {
    ok: result.ok,
    recording: result.recording ? toRecording(result.recording, lang) : null,
    reason: result.reason ?? null,
  };
}

export async function getRecording(
  cameraId: string,
  lang: Language,
): Promise<RecordingResult> {
  return toRecordingResult(
    await get<W.RecordingResult>(`/cameras/${encodeURIComponent(cameraId)}/recording`),
    lang,
  );
}

export async function startRecording(
  cameraId: string,
  actor: string,
  lang: Language,
): Promise<RecordingResult> {
  return toRecordingResult(
    await post<W.RecordingResult>(
      `/cameras/${encodeURIComponent(cameraId)}/recording`,
      undefined,
      { actor },
    ),
    lang,
  );
}

export async function stopRecording(
  cameraId: string,
  actor: string,
  lang: Language,
): Promise<RecordingResult> {
  return toRecordingResult(
    await del<W.RecordingResult>(
      `/cameras/${encodeURIComponent(cameraId)}/recording`,
      { actor },
    ),
    lang,
  );
}

/* ---------- camera sources (onboarding) ---------- */

/** CHANGED: was synchronous. */
export async function getCameraSources(): Promise<CameraSource[]> {
  const sources = await get<W.CameraSource[]>('/sources');
  return sources.map(toSource);
}

/** CHANGED: was synchronous. */
export async function getAreaOptions(): Promise<string[]> {
  return get<string[]>('/sources/areas');
}

/** CHANGED: returns a result, not a bare list.
 *
 *  `[]` used to mean both "your network is empty" and "this engine cannot
 *  look", and the console rendered the first sentence for the second case. */
export async function scanNetwork(): Promise<ScanResult> {
  const result = await post<W.ScanResult>('/sources/scan');
  return {
    available: result.available,
    reason: result.reason ?? undefined,
    devices: result.devices.map((d) => ({
      name: d.name,
      ip: d.ip,
      channels: d.channels,
      duplicate: d.duplicate,
      added: d.added,
    })),
  };
}

/** CHANGED: takes the connection details, and KEEPS what comes back.
 *
 *  The original took no arguments, so the host and password the operator typed
 *  never left the component. It then returned `{ channels: result.channels.length }`
 *  — throwing away every channel the engine described, which is why the page
 *  went on generating `CH 1…N` itself. Both halves are fixed here. */
export async function connectDvr(params: {
  host: string;
  port?: number;
  username: string;
  password: string;
  name?: string;
  area?: string;
  template: string;
  channels: string[];
  budget?: number;
}): Promise<DvrConnectResult> {
  const result = await post<W.DvrConnectResult>('/sources/dvr', params);
  return {
    reachable: result.reachable,
    reason: result.reason ?? undefined,
    checked: result.checked,
    status: result.status,
    channels: result.channels.map((c) => ({
      channel: c.channel,
      name: c.name,
      enabled: c.enabled,
      source: c.source,
      checked: c.checked,
      status: c.status,
      resolution: c.resolution ?? undefined,
      latencyMs: c.latencyMs ?? undefined,
      error: c.error ?? undefined,
    })),
  };
}

/** Add several cameras in one act, and get one outcome per camera.
 *
 *  Sixteen channels used to be sixteen calls, and the fourth failing said
 *  nothing about the other twelve. A refused camera is data here, not an
 *  error: the rest are still added. */
export async function addCameras(
  cameras: Parameters<typeof addCamera>[0][],
): Promise<AddCameraOutcome[]> {
  const outcomes = await post<W.AddCameraOutcome[]>('/sources/bulk', { cameras });
  return outcomes.map((o) => ({
    index: o.index,
    ok: o.ok,
    id: o.id ?? undefined,
    source: o.source,
    error: o.error ?? undefined,
  }));
}

/** Correct a camera without deleting it.
 *
 *  Its id does not change, so everything already recorded against it stays
 *  attached — which is the whole reason this exists. */
export async function editCamera(
  id: string,
  changes: {
    name?: string;
    source?: string;
    area?: string;
    fps?: number;
    rotate?: number;
    features?: string[];
    faces?: boolean;
    gate?: number;
    direction?: string;
    enabled?: boolean;
    username?: string;
    password?: string;
  },
): Promise<EditCameraResult> {
  // The object itself, not a string of it: `request` encodes the body, and a
  // body encoded twice reaches the engine as one JSON string, which it
  // refuses with a 422 - so no camera could be edited from the console.
  const result = await request<W.EditCameraResult>(
    `/sources/${encodeURIComponent(id)}`,
    { method: 'PATCH', body: changes },
  );
  return {
    camera: toSource(result.camera),
    shadowsConfig: result.shadowsConfig,
    restarted: result.restarted,
    featureNotes: result.featureNotes.map((n) => ({
      feature: n.feature,
      running: n.running,
      reason: n.reason ?? undefined,
    })),
  };
}

/** CHANGED: takes the source to test, for the same reason as `connectDvr`.
 *
 *  A failed test comes back as a normal result with `offline: true` rather than
 *  a thrown error, so the page can render the failure inline. */
export async function testConnection(params: {
  source: string;
  username?: string;
  password?: string;
}, lang: Language): Promise<Camera> {
  const result = await post<W.TestConnectionResult>('/sources/test', params);

  if (!result.ok || !result.camera) {
    return {
      id: 'test-frame',
      name: 'Test frame',
      status: result.error ?? translate(lang, 'camera.couldNotConnect'),
      offline: true,
      boxes: [],
    };
  }

  return toCamera(result.camera, lang, result.latencyMs
    ? translate(lang, 'camera.connectionOkLatency', { ms: Math.round(result.latencyMs) })
    : translate(lang, 'camera.connectionOk'));
}

/* ---------- home ---------- */

export async function getAttention(): Promise<W.AttentionItem[]> {
  return get<W.AttentionItem[]>('/attention');
}

/** Acknowledge one Home item. No body: the engine takes the name from the
 *  session - a body-supplied actor let anybody sign as anybody. */
export async function acknowledgeAttention(id: string): Promise<void> {
  await post<W.AttentionItem>(`/attention/${encodeURIComponent(id)}/ack`);
}

/* ---------- settings ---------- */

export const getSchoolProfile = () => get<W.SchoolProfile>('/settings/school');

/* ---------- alert delivery (spec 013) ----------
 *
 * Every write is an administrator's, decided by the engine by path; the page
 * hiding its controls from a guard is only a hint. The console never talks to
 * Gmail: it configures and reads, and the engine sends. */

export const getAlertSettings = () => get<W.AlertSettings>('/settings/alerts');

export const updateAlertRule = (kind: W.AlertKind, change: W.AlertRuleUpdate) =>
  patch<W.AlertRule>(`/settings/alerts/rules/${encodeURIComponent(kind)}`, change);

export const addRecipient = (body: W.RecipientCreate) =>
  post<W.Recipient>('/settings/alerts/recipients', body);

export const updateRecipient = (id: string, change: W.RecipientUpdate) =>
  patch<W.Recipient>(`/settings/alerts/recipients/${encodeURIComponent(id)}`, change);

export const removeRecipient = (id: string) =>
  del<void>(`/settings/alerts/recipients/${encodeURIComponent(id)}`);

/** Really sends. The row comes back queued (or skipped, with why); the
 *  courier's answer appears in the delivery log a moment later. */
export const sendTestAlert = (id: string) =>
  post<W.DeliveryRow>(`/settings/alerts/recipients/${encodeURIComponent(id)}/test`);

export const getDeliveries = (limit = 50) =>
  get<W.DeliveryLog>('/settings/alerts/deliveries', { limit });

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

/** Create an account and sign it straight in.
 *
 *  Sign-up is open — anyone who can reach the console can do this. The engine
 *  fixes the role at `it`; this file does not send one and could not raise it
 *  if it tried, because the wire type forbids the field. The response is the
 *  same shape as a sign-in, cookie included, so nothing downstream has to
 *  know which door the session came through. */
export async function register(
  name: string, email: string, password: string,
): Promise<Account> {
  const result = await post<W.LoginResult>('/auth/register', { name, email, password });
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
    language: wire.language,
    devSignIn: wire.devSignIn === true, // DEV-SIGNIN
  };
}

/** Change the signed-in account's language.
 *
 *  Only ever your own — the endpoint takes no account id, which is what keeps
 *  a display preference out of the permission surface. */
export async function setAccountLanguage(language: Language): Promise<Account> {
  return toAccount(await post<W.Account>('/auth/language', { language }));
}

/* ---------- Ask ----------
 *
 *  Returns the wire object **unrendered**, unlike most of this file. Every
 *  other function here turns numbers into the sentences the pages expect;
 *  Ask must not, because its sentences come from note codes the page words
 *  through `translate()`. Formatting them here would put English back in a
 *  place P11 just took it out of. */

export const ask = (question: string) =>
  post<W.AskAnswer>('/ask', { question });
