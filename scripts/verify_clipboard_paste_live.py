#!/usr/bin/env python3
"""Live A/B of the real paste path against the real Wayland clipboard.

Instead of pressing Ctrl+Shift+V (which would type into the user's window), the
chord is replaced by a probe that reads the clipboard AT THAT EXACT MOMENT --
which is what the focused app would have pasted. Anything other than the
dictation is the bug the user reported.
"""
import asyncio, os, subprocess, sys, time
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mywhispr import paste as paste_mod  # noqa: E402

DICTATION = "THE DICTATED WORDS"
STALE = "PREVIOUSLY COPIED TEXT"


def set_clip(text: str) -> None:
    subprocess.run(["wl-copy", "--type", "text/plain;charset=utf-8"],
                   input=text.encode(), timeout=5)


def read_clip() -> str:
    try:
        p = subprocess.run(["wl-paste", "--no-newline"], capture_output=True, timeout=3)
        return p.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return "<TIMEOUT>"


async def run_trials(label: str, trials: int, legacy: bool) -> tuple[int, int]:
    """Returns (pasted_dictation, pasted_something_else)."""
    good = bad = 0
    for i in range(trials):
        set_clip(STALE)                     # the user's own clipboard
        await asyncio.sleep(0.15)
        seen: list[str] = []

        async def probe_chord(_chord, *, delay_ms=None):
            seen.append(read_clip())        # what the app would paste right now
            return True

        async def legacy_ownership_wait(_proc, *, timeout, kill_on_timeout=True):
            # Pre-fix behaviour: never wait for ownership, just claim success.
            return True

        patches = [patch.object(paste_mod, "_ydotool_keys", probe_chord)]
        if legacy:
            # Restore the old blind 120ms window instead of the ownership wait.
            patches.append(patch.object(paste_mod, "_wait_wl_copy", legacy_ownership_wait))
        for p in patches:
            p.start()
        try:
            paste_mod._pending_release = None
            await paste_mod._wayland_clipboard_paste(
                DICTATION, settle_seconds=0.0, consume_timeout=0.8,
                key_delay_ms=0, grace_seconds=0.3,
            )
            release = paste_mod._pending_release
            if release is not None:
                try:
                    await release.task
                except Exception:
                    pass
        finally:
            for p in patches:
                p.stop()

        got = seen[0] if seen else "<NO CHORD SENT>"
        if got == DICTATION:
            good += 1
        else:
            bad += 1
            print(f"  {label} trial {i:2d}: WOULD PASTE {got[:40]!r}", flush=True)
    return good, bad


async def main() -> None:
    saved = read_clip()
    workers = [subprocess.Popen([sys.executable, "-c",
               "import time\nt=time.time()\nwhile time.time()-t<220: pass"])
               for _ in range(os.cpu_count() or 8)]
    await asyncio.sleep(1.0)
    try:
        n = 60
        print(f"=== OLD behaviour (blind 120ms window), {n} trials under load ===")
        og, ob = await run_trials("OLD", n, legacy=True)
        print(f"=== NEW behaviour (wait for ownership), {n} trials under load ===")
        ng, nb = await run_trials("NEW", n, legacy=False)
    finally:
        for w in workers:
            w.kill()
        set_clip(saved)
    print(f"\nOLD: dictation {og}/{og+ob}   STALE/WRONG {ob}/{og+ob}")
    print(f"NEW: dictation {ng}/{ng+nb}   STALE/WRONG {nb}/{ng+nb}")
    print("clipboard restored")


asyncio.run(main())
