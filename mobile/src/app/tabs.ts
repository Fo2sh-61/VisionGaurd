/** The phone's five tabs, and which tab and header every screen belongs to.
 *
 *  Spec 015 (phone-first redesign, 17 Sep 2026): Home, Cameras, Tools, People
 *  and More. System health, Settings and Accounts moved under More - they are
 *  visited, not lived in, and a guard's thumb should reach Cameras first.
 *
 *  **The tool list is derived, never typed out.** It comes from `NAV` in
 *  `app/navigation.ts`, which is a byte copy of the console's and is on the
 *  parity list. The fixture app kept its own hand-written list of six tools
 *  and had silently never included the vehicle gate at all - a whole feature
 *  missing from the phone because two lists were maintained by hand and only
 *  one of them was ever read.
 *
 *  The labels are keys, not words, so the tab bar can be Arabic. */

import { NAV, type NavEntry } from '@/app/navigation';
import type { MessageKey } from '@/i18n';
import type { Role } from '@/types';
import type { IconName } from '@/components/Icon';

export type TabId = 'home' | 'cameras' | 'tools' | 'people' | 'more';

export interface TabDef {
  id: TabId;
  label: MessageKey;
  path: string;
  icon: IconName;
}

export const TABS: TabDef[] = [
  { id: 'home', label: 'nav.tab.home', path: '/', icon: 'home' },
  { id: 'cameras', label: 'nav.tab.cameras', path: '/cameras', icon: 'camera' },
  { id: 'tools', label: 'nav.tab.tools', path: '/tools', icon: 'tools' },
  { id: 'people', label: 'nav.tab.people', path: '/people', icon: 'people' },
  { id: 'more', label: 'nav.tab.more', path: '/more', icon: 'more' },
];

export interface ScreenDef {
  /** Matches the path exactly, or anything under it (`/people/` + more). */
  prefix: string;
  tab: TabId;
  /** The back header's title. A screen about one thing (a camera, a person)
   *  replaces it with that thing's name through `usePageTitle`. */
  title: MessageKey;
  /** Where Back goes when there is no earlier screen in this visit - a
   *  reload, or a link opened from outside. */
  parent: string;
}

/** Longest prefix first: `/people/enrol` must match before `/people`. */
const SCREENS: ScreenDef[] = [
  { prefix: '/people/enrol', tab: 'people', title: 'enrol.title', parent: '/people' },
  { prefix: '/people/groups', tab: 'people', title: 'nav.people.label', parent: '/people' },
  { prefix: '/people/history', tab: 'people', title: 'nav.people.label', parent: '/people' },
  { prefix: '/cameras', tab: 'cameras', title: 'nav.tab.cameras', parent: '/cameras' },
  { prefix: '/alerts', tab: 'home', title: 'bell.title', parent: '/' },
  { prefix: '/attendance', tab: 'tools', title: 'nav.attendance.label', parent: '/tools' },
  { prefix: '/counting', tab: 'tools', title: 'nav.counting.label', parent: '/tools' },
  { prefix: '/lost-items', tab: 'tools', title: 'nav.lost-items.label', parent: '/tools' },
  { prefix: '/track', tab: 'tools', title: 'nav.track.label', parent: '/tools' },
  { prefix: '/intrusion', tab: 'tools', title: 'nav.intrusion.label', parent: '/tools' },
  { prefix: '/weapons', tab: 'tools', title: 'nav.weapons.label', parent: '/tools' },
  { prefix: '/vehicles', tab: 'tools', title: 'nav.vehicles.label', parent: '/tools' },
  { prefix: '/stations', tab: 'tools', title: 'nav.stations.label', parent: '/tools' },
  { prefix: '/system', tab: 'more', title: 'health.title', parent: '/more' },
  { prefix: '/settings', tab: 'more', title: 'nav.settings.label', parent: '/more' },
  { prefix: '/users', tab: 'more', title: 'nav.users.label', parent: '/more' },
];

const ROOTS = new Set(TABS.map((tab) => tab.path));

/** A tab's own screen gets the top bar; everything below it gets a back header. */
export function isTabRoot(pathname: string): boolean {
  return ROOTS.has(pathname === '' ? '/' : pathname.replace(/\/+$/, '') || '/');
}

function matches(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

export function screenFor(pathname: string): ScreenDef | null {
  return SCREENS.find((screen) => matches(pathname, screen.prefix)) ?? null;
}

/** Which tab lights for a path. */
export function tabFor(pathname: string): TabId {
  const root = TABS.find((tab) => tab.path !== '/' && pathname === tab.path);
  if (root) return root.id;
  return screenFor(pathname)?.tab ?? 'home';
}

/** The tool paths the phone really routes as a tool (`app/routes.tsx`). A `main`
 *  entry in the byte-shared `NAV` whose path is not here gets no tile, so a
 *  tool the console gained cannot appear on the phone as a tile that leads
 *  nowhere. Add a path here in the same change that adds its route.
 *  `/stations` is deliberately absent: the phone only has an honest "on the
 *  console" page for it. */
export const PHONE_TOOL_PATHS: ReadonlySet<string> = new Set([
  '/attendance', '/counting', '/vehicles', '/intrusion',
]);

/** The Tools tab's list: the console's `main` section, in its order, without
 *  People (a tab of its own). The `system` section is under More. An entry
 *  with a `role` is left out for any other role, as in the console's sidebar:
 *  the engine would refuse an IT account on Attendance anyway. */
export function toolEntries(role: Role): NavEntry[] {
  return NAV.filter((entry) => entry.section === 'main' && entry.id !== 'people'
    && PHONE_TOOL_PATHS.has(entry.path)
    && (!entry.role || entry.role === role));
}
