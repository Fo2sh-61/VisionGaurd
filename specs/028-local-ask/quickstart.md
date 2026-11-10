# Quickstart: proving Local Ask works

## Prerequisites

- `models/ask/model.onnx` (448 MiB) and `models/ask/tokenizer.json` (16 MiB),
  supplied by Mohamed. Both are ignored by git.
- `pip install -r engine/requirements.txt`, which now includes `onnxruntime`
  and `tokenizers`.
- `engine/data/ask/questions.yaml`: 200+ questions, each marked `set: tune` or
  `set: score`, corrected by Mohamed.

## 1. Fast checks (no model needed)

```powershell
python -m pytest engine -q
python -m pyflakes engine/vg engine/tools engine/tests
cd web; npx tsc -b --force; cd ..
cd mobile; npx tsc -b --force; cd ..
python tools/check_parity.py
```

**Expect**:
- The test count does not drop below the baseline in `context.md`.
- The new `test_ask_local.py` passes with the fake encoder.
- Parity passes.

## 2. Offline accuracy (SC-001, SC-002, SC-003)

```powershell
python engine/tools/ask_calibrate.py          # prints floor / margin / refuse_floor from the tuning part
python engine/tools/ask_corpus.py             # scores the scoring part only
```

**Expect**:
- At least 95% overall and at least 95% for `lang: eg`.
- Wrong-but-confident at or below 2%.
- Out-of-scope refused at least 90% of the time.
- The run writes `specs/028-local-ask/evidence/routing.md`, and System Health
  shows that figure and date.

Run it again with the network cable out. The output must be identical (SC-003).

## 3. On the Jetson (SC-004, SC-005, SC-006)

```bash
python engine/tools/measure_ask.py --questions 50 --load-cameras
```

**Expect**:
- p95 "understood as" time at or under 1 s.
- Ask's resident memory at or under 500 MB.
- Every camera's analysis rate within 5% of its idle rate while 10 questions
  run back to back.

If memory is over budget:

```bash
python engine/tools/ask_quantize.py
```

This makes the int8 copy on the board. It is kept only if the tuning part
routes identically. Then re-run the measurement.

## 4. Clips on the recorded clip (SC-007, SC-008)

```powershell
.\dev.ps1 up -Clip -AllowSystemPython -DevSignIn admin
```

1. Ask "وريني سارة دخلت امتى النهاردة". **Expect**: the attendance row, the
   understood line, and the clip starting by itself.
2. Ask "سارة دخلت امتى" with no video word. **Expect**: the "want me to fetch
   the clip?" chip. Pressing it plays the clip.
3. In System Health → audit, every clip that played has an `ask.clip` entry
   *earlier* than it.
4. Point `archive.playback_url` at a dead address. **Expect**: "the recorder
   is not answering", shown within 15 s, and tracking legs still run.
5. Ask about a moment 5 s ago. **Expect**: "not available yet".

## 5. Learning (SC-009)

1. As admin, correct 20 questions that are not in the test set.
2. Run `ask_corpus.py`. **Expect**: the score is no lower than before.
3. Remove all learned examples (`POST /ask/examples/reset`) and run it again.
   **Expect**: exactly the starting score.
4. As an operator, pick a "did you mean" button. **Expect**: it appears under
   *suggested*, and changes nothing until an admin approves it.

## 6. Live view and switched off

- "وريني كاميرا البوابة دلوقتي": the live view opens with no boxes and no
  names. An offline camera shows NO SIGNAL.
- With no camera set to `lost`, "فين الشنطة الحمرا" answers "switched off on
  this site", not "nothing found" and not "not recorded". Note that "سارة
  راحت فين" still answers with tracking off: `person_path` is built from face
  sightings and only *adds* appearance stops when tracking runs.
