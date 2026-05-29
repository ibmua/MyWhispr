from __future__ import annotations

import enum


class State(enum.Enum):
    IDLE = "IDLE"
    STARTING = "STARTING"
    RECORDING = "RECORDING"
    STOPPING = "STOPPING"
    STOPPING_NO_PASTE = "STOPPING_NO_PASTE"
    TRANSCRIBING = "TRANSCRIBING"
    TRANSCRIBING_NO_PASTE = "TRANSCRIBING_NO_PASTE"
    PASTING = "PASTING"


class Event(enum.Enum):
    START = "start"
    STOP = "stop"
    RECORDER_READY = "recorder_ready"
    RECORDER_FAILED = "recorder_failed"
    RELEASE = "release"
    COMBO = "combo"
    NOSTREAM = "nostream"
    MAX_DURATION = "max_duration"
    RECORDER_EXITED_ERROR = "recorder_exited_error"
    RECORDER_STOPPED = "recorder_stopped"
    TRANSCRIPT_READY = "transcript_ready"
    TRANSCRIPT_FAILED = "transcript_failed"
    NO_TEXT = "no_text"
    PASTE_DONE = "paste_done"
    PASTE_FAILED = "paste_failed"


# Events that may be received but are explicitly ignored in some states; declared
# so the startup self-check doesn't raise.
IGNORED_BY_DESIGN: set[tuple[State, Event]] = {
    (State.IDLE, Event.STOP),
    (State.IDLE, Event.RELEASE),
    (State.IDLE, Event.COMBO),
    (State.IDLE, Event.NOSTREAM),
    (State.STARTING, Event.COMBO),
    (State.STOPPING, Event.RELEASE),
    (State.STOPPING, Event.COMBO),
    (State.STOPPING, Event.NOSTREAM),
    (State.STOPPING_NO_PASTE, Event.RELEASE),
    (State.STOPPING_NO_PASTE, Event.COMBO),
    (State.STOPPING_NO_PASTE, Event.NOSTREAM),
    (State.TRANSCRIBING, Event.RELEASE),
    (State.TRANSCRIBING, Event.COMBO),
    (State.TRANSCRIBING, Event.NOSTREAM),
    (State.TRANSCRIBING, Event.START),
    (State.TRANSCRIBING_NO_PASTE, Event.RELEASE),
    (State.TRANSCRIBING_NO_PASTE, Event.COMBO),
    (State.TRANSCRIBING_NO_PASTE, Event.NOSTREAM),
    (State.TRANSCRIBING_NO_PASTE, Event.START),
    (State.PASTING, Event.RELEASE),
    (State.PASTING, Event.COMBO),
    (State.PASTING, Event.NOSTREAM),
    (State.PASTING, Event.START),
    (State.RECORDING, Event.START),
}
