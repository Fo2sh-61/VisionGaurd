/** The two counts the sidebar badges show (spec 022 FR-103).
 *
 *  Both come from endpoints that already exist; nothing here is new engine
 *  work. Zones and stations add theirs below (spec 025). */

import { getStations, getVehicleAlerts, getZoneCards } from './api';
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

/** Zones with somebody inside right now. Only what the engine answered: a zone
 *  whose camera is offline or whose detector is stopped is not counted as
 *  clear, and the caller shows no badge when this call fails. */
export async function getZonesInNowCount(): Promise<number> {
  const zones = await getZoneCards('en');
  return zones.filter((z) => z.status === 'personInZone').length;
}

/** Work stations empty past their limit. */
export async function getAbsentStationCount(): Promise<number> {
  const stations = await getStations('en');
  return stations.filter((s) => s.state === 'absent').length;
}
