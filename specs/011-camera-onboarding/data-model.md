# Phase 1 — Data model: Camera Onboarding

Nothing here is a new concept. Every field below either already exists on `CameraConfig` and is
simply never stored, or is a fact about a probe that the engine currently invents.

---

## 1. Camera — the roster row

**Where it lives.** `engine/vg/ingest/store.py`, table `camera`. The roster the engine runs on is
`merge_cameras(engine.yaml cameras, stored cameras)`, and **a stored row wins a clash** — which is
already true, already documented, and is what makes editing a config-file camera possible at all.

**Today** the table has eight columns and `CameraConfig` has fourteen fields. The six missing ones
are the reason a console-added camera can never be an identity camera or a gate camera.

| Column | Type | Default | State | Notes |
|---|---|---|---|---|
| `id` | TEXT PK | — | exists | `_slug(name)` when not given |
| `name` | TEXT | — | exists | 1–120 chars |
| `source` | TEXT | — | exists | `rtsp://…`, `webcam:N`, `file:…`. Credentials folded in here, and this column is **never** returned to a client unredacted |
| `kind` | TEXT | `RTSP` | exists | RTSP / DVR / NVR / IP camera / Webcam / File |
| `area` | TEXT | `Unassigned` | exists | groups People Counting |
| `fps` | REAL | `5.0` | exists | analytics rate, not capture rate |
| `rotate` | INTEGER | `0` | exists | 0 / 90 / 180 / 270 |
| `features` | TEXT | `''` | exists | comma-joined; **becomes a closed vocabulary** |
| `enabled` | INTEGER | `1` | exists | |
| `removed_at` | TEXT | NULL | exists | soft delete — events survive |
| `created_at` | TEXT | — | exists | |
| **`faces`** | INTEGER | `0` | **new** | the identity tier. `CameraConfig.faces` |
| **`gate`** | INTEGER | NULL | **new** | gate number. `CameraConfig.gate` |
| **`direction`** | TEXT | NULL | **new** | `entry` or `exit`. **Never `both`** — `parse` already refuses it |
| **`face_gate`** | TEXT | `''` | **new** | `person` / `frame` / empty=decide from features |
| **`live_capture`** | TEXT | `watched` | **new** | `watched` / `always` |
| **`neighbours`** | TEXT | `''` | **new** | comma-joined camera ids; a hint for the archive warm-up only |

**Migration.** Copy the idiom that is already in the codebase twice — `events/vehicles.py` and
`auth/store.py`: read `PRAGMA table_info(camera)`, then `ALTER TABLE camera ADD COLUMN …` for each
name that is absent. Six lines, no framework, and it is a no-op on a database that already has them.

**Validation.** All of it already exists in `CameraConfig.parse` and must be the only gate —
`CameraStore.add` and the new `CameraStore.update` both build a `CameraConfig` and let `parse`
refuse. In particular `parse` already enforces:

- `vehicles` in features **requires** a gate number and a direction, and a gate number **requires**
  `vehicles`. Both half-states are refused rather than half-run.
- `direction` is `entry` or `exit`. `both` is rejected outright.

**Validation this feature adds — one rule.** A feature name not in the closed set is refused, with
the unknown name in the message. Today an unknown name is accepted and silently does nothing, so a
typo means the feature never runs and nothing anywhere says why.

```
FEATURES = {attendance, counting, intrusion, track, vehicles, weapons, lostitems}
```

Both configured cameras in `engine/engine.yaml` use only names from this set, so nothing existing
fails to load.

### State transitions

```
        add                 edit                    remove
none ─────────► enabled ◄──────────► enabled     ─────────► removed (soft)
                   │                                          │
                   │ set_enabled(false)                       │ add(same id)
                   ▼                                          ▼
                disabled ──────────────────────────────────► revived
```

Two things happen on every transition and neither may be skipped:

1. **Audit first**, then write. `self._log(actor, "camera.add"|"camera.edit"|"camera.remove"|
   "camera.enable", camera_id, detail)` — with `detail` built from the **redacted** source.
2. **The stream and the features are separate.** `CameraRegistry.add/remove` is touched only when
   the stream changed (`source`, `rotate`, `fps`, `enabled`). A features-only edit must not reopen
   the camera — reopening an RTSP stream to add a tickbox is a visible stutter for no reason.

---

## 2. Feature assignment — which worker watches which camera

Not stored anywhere new. It is derived from `CameraConfig.features` (plus `faces` and `is_gate`)
and applied to the workers `LiveStore` already holds. This table is the specification of
`LiveStore._apply_features`.

| Feature name | Worker on `LiveStore` | Camera qualifies when | Governs today? |
|---|---|---|---|
| `counting` | `people_worker` | `counting` in features | yes |
| `intrusion` | `people_worker`, `zones_worker` | `intrusion` in features | **no — zones run on every enabled camera** |
| `track` | `people_worker`, `tracking` | `track` in features | yes |
| `attendance` | `recogniser` or `patrol` | `faces` or `attendance` in features | yes |
| `vehicles` | `vehicles_worker` | `config.is_gate` — features + gate + direction | yes |
| `weapons` | `weapons_worker` | `weapons` in features | **no — knives run on every enabled camera** |
| `lostitems` | `lost_watch` | `lostitems` in features | **no — any camera anybody opens** |

**The identity tier is a move, not a toggle.** `recogniser` serves cameras where
`faces or "attendance" in features`; `patrol` serves the complement. Changing `faces` therefore
means `watch` on one and `unwatch` on the other. Order matters: **watch the new tier first**, so
there is never an instant where neither is looking at that camera.

**An absent worker is skipped, and said so.** A worker is `None` when its subsystem failed to
start, and `LiveStore` already holds the reason — `zones_error`, `weapons_error`, `lost_error`,
`tracking_error`, `vehicles_error`, `people_error`, `recognition_error`. Assigning such a feature
must add the camera anyway and return that reason as a note (`P13-FR-016`). It must never refuse
the camera, and it must never accept silently.

---

## 3. Probed channel — what a recorder actually answered

A transient. Nothing about a probe is persisted; a probe is evidence for a decision the operator is
about to make, and it is stale the moment they make it.

| Field | Type | Meaning |
|---|---|---|
| `channel` | str | the value substituted into `{channel}` |
| `name` | str | what the camera will be called. Editable before adding |
| `source` | str | the URL this channel would use, **redacted** |
| `checked` | bool | `false` = the probe budget ran out before this one was tried. **Not the same as a failure** |
| `status` | `ok` / `down` / `auth` | reuses `SourceStatus`; no new vocabulary |
| `resolution` | str \| None | real, from the frame that arrived. `None` when none did |
| `latency_ms` | float \| None | real, measured |
| `error` | str \| None | the probe's own reason, exactly as `test_connection` already returns it |
| `enabled` | bool | the operator's tick. Only `status == ok` may be ticked |

**Three states that must read differently**, because the spec's edge cases require it and the
current code cannot express any of them:

- `checked=false` — we never asked. *Not checked.*
- `checked=true, status=down` — we asked and nothing came back. *No camera on this channel.*
- `checked=true, status=ok` — a frame arrived, and here is its size. *Addable.*

---

## 4. Scan result — an answer, not a list

| Field | Type | Meaning |
|---|---|---|
| `available` | bool | whether searching the network is possible at all |
| `reason` | str \| None | why not, when `available` is false |
| `devices` | list[FoundDevice] | real devices, empty when there genuinely are none |

`available: false` and `devices: []` is "we cannot look". `available: true` and `devices: []` is
"we looked and your network is empty". Today both are the same empty list, and the console renders
the second sentence for the first situation.

---

## 5. Bulk add outcome — one row per camera, never an exception

| Field | Type | Meaning |
|---|---|---|
| `index` | int | position in the submitted list, so the console can line outcomes up with rows |
| `id` | str \| None | the camera created |
| `ok` | bool | |
| `source` | str | **redacted** |
| `error` | str \| None | why this one was refused |

Always HTTP 200. A refused camera is payload; the request itself did not fail. One bad channel out
of sixteen must not refuse the other fifteen.

---

## Invariants

1. **A source string with a password never leaves the engine.** Every path returns
   `CameraConfig.redacted_source()` or `CameraSource.redacted` — sources list, probe result, bulk
   outcome, edit response, audit detail, log line.
2. **`CameraConfig.parse` is the only validator.** Nothing writes a row it has not accepted.
3. **A camera's identity never changes.** Editing writes to the same `id`, so recorded events,
   sightings, passes and scenes stay attached to it.
4. **Removal is soft.** `removed_at` is set; the events survive; re-adding the same id revives it.
5. **The audit entry precedes the write.** Always, on every one of add, edit, enable, disable,
   remove and bulk add.
6. **Geometry, where it appears, is fractions of the frame.** Unchanged by this feature — zone
   shapes stay on the Intrusion page — but the rule still applies to anything this feature returns.
