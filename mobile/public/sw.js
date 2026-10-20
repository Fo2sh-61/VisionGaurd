// VisionGuard's service worker (spec 020, P10-FR-112 and P9-FR-101). Three jobs,
// nothing else - the third is the phone app's alone:
//
// 1. It makes the phone app installable ("Install app" / "Add to Home screen"):
//    Chrome's own install prompt wants a page with a fetch handler.
// 2. When a PAGE cannot load at all, it shows one plain page saying so,
//    instead of the browser's error. It does not guess why: away from the
//    factory that is usually the VPN, on site the network, and it says only
//    where to look.
// 3. It shows an alert notification while the phone is locked and the app is
//    closed, and a tap opens the app on that kind of alert's page. The
//    notification says only what kind, which camera and when (the engine
//    builds it that way); the details load in the app, over the private
//    network, when it is opened.
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

self.addEventListener('push', (event) => {
  let note = {};
  try {
    note = event.data ? event.data.json() : {};
  } catch (error) {
    note = {};
  }
  event.waitUntil(self.registration.showNotification(note.title || 'VisionGuard', {
    body: note.body || '',
    icon: '/icon-192.png',
    badge: '/icon-192.png',
    data: { path: note.path || '/' },
  }));
});

// Only a page of this app: a path that is not one opens the app's start.
function samePagePath(path) {
  return typeof path === 'string' && path.startsWith('/') && !path.startsWith('//') ? path : '/';
}

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = new URL(samePagePath(event.notification.data && event.notification.data.path),
                      self.location.origin).href;
  event.waitUntil((async () => {
    const open = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of open) {
      if ('focus' in client) {
        if ('navigate' in client) await client.navigate(url).catch(() => undefined);
        return client.focus();
      }
    }
    return self.clients.openWindow(url);
  })());
});
