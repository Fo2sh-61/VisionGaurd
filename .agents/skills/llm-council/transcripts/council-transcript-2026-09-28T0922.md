# Council transcript — VisionGuard as a startup, Shark Tank view

**Date:** 28 Sep 2026, 09:22 · **Asked by:** Mohamed ("see my project as you are shark tanks and tell me what you see for this start up project" — "I'm talking about visionguard in general")
**Founder's answers before the run:** first site = talking, nothing signed · pricing = one-off project price · team = just me · ask = "from all points of view"
**Helpers:** 11, all Sonnet (5 advisors, 5 reviewers, 1 chairman) · about 844k tokens in total (~70–90k each, mostly fixed start-up context)
**Context read for the framing:** README.md, docs/PLAN.md, STATUS.md, specs/016-pilot-site-readiness/spec.md, specs/017-public-website/claims.md, research/concealment-poc/README.md

---

## Framed question

The founder of VisionGuard asks the council to look at the company the way Shark Tank investors would, from every point of view (as an investment, as a partnership, as a customer would see it, as a competitor would) and say plainly what they see: what is strong, what is weak, what would make them invest, partner or pass, and what the founder should do next.

THE PRODUCT. VisionGuard is AI software that runs on a site's existing security cameras (IP cameras and recorders) and answers operators' questions about what happens on site. It targets schools and organisations, starting in Egypt (Arabic and English, Egyptian licence plates). It runs on-premises on one GPU workstation at the site (Windows 11), with a desktop console and a phone app. Running on live data today:
- Attendance by face recognition at entrances, with late cut-off and export (founder considers this done)
- Face enrolment in the browser with quality checks
- Track a person across cameras (a face names a person; clothing only matches "same body")
- Restricted zones: a camera marked restricted logs anyone who appears, with a video clip
- Knife detection (founder-trained model): each alert is marked "unconfirmed" until a person presses Confirm or False alarm. No gun detection
- Lost bag: pick a colour and matching bags are outlined live on chosen cameras; nothing is recorded
- Vehicle gate: reads Egyptian plates and checks them against a register (registered / not registered / blacklisted / expired)
- "Ask": type a question in Arabic, Franco-Arabic or English and it runs one of 14 built-in queries; names are masked before the text is sent to Google's Gemini (free tier, whose terms let Google use submitted content)
- Email alerts, user accounts with roles, and a system health page that reports honestly what is broken
- Arabic screens exist but are an unproofread draft, not yet shipped

WHAT HAS BEEN MEASURED, AND HOW IT CAME OUT
- People counting over-counts: one person reads 1-7 (2.5 on average); an empty room shows 1-5 "people" on about 3 frames in 4. Calibration not started.
- Knife: about one false alarm per four loops of a 40-second test clip that contains no knife. Detection of a real knife has never been measured (no test footage with a knife exists).
- Bags and plates: accuracy on real site footage is unmeasured (plate detection is 99.8% on the dataset the model was trained on).
- Ask: picks the right query 91.9% of the time (target 95%); 83% for Egyptian dialect, which is what guards actually type.
- Scale: designed for about 208 cameras on one site, never tested at that size. Measured cost: 100 cameras need roughly 14-20 processor cores, i.e. 2-3 machines.

STAGE AND TRACTION. Pre-revenue. No customer, no pilot running. The first prospect is a site planned for 208 cameras (about 16 to start): talks only, nothing signed. The software cannot yet be left running unattended at a customer site: installing as a service, backups, data retention, full erasure of a person's data, HTTPS, and removing a password-free developer sign-in are specified but not built. A company website went live on 27 Sep 2026 (vision-guard.org). Its home page still carries claims the founder's own internal check found untrue or overstated (for example "208 cameras on a single site", "every detection is checked by a person before anyone is alerted", "full audit trail", "right to be forgotten"), kept there at the founder's choice; the site's other pages state the limits.

TEAM. One person: a solo founder who builds with AI coding tools and also supplies and trains the AI models. The current codebase is about six weeks old (147 commits since 18 Aug 2026), after an earlier proof-of-concept project in March 2026. The engineering is disciplined: written rules against showing anything untrue, automated tests, claims backed by measurements.

BUSINESS MODEL. One-off project price: installation, hardware and software paid once, perhaps with a maintenance contract.

LEGAL AND PRIVACY. It recognises the faces of students, most of them children. Consent and legal work is the founder's responsibility and has not been done. Full erasure of a person's data is not built yet.

SIDE RESEARCH. The founder also tested detecting shoplifting from body movement; the founder's own measurements show it does not work well enough to use.

WHAT IS AT STAKE. Whether VisionGuard is a real startup worth backing, and where the founder should put the next months: product, first customer, business model, team, or something else.

*Clarification given to the chairman only:* "one GPU workstation" describes the planned pilot (about 16 cameras on one machine). Running across more than one machine is not built yet, so the full 208-camera site would need that work first.

---

## Advisor responses

Anonymised for review as: **A = Executor, B = Contrarian, C = Outsider, D = Expansionist, E = First Principles Thinker.**

### The Contrarian (B)

Pass. Three things kill this before I even reach the product.

First, the website. The founder's own internal check found the homepage lying — "every detection checked by a person," "full audit trail," "right to be forgotten," none of which exist — and he chose to leave it up. That's not a bug, it's a decision. His own constitution says "never show anything untrue," and he's the one breaking it, on the exact page that decides whether a school hands him children's faces. If he'll shade the truth before there's even a deal, I don't trust the rest of the numbers in this brief either.

Second, the infrastructure story contradicts itself. The pitch is "one GPU workstation." His own cost data says 100 cameras need 2-3 machines. His only live prospect wants 208. That's not a rounding error — the core hardware claim breaks on the first real customer.

Third, the feature schools actually buy this for — weapon detection — has never been tested against a real knife, and already false-alarms every ~160 seconds on a clean clip. That's an unvalidated liability, not a beta feature, sitting in a building full of children.

Layer on: no consent or erasure work on biometric data from minors, no HTTPS, a password-free login still live, one-off pricing (systems-integrator economics, no recurring engine), and zero moat — this is off-the-shelf models (SFace, standard detectors, free-tier Gemini) glued together, reproducible by any funded competitor in a quarter. Add a solo founder who is simultaneously the whole eng team and the whole ML department.

Nothing here is investable today. The website claim, specifically, shouldn't survive one more day regardless of what else happens.

### The First Principles Thinker (E)

Wrong question. "Would I invest" presumes VisionGuard is a computer-vision maturity problem on a normal early-stage clock. It isn't. Strip away the Shark Tank framing and ask what job this system does: it tells adults, about children, whether something dangerous is happening. That's not a features list — it's a trust system. Trust systems fail from one crossed line, not from a slow roadmap.

Found the crossed line already. The founder's own internal audit flagged website claims as untrue — "208 cameras on a single site," "every detection checked by a person," "right to be forgotten" — and he kept them live anyway. That's not marketing exaggeration; it's the exact failure mode the product exists to prevent, committed by the person building it, on the one channel a worried parent or school board will actually read. Everything downstream — the disciplined test suite, the honest health page, the "never show anything untrue" rule baked into the code itself — is evidence the founder knows better. So this isn't a skills gap. It's what happens the moment the audience shifts from compiler to customer.

Second-order proof the trust system is already broken on its own terms: about one false alarm per 160 seconds of empty footage, and zero measurement of true positives against an actual knife. Scale that to 208 cameras and guards mute it in week one — the exact alarm-fatigue failure that makes a real knife invisible when it matters most.

Don't evaluate this as an investment. Evaluate whether the founder will tell a school board "we don't know if it detects knives" with the same discipline he holds his own codebase to. Right now the website answers no. Fix that first — it's a one-line edit, and it's the whole company.

### The Expansionist (D)

Everyone will pattern-match this to "school security camera startup" — small TAM, scary liability. That's the wrong frame. Look at what's actually been built: a four-file plugin architecture (infer/features/events/api) that turns any new detector into days of work, not months. That's not a feature list, that's a platform for perception-as-a-service, already proven by shipping knife detection, plate reading, lost-bag tracking, and cross-camera person tracking in six weeks, solo, with AI tooling. The "Ask" natural-language layer is the sleeper asset — 14 intents today, but the real product is "query your camera network like a database." That generalizes past schools into malls, factories, hospitals, ports — anywhere with an operator who wants answers instead of footage to scrub through.

The bigger undervalued asset is geography-as-moat. On-prem processing is being framed as a limitation ("no cloud, one GPU box"), but in Egypt/MENA that's the unlock — data sovereignty, no dependence on shaky bandwidth, no dollar-denominated cloud bill, Arabic and Franco-Arabic native from day one. Verkada, Rhombus, and Evolv are not coming to build Arabic-first on-prem product for Egyptian schools. That's a multi-year regional head start in a market of 500M+ people, if the founder claims it now instead of waiting for validation.

The vehicle-gate plate reader is a second business hiding inside the schools pitch — parking, logistics yards, gated compounds — with a real 99.8% number to build on, independent of whether a single school ever signs.

Biggest missed upside: one-off pricing. This should be a platform license with recurring per-camera, per-feature fees that grow every time a new detector or "Ask" capability ships — the founder is about to sell a subscription business for the price of a one-time invoice.

### The Outsider (C)

Reading this cold, without any industry context, two sentences stop me before I even reach the metrics: the website carries claims the founder's own internal check found untrue, and the founder chose to leave them up. That's not a technical detail — that's the founder telling a total stranger he'll show one thing and deliver another when it's convenient. Everything else in this brief now has to be read through that lens, including the "measurements" offered as reassurance.

And the metrics don't help. A product named for guarding people admits its one safety feature that matters most — knife detection — has never been tested against an actual knife. It has a measured false-alarm rate but no measured true-positive rate. That's like a smoke detector company that can tell you how often it goes off for no reason but has never checked if it detects smoke. People counting is wrong so often an empty room "sees" people on 3 out of 4 frames. If I show those two facts to a parent instead of an engineer, I don't hear "early stage" — I hear "doesn't work yet, and they're advertising like it does."

Then: this product's whole job is scanning children's faces at a school, and the person responsible for the legal and consent side of that hasn't started. Nobody has signed anything. There's no company yet — there's one person with a laptop and a demo.

My plain answer: pass, today, as an investor. Not because the tech is bad — because the founder already showed he'll ship a claim before it's true, and that's the thing that kills trust with parents, schools, and investors alike, no matter how good the detector gets. Fix that first: pull the false lines off the live site before touching anything else, and get a lawyer in the room before the next demo, not after the first paying customer.

### The Executor (A)

Forget the pitch. Here's what's actually buildable by Monday, and what isn't.

Strong: the four-file feature pattern and the test discipline mean this founder ships fast and doesn't fool himself with fixtures. That's real execution capability, not a story.

Weak, concretely: nothing is signed. "Talks only" isn't traction, it's a phone number. And the product can't be left alone at a site yet — no service install, no backups, no retention, no HTTPS, no way to remove the dev-only password bypass. Those aren't hard, they're just undone. That's the actual to-do list, not "AI vision platform."

Pass on investing today — not the idea, the state. A public website carrying claims the founder's own audit called false ("208 cameras," "every detection checked by a person," "audit trail," "right to be forgotten") and left up anyway is disqualifying. If he won't fix a text edit his own tooling flagged, I don't trust the roadmap either. Partner, conditionally: only on "help me close one pilot," not "help me scale."

Monday morning, in order:
1. Fix the website. It's a text file. Do it before lunch.
2. Get a lawyer moving on child-face consent this week — the only blocker you can't code your way around.
3. Finish the specified productionization checklist (service install, backups, retention, erasure, HTTPS, kill dev sign-in). It's already scoped — just execute it.
4. Pitch the 16-camera pilot, not 208. Sell only what has numbers behind it: attendance, gate, tracking. Leave counting and knife detection out of any customer conversation until they're measured.
5. Get one signature. Everything else is theory until then.

---

## Peer reviews

Tally: strongest — B ×3, A ×2 · biggest blind spot — D ×5 · all five reviewers said every advisor missed the shoplifting research.

**Review 1.** Strongest: A — turns the shared finding into a prioritised plan and separates verdicts by relationship (pass as investor, conditional partner on one pilot); concrete go-to-market advice (16 cameras, not 208; keep counting and knives out of customer talks until measured). Blind spot: D — a full bull case that never mentions the false website claims, the untested knife detector or the missing child-biometric consent; for safety software over children that is a material gap. All missed: the shoplifting dead-end (a founder killing his own feature by measurement), and the likelier competitor — a local Egyptian integrator already selling into these schools.

**Review 2.** Strongest: B — adds the hardware-math contradiction (one workstation vs 2–3 machines per 100 cameras vs a 208-camera prospect), plus concrete moat and pricing critiques. Blind spot: D — never mentions the website claims, the knife detector or consent. All missed: "Ask" sends children-related query text to Gemini's free tier, whose terms let Google use it — a second privacy exposure; the killed shoplifting research as counter-evidence; and only A separates invest from partner.

**Review 3.** Strongest: A — the only one that answers everything asked (evidenced strength, "pass on the state, not the idea", ordered next steps tied to the brief's numbers); B a close second for the hardware-math catch. Blind spot: D — bull case with no mention of the untested knife detector, consent/erasure, website claims or the lack of a signature; never gives an invest/partner/pass verdict. All missed: the shoplifting research — rigorous in the lab, permissive on the homepage.

**Review 4.** Strongest: B — the hardware contradiction is a falsifiable business-model break, not just a values objection; also covers moat and pricing. Blind spot: D — the only response that never mentions the website claims; skips knife validation and consent. All missed: the shoplifting research; whether this is venture-scale or a good regional integrator business; and that Hikvision/Dahua already bundle free analytics, undercutting a paid one-off model.

**Review 5.** Strongest: B — original synthesis (the hardware math), plus competitor and customer-safety lenses. Blind spot: D — total; its "one GPU box" moat is the claim B shows breaks. All missed: the shoplifting research; currency and margin risk — one-off pricing that bundles USD-priced GPU hardware, invoiced in Egypt in EGP.

---

## Chairman's verdict (as delivered; the head-count was corrected in chat)

### Where the Council Agrees

- Four of five advisors pass on investing today — and it's not about the tech. Your website still carries claims your own internal check found false ("every detection checked by a person," "full audit trail," "right to be forgotten," "208 cameras on one site"), and you left them up. That reads as a decision, made on the page a worried parent reads first.
- Knife detection has a measured false-alarm rate (about once every 160 seconds on clean footage) and zero measurement of whether it catches a real knife.
- Nothing is signed. "Talks only" isn't traction.
- No consent or legal work has started for scanning children's faces — a hard blocker, not a line item.
- Your engineering discipline (the four-file feature pattern, the tests, the honest health page) is real. Marketing got ahead of the product — you didn't fail to build, you failed to wait.

### Where the Council Clashes

- The Expansionist makes a real bull case: your architecture is a platform, "Ask" could outgrow schools, Arabic and on-prem give you a regional head start, and one-off pricing wastes recurring revenue. Every peer review flagged the same hole in it: it never mentions the website, the unvalidated knife detector, or the consent gap — the facts the other four call disqualifying.
- On moat: the Contrarian says you have none, copyable by a funded competitor in a quarter. The Expansionist says geography and language protect you for years. Reviewers note both miss the likelier threat — a local integrator already in these schools, or Hikvision/Dahua bundling similar analytics free.
- On next step: the Contrarian and Outsider land on a flat pass. The Executor would partner narrowly, to help land one pilot, nothing more. The First Principles Thinker won't even answer as an investor — it asks whether you'll tell a school board "we don't know" as honestly as your own code already tells you.

### Blind Spots the Council Caught

- Every peer review caught the same gap in the Expansionist's case — the most consistent finding of the round.
- All five advisors missed something that helps you: you tested shoplifting detection, found it wasn't good enough, and killed it rather than ship it. That's real evidence you don't ship what doesn't measure up, and nobody weighed it against the website problem.
- Nobody flagged that "Ask" sends query text about children to Gemini's free tier, under terms letting Google use it — a second privacy exposure, separate from face data.
- Nobody asked whether this is a venture-scale company or a strong regional integrator business, and nobody weighed invoicing USD-priced hardware in EGP.

### The Recommendation

The sharks pass today — four outright, one reframes the question, but none say invest. Not on the idea. On the state. As a customer, they wouldn't buy yet: the feature that justifies "guard," knife detection, is unproven, and your site overclaims what's shipped. As a competitor, they're not worried: the moat is thin and copyable, though Arabic and on-prem are worth defending properly. As a partner, the most on offer is narrow: help you land one pilot, nothing more, until the trust problem is fixed, not just noticed.

What flips them to yes: a website that only says what's true, a signed pilot sized to what you can run — 16 cameras, not 208 — a lawyer on child consent, and every unmeasured claim, knife detection and people counting, kept out of customer conversations until it has numbers behind it.

### The One Thing to Do First

Fix the website today. Pull down or correct the exact lines your own internal check already flagged as false. It's the step nearly every advisor named first, it takes an afternoon, and until it's true, nothing else you show a shark, a school, or a parent will be believed.

**Correction made in chat:** three advisors passed outright (Contrarian, Outsider, Executor, who would still partner on one pilot); the First Principles Thinker refused to judge it as an investment; the Expansionist argued the upside and gave no verdict. None said invest.
