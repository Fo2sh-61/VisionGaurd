export type TabId = 'home' | 'tools' | 'people' | 'system' | 'account';

export interface TabDef {
  id: TabId;
  label: string;
  path: string;
  icon: string;
}

/** Icon paths lifted from the design's mobile icon set — 18x18 viewBox. */
export const TABS: TabDef[] = [
  { id: 'home', label: 'Ask', path: '/', icon: 'M3.2 7.8 L9 3 L14.8 7.8 V15 H3.2 Z' },
  {
    id: 'tools',
    label: 'Tools',
    path: '/tools',
    icon: 'M2.8 3.4 H7.6 V8.2 H2.8 Z M10.4 3.4 H15.2 V8.2 H10.4 Z M2.8 10.4 H7.6 V15.2 H2.8 Z M10.4 10.4 H15.2 V15.2 H10.4 Z',
  },
  {
    id: 'people',
    label: 'People',
    path: '/people',
    icon: 'M6.2 3.6 a2.2 2.2 0 1 0 .01 0 M2.9 14.4 c0-2.5 1.7-3.9 3.3-3.9 s3.3 1.4 3.3 3.9 M12.2 5.4 a1.9 1.9 0 1 0 .01 0 M11.5 11.1 c1.8 .3 3.3 1.4 3.3 3.1',
  },
  { id: 'system', label: 'System', path: '/system', icon: 'M2.6 9.5 H5.8 L7.8 5 L10.3 13.5 L12.2 9.5 H15.4' },
  {
    id: 'account',
    label: 'Account',
    path: '/account',
    icon: 'M9 3.4 a2.6 2.6 0 1 0 .01 0 M3.6 15 c0-3 2.4-4.6 5.4-4.6 s5.4 1.6 5.4 4.6',
  },
];
