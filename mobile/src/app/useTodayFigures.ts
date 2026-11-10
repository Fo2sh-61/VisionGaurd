import { useAccount } from '@/app/AuthContext';
import { useCapability, type Capability } from '@/app/CapabilityContext';
import { useLanguage } from '@/app/LanguageContext';
import { useSite, useToday } from '@/app/SiteContext';
import { useAsync } from '@/app/useAsync';
import { useChoice, useGroupNames, usePlaces } from '@/app/useOptions';
import { getAttendance, getBreaches, getCount, getVehicleSummary, getZones } from '@/services/api';
import { formatCount } from '@/services/format';

/** Home's "Today so far": four figures, each exactly what its own tool shows.
 *
 *  Spec 015 (P13-FR-046). Every figure is one call the console already makes
 *  from that tool's page, with the tool's own default question - the first
 *  group today, the first place right now - so tapping the tile opens the tool
 *  on the same question and the same number. Nothing is added up, estimated or
 *  remembered here.
 *
 *  Each figure fails on its own. A feature that is not running says so, in
 *  place of its number; one that could not be reached says that; and while the
 *  first answer is on its way it says it is checking. None of those is ever a
 *  zero. */

export type FigureState = 'checking' | 'ready' | 'off' | 'failed';

export interface TodayFigure {
  id: 'arrived' | 'inView' | 'carsIn' | 'restricted';
  state: FigureState;
  /** The engine's figure, ready to print. Null when there is no figure. */
  value: string | null;
  /** The line under it: the engine's own wording, or why there is no figure. */
  detail: string;
  /** Warn-coloured detail (late arrivals, paused zones, demo data). */
  warn: boolean;
  /** The tool, asked the same question. */
  to: string;
}

const REFRESH_MS = 30_000;

function stateOf(capability: Capability | null, loading: boolean, error: string | null,
                 hasData: boolean): FigureState {
  if (capability?.state === 'unavailable') return 'off';
  if (error && !hasData) return 'failed';
  if (!hasData) return loading || !capability ? 'checking' : 'failed';
  return 'ready';
}

export function useTodayFigures(): TodayFigure[] {
  const { language, t } = useLanguage();
  const { error: engineError } = useSite();
  const today = useToday();
  // Spec 022: attendance is administrator-only, and the engine refuses it to
  // IT. Asking anyway would only show IT a figure that always says "failed".
  const isAdmin = useAccount().role === 'admin';
  const group = useChoice(useGroupNames(), '');
  const place = useChoice(usePlaces(), '');

  const attendanceCap = useCapability('attendance');
  const countCap = useCapability('count');
  const vehiclesCap = useCapability('vehicles');
  const breachesCap = useCapability('breaches');

  const attendance = useAsync(
    () => (isAdmin && group ? getAttendance({ mode: 'group', group, date: today }, language) : Promise.resolve(null)),
    [isAdmin, group, today, language], null, REFRESH_MS,
  );
  const count = useAsync(
    () => (place ? getCount({ place, when: 'Right now' }, language) : Promise.resolve(null)),
    [place, language], null, REFRESH_MS,
  );
  const gate = useAsync(() => getVehicleSummary(), [], null, REFRESH_MS);
  const breaches = useAsync(() => getBreaches('today', language), [language], null, REFRESH_MS);
  const zones = useAsync(() => getZones(), [], null, REFRESH_MS);

  // With the engine gone, every figure says so - the last numbers are not
  // shown as if they were still true.
  const down = engineError !== null;
  const words = (state: FigureState, capability: Capability | null) =>
    state === 'off'
      ? capability?.reason ?? t('phone.figure.off')
      : state === 'failed'
        ? t('phone.figure.failed')
        : t('phone.figure.checking');
  const demo = (capability: Capability | null) => capability?.state === 'demo';

  // --- arrived -------------------------------------------------------------
  const arrivedState: FigureState = down
    ? 'failed'
    : stateOf(attendanceCap, attendance.loading, attendance.error, attendance.data !== null);
  const arrived: TodayFigure = {
    id: 'arrived',
    state: arrivedState,
    value: arrivedState === 'ready' ? attendance.data!.heading : null,
    detail: arrivedState === 'ready'
      ? demo(attendanceCap)
        ? t('state.demoData')
        : attendance.data!.stats.map((s) => `${s.label} ${s.value}`).join(' · ')
      : words(arrivedState, attendanceCap),
    warn: arrivedState !== 'ready' || demo(attendanceCap),
    to: `/attendance?mode=group&subject=${encodeURIComponent(group)}&date=${today}`,
  };

  // --- in view -------------------------------------------------------------
  const inViewState: FigureState = down
    ? 'failed'
    : stateOf(countCap, count.loading, count.error, count.data !== null);
  const inView: TodayFigure = {
    id: 'inView',
    state: inViewState,
    value: inViewState === 'ready' ? count.data!.heading : null,
    // `sub` carries the percentage only when a capacity is set - the engine
    // decides that, never this screen.
    detail: inViewState === 'ready'
      ? demo(countCap) ? t('state.demoData') : count.data!.sub
      : words(inViewState, countCap),
    warn: inViewState !== 'ready' || demo(countCap),
    to: `/counting?place=${encodeURIComponent(place)}&when=${encodeURIComponent('Right now')}`,
  };

  // --- cars in -------------------------------------------------------------
  const g = gate.data;
  const carsState: FigureState = down
    ? 'failed'
    : vehiclesCap?.state === 'unavailable' || (g !== null && g.entered === null && g.reason)
      ? 'off'
      : stateOf(vehiclesCap, gate.loading, gate.error, g !== null);
  const carsIn: TodayFigure = {
    id: 'carsIn',
    state: carsState,
    value: carsState === 'ready'
      ? g!.entered === null ? '—' : formatCount(g!.entered, language)
      : null,
    detail: carsState === 'ready'
      ? demo(vehiclesCap)
        ? t('state.demoData')
        : g!.camerasReading === null
          ? g!.camerasNote ?? ''
          : t('phone.home.gateCameras', { count: formatCount(g!.camerasReading, language) })
      : carsState === 'off'
        ? g?.reason ?? vehiclesCap?.reason ?? t('phone.figure.off')
        : words(carsState, vehiclesCap),
    warn: carsState !== 'ready' || demo(vehiclesCap),
    to: '/vehicles',
  };

  // --- restricted areas ----------------------------------------------------
  const restrictedState: FigureState = down
    ? 'failed'
    : stateOf(breachesCap, breaches.loading, breaches.error, breaches.data !== null);
  const paused = zones.data ? zones.data.filter((z) => !z.enabled).length : null;
  const clips = breaches.data?.length ?? 0;
  const restricted: TodayFigure = {
    id: 'restricted',
    state: restrictedState,
    value: restrictedState === 'ready'
      ? clips === 1 ? t('phone.home.clipsTodayOne') : t('phone.home.clipsToday', { count: formatCount(clips, language) })
      : null,
    detail: restrictedState === 'ready'
      ? demo(breachesCap)
        ? t('state.demoData')
        : paused === null
          ? ''
          : paused === 0
            ? t('phone.home.zonesAllOn')
            : paused === 1
              ? t('phone.home.zonesPausedOne')
              : t('phone.home.zonesPaused', { count: formatCount(paused, language) })
      : words(restrictedState, breachesCap),
    warn: restrictedState !== 'ready' || demo(breachesCap) || (paused ?? 0) > 0,
    to: '/intrusion',
  };

  return isAdmin ? [arrived, inView, carsIn, restricted] : [inView, carsIn, restricted];
}
