/** Turning engine data into the words on screen.
 *
 *  The engine sends numbers, ISO-8601 UTC instants and enums. The pages render
 *  sentences — "1,679 of 1,742 arrived", "7 seconds · 2 people", "Today, 6:12am".
 *  Everything that bridges the two lives here and nowhere else.
 *
 *  Why this file exists rather than the engine just sending the strings:
 *  copy changes and Arabic/RTL would otherwise need a backend deploy, and the
 *  data would be useless to anything but this one screen. The engine stays
 *  honest about what it measured; the UI stays in charge of how it reads. */

import type {
  AttendanceStatus,
  Box as WireBox,
  CameraView,
  Instant,
  MatchKind,
  Metric,
  Severity,
  ZoneOverlay,
  Schedule,
} from './wire';
import type { BoxColor, Camera, CameraZone, DetectionBox, Stat, Tone } from '@/types';
import { assetUrl } from './http';

/* ---------- time ----------
 *
 *  Every instant is rendered in the SCHOOL's timezone, never the viewer's. A
 *  parent opening the app abroad must see the time the school experienced, so
 *  we shift by the offset the engine sent and then read UTC components. */

function siteLocal(instant: Instant): Date {
  return new Date(new Date(instant.utc).getTime() + instant.tzOffsetMinutes * 60_000);
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

/** "7:42am" */
export function formatTime(instant: Instant | null | undefined): string {
  if (!instant) return '—';
  const d = siteLocal(instant);
  const h = d.getUTCHours();
  const m = d.getUTCMinutes();
  const suffix = h < 12 ? 'am' : 'pm';
  const hour12 = h % 12 === 0 ? 12 : h % 12;
  return `${hour12}:${String(m).padStart(2, '0')}${suffix}`;
}

/** The current wall clock at the SCHOOL, as "07:42:11".
 *
 *  Used for the ticking timestamp on a live camera. Rendered from the site's
 *  offset rather than the viewer's, so an operator abroad sees the time the
 *  school is experiencing — the same rule as every other instant in the UI. */
export function siteClock(tzOffsetMinutes: number): string {
  const d = new Date(Date.now() + tzOffsetMinutes * 60_000);
  return [d.getUTCHours(), d.getUTCMinutes(), d.getUTCSeconds()]
    .map((n) => String(n).padStart(2, '0'))
    .join(':');
}

/** "07:42:11" — the timestamp burned into a camera tile. */
export function formatClock(instant: Instant | null | undefined): string | undefined {
  if (!instant) return undefined;
  const d = siteLocal(instant);
  return [d.getUTCHours(), d.getUTCMinutes(), d.getUTCSeconds()]
    .map((n) => String(n).padStart(2, '0'))
    .join(':');
}

function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getUTCFullYear() === b.getUTCFullYear() &&
    a.getUTCMonth() === b.getUTCMonth() &&
    a.getUTCDate() === b.getUTCDate()
  );
}

/** "Today, 6:12am" · "Yesterday, 7:20pm" · "Jul 26, 7:20pm" · "Feb 18, 2026 · 2:40pm"
 *
 *  Relative to the SCHOOL's today, computed from the offset the engine sent —
 *  the UI never decides what "today" means from its own clock. */
export function formatEventTime(instant: Instant | null | undefined): string {
  if (!instant) return '—';
  const d = siteLocal(instant);
  const now = new Date(Date.now() + instant.tzOffsetMinutes * 60_000);
  const time = formatTime(instant);

  if (isSameDay(d, now)) return `Today, ${time}`;

  const yesterday = new Date(now.getTime() - 86_400_000);
  if (isSameDay(d, yesterday)) return `Yesterday, ${time}`;

  const sameYear = d.getUTCFullYear() === now.getUTCFullYear();
  const date = `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;
  return sameYear ? `${date}, ${time}` : `${date}, ${d.getUTCFullYear()} · ${time}`;
}

/** "Wednesday, July 29, 2026" */
export function formatLongDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  const month = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
  ][d.getUTCMonth()];
  return `${DAYS[d.getUTCDay()]}, ${month} ${d.getUTCDate()}, ${d.getUTCFullYear()}`;
}

/** "Tue, Jul 28" */
export function formatShortDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return `${DAYS[d.getUTCDay()].slice(0, 3)}, ${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;
}

/** "7 seconds" · "2 minutes" · "7h 06m" */
export function formatDuration(seconds: number): string {
  if (seconds < 60) {
    const n = Math.round(seconds);
    return `${n} second${n === 1 ? '' : 's'}`;
  }
  if (seconds < 3600) {
    const n = Math.round(seconds / 60);
    return `${n} minute${n === 1 ? '' : 's'}`;
  }
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return `${h}h ${String(m).padStart(2, '0')}m`;
}

/* ---------- severity and tone ----------
 *
 *  The engine decides severity; the UI owns the palette. Thresholds stay
 *  server-side and auditable, and renaming a colour stays a front-end change. */

export function severityToTone(severity: Severity): Tone {
  switch (severity) {
    case 'critical':
      return 'bad';
    case 'warn':
      return 'warn';
    default:
      return 'good';
  }
}

export function severityToNeutralTone(severity: Severity): Tone {
  return severity === 'info' ? 'neutral' : severityToTone(severity);
}

/** Box colour encodes *how* something was identified, which the UI already
 *  relies on: green = face match, blue = appearance match, red = a threat. */
export function boxColor(box: WireBox): BoxColor {
  if (box.severity === 'critical') return 'red';
  if (box.match === 'face') return 'green';
  // A tracked body that a face has named is green too. The box is drawn
  // because clothing matched, so `match` stays APPEARANCE and would leave it
  // blue forever — but the Track page's own legend promises green for
  // "Identified by face", and a name on the box means exactly that.
  if (identifiedByFace(box.label)) return 'green';
  if (box.match === 'appearance') return 'blue';
  if (box.severity === 'warn') return 'amber';
  return 'blue';
}

/** Has a face put a name to this body, right now?
 *
 *  Read from the name, never from the match kind. `/tracking/live` reports
 *  APPEARANCE on every identity by design: the body is being followed because
 *  its clothing matched, and that stays true whether or not a face is readable
 *  in the frame. So `match === 'face'` is not a weaker version of this
 *  question, it is a different question whose answer never changes.
 *
 *  The name is the honest signal. The engine attaches a label only when a face
 *  was matched inside that body in that frame, and drops it again the moment
 *  the face turns away — which is exactly what "identified right now" means.
 *  A stored binding carried forward is the bug that once put one person's name
 *  on every body on the camera, so nothing here may outlive the frame.
 *
 *  "Unknown" is the placeholder the recogniser uses for a face it could not
 *  put a name to. It is not a name. */
export function identifiedByFace(name: string | null | undefined): boolean {
  return !!name && !name.startsWith('Unknown');
}

export function matchLabel(match: MatchKind, confidence: number): string {
  const pct = formatPercent(confidence);
  if (match === 'face') return `Face match · ${pct}`;
  if (match === 'appearance') return `Appearance match · ${pct}`;
  return pct;
}

/* ---------- numbers ---------- */

export const formatCount = (n: number): string => n.toLocaleString();

/** 0.936 -> "94%" */
export function formatPercent(ratio: number, digits = 0): string {
  return `${(ratio * 100).toFixed(digits)}%`;
}

export function formatMetric(metric: Metric): Stat {
  if (metric.text) return { label: metric.label, value: metric.text };
  if (metric.value === null || metric.value === undefined) {
    return { label: metric.label, value: '—' };
  }
  switch (metric.unit) {
    case 'percent':
      return { label: metric.label, value: formatPercent(metric.value) };
    case 'seconds':
      return { label: metric.label, value: formatDuration(metric.value) };
    case 'ratio':
      return { label: metric.label, value: metric.value.toFixed(2) };
    default:
      return {
        label: metric.label,
        value: metric.total
          ? `${formatCount(metric.value)}/${formatCount(metric.total)}`
          : formatCount(metric.value),
      };
  }
}

export const formatMetrics = (metrics: Metric[]): Stat[] => metrics.map(formatMetric);

/* ---------- attendance ---------- */

export function attendanceLabel(status: AttendanceStatus): string {
  switch (status) {
    case 'on_time':
      return 'On time';
    case 'late':
      return 'Late';
    case 'absent':
      return 'Absent';
    default:
      return 'Unknown';
  }
}

export function attendanceTone(status: AttendanceStatus): Tone {
  switch (status) {
    case 'on_time':
      return 'good';
    case 'late':
      return 'warn';
    case 'absent':
      return 'bad';
    default:
      return 'neutral';
  }
}

/** "On time · 7:42am" — the combined string the roster rows show. */
export function attendanceStatusLine(
  status: AttendanceStatus,
  seenAt: Instant | null | undefined,
): string {
  const label = attendanceLabel(status);
  return seenAt ? `${label} · ${formatTime(seenAt)}` : label;
}

/* ---------- zone schedules ---------- */

const DAY_NAMES: Record<string, string> = {
  mon: 'Monday', tue: 'Tuesday', wed: 'Wednesday', thu: 'Thursday',
  fri: 'Friday', sat: 'Saturday', sun: 'Sunday',
};
const WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri'];

function humanTime(hhmm: string): string {
  const [h, m] = hhmm.split(':').map(Number);
  const suffix = h < 12 ? 'am' : 'pm';
  const hour12 = h % 12 === 0 ? 12 : h % 12;
  return m === 0 ? `${hour12}${suffix}` : `${hour12}:${String(m).padStart(2, '0')}${suffix}`;
}

function humanDays(days: string[]): string {
  if (days.length === 0 || days.length === 7) return 'every day';
  const isWeekdays = days.length === 5 && WEEKDAYS.every((d) => days.includes(d));
  if (isWeekdays) return 'weekdays';
  if (days.length === 1) return `${DAY_NAMES[days[0]] ?? days[0]}s`;
  return days.map((d) => (DAY_NAMES[d] ?? d).slice(0, 3)).join(', ');
}

/** "Locked outside 8am–4pm, weekdays" — the sentence the zone list shows. */
export function formatSchedule(schedule: Schedule): string {
  if (schedule.mode === 'always') return 'Locked at all times';
  if (!schedule.start || !schedule.end) return 'Locked at all times';

  const window = `${humanTime(schedule.start)}–${humanTime(schedule.end)}`;
  const days = humanDays(schedule.days);
  return schedule.mode === 'outside'
    ? `Locked outside ${window}, ${days}`
    : `Locked during ${window}, ${days}`;
}

/* ---------- geometry ----------
 *
 *  The engine works in fractions of the frame; `@/types` is in percentages.
 *  One multiplication, in one place. */

export function toDetectionBox(box: WireBox): DetectionBox {
  const confidence =
    box.confidence !== null && box.confidence !== undefined
      ? formatPercent(box.confidence)
      : undefined;
  const label = box.label
    ? confidence
      ? `${box.label} ${confidence}`
      : box.label
    : confidence;

  return {
    x: box.x * 100,
    y: box.y * 100,
    w: box.w * 100,
    h: box.h * 100,
    color: boxColor(box),
    // With a track id the frame draws the id large and the name under it, so
    // the label carries the name alone. Without one, nothing changes.
    label: box.trackId ? (box.label ?? undefined) : label,
    trackId: box.trackId ?? undefined,
  };
}

/** Collapse a polygon to the bounding box the current renderer draws.
 *
 *  `CameraZone` is modelled as x/y/w/h even though real zones are rarely
 *  rectangles. The wire carries the true polygon; when the UI learns to draw
 *  one, only this function changes. */
export function toCameraZone(zone: ZoneOverlay): CameraZone {
  const xs = zone.polygon.map((p) => p.x);
  const ys = zone.polygon.map((p) => p.y);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  return {
    x: minX * 100,
    y: minY * 100,
    w: (Math.max(...xs) - minX) * 100,
    h: (Math.max(...ys) - minY) * 100,
    label: zone.label,
  };
}

/** Build the tile's one-line status.
 *
 *  Offline wins over everything — the UI must say NO SIGNAL rather than
 *  describe detections from a frame that may be minutes old. */
/** Turn a live headcount into the tile's status line.
 *
 *  `undefined` means the poll has not answered yet, `null` means nothing is
 *  measuring this camera. Both fall back to whatever the page already said,
 *  rather than inventing a zero — "0 people" and "nobody is counting" look
 *  identical on screen but mean very different things. */
export function describeCount(count: number | null | undefined, fallback: string): string {
  if (count === undefined || count === null) return fallback;
  if (count === 0) return 'Nobody in view';
  return count === 1 ? '1 person' : `${count} people`;
}

function cameraStatus(view: CameraView, fallback?: string): string {
  if (view.offline) return 'No signal';
  if (fallback) return fallback;
  // null means nothing has measured this camera recently — different from a
  // measured zero, and it must not be rendered as "0 people".
  if (view.peopleCount !== null && view.peopleCount !== undefined) {
    if (view.peopleCount === 0) return 'Nobody in view';
    return view.peopleCount === 1 ? '1 person' : `${view.peopleCount} people`;
  }
  return 'Live';
}

export function toCamera(view: CameraView, statusOverride?: string): Camera {
  return {
    id: view.id,
    name: view.name,
    area: view.area || undefined,
    status: cameraStatus(view, statusOverride),
    offline: view.offline || undefined,
    time: formatClock(view.capturedAt),
    boxes: view.boxes.map(toDetectionBox),
    zone: view.zone ? toCameraZone(view.zone) : undefined,
    countLine: view.countLine !== null && view.countLine !== undefined
      ? view.countLine * 100
      : undefined,
    snapshotUrl: assetUrl(view.snapshotUrl),
    streamUrl: assetUrl(view.streamUrl),
  };
}

export const toCameras = (views: CameraView[]): Camera[] => views.map((v) => toCamera(v));

/** Snapshot URL for a tile, absolute so an <img> can use it directly. */
export const cameraSnapshot = (view: CameraView): string | undefined =>
  assetUrl(view.snapshotUrl);
