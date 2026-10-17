"""The HTTPS front, `deploy/Caddyfile`, checked as text (spec 016, plan A).

Caddy is not installed on a development machine or in CI, so the file is read
and parsed here. The checks that matter most are the drift guards: a new page
in either app must not be mistaken for a media address, and a new engine route
must not be forgotten by the proxy. Both used to be impossible to notice until
a reload on site showed the wrong thing.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = ENGINE_DIR.parent
sys.path.insert(0, str(ENGINE_DIR))

CADDYFILE = REPO_DIR / "deploy" / "Caddyfile"


# --- a small Caddyfile reader ----------------------------------------------

class Block:
    def __init__(self, words: list[str]):
        self.words = words
        self.children: list[Block] = []

    def find(self, *words: str) -> list["Block"]:
        """Every descendant whose line starts with these words."""
        out = []
        for child in self.children:
            if child.words[: len(words)] == list(words):
                out.append(child)
            out.extend(child.find(*words))
        return out

    def lines(self) -> list[list[str]]:
        out = []
        for child in self.children:
            out.append(child.words)
            out.extend(child.lines())
        return out


def parse(text: str) -> Block:
    top = Block([])
    stack = [top]
    for raw in text.splitlines():
        line = re.sub(r"(^|\s)#.*$", "", raw).strip()
        if not line:
            continue
        words = re.findall(r'"[^"]*"|\S+', line)
        words = [w.strip('"') for w in words]
        if words == ["}"]:
            stack.pop()
            continue
        opens = words[-1] == "{"
        node = Block(words[:-1] if opens else words)
        stack[-1].children.append(node)
        if opens:
            stack.append(node)
    assert len(stack) == 1, "unbalanced braces in the Caddyfile"
    return top


@pytest.fixture(scope="module")
def caddy() -> Block:
    return parse(CADDYFILE.read_text(encoding="utf-8"))


def _matcher(caddy: Block, name: str) -> Block:
    found = caddy.find(f"@{name}")
    assert found, f"no @{name} matcher"
    return found[0]


def _paths(block: Block, *, negated: bool = False) -> list[str]:
    """The paths a matcher lists: `@name path …` or `path …` inside its block."""
    out = []
    for words in [block.words[1:]] + block.lines():
        if negated and words[:2] == ["not", "path"]:
            out += words[2:]
        elif not negated and words[:1] == ["path"]:
            out += words[1:]
    return out


def matches(pattern: str, path: str) -> bool:
    """Caddy's path matcher: `*` only at the start and/or the end."""
    pattern, path = pattern.lower(), path.lower()
    if pattern.startswith("*") and pattern.endswith("*") and len(pattern) > 1:
        return pattern[1:-1] in path
    if pattern.startswith("*"):
        return path.endswith(pattern[1:])
    if pattern.endswith("*"):
        return path.startswith(pattern[:-1])
    return path == pattern


def _is(patterns: list[str], path: str) -> bool:
    return any(matches(p, path) for p in patterns)


# --- the paths on each side ------------------------------------------------

def page_paths(app: str) -> list[str]:
    text = (REPO_DIR / app / "src" / "app" / "routes.tsx").read_text(encoding="utf-8")
    paths = ["/"]
    for p in re.findall(r'path="([^"]+)"', text):
        if p == "*":
            continue
        p = "/" + p.lstrip("/")
        paths.append(re.sub(r":\w+", "someone", p))
    assert len(paths) > 10, f"found too few pages in {app}"
    return paths


def engine_paths() -> list[str]:
    from vg.api.app import app
    return sorted({r.path for r in app.routes})


def sample(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "abc", path)


MEDIA = re.compile(r"(/clip|/snapshot|/stream)$|^/path/legs/")


# --- the drift guards ------------------------------------------------------

class TestDrift:
    @pytest.mark.parametrize("app", ["web", "mobile"])
    def test_no_page_is_a_media_address(self, caddy, app):
        media = _paths(_matcher(caddy, "page"), negated=True)
        assert media, "the page matcher lists no media addresses"
        wrong = [p for p in page_paths(app) if _is(media, p)]
        assert not wrong, f"{app} pages that would reach the engine: {wrong}"

    def test_every_media_route_is_a_media_address(self, caddy):
        media = _paths(_matcher(caddy, "page"), negated=True)
        routes = [p for p in engine_paths() if MEDIA.search(p)]
        assert len(routes) >= 6
        missed = [p for p in routes if not _is(media, sample(p))]
        assert not missed, f"media routes a page load would turn into the app: {missed}"

    def test_every_engine_route_is_proxied(self, caddy):
        api = _paths(_matcher(caddy, "api"))
        missed = [p for p in engine_paths() if not _is(api, sample(p))]
        assert not missed, f"engine routes the front does not proxy: {missed}"

    @pytest.mark.parametrize("path", ["/connection", "/connection/x", "/push", "/push/x"])
    def test_spec_020s_paths_are_proxied(self, caddy, path):
        assert _is(_paths(_matcher(caddy, "api")), path)

    def test_a_page_load_needs_html_in_accept(self, caddy):
        page = _matcher(caddy, "page")
        assert ["header", "Accept", "*text/html*"] in page.lines()


# --- the shape of the front ------------------------------------------------

class TestSites:
    def _site(self, caddy, port):
        sites = [b for b in caddy.children if b.words and b.words[0] == f":{port}"]
        assert len(sites) == 1, f"expected one :{port} site"
        return sites[0]

    def test_console_on_443_and_phone_on_8443(self, caddy):
        assert any("web/dist" in w for w in self._site(caddy, 443).lines()[0])
        assert any("mobile/dist" in w for w in self._site(caddy, 8443).lines()[0])

    def test_no_plain_http(self, caddy):
        assert not [b for b in caddy.children if b.words and b.words[0] in (":80", "http://")]
        glob = caddy.children[0]
        assert glob.words == [], "the global options block must come first"
        assert ["auto_https", "off"] in glob.lines()

    def test_http2_and_never_http3(self, caddy):
        assert ["protocols", "h1", "h2"] in caddy.children[0].lines()

    def test_the_proxy_streams_and_sets_the_real_address(self, caddy):
        proxy = caddy.find("reverse_proxy")
        assert len(proxy) == 1 and proxy[0].words[1] == "127.0.0.1:8000"
        lines = proxy[0].lines()
        assert ["flush_interval", "-1"] in lines
        assert ["header_up", "X-Forwarded-For", "{remote_host}"] in lines

    def test_the_site_certificate_is_used(self, caddy):
        tls = caddy.find("tls")
        assert tls and tls[0].words[1:] == [
            "C:/VisionGuard/data/tls/site.crt", "C:/VisionGuard/data/tls/site.key"]


class TestCaching:
    def _handle(self, caddy, name):
        found = caddy.find("handle", f"@{name}")
        assert found, f"no handle for @{name}"
        return found[0].lines()

    def test_a_page_load_is_index_html_and_never_cached(self, caddy):
        lines = self._handle(caddy, "page")
        assert ["rewrite", "*", "/index.html"] in lines
        assert ["header", "Cache-Control", "no-cache"] in lines

    def test_hashed_assets_are_kept_a_year(self, caddy):
        assert _paths(_matcher(caddy, "assets")) == ["/assets/*"]
        lines = self._handle(caddy, "assets")
        assert ["header", "Cache-Control", "public, max-age=31536000, immutable"] in lines

    def test_everything_else_including_the_manifest_is_never_cached(self, caddy):
        # The last handle serves manifest.webmanifest, sw.js and the
        # index.html fallback. `no-cache` is what lets an installed app pick
        # up an update on its next open.
        last = [b for b in caddy.find("handle") if b.words == ["handle"]]
        assert len(last) == 1
        lines = last[0].lines()
        assert ["header", "Cache-Control", "no-cache"] in lines
        assert ["try_files", "{path}", "/index.html"] in lines


class TestLog:
    def test_to_the_logs_folder_ten_by_ten_megabytes(self, caddy):
        glob = caddy.children[0]
        out = glob.find("output", "file")
        assert out and out[0].words[2] == "C:/VisionGuard/logs/front.log"
        lines = out[0].lines()
        assert ["roll_size", "10MiB"] in lines and ["roll_keep", "10"] in lines


class TestEngineBehindTheFront:
    """serve.py believes X-Forwarded-For only from Caddy, on this machine."""

    def test_uvicorn_trusts_only_the_local_front(self, monkeypatch):
        import uvicorn
        sys.path.insert(0, str(ENGINE_DIR / "tools"))
        import serve

        seen: dict = {}
        monkeypatch.setattr(uvicorn, "run", lambda *a, **k: seen.update(k))
        monkeypatch.setattr(serve, "_release_children", lambda: None)
        monkeypatch.delenv("VG_LOGS", raising=False)
        serve.main([])
        assert seen["proxy_headers"] is True
        assert seen["forwarded_allow_ips"] == "127.0.0.1"


class TestInstallable:
    """Both apps install from the browser: a manifest, its icons, the link."""

    @pytest.mark.parametrize("app", ["web", "mobile"])
    def test_manifest_icons_and_link(self, app):
        import json

        public = REPO_DIR / app / "public"
        manifest = json.loads((public / "manifest.webmanifest").read_text(encoding="utf-8"))
        assert manifest["start_url"] == "/" and manifest["scope"] == "/"
        assert manifest["display"] == "standalone"
        assert manifest["theme_color"] and manifest["background_color"]
        icons = {(i["sizes"], i["purpose"]): i["src"] for i in manifest["icons"]}
        assert set(icons) == {("192x192", "any"), ("512x512", "any"),
                              ("512x512", "maskable")}
        for src in icons.values():
            assert (public / src.lstrip("/")).is_file(), src

        html = (REPO_DIR / app / "index.html").read_text(encoding="utf-8")
        assert '<link rel="manifest" href="/manifest.webmanifest" />' in html
        assert '<meta name="theme-color"' in html

    @pytest.mark.parametrize("app", ["web", "mobile"])
    def test_no_service_worker_yet(self, app):
        # sw.js is spec 020's. One here without its update rules would pin
        # an installed app to an old build.
        assert not (REPO_DIR / app / "public" / "sw.js").exists()
