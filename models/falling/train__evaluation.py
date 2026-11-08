"""Event- and frame-level scoring of a FallDetector on cached videos
(shared by eval.py and the threshold calibration in train/calibrate.py).

Event level (per video, one annotated fall at most): the first alert in
[fall start - before_s, impact + after_s] is a true positive, alerts outside it
are false alarms, a fall without one is a miss. "Impact" is the first FALLEN
frame. Frame level: the subject's per-frame state vs. the labels.
"""

import time

import numpy as np

from core.features import FALLEN, FALLING, LABELS, UNKNOWN

from .train import classification_report, confusion_matrix


def ground_truth_fall(frame_labels):
    """(fall start, impact) frames, or None if the video has no fall."""
    labels = np.asarray(frame_labels)
    down = np.flatnonzero(np.isin(labels, (FALLING, FALLEN)))
    if not len(down):
        return None
    fallen = np.flatnonzero(labels == FALLEN)
    return int(down[0]), int(fallen[0] if len(fallen) else down[-1])


def match_events(event_frames, fall, fps, before_s=1.0, after_s=3.0):
    """Score one video's alert frames against its fall (or None)."""
    event_frames = sorted(event_frames)
    if fall is None:
        return {"tp": 0, "fp": len(event_frames), "fn": 0, "latency_s": None}
    start, impact = fall
    lo, hi = start - before_s * fps, impact + after_s * fps
    inside = [f for f in event_frames if lo <= f <= hi]
    outside = [f for f in event_frames if not lo <= f <= hi]
    if not inside:
        return {"tp": 0, "fp": len(outside), "fn": 1, "latency_s": None}
    # Extra alerts inside the window (e.g. a second track id) are neither TP nor FP.
    return {"tp": 1, "fp": len(outside), "fn": 0, "latency_s": (inside[0] - impact) / fps}


def replay(detector, cache, persons):
    """Feed one cached video to a detector. Returns (event frames, subject
    states per frame, seconds spent inside the detector)."""
    detector.reset(cache["fps"])
    events, states = [], np.full(cache["n_frames"], UNKNOWN, dtype=np.int64)
    spent = 0.0
    for f, frame_persons in enumerate(persons):
        t0 = time.perf_counter()
        events += [e.frame_idx for e in detector.update(f, frame_persons)]
        spent += time.perf_counter() - t0
        det = int(cache["subject_det"][f])
        if det >= 0:
            tid = int(cache["det_track"][det])
            status = detector.status_for(tid) if tid >= 0 else None
            if status is not None and status.last_seen == f:
                states[f] = status.state   # UNKNOWN when the detector had no prediction this frame
    return events, states, spent


def evaluate(detector, videos, before_s=1.0, after_s=3.0):
    totals = {"tp": 0, "fp": 0, "fn": 0}
    latencies, per_video = [], []
    cm = np.zeros((len(LABELS), len(LABELS)), dtype=np.int64)
    covered = labelled = 0
    seconds = frames = 0.0
    spent = 0.0
    for cache, persons in videos:
        events, states, t = replay(detector, cache, persons)
        spent += t
        fall = ground_truth_fall(cache["frame_labels"])
        m = match_events(events, fall, cache["fps"], before_s, after_s)
        for k in totals:
            totals[k] += m[k]
        if m["latency_s"] is not None:
            latencies.append(m["latency_s"])
        labels = cache["frame_labels"].astype(np.int64)
        known = labels != UNKNOWN
        ok = known & (states != UNKNOWN)
        cm += confusion_matrix(labels[ok], states[ok])
        labelled += int(known.sum())
        covered += int(ok.sum())
        frames += cache["n_frames"]
        seconds += cache["n_frames"] / cache["fps"]
        per_video.append({"video_id": cache["video_id"], "fall": fall, "events": events, **m})

    tp, fp, fn = totals["tp"], totals["fp"], totals["fn"]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    rep = classification_report(cm)
    return {
        "videos": len(videos), "falls": tp + fn, "tp": tp, "fp": fp, "fn": fn,
        "precision": precision, "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "false_alarms_per_min": fp / (seconds / 60) if seconds else 0.0,
        "latency_s": float(np.mean(latencies)) if latencies else None,
        "frame_macro_f1": rep["macro_f1"], "frame_accuracy": rep["accuracy"],
        "frame_coverage": covered / labelled if labelled else 0.0,
        "ms_per_frame": 1000 * spent / frames if frames else 0.0,
        "confusion": cm, "per_video": per_video,
    }
