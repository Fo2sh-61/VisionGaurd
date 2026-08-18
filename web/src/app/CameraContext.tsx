/** The camera roster — which cameras exist, and what state they are in.
 *
 *  The design principle here is worth stating, because getting it wrong is why
 *  the tiles used to disappear:
 *
 *      Which cameras exist is INFRASTRUCTURE. What they are showing is DATA.
 *
 *  Pages used to take their camera grid from whatever their own query returned,
 *  so a failed attendance lookup — or an engine restart — erased the cameras
 *  from the screen entirely. That is exactly backwards. An operator opening
 *  Intrusion during an outage needs to see their eight cameras sitting there
 *  saying NO SIGNAL. A blank page tells them nothing and looks like the console
 *  is broken rather than the cameras.
 *
 *  So the roster is fetched once here, cached in localStorage, and survives
 *  every kind of failure. When the engine cannot be reached we keep showing the
 *  last known cameras and mark every one of them offline — which is both
 *  honest and the most useful thing we can say. */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { getCameras } from '@/services/api';
import type { Camera } from '@/types';

/** How often the roster refreshes. State changes (a camera dropping) matter
 *  within a few seconds; the roster itself changes very rarely. */
const ROSTER_REFRESH_MS = 5_000;

/** Survives a page reload, so the very first paint after a refresh during an
 *  outage still shows the cameras rather than an empty page. */
const CACHE_KEY = 'vg.cameras';

interface CameraState {
  /** Every configured camera, whatever the engine's condition. */
  cameras: Camera[];
  /** True when the engine cannot be reached. Cameras are still listed. */
  degraded: boolean;
  /** True before the first response, when there is no cache to fall back on. */
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

const CameraContext = createContext<CameraState | null>(null);

function readCache(): Camera[] {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeCache(cameras: Camera[]): void {
  try {
    // Cache identity only — name, id, zone. Never boxes or timestamps, which
    // would come back stale and claim to be current on the next page load.
    localStorage.setItem(
      CACHE_KEY,
      JSON.stringify(
        cameras.map((c) => ({ id: c.id, name: c.name, status: c.status })),
      ),
    );
  } catch {
    /* storage full or blocked; the cache is an optimisation, not a requirement */
  }
}

/** Everything we know about a camera we currently cannot reach. */
function asOffline(camera: Camera): Camera {
  return {
    ...camera,
    offline: true,
    status: 'No signal',
    // Drop overlays: they described a frame we can no longer see, and drawing
    // them over a dead tile would assert something we cannot support.
    boxes: [],
    time: undefined,
  };
}

export function CameraProvider({ children }: { children: ReactNode }) {
  const [cameras, setCameras] = useState<Camera[]>(() => readCache().map(asOffline));
  const [degraded, setDegraded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  // Keeps the last good roster available to the failure path without making
  // the polling effect re-run every time the cameras change.
  const lastGood = useRef<Camera[]>([]);

  useEffect(() => {
    let cancelled = false;

    getCameras()
      .then((next) => {
        if (cancelled) return;
        lastGood.current = next;
        setCameras(next);
        writeCache(next);
        setDegraded(false);
        setError(null);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        // The engine is unreachable. Keep the roster, mark it all offline.
        // Emptying the list here is what made the tiles vanish.
        setCameras((current) =>
          (lastGood.current.length ? lastGood.current : current).map(asOffline),
        );
        setDegraded(true);
        setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [tick]);

  useEffect(() => {
    const timer = setInterval(() => setTick((n) => n + 1), ROSTER_REFRESH_MS);
    return () => clearInterval(timer);
  }, []);

  const refresh = useCallback(() => setTick((n) => n + 1), []);

  const value = useMemo<CameraState>(
    () => ({ cameras, degraded, loading, error, refresh }),
    [cameras, degraded, loading, error, refresh],
  );

  return <CameraContext.Provider value={value}>{children}</CameraContext.Provider>;
}

export function useCameras(): CameraState {
  const context = useContext(CameraContext);
  if (!context) throw new Error('useCameras must be used inside <CameraProvider>');
  return context;
}

/** The cameras a page should show, preferring live detail where it exists.
 *
 *  `fromQuery` is what the page's own request returned — richer, because it
 *  carries zones and detections for that feature. The roster is the fallback,
 *  so the grid is populated even when the query failed or returned nothing.
 *  The union means adding a camera makes it appear on every page at once,
 *  without any page knowing that happened. */
export function useCameraGrid(fromQuery?: Camera[]): Camera[] {
  const { cameras } = useCameras();

  return useMemo(() => {
    if (!fromQuery?.length) return cameras;

    const enriched = new Map(fromQuery.map((c) => [c.id, c]));
    return cameras.map((c) => enriched.get(c.id) ?? c);
  }, [cameras, fromQuery]);
}
