"""The engine must start, and must refuse to start quietly.

This is the CI gate described in `docs/PLAN.md` as P0-10's "strict-mode smoke
start". It exists because of one incident, and every test here is a piece of
that incident:

A name was used but never bound inside `_start_recognition`. The broad
`except Exception` that surrounds every subsystem start caught the NameError,
logged it, and returned a reason. The engine came up looking completely
healthy. `LiveStore` then fell through to `MockStore` for everything face
recognition owns, and the console served invented attendance for days. Nobody
noticed, because a fixture register looks exactly like a real one.

Three separate things had to hold for that to be caught, so there is a test
for each:

  1. The process actually starts and answers. If an import at module scope is
     broken, nothing below matters.
  2. `VG_STRICT=1` turns a degrade into a refusal, so CI and the deployment
     machine die loudly instead of serving fixtures.
  3. Every degrade path consults that guard. A single `except Exception` that
     forgot to call `_reraise_if_strict` re-opens the hole, and it would look
     completely normal in review.

`VG_MOCK=1` is set for the boot tests deliberately: it skips camera capture, so
this suite opens no device and needs no model weights. It runs identically on a
laptop with the webcam in use and on a CI box with neither camera nor GPU.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vg.api import app as app_module  # noqa: E402
from vg.api.app import create_app  # noqa: E402


APP_SOURCE = Path(app_module.__file__)


# ---------------------------------------------------------------------------
# 1. it starts and answers
# ---------------------------------------------------------------------------

class TestSmokeStart:
    """The lifespan completes and the API responds.

    A unit test can pass on a module that cannot be started — it imports one
    symbol and never runs the wiring. These go through the real lifespan, which
    is the part that broke.
    """

    def test_the_app_starts_and_healthz_answers(self, monkeypatch):
        """Startup, a request, shutdown. The whole cycle, not a route call.

        `with TestClient(...)` is what makes this a smoke start rather than a
        route test: entering runs the lifespan startup, leaving runs shutdown.
        Constructing the client without `with` skips both, which is why the
        other API tests could never have caught a startup failure.
        """
        monkeypatch.setenv("VG_MOCK", "1")
        monkeypatch.setenv("VG_STRICT", "1")

        with TestClient(create_app()) as client:
            response = client.get("/healthz")

        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_system_health_is_reachable_on_a_bare_engine(self, monkeypatch, authed):
        """Health must answer when everything it describes is broken.

        Constitution rule 7: degradation is payload, never a 5xx. System Health
        is the page an operator opens to find out what is wrong, so it cannot
        be the page that fails because something is wrong.

        It is behind sign-in (P2) - it describes the site's subsystems, which
        is not something to hand an anonymous caller - so this signs in first.
        The 401 case is test_authorisation.py's job; what is checked here is
        that a broken engine answers rather than erroring.
        """
        monkeypatch.setenv("VG_MOCK", "1")
        monkeypatch.setenv("VG_STRICT", "1")

        app = create_app()
        with TestClient(app):          # runs the lifespan
            client = authed(app)       # a real session against the started app
            response = client.get("/system/health")

        assert response.status_code == 200

    def test_shutdown_releases_the_streams(self, monkeypatch):
        """Leaving the lifespan must set the flag open MJPEG streams watch.

        Without it uvicorn waits for a response that never completes by design,
        and the engine cannot be stopped while a camera view is open.
        """
        monkeypatch.setenv("VG_MOCK", "1")

        app_module.SHUTTING_DOWN.clear()
        with TestClient(create_app()):
            assert not app_module.SHUTTING_DOWN.is_set()
        assert app_module.SHUTTING_DOWN.is_set()

        # Leave it as found; other suites build clients too.
        app_module.SHUTTING_DOWN.clear()


# ---------------------------------------------------------------------------
# 2. strict mode refuses instead of degrading
# ---------------------------------------------------------------------------

class TestStrictGuard:
    def test_strict_turns_a_degrade_into_a_refusal(self, monkeypatch):
        monkeypatch.setenv("VG_STRICT", "1")

        with pytest.raises(RuntimeError) as caught:
            app_module._reraise_if_strict(
                NameError("name 'gallery' is not defined"), "face recognition"
            )

        message = str(caught.value)
        # The operator needs both halves: which subsystem, and why.
        assert "face recognition" in message
        assert "NameError" in message
        assert "gallery" in message

    def test_the_original_error_is_kept_as_the_cause(self, monkeypatch):
        """`raise ... from exc`, so the traceback still shows the real bug.

        Losing the cause would leave a RuntimeError naming the subsystem and
        nothing pointing at the line that actually failed.
        """
        monkeypatch.setenv("VG_STRICT", "1")
        original = NameError("name 'gallery' is not defined")

        with pytest.raises(RuntimeError) as caught:
            app_module._reraise_if_strict(original, "face recognition")

        assert caught.value.__cause__ is original

    def test_without_strict_it_returns_quietly(self, monkeypatch):
        """The default stays degrade-and-report.

        A missing model file on site must not take the whole console down with
        it — the cameras still work and Health still explains the gap.
        """
        monkeypatch.delenv("VG_STRICT", raising=False)

        assert app_module._reraise_if_strict(RuntimeError("no weights"), "x") is None

    @pytest.mark.parametrize("value", ["0", "", "true", "yes", "TRUE"])
    def test_only_exactly_1_enables_strict(self, monkeypatch, value):
        """Fail open, not closed, on a typo.

        A deployment that meant to set strict and mistyped it gets the normal
        degrade-and-report engine, which is the safe half of the mistake.
        """
        monkeypatch.setenv("VG_STRICT", value)

        assert app_module._reraise_if_strict(RuntimeError("no weights"), "x") is None


# ---------------------------------------------------------------------------
# 3. no degrade path can skip the guard
# ---------------------------------------------------------------------------

def _start_functions() -> list[ast.FunctionDef]:
    tree = ast.parse(APP_SOURCE.read_text(encoding="utf-8"))
    return [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_start_")
    ]


def _calls_strict_guard(handler: ast.ExceptHandler) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_reraise_if_strict"
        for node in ast.walk(handler)
    )


class TestEveryDegradePathIsGuarded:
    """Read `app.py` and prove the invariant, rather than trusting review.

    This is a source check on purpose. The failure it guards is an *absent*
    line, and there is no runtime state that reveals a missing call — the
    subsystem simply degrades, exactly as a correctly-guarded one does when
    strict is off. Only the source says which.
    """

    def test_there_are_start_functions_to_check(self):
        """Guard the guard: a rename must not silently empty this suite."""
        names = [fn.name for fn in _start_functions()]

        assert len(names) >= 5, f"expected the subsystem starters, found {names}"

    @pytest.mark.parametrize("fn", _start_functions(), ids=lambda fn: fn.name)
    def test_the_top_level_handler_consults_the_strict_guard(self, fn):
        """Each starter's outer `except Exception` must call the guard.

        Only the outermost try is checked. `_start_counts` has a nested one
        inside its sampling thread that deliberately swallows and logs — losing
        one history row must not kill the thread — and that is not a startup
        path.
        """
        outer = [node for node in fn.body if isinstance(node, ast.Try)]
        assert outer, f"{fn.name} has no top-level try; it cannot degrade safely"

        handlers = [h for try_ in outer for h in try_.handlers]
        unguarded = [
            f"{fn.name}:{h.lineno}" for h in handlers if not _calls_strict_guard(h)
        ]

        assert not unguarded, (
            f"these degrade paths swallow an error without consulting "
            f"VG_STRICT: {unguarded}. A code bug here would look like a "
            f"healthy engine serving fixtures."
        )
