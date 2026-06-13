from __future__ import annotations

import json
from pathlib import Path
import unittest

from mywhispr.gpu_asr_server import GpuAsrServer, _decode_worker_json_line


class GpuAsrProtocolTest(unittest.TestCase):
    def test_decodes_utf8_transcript_json(self) -> None:
        payload = {"ok": True, "text": "Тест ї"}
        raw = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")

        decoded = json.loads(_decode_worker_json_line(raw))

        self.assertEqual(decoded, payload)

    def test_recovers_windows_cyrillic_transcript_json(self) -> None:
        raw = b'{"ok": true, "text": "' + "Тест ї".encode("cp1251") + b'"}\n'
        self.assertEqual(raw[22], 0xD2)

        decoded = json.loads(_decode_worker_json_line(raw))

        self.assertEqual(decoded["text"], "Тест ї")


class GpuAsrServerPathTest(unittest.IsolatedAsyncioTestCase):
    async def test_relative_python_config_does_not_restart_running_worker(self) -> None:
        server = GpuAsrServer(
            model_specs={"demo": {"backend": "transformers_tdt"}},
            python="./.venv-gpu-asr/Scripts/python.exe",
        )
        resolved = Path("C:/repo/.venv-gpu-asr/Scripts/python.exe")
        server._resolve_python = lambda _python: resolved  # type: ignore[method-assign]
        server.proc = type("Proc", (), {"returncode": None})()
        server._running_python = str(resolved)
        server.loaded_model = "demo"
        server._ready.set()

        async def fail_stop() -> None:
            raise AssertionError("worker should not be stopped")

        async def fail_spawn(_python) -> bool:
            raise AssertionError("worker should not be spawned")

        server._stop_locked = fail_stop  # type: ignore[method-assign]
        server._spawn_locked = fail_spawn  # type: ignore[method-assign]

        self.assertTrue(await server.ensure_ready("demo"))


if __name__ == "__main__":
    unittest.main()
