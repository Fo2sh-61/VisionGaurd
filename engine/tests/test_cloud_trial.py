"""The cloud trial (specs/021-cloud-trial).

A free Kaggle GPU, the recorded clip, and a public tunnel address. What has to
hold there and nowhere else: the overlay is the only thing that makes it a
different engine; the developer sign-in cannot start behind a public address;
the engine serves its own console without opening anything else; the console
can tell when the engine is about to go; and clips saved on Linux still play.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vg import config as vgconfig  # noqa: E402
from vg.api import app as app_module  # noqa: E402
from vg.api.app import create_app  # noqa: E402
from vg.api.store import MockStore  # noqa: E402
from vg.auth import dev_signin  # noqa: E402
from vg.ingest import encoder  # noqa: E402

REPO = vgconfig.REPO_DIR
CLOUD = REPO / "engine" / "profiles" / "cloud.yaml"


@pytest.fixture
def overlay(tmp_path, monkeypatch):
    """`overlay(text)` -> sets VG_CONFIG_OVERLAY to a file holding `text`."""
    monkeypatch.delenv("VG_CAMERAS", raising=False)

    def _write(text: str) -> Path:
        path = tmp_path / "overlay.yaml"
        path.write_text(text, encoding="utf-8")
        monkeypatch.setenv("VG_CONFIG_OVERLAY", str(path))
        return path
    return _write


@pytest.fixture
def cloud_env(tmp_path, monkeypatch):
    """The environment tools/cloud/bootstrap.sh starts the engine with."""
    monkeypatch.setenv("VG_CONFIG_OVERLAY", "engine/profiles/cloud.yaml")
    monkeypatch.setenv("VG_CAMERAS", "cam-clip")
    monkeypatch.setenv("VG_TRIAL_DIR", str(tmp_path / "trial"))
    monkeypatch.setenv("VG_PUBLIC_URL", "https://example.trycloudflare.com")
    return tmp_path / "trial"


# ---------------------------------------------------------------------------
# the overlay
# ---------------------------------------------------------------------------

class TestOverlay:
    def test_unset_is_the_workstation(self, monkeypatch):
        monkeypatch.delenv("VG_CONFIG_OVERLAY", raising=False)
        cfg = vgconfig.load()
        assert cfg.profile == ""
        assert cfg.api.console_dir is None

    def test_mappings_merge_key_by_key(self, overlay):
        overlay("api:\n  port: 9123\n")
        cfg = vgconfig.load()
        assert cfg.api.port == 9123
        # The sibling keys of `api` came from engine.yaml, untouched.
        assert cfg.api.host == "127.0.0.1"
        assert cfg.api.cors_origins

    def test_lists_replace(self, overlay):
        overlay(
            "zones:\n"
            "  - id: only-one\n    name: Only\n    camera: cam-clip\n"
            "    rect: [0.1, 0.1, 0.2, 0.2]\n")
        cfg = vgconfig.load()
        assert [z.id for z in cfg.zones] == ["only-one"]

    def test_variables_inside_the_overlay_expand(self, overlay, monkeypatch):
        monkeypatch.setenv("VG_TEST_URL", "https://x.example")
        overlay("alerts:\n  console_url: ${VG_TEST_URL}\n")
        assert vgconfig.load().alerts.console_url == "https://x.example"

    def test_a_missing_overlay_is_an_error_not_the_workstation(self, monkeypatch, tmp_path):
        monkeypatch.setenv("VG_CONFIG_OVERLAY", str(tmp_path / "nope.yaml"))
        with pytest.raises(vgconfig.ConfigError, match="does not exist"):
            vgconfig.load()

    def test_an_overlay_that_is_not_a_mapping_is_an_error(self, overlay):
        overlay("- just\n- a list\n")
        with pytest.raises(vgconfig.ConfigError, match="mapping"):
            vgconfig.load()

    def test_profile_accepts_only_known_names(self, overlay):
        overlay("profile: kaggle\n")
        with pytest.raises(vgconfig.ConfigError, match="not a profile"):
            vgconfig.load()

    def test_console_dir_is_relative_to_the_repo(self, overlay):
        overlay("api:\n  console_dir: web/dist\n")
        assert vgconfig.load().api.console_dir == REPO / "web" / "dist"


class TestCloudProfile:
    def test_what_the_trial_runs(self, cloud_env):
        cfg = vgconfig.load()
        assert cfg.profile == "cloud"
        assert cfg.api.host == "127.0.0.1"
        assert cfg.api.console_dir == REPO / "web" / "dist"
        assert [c.id for c in cfg.cameras if c.enabled] == ["cam-clip"]
        assert cfg.alerts.console_url == "https://example.trycloudflare.com"

    def test_storage_is_throwaway(self, cloud_env):
        cfg = vgconfig.load()
        assert str(cloud_env) in cfg.storage.database_url
        assert cfg.storage.clips_dir == cloud_env / "clips"

    def test_no_keys_in_the_profile(self):
        text = CLOUD.read_text(encoding="utf-8").lower()
        for word in ("gemini", "api_key", "smtp", "password", "token"):
            assert word not in text


# ---------------------------------------------------------------------------
# the developer sign-in never starts behind a public address
# ---------------------------------------------------------------------------

class TestNoDevSignIn:
    def test_role_from_env_refuses_the_cloud_profile(self, monkeypatch):
        monkeypatch.delenv("VG_STRICT", raising=False)
        monkeypatch.setenv(dev_signin.ENV, "admin")
        with pytest.raises(RuntimeError, match="cloud profile"):
            dev_signin.role_from_env("cloud")

    def test_the_engine_will_not_build(self, cloud_env, monkeypatch):
        monkeypatch.delenv("VG_STRICT", raising=False)
        monkeypatch.setenv(dev_signin.ENV, "admin")
        app_module.set_store(MockStore())
        with pytest.raises(RuntimeError, match="cloud profile"):
            create_app()

    def test_an_overlay_that_will_not_load_counts_as_the_cloud(self, monkeypatch, tmp_path):
        """Not knowing where we are is not "a developer's laptop"."""
        monkeypatch.delenv("VG_STRICT", raising=False)
        monkeypatch.setenv(dev_signin.ENV, "admin")
        monkeypatch.setenv("VG_CONFIG_OVERLAY", str(tmp_path / "missing.yaml"))
        app_module.set_store(MockStore())
        with pytest.raises(RuntimeError, match="cloud profile"):
            create_app()

    def test_the_workstation_is_unchanged(self, monkeypatch):
        monkeypatch.delenv("VG_STRICT", raising=False)
        monkeypatch.delenv("VG_CONFIG_OVERLAY", raising=False)
        monkeypatch.setenv(dev_signin.ENV, "admin")
        assert dev_signin.role_from_env("") == "admin"


# ---------------------------------------------------------------------------
# one address: the engine serves the console
# ---------------------------------------------------------------------------

NAVIGATE = {"Sec-Fetch-Mode": "navigate", "Accept": "text/html,application/xhtml+xml"}


@pytest.fixture
def console_dir(tmp_path):
    folder = tmp_path / "dist"
    (folder / "assets").mkdir(parents=True)
    (folder / "index.html").write_text("<!doctype html><div id=root></div>")
    (folder / "assets" / "index-abc123.js").write_text("console.log(1)")
    (folder / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("outside the folder")
    return folder


@pytest.fixture
def console_app(overlay, console_dir, user_store, monkeypatch):
    monkeypatch.delenv(dev_signin.ENV, raising=False)
    overlay(f"api:\n  console_dir: {console_dir.as_posix()}\n")
    app_module.set_store(MockStore())
    application = create_app()
    application.state.users = user_store
    return application


class TestConsole:
    def test_the_page_needs_no_session(self, console_app):
        response = TestClient(console_app).get("/")
        assert response.status_code == 200
        assert "id=root" in response.text
        assert response.headers["cache-control"] == "no-cache"

    def test_assets_and_top_level_files_need_no_session(self, console_app):
        client = TestClient(console_app)
        assert client.get("/assets/index-abc123.js").status_code == 200
        assert client.get("/favicon.svg").status_code == 200

    def test_a_reload_on_a_console_route_gets_the_page(self, console_app):
        response = TestClient(console_app).get("/cameras", headers=NAVIGATE)
        assert response.status_code == 200
        assert "id=root" in response.text

    def test_the_api_is_still_closed(self, console_app):
        """A fetch is not a navigation: same path, same refusal as ever."""
        assert TestClient(console_app).get("/cameras").status_code == 401

    def test_nothing_outside_the_folder(self, console_app):
        client = TestClient(console_app)
        assert client.get("/../secret.txt").status_code in (401, 404)
        assert client.get("/assets/../../secret.txt").status_code in (401, 404)
        assert "outside" not in client.get("/%2e%2e/secret.txt").text

    def test_the_engines_own_pages_stay_the_engines(self, console_app):
        response = TestClient(console_app).get("/openapi.json", headers=NAVIGATE)
        assert "id=root" not in response.text

    def test_writes_are_never_served_from_the_folder(self, console_app):
        assert TestClient(console_app).post("/").status_code != 200

    def test_an_unbuilt_console_says_so(self, overlay, tmp_path, user_store, monkeypatch):
        monkeypatch.delenv(dev_signin.ENV, raising=False)
        overlay(f"api:\n  console_dir: {(tmp_path / 'empty').as_posix()}\n")
        app_module.set_store(MockStore())
        application = create_app()
        application.state.users = user_store
        response = TestClient(application).get("/")
        assert response.status_code == 503
        assert "not built" in response.text
        # The API still runs.
        assert TestClient(application).get("/healthz").status_code == 200

    def test_the_workstation_serves_no_console(self, monkeypatch, user_store):
        monkeypatch.delenv("VG_CONFIG_OVERLAY", raising=False)
        monkeypatch.delenv(dev_signin.ENV, raising=False)
        app_module.set_store(MockStore())
        application = create_app()
        application.state.users = user_store
        assert TestClient(application).get("/", headers=NAVIGATE).status_code == 401


# ---------------------------------------------------------------------------
# /healthz: a clock to compare against, and when the engine goes
# ---------------------------------------------------------------------------

@pytest.fixture
def plain_app(monkeypatch):
    monkeypatch.delenv("VG_CONFIG_OVERLAY", raising=False)
    monkeypatch.delenv(dev_signin.ENV, raising=False)
    app_module.set_store(MockStore())
    return create_app()


class TestHealthz:
    def test_always_carries_the_server_clock(self, plain_app, monkeypatch):
        monkeypatch.delenv("VG_SESSION_ENDS_AT", raising=False)
        before = datetime.now(timezone.utc).timestamp() * 1000
        body = TestClient(plain_app).get("/healthz").json()
        after = datetime.now(timezone.utc).timestamp() * 1000
        assert before - 5 <= body["now"] <= after + 5
        assert body["ok"] is True
        assert "endsAt" not in body and "stopping" not in body

    def test_a_known_end_is_announced(self, plain_app, monkeypatch):
        ends = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(microsecond=0)
        monkeypatch.setenv("VG_SESSION_ENDS_AT", ends.isoformat())
        body = TestClient(plain_app).get("/healthz").json()
        assert datetime.fromisoformat(body["endsAt"]) == ends
        assert body["stopping"] is False

    @pytest.mark.parametrize("value", ["tomorrow", "2026-11-01T18:40:00"])
    def test_an_end_that_cannot_be_trusted_is_ignored(self, plain_app, monkeypatch, value):
        monkeypatch.setenv("VG_SESSION_ENDS_AT", value)
        response = TestClient(plain_app).get("/healthz")
        assert response.status_code == 200
        assert "endsAt" not in response.json()

    def test_stopping_once_shutdown_starts(self, plain_app, monkeypatch):
        monkeypatch.setenv("VG_SESSION_ENDS_AT", "2030-01-01T00:00:00+00:00")
        app_module.SHUTTING_DOWN.set()
        try:
            assert TestClient(plain_app).get("/healthz").json()["stopping"] is True
        finally:
            app_module.SHUTTING_DOWN.clear()

    def test_still_public(self, plain_app, monkeypatch):
        monkeypatch.setenv("VG_SESSION_ENDS_AT", "2030-01-01T00:00:00+00:00")
        assert TestClient(plain_app).get("/healthz").status_code == 200


# ---------------------------------------------------------------------------
# the first administrator, with nobody at the keyboard
# ---------------------------------------------------------------------------

class TestCreateUserFromEnvironment:
    def _run(self, tmp_path, monkeypatch, password: str | None):
        monkeypatch.setenv("VG_TRIAL_DIR", str(tmp_path))
        monkeypatch.setenv("VG_PUBLIC_URL", "https://x.example")
        monkeypatch.setenv("VG_CONFIG_OVERLAY", "engine/profiles/cloud.yaml")
        if password is None:
            monkeypatch.delenv("VG_TEST_ADMIN_PASSWORD", raising=False)
        else:
            monkeypatch.setenv("VG_TEST_ADMIN_PASSWORD", password)
        sys.path.insert(0, str(REPO / "engine" / "tools"))
        import create_user
        return create_user.main([
            "--email", "admin@trial.local", "--name", "Trial admin",
            "--role", "admin", "--password-env", "VG_TEST_ADMIN_PASSWORD"])

    def test_creates_the_account_without_a_prompt(self, tmp_path, monkeypatch):
        monkeypatch.setattr("getpass.getpass", lambda *_: pytest.fail("prompted"))
        assert self._run(tmp_path, monkeypatch, "a-long-enough-trial-password") == 0
        from vg.auth.store import UserStore
        store = UserStore(tmp_path / "visionguard.db")
        try:
            assert [u.email for u in store.users()] == ["admin@trial.local"]
        finally:
            store.close()

    def test_an_empty_variable_is_refused(self, tmp_path, monkeypatch):
        assert self._run(tmp_path, monkeypatch, None) == 1


# ---------------------------------------------------------------------------
# clips saved on Linux play in the browser
# ---------------------------------------------------------------------------

class TestLinuxEncoder:
    def test_linux_tries_the_ffmpeg_program_before_mp4v(self, monkeypatch):
        monkeypatch.setattr(encoder.sys, "platform", "linux")
        assert encoder.candidates() == (
            encoder.FFMPEG_H264, encoder.PIPE_X264, encoder.FFMPEG_MP4V)

    def test_windows_order_is_unchanged(self, monkeypatch):
        monkeypatch.setattr(encoder.sys, "platform", "win32")
        assert encoder.candidates() == (
            encoder.MSMF_H264, encoder.FFMPEG_H264, encoder.FFMPEG_MP4V)

    def test_an_ffmpeg_without_x264_first_on_path_does_not_hide_one_with_it(self, monkeypatch):
        """Kaggle, first run: PATH's ffmpeg had no libx264; /usr/bin's did."""
        monkeypatch.setattr(encoder, "_ffmpeg_candidates",
                            lambda: ["/opt/conda/bin/ffmpeg", "/usr/bin/ffmpeg"])

        class Listed:
            def __init__(self, exe):
                self.stdout = (b" V..... libx264  H.264\n" if exe == "/usr/bin/ffmpeg"
                               else b" V..... mpeg4  MPEG-4\n")

        monkeypatch.setattr(encoder.subprocess, "run", lambda cmd, **_: Listed(cmd[0]))
        encoder._ffmpeg_with_x264.cache_clear()
        try:
            assert encoder._ffmpeg_with_x264() == "/usr/bin/ffmpeg"
        finally:
            encoder._ffmpeg_with_x264.cache_clear()

    def test_vg_ffmpeg_is_asked_first(self, monkeypatch, tmp_path):
        exe = tmp_path / "ffmpeg"
        exe.write_text("")
        monkeypatch.setenv("VG_FFMPEG", str(exe))
        assert encoder._ffmpeg_candidates()[0] == str(exe)

    def test_no_ffmpeg_means_not_opened(self, monkeypatch, tmp_path):
        monkeypatch.setattr(encoder, "_ffmpeg_with_x264", lambda: None)
        writer = encoder.PipeWriter(tmp_path / "x.mp4", 15, 64, 64)
        assert not writer.isOpened()
        writer.release()

    def test_the_pipe_writes_h264_a_browser_plays(self, tmp_path):
        """Real frames through the real program, then ask ffprobe what it wrote."""
        if encoder._ffmpeg_with_x264() is None or shutil.which("ffprobe") is None:
            pytest.skip("ffmpeg with libx264, or ffprobe, is not on PATH")
        path = tmp_path / "clip.mp4"
        writer = encoder.PipeWriter(path, 15, 320, 240)
        assert writer.isOpened()
        for i in range(30):
            frame = np.full((240, 320, 3), i * 8, dtype=np.uint8)
            writer.write(frame)
        writer.release()

        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name,pix_fmt,nb_frames",
             "-of", "json", str(path)],
            capture_output=True, check=True)
        stream = json.loads(probe.stdout)["streams"][0]
        assert stream["codec_name"] == "h264"
        assert stream["pix_fmt"] == "yuv420p"
        assert int(stream["nb_frames"]) == 30

    def test_open_writer_reaches_the_pipe_on_linux(self, monkeypatch, tmp_path):
        """With OpenCV's own avc1 refused, Linux lands on the pipe, not on mp4v."""
        if encoder._ffmpeg_with_x264() is None:
            pytest.skip("ffmpeg with libx264 is not on PATH")
        monkeypatch.setattr(encoder.sys, "platform", "linux")
        encoder._reset_for_tests()
        real = encoder.cv2.VideoWriter

        class Refused:
            def __init__(self, *args, **kwargs):
                pass

            def isOpened(self):  # noqa: N802
                return False

            def release(self):
                pass

        def fake(path, backend, fourcc, *rest):
            if fourcc == encoder.cv2.VideoWriter_fourcc(*"avc1"):
                return Refused()
            return real(path, backend, fourcc, *rest)

        monkeypatch.setattr(encoder.cv2, "VideoWriter", fake)
        try:
            writer, chosen = encoder.open_writer(tmp_path / "c.mp4", 15, 64, 64)
            assert chosen is encoder.PIPE_X264
            writer.release()
        finally:
            encoder._reset_for_tests()


# ---------------------------------------------------------------------------
# the scripts and the notebook
# ---------------------------------------------------------------------------

CLOUD_TOOLS = REPO / "tools" / "cloud"
NOTEBOOK = REPO / "cloud" / "visionguard_trial.ipynb"


class TestScripts:
    @pytest.mark.parametrize("name", ["bootstrap.sh", "stop.sh"])
    def test_shell_syntax(self, name):
        bash = shutil.which("bash")
        if bash is None:
            pytest.skip("no bash on this machine")
        result = subprocess.run([bash, "-n", str(CLOUD_TOOLS / name)],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize("name", ["bootstrap.sh", "stop.sh"])
    def test_unix_line_endings(self, name):
        """A CRLF shell script fails on Linux with `$'\\r': command not found`."""
        assert b"\r\n" not in (CLOUD_TOOLS / name).read_bytes()

    def test_bootstrap_never_runs_the_dev_sign_in(self):
        text = (CLOUD_TOOLS / "bootstrap.sh").read_text(encoding="utf-8")
        assert "unset VG_DEV_SIGNIN" in text
        assert "VG_DEV_SIGNIN=" not in text

    def test_the_admin_goes_into_the_trial_database(self):
        """Kaggle, first full run: the admin landed in engine/data/visionguard.db,
        the engine read the trial's database, and sign-in was 401."""
        text = (CLOUD_TOOLS / "bootstrap.sh").read_text(encoding="utf-8")
        admin = text[text.index("create_admin() {"):]
        admin = admin[:admin.index("\n}\n")]
        assert "trial_env" in admin
        assert '"$TRIAL/visionguard.db"' in admin  # and it checks where it went
        # trial_env reads the tunnel's address, so the tunnel comes first.
        assert text.index('step "Tunnel"') < text.index('step "Administrator account"')

    def test_what_keeps_running_survives_a_stopped_cell(self):
        """Kaggle, first run: stopping cell 4 sent SIGINT to the whole process
        group and the engine and the tunnel stopped with it."""
        text = (CLOUD_TOOLS / "bootstrap.sh").read_text(encoding="utf-8")
        launches = [line for line in text.splitlines() if "nohup " in line]
        assert len(launches) == 4  # tunnel, engine, stop timer, idle stop
        assert all("nohup setsid " in line for line in launches), launches

    def test_a_day_is_four_and_a_half_hours(self):
        """Owner's choice, 31 Oct 2026: six working days x 4.5 h = 27 of the
        ~30 weekly GPU hours. 11.5 h would spend a third of a week in one day."""
        text = (CLOUD_TOOLS / "bootstrap.sh").read_text(encoding="utf-8")
        assert 'hours="${VG_TRIAL_HOURS:-4.5}"' in text

    def test_idle_stop_is_off_unless_asked_for(self):
        """Owner, 31 Oct 2026: start with Run All, stop with the power button.
        In an interactive session an idle stop ended the engine but not
        Kaggle's clock, so it is off unless VG_IDLE_MINUTES is set."""
        text = (CLOUD_TOOLS / "bootstrap.sh").read_text(encoding="utf-8")
        idle = text[text.index("start_idle_watch() {"):]
        idle = idle[:idle.index("\n}\n")]
        assert '-z "${VG_IDLE_MINUTES:-}"' in idle
        assert idle.index("return 0") < idle.index("nohup setsid")

    def test_the_notebook_says_start_and_stop_in_two_buttons(self):
        sys.path.insert(0, str(CLOUD_TOOLS))
        import make_notebook
        assert "**START**" in make_notebook.INTRO and "Run All" in make_notebook.INTRO
        assert "**STOP**" in make_notebook.INTRO and "power button" in make_notebook.INTRO

    def test_the_run_saves_and_ends_by_itself(self):
        """One click: when the engine stops, the keep-alive cell saves and the
        run ends, so a background run gives the GPU back at once."""
        sys.path.insert(0, str(CLOUD_TOOLS))
        import make_notebook
        keep_alive = make_notebook.KEEP_ALIVE
        assert "break" in keep_alive and "stop.sh" in keep_alive.split("break", 1)[1]
        assert "stop.sh" in make_notebook.START and "SystemExit" in make_notebook.START

    def test_bootstrap_downloads_no_model(self):
        """Settled rule: the owner supplies every model."""
        text = (CLOUD_TOOLS / "bootstrap.sh").read_text(encoding="utf-8")
        for line in text.splitlines():
            if "curl" in line or "wget" in line:
                assert not any(ext in line for ext in (".pt", ".onnx", ".pth", ".engine"))

    def test_the_notebook_is_current_and_carries_no_secret(self):
        sys.path.insert(0, str(CLOUD_TOOLS))
        import make_notebook
        book = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        assert book == make_notebook.notebook(), "run tools/cloud/make_notebook.py"
        text = "".join("".join(cell["source"]) for cell in book["cells"])
        for word in ("GEMINI", "SMTP", "api_key", "API_KEY"):
            assert word not in text
        # The only secret it names is the admin password, and it never prints it.
        assert 'get_secret("VG_ADMIN_PASSWORD")' in text
        assert 'print(env["VG_ADMIN_PASSWORD"])' not in text

    def test_pack_builds_from_a_commit(self):
        text = (CLOUD_TOOLS / "pack.ps1").read_text(encoding="utf-8")
        assert "git archive" in text and "--untracked-files=no" in text
        # Kaggle unpacks nested zips; one unpacked onto a real folder and
        # failed the upload ("Directory already exists: loiterwatch").
        assert "':(exclude,glob)**/*.zip'" in text


@pytest.fixture(autouse=True)
def _no_leaked_env():
    """create_app reads the environment; keep each test's to itself."""
    yield
    for name in ("VG_SESSION_ENDS_AT",):
        os.environ.pop(name, None)
