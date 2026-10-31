"""Send this laptop's webcam to the cloud trial's engine. specs/021-cloud-trial.

    pythonw tools/cloud/webcam_sender.py        (the "VisionGuard Cloud Camera" shortcut)

A small window: the day's address (https://....trycloudflare.com), the email
and the password, then Start. It signs in like the console does, and sends
each webcam frame as a JPEG to `/cameras/cam-webcam/push` through the engine's
own address. Nothing on this laptop is opened to the internet.

The round trip to Kaggle is a few hundred milliseconds, so frames go out on
`SENDERS` connections at once; each takes the newest frame when it is free,
so a slow moment drops frames rather than queueing them. Stop, or closing the
window, stops sending - and the camera reads NO SIGNAL in the console within
seconds, as a real camera's would.

The password is never stored. The address and email are remembered between
runs in %APPDATA%\\VisionGuard\\cloud_camera.json.
"""

from __future__ import annotations

import http.client
import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

CAMERA_ID = "cam-webcam"
WIDTH, HEIGHT = 640, 480
FPS = 10
JPEG_QUALITY = 80
SENDERS = 3
SETTINGS = Path(os.environ.get("APPDATA", Path.home())) / "VisionGuard" / "cloud_camera.json"


def normalise(address: str) -> tuple[str, str, int]:
    """'https://x.trycloudflare.com/' -> ('https', 'x.trycloudflare.com', 443)."""
    address = address.strip()
    if "://" not in address:
        address = "https://" + address
    parts = urlsplit(address)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"{address!r} is not a web address")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return parts.scheme, parts.hostname, port


class Engine:
    """One keep-alive connection to the engine."""

    def __init__(self, scheme: str, host: str, port: int, timeout: float = 10.0):
        cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
        self._conn = cls(host, port, timeout=timeout)

    def request(self, method: str, path: str, body: bytes, headers: dict) -> tuple[int, bytes]:
        try:
            self._conn.request(method, path, body=body, headers=headers)
            response = self._conn.getresponse()
            return response.status, response.read()
        except (OSError, http.client.HTTPException):
            self._conn.close()  # reconnects on the next request
            raise

    def close(self) -> None:
        self._conn.close()


def sign_in(scheme: str, host: str, port: int, email: str, password: str) -> str:
    engine = Engine(scheme, host, port)
    try:
        status, body = engine.request(
            "POST", "/auth/login", json.dumps({"email": email, "password": password}).encode(),
            {"Content-Type": "application/json"})
    finally:
        engine.close()
    if status != 200:
        raise PermissionError("sign-in refused: check the email and password")
    return json.loads(body)["token"]


class Sender:
    """The webcam, the newest frame, and the threads that send it."""

    def __init__(self, address: str, email: str, password: str, report):
        self.scheme, self.host, self.port = normalise(address)
        self.email, self.password = email, password
        self.report = report  # report(text): status for the window
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._frame: bytes = b""
        self._frame_seq = 0
        self._claimed = 0
        self._token = ""
        self.sent = 0
        self.failed = 0
        self.last_ms = 0.0
        self.last_error = ""

    def start(self) -> None:
        self._token = sign_in(self.scheme, self.host, self.port, self.email, self.password)
        threading.Thread(target=self._capture, daemon=True).start()
        for _ in range(SENDERS):
            threading.Thread(target=self._send, daemon=True).start()
        threading.Thread(target=self._status, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _capture(self) -> None:
        import cv2

        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            self.last_error = "the webcam would not open (is another program using it?)"
            self._stop.set()
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        interval = 1.0 / FPS
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                ok, image = cap.read()
                if not ok:
                    self.last_error = "the webcam stopped giving pictures"
                    time.sleep(0.5)
                    continue
                ok, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                if ok:
                    with self._lock:
                        self._frame = jpeg.tobytes()
                        self._frame_seq += 1
                left = interval - (time.monotonic() - started)
                if left > 0:
                    time.sleep(left)
        finally:
            cap.release()

    def _send(self) -> None:
        engine = Engine(self.scheme, self.host, self.port)
        path = f"/cameras/{CAMERA_ID}/push"
        try:
            while not self._stop.is_set():
                # Claimed under the lock, so each frame goes out once, on
                # whichever connection is free first. (Each connection keeping
                # its own "last sent" sent every frame three times.)
                with self._lock:
                    seq, frame = self._frame_seq, self._frame
                    fresh = frame and seq != self._claimed
                    if fresh:
                        self._claimed = seq
                if not fresh:
                    time.sleep(0.01)
                    continue
                started = time.perf_counter()
                try:
                    status, body = engine.request("POST", path, frame, {
                        "Content-Type": "image/jpeg",
                        "Authorization": f"Bearer {self._token}"})
                except (OSError, http.client.HTTPException) as exc:
                    self.failed += 1
                    self.last_error = f"no answer from the engine: {exc}"
                    time.sleep(1.0)
                    continue
                if status == 204:
                    self.sent += 1
                    self.last_ms = (time.perf_counter() - started) * 1000
                    self.last_error = ""
                elif status == 401:
                    self.failed += 1
                    try:
                        self._token = sign_in(self.scheme, self.host, self.port,
                                              self.email, self.password)
                    except Exception as exc:  # noqa: BLE001 - shown in the window
                        self.last_error = str(exc)
                        time.sleep(2.0)
                else:
                    self.failed += 1
                    self.last_error = f"engine said {status}: {body[:120].decode(errors='replace')}"
                    time.sleep(1.0)
        finally:
            engine.close()

    def _status(self) -> None:
        before, at = self.sent, time.monotonic()
        while not self._stop.is_set():
            time.sleep(1.0)
            now = time.monotonic()
            rate = (self.sent - before) / (now - at)
            before, at = self.sent, now
            text = f"Sending: {rate:.1f} pictures a second · last one took {self.last_ms:.0f} ms"
            if self.failed:
                text += f" · {self.failed} failed"
            if self.last_error:
                text += f"\n{self.last_error}"
            self.report(text)
        self.report(f"Stopped. {self.sent} pictures sent." +
                    (f"\n{self.last_error}" if self.last_error else ""))


def _load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_settings(address: str, email: str) -> None:
    try:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps({"address": address, "email": email}), encoding="utf-8")
    except OSError:
        pass


def main() -> int:
    import tkinter as tk

    saved = _load_settings()
    root = tk.Tk()
    root.title("VisionGuard Cloud Camera")
    root.resizable(False, False)
    pad = {"padx": 10, "pady": 4}

    tk.Label(root, text="Today's address (from the Kaggle notebook):").grid(row=0, column=0, sticky="w", **pad)
    address = tk.Entry(root, width=52)
    address.insert(0, saved.get("address", "https://"))
    address.grid(row=1, column=0, **pad)
    tk.Label(root, text="Email:").grid(row=2, column=0, sticky="w", **pad)
    email = tk.Entry(root, width=52)
    email.insert(0, saved.get("email", "admin@trial.local"))
    email.grid(row=3, column=0, **pad)
    tk.Label(root, text="Password:").grid(row=4, column=0, sticky="w", **pad)
    password = tk.Entry(root, width=52, show="*")
    password.grid(row=5, column=0, **pad)
    status = tk.Label(root, text="Not sending.", justify="left", width=52, anchor="w")
    status.grid(row=7, column=0, **pad)

    state: dict = {"sender": None}

    def report(text: str) -> None:
        root.after(0, lambda: status.config(text=text))

    def toggle() -> None:
        if state["sender"] is not None:
            state["sender"].stop()
            state["sender"] = None
            button.config(text="Start")
            return
        status.config(text="Signing in...")
        root.update_idletasks()
        try:
            sender = Sender(address.get(), email.get(), password.get(), report)
            sender.start()
        except Exception as exc:  # noqa: BLE001 - every failure is shown, not raised
            status.config(text=f"Could not start: {exc}")
            return
        _save_settings(address.get().strip(), email.get().strip())
        state["sender"] = sender
        button.config(text="Stop")

    button = tk.Button(root, text="Start", width=14, command=toggle)
    button.grid(row=6, column=0, **pad)

    def closing() -> None:
        if state["sender"] is not None:
            state["sender"].stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", closing)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
