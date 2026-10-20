"""Every word a message says, in English and Arabic.

This is the one place the engine writes sentences for people (spec
P9-FR-009). Everywhere else the engine sends codes and facts and the console
words them (P11) - but there is no console at the far end of an email, so the
sentence has to be built here, in the recipient's language.

Each template may use only the facts an `AlertEvent` allows, plus the camera's
name and the site's time. So the wording cannot reach for a student's name
even by mistake: there is nothing of the kind to reach for.

**The Arabic column was drafted by an AI and has not been read by a native
speaker.** `ARABIC_REVIEWED` stays False until Mohamed has read and corrected
every line; until then an Arabic recipient receives English and Settings says
why. `alerts.send_draft_arabic: true` in engine.yaml sends the draft anyway,
so that it can be read where it will be used - on a phone. The same rule the
console's `ar.draft.ts` follows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from vg.alerts.events import AlertEvent

#: Flip to True only after a native speaker has read every Arabic line below.
ARABIC_REVIEWED = False

#: Event messages stay short enough to read on a phone's lock screen, with a
#: 100-character link.
EVENT_LIMIT = 320
#: The noon report may be longer, but not unbounded: a report that long is a
#: page, not a message.
REPORT_LIMIT = 1500
#: Camera names, plates and people are free text; one long one must not push
#: the part that matters - "awaiting review" - off the end of a preview.
NAME_LIMIT = 40

#: The console page each kind opens. Paths from web/src/app/navigation.ts.
PAGES: dict[str, str] = {
    "weapon": "weapons",
    "intrusion": "intrusion",
    "vehicles": "vehicles",
    "camera": "system",
    "attendance": "attendance",
    "test": "",
}

LABELS: dict[str, dict[str, str]] = {
    "weapon": {"en": "Knife alert", "ar": "تنبيه سكين"},
    "intrusion": {"en": "Restricted area", "ar": "منطقة محظورة"},
    "vehicles": {"en": "Gate alert", "ar": "تنبيه البوابة"},
    "camera": {"en": "Camera", "ar": "الكاميرات"},
    "attendance": {"en": "Attendance", "ar": "الحضور"},
    "test": {"en": "Test message", "ar": "رسالة تجريبية"},
}

TEMPLATES: dict[str, dict[str, str]] = {
    "weapon.opened": {
        "en": ("Possible knife on {camera} at {time}, {confidence}% sure.\n"
               "Awaiting review — not yet confirmed by a person."),
        "ar": ("سكين محتمل على {camera} الساعة {time}، بثقة {confidence}%.\n"
               "بانتظار المراجعة — لم يؤكده أي شخص بعد."),
    },
    "weapon.confirmed": {
        "en": "The possible knife on {camera} at {since} was confirmed by {reviewer} at {time}.",
        "ar": "السكين المحتمل على {camera} الساعة {since} أكّده {reviewer} الساعة {time}.",
    },
    "weapon.dismissed": {
        "en": ("The possible knife on {camera} at {since} was a false alarm — "
               "{reviewer} checked it at {time}."),
        "ar": ("السكين المحتمل على {camera} الساعة {since} كان إنذارًا كاذبًا — "
               "راجعه {reviewer} الساعة {time}."),
    },
    "intrusion.opened": {
        "en": "Someone entered the restricted area on {camera} at {time}.",
        "ar": "دخل شخص المنطقة المحظورة على {camera} الساعة {time}.",
    },
    "vehicles.blacklist": {
        "en": ("Blacklisted car {plate} at gate {gate}, {camera}, {time}. "
               "Plate reading {confidence}% sure."),
        "ar": ("سيارة محظورة {plate} عند البوابة {gate}، {camera}، الساعة {time}. "
               "دقة قراءة اللوحة {confidence}%."),
    },
    "vehicles.unknown": {
        "en": ("Car {plate} is not on the register: gate {gate}, {camera}, {time}. "
               "Plate reading {confidence}% sure."),
        "ar": ("السيارة {plate} غير مسجلة: البوابة {gate}، {camera}، الساعة {time}. "
               "دقة قراءة اللوحة {confidence}%."),
    },
    "vehicles.expired": {
        "en": ("Car {plate} has an expired permit: gate {gate}, {camera}, {time}. "
               "Plate reading {confidence}% sure."),
        "ar": ("تصريح السيارة {plate} منتهٍ: البوابة {gate}، {camera}، الساعة {time}. "
               "دقة قراءة اللوحة {confidence}%."),
    },
    "vehicles.weak_read": {
        "en": "Plate reading uncertain — check the photo.",
        "ar": "قراءة اللوحة غير مؤكدة — راجع الصورة.",
    },
    "camera.down": {
        "en": "{camera} has shown no picture since {since}, so nothing on it is being watched.",
        "ar": "{camera} بلا صورة منذ {since}، فلا شيء عليها تحت المراقبة.",
    },
    "camera.up": {
        "en": "{camera} is back: pictures again since {time}.",
        "ar": "{camera} عادت: الصورة متاحة مجددًا منذ {time}.",
    },
    "attendance.report": {
        "en": "Attendance for {date}, as at {time}:",
        "ar": "الحضور ليوم {date} حتى الساعة {time}:",
    },
    "attendance.group": {
        "en": "{group}: {present} present, {late} late, {absent} absent",
        "ar": "{group}: {present} حاضر، {late} متأخر، {absent} غائب",
    },
    "attendance.empty": {
        "en": "Nobody is enrolled yet, so there is nothing to count.",
        "ar": "لا يوجد أحد مسجّل بعد، فلا شيء يُحصى.",
    },
    "attendance.more": {
        "en": "…and {count} more groups",
        "ar": "…و{count} مجموعات أخرى",
    },
    "test": {
        "en": "This is a test from VisionGuard. If you can read it, alerts reach you here.",
        "ar": "هذه رسالة تجريبية من VisionGuard. إن وصلتك، فالتنبيهات تصل إليك هنا.",
    },
}


#: A phone notification's title, per template (spec 020, P9-FR-102). It says
#: what is known: "Possible knife" until a person has decided, then the
#: decision. The body is only the camera and the site time.
PUSH_TITLES: dict[str, dict[str, str]] = {
    "weapon.opened": {"en": "Possible knife", "ar": "سكين محتمل"},
    "weapon.confirmed": {"en": "Knife confirmed", "ar": "تأكَّد وجود سكين"},
    "weapon.dismissed": {"en": "False alarm", "ar": "إنذار كاذب"},
    "intrusion.opened": {"en": "Restricted area entered", "ar": "دخول منطقة محظورة"},
    "vehicles.blacklist": {"en": "Gate: blacklisted car", "ar": "البوابة: سيارة محظورة"},
    "vehicles.unknown": {"en": "Gate: car not on the register",
                         "ar": "البوابة: سيارة غير مسجلة"},
    "vehicles.expired": {"en": "Gate: expired permit", "ar": "البوابة: تصريح منتهٍ"},
    "camera.down": {"en": "Camera has no picture", "ar": "كاميرا بلا صورة"},
    "camera.up": {"en": "Camera is back", "ar": "عادت الكاميرا"},
    "attendance.report": {"en": "Attendance report ready", "ar": "تقرير الحضور جاهز"},
    "test": {"en": "Test notification", "ar": "إشعار تجريبي"},
}


@dataclass(frozen=True)
class Message:
    """What one courier is handed: a subject (email only) and plain text.

    For a phone notification `subject` is its title, and `path` the phone
    app's page the notification opens.
    """

    subject: str
    body: str
    language: str
    path: str = ""


def language_for(requested: str, send_draft_arabic: bool = False) -> str:
    """The language a recipient actually gets today."""
    if requested == "ar" and (ARABIC_REVIEWED or send_draft_arabic):
        return "ar"
    return "en"


def _short(text: Any) -> str:
    text = str(text or "").strip()
    return text if len(text) <= NAME_LIMIT else text[: NAME_LIMIT - 1] + "…"


def _when(clock, when: datetime, ref: datetime) -> str:
    """HH:MM on the site's clock; with the date when it is not `ref`'s day."""
    local = clock.local(when)
    if local.date() != clock.local(ref).date():
        return f"{local.date().isoformat()} {local:%H:%M}"
    return f"{local:%H:%M}"


def _fields(event: AlertEvent, clock) -> dict[str, Any]:
    facts = event.facts
    since = facts.get("since") or event.at
    confidence = facts.get("confidence")
    return {
        "camera": _short(event.camera_name or event.camera_id or "?"),
        "time": _when(clock, event.at, event.at),
        "since": _when(clock, since, event.at),
        "date": clock.local_date(event.at),
        "confidence": round(float(confidence) * 100) if confidence is not None else "",
        "reviewer": _short(facts.get("reviewer", "")),
        "plate": _short(facts.get("plate", "")),
        "gate": facts.get("gate", ""),
    }


def _report_lines(event: AlertEvent, language: str, budget: int) -> list[str]:
    groups = event.groups or ()
    if not groups:
        return [TEMPLATES["attendance.empty"][language]]
    lines: list[str] = []
    # Room for the "…and N more" line, which may be needed at the end.
    reserve = len(TEMPLATES["attendance.more"][language]) + 6
    used = 0
    for index, group in enumerate(groups):
        line = TEMPLATES["attendance.group"][language].format(
            group=_short(group.name), present=group.present,
            late=group.late, absent=group.absent)
        remaining = len(groups) - index - 1
        if used + len(line) + 1 + (reserve if remaining else 0) > budget:
            lines.append(TEMPLATES["attendance.more"][language].format(
                count=len(groups) - index))
            return lines
        lines.append(line)
        used += len(line) + 1
    return lines


def build_push(event: AlertEvent, language: str, *, clock,
               send_draft_arabic: bool = False) -> Message:
    """One phone notification: what kind, on which camera, at what time.

    Built from `PUSH_FACTS` only - the event's other facts (a plate, a
    confidence, a reviewer) are never read here. The page it opens is the
    kind's page; the phone app has no address for a single entry.
    """
    lang = language_for(language, send_draft_arabic)
    title = PUSH_TITLES[event.template][lang]
    parts = []
    if event.camera_id:
        parts.append(_short(event.camera_name or event.camera_id))
    parts.append(_when(clock, event.at, event.at))
    if event.kind == "test":
        parts = [TEMPLATES["test"][lang]]
    return Message(subject=title, body=" · ".join(parts), language=lang,
                   path="/" + PAGES[event.kind])


def build(event: AlertEvent, language: str, *, clock, console_url: str = "",
          send_draft_arabic: bool = False) -> Message:
    """One message, for one recipient, from one event."""
    lang = language_for(language, send_draft_arabic)
    label = LABELS[event.kind][lang]
    header = f"VisionGuard · {label}"
    link = ""
    if console_url:
        link = f"{console_url.rstrip('/')}/{PAGES[event.kind]}"

    values = _fields(event, clock)
    lines = [header, TEMPLATES[event.template][lang].format(**values)]
    if event.template.startswith("vehicles.") and event.facts.get("weak_read"):
        lines.append(TEMPLATES["vehicles.weak_read"][lang])

    limit = EVENT_LIMIT
    if event.kind == "attendance":
        limit = REPORT_LIMIT
        head = "\n".join(lines)
        budget = limit - len(head) - 1 - (len(link) + 1 if link else 0)
        lines += _report_lines(event, lang, budget)

    text = "\n".join(lines)
    room = limit - (len(link) + 1 if link else 0)
    if len(text) > room:
        # Names are already bounded, so only a pathological input gets here;
        # the link survives because it is what the reader acts on.
        text = text[: room - 1] + "…"
    body = f"{text}\n{link}" if link else text
    return Message(subject=header, body=body, language=lang)
