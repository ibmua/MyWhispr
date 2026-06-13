from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from mywhispr import streaming


class FakeConfig:
    def __init__(self, data: dict) -> None:
        self.data = data

    def get(self, key: str, default=None):
        cur = self.data
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur


def wav_with_constant_pcm(value: int, *, seconds: float = 2.0) -> bytes:
    sample = int(value).to_bytes(2, "little", signed=True)
    return (b"\0" * 44) + sample * int(16000 * seconds)


class StreamingCommitTest(unittest.IsolatedAsyncioTestCase):
    def make_session(self) -> streaming.StreamingSession:
        cfg = FakeConfig({
            "streaming": {
                "app_output_enabled": True,
                "stable_lag_seconds": 0.35,
                "max_rewrite_chars": 180,
                "initial_commit_confirmations": 1,
                "rewrite_backspace_confirmations": 2,
                "pause_gate_enabled": True,
                "pause_gate_min_silence_seconds": 0.25,
                "pause_gate_max_rms": 1.0,
                "pause_gate_relative_rms_ratio": 0.1,
            },
            "clipboard_settle_seconds": 0,
            "clipboard_paste_consume_timeout_seconds": 0,
            "paste_key_delay_ms": 0,
            "type_key_delay_ms": 0,
            "direct_type_max_chars": 240,
            "direct_type_ascii_only": True,
            "prefer_clipboard_paste": True,
        })
        return streaming.StreamingSession(
            config=cfg,
            transcriber=None,
            server=None,
            language_provider=lambda: "en",
            wav_provider=lambda: b"",
            on_preview=lambda _text: None,
            loop=asyncio.get_running_loop(),
        )

    async def test_append_commit_does_not_wait_for_pause_gate(self) -> None:
        session = self.make_session()
        wav = wav_with_constant_pcm(1000)
        res = SimpleNamespace(text="hello world", segments=[{"end": 0.5, "text": "hello"}])
        calls: list[dict] = []

        async def fake_stream_replace(**kwargs) -> bool:
            calls.append(kwargs)
            return True

        with patch.object(streaming.paste_mod, "stream_replace", fake_stream_replace):
            await session._maybe_commit_to_app(res, wav)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["previous"], "")
        self.assertEqual(calls[0]["new"], "hello")
        self.assertEqual(session.committed_text, "hello")

    async def test_destructive_rewrite_still_waits_for_pause_gate(self) -> None:
        session = self.make_session()
        session.committed_text = "old text"
        session.app_output_started = True
        wav = wav_with_constant_pcm(1000)
        res = SimpleNamespace(text="new text", segments=[{"end": 0.5, "text": "new text"}])
        calls: list[dict] = []

        async def fake_stream_replace(**kwargs) -> bool:
            calls.append(kwargs)
            return True

        with patch.object(streaming.paste_mod, "stream_replace", fake_stream_replace):
            await session._maybe_commit_to_app(res, wav)

        self.assertEqual(calls, [])
        self.assertEqual(session.committed_text, "old text")


if __name__ == "__main__":
    unittest.main()
