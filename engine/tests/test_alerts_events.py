"""Alerts from real events: a knife, its verdict, a zone scene, a gate pass, a
camera gone dark (spec 013, user stories 2 and 3).

Each test wires the real store that commits the event to a real `AlertService`
whose couriers are fakes, and drives the sender a pass at a time. So what is
proved is the whole path - a row committed, a hook fired, a message built, a
courier handed it, a log row written - with nothing on the network.

The rules held here:

- one message per event, never per frame, and a two-minute continuation of
  the same incident is not a new event;
- the knife message says nobody has confirmed it; the verdict goes to exactly
  the people who got the scare, naming who decided;
- a restart re-sends nothing;
- no message names a student, shows a face or points at a picture (SC-007).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from vg.alerts import providers
from vg.alerts.service import AlertService
from vg.alerts.store import AlertStore
from vg.api import schemas as S
from vg.clock import FixedClock
from vg.config import AlertsConfig
from vg.events.weapons import WeaponSceneStore
from vg.infer.persons import DetectedPerson
from vg.infer.weapons import DetectedWeapon
from vg.ingest.source import Frame

START = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(microsecond=0)

KEYS = ("GMAIL_USER", "GMAIL_APP_PASSWORD")


# ---------------------------------------------------------------------------
# doubles
# ---------------------------------------------------------------------------

class Courier:
    """A fake Gmail: accepts everything and remembers what it was given."""

    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send(self, message, destination):
        self.sent.append((destination, message.body))
        return providers.SendResult.accepted(f"SM{len(self.sent)}")


def drain(service: AlertService, passes: int = 20) -> None:
    """Run the sender until nothing is left to send."""
    for _ in range(passes):
        service.step()


def frame(camera_id: str = "cam-a", *, at: float = 0.0, sequence: int = 0) -> Frame:
    return Frame(camera_id=camera_id, image=np.zeros((4, 4, 3), dtype=np.uint8),
                 captured_at=START + timedelta(seconds=at), sequence=sequence)


class FakeDetector:
    def __init__(self):
        self.people = 0

    def detect(self, frame):
        return [DetectedPerson(x=0.4, y=0.2, w=0.2, h=0.6, confidence=0.9)
                for _ in range(self.people)]


class FakeKnives:
    version = "knifebest"
    device = "cpu"

    def __init__(self):
        self.hits = 0

    def detect(self, image, min_confidence=None):
        return [DetectedWeapon(x=0.45, y=0.4, w=0.05, h=0.05, confidence=0.7,
                               label="knife") for _ in range(self.hits)]


def knife_worker(scenes):
    """A WeaponsWorker with no thread - `analyse` is called directly.
    Copied from test_weapons_live.py::worker."""
    from vg.features.weapons import WeaponsWorker

    class NoBus:
        def subscribe(self, *a, **kw):  # pragma: no cover - never started
            raise AssertionError("never started in these tests")

    people, knives = FakeDetector(), FakeKnives()
    return WeaponsWorker(NoBus(), people, knives, ["cam-a"], scenes), people, knives


def live_store(tmp_path, **kw):
    """A LiveStore over one never-started camera and a throwaway database."""
    from vg import config as vgconfig
    from vg.api.live import LiveStore
    from vg.config import CameraConfig
    from vg.ingest.registry import CameraRegistry

    registry = CameraRegistry([
        CameraConfig.parse({"id": "cam-a", "name": "Yard camera", "source": "webcam:0",
                            "features": ["counting"]}, "cam-a"),
    ])
    config = vgconfig.load()
    object.__setattr__(config.storage, "clips_dir", Path(tmp_path) / "clips")
    return LiveStore(config, registry, **kw)


@dataclass
class World:
    alerts: AlertStore
    service: AlertService
    courier: Courier
    tmp: Path


@pytest.fixture
def world(tmp_path, monkeypatch):
    """An alert database, a sender with a fake courier, email on for knives
    and two people listed."""
    for name in KEYS:
        monkeypatch.delenv(name, raising=False)
    alerts = AlertStore(tmp_path / "alerts.db")
    courier = Courier()
    service = AlertService(AlertsConfig(), alerts, None, FixedClock(offset_minutes=180),
                           senders=lambda channel: courier)
    service.bind(camera_name=lambda camera_id: {"cam-a": "Yard camera"}.get(camera_id))
    alerts.add_recipient("email", "head@school.example", "Head of security")
    alerts.add_recipient("email", "deputy@school.example", "Deputy head")
    yield World(alerts, service, courier, tmp_path)
    alerts.close_db()


def only_recipient(world: World, address: str, name: str) -> None:
    """Make one person the only recipient. Email is the one channel, so the
    world's two knife readers would otherwise get the gate and camera
    messages too."""
    for person in world.alerts.recipients():
        world.alerts.remove_recipient(person.id)
    world.alerts.add_recipient("email", address, name)


def rows_for(alerts: AlertStore, key: str):
    return [r for r in alerts.recent(200) if r.event_key == key]


# ---------------------------------------------------------------------------
# user story 2 - the knife
# ---------------------------------------------------------------------------

@pytest.fixture
def knives(world):
    scenes = WeaponSceneStore(world.tmp / "weapons.db")
    scenes.on_open = world.service.on_weapon_open
    world.alerts.update_rule("weapon", email=True)
    yield scenes
    scenes.close_db()


class TestKnifeMessages:
    def test_an_entry_opening_is_one_message_per_person(self, world, knives):
        scene_id = knives.open("cam-a", START, 0.76, "knifebest")
        drain(world.service)
        rows = rows_for(world.alerts, f"weapon:{scene_id}:opened")
        assert sorted((r.recipient_name, r.outcome) for r in rows) == [
            ("Deputy head", "sent"), ("Head of security", "sent")]
        for _, body in world.courier.sent:
            assert "Yard camera" in body
            assert "awaiting review — not yet confirmed by a person" in body.lower()
            assert "76%" in body

    def test_the_hook_never_breaks_the_write(self, world, tmp_path):
        """A store must not lose its row because a message could not be queued."""
        scenes = WeaponSceneStore(tmp_path / "w2.db")

        def broken(*args, **kwargs):
            raise RuntimeError("queue gone")
        scenes.on_open = broken
        try:
            scene_id = scenes.open("cam-a", START, 0.7, "knifebest")
            assert scenes.get(scene_id) is not None
        finally:
            scenes.close_db()

    def test_a_continuation_sends_nothing(self, world, knives):
        knives.open("cam-a", START, 0.76, "knifebest", continues=True)
        drain(world.service)
        assert world.alerts.recent(10) == []
        assert world.courier.sent == []

    def test_a_knife_held_past_two_minutes_is_one_message(self, world, knives):
        """The worker cuts at two minutes and reopens at once. One incident."""
        worker, people, knife_model = knife_worker(knives)
        for i in range(251):                       # 125 s, a knife in every frame
            people.people, knife_model.hits = 1, 1
            worker.analyse(frame("cam-a", at=i / 2, sequence=i))
        entries = knives.recent(None, None)
        assert len(entries) == 2, "the worker cut the incident in two"
        drain(world.service)
        keys = {r.event_key for r in world.alerts.recent(20)}
        first = min(entries, key=lambda e: e.started_at)
        assert keys == {f"weapon:{first.id}:opened"}
        assert len(world.courier.sent) == 2        # two people, one message each

    def test_the_verdict_goes_to_exactly_the_people_who_got_the_scare(
            self, world, knives, tmp_path):
        scene_id = knives.open("cam-a", START, 0.76, "knifebest")
        drain(world.service)
        world.alerts.add_recipient("email", "later@school.example", "Added later")
        store = live_store(tmp_path, weapon_scenes=knives, alerts_store=world.alerts,
                           alerts=world.service)

        reviewed = store.review_weapon(
            scene_id, S.WeaponReview(verdict=S.ReviewVerdict.DISMISSED), reviewer="Guard A")
        assert reviewed is not None
        drain(world.service)

        verdicts = rows_for(world.alerts, f"weapon:{scene_id}:verdict")
        assert sorted(r.recipient_name for r in verdicts) == ["Deputy head", "Head of security"]
        bodies = [body for _, body in world.courier.sent[2:]]
        assert len(bodies) == 2
        for body in bodies:
            assert "false alarm" in body.lower() and "Guard A" in body

    def test_a_second_review_sends_nothing_more(self, world, knives, tmp_path):
        scene_id = knives.open("cam-a", START, 0.76, "knifebest")
        drain(world.service)
        store = live_store(tmp_path, weapon_scenes=knives, alerts_store=world.alerts,
                           alerts=world.service)
        review = S.WeaponReview(verdict=S.ReviewVerdict.CONFIRMED)
        assert store.review_weapon(scene_id, review, reviewer="Guard A") is not None
        assert store.review_weapon(scene_id, review, reviewer="Guard B") is None
        drain(world.service)
        verdicts = rows_for(world.alerts, f"weapon:{scene_id}:verdict")
        assert len(verdicts) == 2
        assert all("Guard B" not in body for _, body in world.courier.sent)

    def test_no_opening_message_means_no_verdict(self, world, knives, tmp_path):
        """Nobody was scared, so nobody is sent an answer."""
        world.alerts.update_rule("weapon", email=False)
        scene_id = knives.open("cam-a", START, 0.76, "knifebest")
        drain(world.service)
        world.alerts.update_rule("weapon", email=True)
        store = live_store(tmp_path, weapon_scenes=knives, alerts_store=world.alerts,
                           alerts=world.service)
        store.review_weapon(scene_id, S.WeaponReview(verdict=S.ReviewVerdict.DISMISSED),
                            reviewer="Guard A")
        drain(world.service)
        assert world.alerts.recent(10) == []

    def test_a_restart_sends_nothing_again(self, world, knives):
        knives.open("cam-a", START, 0.76, "knifebest")
        drain(world.service)
        before = len(world.alerts.recent(50))

        courier = Courier()
        again = AlertService(AlertsConfig(), world.alerts, None, FixedClock(180),
                             senders=lambda channel: courier)
        again.start(run_thread=False)
        drain(again)
        assert len(world.alerts.recent(50)) == before
        assert courier.sent == []

    def test_the_pending_list_is_every_entry_awaiting_a_verdict(self, knives):
        first = knives.open("cam-a", START, 0.7, "knifebest")
        second = knives.open("cam-a", START + timedelta(minutes=5), 0.8, "knifebest")
        knives.review(first, "dismissed", "Guard A", START + timedelta(minutes=6))
        assert [s.id for s in knives.pending()] == [second]


# ---------------------------------------------------------------------------
# user story 3 - breaches, gate alerts, dark cameras
# ---------------------------------------------------------------------------

def zone_worker(scenes):
    """A ZonesWorker with no thread. Copied from test_zones_live.py::worker."""
    from vg.features.zones import ZonesWorker

    class NoBus:
        def subscribe(self, *a, **kw):  # pragma: no cover - never started
            raise AssertionError("never started in these tests")

    detector = FakeDetector()
    from vg.areas import FULL_FRAME, Area

    zone = Area(id="cam-a", kind="zone", name="cam-a", camera_id="cam-a",
                polygon=FULL_FRAME, hours_mode="always", alert_after_seconds=0.0)
    return ZonesWorker(NoBus(), detector, ["cam-a"], scenes, recorder=None,
                       areas=[zone]), detector


@pytest.fixture
def zones(world):
    from vg.events.zones import SceneStore

    scenes = SceneStore(world.tmp / "zones.db")
    scenes.on_open = world.service.on_zone_open
    world.alerts.update_rule("intrusion", email=True)
    yield scenes
    scenes.close_db()


class TestZoneMessages:
    def test_a_breach_is_one_message_per_person(self, world, zones):
        scene_id = zones.open("cam-a", START)
        drain(world.service)
        rows = rows_for(world.alerts, f"intrusion:{scene_id}")
        assert sorted(r.outcome for r in rows) == ["sent", "sent"]
        for _, body in world.courier.sent:
            assert "restricted area" in body and "Yard camera" in body

    def test_a_continuation_sends_nothing(self, world, zones):
        zones.open("cam-a", START, continues=True)
        drain(world.service)
        assert world.alerts.recent(10) == []

    def test_five_minutes_in_a_restricted_room_is_one_message(self, world, zones):
        """The worker cuts every two minutes. The person is one visit."""
        worker, detector = zone_worker(zones)
        for i in range(600):                       # 300 s, somebody always there
            detector.people = 1
            worker.analyse(frame("cam-a", at=i / 2, sequence=i))
        visits = zones.recent(since_days=1)
        assert len(visits) >= 3, "the worker cut the visit"
        drain(world.service)
        first = min(visits, key=lambda s: s.started_at)
        assert {r.event_key for r in world.alerts.recent(50)} == {f"intrusion:{first.id}"}
        assert len(world.courier.sent) == 2

    def test_a_detector_that_blinks_does_not_mail_for_every_blink(
            self, world, zones):
        """The bug, 12 Sep 2026: one fifty-second visit sent thirty-two emails.

        Nobody left. The person detector lost them for one to two seconds at a
        time, which at the old one-second gap closed the scene each time - and
        every reopening was a new event key, so every blink was an email. The
        dropouts below are the real ones, measured off the scene rows the
        night it happened.
        """
        worker, detector = zone_worker(zones)
        dropouts = [1.0, 1.9, 1.4, 0.6, 1.2, 1.0, 1.4, 0.8]
        at, seq = 0.0, 0

        def play(seconds: float, people: int) -> None:
            nonlocal at, seq
            for _ in range(round(seconds / 0.2)):      # the 5 Hz analysis rate
                detector.people = people
                worker.analyse(frame("cam-a", at=at, sequence=seq))
                at, seq = at + 0.2, seq + 1

        for gap in dropouts:
            play(3.0, 1)
            play(gap, 0)

        assert len(zones.recent(since_days=1)) == 1, (
            "a dropout under the gap is a detector blinking, not a new visit"
        )
        drain(world.service)
        assert len(world.courier.sent) == 2, (
            "one visit, one message each to the two recipients"
        )

    def test_coming_back_within_the_minute_is_the_same_incident(
            self, world, zones):
        # They walk out of shot for long enough to end the entry - fifteen
        # seconds - and walk back. That is one person pacing, not two visits,
        # and the second entry must send nothing.
        from vg.features.zones import GAP_SECONDS

        worker, detector = zone_worker(zones)
        for start in (0.0, GAP_SECONDS + 15.0):
            for i in range(20):                        # 4 s of being seen
                detector.people = 1
                worker.analyse(frame("cam-a", at=start + i * 0.2, sequence=i))
            for i in range(int((GAP_SECONDS + 5.0) / 0.2)):
                detector.people = 0
                worker.analyse(frame("cam-a", at=start + 4.0 + i * 0.2, sequence=i))

        assert len(zones.recent(since_days=1)) == 2, "two entries"
        drain(world.service)
        assert len(world.courier.sent) == 2, "and one message each, not two"

    def test_coming_back_after_a_clear_minute_is_news_again(self, world, zones):
        # The other half of the rule, and the one that keeps it honest: a
        # quiet camera that has been empty this long is reporting somebody
        # new, and holding that back would be the feature failing silently.
        from vg.features.zones import ALERT_AGAIN_AFTER_SECONDS

        worker, detector = zone_worker(zones)
        for start in (0.0, ALERT_AGAIN_AFTER_SECONDS + 30.0):
            for i in range(20):                        # 4 s of being seen
                detector.people = 1
                worker.analyse(frame("cam-a", at=start + i * 0.2, sequence=i))
            for i in range(int((ALERT_AGAIN_AFTER_SECONDS + 10.0) / 0.5)):
                detector.people = 0
                worker.analyse(frame("cam-a", at=start + 4.0 + i * 0.5, sequence=i))

        drain(world.service)
        assert len(world.courier.sent) == 4, (
            "two visits a clear minute apart are two pieces of news"
        )

    def test_a_camera_that_went_dark_does_not_swallow_the_next_alert(
            self, world, zones):
        # A camera that loses its stream sends NO frames - not empty ones. If
        # the run could only end on a frame with nobody in it, the first person
        # after an outage would be taken for the last one before it, and the
        # feature would go silent with every screen saying it was running.
        worker, detector = zone_worker(zones)
        for start in (0.0, 7200.0):                    # two hours of nothing
            for i in range(20):                        # 4 s of being seen
                detector.people = 1
                worker.analyse(frame("cam-a", at=start + i * 0.2, sequence=i))

        drain(world.service)
        assert len(world.courier.sent) == 4, (
            "somebody on a camera that has been dark for hours is news"
        )


class TestNothingAboutAMinor:
    """SC-007, proved by a test and not a review: a student was recognised on
    the very camera, at the very moment, and the message names nobody."""

    def test_a_breach_where_a_student_was_recognised_names_nobody(
            self, world, zones, tmp_path):
        from vg.events.sightings import Sighting, SightingStore
        from vg.identity.gallery import FaceGallery

        model = "sface-2021dec"
        gallery = FaceGallery(tmp_path / "gallery.db", model=model, threshold=0.363)
        sightings = SightingStore(tmp_path / "sightings.db", clock=180)
        try:
            vector = np.random.default_rng(7).standard_normal(128).astype("float32")
            gallery.add_person("p-layla", "Layla Ahmed", group="Grade 8")
            gallery.add_embedding("p-layla", vector / float(np.linalg.norm(vector)), model)
            sightings.record(Sighting("p-layla", "cam-a", START, 0.8, model), force=True)
            store = live_store(tmp_path, gallery=gallery, sightings=sightings, scenes=zones,
                               alerts_store=world.alerts, alerts=world.service)
            world.service.bind(camera_name=store._camera_name)

            zones.open("cam-a", START)
            drain(world.service)

            assert world.courier.sent, "a message was built and sent"
            for _, body in world.courier.sent:
                for leak in ("Layla", "Ahmed", "p-layla", "Grade 8", ".jpg", ".png", "clip"):
                    assert leak not in body, f"{leak!r} left the building"
        finally:
            sightings.close()
            gallery.close()


@pytest.fixture
def gate(world):
    from vg.events.vehicles import VehicleStore

    vehicles = VehicleStore(world.tmp / "vehicles.db")
    vehicles.on_pass = world.service.on_pass
    world.alerts.update_rule("vehicles", email=True)
    only_recipient(world, "gate@school.example", "Gate supervisor")
    yield vehicles
    vehicles.close_db()


TODAY = date(2026, 9, 11)


def gate_pass(vehicles, plate="بجد 1234", needs_review=False, finished=True):
    """A pass the reader is done with - the car has left the camera - unless
    `finished` is False, when the reader may still correct it."""
    record = vehicles.record_pass(
        at=START, camera_id="cam-a", gate=1, direction="entry", plate=plate,
        confidence=0.91, votes=3, needs_review=needs_review, today=TODAY)
    return vehicles.finish_pass(record.id) if finished else record


class TestGateMessages:
    def test_each_reason_is_one_message_with_the_plate_and_the_gate(self, world, gate):
        gate.add(plate="رقص 9058", owner_name="Former contractor", category="blacklist")
        gate.add(plate="نيع 3317", owner_name="Hoda Kamel", category="visitor",
                 valid_until="2020-07-28")
        passes = [gate_pass(gate, "رقص 9058"), gate_pass(gate, "نيع 3317"),
                  gate_pass(gate, "بجد 1234")]
        assert [p.status for p in passes] == ["blacklist", "expired", "unknown"]
        drain(world.service)

        bodies = [body for _, body in world.courier.sent]
        assert len(bodies) == 3, "one message per pass, to the one gate recipient"
        for record, body in zip(passes, bodies):
            assert record.plate_display in body and "gate 1" in body
        assert "Blacklisted" in bodies[0]
        assert "expired permit" in bodies[1]
        assert "not on the register" in bodies[2]

    def test_a_registered_car_sends_nothing(self, world, gate):
        gate.add(plate="بجد 1234", owner_name="Staff member", category="staff")
        assert gate_pass(gate).status == "known"
        drain(world.service)
        assert world.alerts.recent(10) == []

    def test_a_reason_switched_off_sends_nothing(self, world, gate):
        world.alerts.update_rule("vehicles", vehicle_unknown=False)
        gate_pass(gate)
        drain(world.service)
        assert world.alerts.recent(10) == []

    def test_an_uncertain_read_says_so(self, world, gate):
        gate_pass(gate, needs_review=True)
        drain(world.service)
        (body,) = [body for _, body in world.courier.sent]
        assert "uncertain" in body.lower()

    def test_the_owners_name_never_leaves(self, world, gate):
        gate.add(plate="رقص 9058", owner_name="Former contractor", category="blacklist")
        gate_pass(gate, "رقص 9058")
        drain(world.service)
        (body,) = [body for _, body in world.courier.sent]
        assert "Former contractor" not in body


class TestTheGateWaitsForTheFinalReading:
    """The first three frames that agree are the worst look the camera gets,
    and the reader corrects the row as the car comes closer. So a gate message
    waits until the reader is done - the car has left the camera - and says
    what the reading finally was. A few seconds late, and right (decided with
    Mohamed, 11 Sep 2026)."""

    def test_nothing_is_sent_while_the_reader_may_still_correct_it(self, world, gate):
        gate_pass(gate, finished=False)
        drain(world.service)
        assert world.alerts.recent(10) == []

    def test_a_reading_corrected_to_a_blacklisted_car_is_one_blacklist_message(
            self, world, gate):
        gate.add(plate="رقص 9058", owner_name="Former contractor", category="blacklist")
        first = gate_pass(gate, "بجد 1234", finished=False)       # a misread
        assert first.status == "unknown"
        gate.amend_pass(first.id, plate="رقص 9058", confidence=0.95, votes=9,
                        needs_review=False, today=TODAY)
        gate.finish_pass(first.id)
        drain(world.service)
        (body,) = [body for _, body in world.courier.sent]
        assert "Blacklisted" in body and "not on the register" not in body

    def test_a_reading_corrected_to_a_registered_car_sends_nothing(self, world, gate):
        gate.add(plate="رقص 9058", owner_name="Staff member", category="staff")
        first = gate_pass(gate, "بجد 1234", finished=False)
        gate.amend_pass(first.id, plate="رقص 9058", confidence=0.95, votes=9,
                        needs_review=False, today=TODAY)
        gate.finish_pass(first.id)
        drain(world.service)
        assert world.alerts.recent(10) == []

    def test_a_person_correcting_the_plate_sends_nothing_more(self, world, gate):
        """Somebody already looked at the photograph (decided 11 Sep 2026)."""
        record = gate_pass(gate, "بجد 1234")
        drain(world.service)
        assert len(world.courier.sent) == 1
        gate.add(plate="رقص 9058", owner_name="Former contractor", category="blacklist")
        assert gate.set_plate(record.id, "رقص 9058", "Guard A", TODAY).status == "blacklist"
        drain(world.service)
        assert len(world.courier.sent) == 1

    def test_a_pass_is_finished_once(self, world, gate):
        record = gate_pass(gate)
        gate.finish_pass(record.id)
        drain(world.service)
        assert len(world.courier.sent) == 1

    def test_finishing_a_pass_that_is_not_there_is_nothing(self, world, gate):
        assert gate.finish_pass("no-such-pass") is None
        drain(world.service)
        assert world.alerts.recent(10) == []


class TestACarInViewWhenTheEngineStopped:
    """A hard kill runs no `finally`, so a car still in view never has its
    reading finished. The next start closes such passes, and their message is
    a failed row for exactly the people who would have had it - a row, never
    a missing row (P9-FR-023) - and never sent late: a gate message gives a
    time and no date, so a late one would read as today."""

    @staticmethod
    def restart(world, gate, before=None):
        leftovers = gate.close_unfinished(before=before or datetime.now(timezone.utc))
        world.service.not_sent(leftovers, "engine_stopped")
        drain(world.service)
        return leftovers

    def test_it_is_logged_as_not_sent_and_never_sent(self, world, gate):
        gate_pass(gate, finished=False)
        assert len(self.restart(world, gate)) == 1
        assert world.courier.sent == []
        assert [(r.recipient_name, r.outcome, r.reason) for r in world.alerts.recent(10)] == [
            ("Gate supervisor", "failed", "engine_stopped")]

    def test_it_is_closed_once(self, world, gate):
        gate_pass(gate, finished=False)
        self.restart(world, gate)
        assert self.restart(world, gate) == []
        assert len(world.alerts.recent(10)) == 1

    def test_a_closed_pass_cannot_then_be_finished_and_sent(self, world, gate):
        left = gate_pass(gate, finished=False)
        self.restart(world, gate)
        gate.finish_pass(left.id)
        drain(world.service)
        assert world.courier.sent == []

    def test_a_finished_pass_is_not_closed(self, world, gate):
        gate_pass(gate)
        drain(world.service)
        assert self.restart(world, gate) == []
        assert len(world.courier.sent) == 1

    def test_a_pass_recorded_since_this_start_is_left_to_the_reader(self, world, gate):
        started = datetime.now(timezone.utc) - timedelta(seconds=5)
        gate_pass(gate, finished=False)
        assert self.restart(world, gate, before=started) == []

    def test_a_finish_that_could_not_read_the_pass_leaves_it_for_the_next_start(
            self, world, gate):
        """Not marked done with nothing sent: it stays open, and the next
        start logs it as not sent."""
        import sqlite3

        left = gate_pass(gate, finished=False)

        def a_disk_that_hiccups(pass_id):
            raise sqlite3.OperationalError("disk I/O error")

        gate.pass_by_id = a_disk_that_hiccups
        try:
            with pytest.raises(sqlite3.OperationalError):
                gate.finish_pass(left.id)
        finally:
            del gate.pass_by_id
        assert [p.id for p in self.restart(world, gate)] == [left.id]
        assert [r.reason for r in world.alerts.recent(10)] == ["engine_stopped"]

    def test_a_pass_that_would_not_have_been_sent_logs_nothing(self, world, gate):
        world.alerts.update_rule("vehicles", vehicle_unknown=False)
        gate_pass(gate, finished=False)
        self.restart(world, gate)
        assert world.alerts.recent(10) == []

    def test_a_gate_already_running_is_not_taken_for_a_pile_of_unfinished_passes(
            self, world, tmp_path):
        """Passes written before this column existed were sent by the old code
        at their first reading. The first start after the upgrade must not log
        every one of them as unsent."""
        import sqlite3

        from vg.events.vehicles import VehicleStore

        path = tmp_path / "old-gate.db"
        old = VehicleStore(path)
        gate_pass(old, finished=False)
        old.close_db()
        # The table as it was before `finished_at`. Copied rather than DROP
        # COLUMN, which SQLite refuses on a table whose DDL carries comments.
        conn = sqlite3.connect(path)
        columns = ", ".join(row[1] for row in conn.execute("PRAGMA table_info(vehicle_pass)")
                            if row[1] != "finished_at")
        conn.executescript(
            "ALTER TABLE vehicle_pass RENAME TO pass_before;"
            f" CREATE TABLE vehicle_pass AS SELECT {columns} FROM pass_before;"
            " DROP TABLE pass_before;")
        conn.close()

        upgraded = VehicleStore(path)
        try:
            assert upgraded.close_unfinished(before=datetime.now(timezone.utc)) == []
        finally:
            upgraded.close_db()


class CamWorker:
    def __init__(self, status, last_frame_at):
        self.status = status
        self.source = type("S", (), {})()
        self.source.health = type("H", (), {"last_frame_at": last_frame_at})()


class Registry:
    def __init__(self, workers):
        self.workers = workers


class Clockwork:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now


@pytest.fixture
def cameras(world):
    world.alerts.update_rule("camera", email=True)
    only_recipient(world, "office@school.example", "Office")
    return world


def camera_service(world, workers, clock):
    service = AlertService(AlertsConfig(), world.alerts, Registry(workers),
                           FixedClock(180), senders=lambda channel: world.courier,
                           now=clock)
    service.bind(camera_name=lambda camera_id: "Yard camera")
    service.start(run_thread=False)
    return service


class TestCameraMessages:
    def test_four_minutes_dark_is_nothing_five_is_one_message(self, cameras):
        dark_since = START
        cam = CamWorker("down", dark_since)
        clock = Clockwork(START + timedelta(minutes=4))
        service = camera_service(cameras, {"cam-a": cam}, clock)
        drain(service)
        assert cameras.alerts.recent(10) == []

        clock.now = START + timedelta(minutes=5)
        drain(service)
        clock.now = START + timedelta(minutes=30)
        drain(service)
        rows = cameras.alerts.recent(10)
        assert [r.event_key.split(":")[2] for r in rows] == ["down"]
        assert "no picture" in cameras.courier.sent[0][1].lower()

    def test_back_is_one_more_message(self, cameras):
        cam = CamWorker("down", START)
        clock = Clockwork(START + timedelta(minutes=6))
        service = camera_service(cameras, {"cam-a": cam}, clock)
        drain(service)
        cam.status = "ok"
        clock.now = START + timedelta(minutes=9)
        drain(service)
        drain(service)
        states = sorted(r.event_key.split(":")[2] for r in cameras.alerts.recent(10))
        assert states == ["down", "up"]
        assert "is back" in cameras.courier.sent[-1][1]

    def test_a_restart_while_dark_says_nothing_new_and_then_back(self, cameras):
        cam = CamWorker("down", START)
        clock = Clockwork(START + timedelta(minutes=6))
        drain(camera_service(cameras, {"cam-a": cam}, clock))
        assert len(cameras.alerts.recent(10)) == 1

        # The engine restarts: the new process has had no frame at all.
        restarted = CamWorker("down", None)
        clock.now = START + timedelta(minutes=20)
        again = camera_service(cameras, {"cam-a": restarted}, clock)
        clock.now = START + timedelta(minutes=40)
        drain(again)
        assert len(cameras.alerts.recent(10)) == 1, "still dark: nothing new"

        restarted.status = "ok"
        drain(again)
        states = sorted(r.event_key.split(":")[2] for r in cameras.alerts.recent(10))
        assert states == ["down", "up"]

    def test_a_hiccup_shorter_than_the_window_sends_nothing(self, cameras):
        cam = CamWorker("down", START)
        clock = Clockwork(START + timedelta(minutes=3))
        service = camera_service(cameras, {"cam-a": cam}, clock)
        drain(service)
        cam.status = "ok"
        clock.now = START + timedelta(minutes=4)
        drain(service)
        assert cameras.alerts.recent(10) == []


class TestOtherFeaturesSendNothing:
    """Lost bag, tracking and counting cannot send: nothing of theirs can even
    reach the sender. The stores that raise events only call a hook they are
    handed; only the alert package, the API layer and the lifespan import it."""

    def test_only_the_alert_package_and_the_api_reach_the_sender(self):
        import ast

        root = Path(__file__).resolve().parents[1] / "vg"
        allowed = {"vg/api/live.py", "vg/api/app.py", "vg/api/store.py"}
        offenders = []
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(root.parent).as_posix()
            if rel.startswith("vg/alerts/") or rel in allowed:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                elif isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                if any(name.startswith("vg.alerts") for name in names):
                    offenders.append(rel)
        assert not offenders, f"these reach the sender: {offenders}"


class TestTheEngineWiresTheSender:
    """The engine's start-up is the one place the stores meet the sender.

    Every other test here hands a store its hook itself, so a swapped or
    dropped line in `lifespan` would leave them all green and ship an engine
    that sends nothing. `lifespan` cannot run here - it needs cameras and
    models - so its source is read instead, as test_smoke_start reads the
    strict-mode guards.
    """

    @staticmethod
    def _lifespan():
        import ast

        from vg.api import app as app_module

        tree = ast.parse(Path(app_module.__file__).read_text(encoding="utf-8"))
        return next(node for node in tree.body
                    if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan")

    def test_each_store_is_given_its_own_hook_and_every_hook_is_given(self):
        import ast

        wired = {ast.unparse(node.targets[0]): ast.unparse(node.value)
                 for node in ast.walk(self._lifespan())
                 if isinstance(node, ast.Assign) and len(node.targets) == 1
                 and ast.unparse(node.value).startswith("app.state.alerts.on_")}
        assert wired == {
            "app.state.scenes.on_open": "app.state.alerts.on_zone_open",
            "app.state.weapon_scenes.on_open": "app.state.alerts.on_weapon_open",
            "app.state.vehicle_store.on_pass": "app.state.alerts.on_pass",
            "app.state.stations_store.on_alert": "app.state.alerts.on_station_absent",
        }
        offered = {name for name in vars(AlertService) if name.startswith("on_")}
        assert {value.rsplit(".", 1)[1] for value in wired.values()} == offered

    def test_the_gate_reader_says_when_a_pass_is_final(self):
        """The gate hook fires from `finish_pass`, so the plate reader has to
        be told to call it, or no gate message is ever sent."""
        import ast

        from vg.api import app as app_module

        tree = ast.parse(Path(app_module.__file__).read_text(encoding="utf-8"))
        start = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name == "_start_vehicles")
        (worker,) = [node for node in ast.walk(start) if isinstance(node, ast.Call)
                     and ast.unparse(node.func) == "VehiclesWorker"]
        assert "on_final" in {kw.arg for kw in worker.keywords}
        calls = {ast.unparse(node.func) for node in ast.walk(start)
                 if isinstance(node, ast.Call)}
        assert "store.finish_pass" in calls

    def test_the_sender_is_bound_to_the_roster_started_and_stopped_before_its_store_closes(
            self):
        import ast

        calls = sorted((node for node in ast.walk(self._lifespan())
                        if isinstance(node, ast.Call)),
                       key=lambda node: (node.lineno, node.col_offset))
        names = [ast.unparse(node.func) for node in calls]
        bind = next(node for node in calls
                    if ast.unparse(node.func) == "app.state.alerts.bind")
        # The running roster's names, not engine.yaml's: a camera added in
        # Settings is named in messages the way every page names it.
        assert {kw.arg: ast.unparse(kw.value) for kw in bind.keywords} == {
            "camera_name": "store._roster_name",
            "attendance_counts": "store._attendance_counts",
            # The hours Settings saved, read at each tick (spec 022).
            "hours": "store.hours",
            # Each zone's own Notify choice (spec 025).
            "zone_channels": "store.zone_channels",
        }
        assert "app.state.alerts.start" in names
        assert names.index("alerts.stop") < names.index("alerts_store.close_db")
        # Not closed under a courier still talking: its answer is that row's
        # truth, and the process is ending anyway.
        (guard,) = [node for node in ast.walk(self._lifespan()) if isinstance(node, ast.If)
                    and any(ast.unparse(statement) == "alerts_store.close_db()"
                            for statement in node.body)]
        assert "alerts_done" in ast.unparse(guard.test)
        assert "alerts_done = alerts.stop()" in ast.unparse(self._lifespan())

    def test_the_last_runs_unfinished_passes_are_closed_and_logged(self):
        import ast

        names = {ast.unparse(node.func) for node in ast.walk(self._lifespan())
                 if isinstance(node, ast.Call)}
        assert "app.state.vehicle_store.close_unfinished" in names
        assert "app.state.alerts.not_sent" in names
