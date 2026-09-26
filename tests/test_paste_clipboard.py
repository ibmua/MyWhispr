from __future__ import annotations

import asyncio
import contextlib
import time
import unittest
from unittest.mock import patch

from mywhispr import paste as paste_mod


class _FakeWlCopy:
    """Stand-in for the spawned `wl-copy --paste-once` process.

    Measured on this desktop (wl-clipboard 2.2.1): `wl-copy` FORKS once it has
    taken the selection, so the process we hold exits at ownership -- the
    clipboard reads back as ours right after -- and the child that serves the
    data is not ours to wait on. Process exit therefore means "the dictation is
    now on the clipboard", NOT "the app pasted it". `consume_after` is that
    ownership delay; `None` means wl-copy never took the selection at all.
    """

    def __init__(self, consume_after: float | None) -> None:
        self.consume_after = consume_after
        self.returncode: int | None = None
        self.stderr = None
        self.terminated = False
        self._done = asyncio.Event()
        self._handle = None

    def arm(self) -> None:
        if self.consume_after is not None:
            loop = asyncio.get_running_loop()
            self._handle = loop.call_later(self.consume_after, self._consume)

    def _consume(self) -> None:
        if self.returncode is None:
            self.returncode = 0
            self._done.set()

    async def wait(self) -> int:
        await self._done.wait()
        assert self.returncode is not None
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        if self.returncode is None:
            self.returncode = 143
            self._done.set()

    def kill(self) -> None:
        self.terminate()


class _Harness:
    """Records the ordered timeline of side effects of a paste attempt."""

    def __init__(
        self,
        consume_after: float | None,
        key_results: list[bool] | None = None,
    ) -> None:
        self.proc = _FakeWlCopy(consume_after)
        self.events: list[tuple[str, float]] = []
        self.chords_sent: list[list[str]] = []
        # Per-chord delivery outcome; exhausted entries default to success.
        self.key_results = list(key_results or [])
        self._t0 = time.monotonic()

    def _mark(self, name: str) -> None:
        self.events.append((name, time.monotonic() - self._t0))

    def names(self) -> list[str]:
        return [name for name, _ in self.events]

    async def snapshot(self):
        self._mark("snapshot")
        return paste_mod._WaylandClipboardSnapshot(
            mime_type="text/plain;charset=utf-8",
            data=b"PREVIOUSLY COPIED TEXT",
        )

    async def start_wl_copy(self, text, *, paste_once):
        self._mark("wl-copy")
        self.proc.arm()
        return self.proc

    async def ydotool_keys(self, keys, *, delay_ms):
        self._mark("chord")
        self.chords_sent.append(keys)
        if self.key_results:
            return self.key_results.pop(0)
        return True

    async def restore(self, snapshot):
        self._mark("restore")
        return True

    def patches(self):
        return (
            patch.object(paste_mod, "_wayland_clipboard_snapshot", self.snapshot),
            patch.object(paste_mod, "_start_wl_copy", self.start_wl_copy),
            patch.object(paste_mod, "_ydotool_keys", self.ydotool_keys),
            patch.object(paste_mod, "_restore_wayland_clipboard", self.restore),
        )


async def _settle() -> None:
    """Let the detached clipboard release finish before asserting on it."""
    release = paste_mod._pending_release
    if release is not None:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await release.task


def _run(harness: _Harness, **kwargs) -> bool:
    async def main() -> bool:
        p1, p2, p3, p4 = harness.patches()
        with p1, p2, p3, p4:
            ok = await paste_mod._wayland_clipboard_paste("dictated words", **kwargs)
            await _settle()
            return ok

    paste_mod._pending_release = None
    return asyncio.run(main())


class SlowConsumerTests(unittest.TestCase):
    """A busy app can service the paste later than the consume timeout.

    The keystroke has already been delivered, so the paste request is still in
    flight. Restoring the previous clipboard inside that window makes the app
    paste the *previously copied text* instead of the dictation.
    """

    def test_late_consumer_is_treated_as_success(self) -> None:
        harness = _Harness(consume_after=0.20)
        ok = _run(
            harness,
            settle_seconds=0.0,
            consume_timeout=0.05,
            key_delay_ms=0,
            grace_seconds=1.0,
        )
        self.assertTrue(ok, "a late-but-real paste must count as success")

    def test_clipboard_is_not_restored_while_paste_in_flight(self) -> None:
        harness = _Harness(consume_after=0.20)
        _run(
            harness,
            settle_seconds=0.0,
            consume_timeout=0.05,
            key_delay_ms=0,
            grace_seconds=1.0,
        )
        names = harness.names()
        self.assertIn("restore", names)
        self.assertLess(
            names.index("chord"),
            names.index("restore"),
            "sanity: chord precedes restore",
        )
        restore_at = dict(harness.events[::-1])["restore"]
        self.assertGreaterEqual(
            restore_at,
            0.20,
            "old clipboard was restored while the app's paste was still pending",
        )
        self.assertFalse(
            harness.proc.terminated,
            "the offered text was withdrawn before the app could read it",
        )

    def test_no_second_chord_when_first_one_lands_late(self) -> None:
        harness = _Harness(consume_after=0.20)
        _run(
            harness,
            settle_seconds=0.0,
            consume_timeout=0.05,
            key_delay_ms=0,
            grace_seconds=1.0,
        )
        self.assertEqual(
            harness.names().count("chord"),
            1,
            "extra chords turn one dictation into several pastes",
        )


class DeadChordTests(unittest.TestCase):
    """A chord that cannot be DELIVERED falls through to the next one.

    Whether a delivered chord was ignored by the app is not observable (the
    only handle we hold exited at ownership), so that is not what the fallback
    chord is for -- an undeliverable keystroke is.
    """

    def test_falls_back_to_the_next_chord_when_the_keystroke_fails(self) -> None:
        # The first chord never reaches the compositor.
        harness = _Harness(consume_after=0.02, key_results=[False, True])
        ok = _run(
            harness,
            settle_seconds=0.0,
            consume_timeout=0.02,
            key_delay_ms=0,
            grace_seconds=0.05,
        )
        self.assertTrue(ok)
        self.assertEqual(
            harness.chords_sent, [chord for _name, chord in paste_mod.PASTE_CHORDS]
        )
        self.assertEqual(harness.names()[-1], "restore")

    def test_gives_up_and_restores_when_no_chord_can_be_delivered(self) -> None:
        harness = _Harness(
            consume_after=0.02,
            key_results=[False] * len(paste_mod.PASTE_CHORDS),
        )
        ok = _run(
            harness,
            settle_seconds=0.0,
            consume_timeout=0.02,
            key_delay_ms=0,
            grace_seconds=0.05,
        )
        self.assertFalse(ok)
        self.assertEqual(harness.names().count("chord"), len(paste_mod.PASTE_CHORDS))
        self.assertEqual(harness.names()[-1], "restore")


class CancelledPasteTests(unittest.TestCase):
    """Releasing the trigger cancels the streaming task mid-paste.

    `StreamingSession.stop()` joins for `cancel_streaming_join_timeout` (1s) and
    then cancels, which lands inside the grace wait. The chords were already
    delivered as real keystrokes, so restoring the previous clipboard while
    unwinding makes the app paste the *previously copied text*.
    """

    def test_cancel_does_not_restore_while_a_chord_is_pending(self) -> None:
        harness = _Harness(consume_after=0.02)  # wl-copy owns the clipboard
        grace = 0.6

        async def main() -> None:
            p1, p2, p3, p4 = harness.patches()
            with p1, p2, p3, p4:
                task = asyncio.ensure_future(
                    paste_mod._wayland_clipboard_paste(
                        "dictated words",
                        settle_seconds=0.0,
                        consume_timeout=0.05,
                        key_delay_ms=0,
                        grace_seconds=grace,
                    )
                )
                # Land the cancellation inside the grace wait, after the first
                # chord has already been delivered.
                await asyncio.sleep(0.30)
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                # The daemon's loop keeps running after the cancellation, so any
                # deferred clipboard work still gets its chance to finish.
                await asyncio.sleep(grace + 0.3)

        asyncio.run(main())

        events = dict(harness.events[::-1])
        self.assertIn("restore", events, "the previous clipboard must come back eventually")
        last_chord = max(at for name, at in harness.events if name == "chord")
        self.assertGreaterEqual(
            events["restore"] - last_chord,
            grace,
            "old clipboard was restored while a delivered chord was still pending",
        )


class BackToBackPasteTests(unittest.TestCase):
    """The final paste follows ~1s after the streaming session was cancelled.

    While the cancelled attempt is still holding the clipboard, reading it back
    returns MyWhispr's own dictation, so the next paste must reuse the pending
    snapshot instead of adopting our text as the user's clipboard.
    """

    def test_second_paste_restores_the_users_clipboard_not_the_dictation(self) -> None:
        restored: list[bytes] = []
        snapshots = [b"USER TEXT", b"dictated words"]
        reads: list[bytes] = []
        procs = [_FakeWlCopy(0.02), _FakeWlCopy(0.02)]  # both take the selection

        async def snapshot():
            data = snapshots[len(reads)] if len(reads) < len(snapshots) else b"?"
            reads.append(data)
            return paste_mod._WaylandClipboardSnapshot(
                mime_type="text/plain;charset=utf-8", data=data
            )

        async def start_wl_copy(text, *, paste_once):
            proc = procs.pop(0) if procs else _FakeWlCopy(None)
            proc.arm()
            return proc

        async def restore(snap):
            restored.append(snap.data)
            return True

        async def keys(chord, *, delay_ms):
            return True

        async def main() -> None:
            with patch.object(paste_mod, "_wayland_clipboard_snapshot", snapshot), \
                 patch.object(paste_mod, "_start_wl_copy", start_wl_copy), \
                 patch.object(paste_mod, "_ydotool_keys", keys), \
                 patch.object(paste_mod, "_restore_wayland_clipboard", restore):
                kwargs = dict(
                    settle_seconds=0.0,
                    consume_timeout=0.05,
                    key_delay_ms=0,
                    grace_seconds=0.6,
                )
                task = asyncio.ensure_future(
                    paste_mod._wayland_clipboard_paste("dictated words", **kwargs)
                )
                await asyncio.sleep(0.30)
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                await paste_mod._wayland_clipboard_paste("final text", **kwargs)
                await _settle()

        paste_mod._pending_release = None
        asyncio.run(main())

        self.assertEqual(len(reads), 1, "the clipboard was re-read while we owned it")
        self.assertEqual(
            restored,
            [b"USER TEXT"],
            "the dictation was handed back to the user as their clipboard",
        )


class FastConsumerTests(unittest.TestCase):
    def test_normal_path_is_unchanged(self) -> None:
        harness = _Harness(consume_after=0.0)
        ok = _run(
            harness,
            settle_seconds=0.0,
            consume_timeout=0.5,
            key_delay_ms=0,
            grace_seconds=1.0,
        )
        self.assertTrue(ok)
        self.assertEqual(harness.names().count("chord"), 1)
        self.assertEqual(harness.names()[-1], "restore")

    def test_consumed_offer_still_holds_the_clipboard(self) -> None:
        """On GNOME the clipboard manager takes the offer in ~20-35ms.

        Measured on this desktop with no keystroke sent at all, so process exit
        does not mean the focused app has pasted. Restoring on that signal races
        the app's own paste, which is why a busy app pastes the previously
        copied text on an otherwise successful dictation.
        """
        harness = _Harness(consume_after=0.02)
        ok = _run(
            harness,
            settle_seconds=0.0,
            consume_timeout=0.5,
            key_delay_ms=0,
            grace_seconds=1.0,
        )
        self.assertTrue(ok)
        events = dict(harness.events[::-1])
        chord_at = min(at for name, at in harness.events if name == "chord")
        self.assertGreaterEqual(
            events["restore"] - chord_at,
            paste_mod._MIN_HOLD_AFTER_CHORD_SECONDS,
            "clipboard was restored while the app's paste was still in flight",
        )


class ClipboardOwnershipTests(unittest.TestCase):
    """A chord may only be sent once the dictation is *really* on the clipboard.

    `wl-copy` forks after taking the selection (measured on this desktop,
    wl-clipboard 2.2.1), so the spawned process exiting is the moment ownership
    is established -- ~32ms idle, but 4/20 trials under load took longer than
    the blind 120ms window the daemon used to wait. A chord sent before that
    pastes whatever the clipboard held before: the user's previously copied
    text, logged as a successful paste.
    """

    def test_chord_waits_until_wl_copy_owns_the_selection(self) -> None:
        harness = _Harness(consume_after=0.35)  # slow ownership, e.g. a loaded box
        ok = _run(
            harness,
            settle_seconds=0.0,
            consume_timeout=0.5,
            key_delay_ms=0,
            grace_seconds=1.0,
        )
        self.assertTrue(ok)
        chords = [at for name, at in harness.events if name == "chord"]
        self.assertTrue(chords, "expected a paste chord")
        self.assertGreaterEqual(
            chords[0],
            0.35,
            "chord fired before wl-copy owned the selection -- the app pastes "
            "the PREVIOUSLY COPIED text, not the dictation",
        )

    def test_no_chord_is_sent_when_ownership_never_lands(self) -> None:
        """Better to drop the dictation than to paste the user's old clipboard."""
        harness = _Harness(consume_after=None)
        with patch.object(paste_mod, "_CLIPBOARD_OWNERSHIP_TIMEOUT_SECONDS", 0.2):
            ok = _run(
                harness,
                settle_seconds=0.0,
                consume_timeout=0.15,
                key_delay_ms=0,
                grace_seconds=0.2,
            )
        self.assertFalse(ok)
        self.assertNotIn(
            "chord",
            harness.names(),
            "sent a paste chord that could only paste stale clipboard contents",
        )


if __name__ == "__main__":
    unittest.main()
