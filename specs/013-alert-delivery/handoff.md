# Handoff: 013 Alert Delivery — implementation paused, 11 Sep 2026 ~19:45

The implementing session ran out of context. Everything needed to finish is here
and in the files it points to. Read this first, then `context.md` and `tasks.md`.

## Read before touching anything

- **Branch `Fo2sh`. Nothing is committed.** Do not commit unless Mohamed asks: the
  same working tree also holds other sessions' uncommitted work that is **not
  013's** and must not be touched or committed:
  - `engine/vg/features/base.py`, `engine/tests/test_health_load.py`, and the
    System Health load / workers-stage hunks in `engine/vg/api/live.py`;
  - `specs/014-mobile-ui-parity/` (another spec-kit feature, in progress).
- **`.specify/feature.json` points at 014. Leave it.** Setting
  `SPECIFY_FEATURE_DIRECTORY` also rewrites it (common.ps1 persists it). Work from
  this folder by path.
- Follow the queue rule in `tasks.md` ("Working alongside other sessions"): check
  `git diff -- <file>` before editing; if another session has a file open, do other
  work first and come back.

## Where it stands

- `tasks.md`: **T001–T042 done** (marked `[X]`). Open: **T043** (every gate) and
  **T044** (the live walk, then Mohamed's real-phone half).
- The "Implementation notes" section at the end of `tasks.md` lists where the build
  departed from the plan (a new `AlertSettings.tsx` component, `_roster_name`,
  `camera_offline_minutes` on the wire, `template` on `AlertEvent`, and so on).

### Gates at hand-off

| Gate | Result |
|---|---|
| `python -m pyflakes engine/vg engine/tools engine/tests` | clean |
| `tsc -b --force` in `web/` | clean |
| `tsc -b --force` in `mobile/` | clean |
| `python tools/check_parity.py` | **1 of 26 wrong: `services/format.ts`** — pre-existing drift from commit `a830f1c` (4 Sep), owned by feature 014. Do not fix it; report it. |
| Full `pytest` | **not re-run since US2–US5 were built.** Last full run (after US1's engine half): 1709 passed, 6 skipped, 2 failed — `test_recording` forgotten-recording (the known load-flaky test; it failed alone 3/3 while another session ran a heavy process; it touches no 013 code) and `test_smoke_start[_start_alerts]` (fixed since: `_start_alerts` now calls `_reraise_if_strict`). |
| Targeted runs since | all green: the five `test_alerts*.py` files, plus the weapons, zones, vehicles, groups, notes, no-fixtures, api, config and authorisation suites. |

### Live check done

The real engine started on the recorded clip
(`VG_CAMERAS=cam-clip python engine/tools/serve.py --port 8000`), `/healthz`
answered, and `engine/data/visionguard.db` now holds the four alert tables with the
fresh-install defaults: every external channel off, In-app on, the attendance rule's
In-app NULL, zero deliveries. The engine was stopped afterwards.

**Not done**: the by-eye walk of the console (quickstart "Half two"). The dev
sign-in is not on this branch (it lives on `claude/dev-signin`), and nobody types
Mohamed's password, so that walk is his.

## In flight: the adversarial review

A read-only, six-angle review of the whole feature was launched with every finding
checked by skeptics told to refute it: sender-core, privacy-security,
contract-truth, console-phone, integration-lifecycle, tests-adequacy.

- Script: `C:\Users\Fo2sh\.claude\projects\E--VisionGuard\b1e64262-a88f-4cef-8360-3b4c6b6409bf\workflows\scripts\review-013-alert-delivery-wf_f1310dff-a64.js`
- Journal, one line per finished agent: `C:\Users\Fo2sh\.claude\projects\E--VisionGuard\b1e64262-a88f-4cef-8360-3b4c6b6409bf\subagents\workflows\wf_f1310dff-a64\journal.jsonl`
- If the old session is still open when it finishes, its result is appended below
  under **Review results**. If that section is still empty, read the journal; if the
  run never finished, run it again with `Workflow({scriptPath: "<script above>"})`
  (resume only works in the session that started it, so it runs fresh).
- Triage every surviving finding: fix the real ones, each with a regression test, and
  say plainly which ones you judged not worth fixing and why.

## Next steps, in order

1. The review results: triage, fix, targeted tests.
2. **T043**: plain `python -m pytest engine` (pytest.ini already adds `-q`, and the
   plain command prints the pass/skip count); pyflakes; `node
   node_modules/typescript/bin/tsc -b --force` in `web/` and in `mobile/`;
   `python tools/check_parity.py` and `--no-fixtures` (set `PYTHONIOENCODING=utf-8`
   or the output crashes on arrows); `git diff --stat` shows no whole-file rewrites.
   A failure you did not cause is reported, not fixed quietly.
3. **T044**: ask Mohamed for quickstart "Half two" by eye and "Half three" on his own
   phone with the six keys in `engine/.env`; the native-speaker review of the Arabic
   wording (then flip `catalogue.ARABIC_REVIEWED`); and the 2026–27 term dates in
   `engine/engine.yaml` (the configured term ended 20 Jun 2026, so the noon report is
   silent and Settings says so).
4. Mark T043/T044, then give the `/speckit-implement` completion report.

## Traps that cost time in this session

- **CRLF**: the Edit tool keeps CRLF (checked). Scripts must use
  `open(path, newline="")`; never `Path.write_text` on Windows.
- **Bash heredocs over ~8 KB fail to parse.** Write long scripts to the scratchpad
  with the Write tool, then run them.
- **Phone copies**: parity-held files (`types.ts`, `services/api.ts`,
  `services/wire.ts`, `app/useAttention.ts`, `i18n/*`) are copied byte for byte to
  `mobile/src/`. A page is copied only if the phone's file is still the untouched
  copy: `git show HEAD:web/src/pages/X.tsx | cmp - mobile/src/pages/X.tsx`.
  `web/src/components/AlertSettings.tsx` has a byte copy in `mobile/src/components/`.
- **`_camera_name` reads engine.yaml only.** Use `_roster_name` for anything shown to
  people; it reads the running roster.
- **`/settings` is admin-write** now; `/attention/{id}/ack` stays open to any
  signed-in account and takes the actor from the session.
- **Subagents: Sonnet only** (Mohamed's standing preference).

## Review results (11 Sep 2026, evening - the next session)

The review was re-run fresh (the first run's session ended before five of six angles
finished). Six findings survived the skeptics across both runs; all six are fixed, each
with a test, and a second, smaller review of those fixes found three gaps, also fixed.
What changed and what was left alone, with reasons: tasks.md, "After the review".
Mohamed decided three things on the way (11 Sep): a gate message waits until the reader
is done with the car (design correction 11); a plate a guard fixes by hand sends nothing;
recipients' numbers stay readable by any signed-in account.

**T043 is done** (results on the task line). **T044 is Mohamed's**: quickstart half two by
eye, half three on his own phone with the six keys in `engine/.env`, the native-speaker
review of the Arabic wording (then `catalogue.ARABIC_REVIEWED = True`), and the 2026-27
term dates in `engine/engine.yaml`. The gate change cannot be seen on the recorded clip -
`cam-clip` has no vehicles feature and no car - so it needs his gate camera and a car.

Found on the way, not 013's: `engine/vg/ingest/source.py` recurses to RecursionError when
a file camera's reads keep failing (seen at shutdown on the clip). Offered to Mohamed as
its own task.

Still nothing committed.
