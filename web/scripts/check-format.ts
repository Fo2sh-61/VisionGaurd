/** Checks for services/format.ts — the layer that turns engine data into words.
 *
 *  Run with `npm run check:format`.
 *
 *  This file has more logic than it looks like it does: timezone rendering,
 *  relative day labels, and the single place fractions become percentages. All
 *  three are quietly easy to get wrong and loudly wrong on screen when they are,
 *  so they get checked rather than assumed.
 *
 *  There is no test runner in this app yet. When one arrives, this becomes an
 *  ordinary spec file with no other changes. */

import {
  formatEventTime, formatTime, formatClock, formatDuration, formatSchedule,
  formatMetric, toDetectionBox, toCameraZone, severityToTone, boxColor, formatLongDate,
  identifiedByFace, formatCapacityRow, formatEngineBusy, capacityShare,
} from '../src/services/format';
import { pictureRect } from '../src/services/frame';
import type { CapacityRowItem } from '../src/types';

let pass = 0, fail = 0;
const eq = (name: string, got: unknown, want: unknown) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (ok) { pass++; } else { fail++; console.log(`FAIL ${name}\n  got  ${JSON.stringify(got)}\n  want ${JSON.stringify(want)}`); }
};

/** `fill` (i18n/index.ts) wraps every substituted value in bidi isolates, so
 *  an Arabic sentence puts its numbers the right way round. They are invisible
 *  on screen and would only make these expectations unreadable, so they come
 *  off before comparing. On a string carrying none this does nothing. */
const plain = (s: string) => s.replace(/[\u2068\u2069]/g, '');

// Cairo is UTC+3. 06:12 local == 03:12 UTC.
const cairo = (utc: string) => ({ utc, tzOffsetMinutes: 180 });

eq('formatTime morning', formatTime(cairo('2026-07-29T04:42:00Z'), 'en'), '7:42am');
eq('formatTime afternoon', formatTime(cairo('2026-07-29T11:40:00Z'), 'en'), '2:40pm');
eq('formatTime midnight', formatTime(cairo('2026-07-29T21:00:00Z'), 'en'), '12:00am');
eq('formatTime noon', formatTime(cairo('2026-07-29T09:00:00Z'), 'en'), '12:00pm');
eq('formatClock', formatClock(cairo('2026-07-29T04:42:11Z')), '07:42:11');

// A viewer in another timezone must still see the SCHOOL's clock.
const original = process.env.TZ;
process.env.TZ = 'America/New_York';
eq('school time survives a foreign viewer', formatTime(cairo('2026-07-29T04:42:00Z'), 'en'), '7:42am');
process.env.TZ = original;

eq('duration seconds', plain(formatDuration(7, 'en')), '7 seconds');
eq('duration singular', plain(formatDuration(1, 'en')), '1 second');
eq('duration minutes', plain(formatDuration(180, 'en')), '3 minutes');
eq('duration hours', plain(formatDuration(25560, 'en')), '7h 06m');

eq('schedule outside weekdays',
   formatSchedule({ mode: 'outside', days: ['mon','tue','wed','thu','fri'], start: '08:00', end: '16:00' }),
   'Locked outside 8am–4pm, weekdays');
eq('schedule always', formatSchedule({ mode: 'always', days: [], start: null, end: null }), 'Locked at all times');
eq('schedule inside', formatSchedule({ mode: 'inside', days: ['mon'], start: '09:30', end: '11:00' }),
   'Locked during 9:30am–11am, Mondays');

eq('metric count', formatMetric({ key:'a', label:'Here', value:133, unit:'count', total:142, severity:'info' }, 'en'), { label:'Here', value:'133/142' });
eq('metric percent', formatMetric({ key:'a', label:'Rate', value:0.936, unit:'percent', severity:'info' }, 'en'), { label:'Rate', value:'94%' });
eq('metric missing', formatMetric({ key:'a', label:'GPU', value:null, unit:'percent', severity:'info' }, 'en'), { label:'GPU', value:'—' });

// Fractions -> percentages, exactly once.
eq('box scaling', toDetectionBox({ x:0.18, y:0.26, w:0.2, h:0.44, label:'Layla A.', confidence:0.96, kind:'match', match:'face', severity:'info' }),
   { x:18, y:26, w:20, h:44, color:'green', label:'Layla A. 96%' });
eq('threat box is red', boxColor({ x:0,y:0,w:1,h:1, kind:'weapon', match:'none', severity:'critical' }), 'red');
eq('appearance box is blue', boxColor({ x:0,y:0,w:1,h:1, kind:'person', match:'appearance', severity:'info' }), 'blue');

// A polygon collapses to its bounding box for today's renderer.
eq('polygon bounds', toCameraZone({ id:'z', label:'Restricted', enabled:true,
   polygon:[{x:0.1,y:0.2},{x:0.6,y:0.15},{x:0.62,y:0.8},{x:0.12,y:0.78}] }),
   { x:10, y:15, w:52, h:65, label:'Restricted' });

eq('severity mapping', [severityToTone('critical'), severityToTone('warn'), severityToTone('info')], ['bad','warn','good']);
eq('long date', formatLongDate('2026-07-29', 'en'), 'Wednesday, July 29, 2026');

// Relative day labels, anchored to the school's clock.
const now = new Date();
const utcNow = new Date(now.getTime() - 180*60000).toISOString();
eq('today label', formatEventTime(cairo(utcNow), 'en').startsWith('Today, '), true);
const y = new Date(now.getTime() - 86400000 - 180*60000).toISOString();
eq('yesterday label', formatEventTime(cairo(y), 'en').startsWith('Yesterday, '), true);
eq('old date has no year when same year', plain(formatEventTime(cairo('2026-01-26T16:20:00Z'), 'en')), 'Jan 26, 7:20pm');

/* ---------- track: what "identified by face" is read from ----------
 *
 *  `/tracking/live` sets `match` to APPEARANCE on every identity, always, by
 *  design (app.py) — a body is being followed because its clothing matched,
 *  and a readable face is an annotation on top of that, never the reason the
 *  box exists. The match kind therefore cannot answer "has a face named this
 *  person"; it answers "why are we following this body", which is a different
 *  question with a constant answer.
 *
 *  Only the name can answer it, because the engine sets a label only when a
 *  face was matched INSIDE that body in THAT frame. Reading the match kind is
 *  what made the Track page print "Not identified by face" directly beside the
 *  person's own name. */

eq('a name means a face named them', identifiedByFace('Layla A.'), true);
eq('no name means clothing only', identifiedByFace(null), false);
eq('undefined is not identified', identifiedByFace(undefined), false);
eq('an empty label is not a name', identifiedByFace(''), false);
eq('"Unknown" is a placeholder, not a name', identifiedByFace('Unknown'), false);
eq('"Unknown person" is not a name', identifiedByFace('Unknown person'), false);

// ...and the box beside the badge must agree with it. A tracked body carries
// match='appearance' whatever its face is doing, so reading the match kind left
// it blue while the badge said 'Identified by face' — the picture contradicting
// the words directly above it.
eq('named tracked body draws green',
   boxColor({ x:0,y:0,w:1,h:1, kind:'match', match:'appearance', severity:'info', label:'Layla A.' }), 'green');
eq('unnamed tracked body stays blue',
   boxColor({ x:0,y:0,w:1,h:1, kind:'person', match:'appearance', severity:'info' }), 'blue');
eq('an "Unknown" label is not a face match',
   boxColor({ x:0,y:0,w:1,h:1, kind:'face', match:'none', severity:'info', label:'Unknown' }), 'blue');
eq('a weapon is red whatever its label',
   boxColor({ x:0,y:0,w:1,h:1, kind:'weapon', match:'none', severity:'critical', label:'Layla A.' }), 'red');

// The regression itself. This identity is what the endpoint really sends: a
// named person whose match kind is nonetheless 'appearance'.
const namedBody = { name: 'Layla A.', match: 'appearance' as const };
eq('named body, appearance match, IS identified', identifiedByFace(namedBody.name), true);
eq('reading the match kind gets it wrong', namedBody.match === 'face', false);

/* ---------- where the picture is, inside the tile that holds it ----------
 *
 *  A tile is whatever size the page's grid gave it. The picture inside it is
 *  whatever shape the camera is. Every overlay the engine sends is a fraction
 *  of the PICTURE, so drawing one as a percentage of the TILE is only correct
 *  when the two happen to be the same shape.
 *
 *  On the people counting page they were not: a tile about as tall as it is
 *  wide, holding a 16:9 camera. Every box was drawn tens of percent away from
 *  the person it belonged to, and `object-fit: cover` cropped the sides off as
 *  well — so people who were in the count were not on the screen. */

eq('same shape uses the whole tile',
   pictureRect(400, 200, 2), { left: 0, top: 0, width: 400, height: 200 });
eq('wider than the tile gets bars above and below',
   pictureRect(400, 400, 2), { left: 0, top: 100, width: 400, height: 200 });
eq('narrower than the tile gets bars either side',
   pictureRect(400, 100, 2), { left: 100, top: 0, width: 200, height: 100 });

// Before the first frame there is no shape to know, and pretending otherwise
// would move every overlay for one paint. The whole tile is the honest answer.
eq('unknown shape is the whole tile',
   pictureRect(400, 400, null), { left: 0, top: 0, width: 400, height: 400 });
eq('a nonsense aspect is the whole tile',
   pictureRect(400, 400, 0), { left: 0, top: 0, width: 400, height: 400 });
eq('an unmeasured tile has nothing to divide',
   pictureRect(0, 0, 2), { left: 0, top: 0, width: 0, height: 0 });

// The regression itself, in the pixels the box is actually drawn at. A body
// 20% down a 16:9 picture inside a square tile is 140px down, not 80px — and
// 80px is where it used to be drawn.
const shot = pictureRect(400, 400, 2);
eq('a box lands on the picture, not on the tile',
   shot.top + (20 / 100) * shot.height, 140);
eq('reading it against the tile gets it wrong', (20 / 100) * 400, 80);

/* ---------- one camera is not "1 cameras" ----------
 *
 *  Every row of the capacity card carries a camera count, and the catalogue had
 *  a single form for it. On a site running one camera that is not one awkward
 *  row — it is every row on the card. */
const capacityRow = (cameras: number): CapacityRowItem => ({
  name: 'people', pool: 'gpu', cameras, msPerFrame: 31, measured: true,
  onDemand: false, shared: false, busyMsPerSecond: 150, analysedPerSecond: 4.9,
});
eq('one camera reads singular', plain(formatCapacityRow(capacityRow(1), 'en')),
   '1 camera · 4.9 a second analysed · 31 ms a frame');
eq('two cameras still read plural', plain(formatCapacityRow(capacityRow(2), 'en')),
   '2 cameras · 4.9 a second analysed · 31 ms a frame');

/* ---------- the card's share is the driver's figure, never ours ----------
 *
 *  `busyMsPerSecond` is wall clock inside analyse(): preparing the frame, the
 *  inference, reading the result back, and whatever Python did around them.
 *  Dividing it by the card's 1,000 ms printed a percentage and labelled it
 *  "measured", and it ran ahead of the driver's own figure on the bar directly
 *  above it. The processor row keeps its percentage, because there the wall
 *  clock IS the thing `cores x 1000` budgets. */
eq('the graphics row states milliseconds only',
   plain(formatEngineBusy('gpu', 340, 1000, 'en')),
   'This engine: 340 ms of every second inside the detector, measured (worker time, not card time)');
eq('the graphics row claims no share of the card',
   /%/.test(formatEngineBusy('gpu', 340, 1000, 'en')), false);
eq('the processor row keeps its share of cores x 1000',
   plain(formatEngineBusy('cpu', 1600, 8000, 'en')),
   'This engine: 1,600 ms of every second (20%), measured');

// The regression itself, in the arithmetic that was on the page: a detector
// busy 340 ms of every second printed "34%" under a bar the driver had at 12%.
eq('the old arithmetic overstated the card', Math.round(340 / 10), 34);
eq('a share is only honest against the budget the number came out of',
   capacityShare(1600, 8000), 20);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
