/** Domain types for the VisionGuard mobile app.
 *
 *  Mirrors the web console's shapes where it makes sense, but the mobile
 *  design collapses every tool into one generic screen driven by a single
 *  "answer" object — so the types here follow that shape instead of having
 *  one bespoke result type per tool. */

export type Role = 'admin' | 'it';

export interface Account {
  name: string;
  role: Role;
  initials: string;
  email: string;
}

export type Tone = 'good' | 'warn' | 'bad' | 'neutral';

/* ---------- cameras & detection overlays ---------- */

export type BoxColor = 'green' | 'red' | 'blue' | 'amber';

export interface DetectionBox {
  x: number;
  y: number;
  w: number;
  h: number;
  color: BoxColor;
  label?: string;
}

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
  status: string;
  offline?: boolean;
  time?: string;
  boxes?: DetectionBox[];
  zone?: CameraZone;
  countLine?: number;
}

export interface Stat {
  label: string;
  value: string;
}

/* ---------- tools ---------- */

export type ToolId = 'attend' | 'count' | 'lost' | 'track' | 'weapon' | 'intrude';

export interface ToolField {
  key: string;
  label: string;
  options: string[];
}

export interface ToolDef {
  id: ToolId;
  title: string;
  /** one-line sentence under the title on the tool screen */
  lead: string;
  /** three-or-four-word summary, used in the Tools list */
  blurb: string;
  runLabel: string;
  emptyText: string;
  camTitle: string;
  camNote: string;
  fields: ToolField[];
}

export interface AnswerRow {
  name: string;
  sub: string;
  badge: string;
  tone: Tone;
}

export interface AnswerBar {
  label: string;
  value: string;
  pct: number;
}

export interface AnswerPathStop {
  time: string;
  place: string;
  detail: string;
}

export interface AnswerCard {
  id: string;
  title: string;
  meta: string;
  badge: string;
  tone: Tone;
  criticalUnacked: boolean;
  acked: boolean;
}

export interface MapZone {
  name: string;
  label: string;
  value: string;
  x: number;
  y: number;
  w: number;
  h: number;
  tone: Tone;
}

export interface MapArea {
  name: string;
  value: string;
  pct: number;
  tone: Tone;
}

export interface ToolAnswer {
  heading: string;
  sub: string;
  logged?: boolean;
  stats: Stat[];
  rowsTitle?: string;
  rows?: AnswerRow[];
  barsTitle?: string;
  bars?: AnswerBar[];
  path?: AnswerPathStop[];
  cards?: AnswerCard[];
  foot?: string;
  hasMap?: boolean;
  map?: MapZone[];
  areas?: MapArea[];
  cameras: Camera[];
  isWeapon?: boolean;
}

/* ---------- weapons workflow ---------- */

export type WeaponState = 'clear' | 'live' | 'confirmed' | 'dismissed';

export interface WeaponStep {
  icon: string;
  tone: Tone;
  title: string;
  sub: string;
}

/* ---------- intrusion zones ---------- */

export interface Zone {
  id: string;
  name: string;
  hours: string;
  enabled: boolean;
}

/* ---------- home ---------- */

export interface AttentionItem {
  id: string;
  kind: string;
  /** character shown in the filled circle on the badge */
  icon: string;
  tone: Tone;
  title: string;
  sub: string;
  action: string;
  tool: ToolId;
}

export interface RecentItem {
  id: string;
  title: string;
  sub: string;
  tool: ToolId;
}

/* ---------- people directory ---------- */

export type PersonType = 'Student' | 'Staff' | 'Visitor';

export interface DirectoryPerson {
  name: string;
  type: PersonType;
  sub: string;
  guardian: string;
  photoOnFile: boolean;
  attendanceToday: string;
}

export interface GroupSummary {
  name: string;
  count: string;
  here: number;
}

export interface GroupMember {
  name: string;
  sub: string;
  status: string;
  tone: Tone;
}

export interface AttendanceBar {
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

/* ---------- account / settings ---------- */

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

/* ---------- system / camera sources ---------- */

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

export interface SystemSummary {
  camerasOnline: number;
  camerasTotal: number;
  summary: string;
  gpu: string;
  storage: string;
}
