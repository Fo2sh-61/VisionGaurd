# Phase 1 — Data model: Arabic console

Three new types, one new column, one new config field. Everything else is an
existing field changing shape.

---

## 1. `Note` — an explanation the console can say in any language

**Engine** (`engine/vg/api/schemas.py`), a `Wire` subclass like any other:

| Field | Type | Meaning |
|---|---|---|
| `code` | `str` | a dotted token from the registry, e.g. `gate.noExitCamera` |
| `args` | `dict[str, str \| int \| float]` | the facts the sentence needs, default `{}` |

Rules:

- `code` MUST exist in `engine/vg/api/notes.py`. A test enforces it.
- `args` keys are referenced by the console wording as `{name}` placeholders.
- `args` values are **data, never prose** — a camera name, a count, a number of
  minutes. If an arg would be an English phrase, that phrase needs its own code.
- An unrecognised code renders as `t('note.unknown', { code })` and never as a
  blank (`P11-FR-007`).

**Console** (`web/src/types.ts` + `wire.ts`): the mirror type, camelCased by the
existing `Wire` convention — `{ code: string; args: Record<string, string | number> }`.

---

## 2. `MessageKey` — the console's vocabulary

`web/src/i18n/keys.ts` exports a union of every string the interface can say:

```
export type MessageKey =
  | 'nav.home' | 'nav.cameras' | …
  | 'gate.noExitCamera' | 'health.attendanceOff' | …
  | 'window.today' | 'window.last30' | …
  | 'audit.vehicle.passDelete' | …
```

Three sub-vocabularies live in it and must not be confused:

| Prefix family | Source of the key | Who decides the wording |
|---|---|---|
| interface copy (`nav.*`, `page.*`, `action.*`) | written by hand | the console |
| note codes (`gate.*`, `health.*`, `sweep.*`, …) | **must match the engine registry exactly** | the console |
| enum labels (`window.*`, `audit.*`, `status.*`, `boxKind.*`) | derived from a wire enum or token | the console |

The note-code family is the only one where the engine and the console share a
name. That shared name is the contract, and `contracts/notes.md` owns it.

**Catalogues**

| File | Type | Meaning |
|---|---|---|
| `en.ts` | `Record<MessageKey, string>` | complete — the compiler enforces it |
| `ar.ts` | `Partial<Record<MessageKey, string>>` | approved by a native speaker |
| `ar.draft.ts` | `Partial<Record<MessageKey, string>>` | drafted, development builds only |

Resolution order: `ar` → `ar.draft` (dev only) → `en`.

**Derived, not stored**: coverage counts (`approved`, `draft`, `missing`) are
computed from `Object.keys` at runtime and shown on Settings (`P11-FR-003`).

---

## 3. `Language`

`'en' | 'ar'`. Lives in three places, in this order of authority:

1. `app_user.language` — the account's choice, the authority when signed in
2. `localStorage['vg.lang']` — the pre-sign-in fallback, for the login page only
3. `navigator.language` — first-visit guess

Writing the account choice also writes the local copy, so the next sign-in page
appears in the right language before the account is known.

---

## 4. `app_user.language` — the new column

`engine/vg/auth/store.py`, `app_user` table.

| | |
|---|---|
| Type | `TEXT NOT NULL DEFAULT 'en'` |
| Added by | `PRAGMA table_info` guard + `ALTER TABLE … ADD COLUMN`, copying `engine/vg/events/vehicles.py` |
| Reaches the console via | `Account.language` on `S.Account` |
| Written by | `POST /auth/language` |

**It is a preference and nothing else.** `auth/deps.py` decides permissions by
path and must never read it. A language that could change what a caller may do
would be a second, hidden permission system.

---

## 5. `SiteInfo.digits` — the digit system

`engine/vg/api/schemas.py`, `class SiteInfo`.

| | |
|---|---|
| Type | `Literal['western', 'arabic']`, default `'western'` |
| Source | site configuration (`engine.yaml`) |
| Used for | the `Intl` locale extension: `-u-nu-latn` or `-u-nu-arab` |

Site-wide, not per user (`P11-FR-013`): it exists so the console can match the
paperwork the school already uses, which is a property of the school.

**Unverified at plan time** — `engine.yaml` has no site typography section and
the config plumbing was not read. See `context.md` §5.

---

## 6. Existing fields — what changes and what must not

The hard part of this feature is telling **prose the engine wrote** from **data
a person typed**. They are the same Python type today and only one of them may
be replaced by a code.

### Becomes `Note | None`

| Class | Field |
|---|---|
| `Recording` | `reason` |
| `RecordingResult` | `reason` |
| `Breach` | `clip_reason` |
| `WeaponDetection` | `clip_reason`, `end_reason` |
| `PipelineStage` | `detail` |
| `Capability` | `reason` |
| `AttendanceFlag` | `detail` |
| `PersonHistory` | `period_label` |
| `AttentionItem` | `title`, `detail` |
| `Problem` | `detail` |
| `LiveTracking` | `reason` |
| `LegJob` | `gap_reason` |
| `SweepEstimate` | `reason` |
| `FollowRecording` | `reason` |
| `FollowView` | `ended_reason` |
| `EnrolmentPhoto` | `note` |
| `EnrolmentSessionView` | `detail` |
| `GateSummary` | `reason` |
| `GateReaderNow` | `reason` |

### Field deleted — the console maps an existing key

| Class | Field removed | Mapped from |
|---|---|---|
| `Metric` | `label` | `key` |
| `AttendanceTrend` | `label` | `date`, formatted by the console |
| `AlertRule` | `title`, `detail` | static settings copy — moves into the catalogue entirely |
| `DeliveryTarget` | `title` | same |

### Stays `str` — this is data, not interface

Replacing any of these with a code would destroy something a person wrote.

| Class | Field | Why |
|---|---|---|
| `ZoneOverlay` | `label` | the zone's name, typed by an operator |
| `WeaponReview` | `reason` | the reviewer's own words |
| `WeaponDetection` | `dismissal_reason` | the same words, stored |
| `VehiclePass`, `RegisteredVehicle`, `VehicleRegistration`, `VehicleVisit` | `unit` | the owner's department — **not** `Metric.unit`, which is an enum and unrelated |
| `DirectoryPerson`, `StartEnrolmentRequest` | `detail` | the person's grade or department |
| `VehiclePass` | `plate_display` | what is painted on the car |
| `AuditEntry` | `subject`, `detail` | the plate, the name, the count |

### Mixed — needs care, not a rule

**`Box.label`** carries a *person's name* on recognition boxes and a *class
name* (`"Person in zone"`, `"Knife-shaped object"`) elsewhere. One field, two
meanings, and only one of them is translatable.

Resolution: `label` keeps the data meaning only — a name, or `None`. The class
wording comes from `Box.kind`, which already exists and already decides the box
colour. `MockStore`'s class-name labels become `None` with the right `kind`.

Finding this now is the point of the exercise: a field that means two things is
the kind of thing that turns into "every person reads as Mohamed Fouad".

**`CountBar.label`** is a chart bucket caption and carries `at: Instant | None`
beside it. Where `at` is present the console formats the caption itself and the
field is unused; where it is absent the label is the only thing there. Confirm
which buckets have no `at` before deleting the field — recorded in `context.md`.

### `AuditEntry.action` — already correct

The vocabulary is already dotted tokens: `vehicle.pass.delete`, `track.search`,
`weapon.confirmed`, `recording.start`, `path.sweep`. `P11-FR-018` needs only a
catalogue entry per token. Two call sites pass prose as `subject`
(`_log(actor, "vehicle.export", "vehicle passes", …)`) and should pass data or
nothing instead.

---

## 7. Window tokens

`engine/vg/api/app.py`.

| Today (the protocol value) | Becomes | Catalogue key |
|---|---|---|
| `"Today"` | `today` | `window.today` |
| `"Yesterday"` | `yesterday` | `window.yesterday` |
| `"Last 7 days"` | `last7` | `window.last7` |
| `"Last 30 days"` | `last30` | `window.last30` |
| `"Last 90 days"` | `last90` | `window.last90` |
| `"This school year"` | `schoolYear` | `window.schoolYear` |
| `"All"` | `all` | `window.all` |

`WINDOW_DAYS` keeps five, `WEAPON_WINDOWS` keeps seven — the split documented at
`app.py:56` is still correct and is not being merged.

A rejected token still returns 422, now with a `Note` carrying the offending
value and the accepted set in `args`.
