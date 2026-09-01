"""Arabic (RTL) dashboard: live log, alerts, vehicle registry, reports."""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Form, Request, UploadFile, File
from fastapi.responses import (HTMLResponse, JSONResponse, RedirectResponse,
                               StreamingResponse, FileResponse)
from fastapi.templating import Jinja2Templates

from .. import db, plate_text
from ..config import (CameraConfig, SystemConfig, SNAPSHOT_DIR,
                      ensure_dirs, DIRECTION_AR, DIRECTIONS, DATA_DIR)

log = logging.getLogger(__name__)
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

CATEGORIES = {
    "resident": "ساكن",
    "staff": "موظف",
    "visitor": "زائر",
    "vip": "VIP",
    "blacklist": "محظور",
}
STATUS_AR = {
    "known": "مسجلة", "unknown": "غير مسجلة",
    "blacklist": "محظورة", "expired": "تصريح منتهي",
}


def _as_gate(value: str) -> int | None:
    """
    Parse the gate filter from a query string.

    An HTML <select> with "الكل" selected submits `gate=`, an empty string.
    Typing that straight into `gate: int | None` makes FastAPI reject the whole
    request with a 422 — the search form breaks the moment someone searches
    without picking a gate, which is the common case.
    """
    value = (value or "").strip()
    if not value:
        return None
    try:
        n = int(value)
    except ValueError:
        return None
    return n if n > 0 else None


def create_app(cfg: SystemConfig, pool=None) -> FastAPI:
    ensure_dirs()
    app = FastAPI(title="ANPR Gate", docs_url=None, redoc_url=None)
    app.state.cfg = cfg
    app.state.pool = pool

    TEMPLATES.env.globals.update(
        site_name=cfg.site_name,
        categories=CATEGORIES,
        status_ar=STATUS_AR,
        direction_ar=DIRECTION_AR,
        pdisplay=plate_text.display,
        translit=plate_text.transliterate,
        gates=cfg.gates,
    )

    def ctx(request: Request, **kw):
        """Starlette >=0.29 wants (request, name, context)."""
        return {"request": request, **kw}

    # ---------------- pages ----------------

    @app.get("/", response_class=HTMLResponse)
    def live(request: Request):
        conn = db.connect()
        return TEMPLATES.TemplateResponse(request, "live.html", ctx(
            request,
            page="live",
            events=db.list_events(conn, limit=40),
            alerts=db.open_alerts(conn),
            stats=db.daily_stats(conn),
            cameras=db.camera_statuses(conn),
            cams_cfg={c.id: c for c in cfg.cameras if c.enabled},
            live_enabled=getattr(cfg, 'live_view', True),
        ))

    @app.get("/events", response_class=HTMLResponse)
    def events(request: Request, gate: str = "", direction: str = "",
               status: str = "", plate: str = "", date_from: str = "",
               date_to: str = "", page: int = 1):
        conn = db.connect()
        per = 50
        rows = db.list_events(conn, limit=per, offset=(page - 1) * per,
                              gate=_as_gate(gate), direction=direction,
                              status=status, plate=plate,
                              date_from=date_from, date_to=date_to)
        return TEMPLATES.TemplateResponse(request, "events.html", ctx(
            request, page="events", events=rows,
            filters=dict(gate=gate or "", direction=direction, status=status,
                         plate=plate, date_from=date_from, date_to=date_to),
            page_no=page, has_next=len(rows) == per,
        ))

    @app.get("/vehicles", response_class=HTMLResponse)
    def vehicles(request: Request, q: str = "", category: str = "",
                 msg: str = "", err: str = ""):
        conn = db.connect()
        return TEMPLATES.TemplateResponse(request, "vehicles.html", ctx(
            request, page="vehicles",
            vehicles=db.search_vehicles(conn, q, category),
            q=q, category=category, msg=msg, err=err,
        ))

    # ---------------- settings ----------------

    @app.get("/settings", response_class=HTMLResponse)
    def settings(request: Request, msg: str = "", err: str = ""):
        pool = app.state.pool
        running = {w.cam.id for w in (getattr(pool, "workers", []) or [])}
        return TEMPLATES.TemplateResponse(request, "settings.html", ctx(
            request, page="settings", cfg=cfg, cameras=cfg.cameras,
            running=running, msg=msg, err=err, directions=DIRECTIONS,
            data_dir=str(DATA_DIR), can_restart=pool is not None,
        ))

    def _persist_and_apply(restart: bool = True) -> str:
        """Write cameras.yaml, refresh the UI, and restart the camera threads."""
        cfg.validate()
        cfg.save()
        TEMPLATES.env.globals.update(gates=cfg.gates)
        if restart and app.state.pool is not None:
            app.state.pool.restart(cfg)
            return "تم الحفظ وإعادة تشغيل الكاميرات"
        return "تم الحفظ — أعد تشغيل النظام لتطبيق التغيير"

    @app.post("/settings/camera")
    def save_camera(
        original_id: str = Form(""),
        id: str = Form(...),
        name: str = Form(...),
        source: str = Form(...),
        gate_number: int = Form(...),
        direction: str = Form(...),
        enabled: str = Form(""),
        min_plate_width_px: int = Form(0),   # ignored, see config.py
        fps_limit: float = Form(8.0),
        rotate: int = Form(0),
        roi_x1: float = Form(0.0), roi_y1: float = Form(0.0),
        roi_x2: float = Form(1.0), roi_y2: float = Form(1.0),
    ):
        cam_id = (id or "").strip()
        try:
            if not cam_id:
                raise ValueError("المعرّف مطلوب / id is required")
            new = CameraConfig(
                id=cam_id, name=name.strip() or cam_id, source=source.strip(),
                gate_number=int(gate_number), direction=direction,
                enabled=bool(enabled),
                roi=(max(0.0, min(roi_x1, 1.0)), max(0.0, min(roi_y1, 1.0)),
                     max(0.0, min(roi_x2, 1.0)), max(0.0, min(roi_y2, 1.0))),
                min_plate_width_px=0,
                rotate=int(rotate), fps_limit=float(fps_limit))
            new.validate()

            existing = [c for c in cfg.cameras if c.id == (original_id or cam_id)]
            if existing:
                cfg.cameras[cfg.cameras.index(existing[0])] = new
            else:
                if any(c.id == cam_id for c in cfg.cameras):
                    raise ValueError(f"المعرّف مستخدم بالفعل / id already used: {cam_id}")
                cfg.cameras.append(new)
            note = _persist_and_apply()
            return RedirectResponse(f"/settings?msg={note}", status_code=303)
        except Exception as exc:
            return RedirectResponse(f"/settings?err={exc}", status_code=303)

    @app.post("/settings/camera/{camera_id}/delete")
    def delete_camera(camera_id: str):
        try:
            cfg.cameras[:] = [c for c in cfg.cameras if c.id != camera_id]
            note = _persist_and_apply()
            return RedirectResponse(f"/settings?msg=تم حذف الكاميرا — {note}",
                                    status_code=303)
        except Exception as exc:
            return RedirectResponse(f"/settings?err={exc}", status_code=303)

    @app.post("/settings/site")
    def save_site(
        site_name: str = Form(...),
        alert_on_unknown: str = Form(""),
        alert_on_blacklist: str = Form(""),
        live_view: str = Form(""),
        collect_dataset: str = Form(""),
        min_votes: int = Form(3),
        min_accept_conf: float = Form(0.55),
        dedupe_seconds: int = Form(60),
        min_detect_conf: float = Form(0.35),
    ):
        try:
            cfg.site_name = site_name.strip() or cfg.site_name
            cfg.alert_on_unknown = bool(alert_on_unknown)
            cfg.alert_on_blacklist = bool(alert_on_blacklist)
            cfg.live_view = bool(live_view)
            cfg.collect_dataset = bool(collect_dataset)
            cfg.recognition.min_votes = max(1, int(min_votes))
            cfg.recognition.min_accept_conf = float(min_accept_conf)
            cfg.recognition.dedupe_seconds = max(1, int(dedupe_seconds))
            cfg.recognition.min_detect_conf = float(min_detect_conf)
            TEMPLATES.env.globals.update(site_name=cfg.site_name)
            note = _persist_and_apply()
            return RedirectResponse(f"/settings?msg={note}", status_code=303)
        except Exception as exc:
            return RedirectResponse(f"/settings?err={exc}", status_code=303)

    @app.post("/settings/restart")
    def restart_cameras():
        if app.state.pool is None:
            return RedirectResponse(
                "/settings?err=الكاميرات غير مشغّلة في هذه الجلسة",
                status_code=303)
        app.state.pool.restart(cfg)
        return RedirectResponse("/settings?msg=أُعيد تشغيل الكاميرات",
                                status_code=303)

    @app.get("/reports", response_class=HTMLResponse)
    def reports(request: Request, day: str = ""):
        conn = db.connect()
        day = day or db.now_local().date().isoformat()
        return TEMPLATES.TemplateResponse(request, "reports.html", ctx(
            request, page="reports", day=day,
            stats=db.daily_stats(conn, day),
            hourly=db.hourly_counts(conn, day),
            inside=db.currently_inside(conn),
            visits=db.list_visits(conn, limit=100),
        ))

    # ---------------- live polling ----------------

    @app.get("/api/live")
    def api_live(after: int = 0):
        conn = db.connect()
        rows = db.list_events(conn, limit=30)
        new = [_event_json(r) for r in rows if r["id"] > after]
        alerts = [dict(a) for a in db.open_alerts(conn)]
        cams = [dict(c) for c in db.camera_statuses(conn)]
        return JSONResponse({
            "events": new,
            "last_id": rows[0]["id"] if rows else after,
            "alerts": alerts,
            "alert_count": len(alerts),
            "stats": db.daily_stats(conn),
            "cameras": cams,
        })

    def _event_json(r) -> dict:
        d = dict(r)
        d["plate_display"] = plate_text.display(r["plate"])
        d["plate_latin"] = plate_text.transliterate(r["plate"])
        d["status_ar"] = STATUS_AR.get(r["status"], r["status"])
        d["direction_ar"] = DIRECTION_AR.get(r["direction"], r["direction"])
        cam = cfg.camera(r["camera_id"])
        d["camera_name"] = cam.name if cam else r["camera_id"]
        return d

    # ---------------- actions ----------------

    @app.post("/alerts/{alert_id}/ack")
    def ack(alert_id: int):
        db.ack_alert(db.connect(), alert_id)
        return {"ok": True}

    @app.post("/alerts/ack_all")
    def ack_all():
        db.ack_all_alerts(db.connect())
        return {"ok": True}

    @app.post("/events/{event_id}/correct")
    def correct(event_id: int, plate: str = Form(...)):
        db.correct_event(db.connect(), event_id, plate)
        return RedirectResponse("/events", status_code=303)

    @app.post("/events/{event_id}/register")
    def register_from_snapshot(
        event_id: int,
        plate: str = Form(...),
        owner_name: str = Form(""),
        phone: str = Form(""),
        unit: str = Form(""),
        category: str = Form("resident"),
        car_make: str = Form(""),
        car_color: str = Form(""),
        valid_until: str = Form(""),
        notes: str = Form(""),
    ):
        """Guard sees an unknown car in the log and registers it in one click."""
        conn = db.connect()
        ev = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        vid = db.upsert_vehicle(
            conn, plate=plate, owner_name=owner_name, phone=phone, unit=unit,
            category=category, car_make=car_make, car_color=car_color,
            valid_until=valid_until or None, notes=notes,
            photo_path=ev["plate_crop"] if ev else None)
        # Re-classify this event and any other recent events for the same plate.
        norm = plate_text.normalize(plate)
        status, _ = db.classify(conn, norm)
        conn.execute(
            "UPDATE events SET vehicle_id=?, status=? "
            "WHERE plate=? AND vehicle_id IS NULL", (vid, status, norm))
        conn.execute("UPDATE visits SET vehicle_id=? WHERE plate=? AND "
                     "vehicle_id IS NULL", (vid, norm))
        conn.commit()
        return RedirectResponse(
            f"/vehicles?msg=تم تسجيل السيارة {plate_text.display(norm)}",
            status_code=303)

    @app.post("/vehicles/add")
    def add_vehicle(
        plate: str = Form(...),
        owner_name: str = Form(""),
        phone: str = Form(""),
        unit: str = Form(""),
        category: str = Form("resident"),
        car_make: str = Form(""),
        car_color: str = Form(""),
        valid_until: str = Form(""),
        notes: str = Form(""),
        vehicle_id: str = Form(""),
    ):
        conn = db.connect()
        try:
            db.upsert_vehicle(conn, plate=plate, owner_name=owner_name,
                              phone=phone, unit=unit, category=category,
                              car_make=car_make, car_color=car_color,
                              valid_until=valid_until or None, notes=notes)
            norm = plate_text.normalize(plate)
            status, _ = db.classify(conn, norm)
            conn.execute("UPDATE events SET status=? WHERE plate=? AND "
                         "status='unknown'", (status, norm))
            conn.commit()
            return RedirectResponse(f"/vehicles?msg=تم حفظ {plate_text.display(norm)}",
                                    status_code=303)
        except Exception as exc:
            return RedirectResponse(f"/vehicles?err={exc}", status_code=303)

    @app.post("/vehicles/{vehicle_id}/delete")
    def del_vehicle(vehicle_id: int):
        db.delete_vehicle(db.connect(), vehicle_id)
        return RedirectResponse("/vehicles?msg=تم الحذف", status_code=303)

    @app.post("/vehicles/import")
    async def import_vehicles(file: UploadFile = File(...)):
        """Bulk import from .xlsx or .csv."""
        raw = await file.read()
        name = (file.filename or "").lower()
        try:
            rows = (_read_xlsx(raw) if name.endswith((".xlsx", ".xlsm"))
                    else _read_csv(raw))
        except Exception as exc:
            return RedirectResponse(f"/vehicles?err=تعذّرت قراءة الملف: {exc}",
                                    status_code=303)
        result = db.bulk_import(db.connect(), rows)
        msg = f"تم استيراد {result['imported']} سيارة"
        if result["failed"]:
            msg += f" — فشل {result['failed']}"
        return RedirectResponse(f"/vehicles?msg={msg}", status_code=303)

    @app.get("/vehicles/template.xlsx")
    def import_template():
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "vehicles"
        headers = ["plate", "owner_name", "phone", "unit", "category",
                   "car_make", "car_color", "valid_until", "notes"]
        arabic = ["رقم اللوحة", "اسم المالك", "الهاتف", "الوحدة/الشقة",
                  "الفئة", "الماركة", "اللون", "صالح حتى", "ملاحظات"]
        ws.append(headers)
        ws.append(arabic)
        ws.append(["ب ج د ١٢٣٤", "محمد فؤاد", "01000000000", "A-12",
                   "resident", "Toyota", "أبيض", "", "مثال"])
        ws.append(["س ن ٥٦٧", "شركة النقل", "", "", "staff", "", "", "", ""])
        for i, w in enumerate([18, 22, 16, 14, 12, 14, 12, 14, 24], start=1):
            ws.column_dimensions[chr(64 + i)].width = w
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument."
                       "spreadsheetml.sheet",
            headers={"Content-Disposition":
                     'attachment; filename="vehicles_template.xlsx"'})

    @app.get("/export/events.csv")
    def export_events(gate: str = "", status: str = "", direction: str = "",
                      plate: str = "", date_from: str = "", date_to: str = ""):
        conn = db.connect()
        rows = db.list_events(conn, limit=100000, gate=_as_gate(gate),
                              status=status, direction=direction, plate=plate,
                              date_from=date_from, date_to=date_to)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["الوقت", "اللوحة", "Latin", "البوابة", "الاتجاه",
                    "الحالة", "المالك", "الوحدة", "الثقة", "الكاميرا"])
        for r in rows:
            w.writerow([
                r["ts"], plate_text.display(r["plate"]),
                plate_text.transliterate(r["plate"]), r["gate_number"],
                DIRECTION_AR.get(r["direction"], r["direction"]),
                STATUS_AR.get(r["status"], r["status"]),
                r["owner_name"] or "", r["unit"] or "",
                f'{r["confidence"]:.2f}', r["camera_id"],
            ])
        data = "﻿" + buf.getvalue()      # BOM so Excel shows Arabic right
        return StreamingResponse(
            io.BytesIO(data.encode("utf-8")), media_type="text/csv",
            headers={"Content-Disposition":
                     'attachment; filename="events.csv"'})

    @app.get("/stream/{camera_id}")
    def camera_stream(camera_id: str):
        """
        Live MJPEG from a camera worker.

        Never 404s for a configured camera. The worker pool starts on a
        background thread, so a page loaded during startup would otherwise get
        a 404, the <img> would fail, and it would sit there showing "camera not
        running" forever even after the camera came up. Instead this streams a
        placeholder frame and switches to live video the moment frames appear.
        """
        if cfg.camera(camera_id) is None:
            return JSONResponse({"error": "no such camera"}, status_code=404)

        def find_worker():
            pool = app.state.pool
            return next((w for w in (getattr(pool, "workers", []) or [])
                         if w.cam.id == camera_id), None)

        def gen():
            import time as _t

            idle = 0
            placeholder_sent = 0.0
            while True:
                worker = find_worker()
                if worker is not None and worker.stop_event.is_set():
                    break
                jpg = worker.latest_jpeg() if worker else None
                if jpg:
                    idle = 0
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\n"
                           b"Content-Length: " + str(len(jpg)).encode()
                           + b"\r\n\r\n" + jpg + b"\r\n")
                else:
                    idle += 1
                    if idle > 1200:          # ~2 min with no frame at all
                        break
                    # Refresh the placeholder about once a second so the
                    # browser keeps the connection and the user sees *something*
                    # rather than a broken image icon.
                    if _t.time() - placeholder_sent > 1.0:
                        placeholder_sent = _t.time()
                        ph = _placeholder_jpeg(
                            "STARTING..." if worker is None else "NO SIGNAL")
                        if ph:
                            yield (b"--frame\r\nContent-Type: image/jpeg\r\n"
                                   b"Content-Length: " + str(len(ph)).encode()
                                   + b"\r\n\r\n" + ph + b"\r\n")
                _t.sleep(0.08)

        return StreamingResponse(
            gen(), media_type="multipart/x-mixed-replace; boundary=frame")

    @app.get("/api/cameras")
    def api_cameras():
        pool = app.state.pool
        running = {w.cam.id for w in (getattr(pool, "workers", []) or [])}
        return [{"id": c.id, "name": c.name, "gate": c.gate_number,
                 "direction": c.direction,
                 "direction_ar": DIRECTION_AR.get(c.direction, c.direction),
                 "live": c.id in running}
                for c in cfg.cameras if c.enabled]

    @app.get("/api/reader")
    def api_reader():
        """What each camera's reader is producing right now, confirmed or not."""
        pool = app.state.pool
        out = []
        for w in (getattr(pool, "workers", []) or []):
            out.append({
                "camera_id": w.cam.id,
                "name": w.cam.name,
                "backend": w.reader.backend,
                "detector": w.detector.backend,
                "ocr_ms": round(w._ocr_cost * 1000),
                "attempts": w.attempts[:12],
            })
        return out

    @app.get("/shot/{event_id}/{which}")
    def event_image(event_id: int, which: str):
        """
        Serve a snapshot by event id rather than by path.

        The stored path is produced by pathlib on the host, so on Windows it
        contains backslashes, and the filename embeds the Arabic plate. Putting
        that through a URL round-trip broke the thumbnails. The id is stable
        and encoding-free.
        """
        row = db.connect().execute(
            "SELECT snapshot, plate_crop FROM events WHERE id=?",
            (event_id,)).fetchone()
        if row is None:
            return JSONResponse({"error": "no such event"}, status_code=404)
        rel = row["plate_crop"] if which == "crop" else row["snapshot"]
        if not rel:
            return JSONResponse({"error": "no image"}, status_code=404)
        f = (SNAPSHOT_DIR / str(rel).replace("\\", "/")).resolve()
        if not str(f).startswith(str(SNAPSHOT_DIR.resolve())) or not f.exists():
            return JSONResponse({"error": "file missing", "path": str(rel)},
                                status_code=404)
        return FileResponse(f)

    @app.get("/snap/{path:path}")
    def snapshot(path: str):
        f = (SNAPSHOT_DIR / path).resolve()
        if not str(f).startswith(str(SNAPSHOT_DIR.resolve())) or not f.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        return FileResponse(f)

    @app.get("/api/health")
    def health():
        conn = db.connect()
        cams = db.camera_statuses(conn)
        offline = [c["camera_id"] for c in cams if not c["online"]]
        return {"ok": not offline, "offline": offline,
                "stats": db.daily_stats(conn)}

    return app


def _placeholder_jpeg(text: str) -> bytes | None:
    """A dark frame with a short ASCII label (OpenCV cannot draw Arabic)."""
    try:
        import cv2
        import numpy as np

        img = np.full((360, 640, 3), 18, np.uint8)
        cv2.putText(img, text, (170, 190), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                    (140, 160, 180), 2, cv2.LINE_AA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 60])
        return buf.tobytes() if ok else None
    except Exception:
        return None


# --- import helpers ------------------------------------------------------------

_ALIASES = {
    "plate": "plate", "رقم اللوحة": "plate", "اللوحة": "plate",
    "number": "plate", "رقم": "plate",
    "owner_name": "owner_name", "owner": "owner_name", "اسم المالك": "owner_name",
    "المالك": "owner_name", "الاسم": "owner_name", "name": "owner_name",
    "phone": "phone", "الهاتف": "phone", "موبايل": "phone", "التليفون": "phone",
    "unit": "unit", "الوحدة": "unit", "الشقة": "unit", "الوحدة/الشقة": "unit",
    "category": "category", "الفئة": "category", "النوع": "category",
    "car_make": "car_make", "الماركة": "car_make", "make": "car_make",
    "car_color": "car_color", "اللون": "car_color", "color": "car_color",
    "valid_until": "valid_until", "صالح حتى": "valid_until",
    "expiry": "valid_until", "تاريخ الانتهاء": "valid_until",
    "notes": "notes", "ملاحظات": "notes",
}


def _map_headers(headers: list[str]) -> list[str | None]:
    return [_ALIASES.get(str(h or "").strip().lower(),
                         _ALIASES.get(str(h or "").strip())) for h in headers]


def _read_xlsx(raw: bytes) -> list[dict]:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(raw), data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    cols = _map_headers(list(rows[0]))
    out = []
    for r in rows[1:]:
        rec = {}
        for c, v in zip(cols, r):
            if c and v not in (None, ""):
                rec[c] = str(v).strip()
        if rec.get("plate"):
            # Skip the Arabic label row in the shipped template.
            if rec["plate"] in ("رقم اللوحة", "plate"):
                continue
            out.append(rec)
    return out


def _read_csv(raw: bytes) -> list[dict]:
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return []
    cols = _map_headers(rows[0])
    out = []
    for r in rows[1:]:
        rec = {c: v.strip() for c, v in zip(cols, r) if c and v.strip()}
        if rec.get("plate") and rec["plate"] not in ("رقم اللوحة", "plate"):
            out.append(rec)
    return out
