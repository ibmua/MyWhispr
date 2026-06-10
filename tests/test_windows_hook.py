from __future__ import annotations

import sys
import unittest


@unittest.skipUnless(sys.platform == "win32", "Windows keyboard hook")
class HookSwallowTest(unittest.TestCase):
    def _supervisor(self, trigger_codes):
        from mywhispr.input_events_windows import WindowsInputSupervisor

        events = []
        sup = WindowsInputSupervisor(
            events.append,
            trigger_codes_provider=lambda: set(trigger_codes),
        )
        return sup, events

    def _kb(self, scan, flags=0, vk=0):
        from mywhispr.input_events_windows import KBDLLHOOKSTRUCT

        kb = KBDLLHOOKSTRUCT()
        kb.vkCode = vk
        kb.scanCode = scan
        kb.flags = flags
        return kb

    def test_trigger_key_is_swallowed_down_and_up(self):
        from mywhispr.input_events_windows import WM_KEYDOWN, WM_KEYUP

        sup, _ = self._supervisor({41})  # grave configured as trigger
        self.assertTrue(sup._handle(self._kb(41), WM_KEYDOWN))
        self.assertTrue(sup._handle(self._kb(41), WM_KEYDOWN))  # auto-repeat
        self.assertTrue(sup._handle(self._kb(41), WM_KEYUP))

    def test_non_trigger_key_passes_through(self):
        from mywhispr.input_events_windows import WM_KEYDOWN, WM_KEYUP

        sup, _ = self._supervisor({41})
        self.assertFalse(sup._handle(self._kb(30), WM_KEYDOWN))  # 'a'
        self.assertFalse(sup._handle(self._kb(30), WM_KEYUP))

    def test_grave_passes_through_when_not_a_trigger(self):
        from mywhispr.input_events_windows import WM_KEYDOWN

        sup, _ = self._supervisor(set())
        self.assertFalse(sup._handle(self._kb(41), WM_KEYDOWN))

    def test_grave_vk_fallback_is_swallowed_when_scan_code_is_missing(self):
        from mywhispr.input_events_windows import WM_KEYDOWN, WM_KEYUP

        sup, _ = self._supervisor({41})
        self.assertTrue(sup._handle(self._kb(0, vk=0xC0), WM_KEYDOWN))
        self.assertTrue(sup._handle(self._kb(0, vk=0xC0), WM_KEYUP))

    def test_combo_grab_swallows_everything(self):
        from mywhispr.input_events_windows import WM_KEYDOWN

        sup, _ = self._supervisor({41})
        sup.grab_for_combo()
        self.assertTrue(sup._handle(self._kb(30), WM_KEYDOWN))
        sup.ungrab_all()
        self.assertFalse(sup._handle(self._kb(30), WM_KEYDOWN))


if __name__ == "__main__":
    unittest.main()
