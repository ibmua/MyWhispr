# MyWhispr

Minimal hold-to-record dictation for GNOME Wayland.

MyWhispr is a small local daemon for push-to-talk speech transcription. It has no Electron UI, tray icon, floating overlay, or updater. It reads global key-release events from `/dev/input`, records with PipeWire, transcribes through a local `whisper.cpp` HTTP server, and pastes text with `wl-copy` plus `ydotool`.

This project was made as a co-work with Codex. It is intentionally easy to modify and custom-tailor to personal preferences: hotkeys, languages, model choices, prompts, custom vocabulary, paste behavior, web controls, and workflow-specific helper actions are all meant to be edited.

Think of it less as a finished consumer app and more as a compact framework for building your own dictation setup and local AI helper workflows.

The built-in local web UI runs on:

```text
http://127.0.0.1:16666/
```

The UI and HTTP API share that same local-only port. MyWhispr does not use port `6666`, because mainstream browsers block it as unsafe.

## Features

- Hold-to-record hotkeys with release-to-transcribe.
- Separate English and Ukrainian shortcuts.
- CUDA-capable `whisper.cpp` server integration.
- Local-only web UI and API on browser-safe port `16666`.
- Last five dictations with language labels and one-click copy.
- Current configuration summary in the web UI.
- Editable custom words list, persisted to `config.json`.
- Manual model warm/unload controls.
- OpenWhispr-style start/stop tone cues.
- Start cooldown after release, to ignore trailing GNOME shortcut repeats.
- Maximum-duration recordings are discarded instead of pasted, preventing accidental away-from-keyboard transcription.

## Default Hotkeys

- Hold `grave` / backtick: English.
- Hold `Ctrl+grave`: Ukrainian.

GNOME custom shortcuts should call:

```bash
/path/to/MyWhispr/bin/my-whisper-client start en grave
/path/to/MyWhispr/bin/my-whisper-client start uk ctrlgrave
```

The daemon listens to `/dev/input` for the real key release, so it works while another app is focused.

## Requirements

- Linux desktop with PipeWire.
- Python 3.10+.
- `pw-record` and `pw-play`.
- `wl-copy`.
- `ydotool` with a running user daemon and access to `/dev/uinput`.
- Read access to `/dev/input/event*` for the user running the daemon.
- A `whisper.cpp` compatible `whisper-server` binary and GGML model files.

On Debian/Ubuntu-style systems, useful packages include:

```bash
sudo apt install pipewire-bin wl-clipboard ydotool
```

CUDA support depends on the `whisper-server` binary you provide.

## Install

```bash
git clone https://github.com/ibmua/MyWhispr.git
cd MyWhispr
cp config.example.json config.json
```

Edit `config.json`:

- `whisper_server_binary`
- `models.large`
- `models.turbo`
- `models.small`
- `socket_path`, `runtime_dir`, and `ydotool_socket` if your UID is not `1000`
- `web.port` if you need a local port other than `16666`
- `start_cooldown_seconds` if your desktop sends repeated shortcut starts after key release

Then install the user service:

```bash
./scripts/install-user-service
```

Open the UI:

```bash
xdg-open http://127.0.0.1:16666/
```

## Commands

```bash
systemctl --user status my-whisper --no-pager
journalctl --user -u my-whisper --no-pager -n 120
./bin/my-whisper-client status
./bin/my-whisper-client warm
./bin/my-whisper-client unload
./bin/my-whisper-client stop
```

## Custom Words

Custom words bias the transcription prompt. Add them from the web UI or edit `config.json` directly.

Adding words from the UI does not require a daemon restart; the daemon updates `config.json` and reloads the in-memory prompt list immediately.

## Local Web UI

Open:

```text
http://127.0.0.1:16666/
```

The UI shows daemon state, loaded/unloaded model state, the active model, hotkeys, safety timers, the last five dictations, and the current custom words. Copy buttons use the browser clipboard when available and also call the local clipboard API.

## Notes

The listening and stopping cues reproduce OpenWhispr's bundled Web Audio tones:

- start: `523.25 Hz`, then `659.25 Hz`
- stop: `587.33 Hz`, then `440 Hz`

MyWhispr stores runtime logs and history under the configured `log_dir`. Those files are ignored by git.
