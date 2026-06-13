from __future__ import annotations

import asyncio
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from mywhispr import daemon as daemon_mod
from mywhispr.daemon import (
    MAX_QUEUED_RECORDINGS,
    TranscriptionJob,
    _capture_job,
    _handle_recorder_stopped,
    _process_job,
)
from mywhispr.history import History
from mywhispr.state import State


def _wav_bytes(seconds: float = 1.0) -> bytes:
    return b"\x00" * (44 + int(16000 * 2 * seconds))


class _FakeConfig:
    def __init__(self, values: dict | None = None) -> None:
        self.values = values or {}

    def get(self, key, default=None):
        return self.values.get(key, default)


class _FakeTones:
    def __init__(self) -> None:
        self.errors = 0

    def play_error(self) -> None:
        self.errors += 1


class _FakeResult:
    def __init__(self, text: str) -> None:
        self.text = text
        self.raw_text = text
        self.model = "fake-model"
        self.elapsed_seconds = 0.01


class _FakeTranscriber:
    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.calls: list[str] = []

    async def transcribe(self, _server, wav_bytes, *, language):
        self.calls.append(language)
        if self.delay:
            await asyncio.sleep(self.delay)
        return _FakeResult(f"text-{len(self.calls)}")


class _FakeRecorder:
    def __init__(self, path: Path, data: bytes) -> None:
        self.path = path
        self._data = data
        self.cleaned = False

    def read_bytes(self) -> bytes:
        return self._data

    def duration_seconds(self) -> float:
        return 1.0

    def cleanup(self) -> None:
        self.cleaned = True


def _fake_daemon(tmp_path: Path, *, transcriber=None) -> types.SimpleNamespace:
    d = types.SimpleNamespace()
    d.config = _FakeConfig({"minimum_recording_seconds": 0.25})
    d.history = History(limit=20)
    d.tones = _FakeTones()
    d.transcriber = transcriber or _FakeTranscriber()
    d.primary_server = types.SimpleNamespace(loaded_model="fake-model")
    d.recorder = _FakeRecorder(tmp_path, _wav_bytes())
    d._current_language = "en"
    d._current_mode = "en"
    d._current_mode_config = {"type": "language"}
    d._current_trigger = "grave"
    d._stream = None
    d._last_preview_text = ""
    d.last_stop_at = 0.0
    d._job_queue = asyncio.Queue(maxsize=MAX_QUEUED_RECORDINGS)
    d._job_phase = ""
    d._combo_key_down_at = {}
    d._combo_long_task = None
    d._release_requested_while_starting = False
    d._session_lowercase_initial = False
    d._cancel_stop_watchdog = lambda: None
    return d


class RecorderStoppedTest(unittest.IsolatedAsyncioTestCase):
    async def test_recorder_stopped_enqueues_and_returns_idle(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            rec = Path(td) / "rec.raw"
            rec.write_bytes(b"\x00" * 64000)
            d = _fake_daemon(rec)
            d.recorder.path = rec

            state = await _handle_recorder_stopped(d)

            self.assertEqual(state, State.IDLE)
            self.assertEqual(d._job_queue.qsize(), 1)
            job = d._job_queue.get_nowait()
            self.assertTrue(job.paste_allowed)
            self.assertEqual(job.language, "en")
            self.assertTrue(d.recorder.cleaned)
            self.assertEqual(d._current_trigger, "")
            self.assertGreater(d.last_stop_at, 0.0)

    async def test_capture_resets_stream_for_next_take(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            rec = Path(td) / "rec.raw"
            rec.write_bytes(b"\x00" * 64000)
            d = _fake_daemon(rec)
            d.recorder.path = rec
            sentinel_stream = object()
            d._stream = sentinel_stream

            job = _capture_job(d, paste_allowed=True)

            self.assertIs(job.stream, sentinel_stream)
            self.assertIsNone(d._stream)


class JobProcessingTest(unittest.IsolatedAsyncioTestCase):
    async def test_jobs_paste_in_fifo_order(self) -> None:
        import tempfile

        pasted: list[str] = []

        async def fake_paste_final(text, **_kwargs) -> bool:
            await asyncio.sleep(0.01)
            pasted.append(text)
            return True

        with tempfile.TemporaryDirectory() as td:
            d = _fake_daemon(Path(td) / "x.raw", transcriber=_FakeTranscriber(delay=0.02))
            for lang in ("en", "uk", "de"):
                d._job_queue.put_nowait(TranscriptionJob(
                    wav_bytes=_wav_bytes(),
                    duration=1.0,
                    language=lang,
                    mode="en",
                ))

            with patch.object(daemon_mod.paste_mod, "paste_final", fake_paste_final):
                while not d._job_queue.empty():
                    job = d._job_queue.get_nowait()
                    await _process_job(d, job)

            self.assertEqual(pasted, ["text-1", "text-2", "text-3"])
            self.assertEqual(d.transcriber.calls, ["en", "uk", "de"])
            items = d.history.list()
            self.assertEqual(len(items), 3)
            self.assertTrue(all(i.pasted for i in items))

    async def test_short_recording_is_dropped_quietly(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            d = _fake_daemon(Path(td) / "x.raw")
            await _process_job(d, TranscriptionJob(
                wav_bytes=b"\x00" * 100,
                duration=0.01,
                language="en",
                mode="en",
            ))
            self.assertEqual(len(d.history.list()), 0)
            self.assertEqual(d.tones.errors, 0)

    async def test_transcription_failure_records_history_and_tone(self) -> None:
        import tempfile

        class _Failing:
            async def transcribe(self, *_a, **_k):
                raise RuntimeError("model exploded")

        with tempfile.TemporaryDirectory() as td:
            d = _fake_daemon(Path(td) / "x.raw", transcriber=_Failing())
            await _process_job(d, TranscriptionJob(
                wav_bytes=_wav_bytes(),
                duration=1.0,
                language="en",
                mode="en",
            ))
            items = d.history.list()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].failed_reason, "model exploded")
            self.assertEqual(d.tones.errors, 1)

    async def test_no_paste_job_is_recorded_not_pasted(self) -> None:
        import tempfile

        pasted: list[str] = []

        async def fake_paste_final(text, **_kwargs) -> bool:
            pasted.append(text)
            return True

        with tempfile.TemporaryDirectory() as td:
            d = _fake_daemon(Path(td) / "x.raw")
            with patch.object(daemon_mod.paste_mod, "paste_final", fake_paste_final):
                await _process_job(d, TranscriptionJob(
                    wav_bytes=_wav_bytes(),
                    duration=1.0,
                    language="en",
                    mode="en",
                    paste_allowed=False,
                ))
            self.assertEqual(pasted, [])
            items = d.history.list()
            self.assertEqual(len(items), 1)
            self.assertFalse(items[0].pasted)
            self.assertEqual(items[0].failed_reason, "no_paste")


if __name__ == "__main__":
    unittest.main()
