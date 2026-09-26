#!/usr/bin/env python3
"""Does `wl-copy --paste-once` fork after taking the selection?

If the spawned process exits once ownership is established (leaving a child to
serve the data), then process-exit is an OWNERSHIP signal we can wait on --
race-free, no polling, no sleep.
"""
import subprocess, time, sys

def read_clip(timeout=3):
    try:
        p = subprocess.run(["wl-paste", "--no-newline"], capture_output=True, timeout=timeout)
        return p.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return "<TIMEOUT>"

saved = read_clip()
print(f"wl-copy version: {subprocess.run(['wl-copy','--version'],capture_output=True).stdout.decode().strip()}")

for i in range(6):
    token = f"FORKPROBE_{i}_{time.time_ns()}"
    t0 = time.monotonic()
    proc = subprocess.Popen(["wl-copy", "--paste-once", "--type", "text/plain;charset=utf-8"],
                            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    proc.stdin.write(token.encode()); proc.stdin.close()
    try:
        rc = proc.wait(timeout=3.0)
        exited_at = time.monotonic() - t0
    except subprocess.TimeoutExpired:
        rc, exited_at = None, float("nan")
    # Is our text actually the selection AT THE MOMENT the process exited?
    owned = read_clip()
    owned_at = time.monotonic() - t0
    match = "OURS" if owned == token else f"STALE({owned[:24]!r})"
    print(f"trial {i}: parent_exit rc={rc} at {exited_at*1000:7.1f}ms | "
          f"clipboard right after exit = {match} (read at {owned_at*1000:.1f}ms)")
    time.sleep(0.2)

subprocess.run(["wl-copy", "--type", "text/plain;charset=utf-8"], input=saved.encode(), timeout=5)
print("\nclipboard restored")
