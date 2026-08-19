/** Static fixtures for the mobile prototype — the same demo school as the web
 *  console, reshaped for the mobile design's single-answer-object pattern.
 *  Nothing here is real; see the web app's services/mockData.ts for the
 *  fuller commentary. This file goes away once a backend exists. */

import type {
  AlertRule,
  AttendanceFlag,
  AttentionItem,
  Camera,
  CameraSource,
  DeliveryTarget,
  DirectoryPerson,
  GroupMember,
  GroupSummary,
  PersonHistory,
  RecentItem,
  SchoolProfile,
  Stat,
  ToolDef,
  WeaponStep,
  Zone,
} from '@/types';

export const SCHOOL_NAME = 'Greenfield International School';
export const TODAY_ISO = '2026-07-29';

export const CAMERA_TOTAL: number = 208;
export const CAMERA_ONLINE: number = 192;

export const SUGGESTED_QUESTIONS: { q: string; tool: 'attend' | 'count' | 'lost' | 'track' }[] = [
  { q: 'Who was absent today?', tool: 'attend' },
  { q: 'How busy is the cafeteria?', tool: 'count' },
  { q: 'Lost a black backpack', tool: 'lost' },
  { q: 'Where did Layla go today?', tool: 'track' },
];

export const TOOL_DEFS: Record<string, ToolDef> = {
  attend: {
    id: 'attend',
    title: 'Attendance',
    lead: 'Recorded automatically by face recognition at the four entrance cameras.',
    blurb: 'Who arrived, who’s missing',
    runLabel: 'Show',
    emptyText: 'Choose a group and date, then press Show.',
    camTitle: 'Entrance cameras',
    camNote: 'Green box = recognised, red = not enrolled.',
    fields: [
      { key: 'group', label: 'Group', options: ['All students', 'All staff', 'Grade 7', 'Grade 8', 'Grade 9'] },
      { key: 'date', label: 'Date', options: ['Today — Wed, Jul 29', 'Tue, Jul 28', 'Mon, Jul 27'] },
    ],
  },
  count: {
    id: 'count',
    title: 'People counting',
    lead: 'How many people are in a place, now or at any past time.',
    blurb: 'How many, anywhere',
    runLabel: 'Show',
    emptyText: 'Pick a place and a time range.',
    camTitle: 'Cameras counting this area',
    camNote: 'The blue dashed line is the counting line.',
    fields: [
      {
        key: 'place',
        label: 'Place',
        options: ['Main entrance', 'Cafeteria', 'Assembly hall', 'Library', 'Classrooms', 'Playground', 'Whole campus'],
      },
      { key: 'when', label: 'When', options: ['Right now', 'Today by hour', 'This week by day'] },
    ],
  },
  lost: {
    id: 'lost',
    title: 'Lost bag',
    lead: 'Say what the bag looks like and where it went missing. The system searches the footage for it.',
    blurb: 'Search footage for it',
    runLabel: 'Search',
    emptyText: 'Pick the bag, then press Search.',
    camTitle: 'Where the bag was seen',
    camNote: 'Green box = matched bag; amber means less sure.',
    fields: [
      { key: 'item', label: 'Type of bag', options: ['Backpack', 'Sports bag', 'Handbag', 'Laptop bag'] },
      { key: 'colour', label: 'Colour', options: ['Black', 'Blue', 'Grey', 'Red', 'Green', 'Any'] },
      { key: 'area', label: 'Last seen area', options: ['Anywhere', 'Cafeteria', 'Library', 'Gymnasium', 'Corridors', 'Playground'] },
      { key: 'since', label: 'Missing since', options: ['Today', 'Yesterday', 'Last 3 days'] },
    ],
  },
  track: {
    id: 'track',
    title: 'Track a person',
    lead: 'Rebuild where someone went across campus, for investigations only.',
    blurb: 'Always logged',
    runLabel: 'Build path',
    emptyText: 'Choose a person and a time window.',
    camTitle: 'Each sighting on camera',
    camNote: 'Green = face match; blue = appearance match.',
    fields: [
      { key: 'who', label: 'Find', options: ['Layla Ahmed', 'Omar Khaled', 'Karim Adel', 'Unknown visitor (from clip)'] },
      { key: 'window', label: 'Time window', options: ['Whole school day', 'Morning only', 'Afternoon only'] },
    ],
  },
  weapon: {
    id: 'weapon',
    title: 'Knife detection',
    lead: 'Looks for knife-shaped objects on all 208 cameras. Every detection is reviewed by a person.',
    blurb: 'Human-reviewed, always',
    runLabel: 'Show',
    emptyText: '',
    camTitle: 'Highest-risk cameras',
    camNote: 'Green = scanned, nothing found.',
    fields: [{ key: 'window', label: 'Show detections from', options: ['This school year', 'Last 90 days', 'Last 30 days'] }],
  },
  intrude: {
    id: 'intrude',
    title: 'Restricted zones',
    lead: 'Restricted areas that alert when someone enters outside allowed hours.',
    blurb: 'Areas that must stay empty',
    runLabel: 'Show',
    emptyText: '',
    camTitle: 'Cameras watching restricted areas',
    camNote: 'The orange outline is the protected zone.',
    fields: [{ key: 'window', label: 'Show breaches from', options: ['Today', 'Last 7 days', 'Last 30 days'] }],
  },
};

export const TOOLS_LIST: ToolDef[] = [
  TOOL_DEFS.attend,
  TOOL_DEFS.count,
  TOOL_DEFS.lost,
  TOOL_DEFS.track,
  TOOL_DEFS.intrude,
  TOOL_DEFS.weapon,
];

export const ATTENTION: AttentionItem[] = [
  {
    id: 'attendance-g8',
    kind: 'Attendance',
    icon: '●',
    tone: 'warn',
    title: '34 students not yet arrived',
    sub: 'Grade 8 · as of 8:40am',
    action: 'See who',
    tool: 'attend',
  },
];

export const TODAY_STATS: Stat[] = [
  { label: 'On campus now', value: '1,679' },
  { label: 'Absent', value: '63' },
  { label: 'Late', value: '41' },
  { label: 'Visitors', value: '4' },
];

export const RECENT: RecentItem[] = [
  { id: 'r1', title: 'Attendance · Grade 8', sub: 'Checked 12 minutes ago', tool: 'attend' },
  { id: 'r2', title: 'Lost bag · black backpack', sub: 'Searched yesterday, 3 matches', tool: 'lost' },
  { id: 'r3', title: 'Cafeteria · people counting', sub: 'Checked yesterday at 12:40pm', tool: 'count' },
];

export const WEAPON_LIVE_CAMERA: Camera = {
  id: 'wp-live',
  name: 'Main gate — entrance',
  status: 'Detected 8:47:02am · 78% confidence',
  time: '08:47:02',
  boxes: [{ x: 34, y: 26, w: 20, h: 46, color: 'red', label: 'Knife-shaped 78%' }],
};

export const WEAPON_STEPS: WeaponStep[] = [
  { icon: '✓', tone: 'bad', title: 'Security desk notified', sub: 'Push and call · acknowledged by Sara Ibrahim' },
  { icon: '✓', tone: 'bad', title: 'Entrance cameras pinned to live view', sub: 'All 6 cameras, full-rate recording' },
  { icon: '●', tone: 'warn', title: 'Head teacher being contacted', sub: 'Calling · no answer yet' },
  { icon: '○', tone: 'neutral', title: 'Police — not contacted', sub: 'Your decision, never the system’s.' },
];

export const ZONES: Zone[] = [
  { id: 'chem', name: 'Chemistry lab', hours: 'Locked outside 8am–4pm', enabled: true },
  { id: 'server', name: 'Server room', hours: 'Locked outside 9am–5pm', enabled: true },
  { id: 'roof', name: 'Rooftop access door', hours: 'Locked at all times', enabled: true },
  { id: 'gym-store', name: 'Storage — gymnasium', hours: 'Locked outside 8am–6pm', enabled: true },
  { id: 'fence-east', name: 'Boundary fence — east', hours: 'Locked at all times', enabled: false },
];

/* ---------- people directory ---------- */

export const PEOPLE_DIRECTORY: DirectoryPerson[] = [
  { name: 'Layla Ahmed', type: 'Student', sub: 'Grade 8 — B', guardian: 'Rana Ahmed (mother) · +20 100 555 0143', photoOnFile: true, attendanceToday: 'On time · 7:42am' },
  { name: 'Omar Khaled', type: 'Student', sub: 'Grade 8 — A', guardian: 'Khaled Samir (father) · +20 100 555 0167', photoOnFile: true, attendanceToday: 'Late · 8:14am' },
  { name: 'Karim Adel', type: 'Student', sub: 'Grade 7 — C', guardian: 'Adel Hassan (father) · +20 100 555 0121', photoOnFile: false, attendanceToday: 'Absent today' },
  { name: 'Mona Fathy', type: 'Student', sub: 'Grade 9 — A', guardian: 'Nour Fathy (mother) · +20 100 555 0177', photoOnFile: true, attendanceToday: 'On time · 7:36am' },
  { name: 'Sara Ibrahim', type: 'Staff', sub: 'Deputy head', guardian: '', photoOnFile: true, attendanceToday: 'On site · 7:10am' },
  { name: 'Dina Mostafa', type: 'Staff', sub: 'Grade 7 teacher', guardian: '', photoOnFile: true, attendanceToday: 'On site · 7:22am' },
  { name: 'DHL courier', type: 'Visitor', sub: 'Registered Jul 28, one day', guardian: '', photoOnFile: false, attendanceToday: 'Signed out 2:10pm' },
];

export const GROUP_SUMMARIES: GroupSummary[] = [
  { name: 'Grade 7', count: '138 students · 5 classes', here: 129 },
  { name: 'Grade 8', count: '142 students · 5 classes', here: 133 },
  { name: 'Grade 9', count: '129 students · 4 classes', here: 124 },
  { name: 'All staff', count: '168 people', here: 164 },
  { name: 'Bus riders', count: '214 students', here: 201 },
];

type RosterRow = [string, string, string];

const ROSTER: Record<string, RosterRow[]> = {
  'Grade 7': [
    ['Karim Adel', '7 — C', 'Absent'],
    ['Yasmin Tarek', '7 — A', 'On time · 7:38am'],
    ['Hassan Nabil', '7 — B', 'On time · 7:44am'],
    ['Farida Sami', '7 — C', 'Late · 8:09am'],
    ['Ziad Ashraf', '7 — A', 'On time · 7:31am'],
    ['Malak Hisham', '7 — D', 'On time · 7:47am'],
  ],
  'Grade 8': [
    ['Layla Ahmed', '8 — B', 'On time · 7:42am'],
    ['Omar Khaled', '8 — A', 'Late · 8:14am'],
    ['Salma Reda', '8 — C', 'Late · 8:22am'],
    ['Hana Saleh', '8 — B', 'Absent'],
    ['Youssef Emad', '8 — A', 'On time · 7:29am'],
    ['Nour Hany', '8 — D', 'On time · 7:51am'],
  ],
  'Grade 9': [
    ['Mona Fathy', '9 — A', 'On time · 7:36am'],
    ['Adam Wael', '9 — B', 'On time · 7:40am'],
    ['Jana Mostafa', '9 — C', 'On time · 7:33am'],
    ['Seif Amr', '9 — A', 'Late · 8:05am'],
  ],
  'All staff': [
    ['Sara Ibrahim', 'Deputy head', 'On site · 7:10am'],
    ['Tarek Nassar', 'IT manager', 'On site · 7:18am'],
    ['Dina Mostafa', 'Grade 7 teacher', 'On site · 7:22am'],
    ['Amira Fouad', 'Grade 9 teacher', 'On site · 7:15am'],
  ],
  'Bus riders': [
    ['Layla Ahmed', 'Route 3', 'On time · 7:42am'],
    ['Ziad Ashraf', 'Route 1', 'On time · 7:31am'],
    ['Jana Mostafa', 'Route 5', 'On time · 7:33am'],
    ['Farida Sami', 'Route 3', 'Late · 8:09am'],
  ],
};

function statusTone(status: string): 'good' | 'warn' | 'bad' {
  if (status.startsWith('Absent')) return 'bad';
  if (status.startsWith('Late')) return 'warn';
  return 'good';
}

export function getGroupSummary(name: string): GroupSummary {
  return GROUP_SUMMARIES.find((g) => g.name === name) ?? GROUP_SUMMARIES[0];
}

export function getGroupRoster(name: string): GroupMember[] {
  return (ROSTER[name] ?? []).map(([person, sub, status]) => ({
    name: person,
    sub,
    status,
    tone: statusTone(status),
  }));
}

export function getPersonHistory(name: string): PersonHistory {
  const sub =
    PEOPLE_DIRECTORY.find((p) => p.name === name)?.sub ??
    Object.values(ROSTER)
      .flat()
      .find((r) => r[0] === name)?.[1] ??
    'Student';

  const todayRaw =
    Object.values(ROSTER)
      .flat()
      .find((r) => r[0] === name)?.[2] ?? 'On time · 7:42am';

  let todayMins: number;
  if (todayRaw.startsWith('Absent')) {
    todayMins = 0;
  } else {
    const m = todayRaw.match(/(\d+):(\d+)/);
    todayMins = m ? Number(m[1]) * 60 + Number(m[2]) : 462;
  }

  const seed = name.length;
  const days: [string, number | null][] = [
    ['Thu 16', 501],
    ['Sun 19', null],
    ['Mon 20', null],
    ['Tue 21', null],
    ['Wed 22', null],
    ['Thu 23', null],
    ['Sun 26', 0],
    ['Mon 27', 492],
    ['Tue 28', null],
    ['Wed 29', todayMins],
  ];
  const jitter = [0, 7, -5, 12, -9, 3, 16, -3, 9, -7];

  let sum = 0;
  let count = 0;
  const bars = days.map(([day, fixed], i) => {
    if (fixed === 0) return { day, label: 'Absent', pct: 100, tone: 'bad' as const };
    const mins = fixed !== null ? fixed : 448 + jitter[i] + ((seed * 3 + i * i * 5) % 11);
    sum += mins;
    count += 1;
    const h = Math.floor(mins / 60);
    const m = String(mins % 60).padStart(2, '0');
    return {
      day,
      label: `${(h % 12) || 12}:${m}am`,
      pct: Math.max(8, Math.round(((mins - 430) / 80) * 100)),
      tone: mins > 480 ? ('warn' as const) : ('good' as const),
    };
  });

  const avg = Math.round(sum / count);
  const usual = `${(Math.floor(avg / 60) % 12) || 12}:${String(avg % 60).padStart(2, '0')}`;
  const late = 2 + (todayMins > 480 ? 1 : 0);
  const absences = 1 + (todayMins === 0 ? 1 : 0);
  const term = 21;
  const present = term - absences;

  const flags: AttendanceFlag[] = [];
  if (todayMins === 0) {
    flags.push({ date: 'Wednesday, Jul 29', detail: 'No arrival recorded at any entrance', badge: 'Absent', tone: 'bad' });
  } else if (todayMins > 480) {
    const h = Math.floor(todayMins / 60) % 12 || 12;
    const m = String(todayMins % 60).padStart(2, '0');
    flags.push({ date: 'Wednesday, Jul 29', detail: `Main entrance · ${h}:${m}am`, badge: 'Late', tone: 'warn' });
  }
  flags.push(
    { date: 'Monday, Jul 27', detail: 'Main entrance · 8:12am', badge: 'Late', tone: 'warn' },
    { date: 'Sunday, Jul 26', detail: 'No arrival recorded at any entrance', badge: 'Absent', tone: 'bad' },
    { date: 'Thursday, Jul 16', detail: 'Gate 3 · 8:21am', badge: 'Late', tone: 'warn' },
  );

  return {
    name,
    sub,
    heading: `Present ${present} of ${term} days`,
    lead: `This term · usually arrives around ${usual}am, before the 8:00am cut-off.`,
    stats: [
      { label: 'Attendance', value: `${Math.round((present / term) * 100)}%` },
      { label: 'Late arrivals', value: String(late) },
      { label: 'Absences', value: String(absences) },
      { label: 'Usual arrival', value: usual },
    ],
    bars,
    flags,
  };
}

/* ---------- account / settings ---------- */

export const SCHOOL_PROFILE: SchoolProfile = {
  name: 'Greenfield International School',
  hoursFrom: '07:30',
  hoursTo: '15:00',
  termFrom: '2025-09-01',
  termTo: '2026-06-20',
  cutoff: '08:00',
};

export const ALERT_RULES: AlertRule[] = [
  { key: 'weapon', title: 'Weapon alerts', sub: 'Immediately · reviewed by a person first', channels: { Push: true, Email: true, SMS: true } },
  { key: 'attend', title: 'Morning attendance summary', sub: '9:00am each school day', channels: { Push: false, Email: true, SMS: false } },
  { key: 'intr', title: 'Restricted zone alerts', sub: 'When someone enters a restricted area', channels: { Push: true, Email: true, SMS: false } },
];

export const DELIVERY_TARGETS: DeliveryTarget[] = [
  { key: 'app', title: 'VisionGuard app', on: true, dest: 'This phone', editable: false, inputType: 'text', placeholder: '' },
  { key: 'email', title: 'Email', on: true, dest: 'mohamed61fouad@gmail.com', editable: true, inputType: 'email', placeholder: 'name@school.edu' },
  { key: 'sms', title: 'Text message (SMS)', on: false, dest: '', editable: true, inputType: 'tel', placeholder: '+20 1xx xxx xxxx' },
  { key: 'wa', title: 'WhatsApp', on: false, dest: '', editable: true, inputType: 'tel', placeholder: '+20 1xx xxx xxxx' },
];

/* ---------- system / camera sources ---------- */

export const CAMERA_SOURCES: CameraSource[] = [
  { id: 'src-1', name: 'NVR 1–2 — Main building', type: 'NVR', ip: '192.168.1.41', channels: 32, status: 'ok' },
  { id: 'src-2', name: 'DVR 3–4 — Building A', type: 'DVR', ip: '192.168.1.43', channels: 28, status: 'ok' },
  { id: 'src-3', name: 'DVR 5–6 — Building B', type: 'DVR', ip: '192.168.1.45', channels: 24, status: 'ok' },
  { id: 'src-4', name: 'DVR 7 — Building C', type: 'DVR', ip: '192.168.1.47', channels: 16, status: 'down' },
  { id: 'src-5', name: 'NVR 8–9 — Science block, Gymnasium', type: 'NVR', ip: '192.168.1.48', channels: 32, status: 'ok' },
  { id: 'src-6', name: 'NVR 10–11 — Cafeteria, Library', type: 'NVR', ip: '192.168.1.50', channels: 22, status: 'ok' },
  { id: 'src-7', name: 'NVR 12–13 — Gates & perimeter', type: 'NVR', ip: '192.168.1.52', channels: 52, status: 'ok' },
  { id: 'src-8', name: 'Gate cam 5 — bus lane', type: 'IP camera', ip: '192.168.1.121', channels: 1, status: 'ok' },
  { id: 'src-9', name: 'Playground PTZ', type: 'RTSP', ip: 'rtsp://192.168.1.130/main', channels: 1, status: 'auth' },
];

export const AREA_OPTIONS = ['Main building', 'Building A', 'Building B', 'Building C', 'Cafeteria', 'Gates & perimeter', 'Playground'];
