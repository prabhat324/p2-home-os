# Smart Home and Voice Stack

## Home Assistant

Home Assistant belongs on the always-on infrastructure side of P² Home OS rather than the GPU-heavy compute path. core-01 is the preferred placement for lightweight smart-home control.

## Voice pipeline

The local voice architecture currently uses separate speech-to-text and text-to-speech services:

```text
microphone/client
   -> Wyoming Whisper on compute-01:10300
   -> Home Assistant / intent processing
   -> Wyoming Piper on compute-02:10200
   -> speaker/client
```

### Whisper

Confirmed reachable endpoint:

```text
compute-01:10300
```

Validation:

```bash
nc -vz compute-01 10300
```

### Piper

Confirmed endpoint:

```text
compute-02:10200
```

Confirmed voice:

```text
en_US-lessac-medium
```

Validation:

```bash
nc -vz compute-02 10200
```

## Local LLM

Ollama is available on compute-01 and compute-03 for local inference. The earlier experimental assistant persona/project has been intentionally paused; do not treat it as a required production service.

## Known smart-home environment

The household includes integrations/devices from platforms such as Aqara, Ring, Ecobee, Govee, Lepro, Dyson, Kidde, Apple TV, Samsung TV, and camera platforms. Only mark an individual device as Home Assistant-integrated after verifying the integration in the live Home Assistant instance.

## Reliability principle

Voice and automation should degrade independently:

- loss of the GPU node should not take down core home automation;
- loss of Piper should affect speech output, not basic Home Assistant automations;
- loss of Whisper should affect voice input, not dashboards/automations;
- compute-heavy experimental LLM workloads should not be required for core safety/house functions.
