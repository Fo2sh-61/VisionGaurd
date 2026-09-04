/** Load something from the engine, and never silently pretend it worked.
 *
 *  The pattern this replaces was everywhere:
 *
 *      useEffect(() => { void getUsers().then(setUsers); }, []);
 *
 *  `get()` throws `ApiError` when the engine is unreachable, slow, or angry.
 *  With no `.catch`, that becomes an unhandled rejection nobody sees, the
 *  state stays at its initial `[]`, and the page renders "0 people can sign
 *  in" — an assertion of fact, made from no data at all. An operator cannot
 *  tell that from a genuinely empty table.
 *
 *  This is the same problem `DataNotice` solves for unavailable subsystems,
 *  one layer down: there, the engine knows it has nothing and says so; here,
 *  the request never arrived, so only the browser knows. Both end the same
 *  way — say which it is, rather than drawing a confident zero.
 *
 *  Three states come back, and a page is expected to render all three:
 *
 *      loading   the first request is still in flight
 *      error     it failed, with a reason worth showing
 *      data      it worked; may legitimately be empty
 *
 *  `error` and `data` are deliberately not exclusive. A refresh that fails
 *  keeps the last good data on screen and puts the failure beside it, which
 *  is more useful than blanking a table an operator was reading. */

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '@/services/http';

export interface Async<T> {
  /** The last successful response, or `initial` if there has never been one. */
  data: T;
  /** Why the most recent attempt failed, or null if it did not. */
  error: string | null;
  /** True only during the first load. A background refresh does not blank
   *  the page — the data on screen is still the truth until it is replaced. */
  loading: boolean;
  /** Try again. Safe to hand straight to a button's onClick. */
  reload: () => void;
}

/** One line an operator can act on, not a stack trace.
 *
 *  `ApiError` already carries a message written for a person. Anything else
 *  reaching here is a bug in the front end, and saying so is more honest than
 *  blaming the network. */
function reason(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return 'Something went wrong loading this.';
}

/** @param refreshMs re-run `load` on this interval, for data that goes stale
 *  on its own. A page that only fetches on mount shows whatever was true when
 *  the operator arrived, and keeps showing it — the restricted-zone log gained
 *  a clip the moment somebody walked out of frame, and the only way to see it
 *  was to leave the page and come back.
 *
 *  A background refresh never blanks the page: `loading` stays false after the
 *  first load, and a failed poll leaves the last good data up with the reason
 *  beside it. So this is safe to point at a screen somebody is reading. */
export function useAsync<T>(
  load: () => Promise<T>,
  deps: unknown[],
  initial: T,
  refreshMs?: number,
): Async<T> {
  const [data, setData] = useState<T>(initial);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  // `load` is nearly always an inline arrow, so it is a new function every
  // render. Depending on it directly would re-fetch forever. The caller's
  // `deps` say when the request actually changes; this ref carries the latest
  // closure across without being one of them.
  const latest = useRef(load);
  latest.current = load;

  useEffect(() => {
    let cancelled = false;
    // `error` is not cleared here. A failed reload replaces the old message
    // below, and a successful one clears it — clearing up front would flash
    // the page back to "fine" for the length of the request.
    latest
      .current()
      .then((next) => {
        if (cancelled) return;
        setData(next);
        setError(null);
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        // The data already on screen is left alone on purpose. It was true
        // when it arrived, and blanking it tells the operator less.
        setError(reason(caught));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      // A page the operator has already navigated away from must not write
      // state, and must not overwrite the newer request's answer.
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  useEffect(() => {
    if (!refreshMs) return;
    const timer = setInterval(() => setTick((n) => n + 1), refreshMs);
    return () => clearInterval(timer);
  }, [refreshMs]);

  const reload = useCallback(() => setTick((n) => n + 1), []);

  return { data, error, loading, reload };
}
