# Project Mavrick

Project Mavrick is a fully local, privacy-first ambient camera companion running on `compute-02`. When the Logitech camera is connected, it can observe the current scene, respond to spoken questions, describe clearly visible activities or clothing, and occasionally make a short, gentle joke.

It is a fun home demonstration project with no cloud-service budget and no publishing workflow.

## Hardware

- Host: `compute-02`
- Camera and microphone: Logitech Webcam C930e
- Speaker: Marshall speaker through the computer's 3.5 mm analogue output
- Marshall USB connection: charging only

Default device mappings:

- Camera: stable C930e path under `/dev/v4l/by-id/`, with `/dev/video2` fallback
- Microphone: `plughw:CARD=C930e,DEV=0`
- Speaker: `plughw:CARD=sofhdadsp,DEV=0`

## Local architecture

1. `arecord` reads microphone PCM into memory.
2. Faster-Whisper `tiny.en` performs local speech recognition.
3. `ffmpeg` captures a single camera frame into memory when vision is needed.
4. Ollama `qwen3-vl:4b` performs local vision and response generation.
5. Piper `en_US-lessac-medium` creates local speech.
6. `aplay` sends speech to the Marshall speaker.

No paid API or cloud inference service is used.

## Operating modes

### Camera unplugged

The service remains active but idle. It checks periodically for the camera and does not capture anything.

### Ambient companion

When the C930e is connected, Mavrick checks for scene changes approximately every 45 seconds. An unsolicited observation or joke has a default three-minute cooldown so the companion does not chatter continuously.

The cooldown applies only to automatic ambient comments. Spoken questions can be answered immediately.

### Spoken questions

Mavrick listens for speech through the C930e microphone. When an utterance is detected, it transcribes it locally, optionally captures the current view, generates a brief response, and speaks through the Marshall speaker.

There is currently no wake-word requirement; clearly spoken phrases within microphone range may be treated as questions.

## Privacy model

Mavrick is designed for ephemeral local processing:

- Camera frames are captured into process memory, not normal disk storage.
- Microphone audio is handled as in-memory PCM arrays.
- Temporary Piper speech files are created in `/dev/shm` and deleted immediately after playback.
- The application has no recording or publishing function.
- Logs contain operational events and error classes, not images, audio, transcriptions, observations, or replies.
- The systemd service blocks network access except localhost, allowing access to the local Ollama service only.
- The prompt prohibits identifying people or inferring sensitive attributes.
- Comments must remain brief and gentle and must not criticize bodies or appearance.

This design minimizes retention, but anyone demonstrating the system should still tell people nearby that a camera and microphone are active.

## Installation

Run once on `compute-02`:

```bash
curl -fsSL https://raw.githubusercontent.com/prabhat324/p2-home-os/master/services/mavrick/install.sh | sudo bash
```

The installer:

- installs camera and ALSA utilities;
- creates the restricted `mavrick` service account;
- installs the Python environment;
- downloads the local Whisper and Piper models;
- installs and enables `mavrick.service`.

The Ollama vision model is managed through the `ops-control` Ansible control plane.

## Service management

```bash
sudo systemctl status mavrick
sudo systemctl restart mavrick
sudo systemctl stop mavrick
sudo systemctl start mavrick
```

View operational logs:

```bash
sudo journalctl -u mavrick -n 50 --no-pager
sudo journalctl -u mavrick -f
```

Healthy startup events include:

```text
MAVRICK event=started privacy=local_only_ram_media
MAVRICK event=camera_connected device=...
MAVRICK event=speech_model_ready
```

When the camera is unplugged, the runtime status changes to `idle_camera_unplugged`.

## Test procedure

1. Connect the Logitech C930e.
2. Turn on the Marshall speaker and select a moderate volume.
3. Confirm that the service is active.
4. Stand clearly in the camera view.
5. Say: “Mavrick, what am I wearing?”
6. Allow time for CPU-only local vision inference and speech playback.
7. Move or change something visible and wait for an optional ambient comment.

To confirm the vision model is installed:

```bash
ollama list
```

The list should contain `qwen3-vl:4b`.

## Configuration

Runtime settings are stored in `/etc/mavrick/config.env`. Repository defaults are in [config.env](./config.env).

Important settings:

| Setting | Default | Purpose |
| --- | --- | --- |
| `MAVRICK_VISION_MODEL` | `qwen3-vl:4b` | Local Ollama vision model |
| `MAVRICK_AMBIENT_INTERVAL` | `45` | Seconds between ambient checks |
| `MAVRICK_COMMENT_COOLDOWN` | `180` | Minimum seconds between unsolicited comments |
| `MAVRICK_MIC_DEVICE` | C930e ALSA device | Microphone input |
| `MAVRICK_SPEAKER_DEVICE` | HDA analogue ALSA device | 3.5 mm speaker output |

After changing configuration:

```bash
sudo systemctl restart mavrick
```

## Troubleshooting

### `ambient_retry error=HTTPError`

Ollama is reachable but rejected the request. During initial setup this usually means `qwen3-vl:4b` is still downloading or has not registered. Check `ollama list`.

### No camera response

Check:

```bash
v4l2-ctl --list-devices
ls -l /dev/v4l/by-id/
```

The C930e should appear with a stable `video-index0` path.

### No microphone response

Check:

```bash
arecord -l
```

The C930e USB Audio capture device must be present.

### No Marshall playback

Check:

```bash
aplay -l
```

The Marshall USB cable only charges it; sound must travel through the 3.5 mm cable. Verify that the speaker is powered on and its volume is audible.

### Slow responses

Vision and speech inference run locally on CPU. The first response is slower while models load into memory; later responses should improve while Ollama keeps the model warm.

## Control plane

Operational checks and model management use:

```text
GitHub: prabhat324/p2-home-os
Branch: ops-control
GitHub Actions runner: core-01
Path: runner -> Ansible -> compute-02
```

Approved Mavrick operations include:

- `mavrick-inventory`
- `mavrick-model-pull`

## Uninstall

Stop and disable the service:

```bash
sudo systemctl disable --now mavrick.service
```

Remove the Mavrick application, configuration, model data, and service account only if the project is no longer needed:

```bash
sudo rm -f /etc/systemd/system/mavrick.service
sudo systemctl daemon-reload
sudo rm -rf /opt/mavrick /etc/mavrick /var/lib/mavrick
sudo userdel mavrick
```

The Ollama model is separate and can be removed with:

```bash
ollama rm qwen3-vl:4b
```
