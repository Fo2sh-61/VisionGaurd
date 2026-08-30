/** UI copy and option lists that belong to the front end.
 *
 *  This is what survived `mockData.ts`. Everything here is *wording* or a fixed
 *  vocabulary the interface offers — not measurements. It stays client-side on
 *  purpose: the engine returns states and numbers, the front end decides how to
 *  say them. Otherwise a copy tweak or Arabic translation needs a backend
 *  deploy.
 *
 *  If you find yourself adding a number here that the engine could measure,
 *  it belongs in the API instead. */

import type { MessageKey } from '@/i18n';

/** Example questions on the Home ask bar. Keys, not words — the wording
 *  lives in `web/src/i18n/` so the examples can be asked in Arabic too. */
export const SUGGESTED_QUESTIONS: MessageKey[] = [
  'ask.q.absent',
  'ask.q.cafeteria',
  'ask.q.lab',
  'ask.q.backpack',
  'ask.q.where',
];

/** What each role may do, shown on the Users page.
 *
 *  This is a description of the policy, not the policy itself — the engine
 *  enforces roles. `routes.tsx` already flags that the client-side guard is a
 *  product rule, not a security boundary. */
export const CAPABILITIES: { capability: MessageKey; admin: boolean; it: boolean }[] = [
  { capability: 'capability.seeAlerts', admin: true, it: true },
  { capability: 'capability.reviewWeapon', admin: true, it: false },
  { capability: 'capability.track', admin: true, it: false },
  { capability: 'capability.attendance', admin: true, it: false },
  { capability: 'capability.cameras', admin: true, it: true },
  { capability: 'capability.restart', admin: true, it: true },
  { capability: 'capability.users', admin: true, it: false },
];

/** The explainer on the Weapons page: what happens, in order, when something
 *  is spotted. The third step is the product's core safety claim. */
/** Time-of-day presets on the Track a person page. */
export const TRACK_WINDOWS: { label: MessageKey; from: string; to: string }[] = [
  { label: 'track.window.wholeDay', from: '07:00', to: '16:00' },
  { label: 'track.window.morning', from: '07:00', to: '12:00' },
  { label: 'track.window.afternoon', from: '12:00', to: '16:00' },
];
