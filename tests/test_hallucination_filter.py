from __future__ import annotations

import unittest

from mywhispr import hallucination_filter


class HallucinationFilterTest(unittest.TestCase):
    def test_exact_phrase_matches_punctuation_spacing_variant(self) -> None:
        phrases = {"en": ["Subtitles by the Amara. org community"]}

        self.assertTrue(
            hallucination_filter.is_exact_phrase(
                "Subtitles by the Amara.org community.",
                phrases,
            )
        )

    def test_configured_subtitle_byline_is_stripped_from_transcript(self) -> None:
        phrases = {"en": ["Subtitles by the Amara. org community"]}

        self.assertEqual(
            hallucination_filter.strip_global_junk(
                "Actual dictation. Subtitles by the Amara.org community.",
                phrases=phrases,
            ),
            "Actual dictation",
        )

    def test_generic_subtitle_byline_is_stripped(self) -> None:
        self.assertEqual(
            hallucination_filter.strip_global_junk("Subtitles by the Amara. org community"),
            "",
        )


if __name__ == "__main__":
    unittest.main()
