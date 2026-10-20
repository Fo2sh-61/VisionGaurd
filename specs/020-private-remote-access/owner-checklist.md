# Owner checklist: private remote access

For Mohamed. Plain steps, one action each. Times are rough; the first time takes longer.

**Read this first**
- **Steps A1–A4 can be done now.** Everything else needs VisionGuard installed on the
  workstation with HTTPS (spec 016). Until then, nothing can be reached from outside.
- Steps marked **(after 020 is built)** use screens this spec adds. Skip them until then.
- Screens change. If a button has a slightly different name, use the closest one and tell
  the developer. Task T020 checks these steps against the real screens.
- **Never write a setup key, a password, a backup code or a private key in this file, in
  the project, or anywhere you keep.** Setup keys are used once and expire in a day.

**Words used here**
- **LAN address**: the workstation's address inside the factory, like `192.168.1.20`.
  Office PCs use it.
- **VPN**: a private network over the internet. Only devices you add can use it.
- **NetBird**: the free VPN service this plan uses.
- **Private address**: the workstation's address inside NetBird, like `100.81.4.7`. Phones
  and laptops away from the factory use it.
- **Setup key**: a one-time code that lets one device join NetBird.
- **Device** (NetBird calls it a *peer*): a phone, laptop or the workstation joined to
  NetBird.
- **Group**: a named set of devices in NetBird, like "operators".
- **Policy**: a NetBird rule saying which group may reach which.
- **Port**: a numbered door on the workstation. VisionGuard uses one for the console and
  one for the phone app.
- **Root certificate**: a small file that makes a device trust this factory's VisionGuard.
  It never changes. It is safe to copy; it is not a password.

**The two VisionGuard addresses** (spec 016 sets the port numbers; check the on-site guide):
- Console: `https://<address>/`
- Phone app: `https://<address>:8443/`

Use the private address away from the factory, or the LAN address inside it.

---

## A. Once per factory, before anything else (about 30 minutes plus NetBird's reply)

1. **Ask NetBird in writing (optional, do not wait for it).**
   1. Send an email to NetBird's support or sales address (on netbird.io) with the four
      questions at the end of `research.md`: is the Free plan OK for a company's own use;
      do key-joined devices count as users; is a card ever asked for; may you hold one free
      account per factory.
   2. Keep their reply.
   3. Carry on without it (decided 19 Oct 2026). If they ever say no to question 1 or 4,
      tell the developer: remote access then moves to a self-hosted NetBird server, and
      nothing on site is affected.
2. **Make a Google account just for this factory**, e.g. `vg.<factory>@gmail.com`.
   1. Google may ask for a phone number; use yours.
   2. Turn on 2-Step Verification.
   3. Write the backup codes on paper and keep them somewhere safe. If you lose both your
      phone and the codes, you lose this factory's remote access.
   4. If you ever hand the factory over, you hand over this Google account.
3. **Make the NetBird account.**
   1. Go to netbird.io and choose the free plan.
   2. Sign in with the Google account from step 2.
   3. **If any screen asks for a card or payment details, stop and tell the developer**.
      That breaks the no-card rule.
4. **Make two groups.** In the NetBird dashboard, open **Groups**. Add a group named
   `workstation`, then a group named `operators`.

## B. The workstation (about 1 hour, once per factory)

1. **Fix its LAN address.**
   1. On the factory router, find the workstation in the list of connected devices.
   2. Choose "reserve address" (sometimes "DHCP reservation" or "static lease").
   3. Write the address on your device list.

   If you cannot reach the router, ask the factory's IT person.
2. **Make it switch itself back on after a power cut.**
   1. Restart the workstation and open its BIOS (usually Delete, F2 or F10 at start).
   2. Find a setting named like **Restore on AC Power Loss**, **AC Recovery** or **After
      Power Loss**.
   3. Set it to **Power On**, then save and exit.
3. **Add the one rule that is allowed.**
   1. In the NetBird dashboard open **Access Control → Policies → Add policy**.
   2. Source: `operators`. Destination: `workstation`.
   3. Protocol: **TCP**. Ports: **443** and **8443** (the console and the phone app).
   4. Make it **one direction** if the screen offers it.
   5. Name it `operators to VisionGuard`. Save.
4. **Remove the open rule.** In **Policies**, delete the policy named **Default** (it lets
   every device reach every other device). Do this only after step 3 is saved, or nothing
   will connect.
5. **Make a setup key for the workstation.** Sit at the workstation while you do this.
   1. In the dashboard open **Setup Keys → Create Setup Key**.
   2. Name it `workstation`. Leave "reusable" **off**. Set expiry to **1 day**.
   3. Set the auto-assigned group to **workstation**. Leave **Ephemeral peers** and
      **Allow extra DNS labels** **off** (an ephemeral device is removed whenever it is
      offline for a while).
   4. Create it and copy it. The window offers **Install NetBird**: choose **Close** instead,
      because Setup installs NetBird. The key is shown only once; never put it in a
      screenshot or a message.
6. **Run VisionGuard Setup on the workstation** (the newest `VisionGuard-Setup-….exe`).
   1. Go through the pages as usual. On **Remote access (optional)**, paste the key.
   2. Setup installs NetBird, joins this PC with the key (never through a sign-in page: a
      device joined by signing in drops off after a day), opens the firewall for NetBird
      only, and adds the private address to the site certificate.
   3. The last page says **"Away from the site, enrolled devices open: https://100.x.x.x/
      … and https://100.x.x.x:8443/"**. That `100.x.x.x` is the **private address**; write
      it on your device list.
   4. **If NetBird opens a sign-in page or asks you to log in, close it.**
   5. If Setup stops with "NetBird did not connect", make a new key (each works once, for
      one day) and run Setup again.
7. **Tidy the dashboard.**
   1. In **Peers**, rename the new device to `workstation`.
   2. In **Setup Keys**, delete the key if it is still listed.
8. **Check the office still works.** From an office PC, open `https://` + the LAN
   address. It must still work. Setup also turned off any rule Windows made by itself
   that opened VisionGuard on **Public** networks; the office uses a Private network.
9. *(Setup did this in step 6: the private address is on the certificate.)*
10. **Push keys.** Follow the on-site guide's "make push keys" step. Check that the backup
    includes the `.env` file; losing it means every phone must switch notifications on
    again.
11. **(after 020 is built) Check.** Open VisionGuard on the workstation, go to **System
    Health**. "Remote access" should say **connected**, show the same private address and
    a recent "checked" time.

## C. Add a Windows laptop (about 10 minutes per laptop)

1. **The person's account.** They sign up in VisionGuard on the factory network, or you
   create one. Then in **Users**, give it the right role (spec 016).
2. In the NetBird dashboard: **Setup Keys → Create Setup Key**. Name it after the person and
   device (e.g. `ali-laptop`). Reusable **off**, expiry **1 day**, auto-group **operators**,
   Ephemeral peers **off**, Allow extra DNS labels **off**. Copy it, then **Close**.
3. On the laptop: install NetBird from netbird.io. **If it opens a sign-in page, close it.**
4. Open a new PowerShell window **as administrator**. Type `netbird up --setup-key `, paste
   the key, press Enter. `netbird status` should say connected.
5. In the dashboard, rename the device to `operator-01` (next free number; no personal
   names), and delete the key if still listed.
6. **Trust the site.** Copy the **root certificate** file (the public `.crt` from the
   on-site guide, never anything called "key") onto the laptop, then:
   1. Double-click it and choose **Install Certificate**.
   2. Choose **Local Machine**.
   3. Choose **Place all certificates in the following store → Browse → Trusted Root
      Certification Authorities**.
   4. Click **Finish**.
7. Open Chrome or Edge and go to `https://` + the private address. The sign-in page should
   open with no warning. *(Not yet tested on real devices, drill D1-PC. If you see a
   warning, stop and tell the developer.)*
8. **(after 020 is built)** Click the browser's menu (⋮) → **Install VisionGuard** (or
   **Apps → Install**). An icon appears on the desktop and in Start.
9. Sign in with that person's own account.
10. Add a line to your device list.

A laptop that never leaves the factory needs only steps 1 and 6. It opens `https://` + the
**LAN** address.

## D. Add an Android phone (about 15 minutes per phone)

1. **The person's account**: as C1.
2. **The phone needs a screen lock** (PIN, pattern or fingerprint). Android will not install
   a certificate without one.
3. In the NetBird dashboard: **Setup Keys → Create Setup Key**. Name it after the person and
   device (e.g. `ali-phone`). Reusable **off**, expiry **1 day**, auto-group **operators**,
   Ephemeral peers **off**, Allow extra DNS labels **off**.
   To get it onto the phone, send it to yourself in a message and **delete the message once
   the phone has joined**.
4. On the phone, install **NetBird** from the Play Store. Open it. **Do not sign in.**
   1. Open its menu, choose **Change server**, then the setup-key option. (This adds the
      key; it does not change NetBird's server. The menu name is not yet checked, T020.)
   2. Paste the key, confirm, and switch NetBird **on**. Accept Android's "VPN connection"
      question.
5. In the dashboard, rename the device to `operator-02` (next free number), and delete the
   key if still listed.
6. **Trust the site.**
   1. Copy the **root certificate** file to the phone (USB cable, or a message to
      yourself).
   2. Open **Settings**, search for **CA certificate**, open it, and choose **Install
      anyway**.
   3. Pick the file.

   On many phones the path is Settings → Security → More security settings → Encryption
   & credentials → Install a certificate → CA certificate. Android then shows a lasting
   notice like "network may be monitored"; that is normal for a certificate you added
   yourself.
7. Open **Chrome**, go to `https://` + the private address + `:8443`. The sign-in page
   should open with no warning. *(Not yet tested on a real phone, drill D1. If you see a
   warning, stop and tell the developer.)*
8. **(after 020 is built)** In Chrome's menu (⋮) choose **Install app** (or **Add to Home
   screen**). Open VisionGuard from the new icon and sign in with that person's account.
9. **(after 020 is built) Notifications.**
   1. On the phone, in VisionGuard: **Settings → Notifications on this phone** → allow. It
      says "Waiting for an administrator".
   2. As an administrator, in **Settings → Alerts**: tick **Phone** for the kinds of alert
      wanted (e.g. Knife), then find this phone in the recipient list and switch it **on**.
   3. Press **Send test** on that phone's row. A notification should arrive.
   4. In Android settings, set **Battery** to **Unrestricted** for **Chrome** and for
      **NetBird**, so alerts arrive and the VPN stays up while the phone sleeps.
10. **Test it outside.** Turn Wi-Fi off and open VisionGuard on mobile data. It should open.
11. **First phone only: test a power cut**, once, at a quiet time, after a backup.
    1. Pull the workstation's power plug, wait 10 seconds, plug it back in. Do not sign in
       to Windows.
    2. After 5 minutes, open VisionGuard on this phone, Wi-Fi off. It should work.
12. Add a line to your device list.

**Inside the factory** a phone can also have a second shortcut to `https://` + the **LAN**
address + `:8443`. Use it for full-quality video, or when the factory's internet is down.
Notifications only come through the first icon (the private address).

## E. A phone or laptop is lost, or a person leaves (about 5 minutes)

1. **First, in VisionGuard**: open **Users**, find the person, choose **Disable**. This works
   at once, also for a phone on the factory Wi-Fi, ends open sessions and stops their
   notifications.
2. **Then in NetBird**: open **Peers** and find the device by its name on your list
   (`operator-NN`). The one named `workstation` (group `workstation`) is **never** the
   one to delete. Choose **Delete**. The device loses access within about 2 minutes
   (to be confirmed, drill D7).
3. Write the date in the "removed" column of your device list.
4. If the person is staying and only lost a phone:
   1. Enable their account again.
   2. In **Settings → Alerts → recipients**, remove the lost phone's row if it is still
      there.
   3. Repeat part C or D for the new device.
5. While you are in **Users**, disable any account you do not recognise.

## F. A new factory (about 2 hours plus devices, after VisionGuard is installed there)

1. Part A steps 1–4 with a **new** Google account and a **new** NetBird account for this
   factory. Never reuse another factory's.
2. Part B for that factory's workstation.
3. Part C or D for each person's device.
4. A person who works at two factories joins each factory's NetBird. The NetBird app reaches
   **one factory at a time**: switch it to the other factory's account first. (How to
   switch is checked in T020.)

## G. What the services can and cannot see

- **NetBird, by its own account** (not independently checked): it cannot see video,
  pictures, faces, names, alerts or anything on a VisionGuard page. Those travel encrypted
  between the device and the workstation. When NetBird passes them through its own server,
  they stay encrypted.
- **NetBird does see**:
  - each device's name (so use `operator-NN`, not people's names) and private address;
  - each device's internet address;
  - when each device was online;
  - the Google email you signed in with.
- **Notifications** go through Google's push service. It cannot read them. It sees:
  - that a small message reached a phone at a certain time;
  - the workstation's internet address;
  - the phone's push address;
  - the factory's Google email used to sign the messages.
- **Fonts**: the VisionGuard pages load their font from Google, so Google sees that a device
  opened a page that uses the font.
- **No video and no records are stored outside the factory.**

## H. Never do these

- Never delete the **workstation** in NetBird's Peers list, and never change NetBird's
  network address range. Either changes the private address, and every device would need
  a new icon.
- Never make a reusable setup key or one without an expiry.
- Never put the Default "everything to everything" policy back.
- Never share one NetBird account between two factories.
- Never copy the certificate's private key anywhere; devices only ever get the root `.crt`.

## I. If remote access stops

1. Can the office use VisionGuard on the LAN?
   - **No**: the problem is VisionGuard itself, not remote access. Follow the on-site
     guide.
   - **Yes**: go on.
2. Open **System Health → Remote access**:
   - **not connected**: check that the factory has internet. If it does, NetBird's own
     servers may be down; wait 15 minutes.
   - **cannot read the NetBird client**: restart the workstation; if it stays, tell the
     developer.
   - **not set up**: NetBird is not running on the workstation. Restart the workstation.
3. On the phone, open the NetBird app and check that it is switched on and connected.
4. If the phone shows a certificate warning, or System Health warns about the certificate,
   the private address may have changed. Compare it with your device list and tell the
   developer.

---

## Device list template

Keep it **outside the project**: print it or copy it somewhere private, one per factory.
Never fill it in inside the project; the project is shared with developers.

Factory: ______  LAN address: ______  Private address: ______

| NetBird name | Person | Device | Joined | Removed |
|---|---|---|---|---|
| workstation | — | workstation | | never |
| operator-01 | | | | |
