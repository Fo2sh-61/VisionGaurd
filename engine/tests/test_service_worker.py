"""The apps' service workers (spec 020, US4, P10-FR-112).

Each one does two jobs: it makes its app installable, and when a page cannot
load at all it shows one plain page saying the site cannot be reached, without
guessing why. It must cache nothing, so an installed app can never show
yesterday's pages or pictures as if they were now.

The worker is run here in Node with a stand-in `self` and `fetch`, so what is
checked is what it does, not how it is written.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_DIR = Path(__file__).resolve().parents[2]
WORKERS = [REPO_DIR / "web" / "public" / "sw.js", REPO_DIR / "mobile" / "public" / "sw.js"]

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const handlers = {};
let cacheTouched = false;
const sandbox = {
  self: { addEventListener: (type, fn) => { handlers[type] = fn; },
          skipWaiting: () => {}, clients: { claim: async () => {} } },
  caches: new Proxy({}, { get() { cacheTouched = true; return () => Promise.resolve(); } }),
  Response, Promise, console,
  fetch: async (request) => {
    if (request.fail) throw new TypeError('Failed to fetch');
    return new Response('from the workstation', { status: 200 });
  },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), sandbox);

async function run(mode, fail) {
  let answered = null;
  handlers.fetch({ request: { mode, fail }, respondWith: (p) => { answered = p; } });
  if (answered === null) return { passedThrough: true };
  const response = await answered;
  return { status: response.status, type: response.headers.get('content-type'),
           store: response.headers.get('cache-control'), body: await response.text() };
}

(async () => {
  console.log(JSON.stringify({
    handlers: Object.keys(handlers).sort(),
    pageOnline: await run('navigate', false),
    pageOffline: await run('navigate', true),
    pictureOffline: await run('no-cors', true),
    apiOffline: await run('cors', true),
    cacheTouched,
  }));
})();
"""


@pytest.fixture(scope="module", params=WORKERS, ids=["web", "mobile"])
def worker(request, tmp_path_factory):
    harness = tmp_path_factory.mktemp("sw") / "harness.js"
    harness.write_text(HARNESS, encoding="utf-8")
    done = subprocess.run(["node", str(harness), str(request.param)],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@needs_node
class TestWhatItDoes:
    def test_it_has_a_fetch_handler_so_the_app_can_be_installed(self, worker):
        assert "fetch" in worker["handlers"]

    def test_a_page_that_loads_is_the_workstations_own(self, worker):
        assert worker["pageOnline"]["body"] == "from the workstation"

    def test_a_page_that_cannot_load_gets_the_plain_page(self, worker):
        page = worker["pageOffline"]
        assert page["status"] == 503
        assert page["type"].startswith("text/html")
        assert page["store"] == "no-store"
        assert "VisionGuard cannot be reached right now." in page["body"]
        assert "NetBird" in page["body"] and "check the network" in page["body"]
        assert "location.reload()" in page["body"]

    def test_pictures_and_engine_calls_are_never_answered_by_it(self, worker):
        assert worker["pictureOffline"] == {"passedThrough": True}
        assert worker["apiOffline"] == {"passedThrough": True}

    def test_it_caches_nothing(self, worker):
        assert worker["cacheTouched"] is False


@pytest.mark.parametrize("path", WORKERS, ids=["web", "mobile"])
def test_it_never_stores_anything_in_its_source(path):
    text = path.read_text(encoding="utf-8")
    assert "caches." not in text and "cache.put" not in text and "indexedDB" not in text


@pytest.mark.parametrize("app", ["web", "mobile"])
def test_built_apps_register_it_and_the_dev_server_does_not(app):
    main = (REPO_DIR / app / "src" / "main.tsx").read_text(encoding="utf-8")
    assert "if (import.meta.env.PROD && 'serviceWorker' in navigator)" in main
    assert "navigator.serviceWorker.register('/sw.js')" in main


# --- the phone app's notifications (spec 020, US5) -----------------------------

PUSH_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const handlers = {};
const shown = [];
const opened = [];
const sandbox = {
  self: {
    addEventListener: (type, fn) => { handlers[type] = fn; },
    skipWaiting: () => {}, location: { origin: 'https://100.81.4.7:8443' },
    registration: { showNotification: async (title, options) => { shown.push({ title, options }); } },
    clients: {
      claim: async () => {},
      matchAll: async () => [],
      openWindow: async (url) => { opened.push(url); },
    },
  },
  URL, Response, Promise, console, fetch: async () => new Response(''),
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), sandbox);

async function push(payload) {
  let work = null;
  handlers.push({ data: payload === null ? null : { json: () => JSON.parse(payload) },
                  waitUntil: (p) => { work = p; } });
  await work;
}
async function tap(path) {
  let work = null;
  handlers.notificationclick({ notification: { close: () => {}, data: { path } },
                               waitUntil: (p) => { work = p; } });
  await work;
}

(async () => {
  await push(JSON.stringify({ title: 'Possible knife', body: 'Gate 2 · 14:05', path: '/weapons' }));
  await push('not json');
  await tap('/weapons');
  await tap('https://evil.example/x');
  await tap('//evil.example/x');
  console.log(JSON.stringify({ handlers: Object.keys(handlers).sort(), shown, opened }));
})();
"""


@pytest.fixture(scope="module")
def phone_worker(tmp_path_factory):
    harness = tmp_path_factory.mktemp("sw-push") / "harness.js"
    harness.write_text(PUSH_HARNESS, encoding="utf-8")
    done = subprocess.run(["node", str(harness), str(WORKERS[1])],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@needs_node
class TestPhoneNotifications:
    def test_a_notification_shows_what_the_engine_sent(self, phone_worker):
        first = phone_worker["shown"][0]
        assert first["title"] == "Possible knife"
        assert first["options"]["body"] == "Gate 2 · 14:05"
        assert first["options"]["data"] == {"path": "/weapons"}

    def test_a_message_it_cannot_read_still_says_visionguard(self, phone_worker):
        assert phone_worker["shown"][1]["title"] == "VisionGuard"

    def test_a_tap_opens_that_page_of_this_app_and_nothing_else(self, phone_worker):
        assert phone_worker["opened"] == [
            "https://100.81.4.7:8443/weapons",
            "https://100.81.4.7:8443/",
            "https://100.81.4.7:8443/",
        ]


def test_the_console_worker_takes_no_notifications():
    """Phones get notifications; the console is the desk."""
    assert "'push'" not in WORKERS[0].read_text(encoding="utf-8")
