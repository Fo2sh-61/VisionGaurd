/** Who and when the school is.
 *
 *  The chrome and several pages need the school's name, today's date and the
 *  live camera tally before they can render anything. Fetching that in each of
 *  them would mean six copies of the same request and six ways to disagree
 *  about what "today" is, so it is fetched once here.
 *
 *  `today` is the SCHOOL's date, from the engine. A laptop with a wrong clock,
 *  or a parent's phone in another timezone, must not decide which day an
 *  attendance register belongs to. */

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { getSite } from '@/services/api';
import { formatLongDate, formatTime } from '@/services/format';
import type { SiteInfo } from '@/services/wire';
import { useLanguage } from '@/app/LanguageContext';

interface SiteState {
  site: SiteInfo | null;
  /** True until the first response lands. Chrome renders placeholders. */
  loading: boolean;
  /** Set when the engine cannot be reached; the UI says so rather than
   *  silently showing stale or invented numbers. */
  error: string | null;
  /** "Wednesday, July 29, 2026 · 8:47am" */
  todayLabel: string;
  refresh: () => void;
}

const SiteContext = createContext<SiteState | null>(null);

export function SiteProvider({ children }: { children: ReactNode }) {
  const { language } = useLanguage();
  const [site, setSite] = useState<SiteInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getSite()
      .then((next) => {
        if (cancelled) return;
        setSite(next);
        setError(null);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tick]);

  // The camera tally in the top bar goes stale quickly. Re-fetch periodically
  // so an operator does not see "192 online" for an hour after one drops.
  useEffect(() => {
    const timer = setInterval(() => setTick((n) => n + 1), 30_000);
    return () => clearInterval(timer);
  }, []);

  const value = useMemo<SiteState>(() => {
    const todayLabel = site
      ? `${formatLongDate(site.today, language)} · ${formatTime({
          utc: new Date().toISOString(),
          tzOffsetMinutes: site.tzOffsetMinutes,
        }, language)}`
      : '';
    return {
      site,
      loading,
      error,
      todayLabel,
      refresh: () => setTick((n) => n + 1),
    };
  }, [site, loading, error]);

  return <SiteContext.Provider value={value}>{children}</SiteContext.Provider>;
}

export function useSite(): SiteState {
  const context = useContext(SiteContext);
  if (!context) throw new Error('useSite must be used inside <SiteProvider>');
  return context;
}

/**
 * The site's name, or '' when nobody has set one. A deployment fills in
 * `site_name` in engine.yaml; the product ships blank, so callers must render
 * nothing rather than an empty line where a name would be.
 */
export function useSiteName(): string {
  return useSite().site?.name?.trim() ?? '';
}

/** The school's today as an ISO date — the default for every date picker. */
export function useToday(): string {
  const { site } = useSite();
  return site?.today ?? new Date().toISOString().slice(0, 10);
}
