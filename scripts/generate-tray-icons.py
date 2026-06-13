"""Generate the Windows tray .ico assets (idle / recording / busy).

Pure stdlib: draws a modern rounded app tile with a microphone glyph, supersamples
for anti-aliasing, and packs PNG-compressed ICO files into assets/.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
SIZES = [16, 20, 24, 32, 48, 64]
SS = 4  # supersampling factor


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _sd_segment(px, py, ax, ay, bx, by):
    """Distance from point to segment."""
    abx, aby = bx - ax, by - ay
    apx, apy = px - ax, py - ay
    denom = abx * abx + aby * aby or 1e-9
    t = _clamp((apx * abx + apy * aby) / denom, 0.0, 1.0)
    dx, dy = apx - t * abx, apy - t * aby
    return (dx * dx + dy * dy) ** 0.5


def _mic_alpha(x, y):
    """Coverage of the mic glyph at normalized (x, y) in [0,1]^2."""
    # Capsule body
    d = _sd_segment(x, y, 0.50, 0.27, 0.50, 0.43) - 0.155
    a = d < 0
    # Holder: lower half ring around (0.5, 0.47)
    r = ((x - 0.50) ** 2 + (y - 0.47) ** 2) ** 0.5
    if y >= 0.47 and abs(r - 0.255) < 0.045:
        a = True
    # Stem
    if 0.455 <= x <= 0.545 and 0.715 <= y <= 0.83:
        a = True
    # Base bar (capsule)
    if _sd_segment(x, y, 0.345, 0.855, 0.655, 0.855) - 0.045 < 0:
        a = True
    return a


def _rounded_tile_alpha(x, y):
    """Coverage of a rounded square tile at normalized (x, y) in [0,1]^2."""
    left, top, right, bottom = 0.08, 0.08, 0.92, 0.92
    radius = 0.23
    cx = _clamp(x, left + radius, right - radius)
    cy = _clamp(y, top + radius, bottom - radius)
    return ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 <= radius


def render(size, glyph_rgb, *, bg_rgb=(48, 150, 160), dot_rgb=None):
    """Render RGBA bytes (top-down rows) of the tray tile."""
    out = bytearray()
    for j in range(size):
        for i in range(size):
            ar = ag = ab = aa = 0
            for sj in range(SS):
                for si in range(SS):
                    x = (i + (si + 0.5) / SS) / size
                    y = (j + (sj + 0.5) / SS) / size
                    rgb = None
                    if _rounded_tile_alpha(x, y):
                        rgb = bg_rgb
                    if _mic_alpha(x, y):
                        rgb = glyph_rgb
                    if dot_rgb is not None:
                        # State dot at top-right with a white ring so it reads
                        # on both dark and light taskbars.
                        d = ((x - 0.79) ** 2 + (y - 0.21) ** 2) ** 0.5
                        if d < 0.205:
                            rgb = (255, 255, 255)
                        if d < 0.145:
                            rgb = dot_rgb
                    if rgb is None:
                        continue
                    ar += rgb[0]
                    ag += rgb[1]
                    ab += rgb[2]
                    aa += 1
            total = SS * SS
            if aa:
                out += bytes((ar // aa, ag // aa, ab // aa, int(255 * aa / total)))
            else:
                out += b"\x00\x00\x00\x00"
    return bytes(out)


def png_encode(size, rgba):
    def chunk(tag, data):
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b"".join(
        b"\x00" + rgba[j * size * 4 : (j + 1) * size * 4] for j in range(size)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def ico_encode(images):
    """images: list of (size, png_bytes)."""
    header = struct.pack("<HHH", 0, 1, len(images))
    entries = b""
    blobs = b""
    offset = len(header) + 16 * len(images)
    for size, png in images:
        entries += struct.pack(
            "<BBBBHHII",
            size if size < 256 else 0,
            size if size < 256 else 0,
            0, 0, 1, 32, len(png), offset,
        )
        blobs += png
        offset += len(png)
    return header + entries + blobs


def build(name, rgb, dot_rgb=None):
    images = [(s, png_encode(s, render(s, rgb, dot_rgb=dot_rgb))) for s in SIZES]
    path = ASSETS / name
    path.write_bytes(ico_encode(images))
    print(f"wrote {path} ({path.stat().st_size} bytes)")


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    build("tray-idle.ico", (255, 255, 255))
    build("tray-recording.ico", (255, 255, 255), dot_rgb=(255, 70, 70))
    build("tray-busy.ico", (255, 255, 255), dot_rgb=(255, 195, 64))
    build("mywhispr.ico", (255, 255, 255))


if __name__ == "__main__":
    main()
