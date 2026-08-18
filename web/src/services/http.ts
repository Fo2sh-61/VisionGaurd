/** Talking to the engine.
 *
 *  One fetch wrapper so every call gets the same timeout, the same error shape
 *  and the same degraded behaviour. Pages should never call `fetch` directly.
 *
 *  Base URL comes from `VITE_API_BASE`; create `web/.env.local` with
 *
 *      VITE_API_BASE=http://127.0.0.1:8000
 *
 *  and start the engine with `python engine/tools/serve.py`. */

const BASE = (import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000').replace(/\/$/, '');

/** How long before we give up. Lost-item search runs over stored footage and is
 *  allowed a minute; everything else should be quick or is broken. */
const DEFAULT_TIMEOUT_MS = 15_000;
export const SEARCH_TIMEOUT_MS = 90_000;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly retryable: boolean,
    readonly detail?: string,
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
  const url = new URL(BASE + path);
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
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  // Let a caller cancel too — the lost-item search is long enough that the user
  // may navigate away mid-flight.
  if (signal) signal.addEventListener('abort', () => controller.abort(), { once: true });

  try {
    // FormData carries its own multipart Content-Type, complete with the
    // boundary. Setting the header by hand omits the boundary and the server
    // rejects the body, so let the browser write it.
    const isForm = typeof FormData !== 'undefined' && body instanceof FormData;

    const response = await fetch(buildUrl(path, query), {
      method,
      headers: body && !isForm ? { 'Content-Type': 'application/json' } : undefined,
      body: isForm ? (body as FormData) : body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });

    if (!response.ok) {
      let message = `${method} ${path} failed (${response.status})`;
      let detail: string | undefined;
      try {
        const problem = await response.json();
        detail = problem?.detail ?? problem?.error;
        if (typeof detail === 'string') message = detail;
      } catch {
        /* a non-JSON error body is not worth failing over */
      }
      // 5xx and 429 are worth retrying; a 404 or a validation error is not.
      const retryable = response.status >= 500 || response.status === 429;
      throw new ApiError(message, response.status, retryable, detail);
    }

    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError(`${path} timed out`, 0, true);
    }
    // Network-level failure: the engine is not running, or CORS blocked it.
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

/** Absolute URL for a snapshot, clip or stream path the engine handed back. */
export function assetUrl(path: string | null | undefined): string | undefined {
  if (!path) return undefined;
  return /^https?:/.test(path) ? path : BASE + path;
}

export const apiBase = BASE;
