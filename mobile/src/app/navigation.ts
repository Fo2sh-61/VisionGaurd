import type { Role, ToolId } from '@/types';

/** Spec 022: one group of tools under Home, then SYSTEM. The old ask / watch /
 *  manage split is gone with the pages it organised. */
export type NavSection = 'main' | 'system';

export interface NavEntry {
  id: ToolId;
  path: string;
  section: NavSection;
  /** SVG path data for the sidebar icon (18x18 viewBox) */
  icon: string;
  /** undefined = visible to everyone */
  role?: Role;
}

/* The label and the one-line blurb are NOT here. They are wording, and
   wording lives in `web/src/i18n/` under `nav.<id>.label` / `.blurb` and
   `nav.section.<section>`. Keeping them in this table would mean an Arabic
   sidebar could not exist without editing the routing data. */

/** Icon paths from the design's `IC` map — 18x18 viewBox, stroked not filled. */
const ICON = {
  home: 'M3 8 L9 3 L15 8 V15 H3 Z',
  attendance: 'M3.5 9.5 L7.5 13.5 L14.5 5',
  counting: 'M4 14 V8 M9 14 V4.5 M14 14 V10.5',
  'lost-items': 'M7.5 3 a4.2 4.2 0 1 0 0.01 0 M11.2 11.2 L15.5 15.5',
  track: 'M3.5 14.5 C7 6.5 11 12.5 14.5 4',
  intrusion: 'M3.5 4.5 H14.5 V13.5 H3.5 Z M9 7.8 a1.2 1.2 0 1 0 .01 0',
  // A desk seen from the front: a top, two legs, and a person's head above it.
  stations: 'M3 10.5 H15 M4.5 10.5 V15 M13.5 10.5 V15 M9 3.2 a1.8 1.8 0 1 0 .01 0 M6.5 8 c.4-1.6 1.5-2.2 2.5-2.2 s2.1 .6 2.5 2.2',
  weapons: 'M5 15.5 V3 H13.5 L11 6 L13.5 9 H5',
  // A car, from the side: roof line over a body, two wheels.
  vehicles: 'M2.5 11 H15.5 M3.5 11 V8.5 L5.5 5.5 H12 L14.5 8.5 V11 M6 13 a1.3 1.3 0 1 0 .01 0 M12 13 a1.3 1.3 0 1 0 .01 0',
  system: 'M2.5 9.5 H6 L8 5 L10.5 13 L12.5 9.5 H15.5',
  people:
    'M6.2 3.5 a2.3 2.3 0 1 0 0.01 0 M2.8 14.5 c0-2.6 1.7-4 3.4-4 s3.4 1.4 3.4 4 M12.3 5.5 a2 2 0 1 0 0.01 0 M11.5 11.3 c1.9 .3 3.4 1.5 3.4 3.2',
  settings: 'M3 6.2 H15 M3 11.8 H15 M7 4.6 a1.6 1.6 0 1 0 0.01 0 M11.5 10.2 a1.6 1.6 0 1 0 0.01 0',
} as const;

export const HOME_ICON = ICON.home;

/** The sidebar, top to bottom (spec 022 FR-102, FR-129).
 *
 *  Attendance and People are admin-only. The engine refuses an IT account on
 *  `/attendance`, `/groups` and `/people` whatever this table says; `role`
 *  only stops the sidebar offering a page that would be refused.
 *
 *  Lost bag, Track a person and Knife detection are no longer in the product's
 *  navigation (their code stays; see `UNLISTED`). */
export const NAV: NavEntry[] = [
  { id: 'attendance', path: '/attendance', section: 'main', icon: ICON.attendance, role: 'admin' },
  { id: 'people', path: '/people', section: 'main', icon: ICON.people, role: 'admin' },
  { id: 'counting', path: '/counting', section: 'main', icon: ICON.counting },
  { id: 'vehicles', path: '/vehicles', section: 'main', icon: ICON.vehicles },
  { id: 'intrusion', path: '/intrusion', section: 'main', icon: ICON.intrusion },
  { id: 'stations', path: '/stations', section: 'main', icon: ICON.stations },

  { id: 'system', path: '/system', section: 'system', icon: ICON.system },
  { id: 'settings', path: '/settings', section: 'system', icon: ICON.settings },
];

/** Pages that still exist at their old address but are in no menu. Kept so an
 *  old alert or bookmark still resolves, and so `Icon` can still draw them. */
const UNLISTED: Record<string, { path: string; icon: string }> = {
  weapons: { path: '/weapons', icon: ICON.weapons },
  'lost-items': { path: '/lost-items', icon: ICON['lost-items'] },
  track: { path: '/track', icon: ICON.track },
};

/** The icon for any tool id, listed or not. */
export function iconFor(tool: ToolId): string {
  return NAV.find((n) => n.id === tool)?.icon ?? UNLISTED[tool]?.icon ?? '';
}

export function navFor(role: Role): NavEntry[] {
  return NAV.filter((n) => !n.role || n.role === role);
}

export function navSectionsFor(role: Role): { section: NavSection; items: NavEntry[] }[] {
  const items = navFor(role);
  return (['main', 'system'] as NavSection[])
    .map((section) => ({ section, items: items.filter((n) => n.section === section) }))
    .filter((group) => group.items.length > 0);
}

export function pathFor(tool: ToolId): string {
  return NAV.find((n) => n.id === tool)?.path ?? UNLISTED[tool]?.path ?? '/';
}

/** Home's tool cards: the three the design shows (spec 022 FR-116). */
const HOME_ORDER: ToolId[] = ['attendance', 'counting', 'vehicles'];

export function homeTools(): NavEntry[] {
  const byId = new Map(NAV.map((n) => [n.id, n]));
  return HOME_ORDER.map((id) => byId.get(id)!).filter(Boolean);
}
