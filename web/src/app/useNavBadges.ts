import { useEffect, useState } from 'react';
import { getAttendanceBadge, getOpenGateAlertCount } from '@/services/navBadges';
import type { ToolId } from '@/types';
import { useAccount } from './AuthContext';
import { useSite, useToday } from './SiteContext';

/** Numbers for the sidebar badges, per tool id.
 *
 *  A tool is **absent from the result** until its call has answered, and again
 *  whenever the latest call failed. Never 0 on failure: a missing badge says
 *  "unknown", a 0 would say "nothing waiting" (spec 022 FR-103, rule 4). The
 *  attendance badge is late plus not arrived and appears only after today's
 *  late cut-off has passed (spec 023); its call is made only for an administrator; the engine would refuse
 *  it for IT, and an IT account has no Attendance link to put a badge on. */

const POLL_MS = 15_000;

export type NavBadges = Partial<Record<ToolId, number>>;

export function useNavBadges(): NavBadges {
  const { role } = useAccount();
  const today = useToday();
  const tzOffset = useSite().site?.tzOffsetMinutes;
  const [badges, setBadges] = useState<NavBadges>({});

  useEffect(() => {
    let cancelled = false;

    const set = (tool: ToolId, count: number | undefined) => {
      if (cancelled) return;
      setBadges((current) => {
        const next = { ...current };
        if (count === undefined) delete next[tool];
        else next[tool] = count;
        return next;
      });
    };

    const load = () => {
      if (role === 'admin' && tzOffset !== undefined) {
        getAttendanceBadge(today, tzOffset).then((n) => set('attendance', n), () => set('attendance', undefined));
      }
      getOpenGateAlertCount().then((n) => set('vehicles', n), () => set('vehicles', undefined));
    };

    load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [role, today, tzOffset]);

  return badges;
}
