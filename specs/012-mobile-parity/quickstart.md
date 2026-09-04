# Quickstart — running and proving the phone app

## Prerequisites

- The engine runs and has at least one account. If nobody has been created yet,
  nothing can sign in on either app:

```bash
python engine/tools/create_user.py
```

- There is still no `.venv` (DEV_PLAN 1.4), so any `dev.ps1` command that starts
  the engine needs `-AllowSystemPython`, or use `.\launch.ps1`, which detects the
  missing venv and passes the flag itself.

## Run it

```powershell
.\dev.ps1 up -Clip -Mobile -AllowSystemPython
```

Engine on 8000, console on 5173, phone on **5174**. `-Clip` uses the recorded
clip, so the picture is identical every run and has 21 labelled ground-truth
marks. Debug against it, not the webcam.

Open `http://localhost:5174` and set the browser to a 375 px viewport, or open it
on a real phone using the machine's LAN address.

`.\dev.ps1 down` frees 8000, 5173 and 5174.

## The automated gates

```powershell
.\dev.ps1 test
```

Runs the four existing gates plus the two new ones. Individually:

```bash
python -m pytest engine
```

```bash
python -m pyflakes engine/vg engine/tools engine/tests
```

```powershell
cd web; node node_modules/typescript/bin/tsc -b --force
```

```powershell
cd mobile; npm ci; node node_modules/typescript/bin/tsc -b --force
```

```bash
python tools/check_parity.py
```

```bash
python tools/check_parity.py --no-fixtures
```

**Expected**: engine tests green with no drop in count, both typechecks clean,
parity silent, no fixtures found.

`tsc -b --force`, never `--noEmit` — project references make `--noEmit` a silent
no-op that exits 0 with real errors in the source.

## Proving it works — by hand

Automated gates prove the code compiles and the copy is honest. They cannot prove
a screen is usable. These are the checks that need eyes, in the order worth doing
them.

### 1. Nothing is invented — do this one first

Stop the engine. Open every screen on the phone.

**Expect**: every screen says the system cannot be reached, with a reason. No
figure anywhere. No camera tile holding an old picture.

This is the check that the old fixture app would have failed on every screen
while looking perfectly healthy. (SC-002, P13-FR-001, P13-FR-010)

### 2. The same numbers on both

Engine running. Put the console and the phone side by side on the same account.
Walk the tools: attendance, counting, weapons, vehicles, lost items, system
health.

**Expect**: the same figures, the same rows, the same wording. Any difference is
a defect in the copy, not a phone design choice. (P13-FR-017, SC-007)

### 3. A guard sees a guard's console

Sign in as a guard. Then type `/users` in the address bar.

**Expect**: administrator actions are absent from the screens, and the typed URL
is refused **by the engine** with a plain message — not by the phone silently
redirecting. (P13-FR-005, SC-004)

### 4. Acting from the phone

As a guard, open a waiting weapon entry, play the clip, press **False alarm**.

**Expect**: recorded against that account, visible on the console within a
refresh, still present in history, and timed under 30 seconds from unlocking.
(SC-003, P13-FR-004, P13-FR-006)

### 5. Live pictures actually arrive

Open any camera tile.

**Expect**: a moving picture, not a black rectangle. A black rectangle with the
rest of the page working means the proxy is missing from
`mobile/vite.config.ts` — see `research.md` §5. Cover the camera or stop the
clip: the tile must say **NO SIGNAL**, not freeze. (P13-FR-008, spec scenario 4)

### 6. Overlays name only what they should

On a page that must not identify anybody, confirm no green name box appears.
Green names a person, blue says only "same body", amber says unidentified.
(P13-FR-008, P13-FR-009)

### 7. Arabic

Switch to Arabic in Account.

**Expect**: every screen mirrors, including the bottom tab bar. Names, plates and
camera identifiers stay as they are. No English left behind. Then sign out and
sign in as a different account — the language must follow the **account**, not
the browser. (P13-FR-012, SC-006)

### 8. One hand, 375 px

Every screen, both themes.

**Expect**: no sideways scrolling anywhere. Every tap target reachable with a
thumb. Where a console table had six columns, the row shows a headline and a
summary line, and the rest opens on tap — with nothing lost. (P13-FR-016, SC-005)

### 9. Nothing missing

With `navigation.ts` open, walk all 16 destinations from the five tabs.

**Expect**: all 16 reachable, and the Tools tab lists **ten** tools. The fixture
app listed six and silently had no vehicle gate at all. (P13-FR-003, SC-001)

### 10. A failed action says so

Turn off Wi-Fi mid-action — a weapon review, a settings change.

**Expect**: it says it did not go through and offers to retry. It must never draw
a save it was not told about. (P13-FR-011, spec scenario 8)

## What still cannot be proved here

Camera latency on a real phone over school Wi-Fi, whether the Arabic reads
naturally to a native speaker, and whether enrolment photos taken on a phone
camera score as well as a laptop's. All three need Mohamed and a real device.
The Arabic wording is the same unproofread draft as the console's and stays
dev-only.
