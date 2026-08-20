# Phase 1 — Quickstart: proving Restricted Zones works

Two levels: the automated gates (seconds, no camera), then one walk in front of
the webcam to confirm by eye.

---

## 1. The four gates

```powershell
.\dev.ps1 test
```

Must be green, and the pytest count must be **higher** than 490 — this feature
adds tests, so a flat count means they did not run.

Individually:

```powershell
python -m pytest engine -q
python -m pyflakes engine/vg engine/tools engine/tests
cd web; npx tsc -b --force
```

---

## 2. The tests that matter, and what each proves

All in `engine/tests/test_zones_live.py`. None needs a camera, a model or a
server — the scene machine is fed fake frames with fake detections and a
controlled clock.

| Test | Proves |
|---|---|
| `test_zones_lists_every_configured_camera` | P4-FR-001 — the list is the roster, no fixtures |
| `test_no_invented_zone_names_from_live_store` | The P0-01 bug class cannot come back |
| `test_toggle_persists_across_restart` | P4-FR-003 — reopen the store, still on |
| `test_toggle_requires_admin` | P4-FR-004 — IT account gets 403 on PATCH, 200 on GET |
| `test_person_opens_a_scene_and_starts_recording` | P4-FR-005 |
| `test_flicker_under_one_second_does_not_split_the_scene` | **P4-FR-006, SC-003** — gap at 0.9 s → one scene |
| `test_one_full_second_of_nobody_closes_the_scene` | P4-FR-006 — gap at 1.1 s → closed |
| `test_scene_is_cut_at_the_two_minute_limit` | P4-FR-009 |
| `test_camera_not_restricted_never_records` | **SC-005** — and no detector call at all |
| `test_new_clip_replaces_the_previous_one_for_that_camera_only` | P4-FR-008 — camera B's clip survives camera A's new scene |
| `test_replaced_entry_stays_listed_with_a_reason` | P4-FR-008 — row kept, clip_state `replaced`, reason set |
| `test_scene_records_peak_people_not_last_count` | P4-FR-012 |
| `test_toggling_off_mid_scene_closes_and_saves` | Edge case |
| `test_recorder_failure_logs_the_scene_without_a_clip` | Rule 4 — no fake save |
| `test_clip_endpoint_404s_when_the_file_is_missing` | Rule 4 |
| `test_clip_endpoint_refuses_a_path_outside_the_clips_directory` | The file-read hole |
| `test_open_scene_is_closed_on_next_start` | Invariant 4 — nothing shows as recording forever |
| `test_capabilities_says_why_when_the_worker_is_not_running` | Rules 4, 7, 8 |
| `test_intrusion_cameras_have_no_zone_overlay` | P4-FR-002 — no orange rectangle |
| `test_restricted_zones_do_not_change_counting` | **Rule 9, P4-FR-011** |

---

## 3. Pipeline check on the recorded clip

Deterministic, no webcam, no device locked.

```powershell
.\dev.ps1 up -Clip
```

Then:

1. Sign in (`python engine/tools/create_user.py` first if you never have).
2. Open **Restricted zones**.
3. The camera list shows the clip camera — **not** "Server room" or any other
   invented name.
4. Switch it on. The badge reads Protected.
5. When a person walks through the clip, a log entry appears within 5 s
   (**SC-002**) and the entry shows a peak people count.
6. When they leave, the entry gets a duration and **Watch clip** becomes
   pressable — **without touching the page**. It polls; if you have to
   navigate away and back, the poll has broken (SC-007).
7. Press **Watch clip** — the scene plays (**SC-004**).
8. `.\dev.ps1 down`

---

## 4. Manual check — needs Mohamed's eyes

Only these need a real webcam, per `AGENTS.md`:

```powershell
.\dev.ps1 up -AllowSystemPython
```

- **Flicker** — walk in, stand still, walk out once. Confirm **one** entry and
  **one** clip, not three. This is the rule the automated test asserts with a
  fake clock; only a real walk proves the real detector's flicker is covered by
  one second.
- **Latency** — how long from stepping into view to the entry appearing.
  Should feel under 5 s.
- **The clip plays** — H.264 in the browser. The recorder asks the OS for an
  H.264 encoder first and falls back to mp4v only on a machine that has
  none; mp4v does not decode in a browser, so if the player shows no
  picture, look for the recorder's fallback warning in the engine log.
- **No orange rectangle** anywhere on the page.

---

## 5. What "done" looks like

- [ ] Four gates green, test count above 490
- [ ] Every checklist item in `checklists/requirements.md` still passes
- [ ] No fixture zone or breach reachable outside demo mode
- [ ] `STATUS.md` updated: Restricted zones moves from **Fake** to **Real**
- [ ] `docs/PLAN.md` P4 marked done, with what was and was not built
      (no schedules, three clips per camera)
- [ ] Committed with its tests in the same commit
