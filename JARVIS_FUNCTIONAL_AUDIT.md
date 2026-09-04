# JARVIS Functional Audit

Date: 2026-09-04  
Scope: current `G:\JARVIS` Core, excluding OWNER runtime data. Safety baseline: `codex/pre-functional-audit-20260904` points to commit `dba693f` before this audit work.

## Discovery method

The inventory is derived from the source tree rather than the existing suite alone: 94 Python modules, 1,513 public/internal definitions and 329 event emissions were discovered with `rg`. The release manifest is the immutable-source inventory; runtime data (`memory`, `knowledge`, `models`, `logs`, `voice_profiles`, `settings.json`, `apps.json`) is excluded and preserved.

| Capability | Implementation | Tests | Result | Bugs found / fix | Real-machine test required |
|---|---|---|---|---|---|
| Core startup, schema and manifest | IMPLEMENTED | schema, release, installer tests | PASS | UTF-8 STT mojibake repaired by migration | startup/update |
| Local Qwen / llama-server | IMPLEMENTED | executor, health, residency tests | PASS: real local validation 62 ms | none in current run | CUDA/VRAM under real load |
| Fast Path, intents, follow-ups and recall | IMPLEMENTED | router, intent, continuity tests | PASS | none in current run | optional conversational acceptance |
| Tool Registry and authorization | IMPLEMENTED | registry, policy, autonomy tests | PASS | none in current run | app-close confirmation |
| Book/PDF library | IMPLEMENTED | library and grounding tests | PASS | removed unnecessary LLM call on navigation-only evidence | PDF import/search |
| Synthetic Self, Companion, intimacy | IMPLEMENTED | self/identity/companion tests | PASS | global feminine grammar rule added; regression test added | dialogue acceptance |
| Memory, cognition, graph, learning | IMPLEMENTED | memory, cognition, learning/RAG tests | PASS | none in current run | persistence across restart |
| Web research/direct URL | IMPLEMENTED | research/relevance/privacy tests | PASS | network-dependent paths not exercised in this pass | public network test |
| Voice Engine v2 / wake / STT / Voice Lock | PARTIAL | voice/wake/STT/recovery tests | CODE PASS; physical input unavailable | stale mic index removed; physical microphone is currently absent | required |
| TTS / SAPI fallback / silence latch | IMPLEMENTED | speech, queue, silence tests | CODE PASS | none in current run | required |
| Desktop Agent / Vision / Wallpaper | IMPLEMENTED | desktop/vision/wallpaper tests | CODE PASS; desktop bridge started | none in current run | required |
| Guardian / security watch / Windows audit | IMPLEMENTED | guardian/security/block-audit tests | PASS; no active blocks | observe-only policy preserved | optional review |
| Cyber Range / Kali / Purple Team | REQUIRES REAL MACHINE | contracts and safety tests | NOT CONFIGURED | no arbitrary shell added | LAB configuration |
| Planner, Skills, diagnostics and safe repair | IMPLEMENTED | planner, skills, repair tests | PASS | none in current run | optional owner flows |
| Updater, migration, shutdown / VRAM release | IMPLEMENTED | updater, migration, VRAM tests | PASS | none in current run | required shutdown check |

## Executed evidence

- Full automated suite: 920 tests passed after the latest performance and persona work.
- Release integrity: manifest verification passed.
- Real startup/terminal acceptance: startup, status, performance governor, book status, voice doctor, a normal local answer and a PDF-grounded answer executed successfully.
- Measured: normal local response was 957 ms; Voice v2 wake inference measured 1.322 ms per 80 ms audio frame (about 60x realtime headroom).
- The deterministic PDF-reference route previously consumed about 9.1 seconds in a model call with no additional source evidence. It now bypasses the LLM and is regression-tested.

## Open real-machine limitation

Voice acceptance is blocked by current hardware state, not hidden as a passing test: WASAPI exposes a phantom ASUS microphone plus loopback outputs, while no physical microphone endpoint opens. The system correctly refuses loopback input. See `JARVIS_REAL_MACHINE_ACCEPTANCE.md`.

## Safety invariants retained

- No WDAC/App Control enforcement or policy modification was added.
- No Defender, Smart App Control, Code Integrity or Secure Boot control was weakened.
- No arbitrary PowerShell, cmd or Kali shell execution was added.
- OWNER data and mutable runtime stores were not committed or reset.