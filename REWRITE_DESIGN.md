# MyWhispr Design

## Purpose

A small, reliable dictation daemon for GNOME Wayland. Hold a key, talk, release, text appears. That loop must be rock-solid; everything else is opt-in.

The daemon owns one job: get spoken audio in, get clean text out, paste it. Optional features (live preview, retranslate, top-bar indicator, on-the-fly streaming-into-app) attach to that loop in well-isolated modules and must each be able to fail without breaking dictation.

## Core Product Contract

- Press and hold `grave` → start recording (default mode: English on this workstation, configurable).
- Release `grave` → stop recording and paste the final transcript into the focused app.
- While holding `grave`, the daemon owns the configured keyboard devices with `EVIOCGRAB` until release. Press `1` during the hold to switch the whole current recording to Ukrainian. Hold `1` for more than the configured threshold to switch the whole current recording back to the default mode. The `1` keypress must not leak into the focused app.
- Mode switching is not mixed-input transcription. A recording has one current interpretation mode at any instant. Switching modes means reinterpreting the whole current audio in the latest selected mode. Any already-streamed/crystallized focused-app text from the previous mode is deleted, streaming state is reset, and the next hypothesis is made from scratch in the new mode.
- The hold key, default mode, combo key, combo target modes, and script modes are configurable from the local web UI. Any number of named shortcuts can be created, edited, and deleted. Saving a shortcut updates daemon trigger config and the GNOME custom shortcut when GNOME accepts that binding.
- Pressing `grave` again immediately after release must be possible with a short, sub-second cooldown only.
- The app must never require a second press to finish a recording.
- A `max_duration` safety stop saves the recording into history and never pastes into the focused app.
- Streaming-into-app (live backspace + paste rewriting) is on by default; releasing always converges to the final cleaned transcript in the focused app.
- Last 20 dictations (text + WAV bytes) are retained in process memory only by default. No disk history.
- The local web UI must never re-render audio elements while playback is active.
- Every settings control surfaced in the web UI must actually mutate daemon behavior. No decorative inputs.
- All network exposure is loopback-only: HTTP API, whisper-server, web UI.
- http://localhost:16666/ localhost-only web UI where model cards are click-to-switch, shortcuts/modes are configurable, live transcript shows the current mode/language, history shows the last 20 transcriptions with original audio, and manual retranslate can compare retained audio through another selected model. Model selection must be immediate: clicking a model writes `default_model` and warms it behind the scenes.
- prior work at https://github.com/ibmua/MyWhispr
- Make 100% sure that the tool wont get stuck at any state and will be 100% reliable.

## Non-Goals

- No Electron app.
- No automatic alternate transcription after every recording (retranslate is on-demand, batch, manual).
- No persistent audio backlog unless explicitly configured.
- No focus-stealing overlay window. Visual indication lives in the GNOME top bar and the web UI only.
- No unbounded keyboard grab: the daemon may grab configured keyboards only while a dictation trigger is held, and must always release on trigger release, stop, max-duration, device removal, process exit, or the hard safety timeout.
- No outbound network traffic at runtime. No telemetry, no auto-update, no model download.

## Recommended Technology

Python. The constraint is single-developer maintainability and direct Linux integration. Performance is not the constraint; CUDA `whisper-server` handles that.

- Python 3.12+.
- `asyncio` for process supervision, timers, request coordination.
- `python-evdev` for reading `/dev/input` and for `EVIOCGRAB`. It survives device hot-plug cleanly.
- `pyudev` for input-device hot-plug events.
- `aiohttp` (or `httpx`) for talking to the whisper-server; cancellable from asyncio.
- `pw-record` for capture.
- `pw-play` for cue tones.
- `wl-copy` plus `ydotool` for paste.
- `whisper.cpp` server (CUDA build where available) for transcription.
- Standard-library `http.server` for the web UI and JSON API.
- Plain HTML/CSS/JS for the local web UI. No frontend build step.
- GNOME Shell extension (JavaScript, ES modules for Shell 45+) for the top-bar indicator. No build step beyond `gnome-extensions pack`.

Optional later:

- SQLite for opt-in persistent history. Default stays RAM-only.

## Process Model

One user service:

```text
mywhisprd
```

It owns:

- Hotkey event state.
- Recorder process state.
- Whisper server process state for the primary model.
- In-memory dictation history.
- Local HTTP API and UI.
- The control Unix socket.
- The bounded keyboard grab while a dictation trigger is held.

The GNOME Shell extension runs in `gnome-shell`, separate from the daemon. It polls the daemon's HTTP API.

Suggested package layout:

```text
mywhispr/
  __main__.py
  config.py
  daemon.py
  state.py
  input_events.py
  triggers.py
  recorder.py
  transcriber.py
  whisper_server.py
  text_cleanup.py
  hallucination_filter.py
  paste.py
  history.py
  retranslate.py
  streaming.py
  web.py
  control.py
  tones.py
  models.py
extensions/
  mywhispr@local/
    metadata.json
    extension.js
    stylesheet.css
tests/
```

`mywhisprctl` is a thin client that opens the control socket, writes one JSON line, prints the reply, exits non-zero on `ok=false`. The daemon never shells out to itself.

## State Machine

Explicit state machine. Single source of truth. No state inferred from scattered booleans.

```text
IDLE
  start(trigger)             -> STARTING            if cooldown passed
  start(trigger)             -> IDLE  (ignored-repeat) if within cooldown
  stop                       -> IDLE  (no-op)

STARTING
  recorder_ready             -> RECORDING
  recorder_failed            -> IDLE  (error cue + error event)

RECORDING
  release(trigger_key)       -> STOPPING
  combo_key_press(code)      -> RECORDING (current mode switched, streamed text reset)
  max_duration               -> STOPPING_NO_PASTE
  recorder_exited_clean      -> STOPPING
  recorder_exited_error      -> STOPPING_NO_PASTE
  stop  (explicit)           -> STOPPING

STOPPING
  recorder_stopped           -> TRANSCRIBING

STOPPING_NO_PASTE
  recorder_stopped           -> TRANSCRIBING_NO_PASTE

TRANSCRIBING
  transcript_ready           -> PASTING
  no_text                    -> IDLE
  failed                     -> IDLE  (error event)

TRANSCRIBING_NO_PASTE
  transcript_ready_or_failed -> IDLE  (text saved to history, never pasted)

PASTING
  paste_done_or_failed       -> IDLE  (history records pasted=true|false)
```

Rules:

- Only `RECORDING` can transition out of key release.
- Only `IDLE` can start a new recording.
- `start` inside the cooldown window returns `ignored-repeat` with the age since last stop.
- `start` while not idle returns the current state, not a second recording.
- `stop` while not recording is a no-op and never errors.
- Default cooldown 200 ms, configurable in `[100, 400]` ms.
- Every transition is logged with trigger, age since last transition, and reason.

Handlers are direct method references registered in a dispatch table at module load. Missing handlers fail at daemon startup, not at user action time.

## Triggers

```json
"triggers": {
  "grave": {
    "default_mode": "en",
    "language": "en",
    "stop_on_release_codes": [41],
    "combo": {
      "enabled": true,
      "deadline_seconds": 1.2,
      "long_press_seconds": 0.5,
      "keys": [
        { "code": 2, "short_mode": "uk", "long_mode": "en" }
      ]
    }
  }
}
```

`grave` (keycode 41) is the default trigger. Holding `grave` records in its `default_mode`. While holding, pressing `1` (keycode 2) switches the current recording to the key's `short_mode`; holding that same combo key past `long_press_seconds` switches to its `long_mode`. That combo key must not reach the focused app.

Adding a new trigger creates a config entry plus a GNOME custom shortcut that calls `mywhisprctl`. The daemon also watches the configured physical stop keycodes so a missed GNOME shortcut signal has a short evdev fallback instead of requiring a second press.

## Control IPC

Daemon listens on a Unix socket at `$RUNTIME_DIR/mywhispr.sock` (mode `0600`, daemon UID only).

Protocol: one JSON line in, one JSON line out, then close.

```json
{ "cmd": "start", "trigger": "grave" }
{ "cmd": "stop" }
{ "cmd": "status" }
{ "cmd": "warm", "model": "large-q5" }
{ "cmd": "unload" }
```

Replies always include `{ "ok": bool, "state": "...", "reason": "..." }`. GNOME shortcuts target the socket — lower startup cost than HTTP and no port-bind race at daemon start.

The control socket is independent of the HTTP API. The web UI and the top-bar extension use HTTP.

## Hotkey Handling

GNOME custom shortcut calls:

```bash
mywhisprctl start grave
```

The daemon reads `/dev/input` via `python-evdev`. It does not gate `start` on having first seen the physical key-down — GNOME's `start` signal and the `evdev` release stream are independent inputs. Release is detected from `evdev`.

Keyboard grab and live language switching:

- When `start grave` is accepted and `grave.combo.enabled` is true, the daemon issues `EVIOCGRAB` on the configured keyboard devices and holds the grab until the recording ends.
- Grab is released as soon as any of these happens:
  - `grave` is released → release grab.
  - explicit stop → release grab.
  - `max_duration` fires → release grab.
  - Hard safety timeout (`input_grab.maximum_seconds`, default 5 s) → release grab, log warn.
- A combo key can arrive multiple times during the hold. Each combo press switches `current_mode` and is consumed by the daemon. The combo key never reaches the focused app.
- On mode switch, live preview and streaming-into-app discard stale hypotheses from the previous mode. If streaming has committed or crystallized text into the focused app, the daemon deletes that text immediately, resets streaming/crystallization state, and reinterprets the whole current audio in the new mode.
- The grab is held on the same FDs the daemon keeps open for evdev. Process exit closes the FDs and the kernel releases the grab.
- Grab applies only to devices matching `input_grab.device_name_patterns` and not in `exclude_device_name_patterns`. The daemon's own `ydotoold` virtual device must always be excluded.
- During grab, only release and configured combo keys have meaning to MyWhispr; the daemon does not re-inject other keys. Non-combo keys typed while dictating are dropped because the dictation trigger is being held.

Other constraints:

- Re-scan input devices on `udev` events so a reconnected keyboard does not silently stop working.
- Log every ignored `start` with reason and age since last stop.
- The daemon does not bind any global hotkey through GNOME APIs. GNOME shortcuts are the only entry path.

## Whisper Server Lifecycle

One primary `whisper-server` process for the configured primary model.

- Lazy: server starts on first transcription request, or on an explicit `warm`.
- Idle unload: disabled by default (`whisper_idle_shutdown_seconds: 0`) so the selected primary model stays resident. If set to a positive number, the server stops after that many idle seconds and drops the model from VRAM.
- Background warm at `STARTING` so the model is ready by release. Recording itself never blocks on warm.
- A `unload` command stops the server immediately. Releasing during an unload requeues a warm.

Failure handling:

- If the server exits during a transcription, mark the dictation failed, log the exit code and last 40 lines of server stderr, and restart on the next request.
- If the model file is missing or unreadable, refuse to warm and surface the error in `/api/status` and the web UI.

The whisper server itself binds `127.0.0.1` only — see Security.

The alternate transcription server (used by retranslate) follows the same pattern on a separate port. It is never started for live dictation.

## Audio Cues

Cues are part of the core UX. Reliability rules:

- Start cue is the **first** side effect of an accepted `start`. It fires before recorder spawn, before model warm, before any other work.
- Stop cue plays immediately when release is detected.
- Error cue plays on `recorder_failed`, `transcription_failed`, `paste_failed` — any failure that means nothing reached the focused app.

Implementation:

- Cue WAVs are pre-generated at daemon startup and written once to `$RUNTIME_DIR`.
- Playback is a detached `pw-play` process; the daemon does not wait for it.
- Cue playback is spawned synchronously with `subprocess.Popen` from the state handler. It must not be scheduled behind recorder/model startup work. Cue playback failure never blocks recording.

## Recording

`pw-record` with a fixed WAV format:

```text
mono, 16 kHz, signed 16-bit WAV
```

Recording files live under `/run/user/$UID/mywhispr/recordings` (tmpfs, RAM-backed).

Default lifecycle:

- Create temp WAV on start.
- Read bytes into history memory after transcription.
- Delete temp WAV after processing.

Safety:

- `max_duration` defaults to 240 s. On hit, transition to `STOPPING_NO_PASTE`.
- A watchdog checks `pw-record` liveness every 0.5 s. An unexpected exit transitions to `STOPPING_NO_PASTE`.

Debug option:

```json
{ "debug_retained_recordings": 1 }
```

## Transcription

Primary transcription:

- One configured default model.
- Click a model card in the web UI to make it the default model and warm it immediately. The selected model remains the default for future recordings until the user clicks another model.
- Warm manually, on first transcription, or in the background at `STARTING`.
- Do not switch primary model automatically during a dictation.

Whisper prompt biasing:

- Per-language prompts. The Ukrainian prompt instructs the model to prefer standard Ukrainian forms when input is code-switched with Russian.
- `custom_words` are appended to the prompt for any language. Edits take effect immediately, no daemon restart.

## Output Cleanup

Whisper output is never pasted raw. The cleanup pipeline (text → text) runs in this order:

1. **Collapse line breaks.** Replace all `\r` and `\n` with single spaces, then squash whitespace runs to a single space.
2. **Hallucination filter.** Hard-strip exact/global byline hallucinations such as `"Transcription by CastingWords"`, `"Transcription by ESO"`, and `"Translation by"` regardless of the selected language or tail RMS. Then, if the final segment's audio RMS is below `hallucination_filter.silence_rms_threshold` and the trailing text matches one of the known outro phrases, strip the match. Phrase list is editable in config without restart. Defaults:
   - `en`: `"Thank you for watching."`, `"Thanks for watching!"`, `"Transcription by CastingWords"`, `"Transcription by ESO"`, `"Translation by"`, `"I hope you enjoyed this video."`, `"Bye."`, `"Subscribe."`
   - `uk`: `"Дякую за перегляд!"`, `"Дякую."`, `"Підписуйтесь на канал."`
3. **Trim** leading/trailing whitespace.
4. **Append trailing space** if `append_trailing_space` is true (default: true).

The transcriber prepends `snapshot_leading_silence_seconds` (default 0.25 s) of silence to the WAV when sending to whisper-server. This applies to live preview snapshots, streaming snapshots, and the final transcribe, and prevents the first spoken word from being clipped at the start of the audio.

## Live Web Preview

Default: preview shows in the web UI during recording. It never types into the focused app.

```json
"live_preview": {
  "enabled": true,
  "paste_into_app": false,
  "cancel_on_release": true,
  "interval_seconds": 0.8,
  "initial_delay_seconds": 1.2
}
```

Behavior:

- Periodically transcribe a snapshot of the growing audio.
- Show preview text in the web UI and in the top-bar indicator.
- Final released transcription is authoritative; it replaces any preview text.
- On release, any in-flight preview request is cancelled or its result discarded so finalization is not queued behind it.
- Preview failure never affects the final dictation. Preview errors are surfaced in `/api/status` so the UI can show "preview stalled" instead of going silent.

If `live_preview.enabled` is false, the web UI and top-bar indicator still show recording state but no live text.

When streaming-into-app is enabled (default), it shares the same periodic-transcribe cadence; the web preview reads from the same hypothesis stream so the two surfaces never disagree.

## GNOME Top-Bar Indicator

A small GNOME Shell extension provides ambient visual feedback in the top bar.

States shown by the icon:

- `idle` — neutral icon.
- `recording` — clearly distinct icon or color (e.g., red dot).
- `transcribing` — busy/spinner.
- `error` — error glyph; sticks until the next successful dictation or until clicked.

Text shown next to the icon:

- While recording: the live preview text, truncated to the last `topbar.max_words` words (default 10).
- While idle: the last finished dictation's text, also truncated to the last `topbar.max_words` words.
- During retranslate batch: short progress string `retr N/M`.

Configuration:

```json
"topbar": {
  "enabled": true,
  "max_words": 10,
  "show_when_idle": true,
  "poll_interval_ms": 600
}
```

Implementation rules:

- The extension polls `GET /api/status` every `topbar.poll_interval_ms`. No D-Bus dependency.
- Click on the indicator opens a small popup with copy-to-clipboard of the last transcript, a `Stop recording` button when recording, and a `Open web UI` link. The popup never grabs keyboard focus from the active app. Closing it returns focus to whatever was focused before.
- The indicator never types or pastes. It is read-only with respect to the focused app.
- If the daemon's HTTP port is unreachable, the icon shows a dimmed neutral state; it never throws JS errors that destabilize `gnome-shell`.

The extension lives under `extensions/mywhispr@local/` in the repo and is installed into `~/.local/share/gnome-shell/extensions/mywhispr@local/` by the install script. GNOME Shell under Wayland picks it up on next login.

## Streaming Into Focused App

Periodic transcription of the growing recording, with backspace + paste rewrites pushed into the focused app as the hypothesis stabilizes. **On by default** (`streaming.app_output_enabled = true`). Disable with `streaming.app_output_enabled = false`; the basic loop then degrades cleanly to record-release-paste.

Mandatory safety mitigations whenever enabled:

- **Stable lag**: commit only text older than `streaming.stable_lag_seconds`.
- **Initial commit confirmation**: the first hypothesis must repeat `streaming.initial_commit_confirmations` times before any text is sent.
- **Backspace confirmation**: a destructive rewrite (overwriting already-inserted text) must repeat `streaming.rewrite_backspace_confirmations` times before any backspace is sent.
- **Pause gate**: commit only when a relative audio-energy dip is detected (`streaming.pause_gate_*`).
- **Audio-energy gate**: skip snapshots whose new audio is below `streaming.new_audio_gate_min_rms`.
- **Crystallization**: after `streaming.crystallization_required_updates` matching updates on a segment older than `streaming.crystallization_lag_seconds`, that prefix is frozen inside one mode. A mode switch deletes the committed frozen text from the app and clears crystallization state; it never preserves old-mode text.
- **Cancel on release**: any in-flight streaming snapshot is cancelled when the user releases.
- **Final rewrite safety**: when the final transcript diverges too far from already-inserted streaming text, the daemon does not attempt a large destructive rewrite. It copies the final transcript to the clipboard, records `pasted=false`, fires the error cue. No multi-hundred-character backspace burst can reach the focused app.
- **Max rewrite cap**: `streaming.max_rewrite_chars` (default 180) hard-caps any single destructive rewrite.

The entire feature lives in `streaming.py`. Integration rule: with `streaming.app_output_enabled = false`, the streaming module is dormant — no extra whisper requests, no backspaces, no clipboard writes during recording — and the basic loop behaves identically to a build without streaming code. This is verified by an automated test.

## Pasting

Final output (release path):

- Short printable ASCII output is typed directly through the synthetic-input backend with zero inter-key delay by default, avoiding focused-app paste filters.
- Longer or non-ASCII output is pasted through the active output backend; on Wayland that uses `wl-copy --paste-once`.
- Send paste chords via `ydotool`: first `Ctrl+Shift+V`, then `Shift+Insert` if the clipboard offer was not consumed.
- Wait briefly for the clipboard offer to settle before sending the paste chord.
- Mark paste successful only after `wl-copy --paste-once` exits, which means a focused widget consumed the clipboard offer.
- If no paste chord consumes the clipboard, leave final text on the clipboard, fire the error cue, record `pasted=false` in history.
- OS-specific output stays behind `paste.OutputBackend`: Linux uses `ydotool`/`wl-copy`; Windows maps the same type, paste, copy, and backspace operations to `SendInput` and the Win32 clipboard.

Live destructive backspaces run only when `streaming.app_output_enabled` is true.

## In-Memory History

Default:

- Last 20 dictations.
- Text, metadata, and WAV bytes stored in process memory.
- No history JSONL or audio backlog written to disk by default.
- History disappears on daemon restart.

Memory budget (worst case): `20 × 240 s × 32 KB/s ≈ 150 MB` of audio + negligible text. Typical 5–10 s dictations stay well under 10 MB. If `history_limit` or `maximum_recording_seconds` is raised, the ceiling scales linearly; the daemon logs the chosen ceiling at startup.

History item:

```json
{
  "id": "uuid",
  "created_at": "2026-05-26T13:00:00",
  "language": "uk",
  "trigger": "grave",
  "duration_seconds": 3.2,
  "text": "Final transcript ",
  "pasted": true,
  "audio_bytes": "<memory only>",
  "alternate": {
    "model": "large",
    "status": "missing|queued|running|done|error",
    "text": "",
    "error": ""
  }
}
```

## Manual Retranslate

On-demand batch retranscription of retained audio using an alternate model.

- Web UI has a `Retranslate` button in the history panel.
- Clicking retranscribes the retained in-memory audio for up to the last 20 dictations using the configured alternate model.
- Results appear side-by-side under each original transcript as preview text.
- It does not paste anything.
- It does not alter the original transcript.
- It does not run automatically.

Model behavior:

- Start the alternate model server **once** for the batch.
- Process all selected history items through that one server.
- Stop the alternate server after the batch (or on cancel).
- If primary equals alternate, reuse the primary server when safe. Otherwise return a clear "alternate equals primary" status without starting a duplicate.

Batch states:

```text
idle -> loading-model -> running item N/M -> stopping-model -> done
```

API:

```http
POST /api/history/retranslate
```

Request:

```json
{ "model": "large", "limit": 20, "missing_only": true }
```

Response:

```json
{ "ok": true, "state": "queued", "model": "large", "count": 12 }
```

Status surfaced through `/api/status`:

```json
{
  "retranslate": {
    "active": true,
    "model": "large",
    "done": 4,
    "total": 12,
    "stage": "running"
  }
}
```

## Web UI

Local, plain, functional. Bound to `127.0.0.1:16666`. Port 16666 is used because mainstream browsers block 6666 as unsafe.

Panels:

- **Status**: state (idle / recording / transcribing / pasting), current model and loaded/unloaded, live preview health, retranslate progress, daemon PID + uptime + PID-file match.
- **Live transcript**: visible only while recording. Cleared between dictations. Replaced by the final transcript on release.
- **History**: last 20 RAM-only dictations with text, language label, trigger, duration, paste status, audio playback, copy button, and optional alternate-model transcript.
- **Retranslate**: button + progress display.
- **Models**: installed/missing status per configured model, file path and size, active/default labels. Clicking a model card switches the default model and warms it immediately behind the scenes.
- **Shortcuts**: create/edit/delete any number of named shortcuts. Capture trigger and combo keys by pressing them; show numeric keycode as captured detail, not as the primary control.
- **Advanced modes/scripts**: language modes and script modes. Script modes receive final transcript through stdin/JSON and do not paste into the focused app.
- **Settings**: only the controls wired to working endpoints. Cooldown, append-trailing-space, streaming-into-app toggle, hallucination filter on/off, custom words editor, live preview on/off, top-bar indicator on/off.

DOM rules:

- History panel is keyed by item id. Unchanged rows are not touched on poll. `<audio>` nodes are never replaced while their item is unchanged.
- Polling: `/api/status` only, every 500–1000 ms.
- Active audio playback must never be interrupted by polling.

Settings rules:

- Every visible control maps 1:1 to an API endpoint that writes config atomically and reloads the relevant subsystem in the daemon.
- A setting that is not yet wired is not rendered. No decorative inputs.
- Settings reads come from `/api/config` so the UI cannot drift from the daemon's actual config.

## HTTP API

Bound to `127.0.0.1` only. No auth (loopback-only, single-user threat model).

```text
GET    /                         Web UI
GET    /api/status               Full status snapshot
GET    /api/history              List last N history items (text+metadata, no audio)
GET    /api/history/{id}/audio   Raw WAV for one item (in-memory only)
POST   /api/history/retranslate  Start batch retranslate
POST   /api/history/clear        Drop in-memory history
POST   /api/model/warm           Body: { "model": "large-q5" }
POST   /api/model/unload         Stop primary whisper server
POST   /api/recording/stop       Force stop while RECORDING
GET    /api/config               Read current config (redacted)
POST   /api/config/{key}         Update one setting; atomic write to config.json, in-memory reload
POST   /api/config/custom_words  Update custom words list
```

Polling clients use `/api/status` only. Action endpoints are explicit `POST`s and never wedge if the daemon is in a non-idle state — they queue or return the current state clearly.

## Configuration

```json
{
  "runtime_dir": "/run/user/1000/mywhispr",
  "socket_path": "/run/user/1000/mywhispr.sock",
  "default_model": "large-q5",
  "models": {
    "large-q5": "./models/ggml-large-v3-q5_0.bin",
    "parakeet-tdt-0.6b-v3": {"backend": "transformers_tdt", "repo_id": "nvidia/parakeet-tdt-0.6b-v3"},
    "turbo": "./models/ggml-large-v3-turbo.bin",
    "large": "./models/ggml-large-v3.bin",
    "small": "./models/ggml-small.bin"
  },
  "whisper_server_binary": "/path/to/whisper-server",
  "whisper_host": "127.0.0.1",
  "whisper_port": 18178,
  "whisper_idle_shutdown_seconds": 0,
  "alternate_whisper_port": 18179,
  "web": { "host": "127.0.0.1", "port": 16666 },
  "history_limit": 20,
  "maximum_recording_seconds": 240,
  "start_cooldown_seconds": 0.2,
  "append_trailing_space": true,
  "snapshot_leading_silence_seconds": 0.25,
  "live_preview": {
    "enabled": true,
    "paste_into_app": false,
    "cancel_on_release": true,
    "interval_seconds": 0.8,
    "initial_delay_seconds": 1.2
  },
  "topbar": {
    "enabled": true,
    "max_words": 10,
    "show_when_idle": true,
    "poll_interval_ms": 600
  },
  "streaming": {
    "app_output_enabled": true,
    "interval_seconds": 0.8,
    "stable_lag_seconds": 0.65,
    "max_rewrite_chars": 180,
    "rewrite_backspace_confirmations": 2,
    "initial_commit_confirmations": 2,
    "crystallization_enabled": true,
    "crystallization_lag_seconds": 24,
    "crystallization_required_updates": 2,
    "cancel_streaming_on_release": true
  },
  "hallucination_filter": {
    "enabled": true,
    "silence_rms_threshold": 90,
    "phrases": {
      "en": ["Thank you for watching.", "Thanks for watching!", "I hope you enjoyed this video."],
      "uk": ["Дякую за перегляд!", "Дякую.", "Підписуйтесь на канал."]
    }
  },
  "triggers": {
    "grave": {
      "language": "uk",
      "stop_on_release_codes": [41],
      "combo": {
        "enabled": true,
        "deadline_seconds": 1.2,
        "keys": [{ "code": 2, "switch_language": "en" }]
      }
    }
  },
  "input_grab": {
    "maximum_seconds": 5,
    "device_name_patterns": ["Logitech MX Keys", "Logitech ERGO K860"],
    "exclude_device_name_patterns": ["ydotoold virtual device"]
  },
  "audio_cues": { "enabled": true },
  "custom_words": []
}
```

Validation:

- Validated at startup. Unknown keys warn, not fatal. Missing required keys (`whisper_server_binary`, `models.{default_model}`) are fatal.
- `web.host` and `whisper_host` are validated as loopback (`127.0.0.1`, `::1`, or `localhost`). Anything else: daemon refuses to start with a clear error. See Security.
- Active config logged at startup with secrets redacted.
- Live mutations write back atomically: temp file then `os.replace`.
- Invalid config on reload keeps prior in-memory config and surfaces the error in `/api/status`.

## Failure Modes & Recovery

The basic loop must survive each of these without operator intervention:

- `pw-record` exits mid-recording → `STOPPING_NO_PASTE`, error cue, history records `pasted=false`, `failed_reason=recorder_exited`.
- `whisper-server` exits during transcription → mark dictation failed, restart server on next request, no paste.
- `whisper-server` won't start (missing binary/model, port collision) → surface in `/api/status`, refuse warm, dictation fails gracefully with error cue.
- `wl-copy` or `ydotool` missing, or `ydotoold` unreachable → final text stays on clipboard, `pasted=false`, error cue.
- `/dev/input` device disappears (USB keyboard unplugged) → log, continue with remaining devices; on reconnect, re-add via `udev` watch.
- Config file invalid on reload → keep prior in-memory config, surface error in `/api/status`.
- Disk full in `runtime_dir` → recording fails fast; do not silently keep partial WAVs.
- Keyboard-grab failure → release any partial grab, log, fall back to no-combo behavior for that dictation.
- Top-bar extension cannot reach HTTP API → dimmed neutral icon, no JS errors thrown into `gnome-shell`.

Every failure path emits a structured log line with state, trigger, and reason.

## Security

Threat model: one user on one workstation. The daemon handles audio (sensitive content) and synthesizes keystrokes via `ydotool` (privileged capability). Treat the daemon, its sockets, and its config as sensitive assets.

### Network exposure

- **HTTP listener binds `127.0.0.1` only.** The `web.host` config defaults to `127.0.0.1` and is validated at startup to be a loopback address (`127.0.0.1`, `::1`, or `localhost`). Any non-loopback value causes the daemon to refuse to start with an explicit error. Never `0.0.0.0`. Never a LAN IP.
- **Whisper server bound to `127.0.0.1` too.** `whisper_host` and `alternate_whisper_port` follow the same loopback rule. Same enforcement.
- **Loopback is the only auth boundary.** No HTTP auth, by design, because the port is loopback-only and the threat model is one user on one machine. Off-loopback binding would need its own auth design (mutual TLS, token, or similar) and is not in scope.
- **Remote access option (advisory).** To view the web UI from another machine, use SSH port forwarding (`ssh -L 16666:127.0.0.1:16666 user@host`). Do not change the bind address to expose the port directly.
- **No outbound network traffic at runtime.** The daemon does not phone home, does not download models (model files are local paths in config), does not send telemetry, does not contact cloud transcription APIs. Anything making an outbound connection in the daemon is a bug. The install script may fetch a model on first install if asked, but the daemon does not.

### Local privileges

- **Daemon runs as the user, not root.** The user systemd service is the only supported launch path. The unit file does not include any privilege escalation.
- **Control socket** at `$RUNTIME_DIR/mywhispr.sock` is `0600` (owner-only). `$RUNTIME_DIR` is `0700`.
- **`ydotool` / `ydotoold`** is the privileged piece, with `/dev/uinput` access. The daemon trusts the `ydotoold` socket; abuse of that socket lets any process synthesize keystrokes system-wide. Its socket path is set via `$YDOTOOL_SOCKET` in the systemd unit and inherits whatever permissions the `ydotool` package configured. The install script verifies the socket exists and is owner-restricted.
- **`/dev/input/event*`** access is read-only outside the combo window. `EVIOCGRAB` is opt-in per-trigger, time-bounded by `combo.deadline_seconds` and `input_grab.maximum_seconds`, and released at process exit at the kernel level (FD close).
- **No `exec` from config.** Paths to external binaries (`whisper_server_binary`, `pw-record`, `pw-play`, `wl-copy`, `ydotool`) are validated at startup as existing and executable. `record_command` is an `argv` array, not a shell line — the daemon never invokes a shell.

### Data at rest and in motion

- **Audio is RAM-only by default.** History WAV bytes live in process memory; nothing voice-related touches non-tmpfs disk on the default path. Daemon restart drops the history.
- **Temp recording WAVs** live under `/run/user/$UID/mywhispr/recordings`, which is tmpfs (RAM-backed). Files are deleted after transcription. They never reach a persistent filesystem.
- **Transcripts are RAM-only by default.** Persistent history is opt-in and unimplemented in M1–M2.
- **Custom words and config** live in `config.json` under the user's home directory, under standard user file permissions. They are not encrypted; treat them as user-confidential.
- **Clipboard**: short printable ASCII output bypasses the clipboard and is typed through the synthetic-input backend. Longer or non-ASCII output is copied through the current output backend; on Wayland this uses `wl-copy --paste-once` so a single paste consumer clears it. On paste failure the text remains on the clipboard until the user copies something else — by design, so the dictation isn't lost.

### Audit

- The daemon logs to the user journal (`journalctl --user -u mywhisprd`). State transitions, paste outcomes, model errors, and grab events are logged.
- Logs do not include transcript text by default to avoid storing sensitive dictation content in the journal. An opt-in `debug.log_transcripts` flag exists for development; it is off by default and the web UI never enables it from a normal control.
- Errors are explicit. The daemon does not swallow exceptions silently; every failure has a logged reason and, where user-visible, a state transition or `/api/status` field.

## Setup & Installation

The install script performs each step; do not piecemeal them by hand.

1. **System packages.** Verify `pipewire-bin`, `wl-clipboard`, `ydotool`, `python3-evdev`, `python3-pyudev`, `python3-aiohttp` are present. Print the exact `apt` command for any missing.
2. **ydotool daemon.** Verify `ydotoold` is running as a user service and the user is in the `input` group. If not, print instructions; do not silently `usermod`.
3. **Models.** Verify configured GGML model files exist and are readable.
4. **Whisper server binary.** Verify it exists and is executable; run `ldd` against the CUDA build and refuse install if any `not found` lines appear.
5. **Runtime directory.** Create `/run/user/$UID/mywhispr` with mode `0700`.
6. **Loopback validation.** Confirm `web.host` and `whisper_host` are loopback; refuse install otherwise.
7. **Daemon binary.** Install `mywhisprd` and `mywhisprctl` to `/usr/local/bin/` (root step; the install script asks for `pkexec` only here).
8. **systemd user service.** Install `~/.config/systemd/user/mywhisprd.service`, `daemon-reload`, `enable --now`.
9. **GNOME shortcut.** Append a custom keybinding at `org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/mywhispr-grave/`:
   - `name = "MyWhispr grave"`
   - `command = "/usr/local/bin/mywhisprctl start grave"`
   - `binding = "grave"`

   The script reads the current `custom-keybindings` list, appends this path only if absent, and writes back. Existing user shortcuts survive.

10. **GNOME top-bar extension.** Copy `extensions/mywhispr@local/` to `~/.local/share/gnome-shell/extensions/mywhispr@local/`. Run `gnome-extensions enable mywhispr@local`. Under Wayland the extension is picked up on next login; the script prints that instruction.
11. **Smoke test.** Run `mywhisprctl status`. Expect `IDLE`. Press `grave` for a one-second test; verify start/stop cues and a final paste into `xterm` or `gedit`.

If another dictation daemon or shortcut is bound to `grave`, the install script detects it, refuses to overwrite, and prints the conflict — the user resolves it manually.

Uninstall reverses each step; the GNOME shortcut entry is removed from the keybindings list rather than blanking the list.

## Implementation Notes

Reference-level patterns for the trickier parts. The actual code may diverge but should preserve these contracts.

### State machine in code

```python
class State(enum.Enum):
    IDLE = "IDLE"; STARTING = "STARTING"; RECORDING = "RECORDING"
    STOPPING = "STOPPING"; STOPPING_NO_PASTE = "STOPPING_NO_PASTE"
    TRANSCRIBING = "TRANSCRIBING"; TRANSCRIBING_NO_PASTE = "TRANSCRIBING_NO_PASTE"
    PASTING = "PASTING"

class Event(enum.Enum):
    START = "start"; STOP = "stop"
    RECORDER_READY = "recorder_ready"; RECORDER_FAILED = "recorder_failed"
    RELEASE = "release"; COMBO = "combo"
    MAX_DURATION = "max_duration"; RECORDER_EXITED = "recorder_exited"
    RECORDER_STOPPED = "recorder_stopped"
    TRANSCRIPT_READY = "transcript_ready"; NO_TEXT = "no_text"; FAILED = "failed"
    PASTE_DONE = "paste_done"
```

Dispatch table keyed by `(State, Event)`; missing pairs log and ignore (never raise) so stray events during shutdown don't crash the daemon:

```python
TRANSITIONS: dict[tuple[State, Event], Callable] = {
    (State.IDLE, Event.START): handle_start_from_idle,
    (State.STARTING, Event.RECORDER_READY): handle_recorder_ready,
    # ...
}

def dispatch(self, event: Event, **payload):
    handler = TRANSITIONS.get((self.state, event))
    if handler is None:
        self.log.info("ignored event=%s state=%s payload=%s", event, self.state, payload)
        return
    new_state, effects = handler(self, **payload)
    self.log.info("state %s -> %s on %s age_ms=%d", self.state, new_state, event,
                  int((time.monotonic() - self.last_transition_ts) * 1000))
    self.state = new_state
    self.last_transition_ts = time.monotonic()
    for ef in effects: self.schedule(ef)
```

At module load, every state's reachable events must be present in `TRANSITIONS` or explicitly listed as ignored. A self-check at startup raises if a known transition is missing — typos surface at startup, not at user action time.

### evdev event loop

`python-evdev` exposes `async_read_loop()` per device. Watch each in its own task. Hot-plug via `pyudev`:

```python
async def watch_device(dev: evdev.InputDevice, on_key):
    try:
        async for ev in dev.async_read_loop():
            if ev.type == evdev.ecodes.EV_KEY:
                on_key(ev.code, ev.value)  # 1=down, 0=up, 2=repeat
    except OSError:
        return  # device disconnected; supervisor re-adds on udev event

async def supervise_devices(on_key):
    tasks: dict[str, asyncio.Task] = {}
    def add(path):
        if path in tasks: return
        dev = evdev.InputDevice(path)
        tasks[path] = asyncio.create_task(watch_device(dev, on_key))
    def remove(path):
        t = tasks.pop(path, None)
        if t: t.cancel()
    monitor = pyudev.Monitor.from_netlink(pyudev.Context())
    monitor.filter_by("input")
    for dev in list_keyboards(): add(dev.path)
    async for action, path in udev_aiter(monitor):
        if action == "add": add(path)
        elif action == "remove": remove(path)
```

Only `value == 0` triggers `release` in the state machine. `value == 2` (auto-repeat) is ignored outside the combo window.

### EVIOCGRAB semantics

`evdev.InputDevice.grab()` calls `EVIOCGRAB`. While grabbed, the kernel routes that device's events only to the grabbing FD — the compositor sees nothing from it. Consequences:

- A grabbed keyboard's other (non-combo) keys are silently dropped during the bounded grab window. Keep the window short.
- Grabbing only affects the devices passed through. Other keyboards still feed the compositor normally. Multi-keyboard users list which devices to grab in `input_grab.device_name_patterns`.
- Release: `dev.ungrab()`. Process exit closes the FD; the kernel auto-ungrabs.

### pw-record shutdown

SIGINT to flush WAV header; never SIGKILL (corrupts header).

```python
proc.send_signal(signal.SIGINT)
try:
    await asyncio.wait_for(proc.wait(), timeout=1.0)
except asyncio.TimeoutError:
    proc.terminate()
    await proc.wait()
```

### Whisper server protocol

`whisper.cpp` server's HTTP endpoint (verify against the binary in use):

```
POST /inference
Content-Type: multipart/form-data
  file:            WAV bytes
  language:        "uk" | "en" | "auto"
  prompt:          custom_words + language-specific prompt
  temperature:     "0.0"
  response_format: "verbose_json"
```

Response: `{ "text": "...", "segments": [{"start": 0.12, "end": 1.34, "text": "..."}, ...] }`. Segment timestamps drive streaming's `stable_lag` and crystallization.

Readiness check: the server prints `whisper-server is listening on...` to stderr. The supervisor reads stderr line-by-line and considers the server ready when that line appears; `warm` resolves on it.

Cancelling an in-flight request: hold the `aiohttp` (or `httpx`) task; on release, `task.cancel()`. The server gets connection-close and aborts. Cancellation is fire-and-forget.

### Snapshot leading silence

Prepend silence bytes to the WAV data section, patch the header sizes:

```python
SILENCE_BYTES = bytes(int(16000 * 0.25) * 2)  # 0.25s @ 16kHz int16 mono

def with_leading_silence(wav: bytes) -> bytes:
    header = bytearray(wav[:44])
    data = wav[44:]
    new_data = SILENCE_BYTES + data
    struct.pack_into("<I", header, 4, 36 + len(new_data))   # RIFF size
    struct.pack_into("<I", header, 40, len(new_data))       # data subchunk size
    return bytes(header) + new_data
```

### Audio RMS without numpy

```python
import array, math
def rms_int16(buf: bytes) -> float:
    samples = array.array('h'); samples.frombytes(buf)
    if not samples: return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))
```

Used by the hallucination filter (final segment RMS), pause gate (rolling window RMS), and audio-energy gate (new audio RMS).

### Atomic config write

```python
def atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    os.replace(tmp, path)
```

`os.replace` is atomic within the same filesystem on Linux. `config.json` and its `.tmp` are always in the same directory.

### Paste sequence

```python
async def paste(text: str) -> bool:
    proc = await asyncio.create_subprocess_exec(
        "wl-copy", "--paste-once", stdin=asyncio.subprocess.PIPE,
    )
    await proc.communicate(text.encode("utf-8"))
    await asyncio.sleep(0.03)  # let wl-copy register
    keycodes = ["29:1", "42:1", "47:1", "47:0", "42:0", "29:0"]  # Ctrl+Shift+V
    rc = await asyncio.create_subprocess_exec("ydotool", "key", *keycodes)
    await rc.wait()
    return await wait_paste_consumed(timeout=0.8)
```

`YDOTOOL_SOCKET` must be in the daemon's environment (set in the systemd unit) so `ydotool` finds the daemon socket.

### Keyed DOM rendering (vanilla JS)

```javascript
function renderHistory(items) {
  const list = document.getElementById('history');
  const existing = new Map([...list.children].map(n => [n.dataset.id, n]));
  const wanted = new Set(items.map(i => i.id));
  for (const [id, node] of existing) if (!wanted.has(id)) node.remove();
  let cursor = null;
  for (const item of items) {
    let node = existing.get(item.id);
    if (!node) {
      node = createRow(item);
      list.insertBefore(node, cursor ? cursor.nextSibling : list.firstChild);
    } else {
      updateRowIfChanged(node, item);
    }
    cursor = node;
  }
}

function updateRowIfChanged(node, item) {
  const audio = node.querySelector('audio');
  if (audio && !audio.paused) return;  // never touch a row whose audio is playing
  const ver = item.text + '|' + item.pasted + '|' + (item.alternate?.text || '');
  if (node.dataset.ver === ver) return;
  node.querySelector('.text').textContent = item.text;
  node.querySelector('.alternate').textContent = item.alternate?.text || '';
  node.dataset.ver = ver;
}
```

### GNOME shortcut install via gsettings

```bash
SCHEMA=org.gnome.settings-daemon.plugins.media-keys
KB_SCHEMA=$SCHEMA.custom-keybinding
PATH_PREFIX=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings
OUR=$PATH_PREFIX/mywhispr-grave/

current=$(gsettings get "$SCHEMA" custom-keybindings)
case "$current" in
  *"$OUR"*) ;;                                              # already present
  "@as []") gsettings set "$SCHEMA" custom-keybindings "['$OUR']" ;;
  *)        gsettings set "$SCHEMA" custom-keybindings "${current%]*}, '$OUR']" ;;
esac
gsettings set "$KB_SCHEMA:$OUR" name    "MyWhispr grave"
gsettings set "$KB_SCHEMA:$OUR" command "/usr/local/bin/mywhisprctl start grave"
gsettings set "$KB_SCHEMA:$OUR" binding "grave"
```

Uninstall removes the path entry from the array (string-edit) and `gsettings reset` on the three keys.

### systemd user unit

`~/.config/systemd/user/mywhisprd.service`:

```ini
[Unit]
Description=MyWhispr dictation daemon
After=graphical-session.target pipewire.service ydotool.service
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/local/bin/mywhisprd
Restart=on-failure
RestartSec=2
Environment=YDOTOOL_SOCKET=/run/user/%U/.ydotool_socket
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

`Restart=on-failure` recovers from crashes; the daemon is stateless across restarts by design (history is RAM-only and discarded).

### GNOME Shell extension skeleton

`extensions/mywhispr@local/metadata.json`:

```json
{
  "uuid": "mywhispr@local",
  "name": "MyWhispr",
  "description": "Top-bar indicator for MyWhispr dictation daemon",
  "shell-version": ["45", "46", "47", "48"],
  "url": "local"
}
```

`extension.js` outline (GNOME Shell 45+ ES modules):

```javascript
import GObject from 'gi://GObject';
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import Soup from 'gi://Soup';
import GLib from 'gi://GLib';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const Indicator = GObject.registerClass(class extends PanelMenu.Button {
  _init() {
    super._init(0.0, 'MyWhispr', false);
    this._icon  = new St.Icon({icon_name: 'audio-input-microphone-symbolic',
                               style_class: 'system-status-icon'});
    this._label = new St.Label({y_align: Clutter.ActorAlign.CENTER, text: ''});
    const box = new St.BoxLayout();
    box.add_child(this._icon); box.add_child(this._label);
    this.add_child(box);
    this._session = new Soup.Session();
    this._tick();
  }
  _tick() {
    const msg = Soup.Message.new('GET', 'http://127.0.0.1:16666/api/status');
    this._session.send_and_read_async(msg, GLib.PRIORITY_DEFAULT, null, (s, res) => {
      try {
        const bytes = s.send_and_read_finish(res);
        this._apply(JSON.parse(new TextDecoder().decode(bytes.get_data())));
      } catch (_) { this._dim(); }
      this._timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 600,
        () => { this._tick(); return GLib.SOURCE_REMOVE; });
    });
  }
  _apply(status) { /* set icon class by status.state; truncate label to 10 words */ }
  _dim()         { this._label.text = ''; this._icon.opacity = 100; }
  destroy()      { if (this._timer) GLib.source_remove(this._timer); super.destroy(); }
});

export default class extends Extension {
  enable()  { this._ind = new Indicator(); Main.panel.addToStatusArea('mywhispr', this._ind); }
  disable() { this._ind?.destroy(); this._ind = null; }
}
```

Click-popup is a `PopupMenu` populated in `_init` with Stop / Copy-last / Open-web-UI items. `PanelMenu.Button` does not steal focus from the previously focused app when its menu opens.

### Logging & journal

Python `logging` at INFO. Single-line structured entries:

```text
state IDLE->STARTING trigger=grave age_ms=12 reason=cmd-start
paste ok=false reason=ydotool_exit_5
whisper inference ms=420 lang=uk segments=3 chars=87
grab acquired devices=2 reason=combo_window deadline_s=1.2
```

Transcript text is not logged unless `debug.log_transcripts` is true (off by default).

The systemd user service routes stdout/stderr to the user journal:

```bash
journalctl --user -u mywhisprd -n 200 --no-pager
```

## Testing

Core tests (must pass before any optional feature is enabled):

- Start from idle creates exactly one recorder.
- Release stops exactly that recorder.
- Immediate GNOME repeat starts inside cooldown are ignored with `ignored-repeat`.
- New start after cooldown works.
- Start while recording returns already-recording.
- `stop` while idle is a no-op and returns `ok: true`.
- Start cue fires before recorder spawn; record path runs even if cue fails.
- Missing release eventually hits max-duration, saves history, does not paste.
- Recorder unexpected exit transitions to `STOPPING_NO_PASTE` and does not paste.
- `grave + 1` combo grabs keyboard, switches language, releases grab; `1` does not reach the focused app; grab is released within 5 s in the worst case.
- Whisper server crash during transcribe marks the item failed; the server restarts on the next request.
- Whisper idle shutdown fires after the configured timeout; the next dictation re-warms.
- Output cleanup collapses `\n` to spaces and squashes runs of whitespace.
- Hallucination filter strips outro phrases on quiet endings, leaves them alone on loud endings.
- Leading silence pad: a clip whose first 0.1 s contains the word "test" transcribes "test" with the pad enabled.
- Live preview cancel-on-release: a snapshot in flight is discarded; final transcribe runs unblocked.
- Live preview failure does not affect final transcription.
- History keeps only last 20 in memory.
- Audio endpoint returns the correct bytes for retained items.
- UI history render does not replace unchanged audio elements (headless Chromium check).
- Manual retranslate starts the alternate model once per batch.
- Manual retranslate never runs after normal dictation unless requested.
- Settings endpoint write is reflected in `/api/config` and in observed daemon behavior.
- Config reload with invalid JSON keeps prior config.
- With `streaming.app_output_enabled = false`, the streaming module is dormant: no extra whisper requests, no backspaces, no clipboard writes during recording.
- Top-bar extension polls `/api/status` and changes icon state on a synthetic state-transition broadcast.
- Top-bar extension survives daemon-down: icon dims, no JS errors in `journalctl --user -u org.gnome.Shell`.

Security tests:

- `web.host` set to `0.0.0.0` causes the daemon to refuse to start with a clear error and exit non-zero.
- `whisper_host` set to a LAN IP causes the daemon to refuse to start.
- Control socket has mode `0600`; the daemon refuses to start if it cannot create it that way.
- Outbound connect attempt during a full record/transcribe/paste cycle: none observed (verified with `ss -tnp` or a sandboxed network namespace).
- `debug.log_transcripts` off: no transcript text in the journal across a full cycle.

Manual acceptance tests:

- Press `grave`, hear start cue, release, hear stop cue, final text appears in the focused app, no spurious newlines.
- Stop and immediately start again after ~200 ms; second recording starts cleanly.
- Hold `grave`, tap `1`, finish dictation: final transcript is English; `1` is not in the focused app.
- Play a history audio item while the UI is polling; playback continues uninterrupted.
- Click `Retranslate`; alternate text appears under retained items.
- Kill `whisper-server` by hand mid-record; hear error cue on release; next dictation succeeds.
- Unplug and replug the keyboard mid-session; next dictation succeeds.
- Watch the top-bar icon change to "recording" state on press and back to "idle" on release. Live preview text appears next to the icon, truncated to 10 words.
- Click the top-bar icon: popup opens without taking focus from the previously focused app; closing it returns focus to that app.
- Browse to `http://127.0.0.1:16666/` from this workstation: UI loads. Browse to `http://<LAN-IP>:16666/` from another machine: connection refused.

## Milestones

**M1 — Full default behavior**

- Hold `grave` to record Ukrainian; release to paste cleaned final transcript.
- `grave + 1` combo switches the current recording to English without leaking `1`.
- Streaming-into-app on by default with all safety mitigations.
- Start, stop, error cues; start cue is the first side effect of `start`.
- Output cleanup (newlines, hallucinations, leading silence pad).
- Local web UI: status, last 20 RAM-only dictations with audio playback, copy buttons. Live transcript panel updates while recording.
- Settings panel: only wired controls.
- All listeners loopback-only and validated.

**M2 — Polish layers**

- GNOME top-bar indicator: icon for state and last 10 transcribed words; click-popup that does not steal focus.
- Manual batch retranslate against an alternate model.
- Custom words editor.

**M3 — Future**

- Persistent history (SQLite or RAM-disk JSONL) behind explicit opt-in.
- Per-app paste profiles (terminal vs. GUI paste chord).
- Multiple primary models warm at once, with per-trigger model selection.
- Voice command channel: leading control phrases parsed out of the transcript before pasting.

## Possible Future Directions

- Multi-display top-bar awareness if the desktop spans monitors with separate top bars.
- Optional D-Bus interface for other apps to subscribe to recording state (read-only).
- Local LLM cleanup pass between Whisper output and paste (capitalization, punctuation, custom-vocabulary fixes).
