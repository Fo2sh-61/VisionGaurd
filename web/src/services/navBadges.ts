/** The two counts the sidebar badges show (spec 022 FR-103).
 *
 *  Both come from endpoints that already exist; nothing here is new engine
 *  work. Zones and stations add their own badges with specs 025 and 026. */

import { getVehicleAlerts } from './api';
import { get } from './http';
import type { AttendanceResult } from './wire';

/** People expected today who have not arrived yet, across everyone. */
export async function getNotArrivedCount(today: string): Promise<number> {
  const result = await get<AttendanceResult>('/attendance', {
    mode: 'group', subject: 'Everyone', date: today,
  });
  return result.absent;
}

/** Gate alerts still waiting for a person. */
export async function getOpenGateAlertCount(): Promise<number> {
  return (await getVehicleAlerts()).length;
}
