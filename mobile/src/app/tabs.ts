/** The phone's five tabs, and how the console's ten tools reach them.
 *
 *  Five tabs cannot hold sixteen destinations, so two of them are lists: Tools
 *  carries the console's `ask` and `watch` sections, and its `manage` section
 *  splits across the last three tabs. Every route the console has is
 *  reachable; nothing is dropped to make the bar fit.
 *
 *  **The tool list is derived, never typed out.** It comes from `NAV` in
 *  `app/navigation.ts`, which is a byte copy of the console's and is on the
 *  parity list. The fixture app kept its own hand-written list of six tools
 *  and had silently never included the vehicle gate at all — a whole feature
 *  missing from the phone because two lists were maintained by hand and only
 *  one of them was ever read. Deriving it means a tool added to the console
 *  appears here too, and cannot quietly go missing.
 *
 *  The labels are keys, not words. A tab bar with English baked into it could
 *  not be Arabic, which is why `nav.tab.*` lives in the shared catalogue
 *  beside every other piece of wording. */

import { NAV, type NavEntry } from '@/app/navigation';
import type { MessageKey } from '@/i18n';

export type TabId = 'home' | 'tools' | 'people' | 'system' | 'account';

export interface TabDef {
  id: TabId;
  /** A key, resolved at render time in whichever language the account reads. */
  label: MessageKey;
  path: string;
  /** SVG path data from the design's mobile icon set — 18x18 viewBox. */
  icon: string;
}

export const TABS: TabDef[] = [
  { id: 'home', label: 'nav.tab.home', path: '/', icon: 'M3.2 7.8 L9 3 L14.8 7.8 V15 H3.2 Z' },
  {
    id: 'tools',
    label: 'nav.tab.tools',
    path: '/tools',
    icon: 'M2.8 3.4 H7.6 V8.2 H2.8 Z M10.4 3.4 H15.2 V8.2 H10.4 Z M2.8 10.4 H7.6 V15.2 H2.8 Z M10.4 10.4 H15.2 V15.2 H10.4 Z',
  },
  {
    id: 'people',
    label: 'nav.tab.people',
    path: '/people',
    icon: 'M6.2 3.6 a2.2 2.2 0 1 0 .01 0 M2.9 14.4 c0-2.5 1.7-3.9 3.3-3.9 s3.3 1.4 3.3 3.9 M12.2 5.4 a1.9 1.9 0 1 0 .01 0 M11.5 11.1 c1.8 .3 3.3 1.4 3.3 3.1',
  },
  { id: 'system', label: 'nav.tab.more', path: '/system', icon: 'M2.6 9.5 H5.8 L7.8 5 L10.3 13.5 L12.2 9.5 H15.4' },
  {
    id: 'account',
    label: 'nav.tab.more',
    path: '/account',
    icon: 'M9 3.4 a2.6 2.6 0 1 0 .01 0 M3.6 15 c0-3 2.4-4.6 5.4-4.6 s5.4 1.6 5.4 4.6',
  },
];

/** Which tab owns a path, so the bar can show where you are.
 *
 *  Order matters: `/people/enrol` must light the People tab, so longer
 *  prefixes are tested before the shorter ones they begin with. */
const TAB_PREFIXES: [string, TabId][] = [
  ['/people', 'people'],
  ['/system', 'system'],
  ['/settings', 'account'],
  ['/users', 'account'],
  ['/account', 'account'],
  ['/tools', 'tools'],
];

export function tabFor(pathname: string): TabId {
  for (const [prefix, tab] of TAB_PREFIXES) {
    if (pathname === prefix || pathname.startsWith(`${prefix}/`)) return tab;
  }
  // Everything else is a tool — /attendance, /counting, /weapons, /vehicles,
  // /track, /intrusion, /lost-items — and Home is the only bare path left.
  return pathname === '/' ? 'home' : 'tools';
}

/** The Tools tab's list: the console's `ask` and `watch` sections, in its
 *  order. `manage` is deliberately absent — People, System and Settings are
 *  tabs in their own right. */
export function toolEntries(): NavEntry[] {
  return NAV.filter((entry) => entry.section === 'ask' || entry.section === 'watch');
}
