from __future__ import annotations

import unittest
from unittest.mock import patch

from mywhispr import paste
from mywhispr import text_cleanup


class TextCleanupTest(unittest.TestCase):
    def finalized(self, text: str) -> str:
        return text_cleanup.finalize(text, append_trailing_space=False)

    def test_collapses_whitespace_without_phrase_rewrites(self) -> None:
        self.assertEqual(self.finalized("Token_123\nstill fails."), "Token_123 still fails.")

    def test_lowercases_first_cased_letter_for_ukrainian(self) -> None:
        self.assertEqual(text_cleanup.lowercase_first_cased("Привіт, світе."), "привіт, світе.")

    def test_lowercases_first_cased_letter_after_punctuation(self) -> None:
        self.assertEqual(text_cleanup.lowercase_first_cased("«Hello there»"), "«hello there»")

    def test_lowercase_initial_finalize_keeps_trailing_space_option(self) -> None:
        self.assertEqual(
            text_cleanup.finalize("  Доброго дня.  ", append_trailing_space=True, lowercase_initial=True),
            "доброго дня. ",
        )

    def test_lowercase_first_cased_leaves_uncased_text_alone(self) -> None:
        self.assertEqual(text_cleanup.lowercase_first_cased("123 ..."), "123 ...")


class PasteRoutingTest(unittest.TestCase):
    def test_direct_type_is_generic_for_short_printable_ascii(self) -> None:
        self.assertTrue(paste.should_direct_type("Alpha beta "))
        self.assertTrue(paste.should_direct_type("format this"))
        self.assertFalse(paste.should_direct_type("x" * 241))
        self.assertFalse(paste.should_direct_type("Привіт"))
        self.assertFalse(paste.should_direct_type("line one\nline two"))

    def test_fast_ascii_keycodes_cover_printable_direct_type_chars(self) -> None:
        sample = "Aa Zz 09 !@#$%^&*()_+-=[]{}\\|;:'\",.<>/?`~"
        for ch in sample:
            self.assertIsNotNone(paste._ascii_key_chord(ch), ch)

    def test_gnome_input_source_parsing_gates_fast_type(self) -> None:
        sources = paste._parse_gsettings_sources("[('xkb', 'us'), ('xkb', 'ua+winkeys')]")
        self.assertEqual(paste._parse_gsettings_current("uint32 0"), 0)
        self.assertEqual(sources, [("xkb", "us"), ("xkb", "ua+winkeys")])
        self.assertTrue(paste._source_id_uses_us_keycodes(*sources[0]))
        self.assertFalse(paste._source_id_uses_us_keycodes(*sources[1]))

    def test_ibus_engine_parsing_gates_fast_type(self) -> None:
        self.assertEqual(paste._parse_ibus_engine("xkb:us::eng"), ("xkb", "us"))
        self.assertEqual(paste._parse_ibus_engine("xkb:ua::ukr"), ("xkb", "ua"))
        self.assertTrue(paste._source_id_uses_us_keycodes(*paste._parse_ibus_engine("xkb:us::eng")))
        self.assertFalse(paste._source_id_uses_us_keycodes(*paste._parse_ibus_engine("xkb:ua::ukr")))


class PasteFinalTest(unittest.IsolatedAsyncioTestCase):
    async def test_layout_gate_uses_live_ibus_engine(self) -> None:
        async def fake_command(args, *, timeout=0.5):
            if args == ["ibus", "engine"]:
                return "xkb:ua::ukr"
            raise AssertionError(f"unexpected command {args}")

        with patch.dict(paste.os.environ, {"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}):
            with patch.object(paste.sys, "platform", "linux"):
                with patch.object(paste, "_command_stdout", fake_command):
                    self.assertFalse(await paste._linux_fast_type_safe_for_current_layout())

    async def test_layout_gate_fails_closed_when_only_stale_gsettings_exists(self) -> None:
        async def fake_command(args, *, timeout=0.5):
            if args == ["ibus", "engine"]:
                return ""
            if args == ["gsettings", "get", "org.gnome.desktop.input-sources", "current"]:
                return "uint32 0"
            if args == ["gsettings", "get", "org.gnome.desktop.input-sources", "sources"]:
                return "[('xkb', 'us'), ('xkb', 'ua+winkeys')]"
            raise AssertionError(f"unexpected command {args}")

        with patch.dict(paste.os.environ, {"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}):
            with patch.object(paste.sys, "platform", "linux"):
                with patch.object(paste, "_command_stdout", fake_command):
                    self.assertFalse(await paste._linux_fast_type_safe_for_current_layout())

    async def test_short_printable_ascii_prefers_clipboard_by_default(self) -> None:
        calls: list[tuple[str, str, int | None]] = []

        class FakeBackend:
            name = "fake"

            async def type_text(self, text: str, *, delay_ms: int) -> bool:
                calls.append(("type", text, delay_ms))
                return True

            async def paste_text(self, text: str, **_kwargs) -> bool:
                calls.append(("paste", text, None))
                return True

            async def copy_text(self, _text: str) -> bool:
                return True

            async def backspace(self, _count: int) -> bool:
                return True

        ok = await paste.paste_final(
            "Alpha beta ",
            settle_seconds=0,
            consume_timeout=0,
            backend=FakeBackend(),
        )

        self.assertTrue(ok)
        self.assertEqual(calls, [("paste", "Alpha beta ", None)])

    async def test_short_printable_ascii_can_use_legacy_type_first_mode(self) -> None:
        calls: list[tuple[str, str, int | None]] = []

        class FakeBackend:
            name = "fake"

            async def type_text(self, text: str, *, delay_ms: int) -> bool:
                calls.append(("type", text, delay_ms))
                return True

            async def paste_text(self, *_args, **_kwargs) -> bool:
                raise AssertionError("short printable ASCII should not use clipboard")

            async def copy_text(self, _text: str) -> bool:
                return True

            async def backspace(self, _count: int) -> bool:
                return True

        ok = await paste.paste_final(
            "Alpha beta ",
            settle_seconds=0,
            consume_timeout=0,
            prefer_clipboard_paste=False,
            backend=FakeBackend(),
        )

        self.assertTrue(ok)
        self.assertEqual(calls, [("type", "Alpha beta ", 0)])

    async def test_wayland_clipboard_paste_restores_original_after_success(self) -> None:
        calls: list[tuple] = []

        class FakeProc:
            returncode: int | None = None

        proc = FakeProc()
        snapshot = paste._WaylandClipboardSnapshot("text/plain;charset=utf-8", b"old clipboard")

        async def fake_snapshot():
            calls.append(("snapshot",))
            return snapshot

        async def fake_start(text: str, *, paste_once: bool):
            calls.append(("start", text, paste_once))
            return proc

        async def fake_keys(_chord, *, delay_ms: int | None = None):
            calls.append(("keys", delay_ms))
            return True

        async def fake_wait(wait_proc, *, timeout: float, kill_on_timeout: bool = True):
            self.assertIs(wait_proc, proc)
            calls.append(("wait", timeout, kill_on_timeout))
            proc.returncode = 0
            return True

        async def fake_stop(stop_proc):
            self.assertIs(stop_proc, proc)
            calls.append(("stop", proc.returncode))

        async def fake_restore(restore_snapshot):
            calls.append(("restore", restore_snapshot.mime_type, restore_snapshot.data))
            return True

        with patch.object(paste, "_wayland_clipboard_snapshot", fake_snapshot):
            with patch.object(paste, "_start_wl_copy", fake_start):
                with patch.object(paste, "_ydotool_keys", fake_keys):
                    with patch.object(paste, "_wait_wl_copy", fake_wait):
                        with patch.object(paste, "_stop_wl_copy", fake_stop):
                            with patch.object(paste, "_restore_wayland_clipboard", fake_restore):
                                ok = await paste._wayland_clipboard_paste(
                                    "new transcript",
                                    settle_seconds=0,
                                    consume_timeout=0.2,
                                    key_delay_ms=18,
                                )

        self.assertTrue(ok)
        self.assertEqual(calls[-1], ("restore", "text/plain;charset=utf-8", b"old clipboard"))

    async def test_wayland_clipboard_paste_restores_original_after_failure(self) -> None:
        calls: list[tuple] = []

        class FakeProc:
            returncode: int | None = None

        proc = FakeProc()
        snapshot = paste._WaylandClipboardSnapshot("text/plain", b"keep me")

        async def fake_snapshot():
            return snapshot

        async def fake_start(_text: str, *, paste_once: bool):
            calls.append(("start", paste_once))
            return proc

        async def fake_keys(_chord, *, delay_ms: int | None = None):
            calls.append(("keys", delay_ms))
            return True

        async def fake_wait(_proc, *, timeout: float, kill_on_timeout: bool = True):
            calls.append(("wait", timeout, kill_on_timeout))
            return False

        async def fake_stop(_proc):
            proc.returncode = -15
            calls.append(("stop",))

        async def fake_restore(restore_snapshot):
            calls.append(("restore", restore_snapshot.mime_type, restore_snapshot.data))
            return True

        with patch.object(paste, "_wayland_clipboard_snapshot", fake_snapshot):
            with patch.object(paste, "_start_wl_copy", fake_start):
                with patch.object(paste, "_ydotool_keys", fake_keys):
                    with patch.object(paste, "_wait_wl_copy", fake_wait):
                        with patch.object(paste, "_stop_wl_copy", fake_stop):
                            with patch.object(paste, "_restore_wayland_clipboard", fake_restore):
                                with patch.object(paste.log, "warning"):
                                    ok = await paste._wayland_clipboard_paste(
                                        "new transcript",
                                        settle_seconds=0,
                                        consume_timeout=0.2,
                                        key_delay_ms=18,
                                    )

        self.assertFalse(ok)
        self.assertEqual(calls.count(("keys", 18)), len(paste.PASTE_CHORDS))
        self.assertEqual(calls[-1], ("restore", "text/plain", b"keep me"))

    async def test_clipboard_failure_falls_back_to_direct_type(self) -> None:
        calls: list[tuple[str, str, int | None]] = []

        class FakeBackend:
            name = "fake"

            async def type_text(self, text: str, *, delay_ms: int) -> bool:
                calls.append(("type", text, delay_ms))
                return True

            async def paste_text(self, text: str, **_kwargs) -> bool:
                calls.append(("paste", text, None))
                return False

            async def copy_text(self, _text: str) -> bool:
                return True

            async def backspace(self, _count: int) -> bool:
                return True

        ok = await paste.paste_final(
            "Alpha beta ",
            settle_seconds=0,
            consume_timeout=0,
            backend=FakeBackend(),
        )

        self.assertTrue(ok)
        self.assertEqual(calls, [("paste", "Alpha beta ", None), ("type", "Alpha beta ", 0)])


if __name__ == "__main__":
    unittest.main()
