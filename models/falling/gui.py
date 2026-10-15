"""Fall detection viewer: pick a video file or camera, pick a detector from the
dropdown (every registered FallDetector appears there), click Run.

    python gui.py

Pose estimation + detection run in a worker thread; frames and alerts are
handed to the Tk main loop through queues.
"""

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import cv2
import numpy as np

from core.features import FALLEN, FALLING, LABELS, NORMAL
from core.keypoints import KP_CONF_MIN, SKELETON
from detectors import available_detectors, create_detector, detector_classes

try:
    import winsound
except ImportError:
    winsound = None

STATE_COLORS = {NORMAL: (80, 200, 80), FALLING: (0, 200, 255), FALLEN: (0, 0, 255)}   # BGR
UNKNOWN_COLOR = (180, 180, 180)
ALERT_COLOR = (0, 0, 255)
DISPLAY_W = 800


def draw_overlay(frame, persons, detector):
    """Skeletons and boxes colored by each track's current state."""
    for p in persons:
        status = detector.status_for(p.track_id)
        color = ALERT_COLOR if status and status.alerted else STATE_COLORS.get(
            status.state if status else None, UNKNOWN_COLOR)
        x1, y1, x2, y2 = (int(v) for v in p.bbox)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3 if status and status.alerted else 2)
        kps = p.keypoints
        for a, b in SKELETON:
            if kps[a, 2] >= KP_CONF_MIN and kps[b, 2] >= KP_CONF_MIN:
                cv2.line(frame, (int(kps[a, 0]), int(kps[a, 1])), (int(kps[b, 0]), int(kps[b, 1])),
                         color, 2)
        label = f"#{status.track_id}" if status else "?"
        if status and status.state in STATE_COLORS:
            label += f" {LABELS[status.state]} {status.confidence:.2f}"
        if status and status.alerted:
            label += "  FALL!"
        cv2.putText(frame, label, (x1, max(15, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    return frame


class FallDetectionApp:
    def __init__(self, root):
        self.root = root
        root.title("Fall Detection")
        self.detector_names = available_detectors()          # name -> display name
        self._by_display = {v: k for k, v in self.detector_names.items()}
        self.worker = None
        self.stop_event = threading.Event()
        self.frames = queue.Queue(maxsize=1)
        self.messages = queue.Queue()
        self._photo = None

        form = ttk.Frame(root, padding=10)
        form.grid(row=0, column=0, sticky="ew")
        ttk.Label(form, text="Source (file or camera index):").grid(row=0, column=0, sticky="w")
        self.source = tk.StringVar(value="0")
        ttk.Entry(form, textvariable=self.source, width=50).grid(row=0, column=1, padx=4)
        ttk.Button(form, text="Browse...", command=self._browse_video).grid(row=0, column=2)

        ttk.Label(form, text="Detector:").grid(row=1, column=0, sticky="w", pady=4)
        self.detector = tk.StringVar(value=next(iter(self.detector_names.values()), ""))
        self.detector_box = ttk.Combobox(form, textvariable=self.detector, state="readonly", width=47,
                                         values=list(self.detector_names.values()))
        self.detector_box.grid(row=1, column=1, padx=4, sticky="w")
        self.detector_box.bind("<<ComboboxSelected>>", lambda _: self._refresh_state())

        ttk.Label(form, text="Checkpoint (temporal model):").grid(row=2, column=0, sticky="w")
        self.checkpoint = tk.StringVar()
        self.ckpt_entry = ttk.Entry(form, textvariable=self.checkpoint, width=50)
        self.ckpt_entry.grid(row=2, column=1, padx=4)
        self.ckpt_btn = ttk.Button(form, text="Browse...", command=self._browse_checkpoint)
        self.ckpt_btn.grid(row=2, column=2)

        buttons = ttk.Frame(form)
        buttons.grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.run_btn = ttk.Button(buttons, text="Run", command=self._start)
        self.run_btn.grid(row=0, column=0)
        self.stop_btn = ttk.Button(buttons, text="Stop", command=self._stop, state="disabled")
        self.stop_btn.grid(row=0, column=1, padx=6)
        self.status = tk.StringVar(value="Idle.")
        ttk.Label(buttons, textvariable=self.status).grid(row=0, column=2, padx=10)

        self.video = ttk.Label(root)
        self.video.grid(row=1, column=0, padx=10)
        self.alerts = tk.Listbox(root, height=6, width=100)
        self.alerts.grid(row=2, column=0, padx=10, pady=(4, 10), sticky="ew")

        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._refresh_state()
        root.after(30, self._poll)

    # ---------------------------------------------------------------- form --

    def selected_detector(self):
        return self._by_display.get(self.detector.get())

    def _refresh_state(self):
        name = self.selected_detector()
        state = "normal" if name == "temporal_model" else "disabled"
        self.ckpt_entry.configure(state=state)
        self.ckpt_btn.configure(state=state)
        cls = detector_classes().get(name)
        reason = cls.unavailable_reason() if cls else None
        if reason and not self.checkpoint.get():
            self.status.set(f"{self.detector.get()}: {reason}")
        elif self.worker is None:
            self.status.set("Idle.")

    def _browse_video(self):
        path = filedialog.askopenfilename(title="Video file", filetypes=[
            ("Video files", "*.mp4 *.avi *.mkv *.mov *.webm *.m4v *.wmv"), ("All files", "*.*")])
        if path:
            self.source.set(path)

    def _browse_checkpoint(self):
        path = filedialog.askopenfilename(title="Temporal model checkpoint",
                                          filetypes=[("PyTorch checkpoint", "*.pt"), ("All files", "*.*")])
        if path:
            self.checkpoint.set(path)

    # -------------------------------------------------------------- worker --

    def _start(self):
        if self.worker is not None:
            return
        name = self.selected_detector()
        kwargs = {"checkpoint": self.checkpoint.get() or None} if name == "temporal_model" else {}
        try:
            detector = create_detector(name, **kwargs)
        except Exception as e:
            messagebox.showerror("Detector unavailable", str(e))
            return
        self.stop_event.clear()
        self.alerts.delete(0, tk.END)
        self.worker = threading.Thread(target=self._run, args=(self.source.get().strip(), detector),
                                       daemon=True)
        self.worker.start()
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.detector_box.configure(state="disabled")
        self.status.set(f"Running {self.detector.get()} ...")

    def _run(self, source, detector):
        try:
            from core.pose import PoseEstimator
            from core.video import FrameSource

            frames = FrameSource(source)
            estimator = PoseEstimator()
            estimator.reset()
            detector.reset(frames.fps)
            for idx, frame in frames:
                if self.stop_event.is_set():
                    break
                persons = estimator(frame)
                for event in detector.update(idx, persons):
                    self.messages.put(("alert", f"frame {idx} ({idx / frames.fps:.1f}s): fall, track "
                                                f"#{event.track_id}, confidence {event.confidence:.2f}"))
                draw_overlay(frame, persons, detector)
                try:
                    self.frames.get_nowait()   # drop the stale frame; show only the latest
                except queue.Empty:
                    pass
                self.frames.put(frame)
            self.messages.put(("done", "Finished."))
        except Exception as e:
            self.messages.put(("error", str(e)))

    def _poll(self):
        try:
            frame = self.frames.get_nowait()
        except queue.Empty:
            frame = None
        if frame is not None:
            self._show(frame)
        while True:
            try:
                kind, text = self.messages.get_nowait()
            except queue.Empty:
                break
            if kind == "alert":
                self.alerts.insert(0, text)
                if winsound is not None:
                    threading.Thread(target=winsound.Beep, args=(900, 350), daemon=True).start()
            else:
                self._finished(text, error=kind == "error")
        self.root.after(15, self._poll)

    def _show(self, frame):
        from PIL import Image, ImageTk

        h, w = frame.shape[:2]
        if w > DISPLAY_W:
            frame = cv2.resize(frame, (DISPLAY_W, int(h * DISPLAY_W / w)))
        rgb = np.ascontiguousarray(frame[:, :, ::-1])
        self._photo = ImageTk.PhotoImage(Image.fromarray(rgb))
        self.video.configure(image=self._photo)

    def _finished(self, text, error=False):
        self.worker = None
        self.run_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.detector_box.configure(state="readonly")
        self.status.set(text)
        if error:
            messagebox.showerror("Error", text)

    def _stop(self):
        self.stop_event.set()
        self.status.set("Stopping ...")

    def _on_close(self):
        self.stop_event.set()
        self.root.destroy()


def main():
    root = tk.Tk()
    FallDetectionApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
