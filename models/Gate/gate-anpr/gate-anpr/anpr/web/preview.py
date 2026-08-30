"""
اختبار الكاميرا المباشر / live camera test.

    python run.py camtest              # كاميرا اللابتوب
    python run.py camtest --source rtsp://...

يفتح صفحة في المتصفح تعرض ما تراه الكاميرا مع مربع حول كل لوحة يكتشفها
النظام، وعرض اللوحة بالبكسل — وهو الرقم الذي يحدد نجاح التركيب أو فشله.

Why a browser page and not an OpenCV window: the project installs
opencv-python-headless (much smaller, no GUI), so cv2.imshow does not exist.
Streaming MJPEG works everywhere, including over the network from a Jetson
with no screen attached.

A single background thread owns the camera. A webcam can usually only be
opened once on Windows, so opening a second capture per HTTP client would
fail — the thread grabs frames, everyone else reads the latest annotated JPEG.
"""

from __future__ import annotations

import logging
import threading
import time

import cv2
import numpy as np
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from .. import plate_text
from ..capture import open_capture
from ..config import ROOT, RecognitionConfig
from ..detector import PlateDetector
from ..ocr import PlateReader
from ..tracker import PlateTracker, vote_weight

log = logging.getLogger(__name__)

# Comfortable plate width for reliable reading. A guide for aiming a camera,
# not a cut-off — smaller plates are still detected and read, with less weight.
GOOD_WIDTH_PX = 100
MIN_WIDTH_PX = 60


class PreviewWorker(threading.Thread):
    def __init__(self, source: str, rotate: int = 0, rec: RecognitionConfig | None = None):
        super().__init__(name="camtest", daemon=True)
        self.source = source
        self.rotate = rotate
        rec = rec or RecognitionConfig()
        self.detector = PlateDetector(rec.detector_backend,
                                      str(ROOT / rec.plate_detector_weights),
                                      rec.min_detect_conf, rec.device)
        self.reader = PlateReader(rec.ocr_backend,
                                  str(ROOT / rec.char_detector_weights),
                                  rec.device)
        self.tracker = PlateTracker(min_votes=rec.min_votes)
        self.stop_event = threading.Event()
        self._lock = threading.Lock()
        self._jpeg: bytes | None = None
        self.state = {
            "connected": False, "error": "", "fps": 0.0, "size": "",
            "plates": [], "confirmed": [], "best_width": 0,
            "detector": self.detector.backend, "reader": self.reader.backend,
        }

    # ---------------------------------------------------------------

    def run(self) -> None:
        while not self.stop_event.is_set():
            cap = open_capture(self.source)
            if cap is None:
                self.state.update(connected=False,
                                  error="تعذّر فتح الكاميرا / cannot open camera")
                self._render_message("لا يمكن فتح الكاميرا",
                                     f"source: {self.source}")
                if self.stop_event.wait(3):
                    break
                continue

            self.state.update(connected=True, error="")
            t0, n = time.time(), 0
            try:
                while not self.stop_event.is_set():
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        self.state.update(connected=False,
                                          error="انقطع البث / stream ended")
                        break
                    frame = self._rotate(frame)
                    self._process(frame)
                    n += 1
                    if time.time() - t0 >= 1.0:
                        self.state["fps"] = round(n / (time.time() - t0), 1)
                        t0, n = time.time(), 0
            except Exception as exc:
                log.exception("camtest error")
                self.state.update(connected=False, error=str(exc))
            finally:
                cap.release()
            if self.stop_event.wait(2):
                break

    def _rotate(self, frame):
        if self.rotate == 90:
            return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        if self.rotate == 180:
            return cv2.rotate(frame, cv2.ROTATE_180)
        if self.rotate == 270:
            return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return frame

    # ---------------------------------------------------------------

    def _process(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        self.state["size"] = f"{w}x{h}"
        now = time.time()
        boxes = self.detector.detect(frame)

        found = []
        best_w = 0
        for track, box in self.tracker.update(boxes, now):
            crop = box.crop(frame)
            res = self.reader.read(crop, context=frame)
            if res.text:
                track.add_vote(res.text, vote_weight(res.confidence,
                                                     res.plausibility,
                                                     box.w, w))
            leader, _, votes = track.leader()
            best_w = max(best_w, box.w)
            found.append({
                "x1": box.x1, "y1": box.y1, "x2": box.x2, "y2": box.y2,
                "width_px": box.w,
                "text": leader or res.text,
                "display": plate_text.display(leader or res.text),
                "latin": plate_text.transliterate(leader or res.text),
                "votes": votes,
                "conf": round(box.conf, 2),
            })

        confirmed = []
        for t in self.tracker.confirmed():
            text, weight, votes = t.leader()
            confirmed.append({"display": plate_text.display(text),
                              "latin": plate_text.transliterate(text),
                              "votes": votes,
                              "at": time.strftime("%H:%M:%S")})
        self.tracker.expired()

        found = _merge_for_display(found)
        self.state["plates"] = found
        self.state["best_width"] = best_w
        if confirmed:
            self.state["confirmed"] = (confirmed
                                       + self.state["confirmed"])[:12]

        self._draw(frame, found)

    def _draw(self, frame: np.ndarray, found: list) -> None:
        h, w = frame.shape[:2]
        for p in found:
            good = p["width_px"] >= GOOD_WIDTH_PX
            colour = (0, 200, 0) if good else (0, 165, 255)
            cv2.rectangle(frame, (p["x1"], p["y1"]), (p["x2"], p["y2"]),
                          colour, 2)
            # Arabic cannot be drawn by OpenCV — show the Latin form on the
            # image and the Arabic in the HTML panel beside it.
            label = f"{p['latin'] or '?'}  {p['width_px']}px"
            cv2.rectangle(frame, (p["x1"], max(p["y1"] - 22, 0)),
                          (p["x1"] + 11 * len(label), p["y1"]), colour, -1)
            cv2.putText(frame, label, (p["x1"] + 3, max(p["y1"] - 6, 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1,
                        cv2.LINE_AA)

        banner = f"{w}x{h}   {self.state['fps']} fps   plates: {len(found)}"
        cv2.putText(frame, banner, (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (255, 255, 255), 2, cv2.LINE_AA)
        self._encode(frame)

    def _render_message(self, line1: str, line2: str) -> None:
        img = np.full((480, 854, 3), 30, np.uint8)
        cv2.putText(img, "NO CAMERA", (250, 220), cv2.FONT_HERSHEY_SIMPLEX,
                    1.2, (0, 0, 220), 3, cv2.LINE_AA)
        cv2.putText(img, line2[:60], (60, 280), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (200, 200, 200), 1, cv2.LINE_AA)
        self._encode(img)

    def _encode(self, frame: np.ndarray) -> None:
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            with self._lock:
                self._jpeg = buf.tobytes()

    def latest(self) -> bytes | None:
        with self._lock:
            return self._jpeg


PAGE = """<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<title>اختبار الكاميرا</title>
<style>
 body{background:#0f1720;color:#e8eef4;font-family:Segoe UI,Tahoma,Arial;margin:0;padding:16px}
 h1{font-size:18px;margin:0 0 12px}
 .wrap{display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start}
 img{width:min(60vw,860px);border-radius:10px;border:1px solid #2a3a4a;background:#000}
 @media(max-width:900px){img{width:100%}}
 .side{flex:1;min-width:280px}
 .card{background:#17212b;border:1px solid #2a3a4a;border-radius:10px;padding:14px;margin-bottom:12px}
 .n{font-size:26px;font-weight:700}
 .ok{color:#2ecc71}.warn{color:#f5a623}.bad{color:#ff4d4f}.muted{color:#93a4b5}
 .plate{background:#f4f6f8;color:#111;border:2px solid #b9c4cf;border-radius:6px;
        padding:2px 10px;display:inline-block;font-weight:700;letter-spacing:2px}
 table{width:100%;border-collapse:collapse;font-size:13px}
 td,th{padding:6px;border-bottom:1px solid #2a3a4a;text-align:right}
</style></head><body>
<h1>🎥 اختبار الكاميرا — ما يراه النظام</h1>
<div class="wrap">
  <div><img id="v" src="/stream"></div>
  <div class="side">
    <div class="card">
      <div class="muted">حالة الاتصال</div>
      <div class="n" id="conn">…</div>
      <div class="muted" id="meta"></div>
    </div>
    <div class="card">
      <div class="muted">عرض اللوحة في الصورة — الرقم الحاسم</div>
      <div class="n" id="wpx">—</div>
      <div id="wmsg" class="muted"></div>
    </div>
    <div class="card">
      <div class="muted">لوحات مؤكَّدة (بعد اتفاق عدة إطارات)</div>
      <table id="tbl"><tbody></tbody></table>
      <div class="muted" id="empty">لا شيء بعد — قرّب لوحة من الكاميرا.</div>
    </div>
    <div class="card muted" style="font-size:12px">
      الكاشف: <b id="det"></b> · القارئ: <b id="rdr"></b><br>
      بدون نموذج مدرَّب ستكون النتائج ضعيفة — هذا متوقع في هذه المرحلة.
      الهدف الآن هو ضبط زاوية الكاميرا وعرض اللوحة.
    </div>
  </div>
</div>
<script>
async function tick(){
 try{
  const s = await (await fetch('/api/state')).json();
  conn.textContent = s.connected ? 'متصلة ✓' : 'غير متصلة ✗';
  conn.className = 'n ' + (s.connected ? 'ok' : 'bad');
  meta.textContent = (s.size||'') + '   ' + (s.fps||0) + ' لقطة/ث   ' + (s.error||'');
  det.textContent = s.detector; rdr.textContent = s.reader;
  const w = s.best_width||0;
  wpx.textContent = w ? w + ' بكسل' : '—';
  if(!w){ wpx.className='n muted'; wmsg.textContent='لم تُكتشف لوحة بعد.'; }
  else if(w >= 100){ wpx.className='n ok'; wmsg.textContent='ممتاز — هذا العرض كافٍ للقراءة الدقيقة.'; }
  else if(w >= 60){ wpx.className='n warn'; wmsg.textContent='تُقرأ لكن بثقة أقل. قرّب الكاميرا أو استخدم عدسة أطول للوصول إلى ١٠٠ بكسل.'; }
  else { wpx.className='n bad'; wmsg.textContent='صغيرة جدًا — القراءة ضعيفة. قرّب الكاميرا أو زد الزووم.'; }
  const rows = (s.confirmed||[]).map(c=>
    `<tr><td><span class="plate">${c.display}</span></td>
         <td class="muted">${c.latin}</td>
         <td class="muted">${c.votes} إطار</td>
         <td class="muted">${c.at}</td></tr>`).join('');
  tbl.querySelector('tbody').innerHTML = rows;
  empty.style.display = rows ? 'none' : '';
 }catch(e){}
}
setInterval(tick, 700); tick();
</script></body></html>"""


def _merge_for_display(found: list[dict]) -> list[dict]:
    """
    One rectangle per physical plate on screen.

    The detector deliberately keeps a plate's halves as separate candidates —
    that redundancy helps voting when part of a plate is obscured. For a human
    aiming a camera it is just clutter, so overlapping rectangles are collapsed
    to the largest. Display only; the recognition pipeline still sees them all.
    """
    out: list[dict] = []
    for p in sorted(found, key=lambda d: d["width_px"], reverse=True):
        if any(_overlaps(p, q) for q in out):
            continue
        out.append(p)
    return out


def _overlaps(a: dict, b: dict) -> bool:
    ix1, iy1 = max(a["x1"], b["x1"]), max(a["y1"], b["y1"])
    ix2, iy2 = min(a["x2"], b["x2"]), min(a["y2"], b["y2"])
    inter = max(ix2 - ix1, 0) * max(iy2 - iy1, 0)
    small = min((a["x2"] - a["x1"]) * (a["y2"] - a["y1"]),
                (b["x2"] - b["x1"]) * (b["y2"] - b["y1"]))
    return small > 0 and inter / small >= 0.5


def build_app(worker: PreviewWorker) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return PAGE

    @app.get("/api/state")
    def state():
        return JSONResponse(worker.state)

    @app.get("/stream")
    def stream():
        def gen():
            blank = 0
            while not worker.stop_event.is_set():
                jpg = worker.latest()
                if jpg:
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\n"
                           b"Content-Length: " + str(len(jpg)).encode()
                           + b"\r\n\r\n" + jpg + b"\r\n")
                    blank = 0
                else:
                    blank += 1
                    if blank > 200:
                        break
                time.sleep(0.05)

        return StreamingResponse(
            gen(), media_type="multipart/x-mixed-replace; boundary=frame")

    return app


def run_preview(source: str = "0", port: int = 8090, rotate: int = 0,
                rec: RecognitionConfig | None = None) -> int:
    import uvicorn

    worker = PreviewWorker(source, rotate, rec)
    worker.start()
    app = build_app(worker)
    print(f"\n  اختبار الكاميرا / camera test")
    print(f"  المصدر / source: {source}")
    print(f"  افتح المتصفح على / open:  http://localhost:{port}\n")
    print("  اضغط Ctrl+C للإيقاف / Ctrl+C to stop\n")
    try:
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
    finally:
        worker.stop_event.set()
    return 0
