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
                          capture_output=True, text=True, timeout=60)
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
