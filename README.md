# JARVIS Core
## 0.27.8 — Epistemic Learning & Permission-Gated Expert Escalation

> **Consolidated runtime/security hotfix:** this 0.27.8 build also carries forward the final 0.27.7 executor and Windows hardening that landed after the first 0.27.8 package was cut: `jarvis_local` executor abstraction, signed `0xC0E90002` handling, current Block Audit corroboration, pinned CUDA→Vulkan→local-compat fallback, and `setup_appcontrol_trust.ps1` for observe-only App Control diagnostics on Windows Pro. JARVIS-created enforcement is disabled in this hotfix. Epistemic Learning and the optional expert remain intact; expert access is still off by default and permission-gated.

**Windows Pro observe-only correction:** the live-machine incident showed that a JARVIS-derived App Control policy could block legitimate ASUS/Armoury Crate components. This hotfix removes the Enforce path. JARVIS may prepare/audit and diagnose Code Integrity, but cannot deploy a blocking App Control policy; `Disarm` removes legacy JARVIS policies without changing Microsoft Smart App Control state. Rapid restarts also reuse a short-lived clean Windows Block Audit cache when release/runtime metadata has not changed; the full `/security blocked files` audit remains uncached.

0.27.8 keeps the JARVIS-owned `llama.cpp`/Qwen brain local-first and adds a controlled learning loop. When the local answer explicitly shows a real knowledge gap, JARVIS checks its persistent authorized-learning library. If the topic is unknown or stale, it asks the OWNER before performing bounded public-web research, synthesizes the research locally, validates the topic, stores provenance/freshness/confidence metadata, and retries the original request with request-scoped learned RAG.

- **Learning before outsourcing:** a local knowledge gap offers web study before any external-AI expert.
- **OWNER permission first:** gap-triggered web learning is an `external_learning` Autonomy Guardian action. No network study occurs merely because the model is uncertain.
- **Persistent learned state:** topics can be inspected as `KNOWN`, `STALE` or `UNKNOWN`; stored entries keep source metadata, learning timestamp, source count and deterministic confidence metadata.
- **Freshness-aware:** general learned knowledge defaults to 120 days; fast-moving topics such as prices, news, releases, jobs, CVEs and drivers revalidate after 14 days.
- **Automatic retry after study:** once authorized research is validated and stored, JARVIS retries the original question so the new knowledge is immediately useful.
- **Request-scoped RAG:** only strongly matching, non-stale authorized learning is injected into the current prompt; unrelated research is not carried into later conversations.
- **External AI hard block:** JARVIS cannot delegate reasoning to ChatGPT, OpenAI, Gemini, Claude or another LLM. Public Web research remains available and is synthesized only by the local Qwen brain.
- **Isolated expert payload:** the optional expert receives only the exact authorized question plus a neutral instruction — no personal profile, memory, conversation history, telemetry, local tools or web tools; provider storage is disabled for that request.
- **JARVIS remains the only AI brain:** public Web pages are untrusted source data. They are validated and summarized by the local Qwen runtime; no external AI advice is consulted.
- **Secret guard:** suspected API keys/passwords/tokens/private keys are not offered for automatic external-expert escalation.
- **Local brain remains primary:** complexity alone never changes provider; the JARVIS-owned native runtime is still the normal reasoning path.

Useful inspection commands:

```text
/learning status
/learning topic OpenWakeWord
/learning search OpenWakeWord
/cloud status
```

`setup_cloud.ps1` is retained only as a compatibility stub and cannot enable external AI. It reports the hard block and exits without installing a provider or storing credentials.

### Learning-first flow

```text
OWNER question
   -> local Qwen
   -> sufficient? yes -> answer
   -> insufficient?
        -> learned topic KNOWN and fresh?
             no -> ask OWNER to study web
                    -> bounded public-web retrieval
                    -> local synthesis + relevance validation
                    -> store locally with provenance/freshness metadata
                    -> retry original question
             yes -> retry/use learned RAG
        -> still explicitly insufficient?
             -> if optional expert configured, ask OWNER separately
             -> isolated one-shot expert consultation
             -> local JARVIS comparison/synthesis -> final answer
```

## 0.27.7 — Native Brain & Truthful Conversation Memory

0.27.7 moved primary reasoning from the Ollama service to a JARVIS-owned native `llama.cpp` runtime and made conversation recall evidence-driven. In that release external-AI reasoning was disabled; 0.27.8 retains the native local default while reintroducing external AI only as an optional, isolated and explicitly authorized last-resort expert.

- **JARVIS-owned native brain:** `Brain` talks through `jarvis_core/core/local_llm.py`; no direct Ollama client/package is required.
- **Pinned inference runtime:** `setup_native_brain.ps1` installs pinned `llama.cpp` release `b10516` for Windows CUDA under `runtime\llama.cpp`.
- **Model migration without lock-in:** setup can reuse an existing Qwen3 8B GGUF blob from the legacy Ollama cache, otherwise it downloads the pinned Qwen3-8B Q4_K_M GGUF. Runtime reasoning never calls Ollama.
- **Truthful conversation recall:** prior-conversation claims are grounded from persisted `context.jsonl`; unsupported positive recall is rejected.
- **Native shutdown gate:** `/quit`, `run.ps1` and real-machine acceptance stop/check the JARVIS-owned `llama-server.exe`.
- **Vision boundary:** camera/screen capture remains local; native multimodal inference remains a separate future path.

### What “JARVIS is the brain” means

The JARVIS Core owns identity, persistent memory, Synthetic Self, intent classification, planning, tools, permissions, research, learning validation and the lifecycle of local inference. Qwen3 supplies neural language computation and `llama.cpp` executes the model locally. External AI providers are structurally blocked; public Web research is treated as source data and synthesized by the persistent local JARVIS brain.

### Migration

Run `setup.ps1` normally. On an existing machine, `setup_native_brain.ps1` can reuse the current Qwen3 GGUF bytes from the Ollama cache before Ollama is removed. Do not uninstall Ollama until `acceptance_real_machine.ps1` has passed once with the native backend.

## 0.27.6 — Health & Intelligence Baseline

0.27.6 is a stabilization release. It deliberately adds no user-facing feature wave; it makes the active runtime measurable, deterministic and releasable.

- Forces the active Voice v2 STT path to **CPU/int8** on this PC profile and removes silent Voice-v2-to-legacy fallback.
- Makes `full_system_validation` build Voice v2 from the **same runtime configuration factories** as the CLI, including safe Voice Lock auto-disable.
- Enforces UTF-8/pt-PT at process and PowerShell boundaries.
- Uses schema-constrained structured JSON for Task Planner and Companion Planner and Draft 2020-12 JSON Schema validation for tool arguments.
- Adds Guardian alert fingerprinting/cooldown while retaining occurrence counts and evidence.
- Adds bounded event-log rotation and bounded TTS cache pruning.
- Changes local-first escalation: request complexity alone is never sufficient; cloud escalation requires a genuinely insufficient local result.
- Hardens `setup_cloud.ps1` around pinned dependencies, keyring backend/readback and disabled hidden fallbacks.
- Removes OWNER authorization language from the research subject/query.
- Adds a separate `OWNER_MACHINE_DEFENSIVE` Kali service-inventory profile; it does not convert the OWNER machine into LAB scope.
- Keeps legacy voice/wake only as explicit compatibility mode, outside the default active path.
- Pins direct dependency versions for reproducible installs.
- Makes shutdown verify Ollama residency with `ollama ps`; `acceptance_real_machine.ps1` independently repeats `/quit -> ollama ps` and blocks release if a configured JARVIS model remains resident.

### Release gates

The unit/integration suite is necessary but not sufficient. `acceptance_real_machine.ps1` is the final Windows-machine gate for real WASAPI/microphone, Voice v2/STT, Voice Lock health policy, Ollama availability, UTF-8 and post-`/quit` model residency. A Windows/hardware-dependent check must never be reported as PASS merely because a mocked or non-Windows test passed.

## 0.27.5 — Command Intelligence & Resource Cleanup

- Keeps the working audio stack unchanged.
- Repairs narrow voice ASR variants only when an installed app is named.
- Capability questions use Fast Path instead of the 8B model.
- Fixes false ACCEPT_PREVIOUS classification for capability questions.
- Strengthens model VRAM release on `/quit`.


## 0.27.4 — Mic Binding & Ollama Health

- Restores `GENERAL WEBCAM` / WASAPI / 48 kHz preference, with stereo endpoint ranking.
- `/mic list`: `*` is the JARVIS-selected microphone; `D` is Windows default.
- `/mic use` persists the selected endpoint and restarts the listening watchdog.
- Full validation uses Ollama chat with Qwen3 thinking disabled for the health probe, avoiding false empty-response failures.
- Empty local Qwen responses receive one local retry with thinking disabled; this never escalates a simple task to external AI.

# JARVIS Core 0.27.4 — Stability, Local-First Autonomy & Kali VM

Voice input was rebuilt around a deliberately small pipeline: **WASAPI -> Silero VAD -> openWakeWord -> Faster-Whisper -> structured tool calls**. The previous owner-template/verifier/confidence-gate stack is no longer part of the active wake path. Run `./setup_voice_reset.ps1` after updating. A custom openWakeWord ONNX model can be installed as `models/openwakeword/jarvis.onnx` with `./install_custom_wake_model.ps1 -ModelPath ...`.

## 0.26.8 — Wake Responsiveness & Follow-up Capture

0.26.8 removes the hidden multi-second inline-command wait after a verified wake, makes the OWNER-enrolled `Jarvis` profile fast-path short temporally-confirmed wakes without paying a Whisper round-trip, and preserves speech that begins during WASAPI calibration so short follow-up commands do not lose their first syllable. The generic openWakeWord + Silero path and the long-phrase false-wake guard remain active.

## 0.26.7 — Voice Latency & False-Wake Hardening

0.26.7 keeps Qwen resident when Faster Whisper runs on CPU, moves the Voice v2 command recognizer to `small`/CPU by default, rejects low-confidence STT hallucinations after retry, and hardens the OWNER wake profile against long room/TV speech. Medium-confidence `Jarvis` template hits now finalize only at phrase end and receive an independent lightweight wake-word STT veto; strong hits remain immediate. Common praise such as `Parabéns, Jarvis` is handled on the deterministic Fast Path instead of paying a full Qwen turn.

## 0.26.6 — Natural Wake Follow-up

0.26.6 fixes the wake-only conversational handoff. Saying `Jarvis` by itself is now treated as a complete wake turn: JARVIS answers `Sim, Senhor?`, waits for its acknowledgement TTS to finish, temporarily suspends the wake stream, and automatically captures the OWNER's next spoken phrase as the command. The OWNER no longer has to repeat `Jarvis` or place the command in the same utterance. Duplicate wake-only callbacks are suppressed while the follow-up listener is pending, preventing repeated acknowledgements.

The 0.26.5 OWNER wake-profile calibration, VAD hardening, persistent public-web learning authorization, and all prior G-drive/security preservation behavior remain unchanged.

## 0.26.5 — Voice Wake + Persistent Public-Web Learning

0.26.5 fixes the remaining Voice v2 OWNER-wake regression and generalizes OWNER-authorized learning. The v2 engine now respects the threshold stored in `voice_profiles/wake_jarvis.npz` instead of forcing the legacy hardening floor, tolerates short VAD dips, and supports `/wake enroll` plus `/wake test` on the active v2 backend.

An explicit OWNER grant to access/use the Internet can now persist narrowly as **public, read-only web research for OWNER-requested learning**. This lets later instructions such as `Aprende a programar em C` execute without repeating permission. It does not authorize downloads, shell execution, account actions, purchases, posting, or broader autonomous Internet activity. `/autonomy revoke` clears the standing permission. Existing installations can recover the grant only from an explicit prior OWNER sentence preserved in the autonomy audit.

## 0.26.4 — OWNER Authority / Python Learning Hotfix

0.26.4 fixes natural-language OWNER authorization falling through to Qwen. Phrases such as `tens a minha autorização para acederes à internet e aprendas a programar em Python` are now handled by the deterministic authority layer, with topic extraction supporting `aprender a ...` forms.

When Silence Latch is active, typed `Jarvis, ...` normalization now happens before the authority/learning parsers. A valid direct authorization therefore releases silence first, executes one bounded external-learning session, and stores the locally synthesized research result without granting unrestricted standing Internet permission.

## 0.26.2 — Silence/Terminal + STT Reliability Hotfix

0.26.2 fixes a Silence Latch regression where terminal commands such as `Jarvis, verifica o meu computador` could be discarded while silence was active. Explicit OWNER terminal interaction now releases the latch, including normal punctuation after `Jarvis`.

`/stt test` now prints `A ouvir...` before capture, uses VAD for command decoding, rejects punctuation-only noise hallucinations, and preserves failed diagnostic WAVs under `logs/audio_diagnostics/`. Voice v2 also returns its KWS threshold to 0.50 while retaining Silero VAD and temporal confirmation, improving recognition of the stock `hey_jarvis` model without reverting the legacy false-wake path.

## 0.26.1 — UTF-8 BOM Settings Hotfix

0.26.1 fixes G-drive migrations where Windows/PowerShell-created `settings.json` contains an UTF-8 BOM. The settings loader and schema synchronizer accept both UTF-8 variants and normalize BOM-bearing settings without overwriting OWNER choices.

## 0.26.0 — Dedicated G: + Voice Reliability

- Install Core at `G:\JARVIS`; do not copy the old `.venv` from C:. Recreate it with `setup.ps1`.
- Keep the live wallpaper add-on at `G:\JARVIS-Wallpaper`; JARVIS derives this sibling path automatically when no custom path is configured.
- Voice v2 forces ONNX and never silently falls back to TFLite.
- MCI barge-in waits for playback readiness before pause/resume, preventing the observed error 263 race.
- Legacy audio prefers stable WASAPI/DirectSound over WDM-KS duplicates.
- Faster Whisper snapshots stay under `G:\JARVIS\models\faster-whisper` when installed on G:.
- Use `migrate_to_g.ps1` to import persistent state from the old Core and move/copy the visual add-on safely; use `finalize_g_migration.ps1` only after testing.

### Migração recomendada nesta máquina

1. Fecha o JARVIS com `/quit` e fecha o Wallpaper Engine.
2. Extrai esta release para que exista `G:\JARVIS\jarvis.py`.
3. Abre PowerShell e executa:

```powershell
cd G:\JARVIS
powershell -ExecutionPolicy Bypass -File .\migrate_to_g.ps1
.\setup.ps1 -SkipModel
.\setup_voice_v2.ps1
.\verify_release.ps1
.\run.ps1
```

4. Valida `/voice doctor`, `cala-te`, alguns segundos de conversa/ruído sem dizer Jarvis, depois `Jarvis`, e `/desktop status`.
5. Só quando G: estiver validado, a limpeza explícita pode ser feita com:

```powershell
.\finalize_g_migration.ps1 -RemoveOldCore -RemoveOldWallpaper -RemoveOldWallpaperEngine
```

Se o Wallpaper Engine for gerido pelo Steam, não uses `-RemoveOldWallpaperEngine` para forçar uma mudança: transfere a aplicação para uma biblioteca Steam em G: através do Steam Storage. O script não altera manifests do Steam.

# JARVIS Core 0.25.4 — False-Wake Hardening
> **0.25.4 false-wake hotfix:** both wake engines now fail more conservatively. Legacy acoustic profiles are clamped to a safer runtime floor and their isolated Whisper veto uses VAD + tighter confidence limits. Voice Engine v2 explicitly requires Silero speech agreement and temporally confirms medium openWakeWord hits while keeping strong hits fast. The 0.25.3 PCM/App Control workaround is retained, so PyAV remains unnecessary for microphone STT and Windows security does not need to be weakened.

## 0.25.4 — False-Wake Hardening

- Legacy wake: runtime floor `0.72`, persisted low thresholds are clamped, wake-veto VAD is enabled, and candidate confidence is stricter.
- Voice v2: base threshold `0.62`, explicit Silero VAD veto, two-frame confirmation for medium hits, immediate acceptance only at strong score `>=0.82`.
- Existing untouched 0.25.3 defaults migrate automatically; OWNER-tuned settings remain unchanged.
- `setup_voice_v2.ps1` still uses the PCM compatibility loader from 0.25.3, so the blocked PyAV DLL/PYD path is not required.

## 0.25.3 — App Control PCM/STT + Full Wake Learning

0.25.3 made the Voice Engine v2 STT path independent of PyAV/FFmpeg by decoding captured WAV files to PCM before Faster Whisper, avoiding Windows Application Control blocks on PyAV `.pyd` modules. It also added automatic wake-learning persistence and WSL training helpers.


> **0.25.2 Windows Application Control hotfix:** Voice v2 no longer imports openWakeWord's optional scikit-learn/SciPy custom-verifier training stack. The setup installs an inference-only dependency set and JARVIS loads the official openWakeWord Model/VAD/utils through a memory-only compatibility loader. Do not disable Windows Application Control.



> **0.25.1 updater hotfix retained:** corrige o `Join-Path` do instalador 0.25.0 que falhava depois da validação/MOTW. O Voice Engine v2 e restantes funcionalidades mantêm-se.
### Full wake learning under strict Windows App Control

Runtime voice does not need SciPy/scikit-learn or PyAV. For owner-specific wake learning, place 16 kHz mono WAV examples under `voice_profiles/wake_learning/positive` (Jarvis examples, >=3) and `voice_profiles/wake_learning/negative` (ordinary speech/background; >=10s recommended), then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_wake_learning_wsl.ps1
```

Training uses the official openWakeWord SciPy/scikit-learn pipeline inside WSL and exports `models/wake_verifier_jarvis.npz`. Voice v2 loads that verifier with NumPy only.

## 0.25.2 — Voice Engine v2

0.25.2 replaces the preferred Windows always-listening front-end with a single-owner WASAPI pipeline: **PyAudioWPatch -> openWakeWord -> Silero VAD -> Faster Whisper after wake**. The previous sounddevice/NumPy acoustic engine remains available as `legacy` and `auto` falls back to it if the optional v2 runtime is not ready.

The key reliability change is architectural: **Whisper no longer decides whether normal room speech was the word Jarvis**. openWakeWord owns wake detection continuously on CPU, gated by its Silero VAD. Faster Whisper only runs once a wake is verified and a command has been captured.

Install the optional v2 runtime after updating Core:

```powershell
cd G:\JARVIS
powershell -ExecutionPolicy Bypass -File .\setup_voice_v2.ps1
.\run.ps1
```

Diagnostics:

```text
/voice status
/voice doctor
/voice benchmark
/voice latency
/voice release
/voice backend auto
/voice backend v2
/voice backend legacy
```

`/voice status` reports the requested/effective input backend and any fallback reason. `setup_voice_v2.ps1` downloads the pretrained openWakeWord model set and verifies that a Jarvis model plus Silero VAD are locally usable. The v2 STT default is `medium` with `device=auto`: CUDA is attempted by Faster Whisper and the existing CPU/int8 fallback remains available. Voice v2 does not preload STT by default and releases the loaded STT model after the configured idle interval. The VRAM handoff coordinator unloads resident JARVIS/Ollama models before a CUDA STT load, and unloads CUDA Faster Whisper before a complex request hands control back to Qwen; deterministic Fast Path commands keep STT warm.

The `Cala-te` owner interrupt profile is retained and evaluated on the same v2 WASAPI stream, avoiding a second microphone owner.

The System Guardian -> Live HUD contract now includes severity counts (`critical`, `high`, `attention`). Attention-only changes publish `WATCH`; red `ALERT` is reserved for high/critical Guardian findings. This is consumed by Live Wallpaper 0.5.0.

## 0.24.1 — Reliability & Latency Stabilization

0.24.1 is a stabilization release driven by real Always Listening traces. It removes wake-verifier prompt bias, isolates only the acoustic wake candidate for Whisper confirmation, increases post-wake command pre-roll, adds latency-first command decoding with one confidence-gated retry, recovers clipped voice-only app fragments such as `O Brave`, and prevents the language model from claiming a Windows action succeeded when no local tool actually completed it.

Performance changes:

- wake confirmation uses beam 1 with no `Jarvis` prompt/hotwords, reducing both latency and confirmation bias;
- command STT uses beam 1 first and retries at beam 5 only for low-confidence audio;
- command audio trims long leading/trailing silence before Whisper while retaining padding around speech;
- post-wake pre-roll is 420 ms so `Abre o Brave` is less likely to lose the first verb;
- fast local Qwen profile is reduced to a 3072-token context, 128 predicted tokens, 4 history messages and 8 tool schemas;
- voice-only app fragments after a verified wake can recover a clipped verb deterministically without invoking Qwen;
- common social acknowledgements after a verified wake use deterministic replies instead of loading Qwen.

Reliability changes:

- normal room speech must pass an unbiased exact-keyword Whisper confirmation before wake is accepted;
- rejected wake candidates receive a longer cooldown so one utterance is not checked repeatedly;
- repeated successful mutation tools are suppressed inside the same request;
- Action Truth Guard blocks completion claims such as `Brave aberto` when no tool completed successfully;
- `/mind idle reflect` performs an on-demand high-level idle reflection with tools disabled and `keep_alive=0`; it reports focus/possible next action/reason/permission requirement without exposing private chain-of-thought or keeping VRAM resident.

Useful OWNER commands:

```text
/activity on
/mind idle
/mind idle reflect
/vram status
/vram release
```

## 0.24.0 — Fast Interaction & Idle Mind

0.24.0 focuses on interaction latency and observable idle cognition. High-confidence Windows commands such as `Abra o Brave` now use the deterministic Fast Path instead of loading Qwen; repeated successful action tools are suppressed inside the same request; acoustic wake candidates use a lightweight beam-1 Whisper confirmation profile; and `/mind idle` exposes safe functional idle state without revealing private chain-of-thought.

`Cala-te` now activates a Silence Latch that clears speech, invalidates stale pending responses and suppresses unsolicited Companion/Proactive output until a verified new `Jarvis` wake or `/silence off`. The interrupt profile is also checked while idle/thinking using the same acoustic+Whisper two-stage rule.

New OWNER observability commands:

```text
/activity on
/activity status
/activity last
/activity off
/silence status
/silence off
```

The Activity Trace shows safe observable state — what STT heard (raw vs normalized when different), routing, intent contract, processing state, available/used tools, plan state and initiative reason. It deliberately does not expose hidden chain-of-thought.

## 0.23.7 — Startup Device Binding Contract Hotfix

0.23.7 aligns `ListeningConfig`, `WakeWordConfig` and CLI construction so the persisted OWNER microphone index is passed consistently to both microphone capture and Always Listening after restart.

## 0.23.6 — Webcam Wake & STT Binding Fix

0.23.6 makes the OWNER-selected microphone index authoritative for wake, tolerates noise-gated webcams that output digital zero while the room is silent, makes `/av probe` require useful signal instead of microscopic electrical noise, remembers recently proven speech endpoints, and adds conservative pt-PT command-verb normalization for the observed `avie o Brave` -> `abre o Brave` ASR slip.

## 0.23.5 — Signal-Aware Microphone Failover

This release fixes Windows webcam endpoints that open successfully but deliver only digital zeroes. JARVIS now treats real audio signal — not merely a successful PortAudio open — as proof that an input is usable. Silent duplicate endpoints are skipped automatically, Windows WASAPI is preferred over fragile WDM-KS duplicates, Always Listening temporarily quarantines dead endpoints, `/av auto` binds only to a signal-proven microphone, and `/av probe` exposes per-endpoint RMS/host-API diagnostics.

The release includes all 0.23.4 STT-accuracy improvements, 0.23.3 VRAM cleanup behavior and 0.23.2 webcam A/V binding.

## 0.23.4 — Webcam STT Accuracy Hotfix

This release improves command recognition when the primary microphone is the webcam: beam-5 decoding, one low-confidence beam-8 retry, conservative speech-level normalization, a pt-PT fidelity prompt, real post-wake pre-roll, lower command onset threshold, longer trailing-silence tolerance, and `/stt status` / `/stt test` diagnostics. It includes all 0.23.3 VRAM cleanup behavior and all 0.23.2 webcam A/V binding behavior.


## 0.23.3 — VRAM Residency Hotfix

0.23.3 fixes local-AI model residency so closing JARVIS releases GPU memory instead of leaving Ollama models resident. The main Qwen keep-alive default is reduced from the legacy 30 minutes to 5 minutes, while the optional Vision model uses 2 minutes. Normal `/quit` explicitly unloads all configured JARVIS Ollama models with `keep_alive=0`; `run.ps1` repeats the unload as a crash-safe best-effort cleanup after the Python process exits. Ollama itself remains running.

OWNER diagnostics/control:

- `/vram status` — show configured/running JARVIS Ollama models and reported VRAM residency.
- `/vram release` — immediately unload the main and Vision models without closing JARVIS.
- `/perf release` — same all-model release behavior for backward compatibility.

The updater migrates only the exact old shipped `ollama_keep_alive=30m` value to `5m`; custom OWNER values are preserved. `ollama_release_on_shutdown` defaults to true and `vision_keep_alive` defaults to `2m`.


## 0.23.2 — Modular Autonomous Skills Runtime

0.23.2 freezes the proven 0.22.1 Core boundary and moves ambitious capabilities into a modular Skills Runtime. Built-in skills register ordinary Tool Registry entries, inherit the existing profile/SecurityPolicy risk gates and publish their activity through the EventBus. OWNER-trusted external skills live outside the mirrored Core tree and load only when their exact directory SHA-256 digest has been trusted through the CLI. The local model has no tool that can trust or install external code.

### New built-in skills

- **Desktop Agent / Computer Control** — observe the foreground window, list/focus windows, capture the screen, and use bounded mouse/keyboard primitives. Click, typing and hotkeys remain `CONFIRM` actions. No arbitrary PowerShell/cmd executor is added.
- **Purple Team Orchestrator** — coordinates the existing fixed Kali LAB profiles for service discovery, web fingerprinting, safe web audit, defensive recommendations and post-mitigation retest. It remains strictly `LAB`-only and does not add exploits, payloads, persistence or arbitrary Kali shell.
- **System Guardian** — continuously compares startup persistence, listening sockets and selected process-path signals against a local baseline and verifies controlled JARVIS release hashes. Alerts are evidence to review, not automatic malware verdicts.
- **Autonomous Task Planner** — asks the local Qwen model for a JSON plan, validates every step against the real Tool Registry, executes safe steps and pauses at ordinary confirmation tokens. A failed step may trigger one bounded evidence-based adaptation by default; confirmations can never be bypassed.
- **Relational Memory Graph** — adds entities, relations, decisions and project state on top of explicit accepted memory writes. Ordinary conversation is not silently promoted to permanent graph facts.
- **Live Wallpaper State** — publishes `memory/live_hud.json` with active skill/tool/task, Guardian alerts, Purple Team and Vision state for the loopback Wallpaper bridge.
- **Local Vision** — screen/camera capture plus a separate JARVIS-owned native llama.cpp multimodal runtime. `setup_vision.ps1` downloads a pinned Qwen2.5-VL-3B-Instruct Q4_K_M GGUF + mmproj pair into `models/vision`, verifies both SHA-256 digests, and uses OpenCV locally for camera capture. Inference stays on `127.0.0.1`; no external AI provider is contacted.
- **Self Diagnostics & Safe Repair** — checks runtime directories, settings schema, local model readiness, desktop integration and Core integrity, and performs only bounded idempotent repairs. It cannot replace release code, install packages/models automatically or weaken Windows security.
- **Skills System** — built-ins plus persistent OWNER-trusted external modules, with exact-digest trust and restart-after-trust semantics.

### Useful commands

```text
/skills status
/desktop observe
/desktop windows
/desktop screenshot
/vision status
/vision analyze descreve o ecrã
/vision camera descreve o que a webcam vê
/guardian status
/guardian scan
/purple run 192.168.56.10 22,80,443,445
/planner run resolve este problema e verifica o resultado
/planner list
/repair diagnose
/memory graph
```

For the optional local visual model/camera support:

```powershell
.\setup_vision.ps1
```

The updater deliberately does **not** pull the multi-GB visual model or install OpenCV without that explicit command. The visual model download is approximately 2.8 GB and is pinned to a verified ggml-org revision; after setup, image inference runs locally through the existing trusted llama.cpp executable on a separate loopback port.

## 0.22.1 — Follow-up Continuity Guard

0.22.1 fixes short conversational confirmations that previously lost their immediate referent. Replies such as `Sim`, `Sim, faz isso!`, `Pode ser`, `Continua`, `Não, deixa estar` and other short referential follow-ups are now resolved only against the immediately previous persisted turn.

The resolver runs before performance planning, Cyber/learning retrieval and selective tool-schema routing. This means an accepted proposal inherits the topic and tool vocabulary of the proposal it refers to. For example, when JARVIS offers to store a spouse name/date and the OWNER replies `Sim, faz isso!`, memory tools remain available instead of the model drifting back to an older Kali topic.

Safety/continuity properties:

- only the immediately previous turn may be used; the resolver never searches older turns;
- plain yes/no requires an actionable question/offer in the previous response;
- explicitly referential phrases such as `faz isso`/`continua` can bind to the previous turn directly;
- stale previous turns older than 30 minutes are not auto-bound;
- rejecting a proposal does not execute it;
- normal confirmation/security boundaries of the selected tool remain unchanged;
- the original user message remains in conversation history; the expanded effective query is request-scoped routing context only.

### 0.22.1 validation

- 461 unit/regression/contract tests pass.
- 211 controlled Python files are syntax-valid.
- 231 immutable release files are covered by the SHA-256 manifest.
- The exact reported memory-confirmation regression is included in the test suite.
- No arbitrary shell path was added; existing OWNER/STRICT and LAB boundaries remain unchanged.


## 0.22.0 — Desktop Integration / Wallpaper Engine automation

O Core passa a iniciar automaticamente a integração visual local quando o add-on estiver instalado em `G:\JARVIS-Wallpaper`: valida o bridge em `127.0.0.1:8765`, inicia-o sem duplicar processos e, no Windows, deteta/inicia o Wallpaper Engine. Se o add-on ou Wallpaper Engine não existirem, o Core continua normalmente. Comandos de diagnóstico: `/desktop status` e `/desktop ensure`.


## 0.22.0 — Major evolution

0.22.0 gives JARVIS its first controlled execution bridge into an OWNER-authorized Kali Linux VM and adds a feminine, context-driven social presence. The security boundary remains Core-enforced: the local model can select only fixed LAB profiles and cannot configure the bridge, authorize a target, or submit an arbitrary remote shell command.

### Kali Execution Bridge

The bridge uses the Windows OpenSSH client to reach a Kali VM that the OWNER has already placed inside Cyber Range LAB scope. Both the Kali host and every test target are reclassified immediately before each execution.

Integrated profiles:

- `nmap_services` — bounded TCP connect + lightweight service/version discovery; maximum 64 validated ports; XML parsed locally; no NSE scripts, OS detection, spoofing or evasion flags.
- `whatweb_fingerprint` — aggression 1 technology fingerprinting against a literal LAB IP/port; redirects and cookies disabled.
- `nikto_safe_web` — bounded web configuration/information checks with 90-second limit and tuning `123bde`; DoS, command-execution, SQL-injection, evasion and redirect-following profiles are excluded.

The bridge deliberately exposes **no arbitrary Kali shell**, no free-form command parameter, no exploit/payload profile and no model-accessible configuration action. Kali configuration exists only on the OWNER CLI.

OWNER commands:

```text
/cyber kali status
/cyber kali configure IP USER [PORT] [KEY_PATH]
/cyber kali doctor
/cyber kali inventory
/cyber kali nmap IP [P1,P2,...]
/cyber kali whatweb IP PORT [https]
/cyber kali nikto IP PORT [https]
/cyber kali clear
```

Typical isolated VirtualBox/VMware workflow:

```text
/cyber lab add 192.168.56.0/24 Virtual Lab
/cyber kali configure 192.168.56.2 kali 22 "C:\Users\Tiago\.ssh\jarvis_kali"
/cyber kali doctor
/cyber kali inventory
/cyber kali nmap 192.168.56.10 22,80,443,445
```

The SSH bridge uses batch/key authentication. JARVIS does not store a Kali password. `StrictHostKeyChecking=accept-new` and a JARVIS-specific known-hosts file protect subsequent connections against an unexpected host-key change.

### Adaptive Feminine Presence

The default neural voice is now `pt-PT-RaquelNeural`, tuned as the local `velvet_feminine` profile with a slightly slower rate and lower pitch. Windows SAPI fallback prefers a female Portuguese voice when available.

Existing 0.20 settings are preserved during update. On first 0.21 startup, only untouched 0.20 voice defaults (`DuarteNeural`, `-7%`, `-16Hz`) are migrated to the new feminine profile. A custom voice/rate/pitch previously chosen by the OWNER is not overwritten.

The companion layer is model-driven rather than a phrase scheduler:

- deterministic gates decide only whether it is an appropriate time to ask the local planner;
- Qwen decides whether to speak or remain silent;
- Qwen writes the message at that moment from recent local context;
- there is no table of prewritten flirt lines or random flirt selector;
- contextual flirt is enabled by default at intensity `0.60`, capped to one companion message per hour by default;
- flirt stays non-explicit and is suppressed in security incidents, health/legal issues, serious emotional conflict or financial stress;
- the persona does not claim consciousness, genuine desire, jealousy, exclusivity or emotional dependency.

Controls:

```text
/voice feminine
/voice test
/companion status
/companion on
/companion off
/companion flirt on
/companion flirt off
/companion intensity 0.0
/companion intensity 0.8
```

This is contextual model initiative, not a claim of subjective volition: the timing gate creates opportunities, and the local model can independently choose silence or generate a warm/playful/flirty message according to context.

### Upgrade behavior

`settings.json`, `apps.json`, `memory/`, `knowledge/`, voice profiles, models and logs remain runtime/user state and are preserved by the updater. `Settings.ensure_file_schema()` now also runs before settings are loaded at normal startup, so schema/voice migrations apply reliably after an in-place update.

## 0.22.0 validation

- 445 unit/regression/contract tests in the final release suite.
- 205 controlled Python files (Core, tests and launcher) syntax-validated.
- 225 immutable release files covered by SHA-256 manifest.
- Kali bridge is contract-tested without arbitrary shell APIs or model-controlled configuration.
- Companion initiative is contract-tested as tool-free and without prewritten flirt phrase tables.
- 0.20.6 Capability Intent Guard, 0.20.5 Cyber Range Guard, OWNER/STRICT, response continuation and Barge-In remain preserved.

## 0.20.5 — Cyber Range Guard & Lab Probe

0.20.5 turns cybersecurity target scope into deterministic Core policy instead of leaving it to prompt interpretation. The OWNER can explicitly register private VM/lab IPs or narrow private subnets; the local model can inspect that authority but cannot grant it to itself.

- Target classes: `LAB`, `OWNER_MACHINE`, `PRIVATE_UNAUTHORIZED`, `EXTERNAL`.
- LAB scope is explicit; RFC1918/private addresses are never automatically treated as authorized targets.
- Only the OWNER CLI path can add/remove LAB scopes.
- Public targets cannot be registered as LAB in this release.
- IPv4 lab networks are limited to /24 or narrower; IPv6 to /64 or narrower.
- OWNER_MACHINE always wins over an overlapping LAB subnet and remains defensive-audit/hardening scope.
- New bounded `probe_cyber_lab_target` performs TCP-connect checks on at most 32 ports and refuses every non-LAB target.
- The probe performs no exploitation, payload execution, banner collection, shell or PowerShell execution.
- The Qwen system policy now tells JARVIS not to issue generic cyber refusals: classify target → use integrated capability in LAB → explain evidence → detection/mitigation → retest.
- It must also distinguish knowledge of Kali tools from actual installed/integrated execution capability.

OWNER commands:

```text
/cyber lab status
/cyber lab add 192.168.56.10 Metasploitable
/cyber lab add 192.168.56.0/24 VirtualBox Lab
/cyber lab classify 192.168.56.10
/cyber lab probe 192.168.56.10 22,80,443,445
/cyber lab remove 192.168.56.0/24
```

## 0.20.5 final validation

- 419 unit/regression tests passed.
- 197 Python files syntax-checked.
- 217 immutable Core files in the release manifest.
- 141 controlled test files covered by the manifest.
- No arbitrary shell/PowerShell/Kali command executor added.
- OWNER/STRICT and 0.20.4 response continuation/full-speech behavior preserved.


## 0.20.4 — Response Completion & Full Speech

0.20.4 fixes local answers that stopped mid-sentence when the active performance profile reached its Ollama `num_predict` budget. The Core now detects a length-limited completion and performs bounded, tool-free continuation turns until the answer finishes naturally or the continuation ceiling is reached.

- FAST/ECO profiles remain fast; their initial token budgets are not globally inflated.
- Explicit Ollama length/maximum-token termination triggers continuation.
- Older Ollama responses are also detected through `eval_count` reaching the requested `num_predict` while the text ends mid-sentence.
- Continuations are local Qwen-only, tool-free and request-scoped.
- Maximum automatic continuations: 3 by default.
- Continuation segments are merged with overlap removal to reduce repeated phrases.
- Only the final combined assistant answer is stored in conversation history.
- Terminal output therefore receives the complete combined response.
- TTS no longer treats `speech_max_chars` as a total-answer cutoff. It is now a per-segment queue limit, so long answers are spoken in sequence.
- `Cala-te` still cancels the active speech segment and clears the remaining queued segments.

## 0.20.4 final validation

- 408 unit/regression tests passed.
- 194 Python files syntax-checked.
- 214 immutable Core files in the release manifest.
- 139 controlled test files covered by the manifest.
- No external-AI runtime route added.
- OWNER/STRICT, Smart App Control compatibility, local research, memory and Vault boundaries remain unchanged.

## 0.20.3 — Direct URL Learning Router

0.20.3 fixed explicit URL learning orders that could fall through to the generic Qwen tool loop. URL learning is deterministic Core behavior, bounded to the supplied public site and protected by OWNER/STRICT.

- Explicit URL + learning authorization is intercepted before normal Qwen routing.
- Same-host/same-path bounded crawl, depth 1, maximum 4 pages by default.
- Local/private targets, external child domains, downloads and executable content remain blocked.
- Local synthesis receives no tools and treats web text as untrusted data.

## 0.20.1 — Learned-Knowledge Retrieval

Relevant owner-authorized learning is now retrieved automatically from the local journal before Qwen answers. This fixes generic answers after successful learning while preserving local-only reasoning and OWNER/STRICT.

## 0.20.1 final validation

- 380 unit/regression tests passed.
- External AI runtime routing is disabled for ordinary work; 0.27.4 reserves it for explicit or complex-only escalation.
- Direct HTTPS research + local Qwen synthesis enabled.
- Web synthesis exposes no tools and treats source text as untrusted data.
- Local/private URL targets blocked by the research fetcher.
- Preserved 0.19 settings are normalized to local-first by setup schema migration.
- OWNER/STRICT remains required for autonomous external learning.


## 0.20.1 — No external AI runtime

JARVIS reasons with local Ollama/Qwen first. Current/public research uses direct HTTPS search/fetch and local Qwen synthesis. In 0.27.4 external AI is a secondary route only for an explicit OWNER request or a genuinely complex task after a local attempt; it is never selected merely because the PC is under load. Legacy settings/files remain for safe upgrades.

Commands:
- `/research status` — direct-web/local-synthesis status.
- `/research test` — live research smoke test.
- `/research TEXT` or `/web TEXT` — explicit direct Internet research synthesized locally.
- `/cloud status` — confirms external AI runtime is disabled.
- `/privacy on` — blocks external network research while preserving local reasoning.


O JARVIS passa a ter uma base de conhecimento persistente de cibersegurança.

## Armazenamento

```text
knowledge\cyber\cyber_knowledge.sqlite3
```

A base é runtime e não é substituída em upgrades.

Cada registo guarda:
- fonte / publisher;
- URL;
- categoria;
- identificador externo (CVE, ATT&CK ID, etc.);
- proveniência;
- nível de confiança;
- data de recolha;
- SHA-256;
- metadata estruturada.

## Fontes

Sync standard:
- NIST Cybersecurity Framework 2.0
- NIST SP 800-53 Rev. 5
- OWASP Top 10:2025
- Microsoft Windows Security
- CISA Known Exploited Vulnerabilities

Sync full acrescenta:
- MITRE ATT&CK Enterprise STIX

O ATT&CK é deliberadamente bulk e não é descarregado automaticamente num
Core novo.

## Comandos

```text
/cyber knowledge status
/cyber knowledge search ransomware
/cyber knowledge sync
/cyber knowledge sync full
/cyber knowledge sync source cisa_kev
/cyber knowledge ingest "C:\Users\tiago\Documents\security.pdf"
```

## Aprendizagem automática

- cria a vault no arranque;
- começa com 12 notas-base curadas;
- 120 segundos após o arranque pode atualizar as fontes standard;
- volta a verificar aproximadamente a cada 24 horas;
- MITRE ATT&CK completo é ativado no primeiro sync full.

## RAG local

Perguntas de cibersegurança recebem contexto pesquisado na vault antes de o
Qwen responder.

Exemplos:

```text
Jarvis, explica RDP.
Jarvis, o que sabes sobre ransomware?
Jarvis, explica o CVE-...
Jarvis, explica T1059.
```

As perguntas cyber são local-first, salvo pedido explícito para cloud/web.

## Proveniência

```text
official-web-import
official-machine-readable
curated-seed
local-file-import
```

Uma nota curada pelo JARVIS nunca deve ser tratada como documentação oficial.

## Segurança

- HTTPS obrigatório;
- hosts web allowlisted;
- limites máximos de download;
- conteúdo descarregado nunca é executado;
- SQLite local;
- pesquisa READ_ONLY;
- sync/import LOW;
- ferramentas da vault não ficam allowlisted para cloud por defeito.


## 0.13.1 — Windows SQLite handle fix

Cyber Knowledge Vault now closes every SQLite connection deterministically.
The sqlite3 connection context manager commits/rolls back but does not close
the connection; on Windows that could keep temporary `.sqlite3`, `-wal` and
`-shm` files locked and cause `WinError 32` during test cleanup.


## 0.14.0 — System Cyber Auditor

Novo auditor determinístico:

```text
/cyber analyze system
/cyber analyze system full
/cyber analyze system raw
```

Também em linguagem natural:

```text
Jarvis, analisa a segurança do meu sistema.
Jarvis, faz uma análise de segurança completa ao meu PC.
Jarvis, analisa o meu sistema com a tua base de conhecimento.
```

### Controlos

- contas/admins;
- sessões RDP/SMB;
- software remoto conhecido;
- Firewall;
- Defender;
- Security Watch/baseline;
- UAC;
- RDP NLA;
- SMB1/SMB2;
- Secure Boot;
- BitLocker/Device Encryption;
- hotfix mais recente;
- idade das assinaturas Defender;
- listeners e ligações públicas como contexto;
- correlação com a Cyber Knowledge Vault.

A recolha e a severidade são determinísticas. O LLM não decide o que foi
observado.

### Anti-falsos-positivos

- LISTEN não significa vulnerabilidade;
- ligação pública normal não prova intrusão;
- RDP ativo não prova sessão remota;
- software remoto pode ser legítimo;
- um CVE existente na vault não prova que afeta este PC.

A 0.14.0 ainda não faz CVE matching exato por produto/build/patch.


## 0.15.0 — Deep Security Inspection

Comandos:

```text
/cyber inspect network
/cyber inspect network full
/cyber inspect network raw
/cyber inspect listeners
/cyber inspect connections
```

Também em linguagem natural:

```text
Jarvis, investiga os listeners.
Jarvis, analisa as ligações públicas.
Jarvis, faz uma inspeção profunda da rede.
```

### Enriquecimento local

Cada listener/ligação tenta obter:

```text
PID
processo
caminho do executável
utilizador
data de arranque do processo
assinatura Authenticode
signer
company
product
file version
serviços Windows do PID
regra Firewall inbound allow correspondente
```

### Classificação

```text
expected
observed
review
unknown
```

`expected` não significa "garantidamente seguro"; significa que os sinais
locais são consistentes com software/Windows conhecido e assinatura válida.

### Privacidade e segurança

- apenas dados locais;
- sem consulta de reputação externa de IP nesta versão;
- sem shell arbitrário;
- PowerShell é um script fixo;
- READ_ONLY;
- sem terminar processos;
- sem alterar firewall;
- sem desativar serviços.


## 0.15.1 — updater de release

Esta release corrige o risco de uma instalação ficar misturada (por exemplo,
testes 0.15 com `cli.py`/`__init__.py` ainda em 0.14).

Não é recomendado fazer merge manual no Explorer para esta atualização.

Usar:

```powershell
cd <pasta extraída>\JARVIS_Core_0.15.1
.\update_core.ps1
```

O updater:
- recusa atualizar enquanto `jarvis.py` estiver em execução;
- sobrescreve `jarvis_core`, `tests` e `defaults`;
- preserva `memory`, `knowledge`, `.venv`, `.cache`, logs, modelos e perfis;
- preserva `settings.json` e `apps.json`;
- valida SHA-256 de ficheiros críticos;
- confirma versão 0.15.1;
- confirma que os comandos `/cyber inspect ...` existem.

Depois:

```powershell
cd G:\JARVIS
.\setup.ps1 -SkipModel
```

Ou executar tudo de uma vez:

```powershell
.\update_core.ps1 -RunTests
```

## 0.16.0 — Personal Cognition + Proactive Presence

O JARVIS passa a ter quatro conceitos separados: Personal Model, Functional Self Model, Bounded Reflection e Proactive Presence.

Isto **não** é uma afirmação de consciência subjetiva. O JARVIS pode dizer corretamente que mantém memória persistente, um modelo funcional de si próprio, um modelo local do utilizador, reflexão limitada e iniciativa. Não deve afirmar que sente, que possui experiência interior ou que a consciência subjetiva foi demonstrada.

### Aprendizagem pessoal local

A camada observa conversas e aprende apenas sinais explícitos como preferências, objetivos, limites, projetos e frequência de temas. API keys, tokens e passwords são redigidos; atributos pessoais sensíveis não são inferidos automaticamente; o modelo pessoal não é automaticamente enviado à cloud.

### Comunicação espontânea

Enquanto o Core estiver aberto, o JARVIS pode iniciar comunicação quando existe um motivo concreto: compromisso da agenda próximo, novo objetivo/projeto explícito após período de inatividade, ou tema recorrente. Existem guardrails de inatividade, intervalo mínimo, máximo por hora e horas silenciosas.

Comandos:

```text
/mind status
/mind profile
/mind reflect
/mind self
/mind state
/mind why
/mind learning on
/mind learning off
/mind proactive on
/mind proactive off
/mind speech on
/mind speech off
```

### Deep Security Inspection 2.0

- processos protegidos resolvidos por Get-Process, CIM, serviço e caminho canónico;
- assinatura Authenticode também recolhida do executável do serviço;
- processos Windows core deixam de ser UNKNOWN quando existe identidade local suficiente;
- PID 0 de ligação transitória passa a TRANSIENT;
- pares IPv4/IPv6 do mesmo PID/porta são agrupados como listeners lógicos;
- OBSERVED significa identidade/caminho confirmado mas prova criptográfica insuficiente.

### Updater 0.16.0

`update_core.ps1` suporta `Source == Destination`. Nessa situação valida a release e não tenta copiar `jarvis.py` sobre ele próprio.


## 0.16.1 — Self-Audio Guard

Corrige o caso em que a saída TTS do próprio JARVIS podia ser captada pelo
microfone e coincidir falsamente com o perfil acústico "Cala-te".

Antes:

```text
TTS -> microfone -> acoustic match -> speech.stop()
```

Agora:

```text
TTS -> microfone
      ↓
acoustic match "Cala-te"?
      ↓ sim
Whisper confirma literalmente "Cala-te"?
      ├─ não -> SELF_AUDIO_REJECTED -> continua a falar
      └─ sim -> VOICE_INTERRUPT_DETECTED -> speech.stop()
```

Durante a cauda de eco após `SPEECH_FINISHED`, nenhum candidato de interrupção
é aceite.

O stream JBL continua aberto; não há hard suspend/reopen.

Eventos de diagnóstico:

```text
VOICE_INTERRUPT_TRANSCRIBED
VOICE_INTERRUPT_REJECTED_SELF_AUDIO
VOICE_INTERRUPT_TRANSCRIPTION_FAILED
VOICE_INTERRUPT_DETECTED
```

`VOICE_INTERRUPT_DETECTED` passa a incluir:

```text
confirmation = acoustic+whisper
```


## 0.17.0 — Canonical Baseline

Esta release foi reconstruída a partir do `JARVIS.zip` real da instalação,
auditado antes de qualquer alteração.

Principais mudanças:

- Barge-In v2 para `Cala-te`;
- updater com `/MIR` nas árvores controladas;
- remoção automática de `__pycache__` e `.pyc`;
- migração não destrutiva do schema de `settings.json`;
- tokens `/confirm` expiram após 10 minutos;
- manifesto SHA-256 integral da superfície imutável da release;
- Wallpaper mantido como add-on separado.

Instalação recomendada:

```powershell
cd "<pasta extraída>\JARVIS_Core_0.17.0"
.\update_core.ps1
```

Depois:

```powershell
cd G:\JARVIS
.\setup.ps1 -SkipModel
.\verify_release.ps1
```

Não é recomendado voltar a atualizar arrastando manualmente todos os ficheiros
por cima de `G:\JARVIS`. O updater preserva os dados persistentes e elimina
ficheiros obsoletos apenas nas árvores que pertencem ao Core.


## 0.17.1 — updater integrity hotfix

A 0.17.0 tinha um erro de instalação: `update_core.ps1` estava protegido pelo
manifesto integral, mas não era copiado para o destino. Por isso a atualização
parava em `Hash inválido: update_core.ps1`.

A 0.17.1:
1. valida integralmente o pacote extraído;
2. só depois modifica `G:\JARVIS`;
3. copia também o próprio `update_core.ps1`;
4. valida integralmente o destino;
5. testa automaticamente a cobertura manifesto → instalador.


## 0.17.2 - PowerShell parser compatibility

Corrige o `ParserError` da 0.17.1 causado por `"$Label: ..."`.
A interpolacao segura passa a ser `"${Label}: ..."`.

`update_core.ps1` e `verify_release.ps1` usam agora mensagens ASCII-only
para compatibilidade visual com Windows PowerShell 5.1.


## 0.17.3 - Core manifest scope

Corrige o falso erro de manifest causado por add-ons existentes dentro de
`G:\JARVIS`.

O manifesto do Core cobre apenas:
- `jarvis_core`
- `tests`
- `defaults`
- ficheiros top-level oficiais da release

Add-ons externos como o Live Wallpaper ficam fora do manifesto e continuam
preservados.

O updater remove audits antigos `AUDIT_0.*.md` e mantem apenas o audit da
release atual.


## 0.18.0 - Performance & Resource Intelligence

New commands:

```text
/perf status
/perf auto
/perf fast
/perf balanced
/perf deep
/perf eco
/perf release
```

AUTO is recommended.

The local Qwen request now uses selective tool schemas and a dynamic inference
budget. GPU telemetry is cached separately from CPU/RAM telemetry. Under
sustained system pressure, background work is deferred and the local model can
be unloaded from VRAM.

Manual modes:
- FAST: lowest latency.
- BALANCED: normal balance.
- DEEP: maximum local reasoning/context.
- ECO: lowest local CPU/GPU/RAM use.


## 0.18.1 - Windows Block Preflight

Before importing the main CLI/native dependencies, `jarvis.py` performs a
read-only Windows Block Audit.

It checks current Mark-of-the-Web (`Zone.Identifier`) on relevant Core/native
files and recent CodeIntegrity/App Control/Smart App Control/AppLocker events.

Commands:

```text
/security blocked files
/security blocked files full
/security blocked files raw
```

The audit is diagnostic only. It never unblocks files automatically.


## 0.18.2 - MOTW classification

MOTW is now separated from an actual Windows block.

Example:

```text
[PREFLIGHT] Windows Block Audit: INFO |
MOTW=166 (nativos=0, py=145, scripts=21) |
bloqueios confirmados=0 | integridade=0
```

Native `.dll/.pyd/.exe` files carrying MOTW are shown as `REVER`, but are still
not called blocked unless Windows event evidence confirms a block.

Optional updater mode for a trusted, hash-verified Core release:

```powershell
.\update_core.ps1  # verified Core files are unblocked automatically after SHA-256 validation
```

This removes MOTW only from manifest-controlled release files after source and
destination hash validation. External add-ons, `.venv` and user/runtime data are
not touched.


## 0.19.0 - Owner Authority & Autonomous Learning

JARVIS can now decide that external research/cloud reasoning could help, but
autonomous external actions are controlled by the owner.

Example:

```text
Senhor, quero pesquisar na Internet sobre esta atualização.
Motivo: a pergunta requer informação atual.
Não vou avançar sem a sua autorização.
Para autorizar apenas esta ação: /authorize A1B2C3
Para recusar: /deny A1B2C3
```

Authorization is:
- exact scope;
- one use;
- expiring;
- locally audited;
- impossible for the model to grant to itself.

Commands:

```text
/autonomy status
/autonomy pending
/autonomy history
/autonomy revoke
/authorize TOKEN
/deny TOKEN
```

Direct user orders such as `pesquisa na Internet ...`, `/web ...`, `/cloud ...`
or `/sol ...` authorize only that exact requested action and do not create a
standing permission.

Authorized external learning is stored locally in:

```text
knowledge/autonomy/authorized_learning.jsonl
```

This is public web research through the existing cloud web-search path. It is
not arbitrary browser automation or permission to log in, submit forms, buy
items or act on websites.


## 0.19.1 - CLI regex import hotfix

Fixes the startup/input crash:

```text
NameError: name 're' is not defined
```

`cli.py` now explicitly imports Python's standard `re` module before using
`re.fullmatch()` for natural-language owner authorization and denial commands.

The OWNER/STRICT authorization model itself is unchanged.


## 0.19.2 - Natural owner authorization

Natural explicit permission now works without a redundant token:

```text
Senhor > Tens a minha autorização para aprender sobre comportamento humano através da internet
JARVIS > Autorização direta reconhecida. Vou fazer uma sessão de pesquisa...
```

This remains one bounded research session. It does not become a permanent
permission.

A plain learning goal such as:

```text
Quero que tu aprendas tudo sobre comportamento humano
```

is recognized as a learning objective. If external research would help, JARVIS
creates a formal permission request instead of merely discussing the idea.


## 0.19.3

Use:

```text
/cloud diagnose
```

to safely see whether the effective OpenAI credential comes from
`OPENAI_API_KEY` or Windows Credential Manager, without showing the key.

Personal Cognition now migrates response-style requests such as:

```text
que respondas de forma humana
```

from `goal` to `preference`.


## 0.19.4 - Smart App Control STT Compatibility

Windows 11 Smart App Control can block PyAV native `.pyd` modules even when
they have no Mark-of-the-Web. Core 0.19.4 removes PyAV from the mandatory
microphone transcription path without weakening Windows security.

The microphone path is now:

```text
Microphone -> sounddevice -> PCM WAV -> NumPy float32/16 kHz -> faster-whisper
```

Key changes:
- `faster-whisper` is imported through a narrow PCM compatibility layer so its
  eager `import av` does not force PyAV native code to load.
- JARVIS decodes its own PCM WAV captures with the Python standard library and
  NumPy, resampling to 16 kHz when needed.
- `WhisperModel.transcribe()` receives a NumPy waveform, so `decode_audio()` and
  PyAV are not used for microphone STT.
- The PyAV compatibility stub fails closed if media decoding is accidentally
  requested; it does not emulate successful decoding.
- No App Control policy is changed and no blocked binary is unblocked.
- Setup validates the PCM Faster Whisper import path after dependency install.
- Windows Block Audit now recognizes the Smart App Control policy
  `VerifiedAndReputableDesktop` (`{0283ac0f-fff1-49ae-ada1-8a933130cad6}`),
  understands Code Integrity device paths, and distinguishes a historical PyAV
  block mitigated by the PCM path from an active unmitigated Core block.
- Startup diagnostics add a read-only Native Import Health probe for NumPy,
  sounddevice, CTranslate2 and the Faster Whisper PCM import path.

PyAV remains an indirect dependency of faster-whisper and may still be blocked
if another workflow explicitly tries to use PyAV media decoding. JARVIS
microphone STT no longer requires that code path.


## 0.19.5 - Cloud Failure Semantics & Safe 429 Diagnostics

- External learning that fails before a successful cloud answer is never stored as learned knowledge and the exact action is re-queued for fresh owner authorization.
- Rate-limit failures are classified as temporary versus quota/billing when OpenAI supplies a safe error code/type.
- `/cloud diagnose` exposes only the safe provider error code and retryability; API keys, request payloads and raw exception bodies remain hidden.
- No automatic authorization retry loop is introduced. The owner must explicitly authorize each new attempt.


## 0.19.6 - Explicit Personal Memory Semantics

- Explicit local-memory orders are intercepted deterministically before the LLM.
- Ordinary personal facts such as names, family relationships, preferences and goals may be stored locally when the owner explicitly asks.
- The Core no longer treats a spouse/partner name as a blanket privacy-policy refusal.
- Credential material (passwords, API keys, access/refresh tokens, private keys, PIN/CVV and recovery/seed phrases) is rejected by the ordinary memory store.
- Forceful wording such as `Isto e uma ordem` affects command intent but is not written into the stored fact.
- The updater now verifies the exact installed 0.19.6 version instead of accepting a stale previous-version marker.


### 0.19.6 validation

```text
365 tests: OK
Python syntax: 181 files OK
Immutable manifest: 201 files OK
Updater/verifier ASCII: OK
Runtime memory/knowledge/.venv in release ZIP: 0
```


## 0.19.7 - Manifest Completeness Hotfix

0.19.7 fixes a packaging integrity defect observed on Windows: release-controlled
test files could be copied by the updater even when they were absent from the
release manifest. The updater now compares the entire controlled source and
destination scope against the manifest before accepting a release, not only the
files already listed in the manifest. The verifier performs the same full-scope
check. This prevents unmanifested Core/tests/defaults files from being silently
installed.

No runtime memory, Vault, autonomy, cloud, STT, Smart App Control policy, or
SecurityPolicy semantics are changed by this hotfix.

### 0.19.7 validation

```text
367 tests: OK
Python syntax: 182 files OK
Immutable manifest: 202 files OK
Updater/verifier full controlled-scope check: OK
Runtime memory/knowledge/.venv in release ZIP: 0
```


## 0.19.8 - Manifest/Setup Alignment Hotfix

0.19.8 fixes a Windows setup defect discovered after 0.19.7: `setup.ps1` kept a second, hardcoded list of expected test files. New manifest-controlled regression tests could therefore be deleted as "obsolete" immediately before the suite ran, after which the manifest completeness test correctly failed.

The setup cleanup now derives its expected test set directly from `release_manifest.json`. The manifest is the single source of truth; there is no second test inventory to keep synchronized.

### 0.19.8 validation

```text
368 tests: OK
Python syntax: 182 files OK
Immutable manifest: 202 files OK
Setup test inventory: derived from release_manifest.json
Runtime memory/knowledge/.venv in release ZIP: 0
```


## 0.19.9 - Updater Version-Alignment Hotfix

0.19.9 fixes a post-copy updater defect discovered during the Windows 0.19.8 installation. The source tree, destination tree and manifest were validated successfully, but the final installed-version predicate still searched for the previous release marker `0.19.7` while reporting that `0.19.8` was required. This caused every otherwise-correct 0.19.8 update to fail after synchronization.

The updater now checks the exact current release marker. Regression coverage reads the manifest release, the package `__version__`, and the updater's final version predicate and requires all three to agree. This hotfix does not change runtime state, memory, Vault, cloud, autonomy, Smart App Control or SecurityPolicy behavior.

### 0.19.9 validation

```text
369 tests: OK
Python syntax: 182 files OK
Immutable manifest: 202 files OK
Updater installed-version alignment: OK
Runtime state in release ZIP: 0
```


## Listening resilience 0.23.2

If Always Listening stops responding, use `/listening status` to inspect microphone, wake stream, TTS suppression and watchdog state together. `/listening recover` performs a bounded wake-stream recovery without restarting the full Core. The Live Wallpaper publisher is asynchronous in this release so HUD disk I/O no longer runs inside latency-sensitive EventBus callbacks.

## Webcam A/V binding 0.23.2

0.23.2 can use one local webcam as the primary audio/video sensor. When webcam-primary mode is enabled, a clearly identified webcam microphone is ranked ahead of the legacy JBL preference for both one-shot microphone capture and the Always Listening wake stream. If the webcam disappears, JARVIS falls back to the legacy preferred/default input.

The Vision skill can enumerate camera indexes and recover from Windows camera index changes inside a bounded local probe range. Use `/av status`, `/av auto`, `/av microphones`, `/av cameras`, `/av mic N`, `/av camera N`, and `/av webcam on|off` to inspect or control the binding. Device choices are persisted in `settings.json` by OWNER CLI only.

Because the acoustic `Jarvis` wake profile was recorded through a particular microphone, re-run `/wake enroll` once after moving permanently to a new webcam microphone. Faster Whisper command transcription does not require retraining.

## 0.27.4 — Stability, Security Baseline & Strict Local-First

- Voice remains deliberately simple: WASAPI -> Silero VAD -> openWakeWord -> Faster-Whisper. The 0.27.2 wake pre-roll/hangover fix is retained.
- Fast Router tolerates common ASR verb variants such as `abrem Brave` without invoking the LLM.
- `repair_security_baseline.ps1` verifies release hashes, removes obsolete blocked voice dependencies, validates current native imports and requires **zero current active Windows blocks** without deleting historical Event Log evidence.
- The Windows Block Audit now distinguishes current active blocks from resolved/historical and explicitly mitigated events.
- Local reasoning is mandatory first. Resource pressure and ordinary local errors do not trigger external AI. External AI is reserved for explicit OWNER requests or genuinely complex work after a local attempt.
- Public-web research remains direct retrieval + local Qwen synthesis; using the web is not the same as using a cloud AI.
- Qwen keep-alive and STT preload favor the PC's own RAM/CPU for lower latency.
- `full_system_validation.ps1` performs release, unit, native-import, real WASAPI, Faster-Whisper, local Ollama, routing-policy and Windows-block acceptance checks.
- An explicit general OWNER Internet grant enables persistent read-only public web research as well as learning. It does not permit account actions, posting, purchases, arbitrary shell access or cyber-scope expansion.
- Kali VM can be launched visibly through VirtualBox or VMware and controlled through fixed defensive profiles. `/cyber kali vm watch` opens a live activity console.
- OWNER authorization can unlock supported non-critical capabilities for an exact action, but cannot disable OS security controls or expand Kali beyond the OWNER machine / explicitly authorized LAB boundary.

Recommended post-update acceptance flow:

```powershell
.\setup.ps1 -SkipModel
.\full_system_validation.ps1
```

A healthy 0.27.4 installation should report `active_blocks=0` and `native_failures=0`. Historical Code Integrity events may remain visible as resolved/mitigated by design.

### 0.27.6 identity dialogue reliability
Identity/self-state conversation is a first-class local path. Personal questions are classified broadly (not by one exact phrase), receive enough output budget to finish, and are regenerated as a whole if a local-model response hits the token limit. Hidden continuation prompts must never appear in user-visible dialogue.

### 0.27.6 Self-Grounding: state before language
The Synthetic Self now separates persistent drives, learned preferences and current situational intentions. Personal answers are grounded through a structured `JARVIS_SELF_GROUNDING` claim set before Qwen verbalizes them. Asking what JARVIS wants does not create a want by itself, and a permanent `help_owner` drive is not treated as a current intention. If no intention is active, JARVIS is expected to say so naturally instead of inventing one.


### 0.27.6 Self-Grounding determinism
Self-state repair checks are independent of the OWNER's persisted runtime memory. Generic drive-derived statements such as `quero ajudar-te` cannot become a valid current desire merely because another active intention exists in `synthetic_self_state.json`; current-desire language must be grounded in a concrete situational intention.


### 0.27.7 security promotion hotfix
The updater and setup now remove Windows Mark-of-the-Web automatically **only** for release-manifest files whose SHA-256 hashes validate. Use `-PreserveMarkOfTheWeb` on `update_core.ps1` only when you explicitly want to keep MOTW. `repair_security_baseline.ps1` derives the active release from the manifest instead of hardcoding a previous version.


## 0.27.8 consolidated - JARVIS App Control observe-only

JARVIS no longer owns an App Control enforcement path in this release. `setup_appcontrol_trust.ps1` may build an **Audit Mode** policy for diagnostics, but there is no `Enforce` mode and it never changes the Windows Smart App Control registry state. This prevents JARVIS from blocking legitimate applications while its security model is still being developed.

Safe flow (elevated Windows PowerShell when a policy operation is requested):

```powershell
.\setup_appcontrol_trust.ps1 -Mode Prepare
.\setup_appcontrol_trust.ps1 -Mode Audit
.\setup_appcontrol_trust.ps1 -Mode Status
.\setup_appcontrol_trust.ps1 -Mode Disarm
```

`Prepare` creates verified runtime inventory and audit-only artifacts without changing Windows policy. `Audit` can install only a policy containing `Enabled:Audit Mode`. `Disarm` removes non-system JARVIS App Control policies, including the legacy `JARVIS Smart App Control Derived*` and `JARVIS ASUS Compatibility*` policies, supplemental policies first. `Rollback` remains only as a backward-compatible alias for `Disarm`; it no longer restores or changes Smart App Control state. Historical `enforced_native_verified` state is ignored by setup/native-brain selection, so a stale state file cannot restore policy coupling.

### Grounded direct-web learning (0.27.8 acceptance v7)
Time-sensitive learned facts are stored only after source-grounding checks. For current/latest version questions, JARVIS uses fetched source evidence rather than model memory. Pre-v7 freshness-sensitive direct-web records are quarantined and excluded from active recall while remaining available in the audit journal.

### 0.27.8 acceptance hotfix v9

The v9 acceptance hotfix consolidates real-machine fixes for exact tool routing, Action Truth, grounded SELF_STATE, OWNER/relational memory, autonomy-pending inspection, authorized-learning/quarantine audit, learning-confidence semantics and 8K llama.cpp prompt budgeting. External AI remains hard blocked; public-Web evidence is synthesized only by the local JARVIS brain.


### 0.27.8 acceptance hotfix v10

v10 consolidates the failures observed during the extended real-machine acceptance pass after v9. The fixes are centralized rather than prompt-only: named external-AI providers are hard-blocked before Web routing; desire/self-state, autonomy, personal-goal and authorized-learning queries have deterministic paths; explicit output constraints such as "apenas os tópicos" are honoured; public-Web research is separated from durable learning; explicit URLs are treated as Web sources unless the OWNER explicitly asks JARVIS to study/learn them; and source-grounded deterministic fallbacks can answer narrow version/official-site questions when local synthesis fails.

Desktop Agent routing now distinguishes Notepad++ from Windows Notepad, treats permission questions as read-only, grounds application listings in the registry, supports pointer movement without clicking, and routes natural typing/hotkey requests to real confirmation-gated tools. Action Truth also rejects pseudo tool-call JSON/XML, unsupported completion claims and ungrounded visual claims when no tool completed successfully.

Natural screen-analysis requests now route to `analyze_current_screen`. Vision capture remains local-only. The multimodal client follows the current llama.cpp multimodal chat-completions contract and the Vision skill cross-checks the resulting description against local Windows window metadata; a contradictory result is retried once and then rejected as `VISION_GROUNDING_MISMATCH` rather than presented as observed fact.

Conversational output is normalized conservatively toward European Portuguese on both fast and normal local paths. Structured JSON/tool payloads are intentionally left unchanged.

### 0.27.8 acceptance hotfix v10.1 — Language Refinement

JARVIS now has a dedicated local final-language refinement layer. It applies conservative pt-PT grammar/localisation to normal prose before display and before TTS, while leaving code and machine-readable tool/JSON payloads untouched. Personal Cognition continues to learn explicit OWNER interaction preferences; this final pass makes their output presentation more consistent without introducing a second model call or any external AI.

### 0.27.8 acceptance hotfix v10.2 — App Control Observe-Only

The JARVIS-owned App Control enforcement path has been retired after live Windows acceptance exposed legitimate ASUS/Armoury Crate blocking. This hotfix removes Enforce artifact generation/deployment, removes JARVIS writes to the Smart App Control registry state, adds a targeted `Disarm` cleanup mode for legacy JARVIS policies, and keeps local compatibility fallback available regardless of stale enforcement state. Future blocking requires a new, explicit implementation rather than being reachable from this release.
