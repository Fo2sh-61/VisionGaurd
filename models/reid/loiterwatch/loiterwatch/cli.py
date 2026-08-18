"""Command line interface: replay event logs through a rule config."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from typing import Any

from .alerts import Alert, Severity
from .config import load_config
from .engine import Engine
from .events import Event, EventKind, read_jsonl
from .rules.base import RULE_TYPES

_ICON = {Severity.INFO: "i", Severity.WARNING: "!", Severity.CRITICAL: "!!"}
_ANSI = {Severity.INFO: "\033[36m", Severity.WARNING: "\033[33m", Severity.CRITICAL: "\033[31m"}
_RESET = "\033[0m"


def _clock(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")


def _print_alert(alert: Alert, color: bool) -> None:
    tint, reset = (_ANSI[alert.severity], _RESET) if color else ("", "")
    print(
        f"{tint}{_clock(alert.ts)}  [{_ICON[alert.severity]}] "
        f"{alert.severity.value.upper():<8} {alert.rule_id:<22} {alert.message}{reset}"
    )
    ev = alert.evidence
    detail = []
    if "dwell_human" in ev:
        detail.append(f"dwell={ev['dwell_human']}")
    if "entries" in ev:
        detail.append(f"entries={ev['entries']}")
    if "entered_at" in ev:
        detail.append(f"since={_clock(ev['entered_at'])}")
    if "observed_signals" in ev:
        detail.append(f"signals={ev['observed_signals'] or 'none'}")
    if detail:
        print(f"{'':10}     {' | '.join(detail)}")


def cmd_replay(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    engine: Engine = config.engine()
    color = sys.stdout.isatty() and not args.no_color

    events = list(read_jsonl(args.events))
    if not events:
        print("no events in log", file=sys.stderr)
        return 1

    print(f"replaying {len(events)} events through {len(config.rules)} rules "
          f"({args.events})\n")

    wall_start = time.time()
    stream_start = events[0].ts
    seen_open: set[tuple[str, str]] = set()

    for event in events:
        if args.speed > 0:
            target = wall_start + (event.ts - stream_start) / args.speed
            delay = target - time.time()
            if delay > 0:
                time.sleep(delay)

        alerts = engine.ingest(event)

        if args.verbose:
            key = (event.zone, event.track_id or "-")
            if event.kind is EventKind.SIGNAL:
                print(f"{_clock(event.ts)}  ·  signal '{event.signal}' @ {event.zone}")
            elif key not in seen_open and event.kind is not EventKind.EXIT:
                seen_open.add(key)
                print(f"{_clock(event.ts)}  ·  {event.track_id} entered {event.zone}")
            elif event.kind is EventKind.EXIT:
                seen_open.discard(key)
                print(f"{_clock(event.ts)}  ·  {event.track_id} left {event.zone}")

        for alert in alerts:
            if args.json:
                print(json.dumps(alert.to_dict()))
            else:
                _print_alert(alert, color)

    for alert in engine.close():
        if args.json:
            print(json.dumps(alert.to_dict()))
        else:
            _print_alert(alert, color)

    if not args.json:
        by_sev: dict[str, int] = {}
        for alert in engine.alerts:
            by_sev[alert.severity.value] = by_sev.get(alert.severity.value, 0) + 1
        summary = ", ".join(f"{v} {k}" for k, v in sorted(by_sev.items())) or "none"
        print(f"\n{len(engine.alerts)} alert(s): {summary}")
    return 0


def cmd_live(args: argparse.Namespace) -> int:
    from .live import YoloDetector, run
    from .shared_identity import SharedIdentityStore

    from .config import Config

    if args.no_rules:
        # pure re-identification: label people, raise nothing
        config = Config(rules=[], exit_grace_s=3.0, tick_s=0.5)
    elif args.config:
        config = load_config(args.config)
    else:
        print("give -c CONFIG, or --no-rules to just label people",
              file=sys.stderr)
        return 1

    source: object = args.source
    if isinstance(source, str) and source.isdigit():
        source = int(source)
    detector = YoloDetector(
        weights=args.weights, conf=args.conf, imgsz=args.imgsz, device=args.device,
        tracker=args.tracker,
    )

    # --identity-db doubles as the cross-camera link: point two `live`
    # processes at the same file and they mint IDs from a shared counter and
    # sync identities between them, so the same person keeps their ID on
    # whichever camera sees them. A single camera is just the trivial case of
    # "shared with nobody else".
    id_store = (SharedIdentityStore(args.identity_db)
                if args.identity_db and not args.no_stitch else None)
    stitcher = _build_stitcher(args, id_store)

    print(f"camera {source!r} -> zone '{args.camera}', "
          f"{len(config.rules)} rules. q or ESC quits, s saves a snapshot, "
          f"m mutes the alarm.\n")
    if id_store is not None:
        print(f"sharing identities via {args.identity_db} "
              f"(point another `live` process at the same file for "
              f"cross-camera recognition)\n")
    engine = run(
        config, detector, source=source, camera=args.camera,
        window=not args.no_window, log_path=args.log, record_path=args.record,
        stitcher=stitcher, play_alarm=not args.no_alarm,
        hold_on_exit=not args.no_window, show_timer=args.show_timer,
        identity_store=id_store, debug_reid=args.debug_reid,
    )
    if not args.no_rules:
        print(f"\n{len(engine.alerts)} alert(s) this session")
    if stitcher is not None:
        print(f"{len(stitcher.identities)} identities tracked, "
              f"{stitcher.merges} re-link(s)")
        if stitcher.rejected_ambiguous:
            print(f"{stitcher.rejected_ambiguous} match(es) declined as "
                  f"ambiguous -- usually people dressed alike. Lower "
                  f"--stitch-margin to accept more of them.")
        if stitcher.skipped_low_quality:
            print(f"{stitcher.skipped_low_quality} detection(s) were too "
                  f"truncated/small to identify at all -- lower "
                  f"--stitch-quality (now {stitcher.min_quality:.2f}) if this "
                  f"is most of them.")
        if stitcher.corrections:
            print(f"{stitcher.corrections} manual correction(s)")
    if not args.no_window:
        input("press Enter to close this window...")
    return 0


def cmd_multi(args: argparse.Namespace) -> int:
    from .live import YoloDetector
    from .config import Config
    from .multi import CameraSpec, parse_camera_arg, run_multi
    from .shared_identity import SharedIdentityStore

    if args.no_rules:
        config = Config(rules=[], exit_grace_s=3.0, tick_s=0.5)
    elif args.config:
        config = load_config(args.config)
    else:
        print("give -c CONFIG, or --no-rules to just label people",
              file=sys.stderr)
        return 1

    specs: list[CameraSpec] = []
    seen: set[str] = set()
    for raw in args.camera:
        name, source = parse_camera_arg(raw)
        if name in seen:
            print(f"duplicate camera name {name!r}; each --camera needs its own "
                  f"name, e.g. --camera laptop=0", file=sys.stderr)
            return 1
        seen.add(name)
        specs.append(CameraSpec(name=name, source=source))

    id_store = (SharedIdentityStore(args.identity_db)
                if args.identity_db and not args.no_stitch else None)
    stitcher = _build_stitcher(args, id_store)

    # one model per camera: tracker state lives on the model and must not be
    # shared between feeds
    for spec in specs:
        spec.detector = YoloDetector(
            weights=args.weights, conf=args.conf, imgsz=args.imgsz,
            device=args.device, tracker=args.tracker,
        )

    print(f"{len(specs)} camera(s), {len(config.rules)} rules. "
          f"q or ESC quits, s saves snapshots, m mutes the alarm.")
    for spec in specs:
        print(f"  {spec.name:<14} <- {spec.source!r}")
    if stitcher is not None:
        print("identities are shared across these cameras in real time.")
    print()

    engine = run_multi(
        config, specs, stitcher=stitcher, window=not args.no_window,
        play_alarm=not args.no_alarm, show_timer=args.show_timer,
        log_path=args.log, identity_store=id_store,
        hold_on_exit=not args.no_window, debug_reid=args.debug_reid,
    )
    if not args.no_rules:
        print(f"\n{len(engine.alerts)} alert(s) this session")
    if stitcher is not None:
        print(f"{len(stitcher.identities)} identities tracked, "
              f"{stitcher.merges} re-link(s)")
        if stitcher.rejected_ambiguous:
            print(f"{stitcher.rejected_ambiguous} match(es) declined as "
                  f"ambiguous -- two people scored too alike to choose "
                  f"between. Lower --cross-margin (now "
                  f"{stitcher.cross_margin:.2f}) to accept more of them.")
        if stitcher.rejected_unconfirmed:
            print(f"{stitcher.rejected_unconfirmed} claim(s) on an in-use "
                  f"identity waited for a second opinion -- normal, this "
                  f"counts every frame spent confirming.")
        if stitcher.corrections:
            print(f"{stitcher.corrections} manual correction(s)")
    if not args.no_window:
        input("press Enter to close this window...")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    from .probe import probe

    print(f"probing {args.host} as user {args.user!r} "
          f"(this takes a moment per candidate)\n")

    found: list = []

    def report(result) -> None:
        print(f"  {result.display}"
              + (f"   {result.detail}" if result.detail and args.verbose else ""),
              flush=True)
        if result.ok:
            found.append(result)

    probe(args.host, args.user, args.password, port=args.port,
          http_port=args.http_port, timeout=args.timeout,
          include_http=not args.no_http, on_result=report)

    if not found:
        print("\nnothing responded with a frame.")
        print("check the camera's Setup -> Network -> RTSP page for the exact "
              "path, and confirm the username and password.")
        return 1

    best = max(found, key=lambda r: r.width * r.height)
    print(f"\nworking stream: {best.url}")
    print("\nrun it alongside your laptop camera with:\n")
    print(f'  python -m loiterwatch multi -c examples\\live.yaml '
          f'--camera laptop=0 --camera ipcam="{best.url}"')
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
    except Exception as exc:  # noqa: BLE001
        print(f"invalid config: {exc}", file=sys.stderr)
        return 1
    print(f"ok - {len(config.rules)} rule(s), {len(config.zones)} zone(s)")
    for rule in config.rules:
        scope = ", ".join(rule.zones) if rule.zones else "all zones"
        print(f"  - {rule.rule_id} ({rule.type_name}) -> {scope}")
    return 0


def cmd_types(_: argparse.Namespace) -> int:
    for name, cls in sorted(RULE_TYPES.items()):
        doc = (cls.__doc__ or "").strip().splitlines()[0] if cls.__doc__ else ""
        print(f"{name:<18} {doc}")
    return 0


def _add_cross_camera_args(parser: argparse.ArgumentParser) -> None:
    """Knobs for matching a person across two cameras.

    Two `live` processes pointed at one --identity-db are a multi-camera setup
    just as much as `multi` is, so both subcommands get these.
    """
    parser.add_argument("--cross-similarity", type=float, default=None,
                        help="0-1; separate bar for matching a person last "
                             "seen on a DIFFERENT camera. defaults to "
                             "--stitch-similarity minus 0.10")
    parser.add_argument("--cross-margin", type=float, default=None,
                        help="how far a cross-camera winner must beat the "
                             "runner-up. THE dial for 'two people share one "
                             "ID': raising it drops only the matches that were "
                             "a coin-toss. defaults to twice --stitch-margin")
    parser.add_argument("--cross-evidence", type=int, default=None,
                        help="observations an identity needs before another "
                             "camera may claim it (default: --stitch-evidence)")
    parser.add_argument("--concurrent-similarity", type=float, default=None,
                        help="0-1; bar for taking an identity another camera "
                             "is showing right now. defaults to "
                             "--stitch-similarity, with no discounts applied")
    parser.add_argument("--concurrent-confirm", type=int, default=3,
                        help="agreeing observations needed before taking an "
                             "identity another camera holds. 1 disables it")
    parser.add_argument("--confirm-window", type=float, default=2.0,
                        help="seconds those observations must fit inside")
    parser.add_argument("--holder-window", type=float, default=2.0,
                        help="seconds since a camera last showed an identity "
                             "for it to still count as holding it")
    parser.add_argument("--stitch-evidence", type=int, default=2,
                        help="observations an identity needs before anyone may "
                             "match against it")


def _build_stitcher(args: argparse.Namespace, id_store: Any):
    """One construction path, so `live` and `multi` cannot drift apart."""
    from .identity import BodySignature, IdentityStitcher

    if args.no_stitch:
        return None

    similarity = args.stitch_similarity
    margin = args.stitch_margin
    gap = args.stitch_gap
    if args.sensitive:
        # bias hard toward "this is the same person": lower bar, longer memory,
        # and a smaller ambiguity margin. Costs you false merges between people
        # who dress alike -- which is the deal when matching is done on clothes.
        similarity = min(similarity, 0.48)
        margin = min(margin, 0.02)
        gap = max(gap, 3600.0)

    return IdentityStitcher(
        BodySignature(), max_gap_s=gap,
        min_similarity=similarity,
        min_quality=args.stitch_quality, margin=margin,
        min_evidence=args.stitch_evidence,
        cross_min_similarity=args.cross_similarity,
        cross_margin=args.cross_margin,
        cross_min_evidence=args.cross_evidence,
        concurrent_min_similarity=args.concurrent_similarity,
        concurrent_confirmations=args.concurrent_confirm,
        confirm_window_s=args.confirm_window,
        holder_window_s=args.holder_window,
        id_source=id_store.mint_id if id_store else None,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="loiterwatch", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    replay = sub.add_parser("replay", help="run an event log through the rules")
    replay.add_argument("events", help="path to a JSONL event log")
    replay.add_argument("-c", "--config", required=True, help="path to rules YAML")
    replay.add_argument("--speed", type=float, default=0.0,
                        help="playback speed vs real time (0 = as fast as possible)")
    replay.add_argument("--json", action="store_true", help="emit alerts as JSON lines")
    replay.add_argument("-v", "--verbose", action="store_true", help="echo zone transitions")
    replay.add_argument("--no-color", action="store_true")
    replay.set_defaults(func=cmd_replay)

    live = sub.add_parser("live", help="run against a camera with an on-screen overlay")
    live.add_argument("-c", "--config", default=None, help="path to rules YAML")
    live.add_argument("--no-rules", action="store_true",
                      help="skip alerting entirely and just label people with "
                           "stable IDs (no -c needed)")
    live.add_argument("--sensitive", action="store_true",
                      help="bias re-identification toward reusing an existing "
                           "ID; fewer new IDs on re-entry, more risk of merging "
                           "lookalikes")
    live.add_argument("--debug-reid", action="store_true",
                      help="print the closest match and its score whenever a "
                           "new identity is created")
    live.add_argument("--source", default="0",
                      help="webcam index or video file/RTSP URL (default 0)")
    live.add_argument("--camera", default="cam_live", help="zone name for this camera")
    live.add_argument("--weights", default="yolov8n.pt")
    live.add_argument("--conf", type=float, default=0.4, help="detector confidence floor")
    live.add_argument("--imgsz", type=int, default=640)
    live.add_argument("--device", default=None, help="e.g. cpu, 0, cuda:0")
    live.add_argument("--tracker", default="bytetrack.yaml",
                      help="ultralytics tracker config; try examples/botsort_reid.yaml")
    live.add_argument("--no-stitch", action="store_true",
                      help="disable appearance re-linking of returning people")
    live.add_argument("--stitch-gap", type=float, default=900.0,
                      help="seconds a departed person stays re-linkable (default 900)")
    live.add_argument("--stitch-similarity", type=float, default=0.60,
                      help="0-1; raise it if different people get merged, "
                           "lower it if the same person gets a new ID")
    live.add_argument("--identity-db", default=None,
                      help="JSON file to remember people across restarts")
    live.add_argument("--stitch-quality", type=float, default=0.55,
                      help="0-1; minimum crop quality used to identify someone. "
                           "raise it if truncated people get the wrong ID")
    live.add_argument("--stitch-margin", type=float, default=0.05,
                      help="how far the best candidate must beat the runner-up "
                           "before a match is accepted")
    _add_cross_camera_args(live)
    live.add_argument("--show-timer", action="store_true",
                      help="also draw the dwell clock above each person")
    live.add_argument("--log", default=None, help="append alerts as JSON lines")
    live.add_argument("--record", default=None, help="write the annotated video to mp4")
    live.add_argument("--no-window", action="store_true", help="headless")
    live.add_argument("--no-alarm", action="store_true",
                      help="disable the audible alarm on alerts")
    live.set_defaults(func=cmd_live)

    multi = sub.add_parser(
        "multi", help="run several cameras at once, sharing one identity pool")
    multi.add_argument("-c", "--config", default=None, help="path to rules YAML")
    multi.add_argument("--no-rules", action="store_true",
                       help="skip alerting entirely and just label people with "
                            "stable IDs (no -c needed)")
    multi.add_argument("--sensitive", action="store_true",
                       help="bias re-identification toward reusing an existing ID")
    multi.add_argument("--camera", action="append", required=True, metavar="NAME=SOURCE",
                       help="repeatable. e.g. --camera laptop=0 "
                            "--camera ipcam=rtsp://user:pass@host:554/stream")
    multi.add_argument("--weights", default="yolov8n.pt")
    multi.add_argument("--conf", type=float, default=0.4,
                       help="detector confidence floor")
    multi.add_argument("--imgsz", type=int, default=640)
    multi.add_argument("--device", default=None, help="e.g. cpu, 0, cuda:0")
    multi.add_argument("--tracker", default="bytetrack.yaml",
                       help="ultralytics tracker config")
    multi.add_argument("--no-stitch", action="store_true",
                       help="disable appearance re-linking between cameras")
    multi.add_argument("--stitch-gap", type=float, default=900.0,
                       help="seconds a departed person stays re-linkable")
    multi.add_argument("--stitch-similarity", type=float, default=0.60,
                       help="0-1; raise it if different people get merged")
    multi.add_argument("--stitch-quality", type=float, default=0.55,
                       help="0-1; minimum crop quality used to identify someone")
    multi.add_argument("--stitch-margin", type=float, default=0.05,
                       help="how far the best candidate must beat the runner-up")
    _add_cross_camera_args(multi)
    multi.add_argument("--debug-reid", action="store_true",
                       help="print the closest match score whenever a new "
                            "identity is created, so you can tune the threshold")
    multi.add_argument("--identity-db", default=None,
                       help="also persist identities to this file across restarts")
    multi.add_argument("--show-timer", action="store_true",
                       help="also draw the dwell clock above each person")
    multi.add_argument("--log", default=None, help="append alerts as JSON lines")
    multi.add_argument("--no-window", action="store_true", help="headless")
    multi.add_argument("--no-alarm", action="store_true",
                       help="disable the audible alarm on alerts")
    multi.set_defaults(func=cmd_multi)

    probe_cmd = sub.add_parser(
        "probe", help="find an IP camera's stream URL by trying common paths")
    probe_cmd.add_argument("host", help="camera IP, e.g. 192.168.144.108")
    probe_cmd.add_argument("--user", default="", help="camera username")
    probe_cmd.add_argument("--password", default="", help="camera password")
    probe_cmd.add_argument("--port", type=int, default=554, help="RTSP port")
    probe_cmd.add_argument("--http-port", type=int, default=80)
    probe_cmd.add_argument("--timeout", type=float, default=6.0,
                           help="seconds to wait for each candidate")
    probe_cmd.add_argument("--no-http", action="store_true",
                           help="only try RTSP")
    probe_cmd.add_argument("-v", "--verbose", action="store_true",
                           help="show why each candidate failed")
    probe_cmd.set_defaults(func=cmd_probe)

    validate = sub.add_parser("validate", help="check a rules YAML file")
    validate.add_argument("-c", "--config", required=True)
    validate.set_defaults(func=cmd_validate)

    types_cmd = sub.add_parser("types", help="list available rule types")
    types_cmd.set_defaults(func=cmd_types)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
