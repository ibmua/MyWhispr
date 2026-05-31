from __future__ import annotations

import unittest

from mywhispr.model_specs import BUILTIN_MODEL_OPTIONS, model_availability, normalize_model_spec
from mywhispr.web import transcription_api_client_spec


class ExternalApiModelSpecTest(unittest.TestCase):
    def test_remote_large_q5_builtin_is_selectable_without_key(self) -> None:
        spec = normalize_model_spec("remote-large-q5", BUILTIN_MODEL_OPTIONS["remote-large-q5"])
        availability = model_availability(spec)

        self.assertEqual(spec["backend"], "external_api")
        self.assertFalse(spec["api_key_required"])
        self.assertFalse(spec["send_model"])
        self.assertTrue(availability["exists"])
        self.assertTrue(availability["selectable"])
        self.assertIn("uk", spec["languages"])

    def test_external_api_can_skip_model_form_field(self) -> None:
        spec = normalize_model_spec(
            "gateway",
            {
                "backend": "external_api",
                "api_base_url": "http://192.168.50.10:18180",
                "endpoint": "/inference",
                "api_model": "",
                "send_model": False,
                "api_key_required": False,
            },
        )

        self.assertTrue(model_availability(spec)["exists"])


class TranscriptionApiShareSpecTest(unittest.TestCase):
    def test_generated_client_json_contains_connection_and_key(self) -> None:
        cfg = {
            "default_model": "large-q5",
            "models": {
                "large-q5": {
                    "backend": "whisper.cpp",
                    "path": "/tmp/ggml-large-v3-q5_0.bin",
                    "label": "Whisper Large v3 Q5",
                }
            },
            "transcription_api": {
                "enabled": True,
                "host": "0.0.0.0",
                "port": 18180,
                "api_key": "secret-key",
                "advertised_host": "192.168.50.20",
                "advertised_scheme": "http",
                "model_name": "remote-large-q5",
            },
        }

        spec = transcription_api_client_spec(cfg)

        self.assertEqual(spec["backend"], "external_api")
        self.assertEqual(spec["api_base_url"], "http://192.168.50.20:18180")
        self.assertEqual(spec["endpoint"], "/inference")
        self.assertEqual(spec["api_key"], "secret-key")
        self.assertEqual(spec["api_model"], "large-q5")
        self.assertFalse(spec["send_model"])
        self.assertIn("en", spec["languages"])


if __name__ == "__main__":
    unittest.main()
