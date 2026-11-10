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

import { translate, type Language, type MessageKey } from '@/i18n';
import type {
  AttendanceStatus,
  Box as WireBox,
  CameraView,
  GateAlert as WireGateAlert,
  Instant,
  Metric,
  Severity,
  ZoneOverlay,
  Schedule,
  Station as WireStation,
  StationDetail as WireStationDetail,
  StationEvent as WireStationEvent,
  TimelineSegment as WireTimelineSegment,
  WatchedHours as WireWatchedHours,
  Zone as WireZone,
} from './wire';
import type {
  BoxColor, Camera, CameraZone, CapacityRowItem, DetectionBox, PopulationLevel, Stat, Tone,
  StationCard, StationLogEvent, StationState, TimelineBar, WatchedHours, WorkerLoadItem,
  ZoneCard, ZoneStatus,
} from '@/types';
import { assetUrl } from './http';

/* ---------- time ----------
 *
 *  Every instant is rendered in the SCHOOL's timezone, never the viewer's. A
 *  parent opening the app abroad must see the time the school experienced, so
 *  we shift by the offset the engine sent and then read UTC components. */

function siteLocal(instant: Instant): Date {
  return new Date(new Date(instant.utc).getTime() + instant.tzOffsetMinutes * 60_000);
}

/** The CLDR locale for a language.
 *
 *  `ar-EG` rather than plain `ar`: month names, the week's first day and the
 *  order of a date differ across the Arabic-speaking world, and this product
 *  is deployed in Egypt. `-u-nu-latn` pins Western digits for now - the site
 *  setting that chooses Arabic-Indic (`-u-nu-arab`) is `SiteInfo.digits`,
 *  which the engine does not send yet. Pinning it is deliberate: without it
 *  the digits follow the browser, so two people at the same gate could read
 *  the same plate width differently. */
function locale(lang: Language): string {
  return lang === 'ar' ? 'ar-EG-u-nu-latn' : 'en-GB';
}

/** Every formatter reads a wall clock that `siteLocal` has already shifted,
 *  so the timezone here is always UTC. See the note at the top of this file. */
const UTC = { timeZone: 'UTC' } as const;

const fmtCache = new Map<string, Intl.DateTimeFormat>();

function dateFormat(lang: Language, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  // A DateTimeFormat costs about a millisecond to build and these run on
  // every row of every table, several times a second on a live page.
  const key = lang + JSON.stringify(options);
  let f = fmtCache.get(key);
  if (!f) {
    f = new Intl.DateTimeFormat(locale(lang), { ...options, ...UTC });
    fmtCache.set(key, f);
  }
  return f;
}

/** "7:42 am" · "٧:٤٢ ص" */
export function formatTime(instant: Instant | null | undefined, lang: Language): string {
  if (!instant) return '—';
  return dateFormat(lang, { hour: 'numeric', minute: '2-digit' })
    .format(siteLocal(instant));
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
export function formatEventTime(
  instant: Instant | null | undefined,
  lang: Language,
): string {
  if (!instant) return '—';
  const d = siteLocal(instant);
  const now = new Date(Date.now() + instant.tzOffsetMinutes * 60_000);
  const time = formatTime(instant, lang);

  // "Today" and "Yesterday" are words, so they come from the catalogue. The
  // comma between them and the time is punctuation English puts there and
  // Arabic does not, which is why the whole shape is one parameterised key.
  if (isSameDay(d, now)) return translate(lang, 'time.today', { time });

  const yesterday = new Date(now.getTime() - 86_400_000);
  if (isSameDay(d, yesterday)) return translate(lang, 'time.yesterday', { time });

  const sameYear = d.getUTCFullYear() === now.getUTCFullYear();
  const date = dateFormat(lang, sameYear
    ? { day: 'numeric', month: 'short' }
    : { day: 'numeric', month: 'short', year: 'numeric' }).format(d);
  return translate(lang, 'time.dateAndTime', { date, time });
}

/** "Wednesday, 29 July 2026" · "الأربعاء، ٢٩ يوليو ٢٠٢٦" */
/** A dated day — "1 Sep 2025" — in the reader's convention.
 *
 *  Distinct from `formatShortDate`, which is "Tue, 28 Jul" and carries no
 *  year: a term runs across two of them, so the year is the load-bearing
 *  part. Locale-aware like every other formatter here — this was once
 *  `toLocaleDateString('en-US', …)` on Settings, which showed an Arabic
 *  reader an American date and an English one a format used nowhere else in
 *  the console. */
export function formatDayMonthYear(iso: string, lang: Language): string {
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return dateFormat(lang, {
    day: 'numeric', month: 'short', year: 'numeric',
  }).format(d);
}

export function formatLongDate(iso: string, lang: Language): string {
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return dateFormat(lang, {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
  }).format(d);
}

/** "Tue, 28 Jul" */
export function formatShortDate(iso: string, lang: Language): string {
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return dateFormat(lang, { weekday: 'short', day: 'numeric', month: 'short' }).format(d);
}

/** "7 seconds" · "2 minutes" · "7h 06m"
 *
 *  The plural is the catalogue's problem, not a trailing `s`. English has two
 *  forms and Arabic has more, and which one applies is a property of the
 *  language rather than of this function. */
export function formatDuration(seconds: number, lang: Language): string {
  if (seconds < 60) {
    const n = Math.round(seconds);
    return translate(lang, n === 1 ? 'time.oneSecond' : 'time.seconds', { n });
  }
  if (seconds < 3600) {
    const n = Math.round(seconds / 60);
    return translate(lang, n === 1 ? 'time.oneMinute' : 'time.minutes', { n });
  }
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return translate(lang, 'time.hoursMinutes', { h, m: String(m).padStart(2, '0') });
}

/* ---------- population level ----------
 *
 *  Computed here, from the count and the capacity somebody set, so the engine
 *  stays free of wording. With no capacity there is nothing to compare with,
 *  and the answer is null: no level, no percentage. The thresholds are the
 *  engine's own 0.7 and 0.9 for the warn and critical severities. */

export function populationLevel(count: number, capacity: number | null | undefined): PopulationLevel | null {
  if (!capacity || capacity <= 0) return null;
  if (count <= 0) return 'empty';
  const share = count / capacity;
  if (share < 0.7) return 'quiet';
  if (share < 0.9) return 'busy';
  if (share <= 1) return 'near';
  return 'over';
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
  // A plate is coloured by the REGISTER, never by recognition. It is above
  // the face branch because `identifiedByFace` reads the label, and a plate's
  // label is a plate - letting it fall through would paint a car green for
  // looking like a name.
  if (box.kind === 'plate') return box.severity === 'warn' ? 'amber' : 'green';
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

/* `matchLabel` lived here and nothing called it. Removed rather than
   translated: a wording no page renders is a wording nobody reviews. The
   track page says the same thing through `track.identifiedByFace` and its
   siblings, which are reachable and therefore checkable. */

/* ---------- numbers ---------- */

/** A number with its thousands separators, in the reader's convention.
 *
 *  This called `toLocaleString()` with no locale, so it silently followed the
 *  browser: the same figure could read `1,240` on one machine and `1.240` on
 *  the next, in a console two people compare notes over. */
export const formatCount = (n: number, lang: Language): string =>
  new Intl.NumberFormat(locale(lang)).format(n);

/** 0.936 -> "94%" */
export function formatPercent(ratio: number, lang: Language, digits = 0): string {
  return new Intl.NumberFormat(locale(lang), {
    style: 'percent', minimumFractionDigits: digits, maximumFractionDigits: digits,
  }).format(ratio);
}

export function formatMetric(metric: Metric, lang: Language): Stat {
  if (metric.text) return { label: metric.label, value: metric.text };
  if (metric.value === null || metric.value === undefined) {
    return { label: metric.label, value: '—' };
  }
  switch (metric.unit) {
    case 'percent':
      return { label: metric.label, value: formatPercent(metric.value, lang) };
    case 'seconds':
      return { label: metric.label, value: formatDuration(metric.value, lang) };
    case 'ratio':
      return { label: metric.label, value: metric.value.toFixed(2) };
    default:
      return {
        label: metric.label,
        value: metric.total
          ? `${formatCount(metric.value, lang)}/${formatCount(metric.total, lang)}`
          : formatCount(metric.value, lang),
      };
  }
}

export const formatMetrics = (metrics: Metric[], lang: Language): Stat[] =>
  metrics.map((m) => formatMetric(m, lang));

/* ---------- attendance ---------- */




/** What a category means on a register row. */
/* `vehicleCategoryLabel` lived here and returned English. It has gone: the
   register now reads `vehicle.category.*` from the catalogue, which is the
   only way an Arabic label can exist. `vehicleCategoryTone` stays — a tone
   is not wording. */

export function vehicleCategoryTone(category: string): Tone {
  switch (category) {
    case 'staff': return 'good';
    case 'visitor': return 'warn';
    case 'blacklist': return 'bad';
    default: return 'neutral';
  }
}

export function attendanceLabel(status: AttendanceStatus, lang: Language): string {
  // The language is a parameter, not a module-level "current" value. This
  // file is not a component and has to stay testable on its own, and a
  // hidden global would misbehave under React's double render.
  const known = status === 'on_time' || status === 'late' || status === 'absent';
  return translate(lang, known
    ? (`attendance.status.${status}` as MessageKey)
    : 'attendance.status.unknown');
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
  lang: Language,
): string {
  const label = attendanceLabel(status, lang);
  return seenAt
    ? translate(lang, 'attendance.statusLine',
      { status: label, time: formatTime(seenAt, lang) })
    : label;
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
      // Deliberately not the reader's locale. This number is drawn on the
      // camera picture, and that whole container is pinned `dir="ltr"` so an
      // overlay can never mirror off the thing it describes. Latin digits are
      // what belongs inside it.
      ? formatPercent(box.confidence, 'en')
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
    plateWidthPx: box.plateWidthPx ?? undefined,
  };
}

/** Below this a plate still reads, with less confidence in the result.
 *
 *  Not a threshold and not a rejection: nothing is discarded for being small,
 *  and width only changes the weight of that frame's vote. It is an aiming
 *  aid — the one accuracy problem no amount of software fixes is a camera
 *  that is too far away, and this is how an operator sees that for
 *  themselves rather than being told the software is broken. */
export const COMFORTABLE_PLATE_PX = 100;

/** "Registered" · "Not registered" · "Blacklisted" · "Permit expired" */
export function plateStatusLabel(status: string): string {
  if (status === 'known') return 'Registered';
  if (status === 'blacklist') return 'Blacklisted';
  if (status === 'expired') return 'Permit expired';
  return 'Not registered';
}

export function plateStatusTone(status: string): Tone {
  if (status === 'known') return 'good';
  if (status === 'blacklist') return 'bad';
  return 'warn';
}

/** Which way the camera watching this gate is pointed. */
export function directionLabel(direction: string): string {
  return direction === 'exit' ? 'Out' : 'In';
}

/** An Egyptian plate in Latin letters: "ب ج د ١٢٣٤" -> "B G D 1234".
 *
 *  For the register table, where the guard reads Arabic but an exported
 *  report or a Latin keyboard search may not.
 *
 *  **The source of truth is `vg/platetext.py::TRANSLIT`** and this must track
 *  it. It is duplicated here rather than sent per row because `format.ts`
 *  owns rendered strings — a `latin` field on every wire type would be the
 *  engine writing display text for one screen. If the two ever disagree, the
 *  Python is right. */
const TRANSLIT: Record<string, string> = {
  'ا': 'A', 'ب': 'B', 'ج': 'G', 'د': 'D', 'ر': 'R', 'س': 'S',
  'ص': 'C', 'ط': 'T', 'ع': 'E', 'ف': 'F', 'ق': 'K', 'ل': 'L',
  'م': 'M', 'ن': 'N', 'ه': 'H', 'و': 'W', 'ى': 'Y', 'ي': 'Y',
  'ك': 'K', 'ح': 'H', 'ز': 'Z', 'ت': 'T', 'ث': 'S', 'ش': 'S',
  'خ': 'KH', 'ذ': 'Z', 'ض': 'D', 'ظ': 'Z', 'غ': 'GH',
  '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4',
  '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9',
};

export function plateLatin(display: string): string {
  if (!display) return '';
  return [...display].map((ch) => TRANSLIT[ch] ?? ch).join('');
}

/* ---------- gate alerts ----------
 *
 *  The engine sends facts and this file writes the sentences, which is the
 *  standing rule here — but on these three it is load-bearing rather than
 *  tidy, because each sentence has a claim in it that must not be overstated.
 */

/** What an alert says, and what it must not say.
 *
 *  - **Blacklist** states plainly that nothing was stopped. The software has
 *    no barrier to close, and an alert that merely shouted would let a reader
 *    assume the car was held.
 *  - **Unknown** is a question when there is a near match, never a statement.
 *    One misread letter turns a colleague into a stranger, and the engine has
 *    already refused to guess between two candidates — this must not undo
 *    that by phrasing the one candidate as a fact.
 *  - **Expired** is a lapsed permit, which is an administrative matter, not a
 *    security one. It gets no alarming language. */
export function alertMessage(alert: WireGateAlert, lang: Language): string {
  const plate = alert.plateDisplay;
  const where = alert.gateName;

  if (alert.kind === 'blacklist') {
    const who = alert.owner ? ` (${alert.owner})` : '';
    const still = alert.inside ? ' and is still inside' : '';
    return `Blacklisted car ${plate}${who} came in at ${where}${still}. `
      + 'Nothing was stopped — the software has no barrier to close.';
  }

  if (alert.kind === 'expired') {
    const who = alert.owner ?? 'This vehicle';
    const when = alert.permitExpiredOn
      ? ` ran out on ${formatShortDate(alert.permitExpiredOn, lang)}`
      : ' has expired';
    const still = alert.inside ? ' The car is inside now.' : '';
    return `${who}’s permit${when}. ${plate} passed ${where}.${still}`;
  }

  const guess = alert.nearMatchDisplay
    ? ` — maybe ${alert.nearMatchDisplay}`
      + `${alert.nearMatchOwner ? ` (${alert.nearMatchOwner})` : ''}?`
      + ' One misread letter turns a colleague into a stranger.'
    : '';
  return `Unregistered car ${plate} at ${where}${guess}`;
}

/** The label on the button that clears an alert without acting on it. */
export function alertDismissLabel(kind: WireGateAlert['kind']): string {
  if (kind === 'blacklist') return 'I have dealt with it';
  if (kind === 'expired') return 'Leave it expired';
  return 'Just a one-off';
}

/** The action that resolves this alert, or null where the software has none.
 *
 *  **Blacklist deliberately has no action.** There is nothing the console can
 *  do about a car that has already driven in, and a button that pretended
 *  otherwise would be the dead control the constitution forbids. */
export function alertAction(kind: WireGateAlert['kind']): string | null {
  if (kind === 'unknown') return 'Add to the register';
  if (kind === 'expired') return 'Renew the permit';
  return null;
}

export function alertTone(kind: WireGateAlert['kind']): Tone {
  return kind === 'blacklist' ? 'bad' : 'warn';
}

/** How much work one feature worker has done, and how long its last frame took.
 *
 *  Both are real counters off the worker rather than a sampled rate, so the
 *  number on screen can be checked against the engine. */
export function formatWorkerThroughput(w: WorkerLoadItem, lang: Language): string {
  return translate(lang, 'health.workerThroughput', {
    frames: formatCount(w.framesProcessed, lang),
    ms: formatCount(Math.round(w.lastInferenceMs), lang),
  });
}

/** How deep this worker's queue is, and what the bus threw away while it was busy.
 *
 *  Dropped frames are the honest half. A queue that is merely full is a worker
 *  mid-frame; drops are what say it did not catch up, which is why both
 *  numbers are shown rather than one derived verdict. */
export function formatWorkerQueue(w: WorkerLoadItem, lang: Language): string {
  return translate(lang, 'health.workerQueue', {
    depth: formatCount(w.queueDepth, lang),
    max: formatCount(w.queueMax, lang),
    dropped: formatCount(w.framesDropped, lang),
  });
}

/** What share of one budget a projected cost is, 0-100.
 *
 *  Clamped at the top, because a machine can be asked for more than it has —
 *  that is the whole point of showing this — and a bar drawn past its own end
 *  is a rendering bug rather than a louder warning. The number beside it is
 *  not clamped, so 1,400 of 1,000 still reads as 1,400. */
export function capacityShare(usedMs: number, budgetMs: number): number {
  if (budgetMs <= 0) return 0;
  return Math.min(100, Math.round((usedMs / budgetMs) * 100));
}

/** How to colour one budget. The engine sets no threshold for this, so the
 *  two here are the console's own and deliberately conservative: amber from
 *  three-quarters, red at full. A machine at 100% is not "nearly fine". */
export function capacityTone(usedMs: number, budgetMs: number): 'good' | 'warn' | 'bad' {
  const share = budgetMs > 0 ? usedMs / budgetMs : 0;
  if (share >= 1) return 'bad';
  return share >= 0.75 ? 'warn' : 'good';
}

/** What this engine's own workers spent on one pool, per second, as a sentence.
 *
 *  The processor row carries a percentage and the graphics row does not, and
 *  that asymmetry is the whole point of this function. `busyMsPerSecond` is
 *  wall clock inside `analyse()` — letterboxing, NMS and whatever Python did
 *  around them, all included. On the processor that IS processor time and
 *  `cores x 1000` is the budget it comes out of, so a share is a fair claim.
 *
 *  On the graphics card it is not card time: it counts preparing the frame and
 *  reading the result back as well. Dividing it by the card's 1,000 ms and
 *  printing the result said "measured" over a number nothing had measured, and
 *  it ran ahead of the driver's own figure on the bar directly above it. The
 *  card's share is the bar; this line is only ever milliseconds. */
export function formatEngineBusy(
  pool: 'gpu' | 'cpu',
  busyMsPerSecond: number,
  budgetMs: number,
  lang: Language,
): string {
  const ms = formatCount(Math.round(busyMsPerSecond), lang);
  if (pool === 'gpu') return translate(lang, 'health.capacityEngineBusy', { ms });
  return translate(lang, 'health.capacityEngineShare', {
    ms,
    percent: formatCount(capacityShare(busyMsPerSecond, budgetMs), lang),
  });
}

/** One capacity row's MEASURED figures, as a sentence.
 *
 *  Frames actually analysed per second over the window, and what one of
 *  them last cost — the reading, not the configured rate.
 *
 *  The plural is the catalogue's problem, not a trailing `s`. With one
 *  camera every row of the card read "1 cameras" — and on a single-camera
 *  site every row is every row there is. */
export function formatCapacityRow(row: CapacityRowItem, lang: Language): string {
  const key = row.cameras === 1 ? 'health.capacityRowOne' : 'health.capacityRow';
  return translate(lang, key, {
    cameras: formatCount(row.cameras, lang),
    hz: row.analysedPerSecond.toFixed(1),
    ms: formatCount(Math.round(row.msPerFrame), lang),
  });
}

/** What the configuration asks of a row, as a sentence — the projection. */
export function formatCapacityAsks(row: CapacityRowItem, lang: Language): string {
  return translate(lang, 'health.capacityAsks', {
    hz: formatCount(row.framesPerSecond ?? 0, lang),
    ms: formatCount(Math.round(row.msPerSecond ?? 0), lang),
  });
}

/** What colour to draw a plate's pixel width in.
 *
 *  Two outcomes, never four: a width is comfortable or it is not. Returning
 *  the whole `BoxColor` union would invite a caller to handle a red that
 *  cannot happen — and red on this number would say "rejected", which is
 *  exactly what a small plate is not. */
export function plateWidthTone(widthPx: number): 'green' | 'amber' {
  return widthPx >= COMFORTABLE_PLATE_PX ? 'green' : 'amber';
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
export function describeCount(
  count: number | null | undefined,
  fallback: string,
  lang: Language,
): string {
  if (count === undefined || count === null) return fallback;
  if (count === 0) return translate(lang, 'camera.nobodyInView');
  return count === 1
    ? translate(lang, 'camera.onePerson')
    : translate(lang, 'camera.people', { count });
}

function cameraStatus(view: CameraView, lang: Language, fallback?: string): string {
  if (view.offline) return translate(lang, 'camera.noSignal');
  if (fallback) return fallback;
  // null means nothing has measured this camera recently — different from a
  // measured zero, and it must not be rendered as "0 people".
  if (view.peopleCount !== null && view.peopleCount !== undefined) {
    return describeCount(view.peopleCount, '', lang);
  }
  return translate(lang, 'camera.live');
}

export function toCamera(
  view: CameraView,
  lang: Language,
  statusOverride?: string,
): Camera {
  return {
    id: view.id,
    name: view.name,
    area: view.area || undefined,
    status: cameraStatus(view, lang, statusOverride),
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

export const toCameras = (views: CameraView[], lang: Language): Camera[] =>
  views.map((v) => toCamera(v, lang));

/** Snapshot URL for a tile, absolute so an <img> can use it directly. */
export const cameraSnapshot = (view: CameraView): string | undefined =>
  assetUrl(view.snapshotUrl);


/* ---------- zones and stations (spec 025) ----------
 *
 *  The engine sends a status or a state and numbers; every sentence is built
 *  here. A status is never defaulted: a zone the engine could not read is not
 *  a clear one. */

/** Colour of a zone's status. Red only for somebody inside right now. */
export function zoneStatusTone(status: ZoneStatus): Tone {
  switch (status) {
    case 'personInZone':
      return 'bad';
    case 'clear':
      return 'good';
    case 'cameraOffline':
    case 'detectorStopped':
      return 'warn';
    default:
      return 'neutral';
  }
}

export function zoneStatusLabel(status: ZoneStatus, lang: Language): string {
  return translate(lang, `zones.status.${status}` as MessageKey);
}

/** Colour of a station's state. Absent is the only red. */
export function stationStateTone(state: StationState): Tone {
  switch (state) {
    case 'on':
      return 'good';
    case 'away':
    case 'unknown':
      return 'warn';
    case 'absent':
      return 'bad';
    default:
      return 'neutral';
  }
}

export function stationStateLabel(state: StationState, lang: Language): string {
  return translate(lang, `stations.state.${state}` as MessageKey);
}

/** "under a minute" · "12 min" · "1h 20m". Short enough for a tile. */
export function formatDurationShort(seconds: number, lang: Language): string {
  if (seconds < 60) return translate(lang, 'time.underMinute');
  if (seconds < 3600) {
    return translate(lang, 'time.minutesShort', { n: Math.round(seconds / 60) });
  }
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return translate(lang, 'time.hoursMinutes', { h, m: String(m).padStart(2, '0') });
}

function toWatched(w: WireWatchedHours | null | undefined): WatchedHours {
  return {
    mode: w?.mode ?? 'always',
    from: w?.from ?? undefined,
    to: w?.to ?? undefined,
  };
}

/** "Always" · "Outside working hours" · "16:00 to 08:00". */
export function formatWatched(watched: WatchedHours, lang: Language): string {
  if (watched.mode === 'custom') {
    return translate(lang, 'area.hours.customRange', {
      from: watched.from ?? '--:--', to: watched.to ?? '--:--',
    });
  }
  return translate(lang, `area.hours.${watched.mode}` as MessageKey);
}

export function toZoneCard(z: WireZone, lang: Language): ZoneCard {
  return {
    id: z.id,
    name: z.name,
    enabled: z.enabled,
    detectionsToday: z.breachesToday,
    cameraId: z.cameraId,
    polygon: z.polygon.map((p) => ({ x: p.x, y: p.y })),
    // Never "clear" when the engine did not say: an older engine that omits
    // the status is one that cannot tell us anything about the room.
    status: z.status ?? (z.enabled ? 'detectorStopped' : 'paused'),
    inZoneNow: z.inZoneNow ?? null,
    watched: toWatched(z.watched),
    alertAfterSeconds: z.alertAfterSeconds ?? 0,
    notifyInApp: z.notifyInApp ?? true,
    notifyEmail: z.notifyEmail ?? false,
    pausedBy: z.pausedBy ?? undefined,
    pausedAt: z.pausedAt ? formatEventTime(z.pausedAt, lang) : undefined,
    importNote: z.importNote ?? undefined,
    deleted: !!z.deletedAt,
  };
}

/** Segments of one day's timeline as fractions of the day's watched span, so
 *  the picture is drawn left to right whatever the language. */
export function timelineSegments(segments: WireTimelineSegment[], lang: Language): TimelineBar[] {
  if (segments.length === 0) return [];
  const at = (i: Instant) => new Date(i.utc).getTime();
  const start = Math.min(...segments.map((s) => at(s.from)));
  const end = Math.max(...segments.map((s) => at(s.to)));
  const span = end - start;
  if (span <= 0) return [];
  return segments.map((s) => ({
    state: s.state,
    start: (at(s.from) - start) / span,
    width: (at(s.to) - at(s.from)) / span,
    from: formatTime(s.from, lang),
    to: formatTime(s.to, lang),
  }));
}

export function toStationEvent(e: WireStationEvent, lang: Language): StationLogEvent {
  return {
    id: e.id,
    kind: e.kind,
    time: formatTime(e.at, lang),
    limitMinutes: e.limitMinutes ?? undefined,
    byWho: e.byWho ?? undefined,
  };
}

/** One line of a station's log, built from the kind and its facts. */
export function stationEventLine(e: StationLogEvent, lang: Language): string {
  return translate(lang, `stations.event.${e.kind}` as MessageKey, {
    minutes: e.limitMinutes ?? 0,
    who: e.byWho ?? '',
  });
}

export function toStationCard(
  s: WireStation | WireStationDetail,
  lang: Language,
): StationCard {
  const events = 'events' in s ? s.events.map((e) => toStationEvent(e, lang)) : [];
  return {
    id: s.id,
    name: s.name,
    cameraId: s.cameraId,
    cameraName: s.cameraName,
    polygon: s.polygon.map((p) => ({ x: p.x, y: p.y })),
    watched: toWatched(s.watched),
    assigneeId: s.assigneeId ?? undefined,
    assigneeName: s.assigneeName ?? undefined,
    assigneeMissing: s.assigneeMissing,
    limitMinutes: s.limitMinutes,
    notifyInApp: s.notifyInApp,
    notifyEmail: s.notifyEmail,
    faceCheck: s.faceCheck,
    facePx: s.facePx ?? undefined,
    state: s.state,
    since: s.stateSince ? formatTime(s.stateSince, lang) : undefined,
    unknownReason: s.unknownReason ?? undefined,
    presentNotRecognised: s.presentNotRecognised,
    opensAt: s.opensAt ?? undefined,
    workSeconds: s.workSeconds,
    absentSeconds: s.absentSeconds,
    notWatchedSeconds: s.notWatchedSeconds,
    rate: s.rate,
    timeline: timelineSegments(s.timeline, lang),
    alertEventId: s.unacknowledgedAlert?.eventId,
    deleted: !!s.deletedAt,
    events,
  };
}
