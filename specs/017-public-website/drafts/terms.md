# Terms of service

> **Draft for Mohamed to approve (27 September 2026). Not legal advice. Not on the website.**

**To confirm before publishing:**

- [ ] Governing law and jurisdiction for disputes over these terms — not stated anywhere in the repo; needs a legal decision.
- [ ] Any liability cap or disclaimer limit (e.g. 'liability limited to fees paid') — none exists today; needs the owner/lawyer to set one or confirm none is wanted.
- [ ] VisionGuard's registered company name, legal form and registered address in Egypt — not in the codebase; needed for a real terms page.
- [ ] Pricing, licence terms and contract terms for actually buying/using the product (as opposed to browsing the website) — out of scope for this draft and not found in STATUS.md; a lawyer or Mohamed should supply them if the page should cover them.
- [ ] Whether this draft should also mention data-protection/consent obligations for biometric data of minors — the repo's own documents disagree on this: STATUS.md's 'Blocked on the owner' list still names it as a blocker with no date attached, but docs/PLAN.md §9 records it as 'ANSWERED 20 Aug 2026 — permission granted... No longer gates deployment.' Mohamed should say which is current before this page (or the Privacy Policy) states anything about it.

This is a draft, written in plain language, for the owner to review before it is published. It is not legal advice. It sets out the terms for using this website and gives an honest, short description of what VisionGuard the product does and does not promise. Where a term needs a lawyer's or the owner's decision — price, licence terms, liability limits, governing law — it is flagged below rather than invented.

## Using this website

This website (vision-guard.org) is run by VisionGuard, based in Egypt. It describes the product and lets you get in touch with our sales team. By using it, you agree to these terms.

The site is informational. We give it in good faith and keep it up to date as best we can, but we make no warranty that it is complete, accurate or error-free at every moment, and it can change or go offline without notice.

The site is static: it is hosted on GitHub Pages, sets no cookies of its own, and runs no analytics or tracking. Its pages load fonts from Google Fonts, which means your browser contacts Google's servers to fetch them; and GitHub, as the host, receives visitors' IP addresses the way any web host does. Nothing you type on the site is stored by the site itself.

## The contact form

The contact form sends your name, work email, company, phone (if you give one), type of site, number of cameras and message to FormSubmit (formsubmit.co), a third-party service, which emails them on to sales@vision-guard.org. That address is forwarded by ImprovMX to our team's inbox. A hidden field on the form is there only to catch automated spam.

Send the form only if you are comfortable with that message passing through FormSubmit on its way to us. We use what you send only to reply to your enquiry.

## Links to other sites

Where this site links to somewhere else — a form provider, a map, a social page — that destination has its own terms and its own privacy practices, which we do not control and are not responsible for.

## What the product is

VisionGuard is camera software that runs on a computer at your own site. It watches camera feeds for the features you turn on — for example counting people, recognising enrolled faces, spotting a restricted-zone entry, or flagging a knife — and keeps a record of what it finds, with video for the features built to keep it.

It is a tool for the people who run your site, not a replacement for them. Every detection is there to help a person decide, not to decide on its own:

- A knife detection always waits for a person to confirm it or mark it a false alarm before it is treated as real. The system itself never locks a door, calls anyone, or takes any action on its own.
- People counts can be wrong. On the one camera where this is measured today, a single person is usually counted as more than one, and an empty room often reads as occupied when it is not.
- Face recognition can misidentify someone or fail to recognise them. A name shown on screen is the system's best match, not a certified identification.
- Ask, the question-answering tool, sends your question to Google's Gemini free tier, with names and vehicle plates in it masked to a placeholder before anything leaves your site. Google's free-tier terms let Google use what is submitted and let human reviewers read it. A word the system does not recognise as a name or plate is sent to Gemini as you typed it.

## No warranty

The product is provided to help staff notice things faster; it does not guarantee that every event will be caught, correctly counted, or correctly identified. Decisions that affect a person's safety, employment or legal standing should always be made by a person, using the system's output as one input among others, not as the final word.

## Changes to these terms

We may update this page as the site or the product changes. The date at the top (once published) will show when it was last revised.

## Contact

Questions about these terms: sales@vision-guard.org, or +20 100 253 5081 (also WhatsApp), Sunday to Thursday, 9:00 to 18:00.

*Last updated 27 September 2026*
