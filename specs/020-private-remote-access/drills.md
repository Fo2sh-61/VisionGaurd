# Drills: private remote access

What each drill on real devices showed (steps and pass rules: `plan.md`, Test plan). One
row per run; a failure stays here with its fix.

Setup: the stand-in workstation is Mohamed's laptop (Wi-Fi, Public network), VisionGuard
from Setup v0.16.0-setup6, later -setup7; NetBird address 100.121.190.241. The phone is
Mohamed's Samsung Android phone (`operator-01`), group `operators`.

| Drill | Date | Device | Result | Notes |
|---|---|---|---|---|
| D1 Phone outside | 20 Oct 2026 | Samsung Android phone, Samsung Internet 30, mobile data, NetBird on | **Pass, after fixes** | See below |
| D1-PC Laptop outside | | remote Windows PC | not run | |
| D2 Not enrolled | | | not run | |
| D3 Office, no internet | | | not run | |
| D4 Internet back | | | not run | |
| D5 Power cut | | | not run | VisionGuard Control's start-with-Windows switch is off on the laptop (since 19 Oct); switch it on first |
| D6 Vendor unreachable | | | not run | |
| D7 Device removed | | | not run | |
| D8 Lockout | | | not run | use a throwaway account, never the owner's |
| D9 Notification | | | not run | the phone app is installed from Samsung Internet, so its push goes through that browser |
| D10 Video | | | not run | also measures the live view at 720 px, 10/s (plan.md, the figure is still an estimate) |
| D11 Nothing else reachable | | | not run | |
| D12 Forged address | | | not run | |

## D1, 20 Oct 2026

- **Sign-in page, no warning: pass.** `https://100.121.190.241:8443` opened the phone
  app's sign-in page with no certificate warning, after the root `.crt` was installed as
  a CA certificate. Time to open not measured (SC-101's 10 s).
- **NetBird off, app closed: pass.** With VisionGuard swiped away and NetBird off, opening
  it from its icon showed the plain "VisionGuard cannot be reached right now." page, not
  an old copy. With the app still open in the background it shows the screen as it was
  (scenario 11, not 10): the red banner then comes after 5 s without an answer.
- The link was **relayed** (NetBird's relay in Madrid), not direct; the laptop's own
  NetBird firewall rules were in place, so the phone network is the likely reason.
- Enrolment time (SC-108) and the NetBird app's name for its setup-key menu were not
  recorded; owner-checklist D4.1 is still unchecked.

Found on the way, each fixed:

1. "Site can't be reached" at first: VisionGuard itself had been stopped at 12:25 with
   VisionGuard Control's "Stop VisionGuard and exit". Not a remote-access fault; started
   again.
2. The "Cannot reach the site" banner flashed on and off: one lost request over the relay
   set it. Now 5 s with no answer (4335279).
3. The camera grid was one picture every 2 s, too slow for Mohamed: remote defaults raised
   to a tile every 0.5 s and a live view 720 px at 10/s (bc4311a). He wants 15/s or more on
   every visible tile; that is real video, spec 021.
4. `100.121.190.241:8443` typed without `https://` gave "400 Bad Request": the front now
   redirects plain HTTP on 443 and 8443 to HTTPS (next Setup after -setup7).
5. Chrome's **Install** showed "installing…" and then made nothing for this private
   address. Samsung Internet's **Add page to → Home screen** made an app that opens full
   screen from its own icon. Checklist D7–D8 now say so.
