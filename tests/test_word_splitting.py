"""Regression tests for mid-word space insertion (the "neglig ible" bug).

Three independent causes were found and fixed:

1. whisper.cpp's top-level ``text`` field joins segments with ``"\n"``; when a
   segment starts mid-word, collapse_whitespace turned that newline into a
   visible space. transcriber.py now reconstructs text from the segment list.
2. streaming._stable_text joined segment texts with ``" "``, injecting a space
   before every mid-word continuation segment. It now concatenates.
3. collapse_repeated_sentences split on any ".", shattering dotted tokens like
   "CLAUDE.md" into "CLAUDE. md". It now splits only at terminator+whitespace.

The Ukrainian segment fixtures below are the actual whisper.cpp large-v3
response for synthesized speech (espeak-ng), captured via tests/manual
harness. They contain three real mid-word segment boundaries:
  ...точності, ад | же...      ("адже")
  ...призвести до х | ибних...  ("хибних")
  ...усіх отримани | х даних.   ("отриманих")
"""
from __future__ import annotations

import types
import unittest

from mywhispr import streaming, text_cleanup

# Real whisper.cpp large-v3 segments (leading space at word boundaries, none
# mid-word). `end` values are synthetic-but-monotonic for the streaming test.
UK_SEGMENTS = [
    {"text": " Психологічне вимірювання потребує надзвичайної точності, ад", "end": 3.0},
    {"text": "же неправильна інтерпретація результатів може призвести до х", "end": 6.0},
    {"text": "ибних висновків, які згодом неможливо буде виправити без", "end": 9.0},
    {"text": " повторного обстеження та додаткової перевірки усіх отримани", "end": 12.0},
    {"text": "х даних.", "end": 14.0},
]
UK_EXPECTED = (
    "Психологічне вимірювання потребує надзвичайної точності, адже "
    "неправильна інтерпретація результатів може призвести до хибних "
    "висновків, які згодом неможливо буде виправити без повторного "
    "обстеження та додаткової перевірки усіх отриманих даних."
)
# whisper.cpp builds its top-level `text` by joining segment texts with "\n".
WHISPER_TEXT_FIELD = "\n".join(s["text"] for s in UK_SEGMENTS)

# OpenAI-style external API: every segment trimmed, split only at word
# boundaries (never mid-word).
TRIMMED_SEGMENTS = [
    {"text": "The difference between these two values", "end": 3.0},
    {"text": "is absolutely negligible.", "end": 6.0},
]


def _wav(seconds: float) -> bytes:
    """Minimal 16 kHz/16-bit/mono WAV-shaped buffer of the given duration.

    streaming only reads len(wav[44:]) to compute duration (pcm/32000), so the
    44-byte header and the body contents are irrelevant beyond their length.
    """
    pcm_len = int(seconds * 32000)
    return b"\x00" * 44 + b"\x00" * pcm_len


class SegmentReconstructionTest(unittest.TestCase):
    def test_native_segments_concatenate_without_midword_spaces(self) -> None:
        out = text_cleanup.collapse_whitespace(
            text_cleanup.text_from_segments(UK_SEGMENTS)
        )
        self.assertEqual(out, UK_EXPECTED)
        for bad in ("ад же", "до х ибних", "отримани х"):
            self.assertNotIn(bad, out)

    def test_whisper_text_field_with_newlines_is_the_bug(self) -> None:
        # The OLD final path used collapse_whitespace(data["text"]); prove it
        # produced the splits and that the new helper does not.
        old = text_cleanup.collapse_whitespace(WHISPER_TEXT_FIELD)
        self.assertIn("точності, ад же", old)
        self.assertIn("до х ибних", old)
        new = text_cleanup.collapse_whitespace(
            text_cleanup.text_from_segments(UK_SEGMENTS, fallback=WHISPER_TEXT_FIELD)
        )
        self.assertEqual(new, UK_EXPECTED)

    def test_trimmed_segments_space_join_without_gluing_words(self) -> None:
        out = text_cleanup.collapse_whitespace(
            text_cleanup.text_from_segments(TRIMMED_SEGMENTS)
        )
        self.assertEqual(
            out, "The difference between these two values is absolutely negligible."
        )
        self.assertNotIn("valuesis", out)

    def test_empty_segments_use_fallback(self) -> None:
        self.assertEqual(text_cleanup.text_from_segments([], fallback="hi"), "hi")
        self.assertEqual(text_cleanup.text_from_segments(None, fallback="hi"), "hi")

    def test_ignores_non_dict_and_empty_text_segments(self) -> None:
        segs = [{"text": " hello"}, "junk", {"no_text": 1}, {"text": ""}, {"text": " world"}]
        self.assertEqual(text_cleanup.text_from_segments(segs), " hello world")


class StreamingStableTextTest(unittest.TestCase):
    def _session(self) -> streaming.StreamingSession:
        return streaming.StreamingSession(
            config={"streaming": {"stable_lag_seconds": 0.0}},
            transcriber=None,
            server=None,
            language_provider=lambda: "uk",
            wav_provider=lambda: b"",
            on_preview=lambda _t: None,
            loop=None,
        )

    def test_stable_text_concatenates_native_segments(self) -> None:
        sess = self._session()
        res = types.SimpleNamespace(segments=UK_SEGMENTS, text=UK_EXPECTED)
        stable = sess._stable_text(res, _wav(20.0))
        self.assertEqual(stable, UK_EXPECTED)
        for bad in ("ад же", "до х ибних", "отримани х"):
            self.assertNotIn(bad, stable)


class DottedTokenTest(unittest.TestCase):
    def finalized(self, text: str) -> str:
        return text_cleanup.finalize(text, append_trailing_space=False)

    def test_dotted_tokens_are_not_split(self) -> None:
        for token_text in (
            "Edit CLAUDE.md now please okay",
            "Open psymeasure.com in the browser",
            "The build uses version 2.5 today",
            "See AGENTS.md and README.md for details",
        ):
            self.assertEqual(
                text_cleanup.collapse_repeated_sentences(token_text), token_text
            )
            self.assertEqual(self.finalized(token_text), token_text)

    def test_real_repeated_sentences_still_collapse(self) -> None:
        looped = "this is a test. this is a test. this is a test."
        self.assertEqual(
            text_cleanup.collapse_repeated_sentences(looped), "this is a test."
        )

    def test_repeat_collapse_preserves_dotted_token(self) -> None:
        looped = "Edit CLAUDE.md now. Edit CLAUDE.md now. Edit CLAUDE.md now."
        self.assertEqual(
            text_cleanup.collapse_repeated_sentences(looped), "Edit CLAUDE.md now."
        )

    def test_distinct_sentences_are_preserved(self) -> None:
        text = "Open the file. Read the contents. Close it."
        self.assertEqual(text_cleanup.collapse_repeated_sentences(text), text)


if __name__ == "__main__":
    unittest.main()
