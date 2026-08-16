#!/usr/bin/env python3
"""Read-only Discord overseer for the P² Home OS control plane.

Runs on core-01 and uses only fixed, allowlisted read-only probes. User text is
never interpolated into shell commands. Natural-language routing is deterministic
and limited to status/inspection intents.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HOME = pathlib.Path.home()
CONFIG = HOME / ".config" / "psquare-discord.env"
STATE_DIR = HOME / ".local" / "state"
STATE_FILE = STATE_DIR / "psquare-discord-state.json"
INVENTORY = HOME / ".config" / "psquare" / "hosts.yml"
API = "https://discord.com/api/v10"

NODES = {
    "core-01": {"ip": "127.0.0.1", "role": "control-plane"},
    "compute-01": {"ip": "192.168.0.31", "role": "primary-compute"},
    "compute-02": {"ip": "192.168.0.88", "role": "orchestration"},
    "compute-03": {"ip": "192.168.0.158", "role": "gpu-worker"},
    "compute-04": {"ip": "192.168.0.177", "role": "light-gpu-worker"},
}
ALLOWED_NODES = set(NODES)


def load_config() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in CONFIG.read_text(encoding="utf-8").splitlines():
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        k, v = raw.split("=", 1)
        values[k.strip()] = v.strip()
    for key in ("DISCORD_BOT_TOKEN", "DISCORD_CHANNEL_ID"):
        if not values.get(key):
            raise SystemExit(f"missing {key}")
    return values


CFG = load_config()
TOKEN = CFG["DISCORD_BOT_TOKEN"]
CHANNEL_ID = CFG["DISCORD_CHANNEL_ID"]
ALLOWED_USER_ID = CFG.get("DISCORD_ALLOWED_USER_ID", "")


def discord_api(method: str, path: str, payload: dict | None = None) -> object:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bot {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "pSquare-Home-OS/1.0",
        },
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                body = response.read()
                return json.loads(body.decode("utf-8")) if body else {}
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                try:
                    wait = float(json.loads(exc.read().decode()).get("retry_after", 1.0))
                except Exception:
                    wait = 2.0
                time.sleep(min(max(wait, 1.0), 30.0))
                continue
            raise
        except Exception:
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)
    return {}


def post(text: str) -> None:
    discord_api("POST", f"/channels/{CHANNEL_ID}/messages", {
        "content": text[:1900],
        "allowed_mentions": {"parse": []},
    })


def run(args: list[str], timeout: int = 18) -> str:
    try:
        return subprocess.check_output(
            args, text=True, stderr=subprocess.STDOUT, timeout=timeout
        ).strip()
    except subprocess.CalledProcessError as exc:
        return (exc.output or f"exit {exc.returncode}").strip()
    except Exception as exc:
        return f"unavailable ({type(exc).__name__})"


def ansible(host: str, module: str, module_args: str = "", timeout: int = 22) -> str:
    if host not in ALLOWED_NODES and host not in {"all", "compute_nodes", "gpu_nodes", "osho_nodes"}:
        return "not allowed"
    cmd = ["ansible", host, "-i", str(INVENTORY), "-m", module, "-o"]
    if module_args:
        cmd += ["-a", module_args]
    return run(cmd, timeout=timeout)


def tcp_up(ip: str, port: int = 22) -> bool:
    if ip == "127.0.0.1":
        return True
    try:
        with socket.create_connection((ip, port), timeout=1.2):
            return True
    except OSError:
        return False


def dashboard() -> dict:
    try:
        with urllib.request.urlopen("http://192.168.0.88:8787/api/dashboard", timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def network_overview() -> str:
    lines = ["🌐 **P² Home OS overview**"]
    online = 0
    for name, info in NODES.items():
        up = tcp_up(info["ip"])
        online += int(up)
        lines.append(f"{'🟢' if up else '🔴'} **{name}** — {info['role']}")
    d = dashboard()
    s = d.get("summary") or {}
    if s:
        lines.append(
            f"\n🎬 Osho: {s.get('processing', 0)} processing / {s.get('queued', 0)} queued / "
            f"{s.get('uploaded', 0)} uploaded / {s.get('failed', 0)} failed"
        )
    lines.append(f"\nManaged nodes online: **{online}/{len(NODES)}**")
    return "\n".join(lines)


def node_status(node: str) -> str:
    if node not in ALLOWED_NODES:
        return "Unknown node."
    if node == "core-01":
        body = run(["bash", "-lc", "printf 'uptime='; uptime -p; printf 'load='; cut -d' ' -f1-3 /proc/loadavg; free -h | awk '/Mem:/{print \"ram=\"$3\"/\"$2}'; df -h / | awk 'NR==2{print \"root=\"$3\"/\"$2\" used, \"$5}'"])
    else:
        fixed = "printf 'uptime='; uptime -p; printf 'load='; cut -d' ' -f1-3 /proc/loadavg; free -h | awk '/Mem:/{print \"ram=\"$3\"/\"$2}'; df -h / | awk 'NR==2{print \"root=\"$3\"/\"$2\" used, \"$5}'; printf 'failed_services='; systemctl --failed --no-legend 2>/dev/null | wc -l"
        body = ansible(node, "shell", fixed)
    return f"🖥️ **{node}**\n```\n{body[-1500:]}\n```"


def services_status(node: str) -> str:
    if node not in ALLOWED_NODES:
        return "Unknown node."
    fixed = "systemctl list-units --type=service --state=running --no-legend --no-pager 2>/dev/null | awk '{print $1}' | head -35"
    body = run(["bash", "-lc", fixed]) if node == "core-01" else ansible(node, "shell", fixed)
    return f"⚙️ **Running services — {node}**\n```\n{body[-1500:]}\n```"


def storage_status() -> str:
    fixed = "df -h -x tmpfs -x devtmpfs | awk 'NR==1 || $6==\"/\" || $6 ~ /^\\/mnt\\// {print}'"
    body = ansible("all", "shell", fixed, timeout=28)
    return "💾 **P² storage snapshot**\n```\n" + body[-1650:] + "\n```"


def gpu_status() -> str:
    fixed = "nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw --format=csv,noheader,nounits 2>/dev/null || echo no-nvidia-gpu"
    body = ansible("gpu_nodes", "shell", fixed, timeout=28)
    return "🎮 **GPU nodes**\n```\n" + body[-1650:] + "\n```"


def osho_status(detail: str = "status") -> str:
    d = dashboard()
    s = d.get("summary") or {}
    cur = d.get("current_job") or {}
    if not d:
        return "🎬 **Project Osho**\nDashboard is currently unreachable from core-01."
    lines = [
        "🎬 **Project Osho**",
        f"Uploaded **{s.get('uploaded', 0)}** | Processing **{s.get('processing', 0)}** | Queued **{s.get('queued', 0)}** | Skipped **{s.get('skipped', 0)}** | Failed **{s.get('failed', 0)}**",
    ]
    if cur:
        lines.append(
            f"Current: **{cur.get('title') or cur.get('id')}** — {cur.get('stage') or cur.get('status')} "
            f"({cur.get('progress', '?')}%) on {cur.get('worker') or 'unknown'}"
        )
    if detail == "growth":
        fixed = "printf 'growth_metadata='; grep -RIl 'osho-growth-v1' /srv/osho/metadata 2>/dev/null | wc -l; printf 'renderer_marker='; grep -q 'OSHO_GROWTH_TEMPLATE_V1' /srv/compose/osho-worker/production_renderer.py 2>/dev/null && echo applied || echo missing"
        lines.append("```\n" + ansible("compute-01", "shell", fixed)[-900:] + "\n```")
    if detail == "publish":
        fixed = "ls -1t /srv/osho/youtube/receipts/*.json 2>/dev/null | head -1 | xargs -r cat"
        lines.append("Latest receipt:\n```\n" + ansible("compute-01", "shell", fixed)[-900:] + "\n```")
    return "\n".join(lines)


def mavrick_status() -> str:
    fixed = "printf 'service='; systemctl is-active mavrick.service 2>/dev/null || true; printf 'enabled='; systemctl is-enabled mavrick.service 2>/dev/null || true; printf 'runtime='; cat /run/mavrick/status.json 2>/dev/null || echo missing; printf '\nmodel='; curl -fsS --max-time 5 http://127.0.0.1:11434/api/tags 2>/dev/null | jq -r 'if [.models[]? | select(.name == \"qwen3-vl:2b\" or .model == \"qwen3-vl:2b\")] | length > 0 then \"ready\" else \"missing\" end'"
    body = ansible("compute-04", "shell", fixed)
    return "👁️ **Project Mavrick — compute-04**\n```\n" + body[-1500:] + "\n```"


def projects_status() -> str:
    osho = dashboard()
    s = osho.get("summary") or {}
    mav = ansible("compute-04", "shell", "printf 'mavrick='; systemctl is-active mavrick.service 2>/dev/null || true; printf ' model='; curl -fsS --max-time 4 http://127.0.0.1:11434/api/tags 2>/dev/null | jq -r 'if [.models[]? | select(.name == \"qwen3-vl:2b\" or .model == \"qwen3-vl:2b\")] | length > 0 then \"ready\" else \"missing\" end'")
    return (
        "📁 **Projects overseen by p2-home-os**\n"
        f"🎬 **Osho:** {s.get('processing', '?')} processing, {s.get('queued', '?')} queued, {s.get('failed', '?')} failed\n"
        f"👁️ **Mavrick:** `{mav[-500:]}`\n"
        "🏠 **Home infrastructure:** core services, dashboard, storage/media, Ollama/AI and compute nodes are available through pSquare status queries."
    )


def help_text() -> str:
    return (
        "🤖 **Project pSquare — P² Home OS overseer**\n"
        "Talk to me naturally in this channel. Examples:\n"
        "`psquare, what is happening on the network?`\n"
        "`psquare, what is Osho doing?`\n"
        "`psquare, did Growth V1 render anything?`\n"
        "`psquare, how is Mavrick?`\n"
        "`psquare, what are compute-01 and compute-03 doing?`\n"
        "`psquare, show storage` / `psquare, show GPUs` / `psquare, projects`\n"
        "Legacy commands such as `!osho progress` still work.\n\n"
        "🔒 **Read-only:** pSquare can inspect the control plane but cannot restart, stop, publish, delete, or run arbitrary commands from Discord."
    )


def normalize(content: str, my_id: str) -> tuple[str, bool]:
    raw = " ".join(content.strip().split())
    low = raw.lower()
    addressed = False
    if low.startswith(("!psquare", "!osho", "!mavrick", "!network", "!compute")):
        addressed = True
    if low.startswith("psquare") or low.startswith("p square"):
        addressed = True
    mention = f"<@{my_id}>"
    mention2 = f"<@!{my_id}>"
    if mention in raw or mention2 in raw:
        addressed = True
        raw = raw.replace(mention, "psquare").replace(mention2, "psquare")
    return " ".join(raw.lower().split()), addressed


def handle(content: str, my_id: str) -> str | None:
    text, addressed = normalize(content, my_id)
    if not addressed:
        return None
    text = re.sub(r"^[! ]*(psquare|p square)[,: ]*", "", text)
    if text.startswith("!osho"):
        text = "osho " + text[len("!osho"):].strip()
    elif text.startswith("!mavrick"):
        text = "mavrick " + text[len("!mavrick"):].strip()
    elif text.startswith("!network"):
        text = "network " + text[len("!network"):].strip()
    elif text.startswith("!compute"):
        text = "compute " + text[len("!compute"):].strip()

    if not text or "help" in text or "what can you do" in text:
        return help_text()

    node_hits = re.findall(r"(?:core|compute)-0[1-4]", text)
    node_hits = list(dict.fromkeys(n for n in node_hits if n in ALLOWED_NODES))
    if node_hits:
        if "service" in text or "running on" in text:
            return "\n\n".join(services_status(n) for n in node_hits[:2])
        return "\n\n".join(node_status(n) for n in node_hits[:2])

    if "osho" in text:
        if "growth" in text or "template" in text or "new edit" in text:
            return osho_status("growth")
        if any(k in text for k in ("upload", "publish", "youtube", "last video", "hasn't uploaded", "has not uploaded")):
            return osho_status("publish")
        return osho_status("status")

    if "mavrick" in text or "maverick" in text:
        return mavrick_status()
    if any(k in text for k in ("storage", "disk", "drive", "mount")):
        return storage_status()
    if any(k in text for k in ("gpu", "graphics", "temperature", "vram")):
        return gpu_status()
    if "project" in text:
        return projects_status()
    if any(k in text for k in ("network", "everything", "all systems", "overall", "resources", "health", "what is happening", "what's happening")):
        return network_overview()

    return (
        "I can inspect that if it maps to a managed p2-home-os resource, but I did not confidently classify the request.\n"
        "Try `psquare help`, or mention Osho, Mavrick, a compute node, storage, GPUs, projects, or overall network health."
    )


def load_state() -> dict:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def main() -> int:
    state = load_state()
    me = discord_api("GET", "/users/@me")
    my_id = str(me.get("id", "")) if isinstance(me, dict) else ""
    last_id = str(state.get("last_message_id", ""))
    if not last_id:
        recent = discord_api("GET", f"/channels/{CHANNEL_ID}/messages?limit=1")
        if isinstance(recent, list) and recent:
            last_id = str(recent[0].get("id", ""))
            state["last_message_id"] = last_id
            save_state(state)
    post("🟢 **Project pSquare network overseer online on core-01**\nTry: `psquare, what is happening on the network?`")
    while True:
        try:
            suffix = "?limit=25"
            if last_id:
                suffix += "&after=" + urllib.parse.quote(last_id)
            messages = discord_api("GET", f"/channels/{CHANNEL_ID}/messages{suffix}")
            if not isinstance(messages, list):
                time.sleep(3)
                continue
            for msg in sorted(messages, key=lambda m: int(m.get("id", 0))):
                mid = str(msg.get("id", ""))
                if mid:
                    last_id = mid
                author = msg.get("author") or {}
                author_id = str(author.get("id", ""))
                if author_id == my_id or bool(author.get("bot", False)):
                    continue
                if ALLOWED_USER_ID and author_id != ALLOWED_USER_ID:
                    continue
                response = handle(str(msg.get("content") or ""), my_id)
                if response:
                    post(response)
            state["last_message_id"] = last_id
            save_state(state)
            time.sleep(3)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(f"psquare bridge error: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            time.sleep(8)


if __name__ == "__main__":
    raise SystemExit(main())
