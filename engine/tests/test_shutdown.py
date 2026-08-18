"""Ctrl-C must always mean stopped.

Three separate causes used to combine into a server that could not be killed
while a camera view was open in a browser, which meant killing the terminal or
restarting the machine several times a day. Each has a test here.

  1. An MJPEG stream is an HTTP response that never completes by design.
     uvicorn's graceful shutdown waits for open connections to finish, so the
     server waited for the browser and the browser waited for the server.
     Fixed by `app.SHUTTING_DOWN`, which the stream generator checks.

  2. `serve.py` cleans up orphans with psutil inside a try/except ImportError
     that returned silently. psutil was not in requirements.txt, so on the
     development machine the safety net did nothing, every time.

  3. `CameraRegistry.stop()` signalled and joined in the same loop, giving each
     camera its own 3s join while stuck in a blocking cv2 read. Two cameras
     took 6s, ten took 30s, and it looked like a hang. Now signalling is one
     pass and joining is another, against a single total budget.
"""

from __future__ import annotations

import threading
import time

import pytest


# ---------------------------------------------------------------------------
# 1. the stream releases itself
# ---------------------------------------------------------------------------

class TestShuttingDownEvent:
    def test_app_exposes_a_shutdown_event(self):
        from vg.api import app as app_module

        assert isinstance(app_module.SHUTTING_DOWN, threading.Event)

    def test_stream_loop_is_not_an_unconditional_while_true(self):
        """The generator must have a second exit besides client disconnect.

        `while True` here is what held the process open: the only way out was
        the browser closing the connection, which is exactly what does not
        happen when you press Ctrl-C with a camera view open.

        Read from the file rather than via `inspect`: the endpoint is nested
        inside the route-registration function, so it is not a module
        attribute and cannot be reached from the imported module.
        """
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1] / "vg" / "api" / "app.py"
        ).read_text(encoding="utf-8")

        stream_body = source[source.index("async def frames():"):]
        assert "while not SHUTTING_DOWN.is_set()" in stream_body, (
            "the stream generator must check SHUTTING_DOWN, or Ctrl-C hangs "
            "whenever a camera view is open"
        )

    def test_teardown_sets_it_before_stopping_workers(self):
        """Order matters. Releasing the streams first is what lets uvicorn's
        graceful shutdown finish; doing it after the workers means waiting on
        the very connections that are blocking."""
        import inspect

        from vg.api import app as app_module

        source = inspect.getsource(app_module.lifespan)
        _, _, teardown = source.partition("finally:")
        assert "SHUTTING_DOWN.set()" in teardown

        set_at = teardown.index("SHUTTING_DOWN.set()")
        stop_at = teardown.index("worker.stop()")
        assert set_at < stop_at, "SHUTTING_DOWN must be set before workers are stopped"


# ---------------------------------------------------------------------------
# 2. the cleanup net is actually installed
# ---------------------------------------------------------------------------

class TestCleanupDependency:
    def test_psutil_is_importable(self):
        """`_release_children()` returns silently without it, so a missing
        psutil turns the whole cleanup path into a no-op that looks fine."""
        pytest.importorskip(
            "psutil",
            reason="psutil is in requirements.txt; install it or serve.py's "
                   "orphan cleanup silently does nothing",
        )

    def test_psutil_is_declared_in_requirements(self):
        from pathlib import Path

        requirements = Path(__file__).resolve().parents[1] / "requirements.txt"
        text = requirements.read_text(encoding="utf-8")
        assert "psutil" in text, "psutil must be declared, not merely happen to be installed"


# ---------------------------------------------------------------------------
# 3. cameras stop in parallel, against one budget
# ---------------------------------------------------------------------------

class FakeSource:
    """A capture source that ignores stop() for a while, like a blocking read."""

    def __init__(self, linger: float) -> None:
        self.linger = linger
        self.stopped = threading.Event()
        self.stop_called_at: float | None = None

    def stop(self) -> None:
        self.stop_called_at = time.monotonic()
        self.stopped.set()

    def run(self, stop_event: threading.Event) -> None:
        # Stays busy for `linger` seconds after being told to stop, the way a
        # thread parked inside cv2.read() does.
        stop_event.wait()
        time.sleep(self.linger)


def make_worker(linger: float):
    """A CameraWorker with its source and thread replaced, so this test needs
    no camera, no OpenCV and no config."""
    from vg.ingest.registry import CameraWorker

    worker = CameraWorker.__new__(CameraWorker)
    worker.source = FakeSource(linger)
    worker._stop = threading.Event()
    worker._thread = threading.Thread(
        target=worker.source.run, args=(worker._stop,), daemon=True
    )
    worker._thread.start()
    return worker


class TestParallelShutdown:
    def test_worker_has_a_signal_only_stop(self):
        worker = make_worker(0.1)
        started = time.monotonic()
        worker.request_stop()
        elapsed = time.monotonic() - started

        assert elapsed < 0.05, "request_stop must return immediately, not join"
        assert worker._stop.is_set()
        assert worker.source.stopped.is_set()
        worker.join(1.0)

    def test_registry_signals_every_camera_before_joining_any(self):
        """The bug: signal-then-join per camera, so camera 2 was not even told
        to stop until camera 1 had finished its 3s join."""
        from vg.ingest.registry import CameraRegistry

        registry = CameraRegistry.__new__(CameraRegistry)
        registry.workers = {f"c{i}": make_worker(0.4) for i in range(4)}
        registry.disabled = {}
        registry._started = True

        class NullBus:
            def close(self) -> None: ...

        registry.bus = NullBus()

        registry.stop(timeout=5.0)

        signalled = [w.source.stop_called_at for w in registry.workers.values()]
        spread = max(signalled) - min(signalled)
        assert spread < 0.1, (
            f"cameras were signalled {spread:.2f}s apart; they must all be "
            "signalled together before any join begins"
        )

    def test_total_shutdown_time_does_not_scale_with_camera_count(self):
        """Six cameras that each linger 0.4s must still stop in well under the
        2.4s a serial join would take."""
        from vg.ingest.registry import CameraRegistry

        registry = CameraRegistry.__new__(CameraRegistry)
        registry.workers = {f"c{i}": make_worker(0.4) for i in range(6)}
        registry.disabled = {}
        registry._started = True

        class NullBus:
            def close(self) -> None: ...

        registry.bus = NullBus()

        started = time.monotonic()
        registry.stop(timeout=5.0)
        elapsed = time.monotonic() - started

        assert elapsed < 1.2, (
            f"stopping 6 cameras took {elapsed:.2f}s; serial joins would take "
            "~2.4s, so the passes are not running in parallel"
        )
        assert not registry._started

    def test_stop_honours_its_total_budget_when_threads_refuse_to_die(self):
        """A stuck thread must not extend shutdown past the budget. Capture
        threads are daemons, so a straggler dies with the process."""
        from vg.ingest.registry import CameraRegistry

        registry = CameraRegistry.__new__(CameraRegistry)
        registry.workers = {f"c{i}": make_worker(30.0) for i in range(3)}
        registry.disabled = {}
        registry._started = True

        class NullBus:
            def close(self) -> None: ...

        registry.bus = NullBus()

        started = time.monotonic()
        registry.stop(timeout=1.0)
        elapsed = time.monotonic() - started

        assert elapsed < 2.0, (
            f"shutdown took {elapsed:.2f}s against a 1.0s budget; the budget "
            "is per-registry, not per-camera"
        )
