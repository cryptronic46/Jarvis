# JARVIS Live Wallpaper 0.1.0

Wallpaper Engine **Web Wallpaper** funcional, inspirado no visual aprovado,
ligado ao JARVIS Core 0.12.0 sem modificar o Core.

## Arquitetura

```text
Wallpaper Engine
      │
      │ HTML / CSS / JS
      ▼
JARVIS Live Wallpaper
      │
      │ HTTP local, READ_ONLY
      ▼
127.0.0.1:8765
      │
      ▼
JARVIS Wallpaper Bridge
      │
      ├─ telemetria CPU / RAM / GPU / rede
      ├─ memory/*.json
      ├─ .cache/environment_furadouro.json
      └─ logs/events.jsonl
             │
             ▼
       JARVIS Core 0.12.0
```

O bridge **só escuta em `127.0.0.1`** e não possui endpoints de escrita.

## O que já é vivo

- relógio e data;
- CPU, frequência e cores;
- RAM;
- RTX / utilização / temperatura / VRAM / clock;
- download e upload em tempo real;
- IP/interface local;
- clima do Furadouro;
- humidade;
- mar / altura de onda / período / temperatura;
- Security Watch;
- número de dispositivos ativos;
- agenda;
- estado do Core;
- estados JARVIS:
  - `IDLE`
  - `LISTENING`
  - `THINKING`
  - `SPEAKING`
  - `OFFLINE`;
- partículas e núcleo central animados;
- anéis que aceleram conforme o estado;
- waveform áudio-reativa através da API do Wallpaper Engine.

## Estados reais do JARVIS

O bridge lê `G:\JARVIS\logs\events.jsonl`.

Exemplos:

```text
WAKE_WORD_DETECTED -> LISTENING
THINKING_STARTED    -> THINKING
MODEL_REQUEST       -> THINKING
TOOL_EXECUTING      -> THINKING
SPEECH_STARTED      -> SPEAKING
SPEECH_FINISHED     -> IDLE
```

Não é uma animação de vídeo.

## Instalação rápida

Extrai a pasta e, em PowerShell:

```powershell
cd <pasta extraída>
.\install.ps1
```

Por defeito é instalado em:

```text
G:\JARVIS-Wallpaper
```

O Core esperado é:

```text
G:\JARVIS
```

## Testar antes do Wallpaper Engine

Depois do bridge estar ligado, abre:

```text
http://127.0.0.1:8765/
```

no Brave/Chrome.

API de diagnóstico:

```text
http://127.0.0.1:8765/api/health
http://127.0.0.1:8765/api/state
http://127.0.0.1:8765/api/snapshot
```

## Importar para o Wallpaper Engine

1. Abre **Wallpaper Engine**.
2. Vai a **Create Wallpaper**.
3. Arrasta:

```text
G:\JARVIS-Wallpaper\wallpaper\index.html
```

para o editor.
4. Guarda o projeto.
5. Aplica-o como wallpaper.

O Wallpaper Engine copia os ficheiros do Web Wallpaper para o seu projeto.
O bridge continua separado em `G:\JARVIS-Wallpaper`.

## Arranque automático do bridge

Depois de validarmos que está tudo correto:

```powershell
cd G:\JARVIS-Wallpaper
.\install_autostart.ps1
```

Para remover:

```powershell
.\remove_autostart.ps1
```

## Diagnóstico

Bridge visível:

```powershell
cd G:\JARVIS-Wallpaper
.\start_bridge.ps1 -Visible
```

Terminar bridge:

```powershell
.\stop_bridge.ps1
```

## Segurança

- sem alteração ao JARVIS Core;
- bridge apenas loopback;
- endpoints HTTP apenas `GET`;
- sem shell vindo do wallpaper;
- sem comandos de escrita;
- nenhum endpoint para executar ferramentas do JARVIS;
- sem dados enviados para servidores externos pelo wallpaper;
- o clima pode ser renovado usando a função READ_ONLY já existente no Core
  caso a cache local esteja expirada.

## Wallpaper Engine

O projeto usa APIs Web Wallpaper do Wallpaper Engine:

```javascript
window.wallpaperRegisterAudioListener(...)
window.wallpaperPropertyListener.applyGeneralProperties(...)
requestAnimationFrame(...)
```

O visualizador usa os 128 valores de áudio fornecidos pelo Wallpaper Engine
e aplica o FPS configurado globalmente.
