# JARVIS Core 0.27.8 — Performance & Autonomy Hotfix v11

Base: `JARVIS_Core_0.27.8_Language_Refinement_Hotfix_v10.1`.

## Changes

- Low-latency Edge TTS: short first segment, one-segment-ahead synthesis prefetch, playback-first cache handling, and timing events (`TTS_REQUESTED`, `TTS_SYNTH_STARTED`, `TTS_FIRST_CHUNK_READY`, `TTS_NEXT_CHUNK_READY`, `PLAYBACK_STARTED`, `SPEECH_FINISHED`).
- Main terminal/wake/manual-voice response paths now emit `LLM_RESPONSE_READY` before queuing TTS.
- Natural OWNER authorization accepts short responses such as `sim`, `podes`, `autoriza` and `pesquisa` when the pending scope is unambiguous. Natural denial accepts `não`, `agora não`, `recuso` and equivalents. Tokens remain internal/auditable and `/authorize TOKEN` remains available for explicit diagnostics.
- Repeated autonomy requests are deduplicated by exact `scope_hash`. Expired pending scopes receive a cooldown instead of being recreated immediately; denial cooldown is preserved.
- `recurring_topic` proactive messages are suppressed for the same topic for six hours after being emitted, preventing repeated requests about the same topic.
- Standing public-Web read-only permission recognises additional natural OWNER phrasing such as allowing JARVIS to search the Internet when needed. It remains limited to public read-only research/learning and does not authorize downloads, account actions, shell execution or other external actions.
- Voice V2 now exponentially backs off (bounded to 60 s) when PyAudio reports `Invalid device`/`-9996`, while every retry re-enumerates the configured microphone by name. This prevents a disconnected USB webcam/microphone from causing a sub-second retry loop.
- Existing `JARVIS Desktop.lnk` startup shortcuts are repaired from stale `C:\JARVIS` references to the active `G:\JARVIS` installation. No startup shortcut is created if one does not already exist.
- Qwen execution remains on the existing local CUDA/VRAM path. No RAM/CPU migration was introduced, and normal shutdown still releases the local model/runtime.
- App Control/WDAC management is now strictly **observe-only**. The compatibility-named `setup_appcontrol_trust.ps1` performs diagnostics only and contains no policy creation, deployment, removal or enforcement primitives.

## Security invariant

JARVIS has no WDAC/App Control policy-enforcement capability in this hotfix. It may observe, audit, log and warn. It does not create, install, modify, remove or activate Windows application-control policies.

## Validation

The complete Python regression suite is executed from the final source tree before packaging. Real-machine validation is still required for Edge-TTS first-audio latency, Windows MCI playback, USB microphone hot-unplug/replug, CUDA/VRAM residency and the existing Windows startup shortcut.

## Follow-up: disconnected microphone

- Voice V2 now exposes an explicit unavailable-device/reconnect state while its worker remains alive.
- The listening watchdog no longer restarts a live Voice V2 worker that is already waiting for an unplugged microphone, so the exponential backoff is preserved instead of repeatedly resetting to 1.6 seconds.
- Reconnect waiting is observable through `LISTENING_DEVICE_WAITING`; successful recovery emits `LISTENING_DEVICE_RECONNECTED`.
- Backoff waits are interruptible, so shutdown and deliberate restarts do not wait for the current retry timer.
