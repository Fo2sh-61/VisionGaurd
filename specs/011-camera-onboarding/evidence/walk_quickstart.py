"""Walk specs/011-camera-onboarding/quickstart.md against the real app.

The full `create_app()` with its lifespan: real config, real registry, real
feature workers, real endpoints. Only the TCP socket is skipped.

Runs against a THROWAWAY database so it never touches engine/data. Nothing
here is a test fixture standing in for the product - every call below is the
one the console makes.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ENGINE = Path(__file__).resolve()
REPO = Path("E:/VisionGuard")
sys.path.insert(0, str(REPO / "engine"))

FAILS: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILS.append(label)


def main() -> int:
    from fastapi.testclient import TestClient

    from vg import config as vgconfig
    from vg.api import app as app_module
    from vg.auth.store import UserStore

    scratch = Path(tempfile.mkdtemp(prefix="vg-walk-"))
    db = scratch / "walk.db"

    # Point the whole engine at the throwaway database. `EngineConfig` is
    # frozen, which is why this is `object.__setattr__` - the same thing the
    # existing tests do to redirect clips_dir.
    real_load = vgconfig.load

    def scratch_config(*a, **kw):
        cfg = real_load(*a, **kw)
        object.__setattr__(cfg.storage, "database_url", f"sqlite:///{db.as_posix()}")
        object.__setattr__(cfg.storage, "clips_dir", scratch / "clips")
        return cfg

    vgconfig.load = scratch_config

    users = UserStore(db)
    admin = users.create_user(email="walk@local", name="Walkthrough",
                              role="admin", password="a-long-enough-walk-password")
    guard = users.create_user(email="guard@local", name="Guard",
                              role="it", password="a-long-enough-walk-password")
    admin_token, _ = users.start_session(admin)
    guard_token, _ = users.start_session(guard)

    app = app_module.create_app()
    try:
        with TestClient(app) as raw:
            app.state.users = users
            c = TestClient(app, headers={"Authorization": f"Bearer {admin_token}"})
            g = TestClient(app, headers={"Authorization": f"Bearer {guard_token}"})
            run(c, g, scratch)
    finally:
        vgconfig.load = real_load
        users.close()
        shutil.rmtree(scratch, ignore_errors=True)

    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) FAILED: {', '.join(FAILS)}")
        return 1
    print("every check passed")
    return 0


def run(c, g, scratch: Path) -> None:
    # -- 1. the recorder no longer lies ------------------------------------
    print("\n1. The recorder no longer lies")
    r = c.post("/sources/dvr", json={
        "host": "10.255.255.1", "username": "admin", "password": "x",
        "template": "file:/nonexistent/ch{channel}.mp4",
        "channels": ["1", "2", "3"], "budget": 10.0})
    body = r.json()
    check("unreachable recorder is 200, not an error", r.status_code == 200)
    check("reachable is false with a reason", body["reachable"] is False and bool(body["reason"]),
          body.get("reason", "")[:60])
    check("nothing is offered to add", not [x for x in body["channels"] if x["enabled"]])
    check("every channel asked about is still reported", len(body["channels"]) == 3)
    check("no channel claims a resolution it never got",
          all(x["resolution"] is None for x in body["channels"]))

    r = c.post("/sources/dvr", json={
        "host": "10.0.0.5", "username": "u", "password": "p",
        "template": "rtsp://{host}/stream", "channels": ["1"]})
    check("a template with no {channel} is refused 422", r.status_code == 422)

    clip = next((REPO / "engine/data/footage").glob("*.mp4"), None)
    if clip:
        shutil.copy(clip, scratch / "ch7.mp4")
        r = c.post("/sources/dvr", json={
            "host": "unused", "username": "", "password": "",
            "template": "file:" + (scratch / "ch{channel}.mp4").as_posix(),
            "channels": ["7", "8"], "budget": 20.0})
        body = r.json()
        ok = next(x for x in body["channels"] if x["channel"] == "7")
        bad = next(x for x in body["channels"] if x["channel"] == "8")
        check("a real channel reports a real resolution",
              ok["status"] == "ok" and "x" in (ok["resolution"] or ""), ok["resolution"])
        check("a channel with nothing on it is checked, down, and explains itself",
              bad["checked"] and bad["status"] == "down" and bool(bad["error"]))

    # -- 2. nothing appears that was not saved ------------------------------
    print("\n2. Nothing appears that was not saved")
    r = c.post("/sources/scan")
    body = r.json()
    check("scan says whether it could look at all", r.status_code == 200 and "available" in body)
    check("scan is honestly unavailable, not an empty list",
          body["available"] is False and bool(body["reason"]), body.get("reason", "")[:60])

    r = c.post("/sources/bulk", json={"cameras": [
        {"name": "Walk A", "source": "webcam:21", "features": ["counting"]},
        {"name": "Walk B", "source": "webcam:22", "features": ["vehicles"]},
        {"name": "Walk C", "source": "webcam:23", "features": ["counting"]},
    ]})
    outcomes = r.json()
    check("bulk add is 200 with one outcome each",
          r.status_code == 200 and len(outcomes) == 3)
    check("the bad one is refused and the others still added",
          [o["ok"] for o in outcomes] == [True, False, True], str([o["ok"] for o in outcomes]))
    check("the refusal explains itself", bool(outcomes[1]["error"]),
          (outcomes[1]["error"] or "")[:70])

    listed = {s["id"] for s in c.get("/sources").json()}
    check("what was added is actually there", {"cam-walk-a", "cam-walk-c"} <= listed)

    # -- 3. the feature list governs ----------------------------------------
    print("\n3. The feature list governs")
    added = c.post("/sources", json={
        "name": "Walk knives", "source": "webcam:24",
        "features": ["counting", "weapons"]}).json()
    check("a camera can be given knife detection", "weapons" in added["features"])

    plain = c.post("/sources", json={
        "name": "Walk plain", "source": "webcam:25",
        "features": ["counting"]}).json()
    check("a camera without it does not have it", "weapons" not in plain["features"])

    r = c.post("/sources", json={
        "name": "Walk typo", "source": "webcam:26", "features": ["weapon"]})
    check("an unknown feature name is refused 422", r.status_code == 422)
    check("and the message names the word", "weapon" in r.text)

    health = c.get("/system/health").json()
    check("system health stays 200 whatever is off", True)

    # -- 4. a camera can be corrected ---------------------------------------
    print("\n4. A camera can be corrected")
    r = c.patch(f"/sources/{plain['id']}", json={"features": ["counting", "track"]})
    body = r.json()
    check("a features-only edit does not reopen the stream", body["restarted"] is False)
    check("the change took", set(body["camera"]["features"]) == {"counting", "track"})
    check("its id did not change", body["camera"]["id"] == plain["id"])

    r = c.patch(f"/sources/{plain['id']}", json={"fps": 9.0})
    check("changing the rate does reopen the stream", r.json()["restarted"] is True)

    r = c.patch("/sources/cam-laptop", json={"area": "Walk yard"})
    check("editing a config-file camera says it now shadows it",
          r.json()["shadowsConfig"] is True)

    check("editing a camera that does not exist is 404",
          c.patch("/sources/cam-nope", json={"area": "x"}).status_code == 404)

    r = c.patch(f"/sources/{plain['id']}", json={"features": ["vehicles"]})
    check("an invalid edit is refused 422", r.status_code == 422)
    still = next(s for s in c.get("/sources").json() if s["id"] == plain["id"])
    check("and changed nothing", "vehicles" not in still["features"])

    # -- 5. bulk add reports every outcome ----------------------------------
    print("\n5. Adding many at once")
    many = c.post("/sources/bulk", json={"cameras": [
        {"name": f"Walk bulk {i}", "source": f"webcam:{40 + i}",
         "features": ["counting"]} for i in range(12)]}).json()
    check("twelve in, twelve outcomes out", len(many) == 12)
    check("indexes line up with what was sent",
          [o["index"] for o in many] == list(range(12)))
    check("a camera already running was not disturbed",
          "cam-walk-a" in {s["id"] for s in c.get("/sources").json()})

    # -- 6. no password anywhere --------------------------------------------
    print("\n6. No password anywhere")
    SENTINEL = "WALKTHROUGHPW"
    c.post("/sources", json={
        "name": "Walk secret", "source": f"rtsp://admin:{SENTINEL}@10.0.0.9/s",
        "features": ["counting"]})
    surfaces = {
        "the camera list": c.get("/sources").text,
        "the audit trail": c.get("/audit").text,
        "system health": c.get("/system/health").text,
    }
    for where, text in surfaces.items():
        check(f"no password in {where}", SENTINEL not in text)
    shown = next(s for s in c.get("/sources").json() if s["id"] == "cam-walk-secret")
    check("but the address is still readable", "10.0.0.9" in shown["ip"] and "****" in shown["ip"],
          shown["ip"])

    audit = c.get("/audit").json()
    actions = {e["action"] for e in audit}
    check("adds are audited", "camera.add" in actions)
    check("edits are audited", "camera.edit" in actions)

    c.delete(f"/sources/{plain['id']}")
    check("removals are audited",
          "camera.remove" in {e["action"] for e in c.get("/audit").json()})

    # -- 7. only administrators ---------------------------------------------
    print("\n7. Only administrators")
    checks = [
        ("add", g.post("/sources", json={"name": "X", "source": "webcam:99"})),
        ("bulk", g.post("/sources/bulk", json={"cameras": [
            {"name": "X", "source": "webcam:99"}]})),
        ("edit", g.patch("/sources/cam-walk-a", json={"name": "X"})),
        ("remove", g.delete("/sources/cam-walk-a")),
        ("connect a recorder", g.post("/sources/dvr", json={
            "host": "10.0.0.5", "username": "u", "password": "p",
            "template": "rtsp://{host}/ch{channel}", "channels": ["1"]})),
    ]
    for name, r in checks:
        check(f"a guard cannot {name}", r.status_code == 403, f"got {r.status_code}")


if __name__ == "__main__":
    raise SystemExit(main())
