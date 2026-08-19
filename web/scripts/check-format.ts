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
  identifiedByFace,
} from '../src/services/format';

let pass = 0, fail = 0;
const eq = (name: string, got: unknown, want: unknown) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (ok) { pass++; } else { fail++; console.log(`FAIL ${name}\n  got  ${JSON.stringify(got)}\n  want ${JSON.stringify(want)}`); }
};

// Cairo is UTC+3. 06:12 local == 03:12 UTC.
const cairo = (utc: string) => ({ utc, tzOffsetMinutes: 180 });

eq('formatTime morning', formatTime(cairo('2026-07-29T04:42:00Z')), '7:42am');
eq('formatTime afternoon', formatTime(cairo('2026-07-29T11:40:00Z')), '2:40pm');
eq('formatTime midnight', formatTime(cairo('2026-07-29T21:00:00Z')), '12:00am');
eq('formatTime noon', formatTime(cairo('2026-07-29T09:00:00Z')), '12:00pm');
eq('formatClock', formatClock(cairo('2026-07-29T04:42:11Z')), '07:42:11');

// A viewer in another timezone must still see the SCHOOL's clock.
const original = process.env.TZ;
process.env.TZ = 'America/New_York';
eq('school time survives a foreign viewer', formatTime(cairo('2026-07-29T04:42:00Z')), '7:42am');
process.env.TZ = original;

eq('duration seconds', formatDuration(7), '7 seconds');
eq('duration singular', formatDuration(1), '1 second');
eq('duration minutes', formatDuration(180), '3 minutes');
eq('duration hours', formatDuration(25560), '7h 06m');

eq('schedule outside weekdays',
   formatSchedule({ mode: 'outside', days: ['mon','tue','wed','thu','fri'], start: '08:00', end: '16:00' }),
   'Locked outside 8am–4pm, weekdays');
eq('schedule always', formatSchedule({ mode: 'always', days: [], start: null, end: null }), 'Locked at all times');
eq('schedule inside', formatSchedule({ mode: 'inside', days: ['mon'], start: '09:30', end: '11:00' }),
   'Locked during 9:30am–11am, Mondays');

eq('metric count', formatMetric({ key:'a', label:'Here', value:133, unit:'count', total:142, severity:'info' }), { label:'Here', value:'133/142' });
eq('metric percent', formatMetric({ key:'a', label:'Rate', value:0.936, unit:'percent', severity:'info' }), { label:'Rate', value:'94%' });
eq('metric missing', formatMetric({ key:'a', label:'GPU', value:null, unit:'percent', severity:'info' }), { label:'GPU', value:'—' });

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
eq('long date', formatLongDate('2026-07-29'), 'Wednesday, July 29, 2026');

// Relative day labels, anchored to the school's clock.
const now = new Date();
const utcNow = new Date(now.getTime() - 180*60000).toISOString();
eq('today label', formatEventTime(cairo(utcNow)).startsWith('Today, '), true);
const y = new Date(now.getTime() - 86400000 - 180*60000).toISOString();
eq('yesterday label', formatEventTime(cairo(y)).startsWith('Yesterday, '), true);
eq('old date has no year when same year', formatEventTime(cairo('2026-01-26T16:20:00Z')), 'Jan 26, 7:20pm');

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

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
