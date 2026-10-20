#!/usr/bin/env python3
"""keepgoing — out of Claude credits? Carry THIS folder's conversation on with another model.

Finds the most recent Claude Code conversation that ran in the current folder, then shows what you
can continue it with right now:

  * FREE CLOUD  — free models on OpenRouter (needs a free OPENROUTER_API_KEY)
  * THIS MAC    — models from the Claude Code Local lineup that fit your RAM, served by this repo's
                  MLX server on port 4000

With --auto there is no menu: it takes the first free cloud model if you have a key, else the model
already running on this Mac, else the biggest lineup model that fits your RAM. That is what the
Claude Code hook in scripts/limit-handoff.py runs when you hit a usage limit.

The choice is printed for bin/keepgoing as one tab-separated line:
  <session_id> <kind: cloud|local> <model> <already_running: 0|1>
Everything meant for you goes to stderr.
"""
import glob
import json
import os
import subprocess
import sys
import time
import urllib.request

PROJECTS = os.path.expanduser("~/.claude/projects")
PORT = int(os.environ.get("MLX_PORT", "4000"))
C = dict(dim="\033[2m", b="\033[1m", grn="\033[32m", ylw="\033[33m", red="\033[31m",
         cyn="\033[36m", off="\033[0m")

# The lineup setup.sh installs from (see README "Pick your fighter"), smallest first.
# (Hugging Face id, label, minimum Mac RAM in GB)
LOCAL = [
    ("mlx-community/gemma-4-e4b-it-4bit", "Gemma 4 E4B", 8),
    ("divinetribe/Hermes-4-14B-abliterated-4bit-mlx", "Hermes 4 14B", 16),
    ("divinetribe/gemma-4-12B-it-abliterated-4bit-mlx-text", "Gemma 4 12B", 32),
    ("divinetribe/gemma-4-31b-it-abliterated-4bit-mlx", "Gemma 4 31B", 64),
    ("lmstudio-community/Qwen3.8-27B-MLX-8bit", "Qwen 3.8 27B", 96),
]


def say(msg=""):
    sys.stderr.write(msg + "\n")


def find_session(cwd):
    """(session_id, turns, last_modified) of the newest conversation that ran in cwd."""
    best = None
    for path in glob.glob(os.path.join(PROJECTS, "*", "*.jsonl")):
        try:
            if os.path.getsize(path) < 200:
                continue
            session_cwd, turns = None, 0
            with open(path, errors="replace") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if session_cwd is None and rec.get("cwd"):
                        session_cwd = rec["cwd"]
                    if rec.get("type") == "user":
                        turns += 1
            if session_cwd != cwd or turns < 1:
                continue
            mtime = os.path.getmtime(path)
            if best is None or mtime > best[2]:
                best = (os.path.splitext(os.path.basename(path))[0], turns, mtime)
        except OSError:
            continue
    return best


def free_cloud_models(key, limit=3):
    """Free OpenRouter models that can use tools and hold a long conversation, biggest context first."""
    if not key:
        return []
    try:
        req = urllib.request.Request("https://openrouter.ai/api/v1/models",
                                     headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r)["data"]
    except Exception as e:  # offline, bad key, etc. — the local list still works
        say(f"{C['dim']}  (couldn't reach OpenRouter: {e}){C['off']}")
        return []
    picks = [m for m in data
             if m.get("id", "").endswith(":free")
             and "tools" in (m.get("supported_parameters") or [])
             and (m.get("context_length") or 0) >= 128_000]
    picks.sort(key=lambda m: m.get("context_length") or 0, reverse=True)
    return [m["id"] for m in picks[:limit]]


def mac_ram_gb():
    try:
        out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout
        return int(out.strip()) // (1 << 30)
    except Exception:
        return 0


def running_local_model():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as r:
            return json.load(r).get("model")
    except Exception:
        return None


def ago(seconds):
    if seconds < 3600:
        return f"{int(seconds / 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds / 3600)}h ago"
    return f"{int(seconds / 86400)}d ago"


def auto_pick(cloud, live, ram):
    """The --auto choice as (kind, model, already_running), or None if there is nothing to use."""
    if cloud:
        return ("cloud", cloud[0], 0)
    if live:
        return ("local", live, 1)  # already loaded: instant, and nothing else gets swapped out
    fits = [m for m, _, need in LOCAL if ram and ram >= need]
    if fits:
        return ("local", fits[-1], 0)  # LOCAL is smallest first
    return ("local", LOCAL[0][0], 0) if LOCAL else None  # RAM unknown: the smallest is the safe bet


def main(argv=None):
    auto = "--auto" in (sys.argv[1:] if argv is None else argv)
    cwd = os.getcwd()
    session = find_session(cwd)
    if not session:
        say(f"{C['red']}  No Claude Code conversation found for this folder:{C['off']}")
        say(f"{C['dim']}    {cwd}{C['off']}")
        say(f"{C['dim']}  cd to the folder you were working in, then run keep going again.{C['off']}")
        sys.exit(1)
    sid, turns, mtime = session

    say(f"\n{C['cyn']}{C['b']}  Picking up your conversation in {os.path.basename(cwd)}{C['off']}")
    say(f"{C['dim']}  {turns} messages · last active {ago(time.time() - mtime)}{C['off']}\n")

    if auto:
        key = os.environ.get("OPENROUTER_API_KEY", "")
        pick = auto_pick(free_cloud_models(key, limit=1), running_local_model(), mac_ram_gb())
        if not pick:
            say(f"{C['red']}  Nothing to keep going with.{C['off']}")
            sys.exit(1)
        kind, model, already = pick
        where = "free cloud" if kind == "cloud" else "already running" if already else "this Mac"
        say(f"{C['b']}  Keeping going automatically with {model}{C['off']} {C['dim']}({where}){C['off']}")
        print("\t".join([sid, kind, model, str(already)]))
        return

    say(f"{C['b']}  Pick a model to keep going with:{C['off']}\n")

    options = []

    key = os.environ.get("OPENROUTER_API_KEY", "")
    say(f"{C['dim']}  FREE CLOUD{C['off']}")
    cloud = free_cloud_models(key)
    for model in cloud:
        options.append(("cloud", model, 0))
        say(f"{C['grn']}  {len(options):2}{C['off']}  {model}")
    if not key:
        say(f"{C['dim']}  (add a free OpenRouter key to see these — see README){C['off']}")
    elif not cloud:
        say(f"{C['dim']}  (none available right now){C['off']}")

    say(f"\n{C['dim']}  ON THIS MAC{C['off']}")
    live = running_local_model()
    ram = mac_ram_gb()
    if live:
        options.append(("local", live, 1))
        say(f"{C['grn']}  {len(options):2}{C['off']}  {live}  {C['grn']}already running, instant{C['off']}")
    for model, label, need in LOCAL:
        if model == live:
            continue
        if ram and ram < need:
            continue
        options.append(("local", model, 0))
        say(f"{C['grn']}  {len(options):2}{C['off']}  {label}  {C['dim']}(needs {need} GB+ Mac){C['off']}")

    say("")
    sys.stderr.write("  Number (q = quit): ")
    sys.stderr.flush()
    try:
        choice = input().strip()
    except EOFError:
        choice = ""
    if not choice or choice.lower() == "q":
        sys.exit(1)
    try:
        kind, model, already = options[int(choice) - 1]
    except (ValueError, IndexError):
        say("  Not a valid choice.")
        sys.exit(1)
    print("\t".join([sid, kind, model, str(already)]))


if __name__ == "__main__":
    main()
