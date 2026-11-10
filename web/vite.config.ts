import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';

/** Where the engine is listening. The dev server forwards to it. */
const ENGINE = process.env.VITE_ENGINE_ORIGIN ?? 'http://127.0.0.1:8000';

/** Every top-level path the engine serves.
 *
 *  **Why proxy at all, when the browser could just call the engine directly?**
 *
 *  The camera streams are `<img src="/cameras/x/stream">`. An image tag cannot
 *  carry an Authorization header — the only credential it can send is a
 *  cookie, and the session cookie is `SameSite=Strict`, which means the
 *  browser will not attach it to a request for a *different site*. With the
 *  page on localhost:5173 and the engine on 127.0.0.1:8000, every stream
 *  arrived with no credentials, came back 401, and rendered as a black
 *  rectangle. Detection kept working the whole time, because that happens on
 *  the server and never touches the browser — which made it look like a video
 *  problem rather than an auth one.
 *
 *  Proxying puts the engine on the same origin as the page, so the cookie is
 *  same-site and simply works. It also matches how this is deployed for real:
 *  one origin serving both, which is the arrangement `SameSite=Strict` is
 *  worth having.
 *
 *  Loosening the cookie instead would have been the wrong trade. `Lax` still
 *  excludes cross-site subresources, so it would not have fixed it; `None`
 *  would have, at the cost of requiring HTTPS and giving up the protection.
 */
const API_PATHS = [
  '/ask',
  '/attendance', '/attention', '/audit', '/auth', '/breaches', '/cameras',
  '/count', '/docs', '/enrolment', '/groups', '/healthz', '/intrusion',
  '/lost-items', '/openapi.json', '/path', '/people', '/redoc', '/settings',
  '/site', '/sources', '/stations', '/system', '/track', '/tracking', '/users', '/vehicles',
  '/weapons', '/zones',
];

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      API_PATHS.map((path) => [
        path,
        {
          target: ENGINE,
          changeOrigin: false,   // keep the Host header, so the cookie's domain matches
          ws: false,
          // MJPEG never completes by design; it must stream through rather
          // than be buffered until the response ends, which never happens.
          timeout: 0,
          proxyTimeout: 0,
        },
      ]),
    ),
  },
});
