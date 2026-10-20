# VisionGuard — Status

**Updated:** 24 Aug 2026 · **Commit:** `e9ba8dd` · Plan: `docs/PLAN.md` · Rules: `.specify/memory/constitution.md`

## Feature state

| Feature | State |
|---|---|
| Camera ingest, stream, snapshot | **Real** — reconnect, NO SIGNAL, stale flagging all work. **Console grid tiles sped up (11 Sep 2026)**: 15 pictures a second with 1–4 tiles on screen, 5 with 5–12, 2 with more (were 5 / 2 / 0.67). Two brakes were in the way: the tile's own timer, and the camera, which prepared new pictures only at its analytics rate (5 a second or less) unless somebody had it open. A tile now tells the engine its rate, and the camera turns frames into pictures that fast for two seconds after each request, capped at 15 (it decodes every frame either way — see Workload placement below); each tile also gets a picture sized to it instead of 1280 px. On a 1080p test video on the dev laptop, one tile at 15 a second cost about the same as one at 5 did before (4.2% against 4.1% of the processor). The AI's rates are unchanged. Tile overlays (knives, plates) re-fetch at the old rates. **Only tiles on screen move (28 Sep 2026), in both apps**: a tile scrolled away, covered by an open camera, or in a background tab (or on a phone with its screen off) asks for nothing, and one never scrolled to never asks at all; the tiles on screen share 120 pictures a second, at most 15 each and never under 2 — up to 8 run at 15, 12 at 10, 24 at 5. The phone's Home camera had been left at 1 a second and now runs at 15. A live stream that leaves the screen is closed and opened again when it comes back; the headcount and "In view now" list under the phone's camera keep updating once a second while you scroll past the picture to read them. Tile headcounts stop while the tab is in the background **Two bugs found while measuring that, both fixed 12 Sep 2026.** Closing a camera's enlarged view did not stop its live stream: a browser keeps loading an image after its element leaves the page, and an MJPEG response never ends, so the connection stayed open until the whole page was left — and the engine, which counts an open stream as somebody watching, kept that camera reading and converting every frame for nobody (822 a second on the clip, measured, with the view closed; the Track page's big view and enrolment's live view are the same element, so they left a stream behind too). The console's stream picture now removes its own address when it stops showing it, which closes the connection and, unlike an empty address, raises no error the console would read as a failed camera. The phone app had it too, until spec 015 brought its camera frame level with the console's (17 Sep 2026). And a recorded-clip camera played about thirty times too fast — 495 frames a second off the 15 fps walk-through clip — because a file, unlike a camera, hands over frames as fast as they are asked for; it is now held to the rate it was recorded at, so anything timed against `-Clip` is timed against real time |
| Camera setup | **Real** (1 Sep 2026) — recorders are probed channel by channel and report what actually answered; everything added is saved; all seven features assignable per camera with their settings, taking effect without a restart; cameras editable; every change audited. **Network discovery is not built** and says so. See the section below. **The analytics rate became a real setting on 2 Sep 2026.** Until then every worker held one rate — `min(fps)` across its cameras, fixed at construction — with two consequences nobody could see: turning one camera down to 2/sec quietly turned every other camera on that worker down with it, and editing the rate in the console changed the *decode* rate only, so the models carried on at the old rate until somebody restarted the engine. The rate is now per camera, takes effect on the next frame, and sits on the add form beside the features it multiplies rather than being reachable only by adding a camera and reopening it. The form also says what the ticked features actually need — 2/sec for counting, intrusion and attendance, 5 for track, weapons and vehicles, where a moment is the answer — as a recommendation with a one-click apply, never a value written into the field behind the operator. **And there is now a floor**: `weapons` below 3/sec is refused at parse time, because knife detection opens an entry on three sightings inside one second, so at 2/sec the third sighting can never arrive — the camera would watch for knives it is incapable of reporting while every screen said the feature was running |
| Attendance | **Real** — register, late cutoff, CSV export. Owner considers it done |
| Enrolment Studio | **Real** — `/people/enrol`, quality scoring, 5-photo floor (nobody is enrolled without them). Admin-only (P2). Live moving view with the detected face outlined and its five feature points tracking it, plain-language guidance, and a way back at every step |
| People page | **Real** — every column explains itself: recognition state with photo count, enrolled date, last seen (camera and time) or "Not seen yet", today's attendance. Any row opens that person's history. Administrators can remove somebody: face data and directory entry go and they stop being recognised without a restart, audited first. Their past sightings are kept, unreachable from any page, until P3's erasure |
| Live overlays | **Real** — each feature draws its own (faces / bodies / appearance IDs) |
| Tracking engine | **Real** — ByteTrack + appearance IDs, stable across frames and cameras. Shares one detection pass with counting (P1-01) |
| People counting | **Real for "Main entrance"** only (the laptop webcam). Over-counts — reads 4–6 for one person. **Measured again 27 Sep 2026**, twice and independently, with the real detector at today's settings on the recorded walk-through clip: one person reads 1–7 (2.5 on average, exactly 1 on only a fifth of frames), and the empty-room clip shows 1–5 "people" on about three frames in four. The cause is unchanged since 18 Aug: the size filter (`min_area`) is written but never passed, and the person threshold (conf 0.35) was never calibrated — PLAN P5, not started. Other areas are demo and labelled |
| System health | **Real** — honest per-subsystem, including startup failure reasons. **Adds a capacity projection (2 Sep 2026)**: two bars, graphics card against 1,000 ms a second and processor against cores × 1,000, never one combined number — SFace has no CUDA path, so attendance genuinely does not compete with counting for the same milliseconds. Each row is one worker's rate × what one frame last cost it *here*, and is labelled **measured here** or **estimate** — a worker that has not yet analysed a frame falls back to a figure carried in from an earlier run and says so. A worker that did not report which processor it uses is listed and left out of both totals rather than guessed into one; bag search is shown as demand-driven and contributes nothing, because its cost while somebody is watching is fixed by nothing. It is a **projection of what the configuration asks for**, not a reading of the machine — `behind` on the worker rows is still what says the engine has actually fallen over. **Also fixed 2 Sep**: four stages read `worker.stats` unguarded, so a worker whose counters raised took the whole page down with a 500 — the page an operator opens to find out what is broken, refusing to answer because something was. **The first real look at the card, 3 Sep, found it wrong three ways, all fixed the same day.** (1) Counting, intrusion, track and knives read one shared person pass, but each worker's timer included the time it spent *waiting* for another worker to finish that pass — so three rows of 13 ms for one 13 ms model. Time spent inside `SharedDetection.raw_boxes` is now charged to the calling thread and subtracted from that worker's own figure (`Result.shared_ms`), and the pass is costed **once**, on its own row, from `last_pass_ms` timed around the model call alone, at the fastest rate any reader runs each camera. (2) Tracking's own work — ByteTrack and the appearance matcher, NumPy, no GPU path — was charged to the **graphics card** because its pool was taken from its detector; the bar read 100% over a card `nvidia-smi` had at 18%. Tracking and zones now charge the processor. (3) Nothing on the page could contradict the bar: `gpu_percent` was hardcoded `None`. It is now **measured** from the driver (NVML, whole device, every program) and shown under the bar as "measured now". **Separately**: two cameras disabled on purpose read as "1 of 3 online", the ingest stage went amber, the summary said two cameras were not being analysed and the top bar repeated it on every page — `registry.total` counts disabled cameras for the setup list, and health used the same number as "how many should be up". Off is not down: totals now count switched-on cameras, and the page says "2 switched off on purpose" instead. **Then, the same day, the owner looked again: the bar was still red at 100% with "22% busy" written under it — and the rule that came out of it is that a bar is a claim about *now*, and only a measurement gets to make it.** The bars are now READINGS: the graphics driver's own utilisation figure (NVML, whole card, every program, plus memory in use) and the OS's for the processor (whole machine), refreshed every 3 seconds — the page used to load once and sit there. Under each bar, two figures kept apart and labelled: how much of it is this engine, **measured** — every worker keeps a 5-second window of milliseconds actually spent and frames actually analysed (`busy_ms_per_second`, `analysed_per_second`), the shared pass keeps the same window (`SharedDetection.load()`) — and what the configuration **asks for**, which is the projection that lets somebody see the wall coming. Per-worker rows show both. **Also found**: the engine's processor share had read 0.0 since the day it was added — psutil reports the change since the last call on the same object, and a fresh `Process()` was built on every poll, so every call was the first call. Held once and primed once now, with the very first poll returning None rather than psutil's baseline 0.0, and both processor figures taken from the one call so neither can be honest while the other reads idle |
| Track a person | **Real** — live: click a body and it is followed across cameras, named only after a sustained face, recorded one file per camera with the stop reason. Past: stops answer instantly from the anchor table, each with its evidence, and play back as 30s chunks off the footage/DVR archive. Sweeps refuse over a measured budget |
| Restricted zones | **Real** — any camera can be marked restricted; its whole frame is the zone. Scenes are logged and recorded, last three clips kept per camera, log refreshes itself. No schedules. **Three rules changed on 12 Sep 2026, after one walk past the laptop camera sent 32 emails.** The person detector loses a standing person for a second or two at a time, and at the old one-second gap each dropout ended the entry and reopened it: one continuous fifty-second visit was logged as 16 entries, sent 16 alerts, and the three-clips-per-camera cap then deleted 13 of the 16 clips it had just recorded. Now: a person must still be there **2 seconds** after the first sighting before anything is written (so a coat on a chair costs nothing, and the clip starts 2 s in — the entry still says when they arrived); the gap is **5 seconds**, so a blink no longer splits a visit; and a camera must be **empty for a minute** before somebody on it is a new incident — entries before that are continuations, still logged and recorded, but sending no second email. Same last rule for knives |
| Knife detection | **Real** (P6) — the owner's trained knife model runs on every enabled camera, but only on frames with a person in them and only for knives held by one. Three sightings over a second open one entry with one video; two seconds without a knife closes it and ends the video (owner set this, down from ten, after testing with a real knife — the cost is that a blink longer than two seconds splits one incident into two entries). Every entry waits for a person to press Confirm or False alarm, recorded against the signed-in account and audited before the write. Videos are kept 30 days, entries for ever. **Alerts go out (P9, spec 013)**: an entry opening sends one message per recipient marked "awaiting review — not yet confirmed by a person", and the verdict sends one more to exactly the same people, naming who decided. A knife held past two minutes is cut into two entries but is still one message, and so is one the detector loses for more than two seconds: from 12 Sep 2026 a camera must be clear of knives for a full minute before the next one is a new incident. Nothing locks, calls or acts on its own. **False-alarm rate is not zero**: a live loop of the recorded clip raised one 12.5 s entry at 0.76 on footage with no knife (roughly one per four loops). Accuracy on a real knife is unmeasured |
| Falls | **Built, not yet seen on a real camera** (15 Oct 2026) — the owner's learned temporal model (`models/falling/`, the LSTM his own `train.compare` installed, `lstm_cctv`) runs over body pose from `yolov8s-pose` on the cameras switched on in **System health → Fall checking**. The engine carries his code line for line and a test runs his untouched files beside it and requires the same falls on the same frames (`test_falls_model.py`). Somebody who goes down opens an entry and a video at once; **down 10 seconds and still down** puts them on the Falls page, on Home and in the bell; getting up (1 s upright) or leaving the camera (5 s unseen) closes it, and shorter falls are listed as "got up quickly — no alert". **Nothing is sent to anyone** — the owner's design. Two optional, signed buttons: "I'm on my way" (can be undone) and "Not a fall" (final); both audited before the write. Videos 30 days, entries for ever. Console only — the phone hides it from Tools and its bell opens the cameras. **Measured only on the owner's test split** (Le2i + UR Fall, event F1 0.85) **at 25–30 frames a second**; the engine analyses at the camera's rate (5/sec) and fills in the poses between, which the real model still flags correctly on synthetic falls at 5 and 3/sec — but **nothing has been measured on a school camera, at any rate**. Refused below 5 frames a second (a camera set to 3 measured 1.75 at the model, too few for it to judge anyone); System Health names any camera whose frames still arrive too far apart. Needs `models/yolov8s-pose.pt` on the machine; without it System Health says so |
| Lost bag | **Real** (P7) — tick cameras, pick a colour, and any bag of that colour is outlined live on the tiles. There is no search and no job: the tile's own overlay poll is what makes the model run, so it works only on cameras somebody is looking at and stops within seconds of them leaving the page. Idle cost is zero. **Nothing is recorded** — no clip, no still, no history, so a bag taken before you opened the page cannot be found. **Nothing is alerted.** **Accuracy on real bags is unmeasured** — there is no clip with a bag in it. On footage with *no* bag it is now quiet: 1 false bag across 399 sampled frames, after switching from the fine-tuned `bagbest.pt` (17, including a black office chair read as a suitcase at 0.88) to `bagsearch.pt`, a YOLO-World prompted with nine words for "bag". A box still means *possible bag*, in amber, over a live picture the operator judges themselves |
| Vehicle gate | **Real** — a camera with a gate number and a direction reads plates. Nothing is recorded from one frame: frames vote (confidence × plausibility × plate size), near-identical readings merge, and a pass is written only when three agree; the same plate at the same camera inside a minute is one pass. Each pass keeps a photograph and a plate crop, deleted at 30 days, row kept for ever. A weak read is kept and flagged, never discarded. The register imports from Excel or CSV in English or Arabic and collapses both digit systems onto one row; a pass reads as registered, not registered, blacklisted or expired, frozen at the moment it happened and never rewritten. A guard reads, an administrator writes and exports, and the export is audited before the file is built. **Nothing is blocked.** A gate alert — blacklisted, not on the register, or an expired permit, each switchable in Settings and all three on by default — raises an item on Home and sends one message per recipient on the channels its rule has on (P9, spec 013). The message waits until the reader is done with the car - it has left the camera - so it states the corrected reading, not the first three frames' guess; a plate a guard corrects by hand sends nothing, and a car still in view when the engine was stopped is logged at the next start as not sent rather than sent late. The message carries the plate as text and the gate, never the owner's name or a photograph. **"Inside now" needs an exit camera**: with only `cam-laptop` as gate 1 entry, the page says no exit camera is configured rather than printing a paired figure, and a visit closed by the car re-entering is marked an estimated exit. An administrator can **delete one pass** — the row, the photograph and the plate crop go for good, and the audit entry that names the plate stays. **Accuracy: measured for the first time on 27 Aug** against the owner's EALPR set (2,086 photos, 2,142 plates), and the news is good and bad. Our port reproduces the project it came from **exactly** - 2086/2086 identical readings, so the software is not the bug. Plate detection is 99.8%. But the two accelerations that were reverted on 24 Aug are worse than anyone guessed: FP16 changes 6.7% of readings and the TensorRT plan changes **26.6%** - one reading in four on a model that classifies single characters. Both stay off for good; the plate models run the `.pt` at FP32 and no `--fp32` engine experiment is worth building. **What is still unmeasured is the thing that matters**: that dataset is what the models were trained on, so it proves pipeline fidelity and says nothing about the school's gate. Read accuracy on real plates needs a human-confirmed truth file (`python engine/tools/eval_plates.py --label`, waiting on Mohamed) and site captures. See `specs/007-vehicle-gate-tuning/evidence/`. **Two older fixes stand**: the band-stripped greyscale crop bug (fixed 24 Aug, pinned by a test), and three found the same day - the overlay poll refused by request validation, plate reading never boosting while somebody watched, and the repeat window being hardcoded rather than `vehicles.dedupe_seconds`. **And one more, found 27 Aug**: gate tiles had *still* never drawn a plate box, because the 24 Aug fix repaired the request while the response failed one layer down - `kind="plate"` was missing from the wire contract's `Box.kind`, so a plate in view took the whole overlay down. Fixed, and pinned by a test that ends at a validated `CameraView` rather than at the box. Boxes now also carry the plate's width in pixels as an aiming aid. **And the gate was dead for a day, 4-5 Sep**: `a830f1c` gave `FeatureWorker` a load window called `self._recent`, which is also what `vehicles.py` calls its dict of plates seen lately. The subclass assignment won, the base class called `.append()` on a dict, and every vehicles thread died on its first frame - `AttributeError: 'dict' object has no attribute 'append'`, in the log and nowhere else. No plate was read on this machine for a day while every screen said the feature was running. The window is now mangled to `_FeatureWorker__load_window`, which a subclass cannot take by accident, and two tests in `test_live_readings.py` hold it there. **Nothing on screen said the worker had died** - a feature whose thread was gone read as alive and idle, rule 8 unmet. Now fixed: a thread that ends without being stopped is recorded per camera, and System Health's workers row and the feature's own row say it stopped and name the cameras (`test_health_load.py`) |
| Users, audit, notifications | **Auth is real** (P2) — argon2 accounts, server-enforced roles, sessions revocable. **Alerts are real** (P9, spec 013) — email through Gmail (confirmed on a real inbox, 11 Sep 2026; WhatsApp and SMS were removed the same day), and Home's "Needs your attention", which a guard can acknowledge under their own name. Recipients, rules and a delivery log live in the database and survive a restart; every change and every test send is audited first; an administrator decides who is told. "Sent" means the courier accepted the message, nothing more. Messages carry facts only — what, where, when, how sure, who decided — and never a student's name, a face or a picture, proved by a test. With no keys in engine/.env every would-be message is logged as skipped and Settings and System Health name the missing keys. **Not yet**: the Arabic message wording is an unreviewed draft, so Arabic recipients get English; the noon report is silent until the 2026–27 term dates are set, and Settings says so. Audit still lives in RAM |
| Ask | **Real** (P12) — type a question in Arabic, Franco-Arabic, English or a mixture and it runs one of **fourteen existing queries** and shows that query's real result: figures, rows, camera, time, confidence, and the clip where the query already has one. "Track Ali" comes back as Ali's stops, not a link to the Track page. **Every capability is reachable**: attendance, headcounts, restricted zones, knives, the gate (passes, inside-now, totals, register), where a person went, one person's history, the directory, group rosters, lost items and system health — fourteen queries, and each one opens its own page with the question already applied. "Any knife alerts this week" lands on Weapons filtered to last7; "is Omar Khaled enrolled" lands on People searched for him; "how many days has Layla been present" lands on her history page. Every answer carries an **"understood as" line** naming the query and its parameters, and marks any parameter it assumed (a question with no date means today, and says so). Names and plates are **masked locally before anything leaves the site**, across both scripts and both digit systems — سارة, ساره, Sara and Sarah are one person, and a plate in Arabic-Indic digits matches the register's Western ones. A first name two children share is masked to a placeholder that resolves to nobody, and Ask asks which one rather than guessing. **A word the site does not recognise is sent as typed** — a visitor's name does leave — and the answer names those words; administrators see the exact text that left. Read-only, and every question is audited **before** the answer is built, including questions asked while the cloud is down. Four honest states, each with its own message and reason: out of scope, one detail missing, an unknown person (which is *not* an absence), and unavailable. **Lost items cannot be asked about** — bag search runs live on watched tiles and stores nothing, so Ask says there is no history to search and offers the page. **The provider is Gemini's free tier**, whose terms allow Google to use submitted content and human reviewers to read it; accepted on 30 Aug 2026 because masking reduces what leaves to "when did PERSON_1 arrive today?". Linking billing turns that off with no code change. **Routing accuracy measured 30 Aug 2026: 91.9%, against an SC-003 bar of 95% — so SC-003 is NOT met.** 34 of 37 corpus questions, on `gemini-3.5-flash-lite`. Egyptian dialect is the weak side at 83% against 94% for English, which matters because dialect is what the guards type; Franco-Arabic, mixed script and MSA all scored 100%. The configured `gemini-3.7-flash` is **unmeasurable on the free tier** — Google's API returns `limit: 20` requests, not the 1,500/day the published guides claim, and one corpus run is 37 questions. Full figures and every wrong route in `specs/010-ask/evidence/routing.md`. `--dry-run` proves the masking with no key and no network: **0 identifiers leak across 37 questions**. **The Arabic wording is drafted by me and not yet read by a native speaker**, so it renders only in dev until Mohamed corrects it |
| Mobile app | **Rebuilt phone-first (17 Sep 2026, spec 015)** — Mohamed chose his own phone layouts over 014's squeezed console screens, from an approved clickable design. Five tabs: Home, Cameras, Tools, People, More. Tab screens have a top bar with the VisionGuard mark, the camera sentence in the console's words, the alert bell (the console's own count: `app/useAlertFeed.ts`, lifted out of the console's bell and now shared) and the signed-in initials; every screen below a tab has a back arrow. Home puts what needs attention first (each item opens the exact thing, as the bell does), then four figures each taken from its tool's own call, then a live camera. Cameras is new: every camera by area, and one camera at a time with a choice of which feature draws its boxes (one feature at a time). Choices open bottom sheets; tables became cards. Every screen starts from the console page's logic - same calls, polls, notices, wording - and only the arrangement changed; Track a person, Enrol, camera setup and the vehicle register/movements stay the console's code, restyled. 28 shared files are held byte-identical by `tools/check_parity.py` (the bell hook and `useLinkedItem` joined). **Measured**, not hoped: `tools/phone_audit.js` at 360 px on all 20 screens in English and Arabic, light and dark - no sideways scroll, no target under 44 px, no text under 4.5:1 contrast or 12 px - and with the engine unreachable every figure shows a dash, never 0. What was left out of the design, why, and 13 console defects the rebuild found (a school-profile edit that saves nothing, a dead Edit on Accounts, face boxes with names on System health's grid, among others) are in `specs/015-phone-first-redesign/gaps.md`. **Still not done: nothing has been checked on a real phone in a hand** - the keyboard over forms, the notch, export downloads, live video on mobile data. The Arabic stays the unproofread draft, dev-only |
| Remote access | **Built, not yet used from outside** (20 Oct 2026, spec 020, branch `claude/remote-access-020-eb54ac`, not pushed) — phones and PCs the owner enrols reach the console and the phone app over NetBird's private network; there is no public address and nothing is opened on the router. **Setup does the workstation's part**: its optional Remote access page takes a one-off NetBird key, installs NetBird from the kit, joins with the key, opens TCP 443/8443 to NetBird's adapter only, adds its address to the site certificate, and turns off the allow rules Windows makes by itself for Caddy on Public networks (two were found on the stand-in laptop). **Anything outside the factory network is remote**: self sign-up is refused; a camera tile is a still picture every 2 s at 320 px (0.036 Mbit/s each, measured on the clip), a live view 480 px at 5 a second (0.61 Mbit/s), two per account; event clips go in full. **Locks**: 5 wrong passwords lock an account for 15 minutes (an administrator unlocks it on Users), the cookie is HTTPS-only, and every sign-in is audited with its real address (still the in-memory audit until spec 018). The installed apps show a plain “cannot be reached” page and cache nothing; System Health has a Remote access row. **Phone notifications** are a second alert channel (a Phone switch per rule; each phone registers itself and waits for an administrator; kind, camera and time only). **Not yet done**: the NetBird account and installer (owner), Setup rebuilt with them, every drill on real devices, and a notification seen on a locked phone. |
| Website | **Live at www.vision-guard.org** (27 Sep 2026, spec 017) — served from the public repo `Fo2sh-61/vision-guard-website`, which holds only the site. vision-guard.org forwards to www, keeping the page path. **HTTPS works and is enforced** (28 Sep 2026): http:// redirects to https://, on www and the bare domain. GitHub's certificate job had sat at "dns_changed" for about a day although a read-only diagnosis found everything on our side correct (DNS, DNSSEC, CAA, the challenge path, Let's Debug, GitHub's own health check); opening the repo's Pages settings page as the owner made GitHub re-check, and it issued the certificate (Let's Encrypt, valid to 27 Dec 2026, renewed by GitHub). Removing and re-adding the domain through the API had not helped. **Do not remove or re-add the Pages domain, or change DNS or the CNAME file**: each change restarts GitHub's certificate queue. The domain was registered on 26 Sep 2026; the 2025–Jan 2026 certificates on crt.sh belong to an earlier owner of the name. **The new design is live** (published 28 Sep 2026 at Mohamed's go-ahead, site repo commit 452454d, and b7d9903 for the scroll fix below): Mohamed's Website v3 on PC and his Mobile design on phones, English and Arabic; all 14 live files checked byte-for-byte against the tested build. Publishing an update is the copy and push in spec 019 quickstart §9. **How the site is built now**: `node tools/build_website.mjs` turns the four design files in `design/Visionguard website full design/` (Website v3 and Mobile, each in English and Arabic) into plain HTML and CSS with no build step on the host; it stops, writing nothing, if any of its site edits no longer fits a design or a design adds an interaction `main.js` does not know. Each home page carries two copies — the PC design from 600 px wide, the phone design below it — and each matched its drawing element by element (PC at 1440 px, phone at 390 px); tablets get the PC design, with the header's four links on their own row below 920 px (measured: the header was 237 px tall at 600 px). **Arabic site under /ar/**: the home page is Mohamed's Arabic design; About us, Trust & privacy and Help centre were translated by Claude and **wait for Mohamed's read** (Trust & privacy's Arabic is the three old pages' Arabic, shortened; only its title, intro, jump buttons and the forwarding pages' line are new) (`specs/019-website-v3/arabic-review.md`). **The home page's checked wording is back in the build (28 Sep 2026, at Mohamed's request after a council review named it the first thing to fix)**: the 18 sentences the 27 Sep claim check found untrue or overclaiming (`specs/017-public-website/claims.md`), which the design's words had brought back on 27 Sep, are replaced by their checked wording on PC and phone, in English and Arabic (converter edit E18; the Arabic is Claude's draft and waits for Mohamed's read), and "208 cameras on a single site" now counts up to 500+ as it scrolls into view, over "cameras — the scale we're building for" (E19, Mohamed's choice: a goal, since nothing that size has run); the console pictures lost their 208 ("All cameras up"). **Published 28 Sep 2026** (site repo commit ab9d1ce, built from bd7cfde through `git archive`, so nothing uncommitted went out): the 16 changed and shared files are byte-identical to the build, and the §3 check passes on the live Arabic page. The Terms' paragraph saying the home page's short descriptions can say more than the product does, which E18 made untrue, is gone: when the Terms were condensed into Trust & privacy it became the plain rule that where anything elsewhere on the site differs, that page is the accurate account. About us and Help centre keep their checked words. **The contact form sends** through FormSubmit to sales@vision-guard.org from both languages and both layouts; the thank-you shows only when FormSubmit confirms, anything else says "not sent" with the email and phone, and form messages are in the page's language. Mohamed reports FormSubmit is activated and a question sent through the site arrived. The Help centre's form sends to support@vision-guard.org the same way. **Security, Privacy policy and Terms of service are one page, Trust & privacy** (`website/trust.html` and `ar/trust.html`, 28 Sep 2026, at Mohamed's request): short but complete, about 37% of the three pages' length, every legal point kept, each part checked against its original; the old `security.html`, `privacy.html` and `terms.html` forward to its `#security`, `#privacy` and `#terms` parts, and the footer's Trust column has two links, Trust & privacy and Help centre. Privacy policy and Terms of service first went live earlier that day, at Mohamed's choice to publish straight away. Owner named as "VisionGuard, based in Egypt"; Egyptian law and the courts of Cairo; Personal Data Protection Law No. 151 of 2020; form messages kept 12 months after the last reply. Every statement was checked against the code (researched, drafted, then reviewed for truth and for Egyptian law, translated, and the Arabic checked fact by fact against the English). They disclose what the product really does, including two things worth fixing: the Ultralytics library sends usage statistics to Google Analytics (the engine never switches it off), and the Terms say plainly that the home page's short descriptions can say more than the product does. **Not legal advice; an Egyptian lawyer has not read them.** The law's one-year compliance period ends about 31 Oct 2026; research found controllers need a PDPC licence or permit, and transfers abroad need a licence or a legal exception. Footer items with no page yet (the seven Solutions, Careers, Partners, LinkedIn, X, YouTube) are marked Soon (قريبًا) and do nothing. Nothing on the site claims face-based attendance at schools. **Scroll effects**: the new design wrapped 18 boxes per page in overflow:hidden, which froze every scroll-linked effect inside them (the counting numbers, the Honest zoom, the phone drift, the card lines — 23 of 45 on PC); Mohamed noticed the numbers had stopped counting. The converter now uses overflow:clip there (site edit E17); layout measured identical, and no scroll effect is frozen on the live site. **Not checked by hand yet**: a real phone, Firefox, Safari on an iPhone, reduced motion with the OS setting on, and the scroll effects watched by eye (checked by code only: the in-app browser was hidden). |
| Fights | **Removed from scope** — no model. Page, endpoints and mock methods all gone (P0-05) |

## P0 progress

**All ten done.** Each shipped with its regression test.

| | | |
|---|---|---|
| P0-01 | fixture fallback killed | done |
| P0-02 | track badge reads the name | done |
| P0-03 | timezone per timestamp | done |
| P0-04 | person-mode late cutoff | done |
| P0-05 | fights removed | done |
| P0-06 | SQLite WAL + busy-timeout | done |
| P0-07 | dead buttons | done — Health "Restart" was missed and stayed dead until 2026-09-11. Removed, because no endpoint restarts anything (`test_health_restart.py`) |
| P0-08 | error / empty / degraded states on every page | done |
| P0-09 | person history + groups wired | done |
| P0-10 | CI: the four gates | done |

## P1 progress

| | | |
|---|---|---|
| P1-01 | one detection pass per frame, one thread in the model | done |
| P1-02 | overlay freshness (`age_ms`) in API and UI | not started |
| P1-03 | private `_tracked_boxes` reach-in removed | done |
| P1-04 | latency / queue / drop metrics on System Health | **done** (P8, 30 Aug 2026) |
| P1-05 | isolation test: kill one feature, prove the other survives | not started |
| P1-06 | measure and publish the latency budgets | done |

## P2 — security · **done**

Every endpoint except `/healthz` and `/auth/login` refuses an anonymous caller.
Roles are enforced server-side from the path, so a new endpoint under
`/enrolment`, `/sources` or `/users` is admin-only the day it is written.
Editing the browser achieves nothing — a test asserts the console stores no
role, account or token.

The password-free developer sign-in (11 Sep 2026) was removed by spec 016.
Every page, for agents too, needs a local account made by
`engine/tools/create_user.py`.

**Create the first account before starting the engine, or nobody can sign in:**

```powershell
python engine/tools/create_user.py
```

## Workload placement (30 Aug 2026, corrected 12 Sep) — `specs/009-workload-placement`

Removing processor work nothing reads. Measured with `benchmark.py --site`; full
figures in `specs/009-workload-placement/measurements.md`. Figures are in
**cores**: how many processor cores the work keeps busy flat out. An 8-core box
supplies 8.

| 100 cameras | |
|---|---|
| Before | **23.0 cores** — 3 boxes; one 8-core box carries 34 cameras |
| After | **about 14–20 cores** — 2–3 boxes; one box carries about 40–57 cameras |

**The after figure first published, 9.17 cores and 87 cameras a box, was
wrong.** It assumed an unwatched camera skips the decode on four frames in
five. It does not: OpenCV's `grab()` is the decode, and `retrieve()` — the part
that is skipped — only turns the decoded frame into pixels. Every frame of
every camera is still decoded. `benchmark.py --decode` now measures what the
conversion is worth: somewhere between about 10% and 60% of a frame's capture
cost on the labelled clip, depending on how FFmpeg threads the decode and on
the run. `--site` uses that measurement instead of assuming. The saving is real
but small: about 3–9 cores of the 23, not 14.

23.03 corroborates the Workload Plan's ~25 figure, which matters because that
document is not in this repository. Both rest on an assumed 6 ms to capture a
frame, and nothing in the repository records where that came from.

**Decoding is now the biggest cost left** — 6 to 13.5 of the after figure's
cores, on every frame of every camera, watched or not. Hardware decode is what
would cut it (below).

| Change | State |
|---|---|
| Patrol face recognition off | **on** — `patrol_hz: 0` is now the default |
| Convert unwatched frames to pixels only at the analytics rate | **on** — `live_capture: watched`. Saves the conversion, not the decode |
| Batch the shared person pass | shipped, **off**, and buys nothing yet — see below |
| Face detection gated to person crops | shipped, **off** by default — see below |
| Bag TensorRT removal | **rejected on measurement** |

**Face gating is off because it cannot prove it is safe.** `compare_detections.py
--gate-check` finds every face either way — 60 of 60 — but boxes land up to 11px
apart, because YuNet on a crop is a different computation from YuNet on a frame.
That moves the landmarks, and the landmarks decide which patch gets embedded. It
waits on a measurement against a real enrolled roll.

**Batching cannot work on TensorRT.** The compiled engines have a fixed batch size of 1 and raise when handed several frames. That exception lands where `FeatureWorker` catches it per frame, so switching batching on would have made detection **quietly stop** — a log line nobody reads and boxes silently missing. It now detects this once, says so, and runs one frame at a time. Rebuilding the engines with a dynamic batch would unlock it; P8-FR-018 says not before the GPU driver is current.

**The capture change nearly cost more than it saved.** Skipping the conversion only helps if grabbing a frame WAITS for one. On RTSP it does; on a webcam it returns instantly, and the loop spun at 658,000 grabs a second - a whole core per camera, which would have looked like a busy machine rather than a bug. It now paces itself: 653 grabs where there were 1.3 million, same 5 Hz converted.

**The bag TensorRT claim was wrong.** Deleting the engine was supposed to be "a
free ~31%". Measured: TensorRT 23.3 ms p95, PyTorch 29.0 ms. No saving, and
TensorRT is better where it counts. Reverted.

**SC-001 is not met, by a long way.** The target was ≤5 cores and the result is
about 14–20. The gap is decoding, not face gating: the whole faces row is 3.3
cores. 13–39% of the before is gone, not the 60% first reported.

**Follow-on, measured but NOT built: hardware decode.** `benchmark.py --decode
--hw` and `--streams` now time every graphics chip on the machine against the
processor, on an H.264 copy of the labelled clip, and ramp streams until one
falls behind a camera. On this laptop a chip decodes a frame for about **a
tenth of the processor time** — 0.35 ms on the Intel UHD 630 and 0.62 ms on
the NVIDIA against 3.80 ms — and the two halves of capture swap over: the
decode becomes nearly free and the conversion becomes almost all of what is
left. That conversion is exactly what `live_capture: watched` already skips,
so the two changes multiply. For 100 cameras of 1080p, capture only: **67
cores on the processor, about 10 on a graphics chip** — but one chip carried
only 37 of those cameras, so 100 would need three chips whatever the cores
say. Every figure is a re-encode of one laptop clip; two minutes off a real
site camera through `--clip` would replace the lot. **Nothing about capture
has changed** — `CameraSource.open()` still asks for no acceleration, and a
test pins that until the owner chooses. Three shapes for the setting, three
for what System Health should say, and what a fallback has to handle, are in
measurements.md §1c for him to pick from.

**Patrol off is visible, not silent.** Track a Person now says when only the
entrance cameras were looking for faces, so a thinner path cannot read as a
person who was not there.

**System Health shows real load** — per worker: frames processed, last inference
ms, queue depth, dropped frames, and whether it is behind. Frames decoded but
deliberately not used are counted separately from frames dropped; they are not
the same thing. (The page called them "Frames not decoded" until 12 Sep, which
was untrue.) Per-worker processor share is **not** shown: workers are threads in one
process, so that number could only be invented.

Found and not fixed: **`accelerate: false` is silently ignored for the bag and
person models** — neither passes it to `load_model`. It works for plates only.

## Camera onboarding (1 Sep 2026) — `specs/011-camera-onboarding`

Camera setup was the one screen an operator meets before anything else works,
and five things on it were not true. All five are gone.

| Was | Now |
|---|---|
| Connecting a recorder **always** reported 16 channels, "ok", 704x576 — whatever the recorder was, and whether or not it answered | Every channel offered was opened and returned a frame. Channels that did not answer are listed with their reason; ones the time budget never reached read as *not checked*, which is a different answer |
| **Add** on a discovered device, and on recorder channels, called nothing — a row appeared and vanished on refresh | Both call the engine. Recorder channels go in one act with one outcome per camera |
| A ticked "Capture service" at `192.168.1.10` that does not exist | Gone |
| Network scan returned `[]`, rendered as "0 devices found" | Says plainly that searching is not available on this engine, with the reason |
| The name and area typed against a channel were discarded (uncontrolled input, `<select>` with no handler) | Controlled, and sent |

**`LiveStore` never overrode `connect_dvr`.** It subclasses `MockStore`, so the
live engine answered from the fixture. A test now asserts
`LiveStore.connect_dvr is not MockStore.connect_dvr`, shaped after the
`LiveStore.ask is MockStore.ask` assertion in `test_ask.py` — same bug class,
opposite assertion.

**The feature list now governs, and this is a real change in coverage.**
`weapons`, `intrusion` and `lostitems` ignored the camera's `features:` list
and ran on **every enabled camera**; ticking or unticking them changed nothing.
They follow the list now. `cam-laptop` lists `attendance, counting, intrusion,
track, vehicles` and **not** `weapons`, so knife detection no longer runs on
it until somebody adds the feature — which is what that file already said it
wanted. Under `-Clip` it is zero cameras. Startup logs the count per feature,
and System Health says so with a reason rather than looking healthy over
nothing.

Knife detection is the one that cost real money: unlike zones, which return
before touching the detector, it ran the shared person pass on **every frame
it processed on every camera**.

**Assignment takes effect without a restart.** `FeatureWorker` gained
`watch`/`unwatch`, per-camera stop events, and a `_closing` hook that runs on
the camera's **own thread** — never the caller's. That is deliberate:
`ZonesWorker.set_restricted`'s docstring records what happened the last time a
scene was closed across threads, which was that the recording of the scene
still running got replaced. A camera added or edited is analysed by its chosen
features in under 10 seconds.

**Cameras can be corrected.** `PATCH /sources/{id}` keeps the camera's id, so
everything recorded against it stays attached. A features-only edit does not
reopen the stream; changing the address, rate, rotation or enabled state does,
and the response says which. Editing a camera that came from `engine.yaml`
reports that it now has a stored row shadowing the file.

**Six columns the roster never had** — `faces`, `gate`, `direction`,
`face_gate`, `live_capture`, `neighbours` — so a camera added from the console
can now be an identity camera or a gate camera. It never could before,
whatever was typed. Existing databases migrate in place.

**An unknown feature name is refused at startup**, naming the word and what was
expected. `weapon` instead of `weapons` used to mean no knife detection on that
camera, for ever, with nothing anywhere to say why.

Every write under `/sources` is now audited **before** it happens, and
administrator-only by path. One test adds a camera whose password is a sentinel
string and asserts it appears in no response, no log line and no audit entry.

**Verified 1 Sep 2026:** `specs/011-camera-onboarding/evidence/walk_quickstart.py`
walks the whole feature against the real app with its full startup - 42 checks, 0
failures, on a throwaway database. Re-run it after any change here.
**Not verified by me:** a real recorder against real hardware, and the console
screen itself - there is no account on this machine, so nobody can sign in until
`python engine/tools/create_user.py` is run.

**Still not built, and said so rather than faked:** searching the network for
devices. **Out of scope by the owner's decision:** load and capacity work,
splitting cameras across machines, several factories on a shared cloud, and
ONVIF. Camera count remains an input, never a constant.

## Next 3 things

1. **P1-02** — overlay freshness, so a stale box degrades honestly
2. **P1-04** — latency and drop metrics on System Health
3. **P3** — durable events: the audit trail still vanishes on restart (alert recipients, rules and the delivery log already persist, spec 013)

## Blocked on the owner

- **Remote access on real devices** → the NetBird account, its policy and its Windows installer are in place (20 Oct); the workstation still has to join with a setup key and the remote phone and PC be enrolled before any spec 020 drill can run (`specs/020-private-remote-access/owner-checklist.md` parts B–D)
- **Re-ID model** + architecture + how it loads + Python version → blocks `.venv` and track
- **A recorded clip with a knife in it** → the regression suite has 21 labelled ground-truth marks and not one knife, so knife accuracy on real footage is still unmeasured
- **A fall on a school camera** → the fall model is proven against the owner's own code and on synthetic skeletons, never on a person actually falling in front of one of our cameras. A staged fall (and a sit-down that is not one) on the clip camera is the first real check
- **A recorded clip with a bag in it** → same gap on the other side: bag detection is proved not to fire on furniture-only footage but has never been shown to find a real bag. `python engine/tools/record.py` writes one
- **Consent / lawful basis for biometrics of minors** → blocks deployment entirely
- **Target hardware** → blocks the 208-camera plan
- **Rotate the Kaggle key** that was in `models/knife detection/kaggle.json`. The folder and the file are gone from disk and were never in git, but a key that once sat in a working tree is a key to rotate

## Run it

```powershell
.\launch.ps1                         # or the desktop shortcut — the double-click path
.\launch.ps1 -Mobile                 # or the VisionGuard Mobile shortcut — opens the phone app
.\dev.ps1 doctor                     # pre-flight, run each morning
.\dev.ps1 up -Mock                   # UI work — instant, no models
.\dev.ps1 up -Clip                   # pipeline work — deterministic
.\dev.ps1 up -AllowSystemPython      # real cameras — final check only
.\dev.ps1 down                       # panic button, frees 8001/5173
```

**Two launcher bugs fixed 5 Sep 2026**, both reported as "the icon doesn't work properly and no browser opens".

*The tab never opened.* `launch.ps1` waited for both ports by opening a socket to `127.0.0.1`. The engine is there, but Vite binds the IPv6 loopback and nothing else — `[::1]:5173` — so the check could never pass, waited its full ninety seconds, and gave up without a word. It now asks over HTTP by name (`http://localhost:5173/`), which resolves to whichever loopback the server took, exactly as the browser does.

*A failed start closed the window instantly.* `Invoke-Up` returned 0 on the line after it printed "every job has exited", so the launcher skipped its "Press Enter to close" and the console vanished with the error still in it — from an icon, indistinguishable from nothing happening. It returns 1 now, names which job ended and how, and the window waits.

**And saved clips would not play in the console — fixed 5 Sep 2026.** Every recording on this machine was written as MPEG-4 Part 2, which browsers cannot decode, so *Watch clip* gave a player with no picture. The code asked for H.264 and had a comment saying Windows would supply it through Media Foundation, but it called `cv2.VideoWriter(path, fourcc, ...)` without naming a backend — which picks FFmpeg for an `.mp4` and stops there. OpenCV's pip build ships no H.264 encoder for licensing reasons, so that ask failed every time, loudly, in native code Python cannot catch:

```
Failed to load OpenH264 library: openh264-2.5.0-win64.dll
[ERROR] VIDEOIO/FFMPEG: Failed to initialize VideoWriter
```

That block at every start-up was the warm-up probe failing, and the silent fallback to mp4v was the real damage. Naming `cv2.CAP_MSMF` is the whole fix: measured here, it writes real H.264 (`avc1`/`avcC`) at 1920x1080, 1280x720, 640x480 and odd sizes, needs no download, and never reaches the FFmpeg path that printed the error. The ordered list now lives once in `engine/vg/ingest/encoder.py`; the recorder and the archive exporter had a copy each and were wrong the same way. `engine/tools/record.py` still writes mp4v on purpose — those clips are read by OpenCV, never played in a browser. **The end-to-end test that proves it had been skipping on this machine**, because it probed the default backend to decide whether to run; it probes the real chooser now, and passes.

Tests: `.\dev.ps1 test` runs all four gates — pyflakes, pytest, smoke start, tsc.
(tsc is **not** `--noEmit` — project references make it a silent no-op)

No `.venv` yet — deliberately blocked on the re-ID handover. System Python 3.14 works: torch 2.11.0+cu128, CUDA true on an RTX 2080.

**Gates verified 5 Sep 2026, all green:** 1,548 passed, 6 skipped · pyflakes clean over `vg`, `tools` and `tests` · tsc clean. (Was 1,246 on 27 Aug; the launcher and codec pass added 3, and one test that had always skipped here now runs — see below.)

`pytest.ini` already sets `-q`, so `python -m pytest engine -q` is `-qq` and prints **no** final "N passed" line. Use `python -m pytest engine` for the summary.

**Run pytest from the repo root**, as `python -m pytest engine`. Three tests in `test_track_page.py` read `web/vite.config.ts` and `engine/tools/measure_track.py` by relative path, so running from inside `engine/` fails them on a missing file — nothing is wrong with the product, and they pass from the root. Worth fixing the paths one day; `tests/test_eval_plates.py` shows the pattern (derive from `__file__`).

Also verified on a **fresh clone with no `engine/data/` and no model weights** — the condition CI runs in: 374 passed, 7 skipped. The extra skip is the model-weights check, which has nothing to check on a machine that has no weights.

`.github/workflows/ci.yml` is committed and the repo now has a remote (`Fo2sh-61/VisionGaurd`, private), so it runs on push. **It has not been observed passing yet** — nobody has checked the first run.

## Falls (15 Oct 2026)

- **Model**: `models/falling/checkpoints__temporal_model.pt` (70k-parameter LSTM, `lstm_cctv`), the owner's choice; his calibrated alert rules are stored in it and used as stored. The rule-based detector in the same folder is not used. Pose: the `pose` model already in `engine.yaml`, now at the owner's 0.30 confidence
- **Files**: `infer/falls.py` (the port + the 30-a-second timeline), `features/falls.py` (down / alerted / got up / left), `events/falls.py` (`fall_scene`), `/falls/*` endpoints, `pages/Falls.tsx`, `components/FallChecking.tsx`
- **Two older bugs fixed on the way, each with its test**: editing a camera from the console sent its body JSON-encoded twice, so every edit was refused with a 422 (`test_console_requests.py`); and a features-only edit read back as the old list until a restart, because the registry was never told (`test_sources.py`)
- **Not done**: the design's "Moving now" and "Who" rows - one would need a threshold nobody has measured, the other a name this feature must never show; and the per-frame model cost is an estimate on System Health until it runs on the owner's GPU

## Housekeeping

`_to_delete/` at the repo root holds an install zip and git lock litter — safe to delete manually.

## Measured, not assumed

Person detection on the RTX 2080 Max-Q, `python engine/tools/benchmark.py`:
**p95 18 ms**, 57.5 frames/sec, against a 250 ms budget. Re-run it on the
deployment machine — this is a power-limited laptop GPU without TensorRT.

Throughput, not latency, is what sizes the hardware. See `docs/PLAN.md` §7.
