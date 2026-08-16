#!/usr/bin/env python3
"""Project Mavrick: fully local, ephemeral ambient vision companion."""

from __future__ import annotations

import base64
import io
import json
import os
import pathlib
import queue
import re
import resource
import signal
import subprocess
import threading
import time
import uuid

import numpy as np
import requests
from faster_whisper import WhisperModel
from PIL import Image, ImageChops, ImageStat

OLLAMA_URL = os.getenv("MAVRICK_OLLAMA_URL", "http://127.0.0.1:11434")
VISION_MODEL = os.getenv("MAVRICK_VISION_MODEL", "qwen3-vl:4b")
CAMERA_HINT = os.getenv("MAVRICK_CAMERA_HINT", "C930e")
MIC_DEVICE = os.getenv("MAVRICK_MIC_DEVICE", "plughw:CARD=C930e,DEV=0")
SPEAKER_DEVICE = os.getenv("MAVRICK_SPEAKER_DEVICE", "plughw:CARD=sofhdadsp,DEV=0")
SPEAKER_ROUTE = os.getenv("MAVRICK_SPEAKER_ROUTE", "internal_speaker")
TELEMETRY_URL = os.getenv("MAVRICK_TELEMETRY_URL", "http://127.0.0.1:8787/api/mavrick/update")
WHISPER_MODEL = os.getenv("MAVRICK_WHISPER_MODEL", "tiny.en")
WHISPER_ROOT = os.getenv("MAVRICK_WHISPER_ROOT", "/var/lib/mavrick/models/whisper")
PIPER_VOICE = os.getenv("MAVRICK_PIPER_VOICE", "en_US-lessac-medium")
PIPER_DATA = os.getenv("MAVRICK_PIPER_DATA", "/var/lib/mavrick/models/piper")
AMBIENT_INTERVAL = int(os.getenv("MAVRICK_AMBIENT_INTERVAL", "45"))
COMMENT_COOLDOWN = int(os.getenv("MAVRICK_COMMENT_COOLDOWN", "180"))
SPEECH_RMS_THRESHOLD = int(os.getenv("MAVRICK_SPEECH_RMS_THRESHOLD", "120"))
MIC_SOFTWARE_GAIN = float(os.getenv("MAVRICK_MIC_SOFTWARE_GAIN", "4.0"))
CAMERA_LISTEN_INDICATOR = os.getenv("MAVRICK_CAMERA_LISTEN_INDICATOR", "true").lower() in {"1", "true", "yes", "on"}
STATUS_FILE = pathlib.Path("/run/mavrick/status.json")
STATE_LOCK = threading.Lock()
CURRENT_STATE: dict[str, object] = {"state": "starting"}
METRICS: dict[str, object] = {
    "stt_ms": None, "vision_ms": None, "tts_ms": None, "total_ms": None,
    "last_error": None, "last_error_at": None,
}

STOP = threading.Event()
SPEAKING = threading.Event()
UTTERANCES: queue.Queue[np.ndarray] = queue.Queue(maxsize=3)

SYSTEM_PROMPT = """You are Mavrick, a private local ambient companion for a fun home demo.
You may describe visible activity, objects, and clothing colors or styles, then make at most
one brief, gentle joke. Never identify people. Never infer age, ethnicity, religion, health,
disability, emotions, wealth, sexuality, politics, or other sensitive traits. Never criticize
bodies or appearance. Avoid alarming or embarrassing remarks. Keep spoken replies under 28
words. If there is nothing useful or playful to say, set speak=false. No media is retained."""

SCHEMA = {
    "type": "object",
    "properties": {
        "person_present": {"type": "boolean"},
        "observation": {"type": "string"},
        "reply": {"type": "string"},
        "speak": {"type": "boolean"},
    },
    "required": ["person_present", "observation", "reply", "speak"],
}

def log(event: str, **fields: object) -> None:
    safe = " ".join(f"{k}={v}" for k, v in fields.items())
    print(f"MAVRICK event={event} {safe}".strip(), flush=True)
    if event.endswith(("_failed", "_retry")):
        with STATE_LOCK:
            METRICS["last_error"] = event
            METRICS["last_error_at"] = time.time()

def status(state: str, **fields: object) -> None:
    data = {"state": state, "at": time.time(), **fields}
    with STATE_LOCK:
        CURRENT_STATE.clear()
        CURRENT_STATE.update(data)
    tmp = STATUS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, STATUS_FILE)

def telemetry_loop() -> None:
    while not STOP.is_set():
        model_ready = False
        try:
            tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3).json()
            model_ready = any(
                str(item.get("name") or item.get("model") or "") == VISION_MODEL
                for item in tags.get("models", [])
                if isinstance(item, dict)
            )
        except Exception:
            pass
        with STATE_LOCK:
            snapshot = dict(CURRENT_STATE)
            metrics = dict(METRICS)
        payload = {
            "state": snapshot.get("state", "unknown"),
            "service": "active",
            "camera": camera_path() is not None,
            "microphone": any(t.name == "microphone" and t.is_alive() for t in threading.enumerate()),
            "model": VISION_MODEL,
            "model_ready": model_ready,
            "speaker_route": SPEAKER_ROUTE,
            "output_device": SPEAKER_DEVICE,
            "rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
            "load_1m": round(os.getloadavg()[0], 2),
            "privacy": "operational_only_no_retained_media_or_content",
            "updated_at": time.time(),
            **metrics,
        }
        try:
            requests.post(TELEMETRY_URL, json=payload, timeout=3).raise_for_status()
        except Exception:
            pass
        STOP.wait(10)

def camera_path() -> pathlib.Path | None:
    roots = [pathlib.Path("/dev/v4l/by-id"), pathlib.Path("/dev")]
    for root in roots:
        if not root.exists():
            continue
        patterns = [f"*{CAMERA_HINT}*video-index0", "video2"] if root.name == "by-id" else ["video2"]
        for pattern in patterns:
            for path in sorted(root.glob(pattern)):
                try:
                    resolved = path.resolve()
                    if resolved.exists():
                        return path
                except OSError:
                    continue
    return None

def capture_frame(device: pathlib.Path) -> bytes:
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "v4l2", "-input_format", "mjpeg",
        "-video_size", "640x360", "-i", str(device),
        "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=12, check=True)
    if not result.stdout:
        raise RuntimeError("empty camera frame")
    return result.stdout

def scene_change(previous: bytes | None, current: bytes) -> float:
    if not previous:
        return 100.0
    a = Image.open(io.BytesIO(previous)).convert("L").resize((64, 36))
    b = Image.open(io.BytesIO(current)).convert("L").resize((64, 36))
    return float(ImageStat.Stat(ImageChops.difference(a, b)).mean[0])

def ollama(messages: list[dict], image: bytes | None = None) -> dict:
    started = time.monotonic()
    content = messages[-1]["content"]
    user = {"role": "user", "content": content}
    if image is not None:
        user["images"] = [base64.b64encode(image).decode("ascii")]
    payload = {
        "model": VISION_MODEL,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *messages[:-1], user],
        "stream": False,
        "think": False,
        "format": SCHEMA,
        "options": {"temperature": 0.65, "num_ctx": 4096, "num_predict": 120},
        "keep_alive": "10m",
    }
    response = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=180)
    response.raise_for_status()
    message = response.json().get("message", {})
    text = str(message.get("content") or "").strip()
    with STATE_LOCK:
        METRICS["vision_ms"] = round((time.monotonic() - started) * 1000)
    cleaned = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        reply = " ".join(cleaned.split())
        if not reply:
            raise RuntimeError("empty model response")
        log("model_text_fallback", characters=len(reply))
        return {
            "person_present": image is not None,
            "observation": "",
            "reply": reply[:300],
            "speak": True,
        }

def speak(text: str) -> None:
    started = time.monotonic()
    text = " ".join(text.strip().split())[:300]
    if not text:
        return
    SPEAKING.set()
    wav = pathlib.Path("/dev/shm") / f"mavrick-{uuid.uuid4().hex}.wav"
    try:
        subprocess.run(
            [
                "/opt/mavrick/venv/bin/python", "-m", "piper",
                "-m", PIPER_VOICE, "--data-dir", PIPER_DATA,
                "-f", str(wav), "--", text,
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=True,
        )
        subprocess.run(
            ["aplay", "-q", "-D", SPEAKER_DEVICE, str(wav)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=True,
        )
        with STATE_LOCK:
            METRICS["tts_ms"] = round((time.monotonic() - started) * 1000)
        log("spoke", characters=len(text))
    except Exception as exc:
        log("speech_failed", error=type(exc).__name__)
    finally:
        try:
            wav.unlink(missing_ok=True)
        finally:
            time.sleep(0.7)
            SPEAKING.clear()

def start_camera_indicator() -> subprocess.Popen | None:
    if not CAMERA_LISTEN_INDICATOR:
        return None
    device = camera_path()
    if device is None:
        return None
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "v4l2", "-input_format", "mjpeg",
        "-video_size", "640x360", "-i", str(device),
        "-an", "-f", "null", "-",
    ]
    try:
        return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:
        log("listen_indicator_failed", error=type(exc).__name__)
        return None

def stop_camera_indicator(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=2)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

def microphone_loop() -> None:
    chunk_samples = 1600
    command = [
        "arecord", "-q", "-D", MIC_DEVICE, "-f", "S16_LE",
        "-r", "16000", "-c", "1", "-t", "raw",
    ]
    while not STOP.is_set():
        proc = None
        try:
            proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            active: list[np.ndarray] = []
            silence_chunks = 0
            speech_chunks = 0
            indicator = None
            peak_rms = 0.0
            while not STOP.is_set() and proc.poll() is None:
                raw = proc.stdout.read(chunk_samples * 2) if proc.stdout else b""
                if len(raw) < chunk_samples * 2:
                    break
                if SPEAKING.is_set():
                    active.clear()
                    silence_chunks = speech_chunks = 0
                    continue
                samples = np.frombuffer(raw, dtype=np.int16).copy()
                rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
                is_speech = rms >= SPEECH_RMS_THRESHOLD
                if is_speech:
                    peak_rms = max(peak_rms, rms)
                    if indicator is None:
                        indicator = start_camera_indicator()
                        log("listening_started", rms=int(rms), threshold=SPEECH_RMS_THRESHOLD)
                        status("listening", indicator="camera_led", retention="ram_only")
                    speech_chunks += 1
                    silence_chunks = 0
                    active.append(samples)
                elif active:
                    silence_chunks += 1
                    active.append(samples)
                if active and (silence_chunks >= 8 or len(active) >= 120):
                    stop_camera_indicator(indicator)
                    indicator = None
                    if speech_chunks >= 3:
                        audio = np.clip(np.concatenate(active).astype(np.float32) * MIC_SOFTWARE_GAIN / 32768.0, -1.0, 1.0)
                        try:
                            UTTERANCES.put_nowait(audio)
                            log("utterance_queued", speech_chunks=speech_chunks, peak_rms=int(peak_rms))
                            status("transcribing", retention="ram_only")
                        except queue.Full:
                            log("utterance_dropped", reason="queue_full")
                    active.clear()
                    silence_chunks = speech_chunks = 0
                    peak_rms = 0.0
        except Exception as exc:
            log("microphone_retry", error=type(exc).__name__)
        finally:
            stop_camera_indicator(locals().get("indicator"))
            if proc is not None:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        STOP.wait(3)

def transcriber_loop() -> None:
    status("loading_speech_model")
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", download_root=WHISPER_ROOT)
    log("speech_model_ready")
    while not STOP.is_set():
        try:
            audio = UTTERANCES.get(timeout=1)
        except queue.Empty:
            continue
        try:
            started = time.monotonic()
            segments, _ = model.transcribe(
                audio, language="en", beam_size=1, vad_filter=True,
                condition_on_previous_text=False,
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
            with STATE_LOCK:
                METRICS["stt_ms"] = round((time.monotonic() - started) * 1000)
            if len(text) >= 2:
                handle_question(text)
        except Exception as exc:
            log("transcription_failed", error=type(exc).__name__)

def handle_question(text: str) -> None:
    started = time.monotonic()
    status("answering_question", retention="ram_only")
    device = camera_path()
    frame = None
    if device:
        try:
            frame = capture_frame(device)
        except Exception:
            pass
    try:
        result = ollama(
            [{"role": "user", "content": f"The person said: {text}. Reply naturally and briefly, using the current view only if useful."}],
            frame,
        )
        reply = str(result.get("reply", "")).strip()
        if reply:
            speak(reply)
        with STATE_LOCK:
            METRICS["total_ms"] = round((time.monotonic() - started) * 1000)
        status("ambient_ready", camera=str(device) if device else None, retention="ram_only")
    except Exception as exc:
        log("question_failed", error=type(exc).__name__)

def ambient_loop() -> None:
    previous: bytes | None = None
    last_comment = 0.0
    camera_was_present = False
    while not STOP.is_set():
        device = camera_path()
        if not device:
            if camera_was_present:
                log("camera_disconnected")
            camera_was_present = False
            previous = None
            status("idle_camera_unplugged", privacy="no_capture")
            STOP.wait(3)
            continue
        if not camera_was_present:
            log("camera_connected", device=str(device))
            status("ambient_ready", camera=str(device), retention="ram_only")
            camera_was_present = True
        try:
            frame = capture_frame(device)
            change = scene_change(previous, frame)
            previous = frame
            now = time.monotonic()
            if change >= 4.0 and now - last_comment >= COMMENT_COOLDOWN:
                status("local_vision_processing", retention="ram_only")
                result = ollama(
                    [{"role": "user", "content": "Observe the current scene. Mention activity or clothing only when clearly visible. Decide whether a short playful comment would improve this demo."}],
                    frame,
                )
                if result.get("person_present") and result.get("speak"):
                    reply = str(result.get("reply", "")).strip()
                    if reply:
                        speak(reply)
                        last_comment = now
                status("ambient_ready", camera=str(device), retention="ram_only")
            frame = b""
        except Exception as exc:
            log("ambient_retry", error=type(exc).__name__)
            status("camera_retry", error=type(exc).__name__)
        STOP.wait(AMBIENT_INTERVAL)

def shutdown(_signum: int, _frame: object) -> None:
    STOP.set()

def main() -> int:
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    log("started", privacy="local_only_ram_media")
    threads = [
        threading.Thread(target=microphone_loop, name="microphone", daemon=True),
        threading.Thread(target=transcriber_loop, name="transcriber", daemon=True),
        threading.Thread(target=ambient_loop, name="ambient", daemon=True),
        threading.Thread(target=telemetry_loop, name="telemetry", daemon=True),
    ]
    for thread in threads:
        thread.start()
    while not STOP.wait(1):
        pass
    log("stopped")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
