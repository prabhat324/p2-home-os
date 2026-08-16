#!/usr/bin/env python3
"""Local AI + safe image operations for the pSquare Discord overseer.

AI inference goes to compute-01 Ollama. Deterministic image transforms use
FFmpeg. Subject/background replacement uses a dedicated local segmentation
worker on compute-01. Natural scene/composition edits use the isolated local
generative image worker on compute-01. User text is never executed as shell code.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import pathlib
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
import uuid

OLLAMA = "http://192.168.0.31:11434"
TEXT_MODEL = "qwen3:8b"
VISION_MODEL = "qwen3-vl:2b"
MAX_IMAGE_BYTES = 15 * 1024 * 1024
SUPPORTED_IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
STATE_DIR = pathlib.Path.home() / ".local" / "state" / "psquare-jobs"
INVENTORY = pathlib.Path.home() / ".config" / "psquare" / "hosts.yml"
REMOTE_BG_PY = "/home/p2ops/.local/share/psquare-image/venv/bin/python"
REMOTE_BG_WORKER = "/home/p2ops/.local/bin/psquare-background.py"
REMOTE_GEN_PY = "/home/p2ops/.local/share/psquare-generative/venv/bin/python"
REMOTE_GEN_WORKER = "/home/p2ops/.local/bin/psquare-generative.py"

SYSTEM_PROMPT = (
    "You are pSquare, the local assistant for the P2 Home OS network. "
    "Answer clearly and concisely. You are running locally through Ollama on compute-01. "
    "Do not claim that image editing requires web access. If asked to edit an attached image, "
    "the Discord controller handles supported edits separately. For general questions, do not "
    "claim live internet access or current web knowledge."
)


def _json_request(url: str, payload: dict, timeout: int = 120) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
    obj = json.loads(raw.decode("utf-8")) if raw else {}
    return obj if isinstance(obj, dict) else {}


def _ollama_chat(model: str, prompt: str, image_b64: str | None = None, timeout: int = 150) -> str:
    user: dict = {"role": "user", "content": prompt}
    if image_b64:
        user["images"] = [image_b64]
    payload = {
        "model": model,
        "stream": False,
        "keep_alive": "2m",
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, user],
        "options": {"temperature": 0.25, "num_ctx": 4096},
    }
    try:
        data = _json_request(f"{OLLAMA}/api/chat", payload, timeout=timeout)
        message = data.get("message") or {}
        text = str(message.get("content") or "").strip()
        return text or "I did not get a usable response from the local model."
    except Exception as exc:
        return f"I could not reach the local AI on compute-01 ({type(exc).__name__})."


def text_answer(prompt: str) -> str:
    prompt = prompt.strip()
    if not prompt:
        return "Ask me a question and I’ll route it to the local model on compute-01."
    return _ollama_chat(TEXT_MODEL, prompt, timeout=150)


def _safe_attachment_url(url: str) -> bool:
    try:
        p = urllib.parse.urlparse(url)
    except Exception:
        return False
    host = (p.hostname or "").lower()
    return p.scheme == "https" and (host == "cdn.discordapp.com" or host.endswith(".discordapp.net"))


def download_image(attachment: dict) -> tuple[pathlib.Path | None, str | None]:
    url = str(attachment.get("url") or "")
    ctype = str(attachment.get("content_type") or "").split(";", 1)[0].lower()
    if ctype not in SUPPORTED_IMAGE_TYPES:
        guessed, _ = mimetypes.guess_type(str(attachment.get("filename") or ""))
        ctype = guessed or ""
    if ctype not in SUPPORTED_IMAGE_TYPES:
        return None, "I currently accept JPEG, PNG, or WebP images."
    if not _safe_attachment_url(url):
        return None, "I rejected that attachment because it was not a Discord-hosted image URL."
    declared = int(attachment.get("size") or 0)
    if declared and declared > MAX_IMAGE_BYTES:
        return None, "That image is too large for the local Discord workflow (15 MB limit)."

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    job = STATE_DIR / uuid.uuid4().hex
    job.mkdir(mode=0o700)
    path = job / ("input" + SUPPORTED_IMAGE_TYPES[ctype])
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "pSquare-Home-OS/1.3"})
        with urllib.request.urlopen(req, timeout=30) as r, path.open("wb") as out:
            total = 0
            while True:
                chunk = r.read(1024 * 256)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_IMAGE_BYTES:
                    raise ValueError("image too large")
                out.write(chunk)
        return path, None
    except Exception as exc:
        shutil.rmtree(job, ignore_errors=True)
        return None, f"I could not download that Discord image ({type(exc).__name__})."


def vision_answer(attachment: dict, prompt: str) -> str:
    path, error = download_image(attachment)
    if error or path is None:
        return error or "I could not stage the image."
    try:
        image_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        cleaned = prompt.strip() or "Describe this image and point out the important visible details."
        return _ollama_chat(VISION_MODEL, cleaned, image_b64=image_b64, timeout=180)
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)


def _run(args: list[str], timeout: int = 90) -> tuple[int, str]:
    try:
        p = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return p.returncode, (p.stdout or "").strip()
    except Exception as exc:
        return 99, f"{type(exc).__name__}: {exc}"


def _ansible(module: str, module_args: str, timeout: int = 90) -> tuple[int, str]:
    return _run(["ansible", "compute-01", "-i", str(INVENTORY), "-m", module, "-a", module_args], timeout=timeout)


def _background_request(prompt: str) -> str | None:
    text = prompt.lower()
    if not any(k in text for k in ("background", "backdrop", "remove background", "replace background")):
        return None
    if any(k in text for k in ("white background", "white backdrop", "background white")):
        return "white"
    if any(k in text for k in ("black background", "black backdrop", "matte black", "matt black", "background black")):
        return "black"
    return None


def looks_like_generative(prompt: str) -> bool:
    text = " ".join(prompt.lower().split())
    scene_terms = (
        "full body", "full-body", "sitting", "standing", "walking", "running", "drinking", "sipping",
        "cafe", "coffee shop", "restaurant", "beach", "city", "studio", "office", "hotel", "street",
        "sunset", "night", "cinematic", "cyberpunk", "watercolor", "painting", "anime", "vintage",
        "outfit", "clothes", "dress", "suit", "jacket", "hairstyle", "hair color", "lighting",
        "sky", "weather", "futuristic", "luxury", "dramatic", "fantasy", "scene", "environment",
    )
    action_patterns = (
        "make this person", "make her", "make him", "make them", "make this look",
        "turn this person", "turn her", "turn him", "turn them", "turn this into",
        "put this person", "put her", "put him", "put them", "place this person", "place her", "place him", "place them",
        "change the outfit", "change her outfit", "change his outfit", "change their outfit",
        "change the background", "replace the background", "change the scene", "change the lighting",
        "add a", "add an", "remove the object", "remove that object", "create a",
    )
    return any(k in text for k in action_patterns) or any(k in text for k in scene_terms)


def _edit_plan(prompt: str) -> tuple[list[str], str, list[str]]:
    text = prompt.lower()
    filters: list[str] = []
    notes: list[str] = []

    if any(k in text for k in ("grayscale", "grey scale", "gray scale", "black and white", "black & white", "b&w")):
        filters.append("hue=s=0")
        notes.append("grayscale")
    if "rotate left" in text or "rotate 90 left" in text or "counterclockwise" in text:
        filters.append("transpose=2")
        notes.append("rotated left")
    elif "rotate right" in text or "rotate 90 right" in text or "clockwise" in text:
        filters.append("transpose=1")
        notes.append("rotated right")
    elif "rotate 180" in text or "upside down" in text:
        filters.extend(["hflip", "vflip"])
        notes.append("rotated 180°")

    if "square" in text or "1:1" in text:
        filters.extend(["scale=1080:1080:force_original_aspect_ratio=increase", "crop=1080:1080"])
        notes.append("cropped to 1:1")
    elif any(k in text for k in ("9:16", "portrait", "story size", "reel size", "shorts size")):
        filters.extend(["scale=1080:1920:force_original_aspect_ratio=increase", "crop=1080:1920"])
        notes.append("cropped to 9:16")
    else:
        m = re.search(r"(?:resize|scale)(?:\s+(?:to|as))?\s+(\d{2,4})\s*[x×]\s*(\d{2,4})", text)
        if m:
            w, h = int(m.group(1)), int(m.group(2))
            if 64 <= w <= 4096 and 64 <= h <= 4096:
                filters.append(f"scale={w}:{h}:force_original_aspect_ratio=decrease")
                notes.append(f"resized within {w}×{h}")

    if any(k in text for k in ("brighter", "brighten", "increase brightness")):
        filters.append("eq=brightness=0.08")
        notes.append("brightened")
    if any(k in text for k in ("more contrast", "increase contrast")):
        filters.append("eq=contrast=1.15")
        notes.append("contrast increased")
    if any(k in text for k in ("blur", "soften")):
        filters.append("boxblur=2:1")
        notes.append("light blur")

    ext = ".png" if "convert to png" in text or "as png" in text else ".jpg"
    if not filters and ext == ".jpg" and not any(k in text for k in ("convert", "jpg", "jpeg")):
        return [], ext, []
    return filters, ext, notes


def _generative_edit(source: pathlib.Path, prompt: str) -> tuple[str, pathlib.Path | None]:
    token = uuid.uuid4().hex
    remote_in = f"/tmp/psquare-gen-{token}{source.suffix}"
    remote_out = f"/tmp/psquare-gen-{token}-edited.png"
    remote_prompt = f"/tmp/psquare-gen-{token}.txt"
    local_out = source.parent / "edited.png"
    local_prompt = source.parent / "prompt.txt"
    local_prompt.write_text(prompt.strip()[:700], encoding="utf-8")
    try:
        rc, _ = _ansible("copy", f"src={source} dest={remote_in} mode=0600", timeout=90)
        if rc != 0:
            return "I could not stage the image on compute-01.", None
        rc, _ = _ansible("copy", f"src={local_prompt} dest={remote_prompt} mode=0600", timeout=90)
        if rc != 0:
            return "I could not stage the edit instruction on compute-01.", None
        command = f"{REMOTE_GEN_PY} {REMOTE_GEN_WORKER} {remote_in} {remote_out} {remote_prompt}"
        rc, output = _ansible("shell", command, timeout=600)
        if rc != 0:
            return "compute-01 could not complete that generative image edit.", None
        rc, _ = _ansible("fetch", f"src={remote_out} dest={local_out} flat=yes", timeout=90)
        if rc != 0 or not local_out.exists():
            return "The generative edit finished, but I could not retrieve the output from compute-01.", None
        return "✨ Done on **compute-01** — generative photo edit completed.", local_out
    finally:
        _ansible("shell", f"rm -f {remote_in} {remote_out} {remote_prompt}", timeout=30)
        try:
            local_prompt.unlink(missing_ok=True)
        except Exception:
            pass


def image_edit(attachment: dict, prompt: str) -> tuple[str, pathlib.Path | None]:
    source, error = download_image(attachment)
    if error or source is None:
        return error or "I could not stage the image.", None

    background = _background_request(prompt)
    filters, out_ext, notes = _edit_plan(prompt)

    # Exact black/white background requests stay deterministic and identity-preserving.
    if background:
        out_ext = ".png"
    elif looks_like_generative(prompt):
        try:
            return _generative_edit(source, prompt)
        finally:
            try:
                source.unlink(missing_ok=True)
            except Exception:
                pass
    elif not filters and not notes and "convert" not in prompt.lower() and out_ext == ".jpg":
        shutil.rmtree(source.parent, ignore_errors=True)
        return (
            "I can do deterministic edits such as resize/crop/rotate/grayscale/brightness/contrast/blur/format conversion, "
            "solid black or white background replacement, and generative scene/style edits.",
            None,
        )

    token = uuid.uuid4().hex
    remote_in = f"/tmp/psquare-{token}{source.suffix}"
    remote_out = f"/tmp/psquare-{token}-edited{out_ext}"
    local_out = source.parent / ("edited" + out_ext)
    try:
        rc, _ = _ansible("copy", f"src={source} dest={remote_in} mode=0600", timeout=90)
        if rc != 0:
            return "I could not stage the image on compute-01.", None

        if background:
            command = f"{REMOTE_BG_PY} {REMOTE_BG_WORKER} {remote_in} {remote_out} {background}"
            rc, _ = _ansible("shell", command, timeout=240)
            if rc != 0:
                return "compute-01 could not separate the subject from the background for that image.", None
            notes.insert(0, f"background replaced with solid {background}")
        else:
            vf = ",".join(filters)
            codec = "-q:v 2" if out_ext == ".jpg" else ""
            if vf:
                command = f"ffmpeg -y -hide_banner -loglevel error -i {remote_in} -vf '{vf}' -frames:v 1 {codec} {remote_out}"
            else:
                command = f"ffmpeg -y -hide_banner -loglevel error -i {remote_in} -frames:v 1 {codec} {remote_out}"
            rc, _ = _ansible("shell", command, timeout=120)
            if rc != 0:
                return "compute-01 could not complete that image edit.", None

        rc, _ = _ansible("fetch", f"src={remote_out} dest={local_out} flat=yes", timeout=90)
        if rc != 0 or not local_out.exists():
            return "The edit finished, but I could not retrieve the output from compute-01.", None
        summary = ", ".join(notes) if notes else f"converted to {out_ext.lstrip('.').upper()}"
        return f"✅ Done on **compute-01** — {summary}.", local_out
    finally:
        _ansible("shell", f"rm -f {remote_in} {remote_out}", timeout=30)
        try:
            source.unlink(missing_ok=True)
        except Exception:
            pass


def cleanup_job_file(path: pathlib.Path | None) -> None:
    if path is None:
        return
    try:
        shutil.rmtree(path.parent, ignore_errors=True)
    except Exception:
        pass


def looks_like_edit(prompt: str) -> bool:
    text = prompt.lower()
    return looks_like_generative(prompt) or any(k in text for k in (
        "edit", "resize", "crop", "square", "9:16", "portrait", "story size", "reel size",
        "shorts size", "rotate", "grayscale", "grey scale", "gray scale", "black and white",
        "black & white", "b&w", "brighter", "brighten", "contrast", "blur", "soften",
        "convert to png", "convert to jpg", "convert to jpeg", "as png", "as jpg", "as jpeg",
        "background", "backdrop", "remove background", "replace background", "matte black", "matt black",
    ))
