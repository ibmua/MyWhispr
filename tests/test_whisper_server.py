from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mywhispr.whisper_server import WhisperServer


class WhisperServerConfigTest(unittest.IsolatedAsyncioTestCase):
    async def test_missing_binary_is_clear_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            model_path = Path(td) / "ggml-small.bin"
            model_path.write_bytes(b"not a real model, but enough for path validation")
            server = WhisperServer(
                binary="",
                host="127.0.0.1",
                port=18178,
                model_paths={
                    "small": {
                        "backend": "whisper.cpp",
                        "path": str(model_path),
                    }
                },
            )

            ok = await server.ensure_ready("small")

        self.assertFalse(ok)
        self.assertIn("whisper_server_binary is not configured", server.last_error)
        self.assertIsNone(server.loaded_model)


if __name__ == "__main__":
    unittest.main()
