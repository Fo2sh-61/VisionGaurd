// VisionGuard's service worker (spec 020, P10-FR-112). Two jobs, nothing else:
//
// 1. It makes the phone app installable ("Install app" / "Add to Home screen"):
//    Chrome's own install prompt wants a page with a fetch handler.
// 2. When a PAGE cannot load at all, it shows one plain page saying so,
//    instead of the browser's error. It does not guess why: away from the
//    factory that is usually the VPN, on site the network, and it says only
//    where to look.
//
// It caches NOTHING. Every request goes to the workstation as if there were no
// service worker, and that page is built here, in memory. An installed app
// must never show yesterday's pages, lists or pictures as if they were now.
//
// Served with Cache-Control: no-cache (deploy/Caddyfile), so a new version is
// picked up on the next open after an update.

const OFFLINE_PAGE = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#33705b">
<title>VisionGuard cannot be reached</title>
<style>
  :root { color-scheme: light dark; }
  body { margin: 0; min-height: 100vh; display: grid; place-items: center;
         font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
         background: #f2f5f2; color: #17201b; }
  @media (prefers-color-scheme: dark) { body { background: #121815; color: #e4eae5; } }
  main { max-width: 26rem; padding: 2rem 1.25rem; }
  h1 { font-size: 1.25rem; margin: 0 0 .75rem; }
  p { margin: 0 0 .75rem; }
  button { margin-top: .5rem; font: inherit; padding: .6rem 1.2rem; border: 0;
           border-radius: .6rem; background: #33705b; color: #fff; cursor: pointer; }
</style>
</head>
<body>
<main>
  <h1>VisionGuard cannot be reached right now.</h1>
  <p>Away from the factory, check that NetBird is switched on and connected.</p>
  <p>In the factory, check the network.</p>
  <button type="button" onclick="location.reload()">Try again</button>
</main>
</body>
</html>`;

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('fetch', (event) => {
  // Pictures, streams and every engine call go straight through, untouched.
  if (event.request.mode !== 'navigate') return;
  event.respondWith(
    fetch(event.request).catch(() => new Response(OFFLINE_PAGE, {
      status: 503,
      headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' },
    })),
  );
});
