#!/usr/bin/env python3
"""
End-to-end tests. No cameras, no model weights, no network.

Covers the logic that actually decides whether the system is trustworthy:
plate normalisation, multi-frame voting, deduplication, known/unknown/blacklist
classification, entry->exit matching and stay duration, and the Excel importer.

Run:  python tests/test_pipeline.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path

# Point all data output at a temp dir BEFORE importing anpr.config, so a test
# run never leaves snapshots or a database inside the real project folder.
_TEST_DATA = Path(tempfile.mkdtemp(prefix="anpr-test-data-"))
os.environ["ANPR_DATA"] = str(_TEST_DATA)
os.environ["ANPR_DB"] = str(_TEST_DATA / "test.db")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from anpr import db, plate_text                                    # noqa: E402
from anpr.config import CameraConfig, SystemConfig, RecognitionConfig  # noqa: E402
from anpr.detector import PlateDetector                            # noqa: E402
from anpr.ocr import PlateReader, encode_marker, decode_marker      # noqa: E402
from anpr.pipeline import CameraWorker                              # noqa: E402
from anpr.tracker import PlateTracker, vote_weight                  # noqa: E402
from anpr.detector import PlateBox                                  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from make_test_plates import render_plate, make_scene               # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  — {detail}" if detail else ""))


# --------------------------------------------------------------------------
def test_plate_text() -> None:
    print("\n[1] نص اللوحة / plate text")

    check("Arabic digits -> ASCII",
          plate_text.normalize("ب ج د ١٢٣٤") == "بجد 1234",
          plate_text.normalize("ب ج د ١٢٣٤"))

    check("mixed order and spacing normalises the same",
          plate_text.normalize("١٢٣٤بجد") == plate_text.normalize("ب ج  د ١٢٣٤"))

    check("hamza forms unified",
          plate_text.normalize("أ ب ج ١٢٣") == plate_text.normalize("ا ب ج ١٢٣"))

    check("diacritics stripped",
          plate_text.normalize("بـجـد ١٢٣٤") == "بجد 1234")

    check("empty input is safe", plate_text.normalize("") == "")
    check("junk input is safe", plate_text.normalize("!!! ???") == "")

    check("transliteration",
          plate_text.transliterate("بجد 1234") == "B G D 1234",
          plate_text.transliterate("بجد 1234"))

    check("display uses Arabic digits",
          "١٢٣٤" in plate_text.display("بجد 1234"),
          plate_text.display("بجد 1234"))

    p_good = plate_text.plausibility("بجد 1234")
    p_bad = plate_text.plausibility("بجدرسصطع 12345678")
    check("plausible plate scores high", p_good >= 0.9, f"{p_good}")
    check("implausible plate scores low", p_bad < 0.3, f"{p_bad}")
    check("zero is penalised, not rejected",
          0 < plate_text.plausibility("بجد 1034") < p_good)

    nv = plate_text.near_variants("بجد 1234")
    check("near variants generated", len(nv) > 0, f"{len(nv)} variants")
    check("near variants exclude self", "بجد 1234" not in nv)

    check("well-formed check", plate_text.is_wellformed("بجد 1234"))
    check("rejects 5-letter plate", not plate_text.is_wellformed("بجدرس 1234"))


# --------------------------------------------------------------------------
def test_marker_codec() -> None:
    print("\n[2] ترميز الاختبار / test marker codec")
    for text in ["بجد 1234", "ىد 6716", "ا 1", "رمب 816"]:
        strip = encode_marker(text, 1280)
        img = np.dstack([np.vstack([np.full((40, 1280), 200, np.uint8), strip])] * 3)
        check(f"round-trip {text!r}", decode_marker(img) == text,
              repr(decode_marker(img)))
    check("blank image decodes to nothing",
          decode_marker(np.full((50, 300, 3), 255, np.uint8)) == "")


# --------------------------------------------------------------------------
def test_detector_and_reader() -> None:
    print("\n[3] الكشف والقراءة / detection + reading")
    det = PlateDetector("classical", "", min_conf=0.3)
    reader = PlateReader("stub")
    check("reader falls back to stub with no weights", reader.backend == "stub")

    hits = 0
    for i in range(20):
        plate, _ = render_plate(plate_text.normalize("بجد 1234"))
        scene = make_scene(plate, "بجد 1234", seed=i)
        if det.detect(scene):
            hits += 1
    check("classical detector finds plates in synthetic scenes",
          hits >= 18, f"{hits}/20 scenes")

    scene = make_scene(render_plate("بجد 1234")[0], "بجد 1234", seed=1)
    res = reader.read(scene)
    check("stub reader recovers ground truth", res.text == "بجد 1234", res.text)
    check("read has confidence", res.confidence > 0.5)
    check("score folds in plausibility", 0 < res.score <= 1)


# --------------------------------------------------------------------------
def test_opencv_compat() -> None:
    """
    Regression guard for a real field failure.

    cv2.HoughLinesP returns (N, 1, 4) on OpenCV 4 and (N, 4) on OpenCV 5.
    Code that indexed [:, 0] worked in development and crashed the camera
    worker on a user's machine the moment a plate appeared.
    """
    print("\n[4b] توافق OpenCV / OpenCV version compatibility")
    import cv2

    from anpr import detector as det_mod

    img = np.full((80, 200, 3), 240, np.uint8)
    cv2.line(img, (10, 40), (190, 47), (0, 0, 0), 3)
    real = cv2.HoughLinesP
    payload = np.array([[10, 40, 190, 47], [12, 41, 188, 48]], np.int32)
    try:
        for label, shaper in (("OpenCV 4 (N,1,4)", lambda a: a.reshape(-1, 1, 4)),
                              ("OpenCV 5 (N,4)", lambda a: a.reshape(-1, 4))):
            det_mod.cv2.HoughLinesP = lambda *a, **k: shaper(payload)
            try:
                out = det_mod.deskew(img)
                ok = out is not None and out.size > 0
            except Exception as exc:
                ok = False
                print(f"      {exc}")
            check(f"deskew survives {label}", ok)
        det_mod.cv2.HoughLinesP = lambda *a, **k: None
        check("deskew handles 'no lines found'",
              det_mod.deskew(img) is not None)
    finally:
        det_mod.cv2.HoughLinesP = real

    check("enhance() runs end to end", det_mod.enhance(img).size > 0)


# --------------------------------------------------------------------------
def test_voting() -> None:
    print("\n[4] التصويت متعدد الإطارات / multi-frame voting")
    tr = PlateTracker(min_votes=3)
    box = PlateBox(100, 100, 240, 170, 0.9)

    # Same car seen over 5 frames; frame 2 misreads one glyph.
    reads = ["بجد 1234", "بجد 1234", "بحد 1234", "بجد 1234", "بجد 1234"]
    for i, text in enumerate(reads):
        pairs = tr.update([box], now=float(i))
        for track, b in pairs:
            track.add_vote(text, vote_weight(0.9, 1.0, b.w, 1280))

    track = list(tr.tracks)[0]
    leader, weight, votes = track.leader()
    check("single misread does not win", leader == "بجد 1234", leader)
    check("votes accumulated", votes >= 4, f"{votes} votes")
    check("confirmed after threshold", len(tr.confirmed()) == 1)
    check("not confirmed twice", len(tr.confirmed()) == 0)

    # Below threshold -> nothing confirmed.
    tr2 = PlateTracker(min_votes=5)
    for i in range(3):
        for t, b in tr2.update([box], now=float(i)):
            t.add_vote("سنم 999", vote_weight(0.9, 1.0, b.w, 1280))
    check("below vote threshold stays silent", len(tr2.confirmed()) == 0)

    # Confusable-glyph votes get merged rather than splitting the vote.
    tr3 = PlateTracker(min_votes=3)
    for i, text in enumerate(["بجد 1234", "بجد 1234", "تجد 1234"]):
        for t, b in tr3.update([box], now=float(i)):
            t.add_vote(text, vote_weight(0.95, 1.0, b.w, 1280))
    t3 = list(tr3.tracks)[0]
    check("confusable variants merge into the leader",
          t3.leader()[2] == 3, f"{t3.votes}")

    # Two cars at once must not share a track.
    tr4 = PlateTracker(min_votes=2)
    b1, b2 = PlateBox(50, 50, 190, 120, .9), PlateBox(600, 300, 740, 370, .9)
    for i in range(3):
        for t, b in tr4.update([b1, b2], now=float(i)):
            t.add_vote("اا 111" if b.x1 < 300 else "بب 222",
                       vote_weight(0.9, 1.0, b.w, 1280))
    check("two vehicles tracked separately", len(list(tr4.tracks)) == 2,
          f"{len(list(tr4.tracks))} tracks")

    check("expired tracks are dropped",
          (lambda: [tr4.update([], now=float(20 + i)) for i in range(15)]
           and len(tr4.expired()) == 2)())

    check("size weighting: bigger plate counts more",
          vote_weight(0.9, 1.0, 200, 1280) > vote_weight(0.9, 1.0, 40, 1280))


# --------------------------------------------------------------------------
def test_database(tmp: Path) -> None:
    print("\n[5] قاعدة البيانات / database")
    conn = db.connect(tmp / "t.db")

    vid = db.upsert_vehicle(conn, plate="ب ج د ١٢٣٤", owner_name="محمد فؤاد",
                            phone="01000000000", unit="A-12", category="resident")
    check("vehicle inserted", vid > 0)

    same = db.upsert_vehicle(conn, plate="بجد1234", owner_name="محمد ف.")
    check("differently-typed plate updates the same row", same == vid)

    status, veh = db.classify(conn, "بجد 1234")
    check("registered car classified known", status == "known", status)
    check("unregistered car classified unknown",
          db.classify(conn, "سنم 9999")[0] == "unknown")

    db.upsert_vehicle(conn, plate="خطر 666", category="blacklist")
    check("blacklist detected", db.classify(conn, "خطر 666")[0] == "blacklist")

    db.upsert_vehicle(conn, plate="زور 111", category="visitor",
                      valid_until="2020-01-01")
    check("expired pass detected", db.classify(conn, "زور 111")[0] == "expired")

    found = db.search_vehicles(conn, q="محمد")
    check("search by owner name works", len(found) >= 1)


# --------------------------------------------------------------------------
def test_visits(tmp: Path) -> None:
    print("\n[6] الدخول والخروج ومدة البقاء / entry-exit matching")
    conn = db.connect(tmp / "v.db")
    db.upsert_vehicle(conn, plate="بجد 1234", owner_name="اختبار")

    t_in = db.now_local() - timedelta(hours=2, minutes=30)
    e1 = db.insert_event(conn, plate="بجد 1234", camera_id="c1", gate_number=1,
                         direction="entry", status="known", confidence=0.9,
                         when=t_in)
    db.register_passage(conn, dict(conn.execute(
        "SELECT * FROM events WHERE id=?", (e1,)).fetchone()))
    check("car shows as inside after entry", len(db.currently_inside(conn)) == 1)

    e2 = db.insert_event(conn, plate="بجد 1234", camera_id="c2", gate_number=2,
                         direction="exit", status="known", confidence=0.9)
    r = db.register_passage(conn, dict(conn.execute(
        "SELECT * FROM events WHERE id=?", (e2,)).fetchone()))
    check("visit closed on exit", len(db.currently_inside(conn)) == 0)
    check("duration ≈ 150 min", r["duration_min"] and 148 <= r["duration_min"] <= 152,
          f"{r['duration_min']} min")

    visits = db.list_visits(conn)
    check("exit gate recorded separately from entry gate",
          visits[0]["entry_gate"] == 1 and visits[0]["exit_gate"] == 2)

    # Exit with no entry (car got in before the system was running).
    e3 = db.insert_event(conn, plate="لام 777", camera_id="c2", gate_number=1,
                         direction="exit", status="unknown", confidence=0.8)
    r3 = db.register_passage(conn, dict(conn.execute(
        "SELECT * FROM events WHERE id=?", (e3,)).fetchone()))
    check("orphan exit handled without crashing", r3.get("orphan_exit") is True)

    # Double entry without an exit closes the stale visit.
    for _ in range(2):
        eid = db.insert_event(conn, plate="ددد 555", camera_id="c1",
                              gate_number=1, direction="entry",
                              status="unknown", confidence=0.9)
        db.register_passage(conn, dict(conn.execute(
            "SELECT * FROM events WHERE id=?", (eid,)).fetchone()))
    open_for_plate = [v for v in db.currently_inside(conn) if v["plate"] == "ددد 555"]
    check("re-entry does not create two open visits", len(open_for_plate) == 1,
          f"{len(open_for_plate)} open")

    # daily_stats counts TODAY only. The entry above is backdated 2.5 hours,
    # which lands on the previous day when the suite runs just after midnight.
    # Compare against what is actually dated today instead of a fixed number,
    # so the test measures the function and not the clock.
    today = db.now_local().date().isoformat()
    expect_in = conn.execute(
        "SELECT COUNT(*) c FROM events WHERE direction='entry' "
        "AND substr(ts,1,10)=?", (today,)).fetchone()["c"]
    expect_out = conn.execute(
        "SELECT COUNT(*) c FROM events WHERE direction='exit' "
        "AND substr(ts,1,10)=?", (today,)).fetchone()["c"]
    stats = db.daily_stats(conn)
    check("daily stats count today's entries and exits",
          stats["entries"] == expect_in and stats["exits"] == expect_out,
          f"in={stats['entries']}/{expect_in} out={stats['exits']}/{expect_out}")
    check("all five passages were stored",
          conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"] == 5)


# --------------------------------------------------------------------------
def test_worker(tmp: Path) -> None:
    print("\n[7] المسار الكامل / full camera pipeline")
    conn = db.connect(tmp / "w.db")
    db.upsert_vehicle(conn, plate="بجد 1234", owner_name="ساكن مسجل",
                      unit="B-4", category="resident")
    db.upsert_vehicle(conn, plate="خطر 666", category="blacklist")

    cfg = SystemConfig(recognition=RecognitionConfig(min_votes=3,
                                                     dedupe_seconds=60))
    cam = CameraConfig(id="gate1_entry", name="بوابة 1 دخول", source="0",
                       gate_number=1, direction="entry", min_plate_width_px=40)
    worker = CameraWorker(cam, cfg,
                          detector=PlateDetector("classical", "", 0.3),
                          reader=PlateReader("stub"))
    worker.cfg.collect_dataset = False

    def feed(plate_key: str, frames: int = 6, t0: float = 0.0):
        """
        Push one vehicle through the worker until it is confirmed.

        Uses whichever synthetic scene the classical detector can actually see.
        Pinning a single scene seed made this test fail whenever an unrelated
        change shifted the rendering by a few pixels — it was measuring the
        fallback detector's luck on one image, not the pipeline logic it is
        supposed to cover.
        """
        img, _ = render_plate(plate_key)
        for seed in range(12):
            scene = make_scene(img, plate_key, seed=seed)
            if worker.detector.detect(scene):
                break
        else:
            raise AssertionError(f"no synthetic scene detectable for {plate_key}")
        out = []
        for i in range(frames):
            out += worker.process_frame(scene, conn=conn, now=t0 + i)
        return out

    passages = feed("بجد 1234")
    check("known car produced exactly one event", len(passages) == 1,
          f"{len(passages)} events")
    if passages:
        p = passages[0]
        check("event carries the right gate number", p.gate_number == 1)
        check("event carries the right direction", p.direction == "entry")
        check("plate read correctly", p.plate == "بجد 1234", p.plate)
        check("multiple votes recorded", p.votes >= 3, f"{p.votes} votes")

    row = db.list_events(conn, limit=1)[0]
    check("event classified as known", row["status"] == "known", row["status"])
    check("event linked to the registered owner",
          row["owner_name"] == "ساكن مسجل")
    check("visit opened", len(db.currently_inside(conn)) == 1)

    # Same car still sitting in front of the camera -> no duplicate event.
    worker.tracker.reset()
    dup = feed("بجد 1234", t0=100)
    check("duplicate read suppressed inside dedupe window", len(dup) == 0,
          f"{len(dup)} extra events")

    # Unknown car -> alert.
    worker.tracker.reset()
    feed("سنم 9999", t0=200)
    alerts = db.open_alerts(conn)
    check("unknown car raises an alert",
          any(a["kind"] == "unknown" for a in alerts),
          f"{[a['kind'] for a in alerts]}")

    # Blacklisted car -> danger alert.
    worker.tracker.reset()
    feed("خطر 666", t0=300)
    alerts = db.open_alerts(conn)
    check("blacklisted car raises a danger alert",
          any(a["kind"] == "blacklist" and a["level"] == "danger" for a in alerts))

    db.ack_all_alerts(conn)
    check("alerts can be acknowledged", len(db.open_alerts(conn)) == 0)

    # Exit camera on another gate closes the visit.
    exit_cam = CameraConfig(id="gate2_exit", name="بوابة 2 خروج", source="0",
                            gate_number=2, direction="exit",
                            min_plate_width_px=40)
    w2 = CameraWorker(exit_cam, cfg, detector=PlateDetector("classical", "", 0.3),
                      reader=PlateReader("stub"))
    w2.cfg.collect_dataset = False
    img, _ = render_plate("بجد 1234")
    for seed in range(12):
        scene2 = make_scene(img, "بجد 1234", seed=seed)
        if w2.detector.detect(scene2):
            break
    for i in range(6):
        w2.process_frame(scene2, conn=conn, now=400 + i)
    inside = db.currently_inside(conn)
    check("exit at a different gate closes the visit",
          not any(v["plate"] == "بجد 1234" for v in inside))
    v = [x for x in db.list_visits(conn) if x["plate"] == "بجد 1234"][0]
    check("stay duration computed", v["duration_min"] is not None,
          f"{v['duration_min']} min")
    check("entry and exit gates both recorded",
          v["entry_gate"] == 1 and v["exit_gate"] == 2,
          f"in gate {v['entry_gate']} out gate {v['exit_gate']}")


# --------------------------------------------------------------------------
def test_roi_and_capture(tmp: Path) -> None:
    print("\n[7b] منطقة الاهتمام والاتصال / ROI + capture")
    from anpr.capture import normalise_source, open_capture

    check("webcam index parsed", normalise_source("0") == 0)
    check("rtsp url left alone",
          normalise_source("rtsp://a/b") == "rtsp://a/b")

    t0 = time.time()
    cap = open_capture("rtsp://192.0.2.1/nothing", timeout_ms=2000)
    elapsed = time.time() - t0
    check("dead RTSP address gives up instead of hanging",
          cap is None and elapsed < 25, f"{elapsed:.1f}s")

    conn = db.connect(tmp / "roi.db")
    cfg = SystemConfig(recognition=RecognitionConfig(min_votes=2))
    cam = CameraConfig(id="roi_cam", name="roi", source="0", gate_number=3,
                       direction="entry", min_plate_width_px=30,
                       roi=(0.0, 0.3, 1.0, 1.0))
    w = CameraWorker(cam, cfg, detector=PlateDetector("classical", "", 0.3),
                     reader=PlateReader("stub"))
    w.cfg.collect_dataset = False
    img, _ = render_plate("عفق 4321")
    events = []
    for i in range(6):
        events += w.process_frame(make_scene(img, "عفق 4321", seed=3),
                                  conn=conn, now=float(i))
    check("plate still found when a ROI crop is set", len(events) == 1,
          f"{len(events)} events")
    if events:
        check("ROI camera records its own gate number",
              events[0].gate_number == 3)

    # A ROI that excludes the plate must produce nothing, not a wrong read.
    cam2 = CameraConfig(id="roi_top", name="roi2", source="0", gate_number=4,
                        direction="entry", min_plate_width_px=30,
                        roi=(0.0, 0.0, 1.0, 0.15))
    w2 = CameraWorker(cam2, cfg, detector=PlateDetector("classical", "", 0.3),
                      reader=PlateReader("stub"))
    w2.cfg.collect_dataset = False
    out = []
    for i in range(6):
        out += w2.process_frame(make_scene(img, "عفق 4321", seed=3),
                                conn=conn, now=float(i))
    check("ROI excluding the plate yields no events", len(out) == 0,
          f"{len(out)} events")


# --------------------------------------------------------------------------
def test_import_and_web(tmp: Path) -> None:
    print("\n[8] الاستيراد وواجهة الويب / import + web")
    from anpr.web.app import create_app, _read_csv, _read_xlsx

    conn = db.connect(tmp / "i.db")

    csv_bytes = ("plate,owner_name,phone,unit,category\n"
                 "ب ج د ١١١١,أحمد,0100,A-1,resident\n"
                 "س ن م ٢٢٢٢,منى,0101,A-2,staff\n"
                 "خ ط ر ٣٣٣,,,,blacklist\n").encode("utf-8")
    rows = _read_csv(csv_bytes)
    check("CSV parsed", len(rows) == 3, f"{len(rows)} rows")
    res = db.bulk_import(conn, rows)
    check("CSV imported", res["imported"] == 3, str(res))
    check("imported plate is findable",
          db.find_vehicle(conn, "بجد 1111") is not None)
    check("imported blacklist works",
          db.classify(conn, "خطر 333")[0] == "blacklist")

    ar_csv = ("رقم اللوحة,اسم المالك,الوحدة\n"
              "ل م ن ٤٤٤٤,خالد,C-9\n").encode("utf-8")
    rows = _read_csv(ar_csv)
    check("Arabic column headers recognised",
          len(rows) == 1 and rows[0].get("owner_name") == "خالد", str(rows))

    bad = db.bulk_import(conn, [{"plate": "", "owner_name": "x"},
                                {"plate": "ا ب ١", "owner_name": "y"}])
    check("bad rows reported not crashed",
          bad["failed"] == 1 and bad["imported"] == 1, str(bad))

    # xlsx round-trip through the shipped template.
    from openpyxl import Workbook
    import io

    wb = Workbook(); ws = wb.active
    ws.append(["plate", "owner_name", "category"])
    ws.append(["ع ف ق ٧٧٧", "سارة", "vip"])
    buf = io.BytesIO(); wb.save(buf)
    rows = _read_xlsx(buf.getvalue())
    check("xlsx parsed", len(rows) == 1 and rows[0]["owner_name"] == "سارة")

    cfg = SystemConfig(cameras=[CameraConfig("c1", "cam", "0", 1, "entry")])
    app = create_app(cfg)
    import anpr.config as _cfgmod
    cfg_path = tmp / "settings.yaml"
    _orig_path = _cfgmod.CONFIG_PATH
    _cfgmod.CONFIG_PATH = cfg_path
    try:
        from fastapi.testclient import TestClient

        client = TestClient(app)
        for path in ["/", "/events", "/vehicles", "/reports", "/api/live",
                     "/api/health", "/vehicles/template.xlsx",
                     "/export/events.csv"]:
            r = client.get(path)
            check(f"GET {path}", r.status_code == 200, f"HTTP {r.status_code}")
        r = client.get("/")
        check("dashboard is RTL Arabic",
              'dir="rtl"' in r.text and "المباشر" in r.text)

        print("\n[8a] البحث في السجل / event search")
        sconn = db.connect()
        for pl in ("طنب 395", "طنب 3951", "بجد 1234"):
            db.insert_event(sconn, plate=pl, camera_id="c1", gate_number=1,
                            direction="entry", status="unknown", confidence=0.9)

        # The gate <select> submits gate= (empty) whenever "الكل" is chosen.
        # Declaring it as int made FastAPI 422 the whole search.
        r = client.get("/events?plate=&gate=&direction=&status="
                       "&date_from=&date_to=")
        check("search with empty gate does not 422", r.status_code == 200,
              f"HTTP {r.status_code}")
        r = client.get("/events?gate=1")
        check("search with a gate number works", r.status_code == 200,
              f"HTTP {r.status_code}")
        r = client.get("/events?gate=abc")
        check("nonsense gate is ignored, not fatal", r.status_code == 200,
              f"HTTP {r.status_code}")
        r = client.get("/export/events.csv?gate=&status=&date_from=&date_to=")
        check("CSV export with empty gate works", r.status_code == 200,
              f"HTTP {r.status_code}")

        for query, expect in [("395", 2), ("طنب", 2), ("ط ن ب ٣٩٥", 2),
                              ("طن 39", 2), ("بجد", 1), ("9999", 0)]:
            rows = db.list_events(sconn, plate=query)
            check(f"plate search {query!r} finds {expect}",
                  len(rows) == expect, f"{len(rows)} hits")

        print("\n[8b] صفحة الإعدادات / settings page")
        r = client.get("/settings")
        check("GET /settings", r.status_code == 200, f"HTTP {r.status_code}")
        check("settings page asks the two defining questions",
              "رقم البوابة" in r.text and "الاتجاه" in r.text)

        form = {"id": "gate3_exit", "name": "بوابة ٣ خروج",
                "source": "rtsp://x/y", "gate_number": "3",
                "direction": "exit", "enabled": "1",
                "min_plate_width_px": "60", "fps_limit": "8", "rotate": "0",
                "roi_x1": "0", "roi_y1": "0", "roi_x2": "1", "roi_y2": "1"}
        client.post("/settings/camera", data=form, follow_redirects=False)
        added = cfg.camera("gate3_exit")
        check("camera added through the web form", added is not None)
        check("added camera keeps its gate number",
              added and added.gate_number == 3)
        check("added camera keeps its direction",
              added and added.direction == "exit")
        check("Arabic camera name survives the form",
              added and added.name == "بوابة ٣ خروج", added.name if added else "")

        client.post("/settings/camera",
                    data=dict(form, original_id="gate3_exit",
                              gate_number="9", direction="entry"),
                    follow_redirects=False)
        after = cfg.camera("gate3_exit")
        check("gate number changed 3 -> 9", after.gate_number == 9,
              str(after.gate_number))
        check("direction changed exit -> entry", after.direction == "entry")

        client.post("/settings/camera",
                    data=dict(form, id="bad_cam", direction="sideways"),
                    follow_redirects=False)
        check("invalid direction rejected", cfg.camera("bad_cam") is None)

        before = len(cfg.cameras)
        client.post("/settings/camera", data=dict(form, id="c1"),
                    follow_redirects=False)
        check("duplicate camera id rejected", len(cfg.cameras) == before,
              f"{len(cfg.cameras)} cameras")

        client.post("/settings/site",
                    data={"site_name": "موقع جديد", "alert_on_unknown": "1",
                          "alert_on_blacklist": "", "live_view": "",
                          "collect_dataset": "1", "min_votes": "5",
                          "min_accept_conf": "0.6", "dedupe_seconds": "45",
                          "min_detect_conf": "0.4"},
                    follow_redirects=False)
        check("site name saved", cfg.site_name == "موقع جديد", cfg.site_name)
        check("min_votes saved", cfg.recognition.min_votes == 5)
        check("live view can be switched off", cfg.live_view is False)

        check("settings written to disk", cfg_path.exists())
        reloaded = SystemConfig.load(cfg_path)
        check("reload from disk keeps everything",
              reloaded.site_name == "موقع جديد"
              and reloaded.camera("gate3_exit").gate_number == 9,
              f"{reloaded.site_name}, gates {reloaded.gates}")

        client.post("/settings/camera/gate3_exit/delete",
                    follow_redirects=False)
        check("camera deleted", cfg.camera("gate3_exit") is None)
        check("deletion persisted",
              SystemConfig.load(cfg_path).camera("gate3_exit") is None)
    except ImportError:
        print("  … httpx not installed, skipping HTTP route checks")
    finally:
        _cfgmod.CONFIG_PATH = _orig_path


# --------------------------------------------------------------------------
def test_config(tmp: Path) -> None:
    print("\n[9] الإعدادات / config")
    cfg = SystemConfig(site_name="اختبار", cameras=[
        CameraConfig("g1_in", "بوابة ١ دخول", "rtsp://x", 1, "entry"),
        CameraConfig("g1_out", "بوابة ١ خروج", "rtsp://y", 1, "exit"),
        CameraConfig("g2_in", "بوابة ٢ دخول", "rtsp://z", 2, "entry"),
    ])
    p = cfg.save(tmp / "c.yaml")
    back = SystemConfig.load(p)
    check("config round-trips", back.site_name == "اختبار")
    check("cameras preserved", len(back.cameras) == 3)
    check("gate numbers preserved", back.gates == [1, 2], str(back.gates))
    check("direction preserved", back.camera("g1_out").direction == "exit")
    check("Arabic names survive round-trip",
          back.camera("g1_in").name == "بوابة ١ دخول")

    try:
        CameraConfig("bad", "x", "0", 1, "sideways").validate()
        check("invalid direction rejected", False)
    except ValueError:
        check("invalid direction rejected", True)

    try:
        SystemConfig(cameras=[CameraConfig("dup", "a", "0", 1, "entry"),
                              CameraConfig("dup", "b", "0", 1, "exit")]).validate()
        check("duplicate camera id rejected", False)
    except ValueError:
        check("duplicate camera id rejected", True)


# --------------------------------------------------------------------------
def test_misread_tolerance(tmp: Path) -> None:
    """
    The two failures reported from the live site.

    1. The reader drops or duplicates a glyph, so the same car is read several
       different ways and no reading ever gathers enough votes.
    2. The occupancy count only ever climbs, because an exit read one glyph
       differently from its entry never matches it.

    The readings below are the ones the site's own camera actually produced for
    a single car whose plate is مجب 451.
    """
    print("\n[10] القراءات غير المكتملة / tolerating a misread glyph")

    check("one dropped glyph still reads as the same plate",
          plate_text.same_plate("مب 451", "مجب 451"))
    check("one dropped digit still reads as the same plate",
          plate_text.same_plate("مجب 41", "مجب 451"))
    check("two different plates are not confused",
          not plate_text.same_plate("مجب 451", "بجا 249"))
    check("a plate with no digits matches nothing but itself",
          not plate_text.same_plate("م 451", "451"))
    check("the fuller spelling is preferred",
          plate_text.richer("مب 451", "مجب 451") == "مجب 451")
    check("an invented extra letter is not preferred",
          plate_text.richer("مجببع 451", "مجب 451") == "مجب 451")

    # -- votes must gather on one plate, not scatter across its misreadings --
    tr = PlateTracker(min_votes=2)
    box = PlateBox(400, 300, 560, 380, 0.9)
    seen = ["مب 451", "مجب 451", "مب 41", "مب 41", "مب 451",
            "م 451", "مجب 451", "مجب 451"]
    for i, text in enumerate(seen):
        for track, b in tr.update([box], now=float(i)):
            track.add_vote(text, vote_weight(0.7, 1.0, b.w))
    leader, _, votes = list(tr.tracks)[0].leader()
    check("misreadings of one plate vote together", leader == "مجب 451", leader)
    check("votes reach the threshold", votes >= len(seen) - 1, f"{votes} votes")

    # -- one plate, several boxes, must stay one vehicle ---------------------
    tr2 = PlateTracker(min_votes=2)
    tight, loose = PlateBox(400, 305, 555, 375, .9), PlateBox(392, 296, 566, 388, .8)
    half = PlateBox(400, 300, 480, 380, .7)
    for i in range(4):
        for track, b in tr2.update([tight, loose, half], now=float(i)):
            track.add_vote("مجب 451", vote_weight(0.7, 1.0, b.w))
    check("overlapping boxes on one plate stay one track",
          len(list(tr2.tracks)) == 1, f"{len(list(tr2.tracks))} tracks")

    # -- the occupancy count must come back down -----------------------------
    conn = db.connect(tmp / "misread.db")
    e1 = db.insert_event(conn, plate="مجب 451", camera_id="in", gate_number=1,
                         direction="entry", status="unknown", confidence=0.7)
    db.register_passage(conn, dict(conn.execute(
        "SELECT * FROM events WHERE id=?", (e1,)).fetchone()))
    check("entry counted", db.daily_stats(conn)["inside"] == 1)

    e2 = db.insert_event(conn, plate="مب 451", camera_id="out", gate_number=1,
                         direction="exit", status="unknown", confidence=0.7)
    r = db.register_passage(conn, dict(conn.execute(
        "SELECT * FROM events WHERE id=?", (e2,)).fetchone()))
    check("exit read one glyph short still closes the visit",
          db.daily_stats(conn)["inside"] == 0 and not r.get("orphan_exit"))

    e3 = db.insert_event(conn, plate="سنم 782", camera_id="in", gate_number=1,
                         direction="entry", status="unknown", confidence=0.7)
    db.register_passage(conn, dict(conn.execute(
        "SELECT * FROM events WHERE id=?", (e3,)).fetchone()))
    e4 = db.insert_event(conn, plate="بجا 249", camera_id="out", gate_number=1,
                         direction="exit", status="unknown", confidence=0.7)
    r4 = db.register_passage(conn, dict(conn.execute(
        "SELECT * FROM events WHERE id=?", (e4,)).fetchone()))
    check("a different car's exit does not release the wrong visit",
          db.daily_stats(conn)["inside"] == 1 and r4.get("orphan_exit") is True)

    # -- a repeat read replaces the logged one instead of adding a row -------
    conn2 = db.connect(tmp / "improve.db")
    bad = db.insert_event(conn2, plate="م 41", camera_id="in", gate_number=1,
                          direction="entry", status="unknown", confidence=0.30)
    dup = db.recent_event(conn2, "مب 41", "in", 60)
    check("a near-identical read is recognised as the same car",
          dup is not None and dup["id"] == bad)
    check("a read from another camera is not deduped against it",
          db.recent_event(conn2, "م 41", "out", 60) is None)
    db.improve_event(conn2, bad, plate="مجب 451", confidence=0.71,
                     ocr_confidence=0.71, plausibility=1.0, votes=4)
    rows = db.list_events(conn2)
    check("the better read replaces the logged one, no second row",
          len(rows) == 1 and rows[0]["plate"] == "مجب 451", f"{len(rows)} rows")
    check("a worse read never overwrites a better one",
          db.improve_event(conn2, bad, plate="م 4", confidence=0.2) is False)

    # -- a consistent misread must still reach its owner ---------------------
    conn3 = db.connect(tmp / "suggest.db")
    db.upsert_vehicle(conn3, plate="نطب 395", owner_name="محمد فؤاد")
    check("a plate one glyph off is still classed unknown",
          db.classify(conn3, "بطب 395")[0] == "unknown")
    near = db.near_vehicle(conn3, "بطب 395")
    check("...but the registered car it is probably a misread of is found",
          near is not None and near["plate"] == "نطب 395")
    check("an unrelated plate suggests nothing",
          db.near_vehicle(conn3, "سنم 782") is None)
    db.upsert_vehicle(conn3, plate="تطب 395", owner_name="جار")
    check("two equally close cars suggest nothing rather than guessing",
          db.near_vehicle(conn3, "بطب 395") is None)


# --------------------------------------------------------------------------
def test_direction_inference(tmp: Path) -> None:
    """A camera set to `both` has to be able to record an exit."""
    print("\n[11] استنتاج الاتجاه / direction on a two-way camera")
    cfg = SystemConfig(recognition=RecognitionConfig(min_votes=2))
    cam = CameraConfig(id="both1", name="كاميرا", source="0", gate_number=1,
                       direction="both")
    worker = CameraWorker(cam, cfg, detector=PlateDetector("classical", "", 0.3),
                          reader=PlateReader("stub"))

    class _T:
        def __init__(self, first_w, now_w):
            self.first_w = first_w
            self.box = PlateBox(0, 0, now_w, 40, 0.9)

    check("plate growing toward the camera is an entry",
          worker._infer_direction(_T(60, 150)) == "entry")
    check("plate shrinking away from the camera is an exit",
          worker._infer_direction(_T(150, 60)) == "exit",
          worker._infer_direction(_T(150, 60)))
    check("a plate that barely changes size is not called an exit",
          worker._infer_direction(_T(120, 124)) == "entry")


# --------------------------------------------------------------------------
def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="anpr-test-"))
    print("=" * 66)
    print("  اختبارات نظام البوابات / Gate ANPR test suite")
    print("=" * 66)
    try:
        test_plate_text()
        test_marker_codec()
        test_opencv_compat()
        test_detector_and_reader()
        test_voting()
        test_database(tmp)
        test_visits(tmp)
        test_worker(tmp)
        test_roi_and_capture(tmp)
        test_import_and_web(tmp)
        test_config(tmp)
        test_misread_tolerance(tmp)
        test_direction_inference(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(_TEST_DATA, ignore_errors=True)

    print("\n" + "=" * 66)
    print(f"  ✓ نجح / passed: {len(PASS)}     ✗ فشل / failed: {len(FAIL)}")
    if FAIL:
        print("\n  الاختبارات الفاشلة / failing:")
        for f in FAIL:
            print(f"    ✗ {f}")
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
