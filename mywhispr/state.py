from __future__ import annotations

import enum


class State(enum.Enum):
    IDLE = "IDLE"
    STARTING = "STARTING"
    RECORDING = "RECORDING"
    STOPPING = "STOPPING"
    STOPPING_NO_PASTE = "STOPPING_NO_PASTE"
    # TRANSCRIBING/PASTING are no longer FSM states: finished recordings are
    # queued and processed in the background so a new recording can start
    # immediately. They remain here as display states for the UI/tray.
    TRANSCRIBING = "TRANSCRIBING"
    PASTING = "PASTING"


class Event(enum.Enum):
    START = "start"
    STOP = "stop"
    RECORDER_READY = "recorder_ready"
    RECORDER_FAILED = "recorder_failed"
    RELEASE = "release"
    COMBO = "combo"
    NOSTREAM = "nostream"
    LOWERCASE_INITIAL = "lowercase_initial"
    MAX_DURATION = "max_duration"
    RECORDER_EXITED_ERROR = "recorder_exited_error"
    RECORDER_STOPPED = "recorder_stopped"


# Events that may be received but are explicitly ignored in some states; declared
# so the startup self-check doesn't raise.
IGNORED_BY_DESIGN: set[tuple[State, Event]] = {
    (State.IDLE, Event.STOP),
    (State.IDLE, Event.RELEASE),
    (State.IDLE, Event.COMBO),
    (State.IDLE, Event.NOSTREAM),
    (State.IDLE, Event.LOWERCASE_INITIAL),
    (State.STARTING, Event.COMBO),
    (State.STOPPING, Event.RELEASE),
    (State.STOPPING, Event.COMBO),
    (State.STOPPING, Event.NOSTREAM),
    (State.STOPPING, Event.LOWERCASE_INITIAL),
    (State.STOPPING, Event.START),
    (State.STOPPING_NO_PASTE, Event.RELEASE),
    (State.STOPPING_NO_PASTE, Event.COMBO),
    (State.STOPPING_NO_PASTE, Event.NOSTREAM),
    (State.STOPPING_NO_PASTE, Event.LOWERCASE_INITIAL),
    (State.STOPPING_NO_PASTE, Event.START),
    (State.RECORDING, Event.START),
}
