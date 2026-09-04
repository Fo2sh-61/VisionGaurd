/** What the console can honestly show right now, and why not otherwise.
 *
 *  Every page that renders a number checks this before it draws one. The
 *  reason it has to exist: a page cannot tell an empty register from a broken
 *  one, because both arrive as zero rows. Guessing misleads in both
 *  directions — a genuinely quiet morning read as a fault, or a subsystem that
 *  never started read as "nobody came".
 *
 *  The engine used to answer that problem by returning fixtures whenever its
 *  own data was missing, so a page showed measured numbers and then silently
 *  showed invented ones the moment a camera dropped off. Intermittent is worse
 *  than permanent: a page that is always fake gets distrusted, and a page that
 *  is real until the moment it matters gets believed. The engine now returns
 *  empty and puts the reason here.
 *
 *  Fetched once, above the pages, like the school name and the camera roster —
 *  six copies of this request would be six ways to disagree about what is
 *  live. */

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { getCapabilities } from '@/services/api';
import type { Capability, DataState } from '@/services/wire';

interface CapabilityState {
  all: Capability[];
  loading: boolean;
  /** The entry for one capability key, or null before the first response. */
  of: (key: string) => Capability | null;
  /** True only when the engine says this data is measured. Unknown is false:
   *  before we have heard back, we do not claim anything is live. */
  isLive: (key: string) => boolean;
  refresh: () => void;
}

const CapabilityContext = createContext<CapabilityState | null>(null);

export function CapabilityProvider({ children }: { children: ReactNode }) {
  const [all, setAll] = useState<Capability[]>([]);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    // getCapabilities never throws — an unreachable engine comes back as one
    // 'unavailable' entry, which is the honest thing to put on the screen.
    getCapabilities()
      .then((next) => !cancelled && setAll(next))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [tick]);

  // A subsystem can come back — a camera reconnects, a model finishes loading.
  // Same cadence as the camera tally, for the same reason.
  useEffect(() => {
    const timer = setInterval(() => setTick((n) => n + 1), 30_000);
    return () => clearInterval(timer);
  }, []);

  const of = useCallback(
    (key: string) => all.find((c) => c.key === key) ?? null,
    [all],
  );

  const value = useMemo<CapabilityState>(
    () => ({
      all,
      loading,
      of,
      isLive: (key: string) => of(key)?.state === 'live',
      refresh: () => setTick((n) => n + 1),
    }),
    [all, loading, of],
  );

  return <CapabilityContext.Provider value={value}>{children}</CapabilityContext.Provider>;
}

export function useCapabilities(): CapabilityState {
  const context = useContext(CapabilityContext);
  if (!context) throw new Error('useCapabilities must be used inside <CapabilityProvider>');
  return context;
}

/** One capability, for the page that renders it. */
export function useCapability(key: string): Capability | null {
  return useCapabilities().of(key);
}

export type { Capability, DataState };
