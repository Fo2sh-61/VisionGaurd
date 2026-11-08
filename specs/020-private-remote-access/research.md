# Research: Private remote access

**Spec**: [spec.md](spec.md) · **Researched**: 17 Oct 2026. Every fact below was read on the
vendor's own page that day, then re-checked by a second reader who tried to disprove it, and
the disputed ones were read a third time by hand. Vendors change plans without notice:
re-check before sign-up.

Legend:
- **✔ verified**: read on the vendor's own page today.
- **≈ vendor claim or inference**: the vendor says so, or it follows from what the vendor
  says, but nobody independent has proved it.
- **? unverified**: no official source found. It must be tested (drill number given) or
  asked.

## Owner decisions that shape this research (17 Oct 2026)

1. Keep the private-VPN model. No public URL with a login.
2. **No card, ever.** A service that asks for a bank or credit card at sign-up can only be a
   fallback, even if it is never charged.
3. Size: 1–5 people per factory, 1–3 factories in the first year.
4. Away from the factory: alerts, snapshots and clips first; live view limited.
5. Self sign-up stays; no 6-digit sign-in code for now; alerts go to the phone app.

## R1: Which mesh VPN

### Decision

**Primary: NetBird Cloud, Free plan, one account per factory.**
**Fallbacks**, in order: NetBird self-hosted, then Cloudflare Zero Trust, then an Oracle
VM relay. Each one breaks an owner rule (a domain and public server, or a card), so each
needs the owner's say-so before use. See plan.md, "Fallbacks".

### Decision table

| | **NetBird Cloud Free** | **Cloudflare Zero Trust Free** | **Twingate Starter** |
|---|---|---|---|
| Price | €0 ✔ | $0 ✔ | $0 ✔ |
| Card at sign-up | **? not stated anywhere official.** Payment options (cards, Google Pay, Link) are described only for paid plans ✔. Only the sign-up screen settles it, and we may not sign up → owner checklist step A3 stops if a card is asked | **Required, not charged** ✔ ("this step is still needed but you will not be charged") | ? not stated |
| Business use | **? not stated either way.** Terms are written for "customers as business persons" (§1) ✔. They forbid reselling or "commercially exploit[ing] the Software" (§8) ✔, which is not using it for your own console ≈. Free is described as for "individuals or small teams" ✔ → **ask NetBird in writing** (checklist A1) | No restriction found ✔ | Starter is "for personal projects and small startups"; only the Home plan says non-commercial ✔. Terms not read ? |
| Users | 5 ✔ | 50 ✔ | 5 ✔ |
| Devices | 100 machines ✔ | not capped on the plans page ✔ | "5 per user" ≈ (table hard to read) |
| Workstation side on Windows | Native Windows client; silent install (`/S` or MSI `/quiet`) then `netbird up --setup-key` ✔ | `cloudflared` on Windows ≈ (not re-read) | **No native Windows connector**: "a container or a Linux systemd service" ✔. Twingate advises a Linux VM on Hyper-V for Windows ✔ |
| Android | Official app; joins with SSO or a setup key ✔ | WARP app ✔ | Official app ✔ |
| Path | Direct first (LAN first, then across the internet), relay on TCP 443 last ✔ | Always through Cloudflare ✔ | Direct first, relay as backup ≈ |
| What the vendor can see | WireGuard-encrypted on the device; "the relay forwards packets it cannot read" ≈. The vendor sees device names, private and public addresses, online times, and the owner's sign-in email | With TLS decryption off, Gateway cannot see "the full URL, headers, and request body" ✔. It still sees addresses, ports and the site name ≈ | "cannot be decrypted by any third party (including Twingate)" ≈ |
| Vendor down | Signal "steps out" once a tunnel is up ✔; management-down behaviour **? (drill D6)** | Remote access stops ≈ | ? |
| Re-sign-in | SSO devices expire (24 h default); **setup-key devices are never affected** ✔ | session policy | session policy |
| New-device approval | Business plan only ✔ (not on Free) | n/a | n/a |
| Activity log of devices added or removed | **? conflicting**: docs say on "for every network", the pricing page lists it under Team. Not promised; the owner keeps his own device list | yes ≈ | yes ≈ |

### Why NetBird

- The only candidate that is $0, has no card step that the docs show, does not exclude
  business use, and installs natively on the Windows 11 workstation.
- Peer-to-peer WireGuard means video normally never touches a vendor server. When it is
  relayed, the relay cannot read it ≈.
- 5 users should be enough when only the owner signs in to the dashboard and devices join
  with keys, **if** key-joined devices do not count as users. That is not documented
  (R2, question 2). 100 machines is far more than needed.
- Open source (client BSD-3, server AGPLv3 ✔). If the cloud plan disappears, the same
  clients can point at a self-hosted server (`--management-url`) without redesigning the
  site.

### Rejected

| Option | Why |
|---|---|
| Cloudflare Zero Trust Free | Card at sign-up ✔ (decision 2). Every packet goes through Cloudflare. Fallback 2 only |
| Twingate Starter | No native Windows connector ✔. A Linux VM or Docker on a 24/7 workstation that must come back alone after a power cut is fragile |
| Tailscale Free (Personal) | "only suitable for non-commercial use" ✔ |
| ZeroTier Free | "testing, non-commercial, and personal use" ✔ |
| frp, Capacitor `server.url`, paid servers | Ruled out in the brief |
| Oracle Always Free VM relay | Card needed ("a credit card", "most users") ✔. "Idle Always Free compute instances may be reclaimed" ✔. Fallback 3 only |
| Cloudflare public Tunnel | Public URL (decision 1); Cloudflare terminates it |

## R2: One account per factory, and who owns it

- **Decision**: one NetBird account per factory. The owner creates it while signed in with a
  new Google account made for that factory (e.g. `vg.<factory>@gmail.com`), with Google's
  2-Step Verification on. "Social SSO & MFA" is listed on Free ✔. The owner keeps the
  password and the backup codes.
- **Why**:
  - The 5-user cap is per account, so one account per factory keeps each inside it.
  - One factory's devices can never reach another's.
  - Handing a factory over means handing over one Google account.
- **Users vs devices**: devices that join with a setup key need no user sign-in ✔. Whether
  they count against the 5 *users* is **? not documented**. Even if they did, 1–5 people
  with one or two devices each could pass 5, so this is question 2 to ask NetBird
  (checklist A1). The owner as the only dashboard user is the plan either way.

## R3: Data path and what keeps working

| Situation | Console on the LAN | Detection and recording | Remote access |
|---|---|---|---|
| Normal | ✔ | ✔ | ✔ direct or relayed |
| Factory internet down | ✔ (the LAN needs no internet) | ✔ | ✗ nothing can reach the site |
| NetBird cloud down | ✔ | ✔ | Tunnels already up should keep working (Signal steps out ✔); a device that was asleep may not reconnect **? D6** |
| Workstation reboot | ✔ once the VisionGuard service is back | ✔ | ✔ once the NetBird service is back **? D5** |

The LAN console never goes through NetBird: office PCs use the workstation's fixed LAN
address. Two NetBird devices on the same LAN connect straight over the LAN ("Host to Host",
tried first ✔), so a phone on the factory Wi-Fi does not send video out and back.

## R4: Workstation setup

- **Service**: NetBird's background service "starts independently" of its window ✔. Windows
  services set to start automatically run "even when no user is logged on" ✔. That NetBird's
  service is set to start automatically at boot and rejoins after a power cut is **? drill
  D5**.
- **Unattended join**: silent install, then `netbird up --setup-key <KEY>` ✔. A one-off key
  "can be used only once to authenticate a single machine" ✔. Keys from the Add Peer screen
  are one-off and expire after 24 hours ✔. A device already joined stays joined when its key
  expires ✔.
- **Removing a device**: delete the peer. "Its address is released immediately" ✔. How fast
  the tunnel drops, and whether that device could rejoin without a new key, is **? drill D7**.
  The key was one-off and has expired, so it cannot be reused.
- **Fixed LAN address**: a DHCP reservation on the factory router, or a fixed address on the
  workstation. Owner step.
- **Firewall**: `LocalSubnet` is a valid `-RemoteAddress` keyword and CIDR ranges are
  accepted ✔. A single list mixing both is not shown in Microsoft's docs, so the script makes
  **two rules** (one `LocalSubnet`, one `100.64.0.0/10`), each `-Profile Any`. The
  `100.64.0.0/10` rule is also limited to the NetBird adapter (`-InterfaceAlias`), because
  that range is also used by some internet providers. NetBird's own page names the adapter
  `wt0` ✔ (it does not say so for Windows specifically), so the script finds the adapter by
  its 100.64 address rather than by name. Which network
  profile Windows gives the NetBird adapter is **? undocumented**; `-Profile Any` makes it
  not matter.
- **NetBird policy**: access policies on Free can limit by group, protocol and port ✔
  (port rules carry no plan label in the docs ≈). The default policy "should be removed as
  soon as you're ready" ✔, **after** the new policy exists, or all traffic stops ✔.
- **Status for System Health**: the client source has JSON fields `management`, `signal`,
  `peers`, `netbirdIp`, `fqdn`, `daemonStatus` ✔ (source code, not a documented promise).
  Pin the client version and test the parsing (tasks T040–T041).

## R5: The address people type, HTTPS and "Install app"

- **Names do not resolve by default.** "On macOS, Windows, and mobile without nameservers …
  peer domain names like `my-server.netbird.cloud` won't resolve" ✔. Making them resolve
  needs a nameserver set in the account, and on Android "Custom DNS resolution requires
  disabling Private DNS" ✔, which is a phone-wide setting.
- **Decision: people type the workstation's NetBird address** (e.g. `https://100.81.4.7`),
  and the site certificate covers it.
  - Why: no DNS settings on any phone, nothing to break.
  - Cost: the address is not documented as fixed for life ?. NetBird tells you to use names
    or groups because "changing the network range re-allocates every peer's IP" ✔. The
    owner therefore never changes the range and never deletes the workstation's peer. If
    either happens, the certificate is re-made on the workstation (devices keep trusting
    the site's root) and each device's app shortcut is re-added. Drill D5 also checks that
    the address is the same after a reboot.
- **Certificate**: spec 016's site certificate must list the LAN address and the NetBird
  address (plan C).
- **Windows trust**: Chrome uses certificates in the machine's "Trusted Root Certification
  Authorities" store ✔. Edge is built on the same engine ≈. Test both (drill D1-PC).
- **Android trust**: no official page found saying Chrome trusts a user-installed CA without
  warnings **? drill D1**. Chrome has an enterprise policy about "user-added TLS
  certificates from platform trust stores" ✔, so the mechanism exists. The menu path varies
  by phone: the Pixel help page shows "Encryption & credentials > Install a certificate" ✔.
  The checklist tells the owner to search Settings for "CA certificate".
- **Install as app**:
  - Chrome needs HTTPS plus a manifest with name or short_name, 192 px and 512 px icons,
    start_url and display ✔.
  - A service worker is no longer needed for the menu's "Install app" ✔. The automatic
    install prompt still wants a `fetch` handler ✔ (Dec 2023 post).
  - On Android, the installed app (WebAPK) is "generated by the Chrome server" ✔. Whether
    that works for an address only reachable over the VPN is **? drill D1**. If not, the
    phone gets a home-screen shortcut, which opens the same way.
- **What exists in the code**: no manifest, no service worker, no PNG icons in either app
  (plan, "What exists today").

## R6: Live video from outside

- How video works today, read from the code: see plan.md, "What exists today".
- Browsers commonly allow "6 parallel connections" per host over HTTP/1.1 ✔ (MDN, typical
  not guaranteed). One HTTP/2 connection "can contain multiple concurrently open streams" ✔
  (RFC 9113).
- Factory upload speed: unknown per site. Remote limits are sized so that one person away
  needs about 2–3 Mbit/s (estimate; drill D10 measures).

## R7: Alerts while away

- **Web Push with VAPID keys made on the workstation**: "You no longer need a Firebase
  project" ✔ (Chrome, 2016, still the vendor statement). So no Google or Firebase account
  ≈.
- **Encryption**: RFC 8291 protects the message between the workstation and the phone. "The
  timing and length of communication cannot be hidden from the push service" ✔. So Google's
  push service sees that a message of some size reached a phone at a time, not what it says.
  It also sees, from how Web Push works ≈:
  - the workstation's public internet address;
  - the phone's push address, which stays the same for that phone;
  - the contact address in the VAPID signature, which is the factory's own Google address,
    never a personal one.
- **App closed**: the service worker "will be started as necessary to handle incoming push
  messages" ✔ (MDN, not Google). Battery savers or a force-stop can still block it **?
  drill D9**.
- **Outbound internet**: both the workstation and the phone need internet to reach the push
  service. No internet at the factory means no notifications; that is logged (P9-FR-106).
- **Gmail**: unchanged and optional. Email already carries no names, faces or pictures (spec
  013's `ALLOWED_FACTS`). A strict factory switches email off.

## Questions for NetBird (owner sends, checklist A1)

1. May a company use the Free plan for its own internal access to one site, at no charge?
2. Do devices joined with a setup key count against the 5-user limit, or only against the
   100 machines?
3. Does Free sign-up ever ask for a payment method?
4. May one person own up to three Free accounts, one per factory, each with its own email?

No real device joins until the answers are in. If the answer to 1 or 4 is no, the owner
chooses a fallback (plan.md). If the answer to 2 is yes, each person gets one device, or the
owner decides about a paid plan.

## Sources (all read 17 Oct 2026)

- NetBird pricing: https://netbird.io/pricing
- NetBird Terms of Service: https://netbird.io/terms (no version date on the page)
- NetBird plans and billing: https://docs.netbird.io/manage/settings/plans-and-billing
- NetBird setup keys: https://docs.netbird.io/manage/peers/register-machines-using-setup-keys (updated 19 Aug 2026)
- NetBird periodic authentication: https://docs.netbird.io/manage/settings/enforce-periodic-user-authentication
- NetBird peer approval: https://docs.netbird.io/manage/peers/approve-peers
- NetBird access control: https://docs.netbird.io/manage/access-control
- NetBird activity: https://docs.netbird.io/manage/activity
- NetBird how it works: https://docs.netbird.io/about-netbird/how-netbird-works (updated 5 Oct 2026)
- NetBird NAT and connectivity: https://docs.netbird.io/about-netbird/understanding-nat-and-connectivity (updated 12 Jun 2026)
- NetBird relayed connections: https://docs.netbird.io/help/troubleshooting-relayed-connections
- NetBird ports and firewalls: https://docs.netbird.io/about-netbird/ports-and-firewalls
- NetBird network settings: https://docs.netbird.io/manage/settings/networks (updated 19 Aug 2026)
- NetBird DNS: https://docs.netbird.io/manage/dns (updated 16 Oct 2026)
- NetBird Windows install: https://docs.netbird.io/get-started/install/windows (updated 28 Sep 2026)
- NetBird Android install: https://docs.netbird.io/get-started/install/android
- NetBird self-hosted quickstart: https://docs.netbird.io/selfhosted/selfhosted-quickstart (updated 14 Oct 2026)
- NetBird licence: https://raw.githubusercontent.com/netbirdio/netbird/main/LICENSE
- NetBird status fields: https://raw.githubusercontent.com/netbirdio/netbird/main/client/status/status.go
- Cloudflare One setup: https://developers.cloudflare.com/cloudflare-one/setup/
- Cloudflare TLS decryption: https://developers.cloudflare.com/cloudflare-one/traffic-policies/http-policies/tls-decryption/
- Cloudflare Zero Trust plans: https://www.cloudflare.com/plans/zero-trust-services/
- Twingate pricing: https://www.twingate.com/pricing
- Twingate connectors: https://www.twingate.com/docs/connectors
- Twingate encryption: https://www.twingate.com/docs/how-encryption-works-in-twingate
- Tailscale free plans: https://tailscale.com/docs/account/manage-plans/free-plans-discounts.md
- ZeroTier pricing: https://docs.zerotier.com/pricing
- Oracle Always Free: https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm and https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm
- Chrome install criteria: https://developer.chrome.com/blog/update-install-criteria and https://web.dev/articles/install-criteria
- WebAPK: https://chromium.googlesource.com/chromium/src/+/main/chrome/android/webapk/README.md
- Chrome root store FAQ (Windows trust): https://chromium.googlesource.com/chromium/src/+/main/net/data/ssl/chrome_root_store/faq.md
- Chrome policy, user-added certificates: https://chromeenterprise.google/policies/ca-platform-integration-enabled/
- Pixel certificates help: https://support.google.com/pixelphone/answer/2844832
- Web Push without Firebase: https://developer.chrome.com/blog/web-push-interop-wins
- RFC 8291 Web Push encryption: https://www.rfc-editor.org/rfc/rfc8291
- MDN Push API: https://developer.mozilla.org/en-US/docs/Web/API/Push_API
- MDN HTTP/1.x connections: https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Connection_management_in_HTTP_1.x
- Microsoft New-NetFirewallRule: https://learn.microsoft.com/en-us/powershell/module/netsecurity/new-netfirewallrule
- Microsoft services: https://learn.microsoft.com/en-us/windows/win32/services/services
