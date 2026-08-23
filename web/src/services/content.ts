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

/** Example questions on the Home ask bar. Pure copy. */
export const SUGGESTED_QUESTIONS = [
  'Who is absent in Grade 8 today?',
  'How many people are in the cafeteria?',
  'Has anyone entered the chemistry lab after hours?',
  'Find a red backpack left in the library',
  'Where was Layla Ahmed this morning?',
];

/** What each role may do, shown on the Users page.
 *
 *  This is a description of the policy, not the policy itself — the engine
 *  enforces roles. `routes.tsx` already flags that the client-side guard is a
 *  product rule, not a security boundary. */
export const CAPABILITIES: { capability: string; admin: boolean; it: boolean }[] = [
  { capability: 'See alerts and camera views', admin: true, it: true },
  { capability: 'Confirm or dismiss a weapon detection', admin: true, it: false },
  { capability: 'Track a person across cameras', admin: true, it: false },
  { capability: 'View attendance and student records', admin: true, it: false },
  { capability: 'Add or remove cameras and recorders', admin: true, it: true },
  { capability: 'Restart the detection engine', admin: true, it: true },
  { capability: 'Manage users', admin: true, it: false },
];

/** The explainer on the Weapons page: what happens, in order, when something
 *  is spotted. The third step is the product's core safety claim. */
/** Time-of-day presets on the Track a person page. */
export const TRACK_WINDOWS = [
  { label: 'Whole school day', from: '07:00', to: '16:00' },
  { label: 'Morning only', from: '07:00', to: '12:00' },
  { label: 'Afternoon only', from: '12:00', to: '16:00' },
];
