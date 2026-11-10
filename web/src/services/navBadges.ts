/** The counts the sidebar badges show (spec 022 FR-103, attendance rule 023).
 *
 *  Both come from endpoints that already exist; nothing here is new engine
 *  work. Zones and stations add their own badges with specs 025 and 026. */

import { getVehicleAlerts } from './api';
import { attendanceBadgeCount, lateCutoffPassed } from './format';
import { get } from './http';
import type { AttendanceResult, SchoolProfile } from './wire';

/** People expected today who have not arrived yet, across everyone. Home reads
 *  it; excused people are not in it (the engine leaves them out of `absent`). */
export async function getNotArrivedCount(today: string): Promise<number> {
  const result = await get<AttendanceResult>('/attendance', {
    mode: 'group', subject: 'Everyone', date: today,
  });
  return result.absent;
}

/** People late or still not arrived, once today's late cut-off has passed.
 *
 *  `undefined` is "no badge": the cut-off has not passed, cannot be read, or
 *  nothing is being recorded. It is never 0, which would say "nobody is
 *  late". A failed call rejects, and the hook then drops the badge. */
export async function getAttendanceBadge(
  today: string,
  tzOffsetMinutes: number,
): Promise<number | undefined> {
  const profile = await get<SchoolProfile>('/settings/school');
  const passed = lateCutoffPassed(profile.lateCutoff, tzOffsetMinutes);
  // Before the cut-off there is nothing to count: skip the register read.
  if (!passed) return undefined;
  const result = await get<AttendanceResult>('/attendance', {
    mode: 'group', subject: 'Everyone', date: today,
  });
  return attendanceBadgeCount(result, passed);
}

/** Gate alerts still waiting for a person. */
export async function getOpenGateAlertCount(): Promise<number> {
  return (await getVehicleAlerts()).length;
}
