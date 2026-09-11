"""Alert delivery (P9): the engine tells people by WhatsApp, SMS and email.

Five kinds of alert leave the building - a knife entry opening and its
verdict, a restricted-zone scene, a gate alert, a camera gone dark, and the
noon attendance report - each as one short message per recipient, in that
recipient's language, with a row in the delivery log saying what happened.

Three rules shape everything in here:

**Nothing runs on a camera thread.** A store that commits an event calls one
hook, and the hook does one `put_nowait`. A single sender thread does the rest,
so a courier that is slow or down costs detection nothing (constitution II).

**Nothing about a minor enters an `AlertEvent`.** `events.ALLOWED_FACTS` is
the whole vocabulary a message can draw on; there is no field a student's
name, a face or a file path can travel in (constitution IV).

**"Sent" means the courier accepted it.** Every attempt is a row in the
log - queued, sent with the courier's id, failed with the courier's words, or
skipped with a reason - and nothing here claims more than that.

    events.py     what happened, as a message may say it
    catalogue.py  the wording, English and Arabic
    providers.py  Twilio and Gmail, one sender per channel
    store.py      recipients, rules, the delivery log, acknowledgements
    service.py    the queue and the one sender thread
"""
