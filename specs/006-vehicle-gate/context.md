# Implementation context: Vehicle Gate

**Written by `/speckit-plan` on 2026-08-24, against commit `e9ba8dd`.**

Read this **before** opening any source file. Then open the named anchors only — not
the files around them.

> Verify before trusting. This is a snapshot; if it disagrees with the code, the code
> wins and this file is wrong. Anchors drift — search for the symbol, never the line
> number.

---

## 1. Anchors — where each edit lands

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `vg/config.py` | `class CameraConfig` | frozen-ish dataclass: `id, name, source, kind, area, fps, enabled, features: tuple, rotate, faces: bool, neighbours: tuple`. Built by `parse(raw, where)` which validates `rotate ∈ {0,90,180,270}` and `0 < fps <= 60`, raising `ConfigError(f"{where}...")` | add `gate: int \| None = None`, `direction: str \| None = None`; validate direction ∈ {entry, exit} — **reject `both`** |
| `vg/config.py` | `class ModelConfig` | `name, task, weights: Path, imgsz=640, conf=.25, iou=.45, classes: tuple, device="auto", half=True, version`. `parse` resolves relative `weights` against `REPO_DIR`, rejects `conf` outside `0<c<1` | no change — the plate entry uses it as-is |
| `vg/infer/shared.py` | *(module)* | shared inference helpers | **add `weights_to_load(cfg) -> (Path, str)`** — the engine picker |
| `vg/infer/persons.py` | `PersonDetector.export_tensorrt` | exists, `format="engine", imgsz, half, workspace, device=0`. **Nothing calls it.** Sibling copies in `weapons.py` and `bags.py` | keep; call it from the new tool |
| `vg/infer/persons.py` | `_resolve_device` | `"auto"` → `"cuda"` if `torch.cuda.is_available()` else `"cpu"` | leave. Fallback is to `.pt` **on CUDA**, never CPU — the picker chooses weights, not device |
| `vg/features/base.py` | `class FeatureWorker(ABC, Generic[R])` | subclass implements **only** `analyse(frame) -> R`. Owns threads, rate limit, boost, `RESULT_TTL_SECONDS=3.0`, `BOOST_TTL_SECONDS=2.0`, one thread per camera | subclass it. **Write no concurrency code** |
| `vg/features/weapons.py` | `WeaponsWorker.analyse` | the closest analogue: gates the second model behind the first, keeps a per-camera state machine, timestamps from `frame.captured_at` **never `time.monotonic()`** | copy the shape for `VehiclesWorker` |
| `vg/events/weapons.py` | `SCHEMA` / `WeaponSceneStore` | `__init__(database)` → `connect()`, `executescript(SCHEMA)`, `_lock`, every read/write under `with self._lock`. Has `expire(older_than)` and `close_db()` | copy wholesale for `VehicleStore` |
| `vg/events/weapons.py` | `_iso`, `_parse`, `_unlink`, `_to_scene` | module-level helpers already written | reuse the shapes; don't re-derive datetime parsing |
| `vg/api/live.py` | `LiveStore._boxes` | dispatches on `feature`: `"track"`, `("counting","intrusion")`, `"weapons"`, `"lost"`, then a **face default** | add `if feature == "vehicles": return self._plate_boxes(camera_id)` **above the face default** |
| `vg/api/live.py` | `LiveStore.capabilities` | builds a `states` dict with a local `live(available, reason, detail)` helper, then maps to `S.Capability(key, name, state, reason)` | add a `"vehicles"` entry |
| `vg/api/live.py` | `_weapons_stage` | returns `S.PipelineStage`; healthy detail is `f"{version} on {device} - {n} camera(s), {ms}ms last inference"` | copy as `_vehicles_stage`; **and add the loaded form to this and every sibling stage** — that one f-string is P6-FR-035 |
| `vg/api/live.py` | `_instant` | datetime → wire `Instant`. Offset is **per-instant, not per-startup** | never build an `Instant` by hand |
| `vg/api/live.py` | `self._log(actor, action, subject, detail)` | the audit entry; written **before** the thing it records | export writes audit first |
| `vg/api/store.py` | `class Store(Protocol)` | ~50 `def x(...) -> T: ...` stubs incl. `attention()`, `acknowledge(item_id, actor)`, `overlay(camera_id, feature)` | add the vehicle methods |
| `vg/api/store.py` | `MockStore.overlay` | returns `[]` with a comment about why an honest empty beats another camera's fixtures | leave alone. `MockStore` must not gain vehicle fixtures |
| `vg/auth/deps.py` | `ADMIN_WRITE_PREFIXES` | `("/cameras", "/people", "/zones")` | add `"/vehicles"`. **Not** `ADMIN_PREFIXES` |
| `vg/api/app.py` | `_mount(app)` | every endpoint, one function. `StoreDep` for the store, `auth_deps.CurrentUser` for the caller | add the `/vehicles` routes |
| `web/src/app/routes.tsx` | the `<Route>` block | `path="weapons"`, `path="lost-items"` … inside `<RequireSignIn><AppShell/></RequireSignIn>` | add `path="vehicles"` |
| `web/src/pages/Weapons.tsx` | `export function Weapons` | the page to copy: `useCapability`, `useAsync(load, deps, initial, refreshMs)`, module-level `NO_X` constants as stable initials, `running = capability?.state === 'live'` | copy the shape for `VehicleGate.tsx` |

---

## 2. Things to copy, not invent

- Threading, rate limiting, boost → subclass `features/base.py::FeatureWorker`. It is
  ~200 lines you must not rewrite.
- A store with schema + lock + expiry → copy `events/weapons.py::WeaponSceneStore`.
- Two models where the second is gated by the first → `features/weapons.py`, module
  docstring lines 1–16. It is the same cost argument, verbatim.
- Duplicate-key handling → `auth/store.py::UserStore.create_user`, just rewritten for
  the sign-up feature: hash/normalise **outside** the lock, let the `UNIQUE`
  constraint decide, translate `sqlite3.IntegrityError` into a typed error. The plate
  register has exactly this race.
- A closed value set validated in Python → `auth/store.py::ROLES` (`CATEGORIES` here).
- Test fixtures → `conftest.py`: `authed(app, role=)`, `sign_in`, `bare_live_store`,
  `live_ish_store`. A store with real data is built **by hand** — copy the `store`
  fixture in `test_groups.py`.
- The Arabic plate chip markup → the design file
  `design/24-8 design/VisionGuard.dc.html`, the `<span>` with `مصر · EGYPT`. It
  appears five times there; extract it once as `Plate.tsx`.

---

## 3. Traps

- **TensorRT is installed now** — `tensorrt 11.2.1.2`, the **cu13** line, and it
  imports cleanly alongside `torch 2.11.0+cu128`. The cu12/cu13 mismatch looks like it
  must matter and does not: TensorRT ships its own CUDA runtime. Do not spend time
  pinning. If a cu12 build is ever genuinely needed, install
  `tensorrt_cu12_bindings` + `tensorrt_cu12_libs` directly — `--only-binary=:all:` on
  the meta-package fails misleadingly because the meta-package is an sdist.
- **A fresh `pip install tensorrt` takes ~20 minutes and prints nothing**, because it
  builds a 1.96 GB wheel at install time. It is not hung.
- **`export_tensorrt` writes `<stem>.engine`, not `<stem>-<imgsz>.engine`.** ultralytics
  names the output after the weights file with no size suffix, so `build_engines.py`
  must rename it. Skip that and the picker never finds what it just built, and the
  self-enforcing size rule quietly stops enforcing anything.
- **A TensorRT export takes minutes per model and is silent for most of them.** Six
  models is a coffee break, not a hang.
- **The five `.engine` files on disk are unusable.** Built by ultralytics 8.4.46,
  8.4.7 is installed, and `yolov8s-480.engine` is 480px while the person model is
  configured at 640. Do not adopt them — rebuild. The `<stem>-<imgsz>` naming is what
  makes the size mismatch self-enforcing.
- **`_boxes` face default.** Adding the `vehicles` branch below it draws a person's
  **name** on a car. The comment at the `weapons` branch says knife detection shipped
  with exactly this branch missing.
- **`CameraFrame` with `live` also polls recognition boxes, which carry names.** Pass
  `detections={false}` on every gate camera tile.
- **`Fraction`/`Confidence` wire types validate 0..1.** Clamp plate boxes before
  sending or the response 500s — degradation as a 5xx is the thing rule 7 forbids.
- **Mixed line endings, no `.gitattributes`.** `api/*.py`, `services/*.ts`, `types.ts`
  are CRLF; most else LF. Read/write bytes or check `b"\r\n" in path.read_bytes()`
  first. `git diff --stat` catches a whole-file rewrite.
- **Windows teardown**: close a store before its `TemporaryDirectory`.
- **`--reload` orphans processes on Windows.** Don't.
- **`npx tsc -b --force`**, never `tsc --noEmit` — project references make the latter a
  silent no-op.
- **The design file's numbers are fake.** `2,140` · `148` · `121` · `27` · `6` · `1` ·
  `4` · `Last import: 2,140 rows · 6 skipped as duplicates · 12 Aug`. None ships.
- **`test_authorisation.py::test_only_the_three_agreed_paths_are_public`** is a
  tripwire on `PUBLIC_PATHS`. Vehicles adds nothing public, so it should stay green —
  if it fails, something was made public by accident.
- **`models/Gate/` is untracked**, and gate-anpr's own `.gitignore` excludes `*.pt`.
  Decide where the two plate weights live in `models/` before wiring `engine.yaml`.

---

## 4. Baseline

- `python -m pytest engine` → **868 passed** at `e9ba8dd` (2 skipped are
  `@pytest.mark.camera`, expected without `--camera`).
- New test files: `test_platetext.py`, `test_vehicle_voting.py`,
  `test_vehicles_store.py`, `test_vehicles_api.py`, `test_engine_selection.py`.
- Nothing is failing before this feature starts.
- Working tree already carries the open-sign-up change (`/auth/register`), which added
  23 tests to reach 868. Unrelated to this feature.

---

## 5. Still unknown

- **Whether `bagsearch.pt` exports to TensorRT at all.** It is a YOLO-World stripped of
  its CLIP encoder by `engine/tools/strip_clip.py`. Try it; if it fails, P6-FR-033
  already covers it — report and keep running on `.pt`. Do not spend the day on it.
- **Real plate-read accuracy on the laptop webcam.** The supplied models are trained on
  the Egyptian EALPR set. Whether a plate held up to a laptop camera clears the 60-px
  floor is a measurement, and only Mohamed can make it.
- **Where the two plate weights should live.** `models/plate_detector.pt` /
  `models/char_detector.pt` matches every other model's placement, but they are
  currently four directories deep in untracked `models/Gate/`, and `*.pt` is
  gitignored inside that subtree.
- **Whether TensorRT can build on this GPU at all.** Established so far:
  `trt.Builder()` **segfaults** on 11.2.1.2-cu13 (RTX 2080, Turing SM 7.5), and
  **Python 3.14 has wheels for 11.1 and 11.2 only** — every 10.x release predates
  cp314, so pinning down to a Turing-supported 10.x is not available without changing
  Python version. The open test is 11.2-cu12: if it also segfaults the cause is
  Turing, not the CUDA line, and Slice A must fall back to `.pt` on CUDA on this
  machine while still building the tooling for the RTX 6000 Ada workstation.

  **This does not block the feature.** P6-FR-033 already says: no usable engine means
  `.pt` on CUDA, working, and System Health saying so. The plan was written for
  exactly this outcome. What it does change is that Slice A's honest result here may
  be "acceleration is unavailable on this GPU/Python combination, and the console now
  says so" — which is still a strictly better state than the silent one it replaces.
