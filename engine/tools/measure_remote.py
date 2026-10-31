"""How fast does the console get its answers, from here, from that engine?

The cloud trial (specs/021-cloud-trial) puts the engine on a Kaggle GPU and the
console on this PC, with a tunnel in between. This measures what distance
costs, the same way against both, so the two columns can sit side by side:

    python engine/tools/measure_remote.py --url http://127.0.0.1:8000 --label local --email me@site
    python engine/tools/measure_remote.py --url https://x.trycloudflare.com --label cloud --email admin@trial.local
    python engine/tools/measure_remote.py --compare      # rebuild comparison.md only

The password comes from `VG_MEASURE_PASSWORD`, or is asked for without echo.
Never an argument: that would sit in the shell history.

**What it measures**, as the console would see it:

  reads    the GETs the console makes when it first opens (read off the
           browser's network panel, 31 Oct 2026)
  tiles    one camera tile's pictures, asked for the way a single tile asks
  stream   the enlarged view's MJPEG, frames actually received a second
  boxes    how old the overlay is when it arrives here
  events   how old a breach is when it is first visible here (the clip
           camera must be switched on as restricted; bootstrap.sh does it)

**The two machines do not share a clock.** Ages need one, so the offset is
estimated from `/healthz`'s `now`, using the call with the shortest round trip,
and every age is printed with plus-or-minus half that round trip. A breach's age
is measured from its own `at`, without subtracting anything.

**Failures are failures.** A refused or timed-out request is counted in its own
column and never folded into a timing, where it would read as a fast success.

Standard library only, so it runs from any Python on the PC.
"""

from __future__ import annotations

import argparse
import getpass
import json
import math
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
EVIDENCE = REPO_DIR / "specs" / "021-cloud-trial" / "evidence"

#: What the console asks for when it first opens, read off the browser's
#: network panel on 31 Oct 2026 (Home page, signed in).
READ_PATHS = ("/healthz", "/auth/me", "/system/capabilities", "/cameras",
              "/site", "/attention")

#: One tile on screen asks for 15 pictures a second (`frame.ts`
#: `tileRefreshMs`: 120 a second shared across tiles, at most 15 each).
TILE_WIDTH = 640
TILE_FPS = 15

#: Overlay polling at four tiles or fewer (`frame.ts` `tileBoxRefreshMs`).
BOX_INTERVAL_S = 0.2
EVENT_INTERVAL_S = 0.25

#: `features/zones.py` `CONFIRM_SECONDS`, recorded with each run. The age is
#: measured from the breach's own `at` (the scene's `started_at`), whatever
#: that turns out to mean; the first local run saw ~0.3 s, not >= 2 s, which
#: is an open question for zones.py, not something to correct for here.
DWELL_SECONDS = 2.0


# ---------------------------------------------------------------------------
# numbers
# ---------------------------------------------------------------------------

def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile. None for no values - never 0."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, min(len(ordered), math.ceil(q / 100 * len(ordered))))
    return ordered[rank - 1]


def summarise(times_ms: list[float], failures: int) -> dict:
    return {
        "n": len(times_ms),
        "failures": failures,
        "p50Ms": _round(percentile(times_ms, 50)),
        "p95Ms": _round(percentile(times_ms, 95)),
    }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def clock_offset(samples: list[tuple[float, float, float]]) -> dict:
    """Server-minus-PC clock offset from (sent_ms, server_ms, received_ms).

    The sample with the shortest round trip is the one whose server reading
    is pinned down best: the server answered somewhere inside that window, so
    the offset is right to within half of it.
    """
    if not samples:
        return {"offsetMs": None, "uncertaintyMs": None, "samples": 0}
    sent, server, received = min(samples, key=lambda s: s[2] - s[0])
    midpoint = (sent + received) / 2
    return {
        "offsetMs": round(server - midpoint, 1),
        "uncertaintyMs": round((received - sent) / 2, 1),
        "samples": len(samples),
    }


def count_jpegs(chunk: bytes, tail: bytes = b"") -> tuple[int, bytes]:
    """JPEG start markers in a stream, carrying one byte across chunk edges.

    0xFF 0xD8 cannot occur inside JPEG data (a data 0xFF is followed by 0x00
    or a restart marker), so each one is the start of a picture.
    """
    data = tail + chunk
    return data.count(b"\xff\xd8"), data[-1:]


def instant_ms(instant: dict | None) -> float | None:
    """A wire `Instant` -> epoch milliseconds, or None."""
    if not instant or not instant.get("utc"):
        return None
    raw = str(instant["utc"]).replace("Z", "+00:00")
    return datetime.fromisoformat(raw).timestamp() * 1000


def now_ms() -> float:
    return time.time() * 1000


# ---------------------------------------------------------------------------
# talking to the engine
# ---------------------------------------------------------------------------

@dataclass
class Engine:
    url: str
    token: str = ""
    timeout: float = 10.0
    _context: ssl.SSLContext = field(default_factory=ssl.create_default_context)

    def _request(self, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url.rstrip("/") + path, data=data)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        return urllib.request.urlopen(req, timeout=self.timeout, context=self._context)

    def get(self, path: str) -> tuple[bool, float, bytes]:
        """(ok, milliseconds, body). Any failure is (False, ms, b"")."""
        start = time.perf_counter()
        try:
            with self._request(path) as response:
                body = response.read()
            return True, (time.perf_counter() - start) * 1000, body
        except (urllib.error.URLError, OSError, ValueError):
            return False, (time.perf_counter() - start) * 1000, b""

    def sign_in(self, email: str, password: str) -> None:
        with self._request("/auth/login", {"email": email, "password": password}) as r:
            self.token = json.loads(r.read())["token"]


# ---------------------------------------------------------------------------
# the measures
# ---------------------------------------------------------------------------

def measure_clock(engine: Engine, n: int = 20) -> dict:
    samples = []
    for _ in range(n):
        sent = now_ms()
        ok, _, body = engine.get("/healthz")
        received = now_ms()
        if ok:
            server = json.loads(body).get("now")
            if isinstance(server, (int, float)):
                samples.append((sent, float(server), received))
    return clock_offset(samples)


def measure_reads(engine: Engine, rounds: int = 30) -> dict:
    out = {}
    timings: dict[str, list[float]] = {p: [] for p in READ_PATHS}
    failures = {p: 0 for p in READ_PATHS}
    for _ in range(rounds):
        for path in READ_PATHS:
            ok, ms, _ = engine.get(path)
            if ok:
                timings[path].append(ms)
            else:
                failures[path] += 1
    for path in READ_PATHS:
        out[path] = summarise(timings[path], failures[path])
    return out


def measure_tiles(engine: Engine, camera: str, seconds: float) -> dict:
    times, sizes, failures = [], [], 0
    started = time.perf_counter()
    tick = 0
    while time.perf_counter() - started < seconds:
        tick += 1
        ok, ms, body = engine.get(
            f"/cameras/{camera}/snapshot?t={tick}&width={TILE_WIDTH}&fps={TILE_FPS}")
        if ok and body:
            times.append(ms)
            sizes.append(len(body))
        else:
            failures += 1
        # A tile does not ask again before its interval is up.
        wait = 1 / TILE_FPS - ms / 1000
        if wait > 0:
            time.sleep(wait)
    elapsed = time.perf_counter() - started
    result = summarise(times, failures)
    result.update({
        "seconds": round(elapsed, 1),
        "perSecond": round(len(times) / elapsed, 2) if elapsed else None,
        "meanBytes": round(sum(sizes) / len(sizes)) if sizes else None,
    })
    return result


def measure_stream(engine: Engine, camera: str, seconds: float) -> dict:
    frames, failures = 0, 0
    started = time.perf_counter()
    try:
        with engine._request(f"/cameras/{camera}/stream") as response:
            tail = b""
            while time.perf_counter() - started < seconds:
                chunk = response.read1(65536) if hasattr(response, "read1") else response.read(65536)
                if not chunk:
                    break
                found, tail = count_jpegs(chunk, tail)
                frames += found
    except (urllib.error.URLError, OSError, ValueError):
        failures += 1
    elapsed = time.perf_counter() - started
    return {"seconds": round(elapsed, 1), "frames": frames,
            "perSecond": round(frames / elapsed, 2) if elapsed else None,
            "failures": failures}


def measure_boxes(engine: Engine, camera: str, seconds: float, offset_ms: float) -> dict:
    ages, failures = [], 0
    started = time.perf_counter()
    while time.perf_counter() - started < seconds:
        ok, ms, body = engine.get(f"/cameras/{camera}/detections?feature=counting")
        arrived = now_ms()
        at = instant_ms(json.loads(body).get("at")) if ok else None
        if at is not None:
            ages.append(arrived + offset_ms - at)
        else:
            failures += 1
        wait = BOX_INTERVAL_S - ms / 1000
        if wait > 0:
            time.sleep(wait)
    result = summarise(ages, failures)
    return {"n": result["n"], "failures": failures,
            "ageP50Ms": result["p50Ms"], "ageP95Ms": result["p95Ms"]}


def measure_events(engine: Engine, seconds: float, offset_ms: float) -> dict:
    ok, _, body = engine.get("/breaches?window=today")
    already = {b["id"] for b in json.loads(body)} if ok else set()
    ages, failures = [], 0
    started = time.perf_counter()
    while time.perf_counter() - started < seconds:
        ok, ms, body = engine.get("/breaches?window=today")
        arrived = now_ms()
        if not ok:
            failures += 1
        else:
            for breach in json.loads(body):
                if breach["id"] in already:
                    continue
                already.add(breach["id"])
                at = instant_ms(breach.get("at"))
                if at is not None:
                    ages.append(arrived + offset_ms - at)
        wait = EVENT_INTERVAL_S - ms / 1000
        if wait > 0:
            time.sleep(wait)
    result = summarise(ages, failures)
    return {
        "seen": len(ages), "failures": failures,
        "ageP50Ms": result["p50Ms"], "ageP95Ms": result["p95Ms"],
        "seconds": round(time.perf_counter() - started, 1),
        "dwellSeconds": DWELL_SECONDS,
    }


def server_reading(engine: Engine) -> dict | None:
    ok, _, body = engine.get("/system/health")
    if not ok:
        return None
    health = json.loads(body)
    keep = ("gpuPercent", "gpuMemoryUsedMb", "gpuMemoryTotalMb", "cpuPercent",
            "cpuMachinePercent", "camerasOnline", "camerasTotal", "severity")
    return {k: health.get(k) for k in keep}


# ---------------------------------------------------------------------------
# writing it down
# ---------------------------------------------------------------------------

def _ms(value) -> str:
    return "—" if value is None else f"{value:.0f} ms"


def _pm(value, clock: dict) -> str:
    if value is None:
        return "—"
    unc = clock.get("uncertaintyMs")
    return f"{value:.0f} ms ± {unc:.0f}" if unc is not None else f"{value:.0f} ms"


def _num(value, unit: str = "") -> str:
    return "—" if value is None else f"{value}{unit}"


def rows_for(run: dict) -> dict[str, str]:
    """One run -> {measure: cell}. The keys are the table's rows."""
    clock = run.get("clock", {})
    rows: dict[str, str] = {}
    rows["Measured for"] = f"{run.get('minutes')} min, from {run.get('started', '?')[:16]}"
    rows["Clock offset (server − PC)"] = _pm(clock.get("offsetMs"), clock)
    for path, r in run.get("reads", {}).items():
        rows[f"Read {path} p50 / p95"] = (
            f"{_ms(r['p50Ms'])} / {_ms(r['p95Ms'])}"
            + (f" · **{r['failures']} failed**" if r["failures"] else ""))
    t = run.get("tiles", {})
    rows["Tile pictures received per second (asked: 15)"] = _num(t.get("perSecond"))
    rows["Tile picture p50 / p95"] = f"{_ms(t.get('p50Ms'))} / {_ms(t.get('p95Ms'))}"
    rows["Tile picture size"] = _num(
        None if t.get("meanBytes") is None else round(t["meanBytes"] / 1024, 1), " KB")
    rows["Tile failures"] = _num(t.get("failures"))
    s = run.get("stream", {})
    rows["Live view frames per second"] = _num(s.get("perSecond"))
    rows["Live view failures"] = _num(s.get("failures"))
    b = run.get("boxes", {})
    rows["Box age when it arrives p50"] = _pm(b.get("ageP50Ms"), clock)
    rows["Box age when it arrives p95"] = _pm(b.get("ageP95Ms"), clock)
    rows["Box failures"] = _num(b.get("failures"))
    e = run.get("events", {})
    rows["Breaches seen (in this many seconds)"] = (
        f"{_num(e.get('seen'))} (in {_num(e.get('seconds'))} s)"
        + (f" · **{e['failures']} failed**" if e.get("failures") else ""))
    rows["Breach age when first seen p50 (from its own `at`)"] = _pm(e.get("ageP50Ms"), clock)
    rows["Breach age when first seen p95"] = _pm(e.get("ageP95Ms"), clock)
    for when in ("start", "end"):
        srv = (run.get("server") or {}).get(when) or {}
        rows[f"Server GPU % / memory MB ({when})"] = (
            f"{_num(srv.get('gpuPercent'))} / "
            f"{_num(srv.get('gpuMemoryUsedMb'))} of {_num(srv.get('gpuMemoryTotalMb'))}")
        rows[f"Server CPU % of machine ({when})"] = _num(srv.get("cpuMachinePercent"))
    return rows


def comparison(runs: list[dict]) -> str:
    """Markdown, one column per label (its latest run)."""
    latest: dict[str, dict] = {}
    for run in sorted(runs, key=lambda r: r.get("started", "")):
        latest[run["label"]] = run
    labels = list(latest)
    tables = {label: rows_for(latest[label]) for label in labels}
    measures: list[str] = []
    for table in tables.values():
        for key in table:
            if key not in measures:
                measures.append(key)

    lines = [
        "# Cloud trial: response speed, local vs cloud",
        "",
        "Written by `engine/tools/measure_remote.py`. One camera (`cam-clip`, the",
        "recorded walk-through), measured from Mohamed's PC. Ages carry ± half the",
        "shortest `/healthz` round trip, because the two clocks are not shared.",
        "Breach age is measured from the breach's own `at` (its scene's start).",
        "Not a site measurement: one clip, one camera, one viewer.",
        "",
        "| Measure | " + " | ".join(f"{label} ({latest[label]['url']})" for label in labels) + " |",
        "|---|" + "---|" * len(labels),
    ]
    for measure in measures:
        cells = [tables[label].get(measure, "—") for label in labels]
        lines.append(f"| {measure} | " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def write_comparison(out: Path) -> Path:
    runs = []
    for path in sorted(out.glob("*.json")):
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(run, dict) and run.get("label") and run.get("clock") is not None:
            runs.append(run)
    target = out / "comparison.md"
    target.write_text(comparison(runs), encoding="utf-8", newline="\n")
    return target


# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Measure the console's answers from here.")
    p.add_argument("--url", help="http://127.0.0.1:8000 or the tunnel's https address")
    p.add_argument("--label", help="the column name, e.g. local or cloud")
    p.add_argument("--email")
    p.add_argument("--minutes", type=float, default=6.0)
    p.add_argument("--camera", default="cam-clip")
    p.add_argument("--out", type=Path, default=EVIDENCE)
    p.add_argument("--compare", action="store_true", help="only rebuild comparison.md")
    args = p.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    if args.compare:
        print(f"  wrote {write_comparison(args.out)}")
        return 0
    if not (args.url and args.label and args.email):
        p.error("--url, --label and --email are needed to measure")

    engine = Engine(args.url)
    ok, _, _ = engine.get("/healthz")
    if not ok:
        print(f"  {args.url} does not answer /healthz", file=sys.stderr)
        return 1
    password = os.environ.get("VG_MEASURE_PASSWORD") or getpass.getpass("  password  ")
    try:
        engine.sign_in(args.email, password)
    except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        print(f"  could not sign in: {exc}", file=sys.stderr)
        return 1

    total = args.minutes * 60
    started = datetime.now(timezone.utc)
    run: dict = {"label": args.label, "url": args.url, "camera": args.camera,
                 "started": started.isoformat(), "minutes": args.minutes}

    print("  clock ...")
    run["clock"] = measure_clock(engine)
    offset = run["clock"]["offsetMs"] or 0.0
    run["server"] = {"start": server_reading(engine)}
    print("  page-load reads ...")
    run["reads"] = measure_reads(engine)
    print("  tiles (60 s) ...")
    run["tiles"] = measure_tiles(engine, args.camera, 60)
    print("  live view (30 s) ...")
    run["stream"] = measure_stream(engine, args.camera, 30)
    print("  boxes (60 s) ...")
    run["boxes"] = measure_boxes(engine, args.camera, 60, offset)
    spent = (datetime.now(timezone.utc) - started).total_seconds()
    rest = max(60.0, total - spent)
    print(f"  breaches ({rest:.0f} s) ...")
    run["events"] = measure_events(engine, rest, offset)
    run["server"]["end"] = server_reading(engine)

    name = f"{args.label}-{started.strftime('%Y%m%d-%H%M')}.json"
    (args.out / name).write_text(json.dumps(run, indent=2), encoding="utf-8", newline="\n")
    print(f"  wrote {args.out / name}")
    print(f"  wrote {write_comparison(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
