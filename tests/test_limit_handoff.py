"""scripts/limit-handoff.py, the StopFailure hook that starts keepgoing --auto.
Network and osascript are mocked; nothing real opens."""
import io
import json
import os
import time

import pytest

from conftest import ROOT, load_module

hook = load_module("limit_handoff", ROOT / "scripts" / "limit-handoff.py")


@pytest.fixture
def h(tmp_path, monkeypatch):
    """The hook with its log and stamps in tmp_path, and every way out of the process mocked."""
    monkeypatch.setattr(hook, "LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(hook, "LOG", str(tmp_path / "logs" / "limit-handoff.log"))
    monkeypatch.setattr(hook, "STAMPS", str(tmp_path / "logs" / "stamps"))
    calls = {"urlopen": [], "osascript": []}

    def no_network(req, timeout):
        calls["urlopen"].append((req, timeout))
        raise OSError("connection refused")

    class Done:
        returncode, stderr = 0, ""

    def fake_run(cmd, **kw):
        calls["osascript"].append(cmd)
        return Done()

    monkeypatch.setattr(hook.urllib.request, "urlopen", no_network)
    monkeypatch.setattr(hook.subprocess, "run", fake_run)
    calls["folder"] = str(tmp_path / "my project")
    os.makedirs(calls["folder"])
    return calls


def payload(cwd, error="rate_limit"):
    return {"hook_event_name": "StopFailure", "session_id": "s1", "cwd": cwd, "error": error}


def log_lines(h):
    with open(hook.LOG) as f:
        return [json.loads(line) for line in f]


@pytest.mark.parametrize("error", ["server_error", "authentication_failed", "", None])
def test_other_errors_are_logged_and_ignored(h, error):
    assert hook.handle(payload(h["folder"], error), {}) == "ignored"
    assert not h["urlopen"] and not h["osascript"]
    assert log_lines(h)[0]["payload"]["error"] == error


def test_opt_out(h):
    assert hook.handle(payload(h["folder"]), {"KEEPGOING_AUTO": "0"}) == "off"
    assert not h["urlopen"] and not h["osascript"]


def test_missing_folder_does_nothing(h, tmp_path):
    assert hook.handle(payload(str(tmp_path / "gone")), {}) == "no-folder"
    assert not h["osascript"]


def test_falls_back_to_terminal_in_the_folder(h):
    assert hook.handle(payload(h["folder"]), {}) == "terminal"
    (cmd,) = h["osascript"]
    assert cmd[0] == "osascript"
    script = cmd[2]
    assert 'tell application "Terminal" to do script' in script
    assert "cd '" + h["folder"] + "'" in script  # the space in the name is quoted
    assert script.rstrip('"').endswith("keepgoing --auto")


def test_moonstone_request_has_x_dock_and_wins(h, monkeypatch):
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def dock(req, timeout):
        seen.update(url=req.full_url, method=req.get_method(), timeout=timeout,
                    dock=req.get_header("X-dock"), body=json.loads(req.data))
        return Resp(b'{"id": "abc123"}')

    monkeypatch.setattr(hook.urllib.request, "urlopen", dock)
    conf = {"MOONSTONE_URL": "http://127.0.0.1:9999/", "MOONSTONE_LAUNCHER": "kg"}
    assert hook.handle(payload(h["folder"]), conf) == "moonstone"
    assert seen["url"] == "http://127.0.0.1:9999/api/launch"
    assert (seen["method"], seen["dock"], seen["timeout"]) == ("POST", "1", 8)
    assert seen["body"] == {"launcher": "kg", "text": h["folder"], "focus": True}
    assert not h["osascript"]


def test_moonstone_without_an_id_falls_back(h, monkeypatch):
    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(hook.urllib.request, "urlopen", lambda req, timeout: Resp(b"{}"))
    assert hook.handle(payload(h["folder"]), {}) == "terminal"
    assert len(h["osascript"]) == 1


def test_moonstone_down_falls_back_to_terminal(h):
    assert hook.handle(payload(h["folder"]), {}) == "terminal"
    assert len(h["urlopen"]) == 1
    assert h["urlopen"][0][0].get_header("X-dock") == "1"
    assert len(h["osascript"]) == 1


def test_moonstone_can_be_skipped(h):
    assert hook.handle(payload(h["folder"]), {"MOONSTONE": "0"}) == "terminal"
    assert not h["urlopen"]


def test_stamp_allows_one_handoff_per_folder_per_half_hour(h, tmp_path):
    other = str(tmp_path / "other")
    os.makedirs(other)
    assert hook.handle(payload(h["folder"]), {}) == "terminal"
    assert hook.handle(payload(h["folder"]), {}) == "recent"
    assert hook.handle(payload(other), {}) == "terminal"
    assert len(h["osascript"]) == 2


def test_stamp_expires(h):
    now = time.time()
    assert hook.recently_handed_off(h["folder"], now - hook.QUIET_SECONDS - 5) is False
    assert hook.recently_handed_off(h["folder"], now) is False
    assert hook.recently_handed_off(h["folder"], now + 60) is True


def test_terminal_failure_is_reported(h, monkeypatch):
    class Failed:
        returncode, stderr = 1, "not allowed"
    monkeypatch.setattr(hook.subprocess, "run", lambda cmd, **kw: Failed())
    assert hook.handle(payload(h["folder"]), {}) == "failed"


def test_settings_reads_the_env_file_under_the_environment(tmp_path, monkeypatch):
    conf = tmp_path / "keepgoing.env"
    conf.write_text("# comment\nKEEPGOING_AUTO=0\nexport MOONSTONE_LAUNCHER='kg'\nOPENROUTER_API_KEY=x\n")
    monkeypatch.setattr(hook, "CONF", str(conf))
    monkeypatch.setenv("OPENROUTER_API_KEY", "from-env")
    s = hook.settings()
    assert (s["KEEPGOING_AUTO"], s["MOONSTONE_LAUNCHER"], s["OPENROUTER_API_KEY"]) == ("0", "kg", "from-env")


def test_main_never_fails(h, monkeypatch):
    monkeypatch.setattr(hook.sys, "stdin", io.StringIO("not json"))
    monkeypatch.setattr(hook, "settings", lambda: {})
    with pytest.raises(SystemExit) as e:
        hook.main()
    assert e.value.code == 0
    assert log_lines(h)[-1]["result"] == "ignored"
