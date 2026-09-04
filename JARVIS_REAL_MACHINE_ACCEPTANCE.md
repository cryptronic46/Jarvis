# JARVIS Real Machine Acceptance

Run these after connecting the physical microphone/webcam. They are intentionally separate from automated tests because they depend on drivers, Windows sessions, audio routes, GPU and installed desktop software.

| Area | Owner action | Expected result |
|---|---|---|
| Startup | Start `G:\JARVIS\run.ps1` | No import/runtime errors; normal briefing |
| Microphone | `/voice doctor` then `/av probe` | A physical microphone opens; not a loopback endpoint |
| Wake word | Say “Jarvis” in a quiet room | One recognition; no repeated false wake |
| Command STT | “Jarvis, que horas são?” | Accurate pt-PT transcription and reply |
| Unplug/replug | Disconnect/reconnect the microphone while running | Backoff on `-9996`, automatic recovery after reconnect |
| Barge-in | While she speaks, say “cala-te” | Speech stops promptly; silence latch is visible |
| TTS | Ask a short and a long question | Female voice, natural first audio, complete chunked speech |
| TTS fallback | Temporarily make Edge voice unavailable only if you choose | SAPI fallback is reported, no crash |
| Qwen / VRAM | `/vram status`, ask a normal question, `/vram release` | Local model loads; configured VRAM is released |
| CUDA | Run the full validation while GPU is available | Native runtime/VRAM checks report actual backend |
| Desktop Agent | `/desktop status`, then an explicitly authorized safe observation | Correct windows/screen status; no unconfirmed mutation |
| Vision | Use explicit screen/camera command | Local-only visible result or explicit unavailable status |
| Wallpaper | Confirm Wallpaper Engine and bridge | Live HUD updates without duplicate processes |
| Startup shortcut | Launch the normal shortcut | It starts `G:\JARVIS`, not legacy `C:\JARVIS` |
| Shutdown | `/quit`, then inspect `/vram status` after restart if needed | No stranded JARVIS llama/STT process or configured model residency |

Current blocking observation: no physical WASAPI microphone was available during the audit. Do not select a loopback device to make this test pass; it would make JARVIS hear system/TTS audio rather than the OWNER.