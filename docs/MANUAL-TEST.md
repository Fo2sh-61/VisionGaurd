# Manual test — 15 minutes, no cameras needed

A walkthrough of the console by hand. Run it after any change that touches the
pipeline, and before showing the system to anyone.

It uses the **recorded clip**, not a webcam. The clip is identical every run,
locks no device, and has known ground truth — so a difference is a real
difference, not the lighting.

**The most important instruction in this document:** several steps below are
supposed to say "not available". Those are passes, not failures. A page that
cheerfully shows numbers for a feature that does not exist is the single worst
thing this system can do, so the checks that something *refuses* to answer
matter as much as the ones where it does.

---

## Before you start — once only

Create an account. Without one, nobody can sign in and the console will look
broken.

```powershell
python engine/tools/create_user.py
```

It asks for email, name, role and password. Choose **admin**. The password
must be at least 12 characters and is not echoed as you type.

Make a second account as **it** if you want to test roles in step 8.

Check they exist:

```powershell
python engine/tools/create_user.py --list
```

---

## Start it

```powershell
.\dev.ps1 up -Clip
```

Wait for both lines to appear, then open **http://localhost:5173**.

Leave the terminal visible. If something goes wrong the reason is usually
there before it is on screen.

---

## 1. The lock

| Do | Expect |
|---|---|
| Open http://localhost:5173 | The **sign-in page**, not the console |
| Type a wrong password | *"Email or password is wrong."* |
| Type a made-up email address | **Exactly the same message** |

That last one matters. If the two messages differ, the form can be used to
work out who works at the school. They should be indistinguishable.

Now sign in properly. You should land on Home.

**Then try to get in the back way.** Open the browser console (F12) and run:

```js
localStorage.setItem('vg.role', 'admin')
```

Refresh. **Nothing should change.** That line used to be the entire security
system. Now the browser holds no identity at all, so editing it achieves
nothing.

---

## 2. Live camera

Go to **Cameras** (or Home → the camera tile).

- [ ] The clip is playing, not a frozen frame
- [ ] A person walking through gets a box drawn around them
- [ ] The box follows them, and does not lag several seconds behind

**Now unplug it.** Stop the engine in the terminal (`Ctrl-C`) while the page
is open.

- [ ] Within about two seconds the tile says **NO SIGNAL**
- [ ] It shows the last frame it received, clearly marked — **not** a frozen
      image pretending to be live

Restart with `.\dev.ps1 up -Clip` and the tile should recover on its own.

---

## 3. Attendance

Go to **Attendance**, pick a group and today's date, press **Show**.

- [ ] Either a register, or a plain sentence saying why there is not one
- [ ] It never shows an empty table with no explanation

If face recognition is not running, the amber bar at the top says so and names
the reason. That is a pass.

Press **Export CSV**. The file downloads and opens in Excel.

---

## 4. The pages that should refuse

This is the part people skip. Do not skip it.

| Page | What it must say |
|---|---|
| **Restricted zones** | "Not available" with a reason, and **no invented breaches** |
| **Knife detection** | "Not available", and **no green "no knife detected" tick** |
| **Lost items** | Search returns *"the footage was never searched"*, not "no matches" |

For each one:

- [ ] There is an amber bar explaining the gap
- [ ] There are **no rows** underneath it

A banner saying "not available" above three invented breaches would be worse
than either on its own — the page contradicts itself, and the rows are the
half people believe.

On **Knife detection** especially: there must be no green tick reading *"No
knife detected on campus."* Nothing is watching for knives, so that sentence
would be an assurance produced by no measurement at all.

---

## 5. Track a person

Go to **Track a person**, pick someone, press **Search**.

- [ ] Green box = named by their **face**
- [ ] Blue box = same body, identified by **clothing** only
- [ ] The two are never merged into one colour or one number

A blue box means "this is the same person as a moment ago". It does **not**
mean the system knows who they are. If a blue box shows a name, that is a bug
worth stopping for — it is the fault that once put one person's name on every
body on the camera.

---

## 6. System health

Go to **System health**.

- [ ] Every subsystem is listed with an honest state
- [ ] Anything not running says **why** — "weights not found: yolov8s.pt" is
      useful, "not running" is not
- [ ] A failing row is **amber or red**, never a green badge with bad news in it

**Then break something on purpose.** Rename a model file in `models/`,
restart, and come back. The page must load and explain the gap. If System
Health itself fails when something is broken, that is the worst possible bug —
it is the page you open precisely when things are wrong.

---

## 7. Empty and broken states

Sign in as **admin** for this step (Users is admin-only). With the engine
**stopped**, click through: Attendance, Counting, People, Users, Track.

- [ ] Every page shows a red **"Could not load…"** with a **Try again** button
- [ ] No page is blank
- [ ] No page shows a confident **0** — "0 people can sign in" is a claim, and
      it must not be made from a failed request

Start the engine again and press **Try again** on any of them. It should
recover without a refresh.

---

## 8. Roles — needs the second account

Sign out. Sign in as the **it** account.

- [ ] You can see cameras, attendance, counting and health
- [ ] **Enrol a face** is refused — *"This needs an administrator account."*
- [ ] Adding or removing a camera is refused the same way
- [ ] **Users** is refused too — the account list is admin-only

Verified: an `it` account gets `403 This needs an administrator account.` on
both `POST /enrolment/sessions` and `GET /users`.

The refusal comes from the engine, not the page. To prove it, open the browser
console and run:

```js
await fetch('/enrolment/sessions', {
  method: 'POST', credentials: 'include',
  headers: { 'Content-Type': 'application/json' }, body: '{}'
})
```

- [ ] It returns **403**, even though you asked the API directly

---

## 9. Signing out

Press sign out.

- [ ] You land back on the sign-in page
- [ ] Pressing the browser **back** button does not return you to the console

---

## When something fails

Check the terminal first — the engine logs the reason before the page shows
it. Then:

```powershell
python -m pytest engine     # did a rule break?
.\dev.ps1 doctor            # is the machine set up right?
.\dev.ps1 down              # frees ports 8001 and 5173
```

Report what you saw and what you expected. "Attendance showed an empty table
with no message" is worth more than "attendance is broken".
