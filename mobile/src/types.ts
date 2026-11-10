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
  /** Plate width in source-frame pixels — the aiming aid, on gate cameras
   *  only. Drawn beside the box, coloured by whether it clears the
   *  comfortable-read line. Absent on every other kind of box. */
  plateWidthPx?: number;
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
  /** The named place this camera watches. The live grid groups by it. */
  area?: string;
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
  /** Empty .. Over capacity. Absent when no capacity is set. */
  level?: PopulationLevel;
}

/** How full a place is, from count and capacity. See `populationLevel`. */
export type PopulationLevel = 'empty' | 'quiet' | 'busy' | 'near' | 'over';

export interface CountResult {
  place: string;
  /** The people counted, summed over cameras. An upper bound where cameras
   *  overlap - nothing here de-duplicates. */
  count: number;
  /** Absent when no capacity is set: no percentage and no level then. */
  level?: PopulationLevel;
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

/** A camera that can be marked a restricted area.
 *
 *  A zone IS a camera: switching one on makes its whole frame restricted, so
 *  there is no polygon here and nothing is drawn inside the view. There is no
 *  `hours` either — a restricted camera is restricted around the clock. */
export interface Zone {
  id: string;
  name: string;
  enabled: boolean;
  /** Scenes recorded on this camera today. A real count, not a guess. */
  detectionsToday: number;
}

/** One scene: somebody was on a restricted camera, from when to when. */
export interface Breach {
  id: string;
  /** The zone it happened in; the camera's id for an old whole-camera zone. */
  zoneId: string;
  zone: string;
  time: string;
  who: string;
  status: string;
  tone: Tone;
  /** Most people seen at once during the scene — not the last count, which is
   *  zero for every scene that has ended. */
  people: number;
  /** How long they were there, e.g. "12 seconds". */
  duration: string;
  /** Playable clip, present only when one was actually saved. */
  clipUrl?: string;
  /** Why there is no clip. Shown beside the disabled button, never on its own. */
  clipReason?: string;
  /** none | recording | saved | replaced | failed. */
  clipState?: string;
  /** True when the scene ran into the maximum clip length and was cut. */
  cut: boolean;
}

/** One zone as the Zones page draws it. `Zone` above stays what the phone
 *  reads; this adds the polygon and the state the engine built from what the
 *  detector last saw (spec 025). */
export type ZoneStatus =
  | 'personInZone'
  | 'clear'
  | 'paused'
  | 'outsideHours'
  | 'cameraOffline'
  | 'detectorStopped';

export type WatchedMode = 'always' | 'outsideWorking' | 'working' | 'custom';

export interface WatchedHours {
  mode: WatchedMode;
  from?: string;
  to?: string;
}

export interface AreaPoint {
  x: number;
  y: number;
}

export interface ZoneCard extends Zone {
  cameraId: string;
  polygon: AreaPoint[];
  status: ZoneStatus;
  /** People with their feet inside right now; null unless the status says the
   *  detector answered. */
  inZoneNow: number | null;
  watched: WatchedHours;
  alertAfterSeconds: number;
  notifyInApp: boolean;
  notifyEmail: boolean;
  pausedBy?: string;
  pausedAt?: string;
  importNote?: string;
  deleted: boolean;
}

export interface ZoneDraft {
  name: string;
  cameraId: string;
  polygon: AreaPoint[];
  watched: WatchedHours;
  alertAfterSeconds: number;
  notifyInApp: boolean;
  notifyEmail: boolean;
}

export type StationState = 'on' | 'away' | 'absent' | 'notStarted' | 'closed' | 'unknown';

export interface TimelineBar {
  state: 'on' | 'away' | 'absent' | 'notWatched';
  /** Fractions of the timeline's own length, 0..1. */
  start: number;
  width: number;
  from: string;
  to: string;
}

export interface StationLogEvent {
  id: string;
  kind: 'atStation' | 'leftStation' | 'absenceAlert' | 'acknowledged';
  /** Local clock time as the site shows it. */
  time: string;
  limitMinutes?: number;
  byWho?: string;
}

export interface StationCard {
  id: string;
  name: string;
  cameraId: string;
  cameraName: string;
  polygon: AreaPoint[];
  watched: WatchedHours;
  assigneeId?: string;
  assigneeName?: string;
  assigneeMissing: boolean;
  limitMinutes: number;
  notifyInApp: boolean;
  notifyEmail: boolean;
  faceCheck: 'anyone' | 'face' | 'facesTooSmall';
  facePx?: number;
  state: StationState;
  /** Site-local time the state began, when known. */
  since?: string;
  unknownReason?: 'cameraOffline' | 'detectorStopped' | 'notRunning';
  presentNotRecognised: boolean;
  opensAt?: string;
  workSeconds: number;
  absentSeconds: number;
  notWatchedSeconds: number;
  /** null until some time was watched. */
  rate: number | null;
  timeline: TimelineBar[];
  alertEventId?: string;
  deleted: boolean;
  events: StationLogEvent[];
}

export interface StationDraft {
  name: string;
  cameraId: string;
  polygon: AreaPoint[];
  watched: WatchedHours;
  assigneeId?: string;
  limitMinutes: number;
  notifyInApp: boolean;
  notifyEmail: boolean;
}

export interface FaceReachResult {
  facePx: number | null;
  needed: number;
}

/** Window tokens, not the words on the button.
 *
 *  These go to the engine as `?window=last30`. The wording lives in
 *  `web/src/i18n/` under `window.*`, so a rewording - or an Arabic one -
 *  never touches the API. */
export type IntrusionWindow = 'today' | 'last7' | 'last30';

/* ---------- weapons ---------- */

export type WeaponWindow =
  | 'today'
  | 'yesterday'
  | 'last7'
  | 'last30'
  | 'last90'
  | 'schoolYear'
  | 'all';

/** Where a detection has got to. Nothing moves back out of the last two.
 *
 *  Spelled out here rather than imported from `wire.ts`: this file is the
 *  shapes the UI renders and deliberately does not depend on the wire. */
export type WeaponVerdict = 'pending' | 'confirmed' | 'dismissed';

export interface WeaponDetection {
  id: string;
  camera: string;
  area: string;
  time: string;
  duration: string;
  confidence: string;
  status: string;
  tone: Tone;
  verdict: WeaponVerdict;
  reviewer?: string;
  reviewedAt?: string;
  /** The knife is still in view: the duration is still growing. */
  running: boolean;
  /** The scene hit the two-minute limit; a second entry may follow it. */
  cut: boolean;
  clipUrl?: string;
  /** Why there is no video. Shown where the button would be. */
  clipReason?: string;
}

/* ---------- lost items ---------- */

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

/** One feature worker's load, ready to render.
 *
 *  Every figure is a real counter. Nothing here is derived from a sample or
 *  an average, so a number on this row can be checked against the engine. */
export interface WorkerLoadItem {
  name: string;
  cameras: number;
  framesProcessed: number;
  lastInferenceMs: number;
  queueDepth: number;
  queueMax: number;
  framesDropped: number;
  behind: boolean;
}

export interface PipelineItem {
  name: string;
  detail: string;
  status: string;
  /** How the engine rated this stage. Carried through because the page used
   *  to render every row green, so "Needs attention" arrived in a healthy
   *  badge - the engine did the honest work and the UI discarded it. */
  tone: Tone;
  /** Only the feature-workers row carries these. */
  workers?: WorkerLoadItem[];
}

/** One worker's projected share of the machine, ready to render.
 *
 *  `measured` is the field that matters. True means the per-frame cost was
 *  timed on this machine; false means it is a figure carried in from an
 *  earlier run because this worker has not analysed a frame yet. A reader
 *  deciding whether to add a camera needs to know which they are reading. */
export interface CapacityRowItem {
  name: string;
  /** 'unplaced' when the worker did not say which processor it runs on. Such
   *  a row is listed and left out of both totals, never guessed into one. */
  pool: 'gpu' | 'cpu' | 'unplaced';
  device?: string;
  cameras: number;
  framesPerSecond?: number;
  msPerFrame: number;
  measured: boolean;
  msPerSecond?: number;
  /** Runs only while somebody is looking at the tile, so it costs nothing
   *  when nobody is and no fixed number when somebody is. */
  onDemand: boolean;
  /** The one person detection every counting/zone/track/knife worker reads,
   *  costed once. Their own rows have it subtracted. */
  shared: boolean;
  /** Measured over the window: what it really spent, and how many frames. */
  busyMsPerSecond: number;
  analysedPerSecond: number;
}

/** How full the machine is, as arithmetic over what is configured.
 *
 *  Two budgets, never one number. The GPU gives 1000 ms of work a second;
 *  the processor gives `cores` x 1000. Face recognition has no CUDA path, so
 *  it never competes with the person detector for the same milliseconds —
 *  adding the two would produce a percentage of nothing. */
export interface CapacityItem {
  gpuMsPerSecond: number;
  gpuBudgetMs: number;
  cpuMsPerSecond: number;
  cpuBudgetMs: number;
  cores: number;
  unplacedMsPerSecond: number;
  allMeasured: boolean;
  /** Readings from the driver and the OS, whole device / whole machine.
   *  These draw the bars. Absent when there is nothing to ask. */
  gpuPercent?: number;
  gpuMemoryUsedMb?: number;
  gpuMemoryTotalMb?: number;
  cpuMachinePercent?: number;
  /** This engine's process share of the machine, 0–100. */
  cpuEnginePercent?: number;
  /** Measured totals per pool: what this engine's workers really spent. */
  gpuBusyMsPerSecond: number;
  cpuBusyMsPerSecond: number;
  windowSeconds: number;
  rows: CapacityRowItem[];
}

export interface SystemHealth {
  camerasOnline: number;
  /** Switched-on cameras only. */
  camerasTotal: number;
  /** Switched off on purpose — not offline, and not a fault. */
  camerasDisabled: number;
  /** System memory. Absent when the engine could not read it - never 0. */
  memoryUsedMb?: number;
  memoryTotalMb?: number;
  /** True when the engine could read the graphics card. False means the
   *  board has no separate graphics memory, so the memory above is shared. */
  hasGpuReading: boolean;
  summary: string;
  stats: Stat[];
  /** Absent when no worker is running. Not zero — that would read as a
   *  machine with room, which is a different claim from "nothing to cost". */
  capacity?: CapacityItem;
  recorders: Recorder[];
  pipeline: PipelineItem[];
  cameras: Camera[];
}

/* ---------- home ---------- */

export type ToolId =
  | 'attendance'
  | 'counting'
  | 'intrusion'
  | 'stations'
  | 'weapons'
  | 'vehicles'
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
  /** Where opening it goes: the page, and the one thing on it when the engine
   *  named one - `/weapons?entry=…`. `to` alone opens the page and leaves the
   *  reader to find the item. */
  link: string;
}

/* ---------- people directory ---------- */

export type PersonType = 'Student' | 'Staff' | 'Visitor';

export interface DirectoryPerson {
  id: string;
  name: string;
  type: PersonType;
  sub: string;
  photoOnFile: boolean;
  /** "Recognised · 3 photos" / "Cannot be recognised — no face on file". */
  recognition: string;
  /** "Enrolled Aug 15" — or "" when the engine has no date for them. */
  enrolled: string;
  /** "Main entrance · Today, 7:42am" or "Not seen yet". Never a dash: a
   *  missing value is stated in words so a reader knows it was looked for. */
  lastSeen: string;
  /** Today's attendance in words, or "" when nothing is recording it. */
  today: string;
  todayTone: Tone;
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

/* Alert rules, recipients and the delivery log have no UI shapes of their own:
 * Settings renders the wire types (`services/wire.ts`) directly, because every
 * field there is already a fact the page words - there is nothing to convert. */

/* ---------- camera sources (System health) ---------- */

export type SourceStatus = 'ok' | 'down' | 'auth';
export type SourceType = 'NVR' | 'DVR' | 'IP camera' | 'RTSP';

export interface CameraSource {
  id: string;
  name: string;
  type: SourceType;
  /** The address with any password masked. The engine never sends the raw one. */
  ip: string;
  channels: number;
  status: SourceStatus;
  area?: string;
  lastError?: string;
  /** What this camera is watched for, and the settings those features need. */
  features: string[];
  faces: boolean;
  enabled: boolean;
  gate?: number;
  direction?: string;
  fps: number;
  rotate: number;
  /** Seeded by engine.yaml. Editing it writes a row that shadows the file. */
  fromConfig: boolean;
}

/** One chosen feature, and whether it is actually running.
 *
 *  A feature whose subsystem failed to start is reported here at the moment
 *  it is chosen, rather than only on System Health where nobody was looking. */
export interface FeatureNote {
  feature: string;
  running: boolean;
  reason?: string;
}

/** What happened to one camera in a bulk add. A refusal is data, not an error. */
export interface AddCameraOutcome {
  index: number;
  ok: boolean;
  id?: string;
  source: string;
  error?: string;
}

export interface EditCameraResult {
  camera: CameraSource;
  shadowsConfig: boolean;
  restarted: boolean;
  featureNotes: FeatureNote[];
}

export interface FoundDevice {
  name: string;
  ip: string;
  channels: number;
  duplicate: boolean;
  added: boolean;
}

/** One recorder channel, and what actually happened when it was opened.
 *
 *  `checked: false` means the probe budget ran out before this channel was
 *  tried - a different fact from "we asked and nothing came back", and the
 *  two must not render alike. */
export interface DvrChannel {
  channel: string;
  name: string;
  enabled: boolean;
  source: string;
  checked: boolean;
  status: SourceStatus;
  resolution?: string;
  latencyMs?: number;
  error?: string;
}

export interface DvrConnectResult {
  reachable: boolean;
  reason?: string;
  checked: number;
  status: SourceStatus;
  channels: DvrChannel[];
}

/** Whether the network can be searched at all, and what was found.
 *
 *  `available: false` is "we cannot look"; `available: true` with no devices
 *  is "we looked and found nothing". A bare array made those the same. */
export interface ScanResult {
  available: boolean;
  reason?: string;
  devices: FoundDevice[];
}

export type SourceMode = 'scan' | 'dvr' | 'ip' | 'rtsp';
