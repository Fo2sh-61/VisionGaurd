/** Domain types for VisionGuard.
 *
 *  These are the shapes the UI renders. Everything in `src/services` currently
 *  fabricates them from mock data; when the AI backend lands, only the service
 *  implementations change — nothing in `src/pages` should need to move. */

export type Role = 'admin' | 'it';

export interface User {
  id: string;
  name: string;
  role: Role;
  email: string;
  lastActive: string;
}

export type Tone = 'good' | 'warn' | 'bad' | 'neutral';

/** How a person was identified at a given moment.
 *
 *  `face` names a person. `appearance` only says it is the same body seen
 *  earlier, with the name carried over from a face match — a weaker claim, and
 *  the UI must keep the two visually distinct wherever both can appear. */
export type MatchKind = 'face' | 'appearance' | 'none';

/* ---------- cameras & detection overlays ---------- */

export type BoxColor = 'green' | 'red' | 'blue' | 'amber';

/** A detection box, positioned in percentages of the frame. */
export interface DetectionBox {
  x: number;
  y: number;
  w: number;
  h: number;
  color: BoxColor;
  label?: string;
  /** Appearance identity, e.g. "p7". Present only on tracked cameras. */
  trackId?: string;
}

/** A restricted-area polygon drawn on the frame (percentages). */
export interface CameraZone {
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
}

export interface Camera {
  id: string;
  name: string;
  /** short status line under the tile, e.g. "Recognising · 2 people" */
  status: string;
  offline?: boolean;
  time?: string;
  boxes?: DetectionBox[];
  zone?: CameraZone;
  /** vertical position (%) of the people-counting line */
  countLine?: number;
  /** Latest frame as a JPEG. Absent for a camera the engine cannot serve,
   *  in which case the tile falls back to the synthetic room. */
  snapshotUrl?: string;
  /** MJPEG endpoint, used by the enlarged view only — it is far too much
   *  bandwidth to run on every tile in a grid. */
  streamUrl?: string;
}

/* ---------- attendance ---------- */

export type AttendanceMode = 'group' | 'person';

export interface AttendanceQuery {
  mode: AttendanceMode;
  group?: string;
  person?: string;
  date: string;
}

export interface Stat {
  label: string;
  value: string;
}

export interface AttendanceRow {
  name: string;
  status: string;
  tone: Tone;
  time: string;
}

export interface AttendanceDay {
  date: string;
  where: string;
  time: string;
  status: string;
  tone: Tone;
}

export interface AttendanceResult {
  mode: AttendanceMode;
  heading: string;
  sub: string;
  stats: Stat[];
  /** group mode only */
  rows?: AttendanceRow[];
  /** person mode only */
  days?: AttendanceDay[];
  cameras: Camera[];
}

/* ---------- people counting ---------- */

export type CountWindow = 'Right now' | 'Today by hour' | 'This week by day';

export interface CountQuery {
  place: string;
  when: CountWindow;
}

export interface CountBarPart {
  name: string;
  value: number;
  /** Whether a camera measured this area, or it is a demo figure. */
  live: boolean;
  /** This area's share of its bar, 0–100. */
  pct: number;
}

export interface CountBar {
  label: string;
  value: number;
  /** 0–100, relative to the tallest bar in the set */
  pct: number;
  /** Per-area split. A bar with one number and no area attached is unreadable
   *  on a site with six places. */
  parts: CountBarPart[];
}

/** One area on the campus floor-plan. Position is in percentages of the plan
 *  box, so a real site map can drop straight in. */
export interface CountArea {
  name: string;
  value: number;
  capacity: number;
  pct: number;
  tone: Tone;
  x: number;
  y: number;
  w: number;
  h: number;
  /** Measured by a camera, as opposed to a demo figure. */
  live: boolean;
}

export interface CountResult {
  place: string;
  heading: string;
  sub: string;
  stats: Stat[];
  barsTitle?: string;
  bars?: CountBar[];
  /** every area on campus, for the "where those people are" plan */
  areas: CountArea[];
  cameras: Camera[];
}

/* ---------- intrusion ---------- */

export interface Zone {
  id: string;
  name: string;
  hours: string;
  enabled: boolean;
}

export interface Breach {
  id: string;
  zone: string;
  time: string;
  who: string;
  status: string;
  tone: Tone;
}

export type IntrusionWindow = 'Today' | 'Last 7 days' | 'Last 30 days';

/* ---------- weapons ---------- */

export type WeaponWindow = 'Last 30 days' | 'Last 90 days' | 'This school year';

export interface WeaponDetection {
  id: string;
  time: string;
  location: string;
  item: string;
  status: string;
  tone: Tone;
}

/* ---------- lost items ---------- */

export interface LostQuery {
  item: string;
  colour: string;
  area: string;
  since: string;
}

export interface LostHit {
  camera: string;
  time: string;
  confidence: number;
  strong: boolean;
  note: string;
}

export interface LostResult {
  label: string;
  sub: string;
  hits: LostHit[];
  cameras: Camera[];
}

/* ---------- track a person ---------- */

export interface TrackQuery {
  who: string;
  date: string;
  from: string;
  to: string;
}

export interface TrackStop {
  time: string;
  place: string;
  detail: string;
  /** How this stop was established. A face names a person; clothing only says
   *  it is the same body seen earlier. The page must never blur the two - the
   *  distinction is what tells an operator how far to trust the path. */
  match: MatchKind;
  confidence: number;
  /** Set when the person stayed in view, so the stop is a span not a moment. */
  until?: string;
}

export interface TrackResult {
  who: string;
  heading: string;
  sub: string;
  stats: Stat[];
  path: TrackStop[];
  cameras: Camera[];
}

/* ---------- system health ---------- */

export interface Recorder {
  id: string;
  name: string;
  cameras: number;
  online: boolean;
}

export interface PipelineItem {
  name: string;
  detail: string;
  status: string;
  action?: string;
}

export interface SystemHealth {
  camerasOnline: number;
  camerasTotal: number;
  summary: string;
  stats: Stat[];
  recorders: Recorder[];
  pipeline: PipelineItem[];
  cameras: Camera[];
}

/* ---------- home ---------- */

export type ToolId =
  | 'attendance'
  | 'counting'
  | 'intrusion'
  | 'weapons'
  | 'lost-items'
  | 'track'
  | 'system'
  | 'users'
  | 'people'
  | 'settings';

export interface AttentionItem {
  id: string;
  kind: string;
  /** character shown in the filled circle on the badge */
  icon: string;
  tone: Tone;
  title: string;
  sub: string;
  action: string;
  to: ToolId;
}

/* ---------- weapons workflow ---------- */

export type WeaponState = 'clear' | 'live' | 'confirmed' | 'dismissed';

export interface WeaponStep {
  icon: string;
  tone: Tone;
  title: string;
  sub: string;
}

/* ---------- people directory ---------- */

export type PersonType = 'Student' | 'Staff' | 'Visitor';

export interface DirectoryPerson {
  name: string;
  type: PersonType;
  sub: string;
  guardian: string;
  photoOnFile: boolean;
}

export interface GroupSummary {
  name: string;
  count: string;
  /** null when nothing is recording attendance. */
  here: number | null;
}

export interface GroupMember {
  name: string;
  sub: string;
  status: string;
  tone: Tone;
}

export interface Recording {
  id: string;
  cameraId: string;
  cameraName: string | null;
  state: 'recording' | 'saved' | 'failed';
  startedAt: string;
  seconds: number;
  frames: number;
  /** Where it landed, for an operator to go and open. */
  file: string | null;
  /** Why it stopped by itself, or why it failed. */
  reason: string | null;
  maxSeconds: number;
}

export interface RecordingResult {
  ok: boolean;
  recording: Recording | null;
  reason: string | null;
}

export interface AttendanceBar {
  /** ISO date. The row key: weekday labels repeat every five rows. */
  date: string;
  day: string;
  label: string;
  pct: number;
  tone: Tone;
}

export interface AttendanceFlag {
  date: string;
  detail: string;
  badge: string;
  tone: Tone;
}

export interface PersonHistory {
  name: string;
  sub: string;
  heading: string;
  lead: string;
  stats: Stat[];
  bars: AttendanceBar[];
  flags: AttendanceFlag[];
}

/* ---------- settings ---------- */

export interface SchoolProfile {
  name: string;
  hoursFrom: string;
  hoursTo: string;
  termFrom: string;
  termTo: string;
  cutoff: string;
}

export type AlertChannel = 'Push' | 'Email' | 'SMS';

export interface AlertRule {
  key: string;
  title: string;
  sub: string;
  channels: Record<AlertChannel, boolean>;
}

export type DeliveryKind = 'app' | 'email' | 'sms' | 'wa';

export interface DeliveryTarget {
  key: DeliveryKind;
  title: string;
  on: boolean;
  dest: string;
  editable: boolean;
  inputType: 'email' | 'tel' | 'text';
  placeholder: string;
}

/* ---------- camera sources (System health) ---------- */

export type SourceStatus = 'ok' | 'down' | 'auth';
export type SourceType = 'NVR' | 'DVR' | 'IP camera' | 'RTSP';

export interface CameraSource {
  id: string;
  name: string;
  type: SourceType;
  ip: string;
  channels: number;
  status: SourceStatus;
}

export interface FoundDevice {
  name: string;
  ip: string;
  channels: number;
  duplicate: boolean;
  added: boolean;
}

export interface DvrChannel {
  channel: string;
  name: string;
  enabled: boolean;
}

export type SourceMode = 'scan' | 'dvr' | 'ip' | 'rtsp';
