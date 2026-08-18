"""The cross-camera trade-off curve, measured on synthetic two-camera footage.

    python examples/benchmark_crosscam.py

A stream of people walk through a pair of overlapping cameras, one after
another, each camera with its own colour cast and noise. Both numbers matter
and they pull against each other:

  linked      one person on both feeds ends up on ONE number   (recall)
  stolen      a number lands on a second, different person     (precision)

Some of the crowd are colleagues of someone already seen -- same shirt, own
trousers -- which is the case that produces stolen numbers in real buildings.

**Read the direction, not the rates.** These frames are flat colour blocks
under an exaggerated colour cast, which is close to worst case for a histogram
descriptor, so the absolute percentages say nothing about your site. What
transfers is which way each dial moves the two numbers, and how steeply. To
tune for real, run `loiterwatch multi --debug-reid` against your own cameras
and set the bars from the scores it prints.
"""
from __future__ import annotations

import numpy as np

from loiterwatch.identity import BodySignature, IdentityStitcher
from loiterwatch.live import Detection

BOX = (100, 60, 220, 420)
CAST_A = np.array([1.00, 1.00, 1.00])
CAST_B = np.array([1.22, 0.94, 0.82])      # the second camera runs warm
DT = 0.05                                   # ~20fps
ROUNDS = 8
GAP = 40.0                                  # seconds between people


def frame_of(outfit, cast, rng, noise=16):
    top, bottom = outfit
    f = np.full((480, 640, 3), 30, dtype=np.uint8)
    x1, y1, x2, y2 = BOX
    bh = y2 - y1
    f[y1:y1 + int(bh * 0.52), x1:x2] = top
    f[y1 + int(bh * 0.52):y2, x1:x2] = bottom
    f = f.astype(np.float32) * cast + rng.integers(-noise, noise + 1, f.shape)
    return np.clip(f, 0, 255).astype(np.uint8)


def crowd(n, rng, lookalike_share=0.4, spread=12):
    """`n` outfits, some of them colleagues of someone earlier in the queue.

    A colleague wears the same shirt -- the uniform case, which is what
    actually produces stolen numbers -- but their own trousers. They are
    genuinely distinguishable, just not by the strongest cue, which is exactly
    the decision these thresholds are for.
    """
    people = [(rng.integers(0, 256, 3), rng.integers(0, 256, 3))]
    while len(people) < n:
        if rng.random() < lookalike_share:
            top, _ = people[rng.integers(0, len(people))]
            top = np.clip(top + rng.integers(-spread, spread + 1, 3), 0, 255)
            people.append((top, rng.integers(0, 256, 3)))
        else:
            people.append((rng.integers(0, 256, 3), rng.integers(0, 256, 3)))
    return people


def walk_through(st, people, rng):
    """Returns, per person, the (cam1 id, cam2 id) they were left wearing."""
    out = []
    for i, outfit in enumerate(people):
        base = 1000.0 + i * GAP
        a = b = None
        for r in range(ROUNDS):
            t = base + r * DT
            a = st.update(frame_of(outfit, CAST_A, rng), [det(f"a{i}")], t,
                          camera="cam1").detections[0].track_id
            b = st.update(frame_of(outfit, CAST_B, rng), [det(f"b{i}")],
                          t + DT / 2, camera="cam2").detections[0].track_id
        out.append((a, b))
    return out


def det(track_id):
    return Detection(str(track_id), BOX, 0.9)


def score(pairs):
    linked = sum(a == b for a, b in pairs)
    owner: dict[str, int] = {}
    stolen = 0
    for i, (a, b) in enumerate(pairs):
        for number in {a, b}:
            if owner.setdefault(number, i) != i:
                stolen += 1
                break
    return linked / len(pairs), stolen / len(pairs)


def evaluate(label, n=40, **settings):
    rng = np.random.default_rng(11)
    people = crowd(n, rng)
    st = IdentityStitcher(BodySignature(), max_gap_s=9999,
                          min_similarity=0.60, **settings)
    linked, stolen = score(walk_through(st, people, rng))
    print(f"  {label:<28} linked {linked:5.1%}    stolen {stolen:5.1%}")


print("\ncross-margin sweep (all else at the new defaults):")
for m in (0.0, 0.05, 0.10, 0.15, 0.20):
    evaluate(f"--cross-margin {m:.2f}", cross_margin=m)

print("\nconfirmation sweep (cross-margin at its 0.10 default):")
for k in (1, 3, 5):
    evaluate(f"--concurrent-confirm {k}", concurrent_confirmations=k)

print("\nthe other lever, for contrast -- raising the absolute bar:")
for s in (0.50, 0.60, 0.70):
    evaluate(f"--cross-similarity {s:.2f}", cross_min_similarity=s)
