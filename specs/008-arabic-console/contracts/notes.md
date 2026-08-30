# Contract: note codes

The engine says *what happened*. The console says it *in a language*.

A `Note` is `{ code, args }`. The code is the contract; the wording is not.
Changing an English sentence must never require an engine deploy, and changing
a code must break the build on both sides.

---

## Rules

1. Every code emitted anywhere in the engine MUST be declared in
   `engine/vg/api/notes.py`. `engine/tests/test_notes.py` walks the AST for
   `note(...)` calls and fails if one is missing, and fails again if a declared
   code is never emitted.
2. Every code MUST have an entry in `web/src/i18n/en.ts`. The `MessageKey` union
   makes that a compile error, not a runtime surprise.
3. `args` values are **data** — a name, a count, a number of minutes. Never a
   phrase. If an arg would be an English phrase, it needs its own code.
4. A wording MUST carry the **consequence**, not only the cause (`P11-FR-006`).
   `gate.noExitCamera` is not "no exit camera"; it is "no exit camera, so cars
   leaving are not being counted." Dropping the second half is a new bug.
5. An unknown code renders `t('note.unknown', { code })` (`P11-FR-007`).

### The one honest exception

`health.*Failed` carries `{ why }` — the text of the exception that stopped a
subsystem starting. That text comes from a library and is English in both
languages. It is a technical diagnostic, it is shown beside a translated
sentence that explains what it means, and it is not pretended to be otherwise.

---

## Inventory

37 production sites and 28 demo sites, from an AST scan at `988a140`. The codes
below are the proposal; the implementing chat confirms each against the call
site it replaces.

### `engine/vg/api/live.py` — 26 sites

| Line | Today | Code | `args` |
|---|---|---|---|
| 1117 | "No exit camera is configured, so no car can be matched to its exit…" | `gate.noExitCamera` | — |
| 1160 | "{cam} is offline, so plates are not being read there." | `gate.cameraOffline` | `camera` |
| 2287 | "{zone}, currently UTC{offset}" | `health.timezone` | `zone`, `offset` |
| 2299 | "{n} of {m} streams decoding" | `health.streamsDecoding` | `decoding`, `total` |
| 2345 | "Failed to start – {why}. Attendance is showing DEMO DATA." | `health.attendanceFailed` | `why` |
| 2353 | "Off – no camera has the 'attendance' feature…" | `health.attendanceNoCamera` | — |
| 2362 | "Running, but nobody is enrolled…" | `health.attendanceNobodyEnrolled` | — |
| 2370 | "{n} enrolled, {f} faces, running on {c} camera(s)" | `health.attendanceRunning` | `people`, `faces`, `cameras` |
| 2379 | "Failed to start – {why}. Counting and intrusion are showing DEMO DATA." | `health.personFailed` | `why` |
| 2387 | "Off – no camera asks for counting, intrusion or track" | `health.personNoCamera` | — |
| 2398 | "Loaded and shared with knife detection. No camera asks…" | `health.personSharedIdle` | — |
| 2405, 2428, 2452 | "{state} – {n} camera(s), {ms}ms last inference" | `health.modelRunning` | `cameras`, `ms` |
| 3525 | "No days recorded" | `history.noDaysRecorded` | — |
| 3558 | "Not seen on a day the cameras were recording" | `attendance.notSeen` | — |
| 3562 | "Arrived {n} minutes after the {cutoff} cut-off" | `attendance.late` | `minutes`, `cutoff` |
| 3584 | "Last {n} recorded days" | `history.lastNDays` | `days` |
| 3627 | "There is no camera {id}." | `camera.unknown` | `camera` |
| 3634 | "{cam} is not sending frames, so there is nothing to record." | `camera.noFrames` | `camera` |
| 3647 | "This camera is already recording." | `recording.alreadyRunning` | — |
| 3666 | "This camera is not recording." | `recording.notRunning` | — |
| 3178 | passes through `estimate.reason` | *(see `archive.py`)* | — |

Not notes — these lose their prose field and map from a key they already carry:

| Line | Today | Becomes |
|---|---|---|
| 1953 | `Metric(key="capacity", label="Safe capacity")` | `metric.capacity` |
| 1970 | `Metric(key="coverage", label="Not included")` | `metric.coverage` |
| 2711 | `Metric(key="sightings", label="Total sightings")` | `metric.sightings` |
| 3572 | `Metric(key="present", label="Days present")` | `metric.present` |
| 2016, 2019 | chart `title` "Today by hour" / "This week by day" | `chart.todayByHour`, `chart.weekByDay` |

### `engine/vg/api/app.py` — 7 sites

| Line | Today | Code | `args` |
|---|---|---|---|
| 86, 176 | "unknown window {v}; expected one of {…}" | `window.unknown` | `value`, `allowed` |
| 1482 | "The engine hit an unexpected error." | `error.unexpected` | — |
| 1606 | "Sign-in is unavailable. See System Health." | `auth.signInUnavailable` | — |
| 1615 | "Email or password is wrong." | `auth.badCredentials` | — |
| 1646 | "Sign-up is unavailable. See System Health." | `auth.signUpUnavailable` | — |
| 1654 | "Too many accounts created from here. Try again later." | `auth.signUpRateLimited` | — |
| — | "Sign-in is unavailable, so nothing can be served. See System Health." | `auth.storeUnavailable` | — |

The last one was observed at runtime, not found by the AST scan — it is built
somewhere the scan did not reach. **Find it before assuming the list is
complete**, and re-run the scan in `research.md` after the refactor to confirm
nothing is left.

### `engine/vg/auth/deps.py` — 2 sites

| Line | Today | Code |
|---|---|---|
| 195 | "Sign in to use this." | `auth.signInRequired` |
| 215 | "This needs an administrator account." | `auth.adminRequired` |

### `engine/vg/ingest/archive.py` — 2 sites

| Line | Today | Code | `args` |
|---|---|---|---|
| 1019 | "Nobody has measured how fast this machine reads recorded video yet…" | `sweep.noMeasurement` | — |
| 1038 | "That would take about {n} minutes, over the {limit} minute limit…" | `sweep.overLimit` | `minutes`, `limit` |

### `engine/vg/api/store.py` (`MockStore`) — 28 sites

Demo-only wordings get the `demo.` prefix so they are obviously not production
vocabulary, and so leaving them without Arabic is a deliberate, visible choice.

| Line | Today | Code |
|---|---|---|
| 259 | "Vehicle gate is not configured in this demo store." | `demo.gateNotConfigured` |
| 271 | "…so nothing is being read." | `demo.gateNotReading` |
| 782 | "Demo mode has no recorded video to sweep…" | `demo.noSweepData` |
| 912 | "Demo mode: every number on this page is invented." | `demo.everythingInvented` |
| 941, 947, 951 | pipeline stage details | `health.streamsDecoding`, `demo.personWeapons`, `demo.retention` |
| 1113 | "Absent, no guardian contact" | `attendance.absentNoGuardian` |
| 1130, 1135 | `AttentionItem` title + detail ×2 | `attention.*` |
| 1104 | "Last 30 school days" | `history.last30SchoolDays` |

Three groups in `MockStore` are **not** notes:

- **481, 490** `dismissal_reason` — a human's words. Stays `str`.
- **1162–1171** `AlertRule.title/detail`, `DeliveryTarget.title` — static
  settings copy that never came from a measurement. It moves into the console
  catalogue and off the wire entirely.
- **461, 505** `Box.label` (`"Person in zone"`, `"Knife-shaped object"`) — these
  are class names living in the field that also carries a person's **name**.
  They become `None` with the correct `Box.kind`, and the console labels from
  `kind`. See `data-model.md` §6.
- **580, 683, 1108** `Metric.label` — map from `key`, as above.

---

## Wire shape

```json
{
  "reason": { "code": "gate.noExitCamera", "args": {} }
}
```

```json
{
  "reason": { "code": "sweep.overLimit", "args": { "minutes": 47, "limit": 20 } }
}
```

An HTTP error keeps the `Problem` envelope; `detail` becomes a note:

```json
{ "detail": { "code": "auth.badCredentials", "args": {} } }
```

`web/src/services/http.ts` currently does
`detail = problem?.detail ?? problem?.error` and assigns it straight to
`message` when it is a string. It must now accept an object, render it through
`services/notes.ts`, and keep the string branch for anything that has not been
converted yet — so a half-migrated engine degrades to English rather than to
`[object Object]`.
