"""The console's requests reach the engine in the shape the engine reads.

`web/src/services/http.ts::request` JSON-encodes the `body` it is given. A
caller that encodes it first sends the engine one JSON *string* rather than an
object, and FastAPI refuses that with a 422 before any handler runs. That is
how editing a camera from System Health failed for every edit, and how the
Falls switches on the same page would have failed with it: the request looked
right in the code and never arrived as anything the engine could read.

`services/api.ts` is shared byte for byte with the phone app, so this guards
both.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_no_request_body_is_encoded_twice():
    for app in ("web", "mobile"):
        source = (REPO / app / "src" / "services" / "api.ts").read_text(encoding="utf-8")
        twice = re.findall(r"body:\s*JSON\.stringify\(", source)
        assert not twice, (
            f"{app}/src/services/api.ts passes an already-encoded body to "
            f"`request`, which encodes it again - the engine receives a string "
            f"and answers 422. Pass the object.")


def test_a_camera_edit_as_the_console_sends_it_is_accepted(authed):
    """The edit endpoint reads an object; one encoded twice is refused.

    Both halves, so the test above is checking the right thing: the shape
    the console now sends reaches the handler (503 in demo mode, which has
    no camera roster to edit), and the old shape never did (422).
    """
    from vg.api import app as app_module
    from vg.api.app import create_app
    from vg.api.store import MockStore

    app_module.set_store(MockStore())
    client = authed(create_app())
    good = client.patch("/sources/src-2", json={"features": ["falls"]})
    assert good.status_code == 503
    bad = client.patch("/sources/src-2", json='{"features": ["falls"]}')
    assert bad.status_code == 422
