#!/usr/bin/env python3
"""
Vehicle gate ANPR — entry point.

    python run.py setup     configure cameras (gate number + entry/exit)
    python run.py start     run cameras + dashboard
    python run.py web       dashboard only (no cameras)
    python run.py check     verify config, cameras and models
    python run.py camtest   live camera preview: what the system actually sees
    python run.py reset     wipe all recorded traffic and start clean
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time

from anpr import db
from anpr.config import (SystemConfig, CONFIG_PATH, DATA_DIR, ensure_dirs,
                         ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)-18s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("anpr")


def _add_file_log() -> None:
    """
    Mirror the console into <data>/anpr.log.

    When the launcher window is closed in a hurry, or the system is running
    unattended at a gate, the console output is gone. A log on disk is the
    only way to answer "why did it stop last night".
    """
    try:
        from logging.handlers import RotatingFileHandler

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        h = RotatingFileHandler(DATA_DIR / "anpr.log", maxBytes=2_000_000,
                                backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)-18s %(message)s"))
        logging.getLogger().addHandler(h)
    except Exception:
        pass          # logging must never be the reason the gate does not run


def port_is_busy(host: str, port: int) -> bool:
    """True if something is already listening. Checked before uvicorn starts."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        try:
            return s.connect_ex(("127.0.0.1", port)) == 0
        except OSError:
            return False


def _open_browser_when_ready(port: int, timeout: float = 120.0) -> None:
    """
    Open the dashboard once the server actually answers.

    The launcher used to open the browser straight away, which showed
    ERR_CONNECTION_REFUSED while Python was still starting — indistinguishable
    from a crash. Polling from inside the app is more reliable than doing it in
    a batch script, and works the same on Linux and the Jetson.
    """
    import socket
    import time as _t
    import webbrowser

    deadline = _t.time() + timeout
    while _t.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sk:
            sk.settimeout(0.5)
            if sk.connect_ex(("127.0.0.1", port)) == 0:
                try:
                    webbrowser.open(f"http://localhost:{port}")
                except Exception:
                    pass
                return
        _t.sleep(0.5)
    log.warning("dashboard did not come up within %ss", int(timeout))


def _port_busy_message(port: int) -> None:
    print(f"""
{'=' * 62}
  ⚠ المنفذ {port} مشغول — نسخة أخرى من النظام تعمل بالفعل.
  ⚠ Port {port} is already in use — another copy is running.
{'=' * 62}

  الحل / fix, pick one:

   ١. أغلق النافذة السوداء القديمة ثم أعد التشغيل.
      Close the older black window, then run this again.

   ٢. أو شغّل على منفذ آخر / or use another port:
      python run.py start --port {port + 1}

   ٣. أو حرّر المنفذ / or free the port (Windows):
      windows\\STOP-ALL.bat
""")


def cmd_setup(_args) -> int:
    from anpr.setup_wizard import main as wizard

    return wizard()


def _load_cfg() -> SystemConfig:
    try:
        return SystemConfig.load()
    except FileNotFoundError:
        print("\n⚠ لا يوجد ملف إعدادات. / No config yet.")
        print("   شغّل أولًا / run first:   python run.py setup\n")
        sys.exit(2)


def cmd_start(args) -> int:
    import uvicorn

    from anpr.pipeline import WorkerPool
    from anpr.web.app import create_app

    ensure_dirs()
    _add_file_log()
    cfg = _load_cfg()
    if getattr(args, "port", None):
        cfg.web_port = args.port
    db.init()

    # Check before opening cameras: uvicorn's bind error is buried under a
    # stack trace and people read it as "the program is broken".
    if port_is_busy(cfg.web_host, cfg.web_port):
        _port_busy_message(cfg.web_port)
        return 3

    pool = WorkerPool(cfg)
    if not args.no_cameras:
        # Start the cameras on a background thread so the dashboard is
        # reachable immediately. Loading the OCR models takes tens of seconds
        # the first time, and a browser opened during that window just shows
        # "connection refused", which reads as "the app is broken".
        threading.Thread(target=pool.start, name="pool-start",
                         daemon=True).start()

    app = create_app(cfg, pool)

    def shutdown(*_):
        log.info("stopping…")
        pool.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    if getattr(args, "open", False):
        threading.Thread(target=_open_browser_when_ready,
                         args=(cfg.web_port,), daemon=True).start()

    print(f"\n  البيانات / data:  {DATA_DIR}")
    print(f"  السجل / log:      {DATA_DIR / 'anpr.log'}")
    print(f"  لوحة التحكم / dashboard:  http://localhost:{cfg.web_port}")
    if not args.no_cameras:
        print("  الكاميرات تبدأ في الخلفية — قد تستغرق دقيقة أول مرة.")
        print("  Cameras start in the background; first run can take a minute.")
    print(f"  البوابات / gates: {cfg.gates or '—'}   "
          f"الكاميرات / cameras: {len(cfg.cameras)}\n")
    uvicorn.run(app, host=cfg.web_host, port=cfg.web_port, log_level="warning")
    pool.stop()
    return 0


def cmd_web(args) -> int:
    args.no_cameras = True
    return cmd_start(args)


def cmd_check(_args) -> int:
    from anpr.detector import PlateDetector
    from anpr.ocr import PlateReader

    cfg = _load_cfg()
    rc = cfg.recognition
    ok = True

    print("\n── الإعدادات / config " + "─" * 40)
    print(f"  file:    {CONFIG_PATH}")
    print(f"  data:    {DATA_DIR}")
    print(f"  site:    {cfg.site_name}")
    print(f"  gates:   {cfg.gates}")
    print(f"  cameras: {len(cfg.cameras)}")

    print("\n── النماذج / models " + "─" * 42)
    det = PlateDetector(rc.detector_backend,
                        str(ROOT / rc.plate_detector_weights),
                        rc.min_detect_conf, rc.device)
    rdr = PlateReader(rc.ocr_backend, str(ROOT / rc.char_detector_weights),
                      rc.device)
    print(f"  plate detector: {det.backend}")
    print(f"  plate reader:   {rdr.backend}")
    if det.backend == "classical":
        print("     ⚠ no trained detector weights — accuracy will be low until "
              "you train one (see README §7)")
        ok = False
    if rdr.backend == "stub":
        print("     ⚠ NO OCR INSTALLED. Run: pip install easyocr")
        ok = False

    print("\n── الكاميرات / cameras " + "─" * 39)
    from anpr.capture import probe

    for c in cfg.cameras:
        good, info = probe(c.source, timeout_ms=6000)
        mark = "✓" if good else "✗"
        print(f"  {mark} {c.id:<16} gate {c.gate_number} {c.direction:<6}"
              f" {info:<28} {c.source}")
        ok = ok and good

    conn = db.connect()
    n_v = conn.execute("SELECT COUNT(*) c FROM vehicles").fetchone()["c"]
    n_e = conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
    print(f"\n── قاعدة البيانات / database {'─' * 33}")
    print(f"  vehicles: {n_v}   events: {n_e}")
    print("\n" + ("✓ جاهز / ready" if ok else
                  "⚠ راجع التحذيرات أعلاه / review the warnings above") + "\n")
    return 0 if ok else 1


def cmd_reset(args) -> int:
    """
    Wipe recorded traffic so the database holds only what you want to keep.

    Deleting a database file by hand is exactly the step where someone deletes
    the wrong thing, so this shows the counts, names what goes, and asks.
    """
    from anpr.config import SNAPSHOT_DIR, DATASET_DIR

    conn = db.init()
    counts = {t: conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
              for t in ("events", "visits", "alerts", "vehicles")}

    print("\n" + "=" * 62)
    print("  الموجود حاليًا في قاعدة البيانات / current contents")
    print(f"  {db.DB_PATH}")
    print("=" * 62)
    for k, v in counts.items():
        print(f"    {k:<10} {v}")
    print()
    print("  سيتم حذف / will be deleted: events, visits, alerts")
    if args.all:
        print("  وأيضًا / and also: vehicles (السيارات المسجلة)")
    else:
        print("  ستبقى السيارات المسجلة / registered vehicles are kept")
        print("  (استخدم --all لحذفها أيضًا / use --all to clear them too)")
    if args.snapshots:
        print("  وأيضًا الصور المحفوظة / and saved snapshots")
    print()

    if not args.yes:
        try:
            ans = input("اكتب yes للتأكيد / type yes to confirm: ").strip().lower()
        except EOFError:
            ans = ""
        if ans not in ("yes", "y", "نعم"):
            print("ألغيت / cancelled — nothing was deleted.\n")
            return 1

    conn.execute("DELETE FROM alerts")
    conn.execute("DELETE FROM visits")
    conn.execute("DELETE FROM events")
    if args.all:
        conn.execute("DELETE FROM vehicles")
    conn.execute("DELETE FROM camera_status")
    conn.commit()
    conn.execute("VACUUM")

    if args.snapshots:
        import shutil

        for d in (SNAPSHOT_DIR, DATASET_DIR):
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
                d.mkdir(parents=True, exist_ok=True)

    left = conn.execute("SELECT COUNT(*) c FROM vehicles").fetchone()["c"]
    print(f"\n✓ تم المسح / cleared. السيارات المسجلة المتبقية / vehicles kept: {left}")
    print("  الخطوة التالية / next:  python run.py start\n")
    return 0


def cmd_camtest(args) -> int:
    """Live preview so a camera can be aimed before it is configured."""
    from anpr.web.preview import run_preview

    rec = None
    try:
        rec = SystemConfig.load().recognition
        if args.source == "config":
            cams = SystemConfig.load().cameras
            if not cams:
                print("لا توجد كاميرات في الإعدادات / no cameras configured")
                return 2
            args.source = cams[0].source
            print(f"using first configured camera: {cams[0].id}")
    except FileNotFoundError:
        pass
    if args.source == "config":
        args.source = "0"
    if port_is_busy("127.0.0.1", args.port):
        _port_busy_message(args.port)
        return 3
    return run_preview(args.source, args.port, args.rotate, rec)


def main() -> int:
    ap = argparse.ArgumentParser(prog="run.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("setup", help="configure cameras and gates")
    s = sub.add_parser("start", help="run cameras + dashboard")
    s.add_argument("--no-cameras", action="store_true")
    s.add_argument("--port", type=int, default=None)
    s.add_argument("--open", action="store_true",
                   help="open the dashboard in a browser once it is ready")
    w = sub.add_parser("web", help="dashboard only")
    w.add_argument("--port", type=int, default=None)
    sub.add_parser("check", help="verify config, cameras and models")
    ct = sub.add_parser("camtest", help="live camera preview in the browser")
    ct.add_argument("--source", default="0",
                    help='0 = laptop webcam, or an rtsp:// url, or "config" '
                         "to use the first configured camera")
    ct.add_argument("--port", type=int, default=8090)
    ct.add_argument("--rotate", type=int, default=0, choices=[0, 90, 180, 270])
    rs = sub.add_parser("reset", help="wipe recorded traffic, keep the system")
    rs.add_argument("--all", action="store_true",
                    help="also delete registered vehicles")
    rs.add_argument("--snapshots", action="store_true",
                    help="also delete saved snapshot images")
    rs.add_argument("--yes", action="store_true", help="skip the confirmation")

    args = ap.parse_args()
    fn = {"setup": cmd_setup, "start": cmd_start, "web": cmd_web,
          "check": cmd_check, "camtest": cmd_camtest,
          "reset": cmd_reset}.get(args.cmd)
    if fn is None:
        ap.print_help()
        return 1
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
