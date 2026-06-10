from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from mywhispr.model_specs import public_model_card, whisper_cpp_download_url


class WhisperCppDownloadMetadataTest(unittest.TestCase):
    def test_missing_ggml_model_is_downloadable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "models" / "ggml-large-v3-q5_0.bin"
            spec = {
                "backend": "whisper.cpp",
                "path": str(path),
                "label": "Whisper Large v3 Q5",
            }

            card = public_model_card("large-q5", spec)

        self.assertFalse(card["exists"])
        self.assertFalse(card["selectable"])
        self.assertTrue(card["downloadable"])
        self.assertEqual(
            card["download_url"],
            "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-q5_0.bin",
        )

    def test_explicit_whisper_download_url_wins(self) -> None:
        spec = {
            "backend": "whisper.cpp",
            "path": "./models/custom.bin",
            "download_url": "https://example.invalid/custom.bin",
        }

        self.assertEqual(whisper_cpp_download_url(spec), "https://example.invalid/custom.bin")

    def test_uncached_hf_gpu_model_is_downloadable_not_selectable(self) -> None:
        old_hf_home = os.environ.get("HF_HOME")
        with tempfile.TemporaryDirectory() as td:
            os.environ["HF_HOME"] = td
            try:
                card = public_model_card(
                    "gpu-demo",
                    {"backend": "transformers_tdt", "repo_id": "example/gpu-demo"},
                )
            finally:
                if old_hf_home is None:
                    os.environ.pop("HF_HOME", None)
                else:
                    os.environ["HF_HOME"] = old_hf_home

        self.assertFalse(card["exists"])
        self.assertFalse(card["selectable"])
        self.assertFalse(card["cached"])
        self.assertTrue(card["downloadable"])


if __name__ == "__main__":
    unittest.main()
