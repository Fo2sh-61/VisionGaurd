# Routing accuracy — SC-003

**Measured 30 Aug 2026** against `engine/tests/data/ask_questions.yaml`
(37 questions) with `python engine/tools/ask_corpus.py`.

**SC-003 is not met.** Best measured score is **91.9%** against a bar of 95%.

---

## The free tier is far smaller than published guides claim

The plan was written expecting 1,500 requests a day, from aggregator articles.
Google does not publish per-model free-tier numbers — the official rate-limits
page points at AI Studio instead — so the only authoritative figure is the one
the API itself returned:

```
429 - Quota exceeded for metric:
generativelanguage.googleapis.com/generate_content_free_tier_requests,
limit: 20, model: gemini-3.7-flash
```

**20 requests, not 1,500.** Still limited 35 seconds later, so it is a daily
cap rather than a per-minute one. One corpus run is 37 questions, so the
configured model cannot complete a single run on the free tier.

`gemini-3.5-flash-lite` has a materially larger allowance — it completed two
full 37-question runs on the same key — and is what every figure below used.

## Runs

| Run | Model | Overall | eg | en | franco | mixed | msa |
|---|---|---|---|---|---|---|---|
| 1 | `gemini-3.5-flash-lite` | **91.9%** (34/37) | 83.3% | 93.8% | 100% | 100% | 100% |
| 2 | `gemini-3.5-flash-lite`, sharpened prompt | 83.8% (31/37) | 75.0% | 87.5% | 100% | 100% | 75.0% |

Run 2 is **not** a like-for-like regression: three of its six failures were
dropped connections rather than wrong routes. Of the 34 questions that reached
the model it scored 31 — 91.2%, statistically the same as run 1. The tool now
retries a transient failure instead of scoring it as a wrong answer, so a third
run would not have that noise.

## What run 1 got wrong

| Question | Wanted | Got | Verdict |
|---|---|---|---|
| who is absent from Grade 8 today | `attendance` | `group_roster` | **Corpus was wrong.** `group_roster` returns who is in the group and who is present, so it answers the question. Now declared with `accept:`. |
| ليه سارة اتأخرت النهاردة؟ | *refuse* | `attendance` | **Real, and the worst kind.** "Why was Sara late" answered with the register is a true answer to a question nobody asked. Fixed by the prompt in run 2. |
| كام واحد | `headcount` + missing `place` | *refused* | Real. The model refused rather than asking which place. Fixed by the prompt in run 2. |

## What run 2 got wrong, excluding the network noise

| Question | Wanted | Got | Verdict |
|---|---|---|---|
| كام عربية دخلت من بوابة ١ النهاردة | `gate_totals` | `vehicle_passes` | Arguably both — counting passes at a gate answers it. A candidate for `accept:`. |
| في حد دخل المعمل الاسبوع ده؟ | `zone_breaches` | `attendance` | **Real miss.** "Did anyone enter the lab this week" read as a register question. |
| was Sara late | `attendance` | *refused* | The new refuse-judgements rule appears to over-trigger on a short question. |

## What this means

- **Egyptian dialect is the weak side**, at 75–83% against 88–94% for English.
  That is the language the guards actually type, so a blended figure would have
  hidden the thing that matters.
- **Franco-Arabic, mixed script and MSA all scored 100%** in run 1, which is
  the result I least expected and the one worth keeping.
- The prompt is the lever, and it is a two-sided one: the run-2 rules fixed the
  two failures they targeted and cost accuracy elsewhere. That is prompt work,
  and it wants a bigger corpus before it is worth doing — 37 questions means
  one question is 2.7 percentage points.

## What has not been done

- **No native speaker has read the corpus.** Until Mohamed corrects the Arabic,
  this measures the parser against my Arabic rather than the school's, and the
  Egyptian-dialect number is the least trustworthy figure here.
- `gemini-3.7-flash` is unmeasured — its 20-request free allowance cannot
  complete one run.
- Nothing has been measured on a paid tier.
