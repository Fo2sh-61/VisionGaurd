# Claims on the website, checked (27 Sep 2026)

Every product claim on the page was checked against `STATUS.md` and the code by one
agent per section, then challenged by a second agent that tried to overturn each
verdict and each rewrite. Of 34 claims, 15 were true, 11 overclaimed and 8 were untrue.
Mohamed approved all the rewrites below. The illustrations (camera wall, phones, activity
log) were not checked, except the two labels that picture a feature (last two rows of
the first table).

## Changed

| Where | Was | Now | Why |
|---|---|---|---|
| Hero | With the clip attached. | With the clip when there is one. | Arrivals and headcounts have no clip (`events/sightings.py` has no video column) |
| How it works intro | …and keeps the proof. | …and keeps a record. | Only zone and knife alerts keep video |
| Step 1 | Any building, any layout. | Add each one by its address. | No network discovery; ONVIF out of scope |
| Step 3 | Arrivals, alerts and sightings are kept with the video that proves them. | Arrivals and sightings are logged. Zone and knife alerts keep the video. | Sightings have no video |
| Step 4 | in English, Arabic, Franco or a mix | ask in English, Arabic, Franco or a mix | Asking in Arabic works; the Arabic screens are a dev-only draft |
| Stat 208 | cameras on a single site | cameras planned for our first site | The 208-camera plan waits on target hardware; not measured |
| Stat 0 | guesses — every answer shows its footage | made-up figures — every answer is real data | Many answers have no clip (`ask/menu.py`, headcounts) |
| Tools heading | Ask in any language. It opens the right tool. | Ask in your own words. It says what it understood. | Routing measured at 91.9% (SC-003 not met); every answer has an "understood as" line |
| People counting | How many, anywhere / per floor, hall or lobby | How many, right now / for each area with a camera | Real at one camera today |
| Knife detection | Every detection is checked by a person before anyone is alerted. | Every alert says unconfirmed until a person reviews it. | The alert goes out when the entry opens, marked "not yet confirmed by a person" |
| Lost bag | Describe the item and search the cameras you choose… | Pick a colour and see it outlined live on the cameras you choose. | No search and no job; a colour pick only |
| Track a person | with the next likely camera highlighted | with evidence at every stop | No next-camera hint in the product |
| Hero label (illustration) | Next camera: Library east | Last seen: Library east | Pictured the missing next-camera hint |
| Hero tile label (illustration) | awaiting review (amber) | not identified (amber) | Matches the legend |
| Colour legend | Amber — waiting for human review | Amber — not yet identified | AGENTS.md rule 1: amber = unidentified |
| Phone tile | Arabic & English — Full right-to-left layout | Ask in Arabic — Arabic screens in review | Arabic screens are an unproofread draft, dev-only |
| Trust intro | Every action is recorded, so you always know who looked at what, and when. | Searches and changes are logged, with who and when. | Not every action is recorded |
| Trust card | Full audit trail — Every search is recorded, so nothing happens unseen. | Audit trail — Every search is logged before results show. | True today (rule 11), but the audit lives in memory and is lost on restart |
| Trust card | Your retention rules — Footage is deleted on the schedule you choose. | Automatic retention — Footage is deleted after a set number of days. | One setting, `clip_retention_days` (30), read at startup |
| Trust card | Right to be forgotten — Remove a person and every trace goes with them. | Remove anyone — Their face data goes; recognition stops at once. | Past sightings and audit entries are kept until P3 erasure |
| Footer and page description | Ask your cameras anything… and get the answer with the footage. | Ask your cameras a question… and get the answer, with footage when there is some. | 14 kinds of question; some answers have no clip |

## Checked and true

"Type the way you talk" (English, Arabic, Franco, mixed); step 2 (every feed analysed
around the clock); 3 languages; 7 tools, one search box; Attendance; Restricted zones;
"It tells you what it knows"; the live, offline and demo cards; "The whole console, in
your pocket"; Light & dark; Email alerts; Needs your attention; Role-based access.

## Open with Mohamed

- **People counting accuracy**: checked 27 Sep 2026. It still over-counts: one person
  reads 1–7 (2.5 on average) on the recorded clip, and an empty room reads 1–5 on three
  frames in four. The card now reads "Live headcounts for each area with a camera"; whether
  it stays on the site while the count is this far off is Mohamed's call.
- **Audit trail**: Mohamed asked for it to survive restarts, with a way to remove chosen
  entries. Once built, the Trust card can say more.

## Reverted to the design's words, 27 Sep 2026 (spec 019, Mohamed's choice)

The same day, Mohamed redesigned the website and chose, when asked, to use his design's
words exactly. His new designs (`design/Visionguard website full design/`, Website v3 and
Mobile, English and Arabic) carry the "Was" wording of the Changed table above. The
rebuilt home page (`website/index.html`, `website/ar/index.html`), in both languages,
therefore says again:

- "With the clip attached."
- "…and keeps the proof."
- "Any building, any layout."
- "Arrivals, alerts and sightings are kept with the video that proves them."
- "208 — cameras on a single site"
- "0 — guesses — every answer shows its footage"
- "How many, anywhere" / "Live headcounts per floor, hall or lobby"
- "Every detection is checked by a person before anyone is alerted."
- "Describe the item and search the cameras you choose…"
- "…with the next likely camera highlighted"
- "Next camera" on the hero card
- "Amber — waiting for human review"
- "Arabic & English — Full right-to-left layout"
- "Every action is recorded, so you always know who looked at what, and when."
- "Full audit trail — Every search is recorded, so nothing happens unseen."
- "Your retention rules — Footage is deleted on the schedule you choose."
- "Right to be forgotten — Remove a person and every trace goes with them."
- the footer's "Ask your cameras anything… and get the answer with the footage."

The Tools heading "Ask in any language. It opens the right tool." is gone: the new design
says "Our Services". The hero also gains a card the check never saw, "Face match ·
verified". The evidence in the Changed table still holds. None of these sentences is
backed by the product today; they are on the page by decision, not by check.

About us, Security and Help centre keep their checked words, and their Arabic
translations keep the same facts.

## Checked wording back on the home page, 28 Sep 2026 (Mohamed's request)

A council review of VisionGuard as a startup named these sentences as the first thing to
fix, and Mohamed asked for it. The converter now puts the "Now" wording of the Changed
table back over the design's words, on PC and phone, in English and Arabic (site edit E18
in `tools/build_website.mjs`). Two differences from the table:

- The 208 figure did not become "cameras planned for our first site", because nothing is
  signed yet. At Mohamed's choice it counts up to 500+ as it scrolls into view, over
  "cameras — the scale we're building for": a goal, since nothing that size has run (E19).
  The console pictures' "All 208 cameras up" and "across 208 cameras" lost the number.
- The Arabic wording is Claude's draft and waits for Mohamed's read
  (`specs/019-website-v3/arabic-review.md`, last section).

Still on the page: the hero card "Face match · verified", which was never checked.
