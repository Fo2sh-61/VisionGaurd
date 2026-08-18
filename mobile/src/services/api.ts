/** The one place the mobile UI talks to "the system" — same seam as the web
 *  console's services/api.ts. Everything here resolves from fixtures today;
 *  wiring the real backend means replacing these bodies, not the screens. */

import type {
  AnswerRow,
  Camera,
  DirectoryPerson,
  FoundDevice,
  GroupMember,
  GroupSummary,
  MapArea,
  MapZone,
  PersonHistory,
  SystemSummary,
  ToolAnswer,
  ToolId,
} from '@/types';
import {
  AREA_OPTIONS,
  CAMERA_ONLINE,
  CAMERA_SOURCES,
  CAMERA_TOTAL,
  GROUP_SUMMARIES,
  PEOPLE_DIRECTORY,
  getGroupRoster,
  getGroupSummary,
  getPersonHistory,
} from './mockData';

const delay = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

const AREAS = [
  { name: 'Main entrance', cap: 120, x: 2, y: 64, w: 24, h: 32, f: 0.71 },
  { name: 'Cafeteria', cap: 400, x: 28, y: 56, w: 33, h: 40, f: 0.93 },
  { name: 'Assembly hall', cap: 600, x: 63, y: 52, w: 35, h: 44, f: 0.34 },
  { name: 'Library', cap: 150, x: 2, y: 4, w: 30, h: 52, f: 0.52 },
  { name: 'Classrooms', cap: 900, x: 34, y: 4, w: 36, h: 46, f: 0.78 },
  { name: 'Playground', cap: 800, x: 72, y: 4, w: 26, h: 42, f: 0.41 },
];

function areaCounts() {
  return AREAS.map((a) => ({ ...a, value: Math.max(1, Math.round(a.cap * Math.min(0.99, Math.max(0.06, a.f + (Math.random() - 0.5) * 0.08)))) }));
}

function toneFor(pct: number): 'good' | 'warn' | 'bad' {
  if (pct > 85) return 'bad';
  if (pct > 60) return 'warn';
  return 'good';
}

/** Runs a tool with the given field values and returns the unified answer
 *  the design's mobile "Tool" screen renders. */
export async function runTool(id: ToolId, values: Record<string, string>): Promise<ToolAnswer> {
  if (id === 'lost') await delay(1600);
  else await delay(280);

  if (id === 'attend') {
    const group = values.group ?? 'All students';
    const isStaff = group === 'All staff';
    const isGrade = group.startsWith('Grade');
    const total = isStaff ? 168 : isGrade ? 142 : 1742;
    const absent = isStaff ? 4 : isGrade ? 9 : 63;
    const late = isStaff ? 2 : isGrade ? 6 : 41;
    const rows: AnswerRow[] = [
      { name: 'Karim Adel', sub: 'No arrival recorded', badge: '✕ Absent', tone: 'bad' },
      { name: 'Hana Saleh', sub: 'No arrival recorded', badge: '✕ Absent', tone: 'bad' },
      { name: 'Omar Khaled', sub: 'Main entrance · 8:14am', badge: '! Late', tone: 'warn' },
      { name: 'Salma Reda', sub: 'Gate 3 · 8:22am', badge: '! Late', tone: 'warn' },
      { name: 'Layla Ahmed', sub: 'Main entrance · 7:42am', badge: '✓ On time', tone: 'good' },
    ];
    return {
      heading: `${(total - absent).toLocaleString()} of ${total.toLocaleString()} arrived`,
      sub: `${group} · Wednesday, July 29, 2026`,
      stats: [
        { label: 'Present', value: `${Math.round(((total - absent) / total) * 100)}%` },
        { label: 'Absent', value: String(absent) },
        { label: 'Late', value: String(late) },
        { label: 'Last entry', value: '8:31' },
      ],
      rowsTitle: 'Needs follow-up',
      rows,
      cameras: [
        { id: 'a1', name: 'Main entrance', status: 'Recognising · 2 people', time: '07:42:11', boxes: [{ x: 18, y: 26, w: 20, h: 44, color: 'green', label: 'Layla A. 96%' }, { x: 52, y: 31, w: 19, h: 41, color: 'green', label: 'Nour H. 94%' }] },
        { id: 'a2', name: 'Gate 5 — bus lane', status: 'Unknown face — not enrolled', time: '07:42:11', boxes: [{ x: 40, y: 27, w: 20, h: 44, color: 'red', label: 'Unknown' }] },
      ],
    };
  }

  if (id === 'count') {
    const place = values.place ?? 'Cafeteria';
    const when = values.when ?? 'Right now';
    const areas = areaCounts();
    const hit = areas.find((a) => a.name === place);
    const cap = hit ? hit.cap : areas.reduce((s, a) => s + a.cap, 0);
    const now = hit ? hit.value : areas.reduce((s, a) => s + a.value, 0);
    const pct = Math.round((now / cap) * 100);

    let bars;
    if (when !== 'Right now') {
      const labels = when === 'Today by hour' ? ['7am', '8am', '9am', '10am', '11am', '12pm'] : ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'];
      const values2 = labels.map(() => Math.round(cap * (0.25 + Math.random() * 0.7)));
      const max = Math.max(...values2);
      bars = labels.map((label, i) => ({ label, value: String(values2[i]), pct: Math.round((values2[i] / max) * 100) }));
    }

    const map: MapZone[] = areas.map((a) => ({
      name: String(a.value),
      label: a.name,
      value: String(a.value),
      x: a.x,
      y: a.y,
      w: a.w,
      h: a.h,
      tone: toneFor(Math.round((a.value / a.cap) * 100)),
    }));
    const areaRows: MapArea[] = areas.map((a) => ({
      name: a.name,
      value: String(a.value),
      pct: Math.round((a.value / a.cap) * 100),
      tone: toneFor(Math.round((a.value / a.cap) * 100)),
    }));

    const n1 = Math.round(now * 0.4);
    const n2 = Math.round(now * 0.35);

    return {
      heading: `${now} people in the ${place.toLowerCase()}`,
      sub: `${pct}% of safe capacity (${cap}) · updated seconds ago`,
      stats: [
        { label: 'Right now', value: String(now) },
        { label: 'Peak today', value: String(Math.round(cap * 0.94)) },
      ],
      barsTitle: when,
      bars,
      hasMap: true,
      map,
      areas: areaRows,
      cameras: [
        { id: 'c1', name: `${place} — cam 1`, status: `Counting · ${n1} tracked`, countLine: 58, boxes: [{ x: 14, y: 30, w: 16, h: 38, color: 'blue', label: '1' }, { x: 44, y: 34, w: 16, h: 36, color: 'blue', label: '2' }, { x: 70, y: 28, w: 16, h: 40, color: 'blue', label: '3' }] },
        { id: 'c2', name: `${place} — cam 2`, status: `Counting · ${n2} tracked`, countLine: 54, boxes: [{ x: 26, y: 32, w: 17, h: 38, color: 'blue', label: '4' }, { x: 58, y: 36, w: 16, h: 35, color: 'blue', label: '5' }] },
      ],
    };
  }

  if (id === 'lost') {
    const item = values.item ?? 'Backpack';
    const colour = values.colour ?? 'Black';
    const area = values.area ?? 'Anywhere';
    const since = values.since ?? 'Today';
    const label = `${colour === 'Any' ? '' : `${colour.toLowerCase()} `}${item.toLowerCase()}`;
    return {
      heading: '3 possible matches',
      sub: `A ${label} · ${area.toLowerCase()} · ${since.toLowerCase()}`,
      stats: [],
      rowsTitle: 'Best matches first',
      rows: [
        { name: 'Cafeteria — table row 3', sub: '12:41pm · left on a table', badge: '94%', tone: 'good' },
        { name: 'Cafeteria — exit corridor', sub: '12:38pm · carried by a student', badge: '88%', tone: 'good' },
        { name: 'Library — study area', sub: '11:20am · similar item on a chair', badge: '71%', tone: 'warn' },
      ],
      foot: 'If none look right, widen the area or time range and search again.',
      cameras: [
        { id: 'l1', name: 'Cafeteria — table row 3', status: '94% match · 12:41pm', time: '12:41:02', boxes: [{ x: 38, y: 56, w: 16, h: 20, color: 'green', label: `${label} 94%` }] },
        { id: 'l2', name: 'Library — study area', status: '71% match · 11:20am', time: '11:20:15', boxes: [{ x: 58, y: 52, w: 15, h: 19, color: 'amber', label: '71%' }] },
      ],
    };
  }

  if (id === 'track') {
    const who = values.who ?? 'Layla Ahmed';
    const firstName = who.split(' ')[0];
    return {
      heading: `${who} · 6 sightings`,
      sub: 'Wednesday, July 29, 2026 · 7:00 to 15:00',
      logged: true,
      stats: [
        { label: 'On campus', value: '7h 06m' },
        { label: 'Cameras seen on', value: '6' },
      ],
      path: [
        { time: '7:42am', place: 'Main entrance', detail: 'Entered campus · identified by face' },
        { time: '7:51am', place: 'Bldg A — Corridor 1', detail: 'Walking towards classrooms' },
        { time: '10:05am', place: 'Bldg A — Corridor 3', detail: 'Break period movement' },
        { time: '12:34pm', place: 'Cafeteria', detail: 'Lunch · stayed 26 minutes' },
        { time: '1:02pm', place: 'Playground — north', detail: 'Outdoor break' },
        { time: '2:48pm', place: 'Main entrance', detail: 'Left campus' },
      ],
      cameras: [
        { id: 't1', name: '7:42am — Main entrance', status: 'Face match · 96%', time: '07:42:11', boxes: [{ x: 30, y: 28, w: 19, h: 44, color: 'green', label: `${firstName} 96%` }] },
        { id: 't2', name: '12:34pm — Cafeteria', status: 'Appearance match · 92%', time: '12:34:07', boxes: [{ x: 24, y: 32, w: 18, h: 40, color: 'blue', label: '92%' }] },
      ],
    };
  }

  if (id === 'weapon') {
    return {
      heading: 'No weapon detected on campus',
      sub: 'Monitoring every camera · last check 2 seconds ago',
      stats: [],
      isWeapon: true,
      rowsTitle: 'Past detections — shown honestly',
      rows: [
        { name: 'Main gate — entrance', sub: 'Jul 11 · knife-shaped object', badge: 'False alarm', tone: 'neutral' },
        { name: 'Playground — east', sub: 'May 3 · toy replica', badge: 'False alarm', tone: 'neutral' },
        { name: 'Building C — corridor', sub: 'Feb 18 · knife-shaped object', badge: 'Confirmed', tone: 'bad' },
      ],
      foot: 'Every detection is reviewed by a person before any action is taken.',
      cameras: [
        { id: 'w1', name: 'Main gate — entrance', status: 'Scanning · clear', boxes: [{ x: 30, y: 30, w: 18, h: 42, color: 'green', label: 'No weapon' }] },
        { id: 'w2', name: 'Building C — corridor', status: 'Scanning · clear', boxes: [{ x: 52, y: 32, w: 17, h: 40, color: 'green', label: 'No weapon' }] },
      ],
    };
  }

  // intrude
  return {
    heading: '1 breach today',
    sub: '1 still needs review',
    stats: [],
    rowsTitle: 'Recent breaches',
    rows: [
      { name: 'Chemistry lab', sub: 'Today, 6:12am · unidentified person', badge: 'Open', tone: 'bad' },
      { name: 'Rooftop access door', sub: 'Yesterday, 11:42pm · unidentified', badge: 'Resolved', tone: 'good' },
      { name: 'Server room', sub: 'Jul 26, 7:20pm · T. Nassar (IT)', badge: 'Authorised', tone: 'neutral' },
    ],
    cameras: [
      { id: 'i1', name: 'Chemistry lab — door', status: 'Breach detected 6:12am', time: '06:12:44', zone: { x: 10, y: 18, w: 52, h: 62, label: 'Restricted' }, boxes: [{ x: 24, y: 34, w: 19, h: 42, color: 'red', label: 'Person in zone' }] },
      { id: 'i2', name: 'Boundary fence — east', status: 'Paused by IT', zone: { x: 8, y: 44, w: 82, h: 34, label: 'Paused' }, boxes: [] },
    ],
  };
}

/* ---------- people directory ---------- */

export async function getPeople(): Promise<DirectoryPerson[]> {
  await delay(150);
  return PEOPLE_DIRECTORY;
}

export async function getGroups(): Promise<GroupSummary[]> {
  await delay(120);
  return GROUP_SUMMARIES;
}

export async function getGroup(name: string): Promise<{ summary: GroupSummary; roster: GroupMember[] }> {
  await delay(150);
  return { summary: getGroupSummary(name), roster: getGroupRoster(name) };
}

export async function getHistory(name: string): Promise<PersonHistory> {
  await delay(180);
  return getPersonHistory(name);
}

/* ---------- system / camera sources ---------- */

export async function getSystemSummary(): Promise<SystemSummary> {
  await delay(150);
  const total = CAMERA_SOURCES.reduce((sum, s) => sum + s.channels, 0);
  const up = CAMERA_SOURCES.filter((s) => s.status === 'ok').reduce((sum, s) => sum + s.channels, 0);
  const down = CAMERA_SOURCES.filter((s) => s.status !== 'ok').map((s) =>
    s.status === 'down'
      ? `${s.name} is offline — ${s.channels} ${s.channels === 1 ? 'camera is' : 'cameras are'} not recording`
      : `${s.name} is refusing the saved password`,
  );
  return {
    camerasOnline: up || CAMERA_ONLINE,
    camerasTotal: total || CAMERA_TOTAL,
    summary: down.length ? `${down.join('; ')}.` : 'Everything is recording and being analysed.',
    gpu: '61%',
    storage: '47%',
  };
}

export function getCameraSources() {
  return CAMERA_SOURCES;
}

export function getAreaOptions() {
  return AREA_OPTIONS;
}

export async function scanNetwork(): Promise<FoundDevice[]> {
  await delay(1600);
  return [
    { name: 'Hikvision DS-7732NI (NVR)', ip: '192.168.1.42', channels: 32, duplicate: true, added: false },
    { name: 'Dahua IPC-HDW2431T', ip: '192.168.1.126', channels: 1, duplicate: false, added: false },
    { name: 'ONVIF device (unnamed)', ip: '192.168.1.131', channels: 1, duplicate: false, added: false },
  ];
}

export async function connectDvr(): Promise<{ channels: number }> {
  await delay(1300);
  return { channels: 8 };
}

export async function testConnection(): Promise<Camera> {
  await delay(1100);
  return { id: 'test-frame', name: 'Test frame', status: 'Connection OK · H.264 · 1080p · 12 fps', time: '08:47:12', boxes: [] };
}
