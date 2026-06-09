from __future__ import annotations

import unittest

from mywhispr.daemon import (
    TRANSITIONS,
    _handle_recorder_ready_while_stopping,
    _handle_release_starting,
)
from mywhispr.state import Event, State


class FakeRecorder:
    def __init__(self, running: bool = True) -> None:
        self.running = running
        self.stop_calls = 0

    def is_running(self) -> bool:
        return self.running

    async def stop(self):
        self.stop_calls += 1
        self.running = False


class FakeTones:
    def __init__(self) -> None:
        self.stop_calls = 0

    def play_stop(self) -> None:
        self.stop_calls += 1


class FakeDaemon:
    def __init__(self, *, recorder_running: bool = True) -> None:
        self.tones = FakeTones()
        self.recorder = FakeRecorder(recorder_running)
        self._stream = None
        self._release_requested_while_starting = False
        self.events: list[Event] = []
        self.combo_reasons: list[str] = []
        self.cancelled_max_duration = False
        self.stop_watchdog_reasons: list[str] = []

    def post(self, event: Event, **payload) -> None:
        self.events.append(event)

    def _deactivate_combo(self, reason: str) -> None:
        self.combo_reasons.append(reason)

    def _cancel_max_duration_timer(self) -> None:
        self.cancelled_max_duration = True

    def _arm_stop_watchdog(self, reason: str) -> None:
        self.stop_watchdog_reasons.append(reason)


class DaemonStopRaceTest(unittest.IsolatedAsyncioTestCase):
    async def test_release_while_starting_stops_recorder_if_it_already_spawned(self) -> None:
        daemon = FakeDaemon(recorder_running=True)

        state = await _handle_release_starting(daemon, trigger="grave")

        self.assertEqual(state, State.STOPPING)
        self.assertTrue(daemon._release_requested_while_starting)
        self.assertEqual(daemon.recorder.stop_calls, 1)
        self.assertEqual(daemon.events, [Event.RECORDER_STOPPED])
        self.assertEqual(daemon.stop_watchdog_reasons, ["release-starting"])

    async def test_stop_state_handles_late_recorder_ready(self) -> None:
        daemon = FakeDaemon(recorder_running=True)

        state = await _handle_recorder_ready_while_stopping(daemon)

        self.assertEqual(state, State.STOPPING)
        self.assertEqual(daemon.recorder.stop_calls, 1)
        self.assertEqual(daemon.events, [Event.RECORDER_STOPPED])

    def test_late_recorder_ready_transition_is_defined(self) -> None:
        self.assertIs(
            TRANSITIONS[(State.STOPPING, Event.RECORDER_READY)],
            _handle_recorder_ready_while_stopping,
        )


if __name__ == "__main__":
    unittest.main()
