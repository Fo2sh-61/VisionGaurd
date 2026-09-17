# Gaps: what the approved design shows that the phone does not

The closing report for P13-FR-059 / SC-009. It lists every part of the canvas
that was left out or changed, why, and what the phone shows instead. It is
started from research R15 and finalised during implementation.

## Before this feature

Checked 17 September 2026 at `34e2bef` plus the uncommitted tree: console and
phone `tsc` clean, parity 26 files identical, no fixtures, pyflakes clean,
pytest 1889 passed / 6 skipped. Nothing was failing.

## Design parts not built as drawn

| # | Design part | Why | What the phone shows instead |
|---|---|---|---|
| G1 | Per-tool live counts on Tools | Seven extra polls on a list screen | Blurb + capability state |
| G2 | "Features running on it" per camera tile | Only the admin-only `/sources` sends it | Name, area, count |
| G3 | "· retrying" on offline tiles | The roster does not say a retry is happening | "No signal · last picture HH:MM" |
| G4 | "Not set up on this camera" per overlay | No per-camera, per-feature flag for non-admins | "No boxes right now" |
| G5 | Blue "clothing match" rows in In view now | The Faces overlay sends no clothing matches | Face / Not identified rows |
| G6 | Per-person Follow button | To be checked (context §5) | — |
| G7 | Photos-on-file grid + Add photo | The engine keeps embeddings, not photographs | "Face on file · N photos" |
| G8 | Person's "Today" timeline of sightings | Engine sends last seen + day bars, not each sighting | Last seen + the console's history |
| G9 | "No recorded video from…" with recording-range chips | The footage job returns one error string | The console's failed-footage message |
| G10 | One search for camera or name on Catch now | The console's search filters cameras only | Camera search |
| G11 | Movements chips Today / All / Not registered / Blacklisted | The console filters by day, text and gate | The console's filters |
| G12 | "N things need attention" on More's System health row | No count without loading all of System health | Row without a count |
| G13 | Knife "N waiting" | The console counts entries in the window and "still in view" | The console's two counts |
| G14 | Zones badge "Watching" | The console says "Protected" | "Protected" / "Paused" |
| G15 | Tap-to-edit school profile | The console's edit saves nothing | Read-only rows |

## Console defects found (not changed; the console is out of scope)

To be finalised in T046.

## Only a real phone can confirm

To be finalised in T046.

## Appendix: 360-px audit

To be filled in by T042.
