# Feature Specification: Private remote access

**Feature Branch**: `remote-access` (spec directory `020-private-remote-access`)
**Created**: 17 Oct 2026
**Status**: Draft — plan only, nothing built
**Input**: Owner brief of 17 Oct 2026: reach the VisionGuard console from outside the
workplace, in real time, on a small set of enrolled Windows PCs and Android phones; everyone
else must be unable to reach it; $0; factory data stays on the site workstation; the same
design for the pilot and every later factory.

**Settled with Mohamed on 17 Oct 2026**

1. A private network (a VPN) limited to enrolled devices. No public address, no gateway
   server.
2. No bank or credit card at sign-up, ever. A service that asks for one is a fallback only.
3. 1–5 people per factory, 1–3 factories in the first year.
4. Away from the factory: alerts, snapshots and clips come first; live view is limited.
5. Self sign-up stays as it is **on the factory network**. Only the owner enrols devices, in
   person. After review, self sign-up is **refused from outside**, so an enrolled device
   alone never gives access without a real account's password.
6. No 6-digit sign-in code for now. Outside access needs an enrolled device **and** a
   password; a per-account lockout is added.
7. This spec depends on spec 016 (HTTPS, Windows service, the apps served by the
   workstation) and builds none of it again.
8. Away-from-site alerts go to the phone app as notifications with brief details; the person
   opens the app for the rest. Email is optional per site.

Chosen service (see [research.md](research.md)): NetBird Cloud, Free plan, one account per
factory. This is a plan decision, not a requirement. The requirements below hold for any
service that meets them.

## Why this feature *(mandatory)*

Today VisionGuard can only be opened on the workstation itself, and spec 016 will extend that
to the factory's own network. The owner and operators also need it when they are away — on
the road, at home, at another site — to see what an alert was about and to glance at a
camera. Opening a port on the factory router or renting a server would cost money and expose
the console to the whole internet. After this feature, an enrolled laptop or phone opens the
console from anywhere as if it were in the office, and no other device can even find it.

## User Scenarios & Testing *(mandatory)*

### Primary story

The owner sets up a factory once: one free private-network account for that factory, the
workstation joined to it, and the site certificate covering the workstation's private
address. For each operator he joins their laptop or phone to the network himself, installs
the site's root certificate on it, and installs the VisionGuard app from the browser. From
then on the operator, anywhere with internet, taps the app and gets the console, signs in
with their own password, sees alerts and clips in full and a camera or two live at reduced
quality. A notification on the phone says "Possible knife — Gate 2 — 14:05"; tapping it
opens that entry. When a phone is lost, the owner removes it from the network and disables
that person's account in a few minutes; the phone loses access within 2 minutes of the
removal.

**Acceptance scenarios**

*Only enrolled devices, from anywhere*

1. **Given** an enrolled phone on mobile data with Wi-Fi off, **When** the operator taps the
   VisionGuard app, **Then** the console opens over HTTPS with no certificate warning and asks
   them to sign in.
2. **Given** a phone or PC that is not enrolled, **When** it tries the workstation's private
   address or the factory's public address from outside, **Then** it gets no answer at all —
   no page, no sign-in form.
3. **Given** an enrolled phone, **When** it tries any port on the workstation other than the
   console's, tries another enrolled device, or tries another factory's workstation, **Then**
   the connection is refused.
4. **Given** an office laptop on the factory network that is not enrolled, **When** it opens
   the workstation's LAN address, **Then** the console works, with no internet and no VPN
   service in the path.

*When something breaks*

5. **Given** the factory internet is unplugged, **When** an operator in the office uses the
   console and someone walks past a camera, **Then** the console, detection and recording
   carry on as normal; only remote access stops.
6. **Given** the factory internet comes back after 10 minutes, **When** nobody touches the
   workstation, **Then** remote access works again within 5 minutes.
7. **Given** the VPN service's own servers cannot be reached, **When** an operator on the LAN
   uses the console, **Then** nothing on the LAN changes; System Health says remote access is
   not connected to the service, with the reason.
8. **Given** the workstation loses power and comes back, **When** nobody signs in to Windows,
   **Then** remote access works again within 5 minutes of boot, at the same private address.
9. **Given** the owner has removed a phone from the network, **When** that phone tries to
   reach the workstation from outside, **Then** it cannot, within 2 minutes of the removal.
10. **Given** an enrolled phone whose VPN app is switched off or cannot connect, **When** the
    operator opens the VisionGuard app, **Then** it says plainly that it cannot reach the
    site — never yesterday's pages shown as current.
11. **Given** the app is open and the connection drops, **When** a refresh fails, **Then**
    camera tiles stop saying "every 2 s" and show the time of their last picture, and the
    page says it cannot reach the site.

*Video from outside*

12. **Given** an operator connected from outside, **When** they open the cameras page,
    **Then** each camera shows a still picture refreshed about every 2 seconds, labelled with
    how often it refreshes, not "LIVE", and a slowed refresh is never shown as a broken
    camera.
13. **Given** an operator connected from outside, **When** they open a camera's live view,
    **Then** it plays at reduced size and rate, marked as live, reduced for remote use.
14. **Given** an operator connected from outside with two live views open, **When** they open
    a third, **Then** it does not open and they are told to close one first; the workstation
    applies the limit even if the screen is bypassed.
15. **Given** an operator connected from outside, **When** they open a knife entry, a fall or
    a zone breach, **Then** its snapshot and clip play in full.
16. **Given** an operator using the workstation's LAN address, **When** they use any camera
    page, **Then** nothing changes from today. A phone on the factory Wi-Fi that uses the
    private address counts as outside; its LAN-address shortcut gives full video.

*Security*

17. **Given** any account, **When** someone types a wrong password 5 times within 15 minutes,
    **Then** the account is locked for 15 minutes; even the right password is refused during
    that time; more attempts do not extend it; the screen says it is locked and until when;
    the lock is audited with the address the attempts came from.
18. **Given** a request for any camera picture, stream, snapshot or clip with no session,
    **When** it reaches the workstation from the LAN or from outside, **Then** it is refused.
19. **Given** a sign-in from an enrolled phone, **When** the administrator opens the audit,
    **Then** the entry shows the address it came from and that it came through the private
    network.
20. **Given** a disabled account, **When** that person's phone, still enrolled, sends its next
    request, **Then** it is refused (spec 016 P10-FR-016).
21. **Given** an enrolled device outside the factory, **When** it tries to create an account
    with self sign-up, **Then** it is refused with "Sign up on the factory network"; on the
    factory network sign-up works as today.

*Alerts on the phone*

22. **Given** an administrator has switched on phone notifications for knife alerts and for
    this phone, **When** a knife is seen and the phone is locked with the app closed,
    **Then** a notification arrives within 30 seconds saying "Possible knife", the camera and
    the site time, and nothing else.
23. **Given** that notification, **When** the operator taps it, **Then** the app opens on that
    entry, over the private network.
24. **Given** a notification could not be delivered, **When** an administrator opens the alert
    delivery log, **Then** the failure and its reason are listed.
25. **Given** a person turns on notifications on a new phone, **When** the next alert fires,
    **Then** that phone receives nothing until an administrator switches it on, as with a new
    email recipient.
26. **Given** the owner removes a phone from the network and disables the account, or an
    administrator removes just that phone's notifications, **When** the next alert fires,
    **Then** that phone receives nothing.

*Truthful status*

27. **Given** System Health, **When** anyone opens it, **Then** it shows remote access as one
    of: not set up, connected, or not connected (with the reason), checked within the last
    minute and showing when.

*The owner can do it alone*

28. **Given** [owner-checklist.md](owner-checklist.md), **When** the owner follows it with no
    help, **Then** he can create a factory's account, join the workstation, enrol a PC, enrol
    a phone, remove a device, and set up a new factory.

### Edge cases

- **Two factories, one person**: each factory has its own account. A phone joins each
  factory's account separately and reaches **one factory at a time**: it switches the VPN
  app to the other account first. Factory A's devices can never reach factory B.
- **Phone on the factory Wi-Fi**: it uses the same private address as outside; the VPN app
  connects directly over the Wi-Fi, but video is reduced because the address is the private
  one. If the factory internet is down too, or full video is wanted, it uses the LAN-address
  shortcut. Notifications only work from the private-address app.
- **Workstation's private address changes**: this happens only if the owner deletes and
  re-adds the workstation in the VPN service, or changes the service's address range. The
  checklist warns against both. If it happens anyway, System Health warns. The certificate
  is re-made on the workstation and each device's shortcut is re-added; devices keep
  trusting the site's root.
- **Certificate not trusted on a new phone**: the browser warns; the checklist step installs
  the site's root certificate; there is never a plain-HTTP fallback (spec 016).
- **Lockout used as a nuisance**: someone who can reach the sign-in page types wrong
  passwords to lock out an administrator. The lock lifts by itself after 15 minutes and is
  not extended by more attempts. Another administrator can lift it at once, and the owner
  can lift it at the workstation itself. One address that fails on many accounts is slowed
  down too. The audit shows where the attempts came from.
- **The same email typed with spaces or capitals**: it counts as the same account for the
  lockout, exactly as it does for sign-in.
- **Everyone tries live view at once**: each remote account is held to its two live views,
  so the factory's upload is not swamped by one person. A live view that vanished without
  closing (the phone lost signal) frees its place within seconds.
- **The VPN service changes or ends its free plan**: the console and detection keep working
  on the LAN; remote access stops until a fallback in [research.md](research.md) is set up.
- **Notification arrives while the phone is outside the private network**: the notification
  itself still arrives; tapping it opens the app, which says it cannot reach the site until
  the VPN connects.
- **Alerts with nothing to send**: no notification is sent for an event kind the rules do not
  cover; an empty delivery log says "nothing sent yet", never zero.

## Requirements *(mandatory)*

Requirement numbers continue the phases they belong to without reusing spec 016's or spec
013's: **P10-FR-101…** (go live: access, video, security, status) and **P9-FR-101…**
(notifications).

### Reaching the console

- **P10-FR-101**: From outside the factory network, the console and the phone app MUST be
  reachable only from devices the owner has enrolled in that factory's private network. There
  MUST be no public address, no open port on the factory router, and no gateway server.
- **P10-FR-102**: On the factory network, the console MUST be reachable at the workstation's
  fixed LAN address with neither the internet nor the VPN service in the path.
- **P10-FR-103**: Losing the factory internet or the VPN service MUST NOT affect detection,
  recording, the LAN console or anything else that works on site.
- **P10-FR-104**: The VPN client on the workstation MUST start at boot with nobody signed in,
  rejoin by itself after a reboot or power cut, and never need a person to sign in again.
- **P10-FR-105**: The workstation MUST accept console connections only from the factory
  network and from the factory's private network. The engine itself stays reachable only
  from the workstation (spec 016).
- **P10-FR-106**: Inside the private network, enrolled devices MUST be able to reach only the
  workstation's console ports — not each other and not any other port.
- **P10-FR-107**: The site certificate (spec 016 P10-FR-007) MUST also cover the
  workstation's private-network address, so an enrolled device opens the console over HTTPS
  with no warning and with no DNS setting changed on the device. The names and addresses the
  certificate covers MUST come from configuration.
- **P10-FR-108**: The owner MUST be able to remove one device from the private network, after
  which it can no longer reach the workstation from outside.
- **P10-FR-109**: Each factory MUST have its own private-network account, owned by the owner.
  One factory's devices MUST never reach another factory's workstation.
- **P10-FR-110**: Footage, faces, names and records MUST NOT be stored by the VPN service, and
  the console traffic MUST be encrypted end to end so that, according to the service's own
  documentation, it cannot read it. What the service can see MUST be written down in the
  owner checklist, marked as the vendor's claim where it is one.

### Installing as an app

- **P10-FR-111**: The console and the phone app MUST each be installable from Chrome and Edge
  on Windows and Chrome on Android: with a name, an icon, a start address, and opening in
  their own window.
- **P10-FR-112**: The installed apps MUST NOT keep pages or data to show when the workstation
  cannot be reached. They MUST say plainly that the site cannot be reached, without guessing
  the cause.
- **P10-FR-125**: When an open app loses the workstation, camera tiles MUST stop showing their
  refresh pace and show the time of their last picture, and the page MUST say it cannot
  reach the site.

### Video from outside

- **P10-FR-113**: The engine MUST tell remote requests apart by their address and apply the
  remote limits itself; a screen that ignores the limits MUST still get only what they allow.
  Only addresses on the factory network count as local; anything else, including an address
  the engine cannot read, MUST count as remote.
- **P10-FR-114**: Remote defaults: camera tiles are still pictures refreshed about every 2
  seconds, labelled with that pace and never as LIVE; a live view is reduced in size and rate
  (default 480 pixels wide, 5 pictures a second) and marked as reduced. A refresh the
  workstation slows down MUST NOT be shown as a camera fault.
- **P10-FR-115**: A remote account MUST have at most 2 live views open at once (default). A
  third MUST be refused with a plain reason. A live view whose viewer has vanished MUST free
  its place within 15 seconds.
- **P10-FR-116**: The remote limits MUST be read from the site's configuration with the
  defaults above, never fixed in code.
- **P10-FR-117**: Event snapshots and clips (knife, fall, zone, vehicle) MUST be delivered in
  full to remote users. Nothing MUST change for requests from factory-network addresses.

### Security

- **P10-FR-118**: Sign-in MUST lock an account after 5 failed attempts within 15 minutes, for
  15 minutes. The count is per account, with the email matched exactly as sign-in matches it
  (spaces and capitals ignored), and is not per address. While locked, the right password is
  refused, and more attempts do not extend the lock. The person MUST be told it is locked and
  until when. Locks and unlocks MUST be audited with the address of the attempts. An
  administrator MUST be able to lift a lock, and so must the owner at the workstation
  itself. One address failing on many accounts MUST be slowed down as well.
- **P10-FR-119**: Every camera picture, stream, snapshot and clip request MUST require a
  session, from the LAN and from outside. An automated test MUST prove it for every such
  route, so a new route without it fails the test.
- **P10-FR-120**: The session cookie MUST be marked secure (HTTPS only) on an installed site.
- **P10-FR-121**: Sign-in audit entries (spec 018) MUST record the address the request came
  from and whether it came from the factory network or the private network. That address
  MUST be the real one and impossible for the device to fake.
- **P10-FR-124**: Self sign-up MUST be refused for requests from outside the factory network,
  with a plain reason. On the factory network it MUST work as today.

### Status

- **P10-FR-122**: System Health MUST show remote access as *not set up*, *connected*, or *not
  connected* with the reason, checked within the last minute and showing when. A client
  that is installed but cannot be read MUST say so with its reason, not "not set up". If the
  workstation's private address is missing from the certificate, the row MUST warn. System
  Health MUST stay a normal answer when the VPN client is missing or broken (AGENTS rule 7).

### Notifications

- **P9-FR-101**: A person MUST be able to turn on notifications in the installed phone app on
  each of their devices, and receive alerts while the phone is locked and the app is closed.
- **P9-FR-102**: A notification MUST carry only the kind of event, the camera name and the
  site time. Its title MUST say what is actually known: "Possible knife" until a person has
  confirmed it, "Knife confirmed" or "False alarm" after. No person's name, no face, no
  picture, no plate text and no reviewer's name.
- **P9-FR-103**: Tapping a notification MUST open the app on that event. The details MUST load
  over the private network only.
- **P9-FR-104**: Notification content MUST be encrypted end to end to the phone, so the push
  service carrying it cannot read it. No account with Google or any other company may be
  needed to send them.
- **P9-FR-105**: Phone notifications MUST be a separate switch per alert kind next to email,
  off on a fresh install. A newly registered phone MUST receive nothing until an
  administrator switches it on, as with a new email recipient (spec 013). A phone's
  notifications MUST stop when its owner's account is disabled or deleted, or when the person
  turns them off.
- **P9-FR-106**: A failed notification MUST be recorded in the alert delivery log with its
  reason, never dropped silently.
- **P9-FR-107**: Email MUST stay optional per site, so a strict factory can use notifications
  only.
- **P9-FR-108**: The workstation MUST send notifications only to known push services over
  HTTPS, never to an address a user typed or to anything on the factory network.
- **P9-FR-109**: An administrator MUST be able to see every person's registered phones and
  remove any one of them.

### Owner's instructions

- **P10-FR-123**: The spec directory MUST contain an owner checklist with numbered,
  plain-language steps and the time each takes: create a factory's account, join the
  workstation, enrol a PC, enrol a phone, remove a device, set up a new factory, and what the
  VPN service and the push service can see.

### Depends on (built elsewhere, needed first)

| Needed from | What |
|---|---|
| Spec 016 P10-FR-005 | VisionGuard runs as a Windows service that starts with nobody signed in |
| Spec 016 P10-FR-007 | HTTPS with the site certificate; the workstation serves both apps itself, each at its own address (plan D) |
| Spec 016 P10-FR-009 | The password-free developer sign-in is gone |
| Spec 016 P10-FR-014, -016 | An administrator can change a role and disable an account, and its sessions stop at once |
| Spec 018 P3-FR-001, -002 | The audit is saved and sign-ins are audited |
| Spec 013 | Alert rules, recipients and the delivery log the new notification channel joins |

## Success Criteria *(mandatory)*

- **SC-101**: An enrolled phone on mobile data, Wi-Fi off, shows the sign-in page within 10
  seconds of tapping the app.
- **SC-102**: A device that is not enrolled gets no answer from the workstation from outside:
  0 pages, 0 sign-in forms.
- **SC-103**: With the factory internet unplugged, an office laptop uses the console normally
  and new events keep being saved.
- **SC-104**: After the factory internet or the workstation's power comes back, remote access
  works within 5 minutes without anyone touching the workstation.
- **SC-105**: A removed phone cannot reach the workstation from outside within 2 minutes.
- **SC-106**: Measured on the recorded clip, one remote live view uses no more than 1.5 Mbit/s
  and a page of remote camera tiles no more than 0.5 Mbit/s.
- **SC-107**: A knife alert reaches a locked phone within 30 seconds, titled "Possible
  knife", with no name, face, picture or plate.
- **SC-108**: The owner enrols a new phone in 20 minutes or less using only the checklist.
- **SC-109**: The sixth sign-in attempt after 5 wrong passwords is refused, even with the
  right password, until 15 minutes have passed or an administrator lifts the lock.
- **SC-110**: From outside, 0 of the attempts to self-sign-up succeed; on the factory network,
  sign-up works as before.
- **SC-111**: On a phone over mobile data with good signal, the remote live view is no more
  than 1.5 seconds behind the camera, and a remote tile's picture is never more than 3
  seconds old while its label says "every 2 s". Measured by pointing a camera at a running
  clock.

## Out of scope

- A public web address, or any login page reachable from the internet.
- iPhones and Macs (not in the brief). Nothing here should prevent them later.
- A 6-digit sign-in code (owner decision 6). It can be its own spec.
- Camera sub-streams. Remote video is reduced by the workstation, which already decodes every
  camera; a second camera stream would add load at the workstation and save nothing on the
  remote link.
- A screen for editing the remote limits.
- App-store apps.
- Paid plans of any service, and running our own VPN server (fallback only, see research).
- Any change to self sign-up on the factory network (owner decision 5).
- One screen that shows several factories at once.

## Constitution check *(mandatory)*

- **I. Real-time camera experience**: remote tiles are slower pictures, so they are labelled
  with their pace and never shown as LIVE. When a refresh fails they show the time of their
  last picture. The reduced live view is still live and current, and says it is reduced. The
  LAN address is untouched.
- **III. Truthful data**: System Health reports the VPN state with the time it was checked;
  the installed app never shows cached pages as current; a failed notification is logged; a
  notification says "Possible knife" until a person has confirmed it (AGENTS rules 4 and 10).
- **IV. Security and privacy**: outside access needs an enrolled device **and** a real
  account's password, since self sign-up is refused from outside. Lockout, a secure cookie,
  a session on every media route, notifications with no names or pictures and only to known
  push services. Nothing leaves the site except encrypted traffic. Two risks remain by owner
  decision: self sign-up on the factory network (anyone there can create a read-only IT
  account) and no sign-in code.
- **AGENTS rule 4** (nothing untrue): the reduced view says it is reduced; the offline page
  does not guess why. **Rule 7**: System Health stays a 200. **Rule 8**: a missing or
  unreadable VPN client shows in the UI. **Rule 9**: remote access needs no feature switched
  on. **Rule 10**: notifications never present an unconfirmed knife as confirmed. **Rule
  11**: audit entries are written before the result.
- **Owner supplies all models**: no model is involved.

## Assumptions

- Lockout numbers (5 tries, 15 minutes, 15 minutes; one address slowed after 20 failures in
  15 minutes) and the remote video defaults (2-second tiles, 480 pixels, 5 pictures a
  second, 2 live views) are plan defaults the owner can change.
- "Factory network" means the usual private address ranges (192.168.x.x, 10.x.x.x,
  172.16–31.x.x). A factory whose network uses other addresses sets its own list.
- "Brief details" in a notification means the kind of event, the camera and the time. Plate
  text is left out because it can identify a person; the owner can ask for it.
- The owner is the only person who signs in to the VPN service's dashboard. Devices join with
  one-time keys and need no account of their own. Whether they count against the free plan's
  5-user limit is **not yet known**; the owner asks the service before the pilot (checklist
  A1).
- Office PCs that never leave the factory need no enrolment; they use the LAN address.
- The factory has internet on the workstation for remote access and notifications. Without
  it, everything on site still works.
