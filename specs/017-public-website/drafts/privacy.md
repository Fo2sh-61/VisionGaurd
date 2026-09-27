# Privacy Policy

> **Draft for Mohamed to approve (27 September 2026). Not legal advice. Not on the website.**

**To confirm before publishing:**

- [ ] Governing law / jurisdiction for this policy — not set anywhere in the repo; needs the owner or a lawyer to choose.
- [ ] A named data-protection contact and registered company address — not present in the repo; currently only the sales contact card exists.
- [ ] How long a website contact-form enquiry is kept before deletion — no retention period is set for the FormSubmit/ImprovMX/Gmail chain; needs an owner decision.
- [ ] The contact-form paragraph currently says plainly that delivery is not guaranteed yet, because FormSubmit is not activated and ImprovMX forwarding is not live (STATUS.md, 27 Sep 2026). Once both go live, that paragraph should be revisited and likely simplified.
- [ ] Whether/when the audit-trail persistence work (making the action log survive a restart) will ship, so this page can say retention is fixed rather than 'planned'.
- [ ] Whether attendance/sighting records should get a retention period, since none exists today — an owner decision, not a code gap to silently fill in.
- [ ] Legal review of the whole draft before publishing, including whether Gemini's free-tier data terms need a more formal disclosure or a link to Google's own policy.

Draft for the owner to review — plain language, not legal advice, and not yet published. It covers two separate things: this website (vision-guard.org), and the VisionGuard product once it is running at a customer's site. VisionGuard is a company based in Egypt. Contact: sales@vision-guard.org, +20 100 253 5081 (call or WhatsApp), Sunday–Thursday, 9:00–18:00.

## Part 1 — This website

vision-guard.org is a static website: a handful of plain pages and two pictures, with no server of its own. It is hosted on GitHub Pages, and it uses two outside services besides that: Google Fonts, to load its typefaces, and FormSubmit, to deliver its two forms. Visiting the site does not set a single cookie, and nothing on it tracks or analyses visitors.

When you use the 'Contact us' form, we collect what you type: your name, work email, company, phone (optional), the type of site you have, roughly how many cameras, and your message. When you use 'Ask us a question' in the Help centre, we collect your name, email, the topic you pick and your question. On both forms, a hidden field catches automated spam and collects nothing about you.

When you press send, FormSubmit (formsubmit.co) sends your message toward sales@vision-guard.org (the contact form) or support@vision-guard.org (the Help centre form), each set up to forward to our team's Gmail inbox through ImprovMX. That forwarding is still being switched on: as of today a message is not guaranteed to reach us, and if the page cannot confirm it was sent, it says so plainly and gives you our email and phone number instead. The website itself keeps no copy of what you type, either way.

- Hosting: GitHub Pages. Like any web host, GitHub sees the IP address of every visitor.
- Fonts: loaded live from Google Fonts, so your browser also contacts Google when the page loads.
- Cookies and analytics: none. The site sets no cookies and runs no tracking of any kind.
- How long we keep an enquiry: not yet decided.
- To ask us to delete an enquiry you sent, email or call/WhatsApp us using the details above.

## Part 2 — The VisionGuard product, at your site

VisionGuard runs on a computer at the customer's own site — a school, factory, hospital or office. The customer is in charge of the footage and the records their own installation produces: camera video, enrolled face data, attendance and sighting logs, restricted-zone and knife-detection incidents, vehicle-gate passes and plate images, and the record of who searched or changed what. All of it sits in a database and files on that machine. VisionGuard does not hold a copy anywhere else — with two exceptions, below.

If the site includes people who are minors — for example, a school — the customer is responsible for having a lawful basis to process their biometric data (face recognition). VisionGuard does not arrange this on the customer's behalf; today this is unresolved and stands in the way of any real deployment.

- What leaves the site, exception 1 — Ask: when someone asks Ask a question, names and vehicle plates in it are masked on site first. The masked question is sent to Google's Gemini, on its free tier, to work out what is being asked. Google's free-tier terms let Google use what is submitted, and let human reviewers read it. A word Ask does not recognise — which can include a person's actual name as typed — is sent exactly as typed, unmasked; connecting a paid Gemini account would turn this off, and has not been done.
- What leaves the site, exception 2 — email alerts: a restricted-zone, knife or vehicle-gate alert is emailed, through Gmail, to the people the customer's own administrator has chosen. The message carries facts only — what happened, where, when, how sure the system is, and who decided — never a name, a face or a picture, and never an attachment.
- Knife-detection videos are deleted automatically after 30 days. The written record that an alert happened is kept permanently and, by design, can never be deleted — even a confirmed false alarm stays in the history.
- Restricted-zone recordings: only the three most recent clips per camera are kept — the oldest is deleted to make room for a new one.
- Vehicle-gate photos and plate close-ups are deleted automatically after 30 days; the record that a car passed is kept permanently. An administrator can delete one pass by hand — its photo, plate close-up and row all go — and the log entry that someone deleted it stays.
- Attendance and general sightings (arrivals, headcounts) keep no video, and today have no set deletion schedule.
- Removing a person: an administrator can remove someone from the People page. Their face data is deleted and VisionGuard stops recognising them from the next camera frame — no restart needed. Their past sightings are kept, and are not shown on any screen, until a full erasure feature is built — this is planned but not done yet.
- The log of who searched or changed what is written before the action it records. Today it lives in the program's memory rather than the database, so it can be lost if the computer restarts; making it durable is planned but not built yet.

## Questions or a request

For anything about this policy, or about data this website holds, contact us at support@vision-guard.org or +20 100 253 5081 (call or WhatsApp), Sunday–Thursday, 9:00–18:00.

If your data is held inside a VisionGuard installation — for example, you are an employee, student or visitor at a customer's site — that customer controls it, and is the right place to ask first.

*Last updated 27 September 2026*
