import types
import unittest

from mywhispr.daemon import Daemon
from mywhispr.key_event import KeyEvent
from mywhispr.state import State


class SyntheticShortcutTests(unittest.TestCase):
    def make_daemon(self):
        events = []
        d = types.SimpleNamespace(
            state=State.RECORDING, _current_trigger='grave',
            _combo_active=True, _combo_key_down_at={}, _combo_long_task=None,
            _pressed_keycodes=set(), _last_key_down_at={}, _last_key_up_at={},
            _maybe_start_from_keydown=lambda code: None,
            config={'triggers': {'grave': {'stop_on_release_codes': [41],
                'combo': {'keys': [{'code': 42, 'short_mode': 'uk'}]}}}},
            post=lambda *args, **kwargs: events.append((args, kwargs)),
        )
        return d, events

    def test_injected_shift_cannot_switch_recording_language(self):
        d, events = self.make_daemon()
        Daemon._on_key(d, KeyEvent('/dev/input/test', 'ydotoold virtual device', 42, 1))
        self.assertEqual(events, [])
        self.assertEqual(d._combo_key_down_at, {})

    def test_injected_grave_release_cannot_stop_recording(self):
        d, events = self.make_daemon()
        Daemon._on_key(d, KeyEvent('/dev/input/test', 'ydotoold virtual device', 41, 0))
        self.assertEqual(events, [])

    def test_physical_shift_still_switches_recording_language(self):
        d, events = self.make_daemon()
        Daemon._on_key(d, KeyEvent('/dev/input/test', 'Logitech keyboard', 42, 1))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][1]['mode'], 'uk')
