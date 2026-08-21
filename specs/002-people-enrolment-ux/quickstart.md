# Phase 1 — Quickstart: proving the People & enrolment work

Two levels: the automated gates (seconds, no camera), then a short session in
front of the webcam — this feature is UX, so the by-eye half matters more than
usual.

---

## 1. The four gates

```powershell
.\dev.ps1 test
```

Must be green, and the pytest count must be **higher** than 560 — this feature
adds `engine/tests/test_people_page.py`; a flat count means it did not run.

Individually:

```powershell
python -m pytest engine -q
python -m pyflakes engine/vg engine/tools engine/tests
cd web; npx tsc -b --force
```

---

## 2. The tests that matter, and what each proves

All in `engine/tests/test_people_page.py`. None needs a camera or a model —
the preview is fed a fake frame with a fake detector, removal runs on a
throwaway gallery.

| Test | Proves |
|---|---|
| `test_preview_returns_faces_as_fractions_with_five_points` | PPL-FR-002, rule 6 |
| `test_preview_carries_no_name_or_identity` | an enrolment preview never claims to know who it sees |
| `test_preview_empty_frame_is_no_faces_not_an_error` | edge case: nobody there is information |
| `test_preview_offline_camera_says_offline` | rule 4 — never an empty overlay pretending to have looked |
| `test_removal_requires_admin` | PPL-FR-005 — IT gets 403 on DELETE, 200 on GET |
| `test_removal_deletes_person_and_embeddings` | the cascade actually fires |
| `test_removed_person_is_never_matched_again` | PPL-FR-006 — gallery declines from the same index the worker reads |
| `test_removal_writes_audit_before_returning` | who did it, recorded |
| `test_removing_unknown_person_404s` | honest refusal |
| `test_directory_carries_photos_enrolled_and_last_seen` | PPL-FR-008/010 |
| `test_never_sighted_person_has_null_last_seen` | "Not seen yet" is null on the wire, words on the screen |
| `test_people_get_stays_open_to_non_admins` | pins the read half of the auth rule |

---

## 3. By-eye session — needs Mohamed

```powershell
.\dev.ps1 up
```

Sign in as an admin, then:

**Enrolment (SC-001, SC-002, SC-006)**
1. People → *Enrol a face* → fill a test name → *Start enrolment*.
2. The camera view **moves**. Step in front of it: within ~2 s a face outline
   and five feature points appear and follow you.
3. Step out: the overlay disappears and the page says nobody is detected.
   Bring a second person in: it asks for one at a time.
4. Capture three photos at different angles; watch the guidance change and
   the Save gate open. Save.
5. Press *← People* — it returns without confirmation (nothing staged).
   Start another enrolment, add one photo, press *← People*: one
   confirmation, then back, nothing half-saved (check the directory).

**People page (SC-003, SC-004)**
6. Read a full row aloud: every element should explain itself — type,
   "Recognised from 3 photos", enrolled date, "Last seen Main entrance ·
   07:42" or "Not seen yet", today's attendance in words. No "—" anywhere.
7. Click the row (not a button) — the history page opens. Try it on a staff
   member too.

**Removal (SC-005)**
8. Stand in front of a camera until your test person's name is drawn. Press
   *Remove* on their row — the confirmation states what it means. Confirm.
9. The row is gone; within ~5 s the overlay stops naming you (the box goes
   blue/unidentified). Settings → audit shows who removed whom.
10. Sign in as a non-admin (IT): the Remove control is absent, and
    `DELETE /people/...` by hand gets 403.

---

## 4. What "done" looks like

- [ ] Four gates green, pytest count above 560
- [ ] Every checklist item in `checklists/requirements.md` still passes
- [ ] The by-eye session above, confirmed by Mohamed
- [ ] `STATUS.md` People/enrolment line updated
- [ ] Committed with its tests in the same commit
