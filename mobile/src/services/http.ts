/** Talking to the engine.
 *
 *  One fetch wrapper so every call gets the same timeout, the same error shape
 *  and the same degraded behaviour. Pages should never call `fetch` directly.
 *
 *  Base URL comes from `VITE_API_BASE`; create `web/.env.local` with
 *
 *      VITE_API_BASE=http://127.0.0.1:8001
 *
 *  and start the engine with `python engine/tools/serve.py`. */

import { translate } from '@/i18n';

/** Where the engine is, from the browser's point of view.
 *
 *  **Empty by default, and that is deliberate.** An empty base means every
 *  request is same-origin and goes through the dev server's proxy (see
 *  `vite.config.ts`), which forwards it to the engine.
 *
 *  Pointing this straight at `http://127.0.0.1:8001` works for JSON — those
 *  calls carry an Authorization header — but silently breaks the camera
 *  streams. An `<img src=...>` cannot send a header, so its only credential
 *  is the session cookie, and that cookie is `SameSite=Strict`: the browser
 *  will not attach it to a *different site*. Every stream came back 401 and
 *  drew a black rectangle, while detection carried on working because it
 *  never touches the browser at all.
 *
 *  Set `VITE_API_BASE` only if you deliberately want to talk to an engine on
 *  another origin, and expect the live views to be blank if you do. */
const BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '');

/** The one sentence for "the front is up, the engine is not". In the reader's
 *  language: http.ts has no React context, but LanguageContext keeps the
 *  page's `lang` attribute current. */
function engineNotRunning(): string {
  const lang = document.documentElement.lang === 'ar' ? 'ar' : 'en';
  return translate(lang, 'state.engineNotRunning');
}

/** How long before we give up. Everything should be quick or is broken:
 *  the lost-bag search that once needed ninety seconds now starts a job and
 *  returns at once, so nothing is left that waits on a long answer. */
const DEFAULT_TIMEOUT_MS = 15_000;

/** The session token, held in memory for the life of the page.
 *
 *  Deliberately **not** in localStorage. Anything in localStorage is readable
 *  by any script that ends up on the page, and this token is a working
 *  session for a system holding face data for children. The engine also sets
 *  an HttpOnly cookie, which is what survives a refresh and what the MJPEG
 *  `<img src=...>` streams travel on — a script cannot read that one.
 *
 *  So: the variable below is a convenience for the Authorization header, and
 *  losing it on refresh costs nothing, because `/auth/me` re-establishes the
 *  session from the cookie. */
let sessionToken: string | null = null;

export function setSessionToken(token: string | null): void {
  sessionToken = token;
}

/** Called when the engine says 401 on a request we thought was authenticated.
 *  The app subscribes so it can drop straight back to the sign-in screen
 *  rather than rendering a page full of "could not load". */
type Unauthorised = () => void;
let onUnauthorised: Unauthorised | null = null;

export function setUnauthorisedHandler(handler: Unauthorised | null): void {
  onUnauthorised = handler;
}

/* ---------- can the site be reached at all (spec 020) ---------- */

/** False after a request got no answer of any kind - no page, no error page -
 *  and true again after the next one that did. Away from the factory that is
 *  the VPN being off or the factory's internet being down; on site, the
 *  network. It never guesses which: the page says only that the site cannot
 *  be reached. A 502 from the HTTPS front is an answer (the engine is down,
 *  which `engineNotRunning` says), so it counts as reachable. */
let siteReachable = true;
const reachableListeners = new Set<() => void>();

function setSiteReachable(value: boolean): void {
  if (siteReachable === value) return;
  siteReachable = value;
  reachableListeners.forEach((listener) => listener());
}

export function isSiteReachable(): boolean {
  return siteReachable;
}

export function subscribeSiteReachable(listener: () => void): () => void {
  reachableListeners.add(listener);
  return () => {
    reachableListeners.delete(listener);
  };
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly retryable: boolean,
    readonly detail?: string,
    /** The engine's whole error body, for the few answers that carry more
     *  than a sentence - a 423 sign-in carries `lockedUntil`. */
    readonly body?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  /** True when the engine could not be reached at all, as opposed to reached
   *  and refused. The UI shows a different message for each. */
  get offline(): boolean {
    return this.status === 0;
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  timeoutMs?: number;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  // The second argument is not optional here. `BASE` is empty by default so
  // that requests are same-origin, which makes `BASE + path` a relative path
  // like "/auth/login" - and `new URL()` throws a TypeError on a relative URL
  // with no base to resolve it against.
  //
  // That throw happened inside the request's try block, was not an ApiError
  // and not an AbortError, and so fell through to the branch that reports
  // "Cannot reach the engine. Is it running?". The engine was running, and
  // answering: no request was ever made. Every call in the app failed this
  // way, including sign-in.
  //
  // `window.location.origin` resolves a relative path against the page, which
  // is exactly where the dev-server proxy and a same-origin deployment both
  // want it to go. An absolute `BASE` still wins, because a base argument is
  // ignored when the first argument is already absolute.
  const url = new URL(BASE + path, window.location.origin);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, query, timeoutMs = DEFAULT_TIMEOUT_MS, signal } = options;

  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  // Let a caller cancel too — the lost-item search is long enough that the user
  // may navigate away mid-flight.
  if (signal) signal.addEventListener('abort', () => controller.abort(), { once: true });

  try {
    // FormData carries its own multipart Content-Type, complete with the
    // boundary. Setting the header by hand omits the boundary and the server
    // rejects the body, so let the browser write it.
    const isForm = typeof FormData !== 'undefined' && body instanceof FormData;

    const headers: Record<string, string> = {};
    if (body && !isForm) headers['Content-Type'] = 'application/json';
    if (sessionToken) headers.Authorization = `Bearer ${sessionToken}`;

    const response = await fetch(buildUrl(path, query), {
      method,
      headers: Object.keys(headers).length ? headers : undefined,
      body: isForm ? (body as FormData) : body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
      // Send the session cookie. The engine is on another origin in
      // development, so without this the cookie never leaves the browser and
      // a page refresh would look like being signed out.
      credentials: 'include',
    });
    setSiteReachable(true);

    if (!response.ok) {
      let message = `${method} ${path} failed (${response.status})`;
      let detail: string | undefined;
      let problem: unknown;
      try {
        problem = await response.json();
        const p = problem as { detail?: string; error?: string } | null;
        detail = p?.detail ?? p?.error;
        if (typeof detail === 'string') message = detail;
      } catch {
        /* a non-JSON error body is not worth failing over */
      }
      // The session went away - expired, signed out elsewhere, or the
      // account was disabled. Handled in one place so every page does not
      // need its own "am I still signed in" branch.
      if (response.status === 401 && !path.startsWith('/auth/login')) {
        sessionToken = null;
        onUnauthorised?.();
      }

      // The HTTPS front answered for an engine that is not there: stopped,
      // or refused to start under strict mode. The engine's own 503s carry a
      // reason in `detail` and keep it; this is only the bare gateway answer.
      if ([502, 503, 504].includes(response.status) && detail === undefined) {
        message = engineNotRunning();
      }

      // 5xx and 429 are worth retrying; a 404 or a validation error is not.
      const retryable = response.status >= 500 || response.status === 429;
      throw new ApiError(message, response.status, retryable, detail, problem);
    }

    if (response.status === 204) return undefined as T;

    try {
      return (await response.json()) as T;
    } catch {
      // A 200 that is not JSON almost always means the dev server answered
      // instead of the engine: with no proxy configured, Vite falls back to
      // serving index.html for any unknown path, so `/auth/login` returns the
      // web page with a cheerful 200.
      //
      // This used to fall through to the network-error branch below and say
      // "Cannot reach the engine. Is it running?" - which sent people to look
      // at an engine that was running perfectly. Say what actually happened.
      const prefix = `/${path.replace(/^\//, '').split('/')[0]}`;
      throw new ApiError(
        `The engine did not answer — the dev server did, for ${prefix}. `
        + `Two causes, in the order they happen: ${prefix} may be missing from `
        + 'API_PATHS in web/vite.config.ts (a new endpoint the proxy has never '
        + 'been told about), or the dev server is running with an older copy of '
        + 'that list. Add it if absent, then restart `npm run dev` either way — '
        + 'Vite reloads source on save but never its own proxy settings.',
        response.status,
        false,
        `${method} ${path} returned ${response.headers.get('content-type') ?? 'no content-type'}`,
      );
    }
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === 'AbortError') {
      // Its own timer, not a page that went away: nothing came back in time.
      if (timedOut) setSiteReachable(false);
      throw new ApiError(`${path} timed out`, 0, true);
    }
    // Network-level failure: the engine is not running, or CORS blocked it.
    setSiteReachable(false);
    throw new ApiError(
      'Cannot reach the engine. Is it running?',
      0,
      true,
      error instanceof Error ? error.message : undefined,
    );
  } finally {
    clearTimeout(timer);
  }
}

export const get = <T>(path: string, query?: RequestOptions['query'], timeoutMs?: number) =>
  request<T>(path, { query, timeoutMs });

export const post = <T>(path: string, body?: unknown, query?: RequestOptions['query'], timeoutMs?: number) =>
  request<T>(path, { method: 'POST', body, query, timeoutMs });

export const patch = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'PATCH', body });

export const del = <T>(path: string, query?: RequestOptions['query']) =>
  request<T>(path, { method: 'DELETE', query });

/** Multipart upload. Embedding a photo runs two models on the CPU, so this gets
 *  a longer leash than an ordinary call. */
export const postFile = <T>(path: string, file: Blob, filename = 'photo.jpg') => {
  const form = new FormData();
  form.append('file', file, filename);
  return request<T>(path, { method: 'POST', body: form, timeoutMs: 30_000 });
};

/** Fetch a file the engine builds, and hand it to the browser to save.
 *
 *  `request()` cannot do this: it parses every reply as JSON, and a CSV is
 *  not one. This carries the same session — the Authorization header **and**
 *  the cookie — because a bare `fetch` sends neither to another origin, which
 *  is a 401 the moment the engine is not being proxied. */
export async function download(
  path: string,
  options: { method?: 'GET' | 'POST'; query?: RequestOptions['query']; fallbackName: string },
): Promise<void> {
  const headers: Record<string, string> = {};
  if (sessionToken) headers.Authorization = `Bearer ${sessionToken}`;

  const response = await fetch(buildUrl(path, options.query), {
    method: options.method ?? 'GET',
    headers: Object.keys(headers).length ? headers : undefined,
    credentials: 'include',
  });

  if (!response.ok) {
    let message = `Download failed (${response.status})`;
    try {
      const problem = await response.json();
      if (typeof problem?.detail === 'string') message = problem.detail;
    } catch {
      /* a non-JSON error body is not worth failing over */
    }
    if (response.status === 401) {
      sessionToken = null;
      onUnauthorised?.();
    }
    throw new ApiError(message, response.status, response.status >= 500);
  }

  // Use the filename the engine chose, so the file is named after what is in
  // it rather than after the endpoint.
  const disposition = response.headers.get('Content-Disposition') ?? '';
  const named = /filename="([^"]+)"/.exec(disposition)?.[1];
  const href = URL.createObjectURL(await response.blob());

  const link = document.createElement('a');
  link.href = href;
  link.download = named ?? options.fallbackName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoking immediately can cancel the download in some browsers.
  setTimeout(() => URL.revokeObjectURL(href), 10_000);
}

/** Absolute URL for a snapshot, clip or stream path the engine handed back. */
export function assetUrl(path: string | null | undefined): string | undefined {
  if (!path) return undefined;
  return /^https?:/.test(path) ? path : BASE + path;
}

export const apiBase = BASE;
