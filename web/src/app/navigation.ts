import type { Role, ToolId } from '@/types';

export type NavSection = 'ask' | 'watch' | 'manage';

export interface NavEntry {
  id: ToolId;
  path: string;
  label: string;
  /** short line used on the Home "Tools" grid */
  blurb: string;
  section: NavSection;
  /** SVG path data for the sidebar icon (18x18 viewBox) */
  icon: string;
  /** undefined = visible to everyone */
  role?: Role;
}

export const SECTION_LABEL: Record<NavSection, string> = {
  ask: 'ASK',
  watch: 'WATCH',
  manage: 'MANAGE',
};

/** Icon paths from the design's `IC` map — 18x18 viewBox, stroked not filled. */
const ICON = {
  home: 'M3 8 L9 3 L15 8 V15 H3 Z',
  attendance: 'M3.5 9.5 L7.5 13.5 L14.5 5',
  counting: 'M4 14 V8 M9 14 V4.5 M14 14 V10.5',
  'lost-items': 'M7.5 3 a4.2 4.2 0 1 0 0.01 0 M11.2 11.2 L15.5 15.5',
  track: 'M3.5 14.5 C7 6.5 11 12.5 14.5 4',
  intrusion: 'M3.5 4.5 H14.5 V13.5 H3.5 Z M9 7.8 a1.2 1.2 0 1 0 .01 0',
  weapons: 'M5 15.5 V3 H13.5 L11 6 L13.5 9 H5',
  system: 'M2.5 9.5 H6 L8 5 L10.5 13 L12.5 9.5 H15.5',
  people:
    'M6.2 3.5 a2.3 2.3 0 1 0 0.01 0 M2.8 14.5 c0-2.6 1.7-4 3.4-4 s3.4 1.4 3.4 4 M12.3 5.5 a2 2 0 1 0 0.01 0 M11.5 11.3 c1.9 .3 3.4 1.5 3.4 3.2',
  settings: 'M3 6.2 H15 M3 11.8 H15 M7 4.6 a1.6 1.6 0 1 0 0.01 0 M11.5 10.2 a1.6 1.6 0 1 0 0.01 0',
} as const;

export const HOME_ICON = ICON.home;

export const NAV: NavEntry[] = [
  { id: 'attendance', path: '/attendance', label: 'Attendance', blurb: 'Who arrived, who’s missing', section: 'ask', icon: ICON.attendance },
  { id: 'counting', path: '/counting', label: 'People counting', blurb: 'How many, anywhere', section: 'ask', icon: ICON.counting },
  { id: 'lost-items', path: '/lost-items', label: 'Lost bag', blurb: 'Look for it now', section: 'ask', icon: ICON['lost-items'] },
  { id: 'track', path: '/track', label: 'Track a person', blurb: 'Always logged', section: 'ask', icon: ICON.track },

  { id: 'intrusion', path: '/intrusion', label: 'Restricted zones', blurb: 'Areas that must stay empty', section: 'watch', icon: ICON.intrusion },
  { id: 'weapons', path: '/weapons', label: 'Knife detection', blurb: 'Human-reviewed, always', section: 'watch', icon: ICON.weapons },

  { id: 'people', path: '/people', label: 'People', blurb: 'Students, staff and groups', section: 'manage', icon: ICON.people },
  { id: 'system', path: '/system', label: 'System health & configuration', blurb: 'Cameras and recorders', section: 'manage', icon: ICON.system },
  { id: 'settings', path: '/settings', label: 'Settings', blurb: 'School, alerts and appearance', section: 'manage', icon: ICON.settings },
];

export function navFor(role: Role): NavEntry[] {
  return NAV.filter((n) => !n.role || n.role === role);
}

export function navSectionsFor(role: Role): { section: NavSection; items: NavEntry[] }[] {
  const items = navFor(role);
  return (['ask', 'watch', 'manage'] as NavSection[])
    .map((section) => ({ section, items: items.filter((n) => n.section === section) }))
    .filter((group) => group.items.length > 0);
}

export function pathFor(tool: ToolId): string {
  return NAV.find((n) => n.id === tool)?.path ?? '/';
}

/** Home's tool grid mirrors the design: the everyday tools, then People. */
const HOME_ORDER: ToolId[] = [
  'attendance',
  'counting',
  'lost-items',
  'track',
  'intrusion',
  'weapons',
  'people',
];

export function homeTools(): NavEntry[] {
  const byId = new Map(NAV.map((n) => [n.id, n]));
  return HOME_ORDER.map((id) => byId.get(id)!).filter(Boolean);
}
