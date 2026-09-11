# Implementation context: Alert Delivery

> **11 Sep 2026, evening: T001–T043 done, the review triaged and fixed. Only T044 -
> Mohamed's checks by eye and on his phone - is left. Read
> [handoff.md](./handoff.md) first** — it says what is left and what in this tree
> belongs to other sessions.

**Written by `/speckit-plan` on 11 Sep 2026 and rewritten by `/speckit-tasks` the same
day, against commit `569efe0` on branch `Fo2sh`.** The working tree carries uncommitted
edits that are not this feature's — `engine/vg/api/live.py` (+99 lines),
`engine/vg/features/base.py` (+24), `engine/tests/test_health_load.py` (+243). Read
`git diff` before editing near them and never revert them.

Read this **before** opening any source file. Then open the named anchors only.

> Verify before trusting. Anchors drift — search for the symbol, not the line number.

---

## 1. Anchors — where each edit lands

### Engine

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `engine/vg/events/weapons.py` **CRLF** | `class WeaponSceneStore` | `__init__(database)`: `self._lock = threading.RLock()`, `self._conn = db.connect(self.path)`, `executescript(SCHEMA)`, commit. `open(self, camera_id, started_at, confidence, model_version) -> str`: `uuid4().hex`, `with self._lock:` INSERT + commit, `return scene_id`. `review(scene_id, verdict, reviewer, at, reason=None) -> bool` (`WHERE verdict = 'pending'`, `rowcount == 1`). `get(id)`. `recent(since, until=None, camera_id=None)` newest first. **No `pending()`.** Helpers `_iso`, `_to_scene` | `self.on_open = None` in `__init__`; `open(..., continues: bool = False)`; after the `with` block, `if self.on_open is not None:` call `on_open(scene_id, camera_id, started_at, confidence, continues)` inside `try/except Exception: log.exception(...)`; add `pending()` beside `recent()`: `SELECT * FROM weapon_scene WHERE verdict = 'pending' ORDER BY started_at DESC` |
| `engine/vg/events/zones.py` **CRLF** | `class SceneStore` | `open(self, camera_id, started_at) -> str`, same lock/commit shape. `recent(since_days, camera_id=None, include_replaced=True)` newest first — takes **days**, not a datetime | same hook: `on_open(scene_id, camera_id, started_at, continues)`, `open(..., continues=False)` |
| `engine/vg/events/vehicles.py` **CRLF** | `VehicleStore.record_pass` | `(at, camera_id, gate, direction, plate, confidence, votes, needs_review, today, snapshot=None, plate_crop=None) -> VehiclePass`; `status = status_for(vehicle, today)` → `unknown` / `blacklist` / `expired` / `known` (blacklist outranks expiry); builds a frozen `VehiclePass(id, at, camera_id, gate: int, direction, plate, plate_display, status, confidence, votes, needs_review, vehicle_id, owner_name, unit, snapshot, plate_crop, corrected_by)`; INSERT + commit **inside** `with self._lock:`; `return record`. `__init__` also calls `_add_missing_columns()` | `self.on_pass = None` in `__init__`; after the `with` block, before `return record`, call `on_pass(record)` in the same `try/except`. **Never pass `owner_name` onward** — the service reads `id, at, camera_id, gate, plate_display, status, confidence, needs_review` only |
| `engine/vg/features/weapons.py` LF | the `MAX_SCENE_SECONDS` branch in the state step; `def _open(self, camera_id, started_at, confidence, at=None)` | branch: `self._close(camera_id, now, "limit")` then `scene_id=self._open(camera_id, now, peak)`. `_open` calls `self.scenes.open(camera_id, started_at, confidence, self.knives.version)` | `_open(..., continues: bool = False)` → `self.scenes.open(..., continues=continues)`; the limit branch passes `continues=True`. Nothing else in the file changes |
| `engine/vg/features/zones.py` LF | the `MAX_SCENE_SECONDS` branch; `def _open(self, camera_id, at, people)` | branch: `self._close(camera_id, now, "limit")` then `self._open(camera_id, now, people)`; `_open` calls `self.scenes.open(camera_id, at)` | same: `continues` pass-through, `True` in the limit branch |
| `engine/vg/api/live.py` CRLF | `class LiveStore(MockStore)` → `def __init__(` | kwargs incl. `scenes=None, zones=None, weapons=None, weapon_scenes=None, vehicles=None, vehicle_store=None, patrol=None, users=None`; stored as `self.scenes`, `self.weapon_scenes`, `self.vehicle_store`. **`self.weapons` is a METHOD** (the knife list); the worker is `self.weapons_worker`. `self.alerts` is free | add `alerts_store=None, alerts=None` → `self.alerts_store`, `self.alerts`; `self.alerts_error: str \| None = None`; `self._started_at = datetime.now(timezone.utc)` |
| `engine/vg/api/live.py` | `def review_weapon` | audits first: `self._log(who, f"weapon.{review.verdict.value}", detection_id, review.reason)`; returns None if `self.weapon_scenes is None` or `review()` is False; `scene = self.weapon_scenes.get(detection_id)`; rebuilds via `self.weapons(scene.started_at, None)`. **Docstring says "today it hangs nothing"** | after `scene` is fetched: `if self.alerts is not None: self.alerts.verdict(scene.id, scene.camera_id, review.verdict.value, who, datetime.now(timezone.utc))`; rewrite the docstring's first paragraph |
| `engine/vg/api/live.py` | `def attention` / `acknowledge` / `alert_rules` / `delivery_targets` (~L2511) | four stubs returning `[]` / `None` / `[]` / `[]` | replace per contracts/alerts.md; delete `alert_rules` and `delivery_targets`; add `alert_settings`, `update_rule`, `add_recipient`, `edit_recipient`, `remove_recipient`, `test_send`, `deliveries`, `_attendance_counts` |
| `engine/vg/api/live.py` | `def capabilities` → `states = {…}` | `"attention": (S.DataState.UNAVAILABLE, "Alerts are not built yet. Nothing is being sent to anybody.")` | `"attention": self._attention_state()` — LIVE with `None` when `self.alerts_store` is set, else UNAVAILABLE with the database error |
| `engine/vg/api/live.py` | `def _ask_state` | `(DataState, reason \| None)`; three sentences | the shape to copy for `_attention_state` |
| `engine/vg/api/live.py` | `def health` → `pipeline = [` (~L3127) | `S.PipelineStage(key="ingest", …)`, then `self._recognition_stage()`, `_people_stage`, `_clock_stage`, `_weapons_stage`, `_vehicles_stage`, `_lost_stage`, `_workers_stage`; `struggling = any(not stage.healthy …)` raises the summary | add `self._alerts_stage()` before `_workers_stage()`, modelled on `_lost_stage` (`S.PipelineStage(key=, name=, detail=, healthy=, severity=, restartable=False)`) |
| `engine/vg/api/live.py` | `def vehicle_alerts` | derived from `self.vehicle_store.passes(limit=200, since=self._start_of_day())`, skips `status == "known"` and ids in `dismissed_alerts(since)`; returns `S.GateAlert(pass_id, kind: unknown\|blacklist\|expired, at, plate, plate_display, gate_name, …)`. Docstring: "Blacklist alerts … keep raising their Home attention item … Unknown and expired stay here" | called by `attention()`; rewrite that docstring sentence — the vehicles rule's reason switches now decide |
| `engine/vg/api/live.py` | `def dismiss_alert` | `_need_register()`; `pass_by_id` → `KeyError` if unknown; `self._log(actor, "vehicle.alert.dismiss", …)` **then** `store.dismiss_alert(...)` | the order to copy in `acknowledge()` |
| `engine/vg/api/live.py` | `_start_of_day()`, `_camera_name(camera_id)` (~L3797), module `_instant(when, clock)` (L50) | site midnight as UTC; roster name or None; `S.Instant(utc, tz_offset_minutes=clock.offset_minutes(when))` | reuse all three |
| `engine/vg/api/live.py` | `def attendance(self, mode, subject, on)`, `def groups(self)` | `attendance` → `S.AttendanceResult(expected, present, late, absent, …)`, **empty when `not self.recognition_live`**; `groups()` → `GroupSummary(name, people, here)`, includes `Everyone`, which overlaps every other group | `_attendance_counts(date) -> tuple[GroupCount, ...] \| None`: `None` when `not self.recognition_live`, else one `GroupCount` per `groups()` entry from `attendance("group", g.name, date)` |
| `engine/vg/api/store.py` CRLF | `class Store(Protocol)` (~L211) | `attention()`, `acknowledge(item_id, actor)`, `school_profile()`, `alert_rules()`, `delivery_targets()`, `audit(limit)`, `capabilities()` | replace the two alert methods with the seven new signatures |
| `engine/vg/api/store.py` | `MockStore._build_attention`, `attention`, `acknowledge`, `alert_rules`, `delivery_targets` (~L1183–1230) | two English fixtures (`breach-chem`, `cam-c3-down`); `acknowledge` does `model_copy(update={"acknowledged": True})` + `self._log(actor, "attention.ack", item_id, None)`; `delivery_targets` holds **a real-looking address, `mohamed61fouad@gmail.com`** | new-shape fixtures for `-Mock`, mutated in memory; use `security@school.example` and `+20 100 000 0000`-style placeholders; a mock test send appends `skipped: provider_missing`, never a fake `sent` |
| `engine/vg/api/store.py` | `MockStore._log` (~L1232), `CAPABILITIES` (~L910), `class SubsystemUnavailable` (L75) | `_log(actor, action, subject, detail)` inherited by LiveStore; `("attention", "Alerts")` already listed; message reaches the 503 body | reuse; no change to `CAPABILITIES` |
| `engine/vg/api/schemas.py` CRLF | `class AlertRule` (L1307), `class DeliveryTarget` (L1316), `class AttentionItem` (L1245), `class Acknowledgement` (L1258), `class LiveEvent` (L1262), `class Note` (L155), `class DataState` (L739), `class PipelineStage` (L721) | `AlertRule(key, title, detail, push, email, sms)`; `DeliveryTarget(key: Literal[app,email,sms,wa], …)`; `AttentionItem(id, kind: Literal[weapon,intrusion,camera,attendance,system], at, severity, title, detail, target, target_id=None, acknowledged=False, clip=None)`; **`Note(code, args)` — `args`, not `params`**; DataState is LIVE/UNAVAILABLE/DEMO, "there is no fourth answer"; `PipelineStage(key, name, detail: str, healthy, severity, restartable=False, model_version=None, workers=[])` | per data-model.md. Leave `LiveEvent` alone — nobody sends it and deleting it is scope creep |
| `engine/vg/api/notes.py` CRLF | `CODES: frozenset[str]` (L42), `def note(code, **args)` (L82) | Ask's codes, one comment each; `note()` refuses an undeclared code | add the six `attention.*` codes with a comment each |
| `engine/vg/api/app.py` CRLF | `lifespan`: defaults `app.state.scenes = None` … (~L306–316); `if cfg is not None and os.getenv("VG_MOCK") != "1":` (~L318); `(app.state.zones, app.state.scenes, app.state.zones_error) = _start_zones(...)`, `(app.state.weapons, app.state.weapon_scenes, app.state.weapons_error) = _start_weapons(...)`, `_start_lost`, `(app.state.vehicles, app.state.vehicle_store, app.state.vehicles_error) = _start_vehicles(cfg, registry, roster)` (~L397–424); `store = LiveStore(` (~L468) then `store.recognition_error = …`, `set_store(store)` | the helpers start their workers before returning | build `AlertStore(_database(cfg))` and, if `cfg.alerts.enabled`, `AlertService(...)` just **before** `_start_zones`; attach each hook on the line after its helper returns; pass `alerts_store=`, `alerts=` to `LiveStore(`; after it, `bind(...)` then `start()` in a `try` that sets `store.alerts_error` |
| `engine/vg/api/app.py` | `lifespan` `finally:` | `SHUTTING_DOWN.set()`; counts stop; `recorder.stop_all()`; lost watch stop; `for worker in (weapons, zones, people, recogniser, patrol, tracking): worker.stop()` (~L538); `registry.stop()`; then archive runner, then store closes ("after the workers, never before") | `alerts.stop()` right after `registry.stop()`; `alert_store.close_db()` with the other store closes |
| `engine/vg/api/app.py` | `ack_attention` (~L3572), `get_alerts` / `get_delivery` (~L3587, the last endpoints in `create_app`), `dismiss_alert` endpoint (~L3332) | `ack_attention(item_id, ack: S.Acknowledgement, store)` takes the actor **from the body**; dismiss takes `user: auth_deps.CurrentUser` and passes `user.name` | ack: drop the body, add `user: auth_deps.CurrentUser`; replace the two GETs with the endpoints in contracts/alerts.md; map `SubsystemUnavailable` → 503, `KeyError` → 404, `DuplicateRecipient` → 409, `ValueError` → 422 |
| `engine/vg/auth/deps.py` LF | `ADMIN_WRITE_PREFIXES` (L97) | `("/cameras", "/people", "/zones", "/vehicles")`, a comment per entry; `OPERATOR_WRITE_PREFIXES = ("/vehicles/alerts",)` checked first | add `"/settings"` with a comment. **Do not add `/attention` anywhere** — `test_vehicle_alerts.py` pins `OPERATOR_WRITE_PREFIXES == ("/vehicles/alerts",)` |
| `engine/vg/config.py` CRLF | `class AskConfig` (L976), `class EngineConfig` (L1128), `HoursConfig` (~L630), `_load_dotenv` (L45) | `AskConfig.parse(raw, where)` rejects unknown keys with `ConfigError`; `HoursConfig.term_from/term_to: str = ""`; `_load_dotenv` fills `os.environ`, existing variables win, called from `load()` | `AlertsConfig` copying `AskConfig.parse`; `EngineConfig.alerts`; parse `alerts:` in `load()` beside `ask:` |
| `engine/vg/clock.py` LF | `class SiteClock(Clock)`, `class FixedClock(Clock)` | `local(when)`, `local_date(when) -> str`, `local_time(when)`, `today()`, `offset_minutes(when)`; `FixedClock(offset_minutes)` for tests | the service takes a `Clock` and a `now` callable |
| `engine/vg/ingest/registry.py` | `CameraRegistry.workers: dict[str, CameraWorker]`, `.disabled`; `CameraWorker.status` | `status` → `"ok" \| "down" \| "auth"`; `down` after only `STALE_AFTER_SECONDS = 10.0` with no frame. Last frame time is `worker.source.health.last_frame_at` (set per frame in `ingest/source.py`) | `offline_cameras()` reads both; ignores `disabled` |
| `engine/engine.yaml` CRLF | `ask:` (L165), `hours:` (L26), `timezone: Africa/Cairo` (L11) | **the file is `engine/engine.yaml`**, not the repo root. `hours.term_from: "2025-09-01"`, `term_to: "2026-06-20"` — **the term has ended** | add `alerts:` after `ask:`, every key commented. Do not change the term dates; that is Mohamed's to do (quickstart) |
| `engine/.env.example` LF | whole file | camera variables with comments | append the six variables, empty, under a comment saying Twilio and Google see every message |
| `engine/tests/test_api.py` LF | `REQUIRED = [` (~L280) | includes `("GET", "/settings/delivery")`; paths normalise `{item_id}` → `{id}` | remove `/settings/delivery`; add the new routes |

### Console and phone

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `web/src/services/wire.ts` CRLF | `AttentionItem` (L653), `AlertRule` (L694), `DeliveryTarget` (L703) | mirror of schemas.py | per data-model.md |
| `web/src/types.ts` CRLF | `AlertChannel` (L518), `AlertRule` (L520), `DeliveryKind` (L527), `DeliveryTarget` (L529), UI `AttentionItem` (L412: `id, kind, icon, tone, title, sub, action, to: ToolId`) | `AlertChannel = 'Push' \| 'Email' \| 'SMS'` | delete the four alert types; Settings uses the wire types |
| `web/src/services/api.ts` CRLF | L1379–1391: `getAttention`, `acknowledgeAttention(id, actor)`, `getAlertRules`, `getDeliveryTargets` | imports `get, post, patch, del, …` from `./http`. **`http.ts` has no `put`** | `acknowledgeAttention(id)` with no body; replace the two getters with the seven new calls |
| `web/src/app/useAttention.ts` CRLF | `TARGET`, `ACTION` keyed by `WireAttentionItem['kind']`; `toAttentionItem(item, t)`; `useAttention(): AttentionItem[]`; `POLL_MS = 15_000` | **`toAttentionItem` calls `useLanguage()` inside a plain function** — works only by accident of call order | add `vehicles`; take `language` once in the hook and pass it down; `sub` uses `noteText(t, item.note) \|\| item.detail`; return `{ items, acknowledge }` |
| `web/src/i18n/keys.ts` CRLF / `en.ts` CRLF / `ar.draft.ts` CRLF | `NoteCode` union (L28), `UiKey` (L40), `MessageKey = UiKey \| \`note.${NoteCode}\`` (L766); note wordings like `'note.ask.unsupported'` (en ~L777, ar.draft ~L785) | `en.ts` is `Record<MessageKey, string>`, so a missing English wording fails `tsc`; `ar.draft.ts` is `Partial` and dev-only | add the keys named in tasks.md |
| `web/src/services/notes.ts` LF | `noteText(t, note)`, `noteSentence` | looks up `note.<code>`; an unknown code renders "unknown code" rather than nothing | use as is |
| `web/src/pages/Settings.tsx` LF | imports (L7–9), `DELIVERY_META`, `CHANNELS`, `fmtTime`, quiet state (L113–116), `toggleChannel` (L129), `toggleDelivery` (L137), the Alerts card with the quiet-hours block, the "Where alerts reach you" card; `loadError`, `note(...)`, `tick` reload | React-state only. **`fmtTime` is also used by the School profile rows (L150, L167) — keep it.** The School profile card is out of scope; leave it alone. **Byte-identical to `mobile/src/pages/Settings.tsx`** | three real cards; delete quiet hours, `DELIVERY_META`, `CHANNELS`, `toggleChannel`, `toggleDelivery`, `delivEdit`, the two old cards; copy the bytes to mobile |
| `web/src/pages/Home.tsx` CRLF | `const attention = useAttention();` (L20); `attention.map((item) => …)` card with one `linkbtn` | no acknowledge control anywhere in `web/src` or `mobile/src`. **Byte-identical to `mobile/src/pages/Home.tsx`** | `const { items: attention, acknowledge } = useAttention();`; a second `linkbtn` "Acknowledge"; copy the bytes to mobile |
| `web/src/components/ui.tsx` LF | `Field({label, children})`, `Select({value, onChange, options, label?})`, `Toggle({on, onToggle, label})`, `Empty`, `LoadError`, `Badge` | — | use as is |
| `web/src/app/AuthContext.tsx` | `useAccount()` (L129) | `.role` is an interface hint; the server decides | hide the write controls for a guard |
| `web/src/app/navigation.ts` | tool rows | paths `/attendance`, `/intrusion`, `/weapons`, `/vehicles`, `/system`, `/settings` | the message links use these paths |
| `docs/PLAN.md` CRLF | L343 `\| A weapon alert always waits for a human \| No notify/call/lock …`; L59 `\| FR-14 \| Alert delivery \| missing \|`; L51 FR-06 "no alert fan-out until P9"; L286 `### P9` | — | rewrite the row, mark FR-14 done, update FR-06, add the dated amendment under P9 |
| `STATUS.md` CRLF | L20 knife "**No alerts fan out**", L22 vehicle gate "**Nothing is blocked and nothing is alerted** … no message goes anywhere", L23 "Users, audit, notifications" | — | update those three; leave lost bag's "Nothing is alerted" |

## 2. Things to copy, not invent

- Store with lock, `SCHEMA`, `db.connect`, `_iso` → `events/weapons.py::WeaponSceneStore.__init__` and `open`.
- Audit first, then write; `KeyError` for unknown, `False` for already done → `api/live.py::LiveStore.dismiss_alert`.
- Derived items from today's rows minus acknowledgements → `api/live.py::LiveStore.vehicle_alerts`.
- A capability state with one sentence per cause → `api/live.py::LiveStore._ask_state`.
- A System Health row → `api/live.py::LiveStore._lost_stage`.
- Config block with unknown-key rejection → `config.py::AskConfig.parse`.
- A provider seam with an injectable transport and a failure classifier → `ask/parser.py::CloudParser` and `_reason(exc)`.
- Secret redaction test → `tests/test_sources.py::SENTINEL` and `test_a_password_never_reaches_the_audit`.
- `LiveStore.x is not MockStore.x` pin → `tests/test_ask.py` (~L561).
- A `LiveStore` over a throwaway database → `tests/test_groups.py::store` (`build(...)`; close the gallery **before** `tmp.cleanup()`); `conftest.py::bare_live_store` (`CameraRegistry([])`), `live_ish_store` (`CameraRegistry(cfg.cameras)`), `authed(app, role)`, `sign_in`.
- An endpoint taking the actor from the session → `app.py::dismiss_alert` endpoint.
- Console: `useAsync(load, deps, initial, refreshMs?)` → `{data, error, loading, reload}`; `Card`, `Toggle`, `Select`, `Field`, `Empty`, `LoadError`, `Badge tone=`; `chip-btn chip-btn--on|--off`, `linkbtn`; a `Note` worded by `services/notes.ts::noteText`.

## 3. Traps

- **Every knife and zone incident longer than two minutes is cut and reopened at once.**
  A hook on "scene opened" alone would text the same person every two minutes. The
  `continues` flag is the fix; `test_alerts_events.py` holds it.
- **The launcher stops the engine with a hard kill** (a job object marked
  `KILL_ON_JOB_CLOSE`): no `finally` runs. Anything kept only in memory is lost at stop.
  That is why rows are written before any courier call and `start()` marks leftovers
  `failed: engine_stopped`.
- **A LIVE capability must carry no reason** — `test_no_fixtures.py::test_a_live_capability_offers_no_excuse`.
  And an UNAVAILABLE capability's getter must return `[]` —
  `test_nothing_unavailable_still_returns_rows`, which calls `store.attention()` on
  `bare_live_store`. So: `attention()` returns `[]` whenever `alerts_store` is None, and a
  missing key is said on System Health, never as a capability reason.
- **`test_notes.py` scans the source with `ast` for literal `note("…")` calls.** Every
  declared code must be emitted literally and every emitted code declared. An f-string
  code is invisible to it. Declare, emit and word each code in the same task.
- **`Note` is `{code, args}`**, not `params`.
- **`services/http.ts` has no `put`.** The rule update is `PATCH`.
- **`test_api.py::REQUIRED` lists `/settings/delivery`.** Removing the route without
  editing the list fails the suite.
- **`ack_attention` takes the actor from the request body today.** Anyone could
  acknowledge under any name. The contract moves it to the session and removes
  `Acknowledgement`.
- **`useAttention.ts::toAttentionItem` calls `useLanguage()` outside a component.** Do not
  add another hook call there; fix it while the file is open.
- **`HoursConfig.term_from/term_to` default to `""`**, and `engine/engine.yaml`'s term
  ended on 20 Jun 2026. `report.state` must say `no_term_dates` / `after_term` rather than
  the report going quietly silent.
- **`groups()` includes `Everyone`, which overlaps every other group.** List groups as
  they come; never add them up.
- **`attendance("group", …)` returns zeros when recognition is not live.** The report must
  then be `skipped: attendance_unavailable`, never sent as zeros that read "everyone
  absent".
- **Camera `status` is `down` after only 10 s.** The five-minute rule is the service's;
  time it from `last_frame_at`, not from `status` alone.
- **A Twilio error from `urllib` can carry the request URL, which contains the Account
  SID.** Build `provider_reason` from Twilio's JSON `message` and `code` or the exception
  class name, never `str(exc)`, and run `redact()` over it anyway.
- **Line endings** — CRLF: `events/weapons.py`, `events/zones.py`, `events/vehicles.py`,
  `api/live.py`, `api/app.py`, `api/schemas.py`, `api/store.py`, `api/notes.py`,
  `config.py`, `engine/engine.yaml`, `types.ts`, `services/api.ts`, `services/wire.ts`,
  `app/useAttention.ts`, `i18n/en.ts`, `i18n/keys.ts`, `i18n/ar.draft.ts`,
  `pages/Home.tsx`, `STATUS.md`, `docs/PLAN.md`. LF: `auth/deps.py`, `features/weapons.py`,
  `features/zones.py`, `clock.py`, `engine/.env.example`, `tests/test_api.py`,
  `pages/Settings.tsx`, `services/http.ts`, `services/notes.ts`, `components/ui.tsx`.
  Use the Edit tool or byte-preserving scripts (`open(p, newline="")`); **never
  `Path.write_text` on Windows**, which turns every `\n` into `\r\n`. Check
  `git diff --stat` before committing.
- **`mobile/src/pages/Settings.tsx` and `Home.tsx` are byte copies, not parity-held.**
  Copy bytes after editing the web files (`Copy-Item`), then run the mobile `tsc`.
  Forgetting passes web CI and fails mobile CI.
- **Twilio WhatsApp refuses free-form business-initiated bodies on a production sender.**
  On the sandbox they work after the join phrase. A refusal is a `failed` row with
  Twilio's reason — correct behaviour, not a bug.
- **Other sessions share this working tree.** Feature 014 (`specs/014-mobile-ui-parity`)
  is redesigning the phone's pages, so `mobile/src/pages/Settings.tsx` and `Home.tsx`
  may stop being byte copies; the School profile session is editing the same Settings
  page, the `/settings` permission line and the settings endpoints. 014 has pointed
  `.specify/feature.json` at itself. See tasks.md, "Working alongside other sessions".
- **`weapon_scenes`, `scenes` and `vehicle_store` may each be None** on `LiveStore`.
  `attention()` skips a None source rather than raising.
- **`mohamed61fouad@gmail.com` sits in a mock fixture today.** Do not carry a real
  address into the new fixtures.

## 4. Baseline

- `python -m pytest engine --co -q` → **1564 tests collected** at `569efe0` with the
  working-tree edits present.
- Full run, same tree, 11 Sep 2026: **1558 passed, 6 skipped, 0 failed** (progress
  dots counted; the run printed no summary line). Other sessions keep editing this
  tree, so re-run before starting and treat a new failure you did not cause as
  information, not yours to fix quietly.
- Known flaky under load: `test_recording` forgotten-recording and `test_lost_bag`
  interest-lapse — rerun alone before believing either.
- New test files: `test_alerts.py`, `test_alerts_api.py`, `test_alerts_events.py`,
  `test_alerts_feed.py`, `test_alerts_report.py`.

## 5. Answered while writing tasks

- `WeaponSceneStore` has no pending query — add `pending()`.
- `SceneStore.recent(since_days, camera_id=None, include_replaced=True)` takes days and
  returns replaced rows by default; filter by `_start_of_day()` after `recent(1)`.
- `VehicleStore.record_pass` commits inside the `with` block; the hook goes after it.
  **Superseded 11 Sep 2026:** the gate hook fires from `VehicleStore.finish_pass`, once
  the reader is done with the car - see plan.md §1.
- `dev.ps1 up -Clip` only sets `VG_CAMERAS`; `alerts.console_url` has to be set in
  `engine/engine.yaml` to see links during a clip run.
- The mobile CI job runs `node node_modules/typescript/bin/tsc -b --force` in `mobile/`,
  so a stale import in the phone's Settings copy fails it.

## 6. Still unknown

- The exact Twilio error codes returned for the sandbox before the join phrase is sent;
  the quickstart's real-phone half will show them.
- Whether Gmail's `send_message` returns anything usable as an id; the plan uses the
  `Message-ID` header the sender sets itself.
