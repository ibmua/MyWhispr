from __future__ import annotations

import unittest

from mywhispr import paste
from mywhispr import text_cleanup


class TextCleanupTest(unittest.TestCase):
    def finalized(self, text: str) -> str:
        return text_cleanup.finalize(text, append_trailing_space=False)

    def test_collapses_whitespace_without_phrase_rewrites(self) -> None:
        self.assertEqual(self.finalized("Token_123\nstill fails."), "Token_123 still fails.")


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


class PasteFinalTest(unittest.IsolatedAsyncioTestCase):
    async def test_short_printable_ascii_uses_type_before_clipboard(self) -> None:
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
            backend=FakeBackend(),
        )

        self.assertTrue(ok)
        self.assertEqual(calls, [("type", "Alpha beta ", 0)])


if __name__ == "__main__":
    unittest.main()
