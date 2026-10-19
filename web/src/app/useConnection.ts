/** How this device is reaching the site, and whether it can at all (spec 020).
 *
 *  `useConnection()` is the engine's answer to `GET /connection`: whether this
 *  device is remote (anything outside the factory network) and the site's
 *  remote limits. Asked once per sign-in and again on `refreshConnection()`,
 *  which the live view calls when its stream is refused. Until the engine has
 *  answered it is null, and screens behave as on the factory network; the
 *  engine applies the limits whatever a screen does, so the worst a screen
 *  can get wrong is a label for a second.
 *
 *  `useSiteReachable()` is false after a request got no answer of any kind
 *  (`services/http.ts`). It does not guess why. */

import { useEffect, useSyncExternalStore } from 'react';
import { getConnection } from '@/services/api';
import { isSiteReachable, subscribeSiteReachable } from '@/services/http';
import type { Connection } from '@/services/wire';
import { useAuth } from './AuthContext';

let current: Connection | null = null;
/** Whose answer `current` is: a new sign-in asks again. */
let currentFor: string | null = null;
let asking: Promise<Connection | null> | null = null;
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Ask the engine again. Resolves with the answer, or null if it gave none. */
export function refreshConnection(): Promise<Connection | null> {
  if (!asking) {
    asking = getConnection()
      .then((answer) => {
        current = answer;
        listeners.forEach((listener) => listener());
        return answer;
      })
      // No answer leaves the last one standing; the site banner says the rest.
      .catch(() => current)
      .finally(() => {
        asking = null;
      });
  }
  return asking;
}

export function useConnection(): Connection | null {
  const { account } = useAuth();
  const connection = useSyncExternalStore(subscribe, () => current);
  const who = account?.id ?? null;
  // Every tile uses this; only the first one on a sign-in (or after an
  // answer that never came) asks.
  useEffect(() => {
    if (who === null) {
      current = null;
      currentFor = null;
      return;
    }
    if (currentFor !== who || current === null) {
      currentFor = who;
      void refreshConnection();
    }
  }, [who]);
  return who === null ? null : connection;
}

export function useSiteReachable(): boolean {
  return useSyncExternalStore(subscribeSiteReachable, isSiteReachable);
}
