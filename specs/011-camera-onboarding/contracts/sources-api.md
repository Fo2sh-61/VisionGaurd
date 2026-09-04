# Contract: `/sources` — camera setup

**Every path here is already inside `ADMIN_PREFIXES` in `engine/vg/auth/deps.py`.** That is the
whole authorisation design: a new route under `/sources` is administrator-only the day it is
written, with nothing to remember and no decorator for anyone to forget. Do not add a decorator.

Wire types subclass `Wire`: snake_case in Python, camelCase on the wire, `extra="forbid"`.
`Fraction` and `Confidence` are validated 0..1. Nothing in this contract carries geometry.

Legend: **new** · **changed** · unmarked = unchanged.

---

## GET `/sources` → `list[CameraSource]`

**changed** — three fields added so the console can render and edit a camera without a second
round trip.

```
CameraSource
  id            str
  name          str
  type          SourceType          NVR | DVR | IP camera | RTSP
  ip            str                 REDACTED source string. Never the raw one
  channels      int
  status        SourceStatus        ok | down | auth
  area          str | None
  lastError     str | None
  features      list[str]           NEW  the seven names, as configured
  faces         bool                NEW  identity tier
  enabled       bool                NEW  configured but switched off
  gate          int | None          NEW
  direction     str | None          NEW  entry | exit, never both
  fps           float               NEW
  rotate        int                 NEW
  fromConfig    bool                NEW  seeded by engine.yaml rather than added here
```

`fromConfig` is what lets the console tell an operator what editing this camera means, which is
`P13-FR-020`. It is derived, not stored: a camera is `fromConfig` when it has no row in `camera`.

---

## POST `/sources` → `CameraSource` · 201

**changed** — the request gains the settings that `CameraConfig` already validates and the store
has never persisted.

```
AddCameraRequest
  name        str                 1..120
  source      str                 rtsp:// | webcam:N | file:path
  id          str | None
  kind        SourceType = RTSP
  area        str = "Unassigned"
  fps         float = 5.0         0 < fps <= 60
  features    list[str] = ["counting"]
  rotate      int = 0
  username    str | None          folded into `source`, then discarded
  password    str | None          folded into `source`, then discarded
  faces       bool = false        NEW
  gate        int | None          NEW
  direction   str | None          NEW
  neighbours  list[str] = []      NEW
```

- **422** with the reason when `CameraConfig.parse` refuses. Already the behaviour for a bad
  source; now also for an unknown feature name, and for the two half-configured gate states
  (`vehicles` without a gate; a gate without `vehicles`).
- **Audited before the write**, action `camera.add`, detail built from the redacted source.
- The response's `status` is honest immediately: a camera that has not connected yet is `down`,
  not `ok`. This is existing behaviour and must survive.

---

## POST `/sources/bulk` → `list[AddCameraOutcome]` · 200 **new**

Sixteen channels is sixteen `POST /sources` calls today, and the fourth failing says nothing about
the other twelve.

```
BulkAddRequest
  cameras   list[AddCameraRequest]     1..500

AddCameraOutcome
  index     int                        position in the submitted list
  ok        bool
  id        str | None
  source    str                        REDACTED
  error     str | None
```

- **Always 200.** A refused camera is payload. A partial failure is not a request failure.
- Every camera is attempted; the first failure does not abandon the rest (`P13-FR-024`).
- One audit entry per camera, each before its own write.
- No camera already running is disturbed (`P13-FR-025`).

---

## PATCH `/sources/{id}` → `EditCameraResult` · 200 **new**

```
EditCameraRequest        every field optional; absent means "leave alone"
  name        str | None
  source      str | None
  area        str | None
  fps         float | None
  rotate      int | None
  features    list[str] | None
  faces       bool | None
  gate        int | None
  direction   str | None
  neighbours  list[str] | None
  enabled     bool | None
  username    str | None
  password    str | None

EditCameraResult
  camera            CameraSource
  shadowsConfig     bool          this camera came from engine.yaml and now has a stored row
  restarted         bool          the stream was reopened (source/fps/rotate/enabled changed)
  featureNotes      list[FeatureNote]

FeatureNote
  feature   str
  running   bool
  reason    str | None            why not — from the subsystem's own startup error
```

- **422** when the merged config fails `CameraConfig.parse`.
- **404** when there is no such camera. **503** when the runtime roster is unavailable —
  "nothing is running" is not the same answer as "not found", which is what `SubsystemUnavailable`
  already exists to keep apart.
- **Audited before the write**, action `camera.edit`, detail naming the fields that changed —
  never their values when one of them is a credential.
- `restarted` is `false` for a features-only edit. Reopening an RTSP stream to add a tickbox is a
  visible stutter for nothing (`P13-FR-025`).
- `featureNotes` carries `P13-FR-016`: a feature chosen whose worker did not start is reported
  here, and the camera is still saved.

`POST /sources` returns the same `featureNotes` and `shadowsConfig` fields, for the same reasons.

---

## DELETE `/sources/{id}` · 204

**changed** — audited, and it now unwatches every feature.

- Soft delete. Recorded events survive (`P13-FR-022`).
- **Audited before the write**, action `camera.remove`.
- Every feature worker unwatches the camera. Any scene open on it is closed **by that camera's own
  thread**, with a reason — never from the request thread. See the design note in `research.md`;
  closing across threads is what once destroyed the recording of the scene that was running.

---

## POST `/sources/dvr` → `DvrConnectResult` **changed — this is the fixture**

`LiveStore` has never overridden `connect_dvr`, so the live engine answers from
`MockStore.connect_dvr`: sixteen channels, `ok`, `704x576`, whatever the recorder is and whether or
not it answered.

```
DvrConnectRequest
  host        str
  port        int = 554
  username    str
  password    str
  type        SourceType = DVR
  name        str | None
  area        str | None
  template    str                    NEW  REQUIRED. must contain {channel}
  channels    list[str]              NEW  REQUIRED. 1..64 channel ids to try
  budget      float = 20.0           NEW  seconds, total, for the whole probe

DvrConnectResult
  reachable   bool                   NEW  did anything at all answer
  reason      str | None             NEW  why not
  checked     int                    NEW  how many were actually tried
  status      SourceStatus
  channels    list[DvrChannel]
  sourceId    str | None             CHANGED  nullable — nothing is created by connecting

DvrChannel
  channel     str
  name        str
  enabled     bool = true
  source      str                    NEW  REDACTED url this channel would use
  checked     bool = true            NEW  false = the budget ran out before this one
  status      SourceStatus           NEW  ok | down | auth
  resolution  str | None             CHANGED  real, from the frame. None when none arrived
  latencyMs   float | None           NEW  real, measured
  error       str | None             NEW  the probe's own reason
```

Rules the implementation must hold:

1. **Every channel with `status: ok` was opened and returned a frame.** No exceptions
   (`P13-FR-002`).
2. `template` must contain `{channel}`; **422** if not. Credentials are folded in exactly as
   `add_camera` and `test_connection` already fold them.
3. Probes run several at a time under one **total** budget. A channel the budget never reached is
   `checked: false` — a different answer from `status: down`, and the console must render it
   differently.
4. Unreachable recorder → **200** with `reachable: false`, a reason, and `channels: []`
   (`P13-FR-004`). Never a 5xx, and never a channel list.
5. **Nothing is created.** Connecting is a probe. Cameras appear only through `POST /sources/bulk`.
6. **A test must assert `LiveStore.connect_dvr is not MockStore.connect_dvr`** — the same guard
   shape as the existing `LiveStore.ask is MockStore.ask` assertion in `test_ask.py`, which exists
   for exactly this bug class.

---

## POST `/sources/scan` → `ScanResult` **changed**

`LiveStore.scan()` returns `[]`. The console renders "0 devices found", so "we cannot search" and
"your network is empty" are the same sentence.

```
ScanResult
  available   bool
  reason      str | None
  devices     list[FoundDevice]
```

`available: false` + a reason is the honest answer while discovery is not built (`P13-FR-007`).
Still 200 — this is degradation, and degradation is payload.

---

## POST `/sources/test` → `TestConnectionResult`

Unchanged, and deliberately so. It already opens the stream, pulls a real frame, and returns a
failure as `ok: false` with a reason rather than an error status. **The channel probe is this
function in a loop** — do not write a second prober.

---

## GET `/sources/areas` → `list[str]`

Unchanged.

---

## Console contract — `web/src/services/api.ts`

The only place the console talks to the engine. Three existing functions are wrong in ways the
engine cannot fix:

- **`connectDvr` throws the channels away** — it returns `{ channels: result.channels.length }`,
  so even a truthful engine response would be discarded and `CameraSources.tsx` would go on
  generating `CH 1…N` / `Camera 1…N` itself. It must return the channels.
- **`scanNetwork` returns a bare array** and cannot express "unavailable".
- **No `editCamera`, no `addCameras`.**

And in `CameraSources.tsx`, four things must go because they are inventions, not bugs:

1. the `source.captureService` banner — a ticked device at `192.168.1.10` that does not exist;
2. `addFound()` — pushes a local row with a fabricated id and `status: 'ok'`, calling nothing;
3. `addDvr()` — pushes a local row with an address it makes up from a counter, calling nothing;
4. the eight-row `dvrChannels` initial state, and the `192.168.1.0/24` scan range text.

Two more are quieter and matter as much: the channel `name` input is uncontrolled
(`defaultValue`) and the area `<select>` has no `value` or `onChange`, so **what the operator types
against a channel is discarded** even before the fake save. Both become controlled.

Every new sentence goes through `i18n/keys.ts` + `en.ts` + `ar.draft.ts`, and every rendered string
through `format.ts`. The engine sends a state and the facts; the console builds the sentence.
