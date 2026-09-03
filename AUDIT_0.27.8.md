# JARVIS Core 0.27.8 — Consolidated Epistemic Learning + Runtime Trust Hotfix

## Release intent

0.27.8 keeps the JARVIS Core as the primary local orchestration brain and combines two lines that had diverged during development:

1. **Epistemic Learning & Permission-Gated Expert Escalation** — explicit local knowledge-gap detection, OWNER-authorized public-web study, persistent provenance/freshness metadata, request-scoped learned RAG, and an optional isolated external expert that is off by default and requires a separate one-shot authorization.
2. **Final 0.27.7 Windows/runtime hardening** — adaptive local executor, signed Windows exit-code handling, current corroboration for App Control events, pinned CUDA/Vulkan runtime verification, local compatibility fallback, and observe-only App Control diagnostics for the verified llama.cpp runtime.

The consolidated hotfix deliberately does **not** restore regressions present in the original 0.27.8 package. In particular, it does not revert to a native-only backend that aborts on `0xC0E90002`, does not treat historical Windows events as permanent active blockers, and does not erase an explicit OWNER external-expert opt-in during setup.

## Local brain / executor architecture

`local_llm_backend` is `jarvis_local`. This means JARVIS owns identity, memory, Synthetic Self, intent routing, grounding, learning, tools, permissions and final response synthesis; the executor only runs the local Qwen token computation.

Executor order:

`JARVIS Core -> verified llama.cpp CUDA -> verified llama.cpp Vulkan -> local Ollama/qwen3:8b compatibility executor (only if allowed and native execution is blocked)`

Important contracts:

- The Python Core does not import or depend on the Ollama Python SDK.
- Native `llama.cpp` remains preferred.
- CUDA and Vulkan archives are pinned and SHA-256 verified before use.
- Windows exit code `-1058471934` is reinterpreted safely as `0xC0E90002`; PowerShell never casts the negative value directly to `UInt32`.
- A blocked native executor is not fatal when a healthy local compatibility executor is explicitly allowed.
- `/quit` releases the selected local model/runtime; the compatibility path requests `keep_alive=0` for Qwen.
- Legacy `enforced_native_verified` state is ignored; App Control enforcement by JARVIS is retired and the compatibility fallback remains available.

## Windows Pro App Control — observe-only correction

`setup_appcontrol_trust.ps1` remains part of the controlled release only for verified runtime inventory, Audit Mode diagnostics, status and legacy cleanup. The live-machine acceptance pass demonstrated that a JARVIS-derived enforcement policy could block legitimate vendor software outside the JARVIS runtime. Therefore this hotfix removes the JARVIS Enforce path entirely.

The supported flow is:

`Prepare -> Plan/Audit -> Status -> Disarm`

Security properties:

- Any JARVIS policy created by this release contains `Enabled:Audit Mode`.
- No enforced policy artifact is generated and no code path deletes Audit Mode.
- JARVIS does not write `VerifiedAndReputablePolicyState` or otherwise change Microsoft Smart App Control state.
- `Disarm` removes only non-system JARVIS-managed App Control policies, including known legacy base/supplemental IDs and JARVIS friendly-name families; supplemental policies are removed before bases.
- `Rollback` is retained only as an alias for `Disarm` and does not change Smart App Control state.
- Exact-hash runtime inventory and ConfigCI batching remain available for audit diagnostics.
- Historical `enforced_native_verified` state cannot disable the local compatibility executor.

This release intentionally has **no App Control blocking authority owned by JARVIS**. Restoring an enforcement capability in the future requires a new explicit design and implementation.

## Final live-machine observe-only corrections

The correction preserves the useful diagnostic work from the earlier runtime-trust implementation—batched ConfigCI hashing, normalized Rule arrays, bounded probes and clean status reporting—while removing the unsafe operational consequence. No broad path allow rule, Defender disable, TESTSIGNING, integrity-check bypass or automatic Microsoft SAC state change is introduced.

## Startup latency optimization

A clean Windows Block Audit may now be reused for a short, bounded startup window (10 minutes by default, maximum 30 minutes) when the release/runtime/native-file metadata fingerprint is unchanged. The cache is accepted only after a clean full audit: active block events, failed native imports or a failed installed llama runtime make it ineligible. A cache hit also re-checks MOTW on the principal execution boundaries (`llama-server.exe`, `llama-server-impl.dll`, the venv Python executable and launch scripts).

This removes repeated Windows Event Log queries and native import/load probes from rapid restarts while keeping `/security blocked files` as an uncached authoritative audit. Set `JARVIS_STARTUP_SECURITY_CACHE_SECONDS=0` to disable the startup cache.

## Windows Block Audit semantics

Windows Event Log is historical evidence. Event IDs such as 3077/8004/8007 prove that a block occurred; they do not prove the same artifact remains blocked forever.

An event is counted as an active blocker only when current evidence corroborates it, for example:

- referenced artifact still has Mark-of-the-Web;
- current JARVIS native import probe fails; or
- current JARVIS `llama-server.exe --version` load probe fails.

Historical uncorroborated events remain visible and are never deleted. This preserves evidence without preventing setup because of a resolved event from an older runtime.

## Epistemic learning loop

Normal knowledge-gap path:

`local Qwen -> sufficiency check -> learned-knowledge check -> OWNER permission -> bounded public-web research -> local synthesis -> relevance validation -> persistent learning -> request-scoped RAG -> retry original request`

Contracts:

- A long/complex request is not automatically outsourced.
- A learning offer requires a deterministic local knowledge-gap signal.
- Safety/policy refusals and operational commands are not treated as knowledge gaps.
- Web study uses the existing Autonomy Guardian and exact `external_learning` authority unless a narrow standing public-web learning grant already exists.
- Learned material is locally synthesized and treated as untrusted reference data, not instructions.
- Storage occurs only after topic/relevance validation.
- Stored learning keeps source/provenance, `learned_at`, deterministic confidence metadata and source count.
- Knowledge state is exposed as `KNOWN`, `STALE` or `UNKNOWN`.
- General freshness defaults to 120 days; fast-moving topics use the shorter freshness policy implemented by the learning-gap service.
- Learned RAG is request-scoped and strong-match gated, so unrelated older research is not ambient conversation context.

Inspection commands include `/learning status`, `/learning topic TEXTO` and `/learning search TEXTO`.

## External AI boundary

External AI/LLM execution is structurally **HARD BLOCKED** in the 0.27.8 acceptance line. JARVIS may read the public Web when the OWNER explicitly authorizes public research, but all synthesis remains inside the local JARVIS/Qwen/llama.cpp runtime. OpenAI, Anthropic, Gemini, cloud fallback and external-expert execution are not valid answer routes. Legacy expert/cloud settings are revoked during settings migration and cannot authorize another AI.

## Conversation identity, Synthetic Self and memory

The consolidated release retains the 0.27.6/0.27.7 conversation work:

- `SELF_STATE_CONVERSATION` and `IDENTITY_DIALOGUE` routing;
- Synthetic Self v2, drives/preferences/active-intention separation and Self-Grounding;
- response repair for generic unsupported desire/identity boilerplate;
- Conversation Primacy;
- evidence-grounded previous-conversation recall;
- recall follow-up continuity such as `Falámos sobre o quê?`;
- truth gate preventing unsupported positive recall claims;
- deterministic fallback when recalled evidence exists but local generation fails.

## Setup/update safety

- Release files are manifest-controlled and SHA-256 validated before and after copy.
- Verified release files can have MOTW removed only after validation.
- `memory`, `knowledge`, `.venv`, logs, models, voice profiles, settings and app registry remain runtime/mutable state and are not overwritten as immutable release content.
- `setup.ps1` installs/prepares the local executor before the final security-baseline decision, so the Block Audit can corroborate the **current** runtime rather than only historical events.
- External-AI/expert settings are revoked by the local-only policy; no external expert route is valid in this acceptance line.
- App Control enforcement is not owned by JARVIS; stale legacy trust state cannot disable `local_llm_allow_ollama_compat`.

## Automated regression

The original uploaded 0.27.8 package passed **758/758** tests before consolidation.

The consolidated source tree adds the later security/runtime/App-Control suites and the acceptance hotfix regressions. Current v9 source regression: **877/877 tests passed** before packaging. The same suite is re-run from the extracted final ZIP before delivery.

Final approval on the target Windows machine still requires the real-machine acceptance path because GPU driver loading, App Control state, audio devices and current Windows policy cannot be certified inside the build container.


## Acceptance hotfix v5
- Corrige o segundo uso de Python inline em `setup_vision.ps1` ao atualizar `settings.json`; usa helper temporário UTF-8 e preserva os modelos já verificados.
- A aprendizagem por URL explícito devolve agora a síntese local pedida ao OWNER antes da nota de persistência.
- Remove wrappers `\\nJARVIS > ...\\n` que imprimiam `\n` literalmente no terminal.

### v7 grounding repair
Acceptance testing found that a topically relevant direct-URL synthesis could still select an obsolete version and persist it. v7 adds source-claim validation, deterministic freshness/version evidence, and quarantine of legacy freshness-sensitive direct-web records. The original quarantine journal is preserved for audit; unverified legacy records are not returned to the active learning RAG.

## Acceptance hotfix v9 — consolidated real-machine findings

The extended acceptance pass exposed repeated root causes rather than isolated prompt defects: tool-name imperatives could lose the requested tool, generic capability markers could select unrelated network/weather tools, Action Truth did not cover future/in-progress execution claims, SELF_STATE values could be improvised without reading runtime state, reverse relational recall was inconsistent, authorized-learning quarantine was not inspectable, and some fresh-session requests exceeded the 8K llama.cpp context before any tool call.

v9 addresses those causes centrally. Exact registered tool names take routing priority; capability markers are boundary-aware and respect negative tool constraints; Action Truth covers execution promises; SELF_STATE reports are read from local state tools; OWNER facts, JARVIS learning goals and model inference are separated; autonomy and learning inspection gain deterministic read paths; quarantine gets a read-only audit tool; confidence semantics distinguish source-diversity from claim truth; dotted version retrieval is exact-aware; and the 8K brain path uses a compact system contract plus prompt-budget compaction.

External AI remains structurally hard blocked. Public-Web learning remains a source acquisition path only; synthesis and memory admission remain local.


## Acceptance hotfix v10 — real-machine repair batch

The post-v9 acceptance run found several classes of remaining faults: provider-name gaps in the external-AI hard block; natural self-state/autonomy phrases falling through to Qwen; OWNER goals contaminated by assistant directives/transient utterances; quarantine/search formatters ignoring "only" constraints; public-Web search being conflated with learning; explicit URL claims being answered locally without a fetch; application-name aliasing (`Notepad++` -> Windows Notepad); permission questions executing actions; model-emitted pseudo tool calls escaping as text; missing natural routes for typing/hotkeys/pointer movement; and screen-vision descriptions being asserted despite contradictory evidence.

v10 repairs those boundaries at the Core/router/service level. External AI remains structurally unavailable. Public Web remains a source-acquisition path only and does not become durable learning without an explicit study/learn request. Desktop input primitives remain bounded and typing/hotkeys still require OWNER confirmation. A move-only pointer command is a separate low-risk action and never synthesizes a click. Vision remains entirely local and now fails closed if its description cannot be reconciled with local window metadata after a bounded retry.

The v10.2 regression suite contains **908 automated tests**. Final delivery additionally requires a clean manifest/hash validation and a second run from the extracted final ZIP. Real Windows acceptance is still required for UI focus/input, App Control, GPU/mmproj behaviour, audio devices and driver-dependent execution.

## Incremental v10.1 — pt-PT final language refinement

A deterministic local final-pass now sits between response generation and presentation, and the same pass is applied before TTS normalisation. This prevents written and spoken JARVIS from diverging on European-Portuguese grammar/localisation. The refiner does not alter JSON/tool payloads or code, does not perform factual rewriting, and has no external-AI/Web path. Personal Cognition remains enabled and its explicit interaction-style preferences are injected into the local brain context.

## Hotfix v10.2 — JARVIS App Control observe-only

Live Windows acceptance confirmed that the former JARVIS-derived enforcement policy could disrupt ASUS Update, ROG Live Service, Aura/Fan HAL installation, Armoury Crate and unrelated signed components. v10.2 therefore removes enforcement artifact creation/deployment and SAC registry mutation from the controlled source. `Disarm` is the supported cleanup path for legacy JARVIS policies.
