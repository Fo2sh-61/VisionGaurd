/** What the engine actually sends.
 *
 *  These mirror `engine/vg/api/schemas.py`. They are deliberately NOT the same
 *  as `@/types` — the engine sends numbers, ISO-8601 UTC instants and enums;
 *  `@/types` are the rendered shapes the pages draw. `format.ts` converts one
 *  into the other, which is why the pages never had to change.
 *
 *  Keep this file in sync with the OpenAPI document at /docs. If the two ever
 *  disagree, the engine's document wins. */

/* ---------- primitives ---------- */

export type Severity = 'info' | 'warn' | 'critical';
export type MatchKind = 'face' | 'appearance' | 'none';
export type SourceStatus = 'ok' | 'down' | 'auth';
export type SourceType = 'NVR' | 'DVR' | 'IP camera' | 'RTSP';
export type PersonType = 'Student' | 'Staff' | 'Visitor';
export type ReviewVerdict = 'pending' | 'confirmed' | 'dismissed';
export type BreachStatus = 'open' | 'authorised' | 'resolved';
export type ScheduleMode = 'outside' | 'inside' | 'always';
export type AttendanceStatus = 'on_time' | 'late' | 'absent' | 'unknown';

/** A moment in time.
 *
 *  `utc` is the truth; `tzOffsetMinutes` is the *school's* offset, not the
 *  viewer's. Rendering uses both so a phone abroad still shows the time the
 *  school experienced. */
export interface Instant {
  utc: string;
  tzOffsetMinutes: number;
}

/** Fractions of the frame, origin top-left. Multiply by 100 for the UI. */
export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
  label?: string | null;
  confidence?: number | null;
  kind: 'person' | 'weapon' | 'object' | 'face' | 'match';
  match: MatchKind;
  severity: Severity;
  /** The appearance identity following this body. Holds across leaving the
   *  frame and across cameras — with or without a face ever being seen. */
  trackId?: string | null;
}

export interface Point {
  x: number;
  y: number;
}

export interface ZoneOverlay {
  id: string;
  label: string;
  polygon: Point[];
  enabled: boolean;
}

export interface CameraView {
  id: string;
  name: string;
  /** The named place this camera watches. What the live grid partitions by. */
  area: string;
  /** True when faces are the point on this camera — the identity tier. False
   *  is the patrol tier, which recognises far more slowly. */
  faces: boolean;
  offline: boolean;
  capturedAt?: Instant | null;
  /** True when this is the last good frame of a dropped stream. */
  stale: boolean;
  peopleCount?: number | null;
  boxes: Box[];
  zone?: ZoneOverlay | null;
  countLine?: number | null;
  snapshotUrl?: string | null;
  streamUrl?: string | null;
}

/** Everything that changes frame to frame, in one payload.
 *
 *  Boxes and headcount travel together because they come from the same
 *  inference pass — split across two polls they could disagree by a frame. */
export interface CameraDetections {
  cameraId: string;
  at?: Instant | null;
  boxes: Box[];
  /** null means nothing measured this camera — not zero. */
  peopleCount?: number | null;
  inferenceMs?: number | null;
}

/** A number plus what kind of number it is, so the UI can format it. */
export interface Metric {
  key: string;
  label: string;
  value?: number | null;
  unit: 'count' | 'percent' | 'seconds' | 'ratio' | 'text';
  text?: string | null;
  total?: number | null;
  severity: Severity;
}

export interface Clip {
  id: string;
  url: string;
  thumbnailUrl?: string | null;
  durationSeconds: number;
  startsAt: Instant;
}

export interface PersonRef {
  id?: string | null;
  name?: string | null;
  type?: PersonType | null;
  match: MatchKind;
  confidence?: number | null;
}

/* ---------- intrusion ---------- */

export interface Schedule {
  mode: ScheduleMode;
  days: string[];
  start?: string | null;
  end?: string | null;
}

export interface Zone {
  id: string;
  name: string;
  cameraId: string;
  schedule: Schedule;
  enabled: boolean;
  polygon: Point[];
  breachesToday: number;
}

export interface Breach {
  id: string;
  zoneId: string;
  zoneName: string;
  cameraId: string;
  cameraName: string;
  at: Instant;
  subject: PersonRef;
  status: BreachStatus;
  severity: Severity;
  confidence: number;
  dwellSeconds: number;
  clip?: Clip | null;
  modelVersion?: string | null;
  /** Peak people seen during the scene. Optional so an older engine still
   *  parses; it defaults to 1 there, which is what "somebody was seen" means. */
  people?: number;
  /** none | recording | saved | replaced | failed. Only `saved` has a file. */
  clipState?: string;
  /** Why there is no playable clip. Null when there is one. */
  clipReason?: string | null;
}

/* ---------- weapons ---------- */

export interface WeaponDetection {
  id: string;
  at: Instant;
  cameraId: string;
  cameraName: string;
  location: string;
  item: string;
  confidence: number;
  severity: Severity;
  verdict: ReviewVerdict;
  reviewedBy?: string | null;
  reviewedAt?: Instant | null;
  dismissalReason?: string | null;
  box?: Box | null;
  clip?: Clip | null;
  modelVersion?: string | null;
  /** null means the knife is still in view; `seconds` is then counting up. */
  endedAt?: Instant | null;
  seconds?: number;
  clipState?: string;
  clipReason?: string | null;
  endReason?: string | null;
}

/* ---------- attendance ---------- */

export interface AttendanceRecord {
  person: PersonRef;
  status: AttendanceStatus;
  seenAt?: Instant | null;
  cameraId?: string | null;
  location?: string | null;
  minutesLate?: number | null;
}

export interface AttendanceDay {
  date: string;
  status: AttendanceStatus;
  seenAt?: Instant | null;
  location?: string | null;
  minutesLate?: number | null;
}

export interface AttendanceResult {
  mode: 'group' | 'person';
  date: string;
  subject: string;
  expected: number;
  present: number;
  late: number;
  absent: number;
  metrics: Metric[];
  records: AttendanceRecord[];
  days: AttendanceDay[];
  cameras: CameraView[];
}

/* ---------- counting ---------- */

export interface CountBarPart {
  name: string;
  value: number;
  live: boolean;
}

export interface CountBar {
  label: string;
  value: number;
  at?: Instant | null;
  /** Per-area split of this bucket. A bar with one number and no area attached
   *  is unreadable on a site with six places. */
  parts: CountBarPart[];
}

export interface CountArea {
  id: string;
  name: string;
  count: number;
  capacity: number;
  x: number;
  y: number;
  w: number;
  h: number;
  severity: Severity;
  /** True when a camera measured this. False means it is a demo figure, and
   *  the page has to say so rather than let it pass as real. */
  live: boolean;
}

export interface CountResult {
  place: string;
  count: number;
  capacity?: number | null;
  measuredAt: Instant;
  deduplicated: boolean;
  metrics: Metric[];
  bars: CountBar[];
  barsTitle?: string | null;
  areas: CountArea[];
  cameras: CameraView[];
}

/* ---------- lost items ---------- */

export interface SearchJob {
  id: string;
  /** `stopped` is a finished search that was cut short by hand or replaced by
   *  a newer one. It keeps its hits - stopping is not undoing. */
  state: 'queued' | 'running' | 'done' | 'stopped' | 'failed';
  progress: number;
  submittedAt: Instant;
  /** Always 0. Nothing is recorded, so there are no clips to have searched. */
  clipsSearched: number;
  clipsTotal: number;
  error?: string | null;
}

export interface LostHit {
  cameraId: string;
  cameraName: string;
  at: Instant;
  confidence: number;
  note?: string | null;
  box?: Box | null;
  /** Always null. Nothing is recorded, so there is never a clip to offer. */
  clip?: Clip | null;
  colour?: string | null;
  /** The lenient set: what the colour filter matched against. A dark blue bag
   *  looks black in poor light, so it answers to both. */
  colours?: string[];
}

export interface UnavailableCamera {
  cameraId: string;
  cameraName: string;
  reason: string;
}

export interface LostResult {
  job: SearchJob;
  query: { cameras: string[]; colour?: string | null; item?: string };
  hits: LostHit[];
  cameras: CameraView[];
  camerasChecked: number;
  camerasUnavailable: UnavailableCamera[];
  hiddenByColour: number;
  framesChecked: number;
  secondsLimit: number;
  secondsElapsed: number;
}

/* ---------- track ---------- */

export interface TrackStop {
  at: Instant;
  until?: Instant | null;
  cameraId: string;
  cameraName: string;
  place: string;
  match: MatchKind;
  confidence: number;
  clip?: Clip | null;
}

export interface TrackResult {
  subject: PersonRef;
  date: string;
  /** Receipt proving the audit row was written before this was returned. */
  auditId: string;
  sightings: number;
  firstSeen?: Instant | null;
  lastSeen?: Instant | null;
  metrics: Metric[];
  path: TrackStop[];
  cameras: CameraView[];
}

/* ---------- system ---------- */

export interface Recorder {
  id: string;
  name: string;
  cameras: number;
  online: boolean;
  ip?: string | null;
}

export interface PipelineStage {
  key: string;
  name: string;
  detail: string;
  healthy: boolean;
  severity: Severity;
  restartable: boolean;
  modelVersion?: string | null;
}

/** Where a page's data came from. There is no fourth answer.
 *
 *  'live' is measured. 'unavailable' is an honest refusal and always carries a
 *  reason. 'demo' is invented on purpose and only reachable with VG_MOCK=1. */
export type DataState = 'live' | 'unavailable' | 'demo';

export interface Recording {
  id: string;
  cameraId: string;
  cameraName?: string | null;
  state: 'recording' | 'saved' | 'failed';
  startedAt: Instant;
  stoppedAt?: Instant | null;
  seconds: number;
  frames: number;
  /** Where it landed. null while running, and null when it failed — a path to
   *  a file that was never written is exactly the fake save rule 4 forbids. */
  file?: string | null;
  /** Why it stopped by itself, or why it failed. null after a plain stop. */
  reason?: string | null;
  maxSeconds: number;
}

export interface RecordingResult {
  ok: boolean;
  recording?: Recording | null;
  reason?: string | null;
}

export interface Capability {
  key: string;
  name: string;
  state: DataState;
  /** Why, in the operator's words. Set whenever state is not 'live'. */
  reason?: string | null;
}

export interface SystemHealth {
  camerasOnline: number;
  camerasTotal: number;
  recordersOnline: number;
  recordersTotal: number;
  severity: Severity;
  gpuPercent?: number | null;
  cpuPercent?: number | null;
  storagePercent?: number | null;
  uptimeSeconds?: number | null;
  metrics: Metric[];
  recorders: Recorder[];
  pipeline: PipelineStage[];
  cameras: CameraView[];
}

export interface CameraSource {
  id: string;
  name: string;
  type: SourceType;
  ip: string;
  channels: number;
  status: SourceStatus;
  area?: string | null;
  lastError?: string | null;
}

export interface FoundDevice {
  name: string;
  ip: string;
  channels: number;
  type: SourceType;
  duplicate: boolean;
  added: boolean;
}

export interface DvrChannel {
  channel: string;
  name: string;
  enabled: boolean;
  resolution?: string | null;
}

export interface DvrConnectResult {
  sourceId: string;
  channels: DvrChannel[];
  status: SourceStatus;
}

export interface TestConnectionResult {
  ok: boolean;
  status: SourceStatus;
  camera?: CameraView | null;
  error?: string | null;
  latencyMs?: number | null;
}

/* ---------- directory ---------- */

export interface DirectoryPerson {
  id: string;
  name: string;
  type: PersonType;
  group?: string | null;
  detail?: string | null;
  guardianName?: string | null;
  guardianRelation?: string | null;
  guardianPhone?: string | null;
  photoOnFile: boolean;
  attendanceToday?: AttendanceStatus | null;
  /** How many faces are on file. `photoOnFile` says whether they can be
   *  recognised at all; this says from how many photos. */
  photos?: number;
  enrolledAt?: Instant | null;
  /** Null means never sighted. The page says so in words, never a dash. */
  lastSeen?: Instant | null;
  /** The camera's display name, already resolved by the engine. */
  lastCamera?: string | null;
}

export interface GroupSummary {
  name: string;
  people: number;
  classes?: number | null;
  /** null when nothing is recording attendance. Zero would mean empty. */
  here: number | null;
}

export interface GroupDetail {
  summary: GroupSummary;
  roster: AttendanceRecord[];
}

export interface AttendanceTrend {
  date: string;
  label: string;
  presentRatio: number;
  /** Present is binary for one person on one day; this is what tells a late
   *  morning apart from an on-time one. */
  status: AttendanceStatus;
}

export interface AttendanceFlag {
  date: string;
  detail: string;
  kind: string;
  severity: Severity;
}

export interface PersonHistory {
  person: DirectoryPerson;
  periodLabel: string;
  presentDays: number;
  totalDays: number;
  metrics: Metric[];
  trend: AttendanceTrend[];
  flags: AttendanceFlag[];
}

export interface User {
  id: string;
  name: string;
  email: string;
  role: 'admin' | 'it';
  lastActive?: Instant | null;
}

/* ---------- home / live ---------- */

export interface AttentionItem {
  id: string;
  kind: 'weapon' | 'intrusion' | 'camera' | 'attendance' | 'system';
  at: Instant;
  severity: Severity;
  title: string;
  detail: string;
  target: string;
  targetId?: string | null;
  acknowledged: boolean;
  clip?: Clip | null;
}

export interface LiveEvent {
  type:
    | 'weapon.detected'
    | 'weapon.reviewed'
    | 'intrusion.breach'
    | 'camera.status'
    | 'count.updated'
    | 'system.health';
  at: Instant;
  attention?: AttentionItem | null;
  breach?: Breach | null;
  weapon?: WeaponDetection | null;
  camera?: CameraView | null;
  health?: SystemHealth | null;
}

/* ---------- settings ---------- */

export interface SchoolProfile {
  name: string;
  hoursFrom: string;
  hoursTo: string;
  termFrom: string;
  termTo: string;
  lateCutoff: string;
  timezone: string;
}

export interface AlertRule {
  key: string;
  title: string;
  detail: string;
  push: boolean;
  email: boolean;
  sms: boolean;
}

export interface DeliveryTarget {
  key: 'app' | 'email' | 'sms' | 'wa';
  title: string;
  enabled: boolean;
  destination: string;
  editable: boolean;
}

/** What the app chrome needs before any page loads.
 *
 *  `today` is the SCHOOL's date, decided by the engine — a device with a wrong
 *  clock must not choose which day an attendance register belongs to. */
export interface SiteInfo {
  name: string;
  today: string;
  timezone: string;
  tzOffsetMinutes: number;
  camerasOnline: number;
  camerasTotal: number;
  places: string[];
  areas: string[];
  /** How long recorded clips are kept, from the engine's configuration.
   *  A page that states a retention period must read this rather than
   *  print a number, or it promises something the engine may not do. */
  clipRetentionDays?: number;
}

export interface Problem {
  error: string;
  detail?: string | null;
  retryable: boolean;
}

/* ---------- live tracking ---------- */

/* ---------- sweeping a window ----------
 *
 *  The expensive question, and the only one that states its cost before it
 *  runs. `allowed: false` always carries the reason in words — either the
 *  arithmetic says it is over budget, or nobody has measured this machine. */

export interface SweepRequest {
  /** Empty for a stranger search: nobody has a name to look for. */
  person: string;
  start: string;
  end: string;
  cameraIds?: string[];
  areas?: string[];
}

export interface SweepEstimate {
  seconds: number;
  cameraHours: number;
  cameras: number;
  allowed: boolean;
  reason?: string | null;
  measuredAt?: Instant | null;
}

export interface SweepHit {
  cameraId: string;
  cameraName: string;
  place: string;
  at: Instant;
  until: Instant;
  matches: number;
  score: number;
  facePx: number;
  /** face = a face was recognised. appearance = only the body matched, which
   *  says the same body moved and never who it is. */
  match: MatchKind;
}

export interface SweepJob {
  job: SearchJob;
  cameras: string[];
  hits: SweepHit[];
  segmentsDone: number;
  segmentsTotal: number;
  /** How many pieces had no recorded video behind them. A sweep that examined
   *  nothing must never be read as having found nobody. */
  segmentsMissing: number;
  estimateSeconds?: number | null;
}

/* ---------- the video behind a stop ----------
 *
 *  A leg is fetched and processed in pieces. `chunkUrls` grows while the job
 *  runs, and the player starts on the first rather than waiting for the last.
 *  The URLs are same-origin paths because a `<video src>` cannot send an
 *  Authorization header. */

export interface LegRequest {
  cameraId: string;
  /** ISO-8601 UTC. */
  start: string;
  end: string;
  personId?: string | null;
  descriptorOf?: { jobId: string; chunk: number; x: number; y: number } | null;
}

export interface LegJob {
  job: SearchJob;
  cameraId: string;
  cameraName: string;
  place: string;
  start: Instant;
  seconds: number;
  chunksReady: number;
  chunksTotal: number;
  /** Pieces the archive holds no video for. A stop starts when somebody was
   *  recognised and a recording starts when somebody pressed a button, so a
   *  gap at the front is ordinary. */
  chunksMissing: number;
  /** The archive's own words about the gap, naming what it does hold. */
  gapReason?: string | null;
  chunkUrls: string[];
  nextPrefetched?: string | null;
  /** From what was measured on this machine. null means nobody has measured
   *  it, and the page says the wait is unknown rather than inventing one. */
  estimateSeconds?: number | null;
}

/* ---------- the path behind somebody ----------
 *
 *  Two layers, never merged, because they answer different questions:
 *
 *    anchors     a face was recognised well enough, and often enough, to
 *                claim it. Evidence about IDENTITY.
 *    appearance  the same body was seen again. Evidence about CONTINUITY
 *                only — clothing cannot say which person somebody is, so
 *                nothing in that layer is ever named. */

export interface PathAnchor {
  cameraId: string;
  cameraName: string;
  place: string;
  at: Instant;
  until: Instant;
  /** Separate looks, not frames. */
  matches: number;
  score: number;
  facePx: number;
}

export interface PathSkeleton {
  subject: PersonRef;
  date: string;
  /** Written before this answer was returned, never after. */
  auditId: string;
  anchors: PathAnchor[];
  appearance: TrackStop[];
  cameras: CameraView[];
}

/* ---------- following one person, live ----------
 *
 *  The engine holds the session and advances it on the frames it is already
 *  processing, so a timer runs out and a track is lost whether or not this
 *  page is open. Closing the tab cannot leave a camera recording. */

export interface FollowRequest {
  cameraId: string;
  /** Fractions of the frame, never pixels. */
  x: number;
  y: number;
}

export interface TrailHop {
  cameraId: string;
  cameraName: string;
  place: string;
  at: Instant;
}

export interface FollowRecording {
  state: 'recording' | 'stopped';
  /** manual | timer | track lost, once it has stopped. */
  reason?: string | null;
  timerSecondsLeft?: number | null;
  segments: Recording[];
}

/** `name` appears only after a face has been recognised well enough, several
 *  times, to claim it — and it goes the moment the track does. It is an
 *  annotation on this body in these frames, never a binding that outlives
 *  them. */
export interface FollowView {
  stableId: string;
  cameraId: string;
  cameraName: string;
  place: string;
  since: Instant;
  personId?: string | null;
  name?: string | null;
  match: MatchKind;
  trail: TrailHop[];
  recording?: FollowRecording | null;
  endedReason?: string | null;
}

export interface TrackedIdentity {
  stableId: string;
  cameraId: string;
  cameraName: string;
  at: Instant;
  box: Box;
  personId?: string | null;
  name?: string | null;
  match: MatchKind;
}

export interface LiveTracking {
  running: boolean;
  reason?: string | null;
  cameras: string[];
  identities: TrackedIdentity[];
}

/* ---------- enrolment ----------
 *
 *  No image data crosses this boundary in either direction beyond the upload
 *  itself. The browser keeps its own thumbnails; the engine embeds the photo,
 *  returns an assessment, and drops the pixels. The gallery stores 128-number
 *  vectors and never images — a vector cannot be turned back into a
 *  photograph, which is what limits the exposure of children's biometric data. */

export interface EnrolmentPhoto {
  id: string;
  usable: boolean;
  /** 0-100, from face size and detector confidence. */
  score: number;
  facePixels: number;
  confidence: number;
  /** Cosine similarity against this person's other staged photos. High is bad:
   *  the same pose again adds nothing to recognition. */
  similarity: number;
  /** Rough head turn. The sign distinguishes two angles. */
  yaw: number;
  note: string;
  source: string;
}

/** One face in the enrolment camera's latest frame.
 *
 *  Geometry only — no name, no match, nothing about identity. An enrolment
 *  preview must never claim to know who it is looking at. */
export interface PreviewFace {
  x: number;
  y: number;
  w: number;
  h: number;
  /** Right eye, left eye, nose, mouth corners. Fractions of the frame. */
  points: Point[];
  confidence: number;
}

/** What the enrolment page draws over the live view.
 *
 *  `faces: []` with `offline: false` means the engine looked and nobody was
 *  there. `offline: true` means it could not look — the page shows NO SIGNAL
 *  rather than an empty overlay pretending to have checked. */
export interface EnrolmentPreview {
  cameraId: string;
  at?: Instant | null;
  offline: boolean;
  faces: PreviewFace[];
}

export interface EnrolmentSession {
  id: string;
  name: string;
  type: PersonType;
  personId: string;
  group?: string | null;
  detail?: string | null;
  photos: EnrolmentPhoto[];
  usableCount: number;
  requiredCount: number;
  /** Save stays disabled until this is true. */
  ready: boolean;
  advice: string;
}

/* ---------- auth ---------- */

/** The signed-in user as the engine sees them.
 *
 *  No permissions list and no password hash. The console asks the server what
 *  it may do rather than deciding from a role it holds locally. */
export interface Account {
  id: string;
  name: string;
  email: string;
  role: string;
  initials: string;
}

export interface LoginResult {
  token: string;
  expiresAt: Instant;
  user: Account;
}
