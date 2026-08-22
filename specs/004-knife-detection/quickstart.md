# Phase 1 — Quickstart: proving Knife detection works

Two levels: the automated gates (seconds, no camera), then one knife in front
of the webcam to confirm by eye — and to record the clip the suite still
lacks.

---

## 1. The four gates

```powershell
.\dev.ps1 test
```

Must be green, and the pytest count must be **higher than 768** — this
feature adds tests, so a flat count means they did not run.

Individually:

```powershell
python -m pytest engine -q
python -m pyflakes engine/vg engine/tools engine/tests
cd web; npx tsc -b --force
```

---

## 2. The tests that matter, and what each proves

All in `engine/tests/test_weapons_live.py`. None needs a camera or a server;
the state machine is fed fake frames, fake people, fake knives and a clock the
test controls. Only the first needs the model file, and it skips without it.

| Test | Proves |
|---|---|
| `test_model_loads_and_finds_nothing_on_grey_and_noise` | D1 — the `.pt` decodes correctly in the pinned runtime (skips without `models/knifebest.pt`) |
| `test_knife_model_is_never_called_with_nobody_in_view` | **P6-FR-002** — the person gate, and the cost claim behind Q1 |
| `test_a_knife_outside_every_person_box_is_ignored` | P6-FR-002 — the static corner object from D2 |
| `test_one_sighting_opens_nothing` | **P6-FR-003** — no entry, no recorder call |
| `test_three_sightings_over_a_second_open_a_scene_and_start_recording` | P6-FR-003, P6-FR-004, SC-001 |
| `test_entry_time_is_the_first_sighting_not_the_third` | P6-FR-003 |
| `test_flicker_under_ten_seconds_is_one_scene` | **P6-FR-004, SC-002** — gap at 9.5 s → one entry |
| `test_ten_seconds_without_a_knife_closes_and_saves` | P6-FR-004 — gap at 10.5 s → closed `gone`, clip `saved` |
| `test_scene_is_cut_at_two_minutes_and_a_knife_still_there_reopens` | P6-FR-004 |
| `test_the_measured_false_hit_sequences_never_form_a_scene` | **SC-003** — replays the D2 runs (`[1,5,1,1,1]` outside the box, `[1,1]` inside) |
| `test_recorder_busy_logs_the_scene_without_a_video` | Edge — reason sentence, no fake save |
| `test_shutdown_closes_the_open_scene` | Edge |
| `test_open_scene_is_closed_on_next_start` | Edge — nothing shows as recording forever |
| `test_review_records_the_signed_in_user_not_the_body` | **P6-FR-007** — body `actor: "Mallory"` is ignored |
| `test_audit_entry_is_written_before_the_verdict` | P6-FR-007 — store made to fail after `_log`; the entry exists anyway |
| `test_a_second_review_is_refused_with_404` | P6-FR-007 |
| `test_an_it_support_account_can_review` | P6-FR-007 — `/weapons` stays operator-open |
| `test_dismissed_entries_stay_listed_and_there_is_no_delete_route` | **P6-FR-008** |
| `test_videos_older_than_retention_expire_but_rows_stay` | **P6-FR-009, SC-007** — file gone, row listed, reason set, mark before unlink |
| `test_windows_today_yesterday_and_all_use_site_local_days` | **P6-FR-010** |
| `test_unknown_window_is_422_naming_the_allowed_ones` | P6-FR-010 |
| `test_weapons_overlay_carries_no_name_even_when_a_face_is_matched` | **P6-FR-012, rules 1 and 3** |
| `test_capabilities_says_why_when_knife_detection_is_not_running` | P6-FR-011, P6-FR-015 |
| `test_knife_detection_does_not_change_counting` | **P6-FR-013, rule 9** |
| `test_clip_endpoint_404s_with_a_reason_and_refuses_paths_outside_the_folder` | P6-FR-006, rule 4 |
| `test_bare_live_store_returns_no_weapons` | No fixtures — extends `test_no_fixtures.py` |

---

## 3. Pipeline check on the recorded clip

Deterministic, no webcam, no device locked. The clip has **no knife**, so this
is SC-003 running live: a full loop of the clip must produce nothing.

```powershell
.\dev.ps1 up -Clip
```

Then:

1. Sign in (`python engine/tools/create_user.py` first if you never have).
2. Open **Knife detection**. The header reads **1 camera being checked** — not
   "Monitoring all N cameras", and never "No knife detected on campus".
3. The list says nothing has been seen in the chosen period. Leave it for one
   full loop of the clip (about 40 s).

   **Corrected 22 Aug 2026.** This step used to say the list must stay empty.
   It does not. The first run of this check raised **one** entry — a 12.5 s
   scene at 0.76 confidence — then stayed clean for three more loops. Expect
   roughly one false entry per four loops. What you are checking is that it
   is rare and that every entry is reviewable, not that it is zero. If you
   see one per loop, something has regressed.
4. Enlarge the clip camera. Any box drawn is red and reads "Knife NN%" —
   there must be none on this clip, and there must never be a name.
5. **System health** shows a **Knife detection** stage with the model version,
   `cuda`, 1 camera and a last-inference time around 15–25 ms.
6. Stop the engine and start it again: the page and the stage come back the
   same; nothing claims to be recording.
7. `.\dev.ps1 down`

---

## 4. Manual check — needs Mohamed's eyes, and a knife

```powershell
.\dev.ps1 up -AllowSystemPython
```

Hold a kitchen knife in front of the webcam, 1–3 m away, visibly.

- **Latency** — the entry appears within 5 s of the knife first showing.
- **One scene** — hide the knife for a few seconds and show it again. Still
  one entry. Put it away for a full ten seconds: the entry gets a duration
  and **Watch** appears on its own, without touching the page.
- **The video plays** — Watch plays inline; Open plays it in a new tab. If
  the player shows no picture, look for the recorder's mp4v fallback warning
  in the engine log (no H.264 encoder on this machine).
- **Review** — Confirm knife: the entry reads "Confirmed by *your name*" with
  the time. Reload: unchanged. Try a second verdict: refused. Mark the next
  one False alarm: it stays in the list.
- **Periods** — Today shows it; Yesterday does not; All does.
- **Nothing is sent** — no notification of any kind; that is the next spec.

Then record the clip the regression suite needs — the first footage with a
knife in it:

```powershell
python engine/tools/record.py --camera cam-laptop --seconds 40 --label knife
```

Press SPACE each time the knife comes into view. Record a second clip holding
a phone, a pen and a spoon instead (`--label knife-negative`) and press N for
each. Both go in `engine/data/footage/` and become the evidence the D2
thresholds are re-checked against.

---

## 5. What "done" looks like

- [ ] Four gates green, test count above 768
- [ ] Every item in `checklists/requirements.md` still passes
- [ ] No fixture detection reachable outside demo mode; "police notified" gone
- [ ] `models/README.md` headline updated — the weapons model is now a trained
      knife model; `MODELS.md` and `knifebest_pt.yaml` regenerated with
      `python engine/tools/audit_models.py`
- [ ] `STATUS.md`: Weapons moves from **Fake** to **Real**; lost items stays
- [ ] `docs/PLAN.md`: FR-06 and P6 updated with what was and was not built
      (no model manager, no alerts); §7 gains the knife model's measured cost
- [ ] The four owner answers confirmed by Mohamed, or the spec amended
- [ ] Committed with its tests in the same commit
