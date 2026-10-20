#!/usr/bin/env python3
"""limit-handoff: a Claude Code StopFailure hook that runs `keepgoing --auto` for you.

When Claude Code stops because you hit your usage limit, this opens a new window in the same folder
and carries the conversation on with a free cloud model or a model on this Mac (see bin/keepgoing).

Add it to ~/.claude/settings.json (docs/AUTO-HANDOFF.md has the full walkthrough):

  "hooks": {
    "StopFailure": [
      { "matcher": "rate_limit",
        "hooks": [ { "type": "command",
                     "command": "python3 ~/claude-code-local/scripts/limit-handoff.py" } ] }
    ]
  }

Where the new window opens:
  1. Moonstone (https://github.com/nicedreamzapp/moonstone), if a dock answers at MOONSTONE_URL
     (default http://127.0.0.1:8899). It starts the launcher named by MOONSTONE_LAUNCHER
     (default "keep-going") and sends it the folder as the first message.
  2. Otherwise a macOS Terminal window in that folder.

Settings (environment or ~/.config/claude-code-local/keepgoing.env):
  KEEPGOING_AUTO=0        turn the hook off without editing settings.json
  MOONSTONE_URL           where to look for a Moonstone dock
  MOONSTONE_LAUNCHER      which Moonstone launcher to start
  MOONSTONE=0             skip Moonstone and always use Terminal

Every payload is logged to ~/.claude/logs/limit-handoff.log. The hook always exits 0, so it can
never get in Claude Code's way.
"""
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.realpath(__file__))
KEEPGOING = os.path.join(os.path.dirname(HERE), "bin", "keepgoing")
CONF = os.path.expanduser("~/.config/claude-code-local/keepgoing.env")
LOG_DIR = os.path.expanduser("~/.claude/logs")
LOG = os.path.join(LOG_DIR, "limit-handoff.log")
STAMPS = os.path.join(LOG_DIR, "limit-handoff-stamps")
# A capped account hits the limit again in every open chat. Without this, one bad afternoon opens
# ten windows. One handoff per folder per half hour is plenty.
QUIET_SECONDS = 30 * 60
MOONSTONE_TIMEOUT = 8


def settings():
    """keepgoing.env first, then the real environment on top (same order as bin/keepgoing)."""
    conf = {}
    try:
        with open(CONF) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    conf[k.strip().removeprefix("export ").strip()] = v.strip().strip("'\"")
    except OSError:
        pass
    conf.update(os.environ)
    return conf


def log(entry):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG, "a") as f:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), **entry}) + "\n")
    except OSError:
        pass


def recently_handed_off(cwd, now=None):
    """True if this folder already got a handoff in the last QUIET_SECONDS; otherwise stamp it."""
    now = time.time() if now is None else now
    stamp = os.path.join(STAMPS, hashlib.sha1(cwd.encode()).hexdigest()[:16])
    try:
        if now - os.path.getmtime(stamp) < QUIET_SECONDS:
            return True
    except OSError:
        pass
    os.makedirs(STAMPS, exist_ok=True)
    with open(stamp, "w") as f:
        f.write(cwd + "\n")
    os.utime(stamp, (now, now))
    return False


def try_moonstone(cwd, conf):
    """Ask a Moonstone dock to start the keep-going launcher. True if it said yes."""
    url = conf.get("MOONSTONE_URL", "http://127.0.0.1:8899").rstrip("/") + "/api/launch"
    body = {"launcher": conf.get("MOONSTONE_LAUNCHER", "keep-going"), "text": cwd, "focus": True}
    # Moonstone answers every POST without x-dock with a bare 403. Leaving it off once broke these
    # launches with nothing in any log, so it is set here on purpose.
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", "x-dock": "1"})
    try:
        with urllib.request.urlopen(req, timeout=MOONSTONE_TIMEOUT) as r:
            reply = json.load(r)
    except Exception as e:  # no dock, unknown launcher (400), timeout: Terminal takes over
        log({"moonstone": "no", "why": str(e)[:200]})
        return False
    ok = bool(reply.get("id") or reply.get("opened"))
    log({"moonstone": "yes" if ok else "no", "reply": reply})
    return ok


def open_terminal(cwd):
    """A new macOS Terminal window in cwd running keepgoing --auto."""
    cmd = f"cd {shlex.quote(cwd)} && {shlex.quote(KEEPGOING)} --auto"
    script = cmd.replace("\\", "\\\\").replace('"', '\\"')
    r = subprocess.run(["osascript", "-e", f'tell application "Terminal" to do script "{script}"',
                        "-e", 'tell application "Terminal" to activate'],
                       capture_output=True, text=True, timeout=20)
    log({"terminal": "yes" if r.returncode == 0 else "no", "err": (r.stderr or "")[-200:]})
    return r.returncode == 0


def handle(payload, conf):
    """What the hook does with one payload. Returns a short word for the log and the tests."""
    log({"payload": payload})
    if str(conf.get("KEEPGOING_AUTO", "1")).lower() in ("0", "no", "off", "false"):
        return "off"
    # Claude Code retries short 429s on its own, so a rate_limit stop means the work really
    # halted. Every other error (auth, server, billing) is left alone.
    if payload.get("error") != "rate_limit":
        return "ignored"
    cwd = payload.get("cwd") or ""
    if not os.path.isdir(cwd):
        return "no-folder"
    if recently_handed_off(cwd):
        return "recent"
    if str(conf.get("MOONSTONE", "1")) != "0" and try_moonstone(cwd, conf):
        return "moonstone"
    return "terminal" if open_terminal(cwd) else "failed"


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}
    try:
        result = handle(payload if isinstance(payload, dict) else {}, settings())
        log({"result": result})
    except Exception as e:  # a hook must never break Claude Code
        log({"error": repr(e)[:300]})
    sys.exit(0)


if __name__ == "__main__":
    main()
