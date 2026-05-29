# MyWhispr

Local hold-to-record dictation for GNOME Wayland.

MyWhispr runs as a user daemon, records audio with PipeWire, transcribes with
local ASR backends, and pastes the result into the focused app with
`wl-copy`/`ydotool`. The web UI is local-only:

```text
http://127.0.0.1:16666/
```

## Current Shape

- GNOME Wayland hold-to-record workflow.
- Configurable trigger and combo modes from the web UI.
- Bounded keyboard grab while recording so combo keys do not leak into apps.
- PipeWire input-device selection.
- Local history with retained in-memory audio and manual retranslate.
- Whisper.cpp models plus GPU ASR backends for Parakeet, Canary, Qwen, Cohere,
  Granite, and Seamless M4T.
- Live preview / streaming text path with guarded cancellation.
- GNOME Shell top-bar extension plus optional AppIndicator fallback.

The shipped default model is `large-q5`. Parakeet TDT 0.6B v3 is included as
the fast secondary model option.

## Requirements

- Linux desktop with PipeWire and GNOME Wayland.
- Python 3.10+.
- `pw-record`, `pw-play`, `wl-copy`, and `ydotool`.
- Read access to the selected `/dev/input/event*` devices.
- A local `whisper.cpp` server binary for whisper.cpp models.
- Optional GPU ASR Python environments for Hugging Face / NeMo models.

On Ubuntu-style systems:

```bash
sudo apt install pipewire-bin wl-clipboard ydotool python3-evdev python3-pyudev python3-aiohttp
```

## Install

```bash
git clone https://github.com/ibmua/MyWhispr.git
cd MyWhispr
cp config.example.json config.json
```

Edit `config.json` for your local model paths and ASR Python environments.
Then install the user service and GNOME shortcut:

```bash
./scripts/install.sh
```

Open the UI:

```bash
xdg-open http://127.0.0.1:16666/
```

## Commands

```bash
systemctl --user status mywhisprd --no-pager
journalctl --user -u mywhisprd --no-pager -n 120
./bin/mywhisprctl status
./bin/mywhisprctl start grave
./bin/mywhisprctl stop
```

## Models

Download whisper.cpp GGML models into `models/`:

```bash
./scripts/download-model.sh large-v3-q5_0
```

Download configured Hugging Face GPU ASR models into the local HF cache:

```bash
./scripts/download-gpu-asr-model.sh parakeet-tdt-0.6b-v3
./scripts/download-gpu-asr-model.sh canary-1b-v2
```

Model weights, virtualenvs, local config, and transcript scratch files are
intentionally ignored by git.

## Design Notes

The detailed rewrite design lives in `REWRITE_DESIGN.md`.
