# Quickstart — proving Camera Onboarding works

How to check each part of this feature by hand and by test. Nothing here needs a recorder to be
bought; the honest-failure paths are the ones a real site hits first anyway.

## Before anything

```powershell
.\dev.ps1 doctor
```

Prints the current school-hours window every time, so a sighting outside it is never a surprise.

**Create an account before starting the engine, or nobody can sign in:**

```powershell
python engine\tools\create_user.py
```

---

## The fast loop — tests, not a browser

Tests beat hot reload here: milliseconds, no server, no device locked. Do not enable `--reload` on
the engine; it orphans processes on Windows.

```bash
python -m pytest engine/tests/test_sources.py engine/tests/test_feature_assignment.py -q
```

Run from the **repo root**, as `python -m pytest engine`. Three tests in `test_track_page.py` read
files by relative path and fail from inside `engine/`.

Fixtures to build on, from `engine/tests/conftest.py`:

| Fixture | Gives you |
|---|---|
| `authed(app, role="admin")` | a `TestClient` already carrying a session |
| `sign_in(app, role)` | a bearer token, and attaches `app.state.users` |
| `bare_live_store` | `LiveStore` with every subsystem absent — the right base for the "feature not running" notes |
| `live_ish_store` | `LiveStore` with cameras configured |

A store with real data is built by hand, not by fixture — copy the `store` fixture in
`test_groups.py`. **Close the gallery before the tempdir**, or Windows fails the teardown.

---

## 1 · The recorder no longer lies

The single most important check, and it needs no recorder.

```bash
curl -X POST localhost:8000/sources/dvr \
  -H "Content-Type: application/json" \
  -d '{"host":"10.0.0.99","username":"admin","password":"x",
       "template":"rtsp://{host}:554/ch{channel}","channels":["1","2","3"]}'
```

**Expect** `200`, `reachable: false`, a reason, and `channels: []`.

**Today** you get sixteen channels, `status: ok`, `704x576`, from a host that does not exist.

Then point `template` at something that does answer — the loopback RTSP the repo already assumes
for `cam-rtsp-1`, or a second webcam — and expect only channels that returned a frame to come back
`ok`, each with a **real** resolution.

Pin it with the guard test, copying the shape of the existing `LiveStore.ask is MockStore.ask`
assertion in `test_ask.py`:

```python
def test_live_store_does_not_inherit_the_dvr_fixture():
    assert LiveStore.connect_dvr is not MockStore.connect_dvr
```

**Budget check:** ask for 32 channels against an unreachable host with `budget: 5`. Expect the call
to return in about five seconds, with the channels it never reached marked `checked: false` — not
`down`. Those are different facts.

---

## 2 · Nothing appears that was not saved

```powershell
.\dev.ps1 up -Mock          # console work: starts in under a second, no models
```

On System Health:

1. Press **Scan**. Expect a sentence saying searching the network is not available, and why.
   Not "0 devices found".
2. Connect a recorder, tick channels, type a name and pick an area for each, press Add.
3. **Refresh the page.** Every camera is still there with the name and area you typed.
4. Stop and restart the engine. They are still there.

The names and areas surviving is the specific check: the channel `name` input is uncontrolled
today and the area `<select>` has no handler, so what you type is discarded before the fake save
even gets to it.

Also confirm the **capture service banner at `192.168.1.10` is gone**. It is a ticked device that
does not exist.

---

## 3 · The feature list governs

Use the recorded clip, not the webcam — identical every run, locks no device, 21 labelled
ground-truth marks.

```powershell
.\dev.ps1 up -Clip
```

**Knives.** `cam-laptop` lists `attendance, counting, intrusion, track, vehicles` — no `weapons`.

- Before: knife detection runs on it anyway.
- After: it does not, and System Health says no camera is set to check for knives, in the same
  sentence shape the vehicle gate already uses for "No camera is set up as a gate".
- Add `weapons` from the console and it starts — **within 10 seconds, with no restart**.

**Isolation, which is the rule that matters most here.** With two cameras both carrying `counting`:

- Remove `counting` from one.
- That camera stops being counted; **the other keeps counting without a gap**.
- Every other feature on the first camera keeps running.

**The unwatch race** — worth a test of its own, because the codebase already paid for this once.
Mark a camera restricted, let a scene open with a recording running, then unwatch `intrusion` on
it. The scene must close with a reason and its clip must survive. Closing a scene from the request
thread while the camera's own thread is mid-`analyse` is what once destroyed the recording of the
scene that was running — see the docstring on `ZonesWorker.set_restricted`.

---

## 4 · A camera can be corrected

1. Add a camera with a typo in its name and the wrong area.
2. Edit it. Expect `restarted: false` — a features-or-name edit must not reopen the stream.
3. Change its `fps`. Expect `restarted: true`.
4. Confirm its recorded events are still attached to it. Its `id` must not have changed.
5. Edit `cam-laptop`, which comes from `engine.yaml`. Expect `shadowsConfig: true`, and a sentence
   on screen saying what happens to this camera the next time the config file changes.

---

## 5 · Bulk add reports every outcome

Submit sixteen cameras where the fourth has a duplicate id.

**Expect** `200` and sixteen outcomes: fifteen `ok`, one refused with its reason. Not a 4xx, and
not fifteen cameras silently missing.

While it runs, watch an already-running camera on another tab. It must not stutter.

---

## 6 · No password anywhere

Add a camera as `rtsp://admin:hunter2@10.0.0.5/stream`. Then grep for `hunter2` in:

- every `/sources` response, the probe result, the bulk outcome, the edit response
- the engine log
- `GET /audit`
- any CSV the console can export

**Expect zero hits.** Write it as a test with a known sentinel password — it is the cheapest
possible guard on `P13-FR-027` and it covers every path at once.

---

## 7 · Only administrators

Sign in as `it` rather than `admin` and try every write: `POST /sources`, `POST /sources/bulk`,
`PATCH /sources/{id}`, `DELETE /sources/{id}`, `POST /sources/dvr`.

**Expect 403 on all of them**, decided by path in `auth/deps.py`, not by the console hiding a
button. `/sources` is already in `ADMIN_PREFIXES`, so this should pass without any new code — the
test exists to prove the new routes really did land under that prefix.

---

## Before calling it done

The four gates, from `AGENTS.md`. All four, every time.

```powershell
.\dev.ps1 test
```

or individually:

```bash
python -m pytest engine
```

```bash
python -m pyflakes engine/vg engine/tools engine/tests
```

```bash
cd web; npx tsc -b --force
```

- `pytest` green, and **the count must not drop**. Baseline is in `context.md`.
- `pyflakes` clean — this catches the exact bug class that once silently killed face recognition.
- `tsc -b --force`, never `--noEmit`: project references make that a silent no-op.
- Then `.\dev.ps1 up -Clip` and confirm the pipeline behaviour on the recorded clip.

**Ask Mohamed for a manual check** on the two things only an eye can settle: that a real recorder's
channels come back correct against real hardware, and that adding a camera on a busy site does not
make any other camera stutter.
