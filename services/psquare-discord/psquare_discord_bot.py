#!/usr/bin/env python3
"""Discord gateway and local AI overseer for the P² Home OS control plane.

Runs on core-01. Infrastructure probes are fixed and read-only. General Q&A and
photo understanding are routed to compute-01's local Ollama service. Basic image
edits are isolated FFmpeg jobs on compute-01; user text is never executed as shell
code and infrastructure-changing commands are not exposed through Discord.
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
import uuid

import psquare_ai

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
            "User-Agent": "pSquare-Home-OS/1.2",
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


def post_file(text: str, path: pathlib.Path) -> None:
    if not path.exists():
        post(text + "\n⚠️ The output file was not found.")
        return
    if path.stat().st_size > 8 * 1024 * 1024:
        post(text + "\n⚠️ The edited image is larger than the current 8 MB Discord upload limit for pSquare.")
        return
    boundary = "----pSquare" + uuid.uuid4().hex
    payload = json.dumps({"content": text[:1500], "allowed_mentions": {"parse": []}}).encode("utf-8")
    file_bytes = path.read_bytes()
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    body = bytearray()
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(b'Content-Disposition: form-data; name="payload_json"\r\n')
    body.extend(b"Content-Type: application/json\r\n\r\n")
    body.extend(payload)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(f'Content-Disposition: form-data; name="files[0]"; filename="{path.name}"\r\n'.encode())
    body.extend(f"Content-Type: {mime}\r\n\r\n".encode())
    body.extend(file_bytes)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        API + f"/channels/{CHANNEL_ID}/messages",
        data=bytes(body),
        method="POST",
        headers={
            "Authorization": f"Bot {TOKEN}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "pSquare-Home-OS/1.2",
        },
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        response.read()


def run(args: list[str], timeout: int = 18) -> str:
    env = os.environ.copy()
    env["ANSIBLE_DEPRECATION_WARNINGS"] = "False"
    env["ANSIBLE_LOCALHOST_WARNING"] = "False"
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=timeout, env=env).strip()
    except subprocess.CalledProcessError as exc:
        return (exc.output or f"exit {exc.returncode}").strip()
    except Exception as exc:
        return f"unavailable ({type(exc).__name__})"


def clean_ansible(raw: str) -> str:
    text = raw.replace("\\n", "\n")
    kept: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("[WARNING]") or s.startswith("[DEPRECATION WARNING]"):
            continue
        if re.match(r"^\S+\s+\|\s+(SUCCESS|CHANGED)\s+\|", s):
            continue
        if s in {"(stdout)", "(stderr)"}:
            continue
        kept.append(line.rstrip())
    return "\n".join(kept).strip()


def ansible(host: str, module: str, module_args: str = "", timeout: int = 22) -> str:
    if host not in ALLOWED_NODES and host not in {"all", "compute_nodes", "gpu_nodes", "osho_nodes"}:
        return "not allowed"
    cmd = ["ansible", host, "-i", str(INVENTORY), "-m", module]
    if module_args:
        cmd += ["-a", module_args]
    return clean_ansible(run(cmd, timeout=timeout))


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
    lines = ["🌐 **P² Home OS**"]
    online = 0
    for name, info in NODES.items():
        up = tcp_up(info["ip"])
        online += int(up)
        lines.append(f"{'🟢' if up else '🔴'} **{name}** — {info['role']}")
    d = dashboard()
    s = d.get("summary") or {}
    if s:
        lines.append(f"\n🎬 Osho — {s.get('processing', 0)} processing, {s.get('queued', 0)} queued, {s.get('uploaded', 0)} uploaded, {s.get('failed', 0)} failed")
    lines.append(f"\n**{online}/{len(NODES)} managed nodes online**")
    return "\n".join(lines)


def node_status(node: str) -> str:
    if node not in ALLOWED_NODES:
        return "Unknown node."
    if node == "core-01":
        body = run(["bash", "-lc", "printf 'uptime='; uptime -p; printf 'load='; cut -d' ' -f1-3 /proc/loadavg; free -h | awk '/Mem:/{print \"ram=\"$3\"/\"$2}'; df -h / | awk 'NR==2{print \"root=\"$3\"/\"$2\" used, \"$5}'"])
    else:
        fixed = "printf 'uptime='; uptime -p; printf 'load='; cut -d' ' -f1-3 /proc/loadavg; free -h | awk '/Mem:/{print \"ram=\"$3\"/\"$2}'; df -h / | awk 'NR==2{print \"root=\"$3\"/\"$2\" used, \"$5}'; printf 'failed_services='; systemctl --failed --no-legend 2>/dev/null | wc -l"
        body = ansible(node, "shell", fixed)
    values = {}
    for line in body.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
    if values:
        return (
            f"🖥️ **{node}**\n🟢 Reachable\n"
            f"⏱️ {values.get('uptime', 'uptime unavailable')}\n"
            f"📊 Load: **{values.get('load', '?')}**\n"
            f"🧠 RAM: **{values.get('ram', '?')}**\n"
            f"💾 Root: **{values.get('root', '?')}**\n"
            f"{'✅' if values.get('failed_services', '0') == '0' else '⚠️'} Failed services: **{values.get('failed_services', '0')}**"
        )
    return f"🖥️ **{node}**\n```\n{body[-1200:]}\n```"


def services_status(node: str) -> str:
    if node not in ALLOWED_NODES:
        return "Unknown node."
    fixed = "systemctl list-units --type=service --state=running --no-legend --no-pager 2>/dev/null | awk '{print $1}' | head -35"
    body = run(["bash", "-lc", fixed]) if node == "core-01" else ansible(node, "shell", fixed)
    services = [x.strip() for x in body.splitlines() if x.strip() and " | " not in x]
    if not services:
        return f"⚙️ **{node}** — no running-service data returned."
    shown = ", ".join(f"`{x}`" for x in services[:20])
    more = len(services) - min(len(services), 20)
    return f"⚙️ **Running services — {node}**\n{shown}" + (f"\n…and **{more}** more." if more else "")


def storage_status() -> str:
    fixed = "df -h -x tmpfs -x devtmpfs | awk 'NR==1 || $6==\"/\" || $6 ~ /^\\/mnt\\// {print}'"
    body = ansible("all", "shell", fixed, timeout=28)
    return "💾 **P² storage snapshot**\n```\n" + body[-1550:] + "\n```"


def gpu_status() -> str:
    fixed = "nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw --format=csv,noheader,nounits 2>/dev/null || echo no-nvidia-gpu"
    body = ansible("gpu_nodes", "shell", fixed, timeout=28)
    lines = [x.strip() for x in body.splitlines() if x.strip()]
    return "🎮 **GPU nodes**\n```\n" + "\n".join(lines[-20:]) + "\n```" if lines else "🎮 **GPU nodes**\nNo GPU telemetry returned."


def osho_status(detail: str = "status") -> str:
    d = dashboard()
    s = d.get("summary") or {}
    cur = d.get("current_job") or {}
    if not d:
        return "🎬 **Osho**\nDashboard is currently unreachable from core-01."
    lines = ["🎬 **Osho**", f"Uploaded **{s.get('uploaded', 0)}** · Processing **{s.get('processing', 0)}** · Queued **{s.get('queued', 0)}** · Skipped **{s.get('skipped', 0)}** · Failed **{s.get('failed', 0)}**"]
    if cur:
        lines.append(f"Current: **{cur.get('title') or cur.get('id')}** — {cur.get('stage') or cur.get('status')} ({cur.get('progress', '?')}%) on {cur.get('worker') or 'unknown'}")
    if detail == "growth":
        fixed = "printf 'growth_metadata='; grep -RIl 'osho-growth-v1' /srv/osho/metadata 2>/dev/null | wc -l; printf 'renderer_marker='; grep -q 'OSHO_GROWTH_TEMPLATE_V1' /srv/compose/osho-worker/production_renderer.py 2>/dev/null && echo applied || echo missing"
        probe = ansible("compute-01", "shell", fixed)
        vals = dict(re.findall(r"(growth_metadata|renderer_marker)=([^\s]+)", probe))
        lines.append(f"Growth V1 renderer: **{vals.get('renderer_marker', 'unknown')}** · Growth artifacts found: **{vals.get('growth_metadata', 'unknown')}**")
    if detail == "publish":
        fixed = "ls -1t /srv/osho/youtube/receipts/*.json 2>/dev/null | head -1 | xargs -r cat"
        receipt = ansible("compute-01", "shell", fixed)
        try:
            start = receipt.find("{")
            data = json.loads(receipt[start:]) if start >= 0 else {}
        except Exception:
            data = {}
        lines.append(f"Latest publication: **{data.get('title') or data.get('video_id') or 'unknown'}** ({data.get('privacy_status') or data.get('status') or 'status unknown'})" if data else "Latest publication receipt could not be parsed.")
    return "\n".join(lines)


def mavrick_probe() -> dict[str, str]:
    fixed = "printf 'service='; systemctl is-active mavrick.service 2>/dev/null || true; printf '\nenabled='; systemctl is-enabled mavrick.service 2>/dev/null || true; printf '\nruntime='; cat /run/mavrick/status.json 2>/dev/null || echo missing; printf '\nmodel='; curl -fsS --max-time 5 http://127.0.0.1:11434/api/tags 2>/dev/null | jq -r 'if [.models[]? | select(.name == \"qwen3-vl:2b\" or .model == \"qwen3-vl:2b\")] | length > 0 then \"ready\" else \"missing\" end'"
    body = ansible("compute-04", "shell", fixed)
    result: dict[str, str] = {}
    for key in ("service", "enabled", "runtime", "model"):
        m = re.search(rf"(?:^|\n){key}=(.*?)(?=\n(?:service|enabled|runtime|model)=|$)", body, re.S)
        if m:
            result[key] = m.group(1).strip()
    return result


def mavrick_status() -> str:
    p = mavrick_probe()
    service, enabled, model, runtime = p.get("service", "unknown"), p.get("enabled", "unknown"), p.get("model", "unknown"), p.get("runtime", "missing")
    lines = ["👁️ **Mavrick — compute-04**", f"{'🟢' if service == 'active' else '🔴'} Service: **{service}**", f"{'✅' if enabled == 'enabled' else '⚠️'} Auto-start: **{enabled}**", f"{'🧠' if model == 'ready' else '⚠️'} Vision model `qwen3-vl:2b`: **{model}**"]
    if runtime == "missing":
        lines.append("⚠️ Runtime status file is **missing**; the service is running but has not published runtime state yet.")
    else:
        try:
            data = json.loads(runtime)
            lines.append(f"📡 Runtime: **{data.get('status') or data.get('state') or data.get('mode') or 'available'}**")
        except Exception:
            lines.append("📡 Runtime status: **available**")
    return "\n".join(lines)


def projects_status() -> str:
    osho = dashboard()
    s = osho.get("summary") or {}
    mav = mavrick_probe()
    return (
        "📁 **pSquare project overview**\n"
        f"🎬 **Osho:** {s.get('processing', '?')} processing, {s.get('queued', '?')} queued, {s.get('failed', '?')} failed\n"
        f"👁️ **Mavrick:** service **{mav.get('service', 'unknown')}**, model **{mav.get('model', 'unknown')}**\n"
        "🏠 **P² Home OS:** core infrastructure, storage/media, AI services and managed compute nodes are available through pSquare."
    )


def help_text() -> str:
    return (
        "🤖 **pSquare — local P² Home OS assistant**\n"
        "Ask naturally: `psquare, explain quantum computing` or `psquare, how is Mavrick?`\n"
        "Attach a photo and ask: `psquare, what is in this image?` or `psquare, read the visible text`.\n"
        "Basic photo edits: `psquare, make this square`, `resize to 1080x1080`, `rotate right`, `grayscale`, `brighten`, `increase contrast`, `blur`, or `convert to PNG`.\n"
        "Infrastructure examples: `psquare, what is Osho doing?`, `show GPUs`, `show storage`, `what is compute-01 doing?`.\n\n"
        "🧠 General Q&A uses local `qwen3:8b` on compute-01. Photo understanding uses local `qwen3-vl:2b`.\n"
        "🔒 Infrastructure control remains read-only. Image edits create isolated derived files only; Discord cannot run arbitrary shell commands."
    )


def normalize(content: str, my_id: str) -> tuple[str, bool]:
    raw = " ".join(content.strip().split())
    low = raw.lower()
    addressed = low.startswith(("!psquare", "!osho", "!mavrick", "!network", "!compute", "psquare", "p square"))
    mention, mention2 = f"<@{my_id}>", f"<@!{my_id}>"
    if mention in raw or mention2 in raw:
        addressed = True
        raw = raw.replace(mention, "psquare").replace(mention2, "psquare")
    return " ".join(raw.lower().split()), addressed


def clean_prompt(content: str, my_id: str) -> str:
    raw = " ".join(content.strip().split())
    raw = raw.replace(f"<@{my_id}>", "psquare").replace(f"<@!{my_id}>", "psquare")
    raw = re.sub(r"^[! ]*(psquare|p square)[,: ]*", "", raw, flags=re.I)
    return raw.strip()


def handle_status(content: str, my_id: str) -> str | None:
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
    node_hits = list(dict.fromkeys(n for n in re.findall(r"(?:core|compute)-0[1-4]", text) if n in ALLOWED_NODES))
    if node_hits:
        return "\n\n".join(services_status(n) if "service" in text or "running on" in text else node_status(n) for n in node_hits[:2])
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
    return None


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


def ensure_bot_name(me: dict) -> dict:
    if str(me.get("username") or "") == "pSquare":
        return me
    try:
        updated = discord_api("PATCH", "/users/@me", {"username": "pSquare"})
        return updated if isinstance(updated, dict) else me
    except Exception as exc:
        print(f"pSquare username update skipped: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return me


def main() -> int:
    state = load_state()
    me = discord_api("GET", "/users/@me")
    if isinstance(me, dict):
        me = ensure_bot_name(me)
    my_id = str(me.get("id", "")) if isinstance(me, dict) else ""
    last_id = str(state.get("last_message_id", ""))
    if not last_id:
        recent = discord_api("GET", f"/channels/{CHANNEL_ID}/messages?limit=1")
        if isinstance(recent, list) and recent:
            last_id = str(recent[0].get("id", ""))
            state["last_message_id"] = last_id
            save_state(state)
    post("🟢 **pSquare online** — local AI + P² Home OS overseer. Try `psquare help`.")
    while True:
        try:
            suffix = "?limit=25" + ("&after=" + urllib.parse.quote(last_id) if last_id else "")
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
                content = str(msg.get("content") or "")
                _, addressed = normalize(content, my_id)
                if not addressed:
                    continue
                prompt = clean_prompt(content, my_id)
                attachments = msg.get("attachments") or []
                image = next((a for a in attachments if str(a.get("content_type") or "").startswith("image/")), None)
                if image:
                    if psquare_ai.looks_like_edit(prompt):
                        text, output = psquare_ai.image_edit(image, prompt)
                        try:
                            post_file(text, output) if output else post(text)
                        finally:
                            psquare_ai.cleanup_job_file(output)
                    else:
                        answer = psquare_ai.vision_answer(image, prompt)
                        post("🖼️ **Photo analysis — compute-01**\n" + answer)
                    continue
                response = handle_status(content, my_id)
                if response:
                    post(response)
                else:
                    answer = psquare_ai.text_answer(prompt)
                    post("🧠 **compute-01**\n" + answer)
            state["last_message_id"] = last_id
            save_state(state)
            time.sleep(3)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(f"pSquare bridge error: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            time.sleep(8)


if __name__ == "__main__":
    raise SystemExit(main())
