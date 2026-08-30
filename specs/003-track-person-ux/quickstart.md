# Phase 1 — Quickstart: proving Track a person works

Three levels: measurement first (the numbers gate the promises), then the
automated gates, then the by-eye session. This feature makes timing claims,
so the measurement half matters more than usual.

---

## 0. Measure before promising

```powershell
python engine/tools/measure_track.py
```

Prints and stores: archive fetch speed (× real-time, `footage` backend in
dev), processing rate (fps through detect+track+encode), and the derived
numbers — chunk-1 wait, sweep budget. **Run this before believing any
estimate the page shows.** With no stored measurement the page must say
estimates are unavailable and refuse sweeps — that state is itself a test.

## 1. The four gates

```powershell
python -m pytest engine        # count must rise above 602
python -m pyflakes engine/vg engine/tools engine/tests
cd web; npx tsc -b --force
```

## 2. The tests that matter (all in `engine/tests/test_track_page.py`)

None needs a camera, a DVR, or a model download: anchors are driven with a
fake pipeline, legs run over the `footage` backend, follows over a fake
tracker result.

| Test proves | Spec |
|---|---|
| all five anchor gates must pass; four of five writes nothing | TRK-FR-002, SC-003 |
| anchor decision uses frames the debounce would have hidden | D6 |
| skeleton returns anchors only, audit id present, audit written first | TRK-FR-003/008 |
| empty window → empty anchors, 200, offers survive | edge case |
| leg job: chunk urls grow, chunk file exists, 404-with-reason after retention | TRK-FR-004 |
| prefetch picks next anchor's camera, else neighbours, else same area | TRK-FR-005 |
| sweep estimate: allowed=false over budget, and with no measured rates | TRK-FR-007/014 |
| follow: click point picks the right body; 404 on empty ground | TRK-FR-010 |
| name appears only after sustained gate; single frame is not enough | TRK-FR-011, SC-005 |
| name gone after track loss; new body never inherits it | TRK-FR-011 |
| recording: segment per camera hop; timer stop; track-loss stop with reason | TRK-FR-012, SC-007 |
| follow/record/skeleton/leg/sweep all write audit before result | TRK-FR-008 |
| `it` role can follow, record, and search; nothing 403s by accident | auth pin |

## 3. By-eye session — needs Mohamed

```powershell
.\dev.ps1 up -Clip     # the walk-through clip is the archive in dev
```

**Live catch (SC-004, SC-005)**
1. Track → *Where is someone now*. Areas partition the grid; search finds a
   camera by name. Three clicks: area → camera → click the person.
2. The follow view moves with them (clip loops help here). No name shows.
3. Walk your own face close to the webcam camera: after a sustained clear
   look — not a glance — your name attaches. Cover your face and duck out of
   frame past the loss window: the name and the follow end, saying why.
4. Record with a 1-minute timer; cross cameras if two are up; check one
   segment per camera and the timer stop reason. Settings → audit shows every
   action.

**Past path (SC-001, SC-002)**
5. *Where did someone go* → pick yourself, today. The skeleton appears
   instantly; each stop shows its evidence on hover.
6. Click a stop: first video within ~10–15 s, your body highlighted, playback
   rolls through chunks without stalling. The next stop should open near-
   instantly (prefetch).
7. Ask for a window with nothing in it: the page says so and offers the
   sweep / hop-by-hop, no dash, no spinner.

**Sweep honesty (SC-006)**
8. Ask for a big sweep: the estimate appears before anything runs; an
   over-budget ask is refused with the arithmetic. Run an allowed one:
   progress is real, cancel stops it.

## 4. What "done" looks like

- [ ] `measure_track.py` run and rates stored; page estimates match them
- [ ] Four gates green, pytest count above 602
- [ ] By-eye session confirmed by Mohamed (SC-001..007)
- [ ] `STATUS.md` Track line rewritten (engine real, page real — no more
      "page part fake")
- [ ] Committed per increment with tests in the same commit
