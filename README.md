# MyWhispr

MyWhispr is a local hold-to-record dictation daemon for GNOME Wayland.
Hold the configured trigger key, speak, release, and the final transcript is
inserted into the focused app. Audio is recorded locally through PipeWire and
transcribed by local ASR backends by default. External transcription APIs are
available as explicit opt-in model cards.

The local control panel runs at:

```text
http://127.0.0.1:16666/
```

## Screenshots

![MyWhispr dashboard overview](docs/screenshots/dashboard-overview.png)

![MyWhispr settings and shortcuts](docs/screenshots/settings-shortcuts.png)

## What It Does

- Hold-to-record dictation with release-to-insert behavior.
- Configurable trigger key and combo shortcuts from the web UI.
- Live transcript preview while recording.
- Optional streaming into the focused app with guarded backspace/rewrite logic.
- Local history for recent dictations, including in-memory WAV playback.
- Manual retranscription of retained history through another configured model.
- PipeWire input-device selection.
- Custom vocabulary and hallucination phrase filtering.
- GNOME Shell top-bar indicator.
- Local-only HTTP UI bound to `127.0.0.1` by default.

## Platform Support

| Platform | Status | Notes |
|---|---:|---|
| Ubuntu / GNOME / Wayland | Supported target | Main development and test environment. Uses PipeWire, evdev, GNOME shortcuts, `ydotool`, and `wl-copy`. |
| Other Linux Wayland desktops | Possible, not guaranteed | Core pieces may work if PipeWire, `/dev/input`, `ydotool`, and `wl-copy` are available. GNOME shortcut and top-bar integration are GNOME-specific. |
| Linux X11 | Not supported | The app is designed around Wayland-era input and clipboard tools. |
| macOS | Not supported | No recording, hotkey, service, or output backend is implemented for macOS. |
| Windows | Porting groundwork only | The output layer has a Windows `SendInput`/Win32 clipboard backend, but the full daemon is not yet a Windows app. Recording, global hotkeys, service install, tray UI, and model setup still need Windows-specific work. |
| WSL / WSLg | Not supported | Global hotkeys, audio capture, and focused-app input are host-desktop problems, not normal WSL process capabilities. |

The app currently works best as a desktop daemon on GNOME Wayland. The code is
being kept portable where practical, but the shipping workflow is Linux-first.

## How Text Gets Inserted

MyWhispr separates transcription from output transport:

- Short printable ASCII text is typed directly through the synthetic-input
  backend. This avoids application-specific paste handling and keeps command
  snippets responsive.
- Longer text and non-ASCII text use clipboard paste fallback.
- On Linux Wayland, output uses `ydotool` plus `wl-copy --paste-once`.
- On Windows, the output backend maps the same operations to `SendInput` and
  the Win32 clipboard, but the rest of the app still needs a Windows port.

This is intentionally content-agnostic. MyWhispr does not special-case phrases
or leading words to decide whether insertion should work.

## Requirements

For the supported Linux/GNOME/Wayland setup:

- Python 3.10+.
- PipeWire tools: `pw-record` and `pw-play`.
- Wayland clipboard tool: `wl-copy` from `wl-clipboard`.
- Synthetic input tool: `ydotool` and a working `ydotoold` service/socket.
- Python packages used by the daemon: `aiohttp`, `evdev`, and `pyudev`.
- Read access to the selected `/dev/input/event*` keyboard devices.
- A local `whisper.cpp` server binary for whisper.cpp models.
- Optional GPU ASR Python environments for Hugging Face / NeMo models.

On Ubuntu-style systems:

```bash
sudo apt install pipewire-bin wl-clipboard ydotool python3-evdev python3-pyudev python3-aiohttp
```

## Install

Clone the repo and create a local config:

```bash
git clone https://github.com/ibmua/MyWhispr.git
cd MyWhispr
cp config.example.json config.json
```

Edit `config.json` for your local model paths, ASR Python environments, audio
input device, trigger key, and shortcut preferences.

Install the user service and GNOME shortcut:

```bash
./scripts/install.sh
```

Open the local UI:

```bash
xdg-open http://127.0.0.1:16666/
```

## Daily Use

The default workflow is:

1. Focus any text field, terminal, editor, or chat box.
2. Hold the configured trigger key.
3. Speak.
4. Release the trigger key.
5. MyWhispr transcribes locally and inserts the final text into the focused app.

Combo shortcuts can switch language or mode while the trigger is held. For
example, a setup can use one combo key for English, another for Ukrainian, and
another for non-streaming dictation.

## Commands

```bash
systemctl --user status mywhisprd --no-pager
journalctl --user -u mywhisprd --no-pager -n 120
./bin/mywhisprctl status
./bin/mywhisprctl start grave
./bin/mywhisprctl stop
```

## Models

Whisper.cpp GGML models can be stored in `models/`:

```bash
./scripts/download-model.sh large-v3-q5_0
```

Configured Hugging Face / NeMo GPU ASR models can be downloaded into the local
HF cache:

```bash
./scripts/download-gpu-asr-model.sh parakeet-tdt-0.6b-v3
./scripts/download-gpu-asr-model.sh canary-1b-v2
```

The included model catalog covers whisper.cpp models plus GPU ASR backends for
Qwen, Parakeet, Canary, Cohere, Granite, and Seamless M4T. The web UI can also
add OpenAI-compatible external API models such as `gpt-4o-transcribe`; set the
API key through an environment variable like `OPENAI_API_KEY` or the local
model form. Model weights, virtualenvs, local config, and transcript scratch
files are intentionally ignored by git.

## Architecture

MyWhispr is split into small local components:

- `mywhispr/daemon.py`: state machine, recording lifecycle, history, config,
  and final paste orchestration.
- `mywhispr/recorder.py`: PipeWire recording.
- `mywhispr/transcriber.py`: final ASR requests and text cleanup.
- `mywhispr/streaming.py`: live preview and optional app-output streaming.
- `mywhispr/paste.py`: platform output backend for typing, paste, copy, and
  backspace.
- `mywhispr/web.py` and `webui/`: local control-panel API and React UI.
- `extensions/mywhispr@local/`: GNOME Shell top-bar indicator.

The detailed implementation plan and design constraints live in
`REWRITE_DESIGN.md`.

## Privacy And Safety

- The daemon does not send audio to cloud APIs unless an external API model is
  explicitly selected.
- The default history is RAM-only and disappears when the daemon restarts.
- Temporary recordings live under `/run/user/$UID`, which is tmpfs on typical
  Linux desktops.
- The web UI binds to `127.0.0.1` by default.
- Transcript text is not logged by default.
- Config and custom words live in `config.json`; treat that file as
  user-confidential.

## Known Limits

- The web UI is desktop-oriented. It is not currently designed as a mobile UI.
- GNOME integration is first-class; other desktops may need launcher or shortcut
  work.
- Windows has an output backend scaffold, not a full supported release.
- Non-ASCII dictation uses the paste fallback by default because direct typing
  is limited to short printable ASCII text on the current Linux path.
