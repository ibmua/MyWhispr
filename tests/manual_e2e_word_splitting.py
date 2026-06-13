#!/usr/bin/env python3
"""Manual end-to-end check for the mid-word word-splitting bug ("neglig ible").

NOT run by unit-test discovery (filename is not test_*.py): it needs espeak-ng
installed and the whisper.cpp server reachable on 127.0.0.1:18178 (start the
mywhisprd service, which manages it). Run directly:

    cd /home/i/CODE/voice-assistants/mywhispr
    python3 tests/manual_e2e_word_splitting.py

It synthesizes long, pause-free Ukrainian/English passages (which force whisper
to break words across timestamped segments), drives the real
mywhispr.transcriber.Transcriber against the live server, and asserts that no
mid-word segment boundary leaked a space into the transcript. Exit code 0 = OK.

The deterministic regression of the same bug lives in tests/test_word_splitting.py
(no network/audio needed); this harness is for reproducing against real audio.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mywhispr.transcriber import Transcriber  # noqa: E402

SERVER_PORT = 18178
CONFIG = {
    "default_model": "large",
    "models": {"large": {"backend": "whisper.cpp", "path": "/unused-by-stub"}},
    "custom_words": [],
    "language_prompts": {},
    "append_trailing_space": False,
    "hallucination_filter": {"enabled": True},
    "snapshot_leading_silence_seconds": 0.0,
}
CASES = [
    ("uk", "Психологічне вимірювання потребує надзвичайної точності, адже "
           "неправильна інтерпретація результатів може призвести до хибних "
           "висновків, які згодом неможливо буде виправити без повторного "
           "обстеження та додаткової перевірки усіх отриманих даних."),
    ("uk", "Сьогодні ми поговоримо про те, наскільки надзвичайно важливою є "
           "продуктивність у сучасному світі, адже саме від неї залежить "
           "результат нашої щоденної роботи та загальне самопочуття людини."),
    ("en", "The difference between these two values is absolutely negligible, "
           "and therefore we can confidently ignore it during the calculation."),
]


class _StubServer:
    """Drives the transcriber at the already-running whisper.cpp without
    spawning/managing a process."""

    base_url = f"http://127.0.0.1:{SERVER_PORT}"
    loaded_model = "large"
    last_error = ""

    async def ensure_ready(self, model=None):
        return True

    def acquire_slot(self):
        pass

    def release_slot(self):
        pass


def _synth(voice: str, text: str) -> bytes:
    raw = f"/tmp/_wsplit_{uuid.uuid4().hex}.wav"
    wav16 = f"/tmp/_wsplit16_{uuid.uuid4().hex}.wav"
    try:
        subprocess.run(["espeak-ng", "-v", voice, "-s", "150", "-w", raw, text],
                       check=True, capture_output=True)
        subprocess.run(["ffmpeg", "-y", "-i", raw, "-ar", "16000", "-ac", "1",
                        "-sample_fmt", "s16", wav16], check=True, capture_output=True)
        with open(wav16, "rb") as f:
            return f.read()
    finally:
        for p in (raw, wav16):
            try:
                os.unlink(p)
            except OSError:
                pass


def _midword_violations(res) -> list[str]:
    """For each segment boundary that falls mid-word (next segment starts with
    an alphanumeric and no leading space), the SPACED version of the glued word
    must NOT appear in the transcript. Language-agnostic: genuine one-letter
    words (Ukrainian є/у/в/і/з) correspond to boundaries that carry a leading
    space, so they are never flagged."""
    segs = res.segments or []
    bad = []
    for i in range(1, len(segs)):
        left = str(segs[i - 1].get("text") or "")
        right = str(segs[i].get("text") or "")
        if not left or not right or right[0].isspace():
            continue
        lr = left.rstrip()
        if not lr or not lr[-1].isalnum() or not right[0].isalnum():
            continue
        spaced = lr.split()[-1] + " " + right.split()[0]
        if spaced in res.text or spaced in res.raw_text:
            bad.append(spaced)
    return bad


async def _main() -> int:
    tr = Transcriber(CONFIG)
    server = _StubServer()
    failures = 0
    try:
        for voice, text in CASES:
            res = await tr.transcribe(server, _synth(voice, text), language=voice)
            bad = _midword_violations(res)
            boundaries = max(0, len(res.segments) - 1)
            print(f"\n[{voice}] {'FAIL' if bad else 'ok'}  "
                  f"({len(res.segments)} segments, {boundaries} mid-word boundaries checked)")
            print(f"  {res.text!r}")
            if bad:
                failures += 1
                print(f"  LEAKED SPLITS: {bad}")
    finally:
        await tr.close()
    print(f"\n{'='*70}\nFAILURES: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
