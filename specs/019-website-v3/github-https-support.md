# Message for GitHub Support: the HTTPS certificate is stuck

**Where to send it:** https://support.github.com → Contact support → GitHub Pages. If the
account has no support plan, post it in https://github.com/orgs/community/discussions
under the "Pages" category.

**Before sending:** open https://github.com/Fo2sh-61/vision-guard-website/settings/pages
while signed in. Opening that page makes GitHub check again. If a "Check again" link
shows beside the domain, click it. **Do not click "Remove"**: each remove/re-add restarts
the queue. Send the message below if nothing changes within about two hours.

---

**Title:** Pages HTTPS certificate stuck at "dns_changed" for www.vision-guard.org — DNS verified correct

**Body:**

Repository: Fo2sh-61/vision-guard-website (public; Pages from branch `main`, root)
Custom domain: www.vision-guard.org (the apex vision-guard.org redirects to it)

The certificate has been in state `dns_changed` ("Detected a change to DNS settings.
Requesting a new certificate.") since 2026-09-27 12:22 UTC and has not moved on.
Certificate Transparency shows no certificate issued for either name, and HTTPS still
serves the `*.github.io` certificate.

Checked on 2026-09-28:

- `/pages/health`: both names `is_valid`, `is_https_eligible`, `caa_error: null`, not
  proxied.
- DNS: apex `A` records are exactly 185.199.108.153–185.199.111.153; `www` is a `CNAME`
  to fo2sh-61.github.io; the apex has no `AAAA` or `CAA`, and `www` inherits github.io's
  CAA, which allows letsencrypt.org.
- DNSSEC is valid: DS 35139 matches the served KSK.
- Answers are identical on Google, Cloudflare, Quad9 and both authoritative servers
  (launch1/launch2.spaceship.net). The zone has not changed since 2026-09-27 07:41 UTC.
- Let's Debug (http-01) passes for both names (runs 3179874 and 3179875). Let's Encrypt
  staging reached GitHub's challenge responder on both names, over IPv4 and IPv6.
- `/.well-known/acme-challenge/` reaches GitHub's responder on both names, with no
  redirect.

History: the domain was first set at 07:02 UTC on 27 Sep, before the last DNS edit at
07:41. It was then changed several times the same day: 07:42, 08:44, 10:24 (apex to www)
and 12:22 (removed and re-added through the API). We think the certificate job stalled
during those changes.

Could you please re-request (reset) the certificate for this Pages site? We will make no
further domain or DNS changes in the meantime.

---

**Once it works:** the state reads `approved`. Then tick "Enforce HTTPS" on the same
settings page, or ask Claude to switch it on.
