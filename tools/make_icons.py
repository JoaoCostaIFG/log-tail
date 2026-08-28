#!/usr/bin/env python3
"""Regenerate the favicon PNGs in static/ from the same letterform geometry
as favicon.svg (black square, white 'LT'). Stdlib only; run manually."""

import struct
import zlib
from pathlib import Path

RECTS = [(6, 8, 3, 16), (6, 21, 9, 3), (19, 8, 8, 3), (21.5, 8, 3, 16)]
STATIC = Path(__file__).resolve().parent.parent / "static"


def pixel(x, y, scale):
    X, Y = x / scale, y / scale
    if any(rx <= X < rx + rw and ry <= Y < ry + rh for rx, ry, rw, rh in RECTS):
        return (255, 255, 255)
    return (0, 0, 0)


def write_png(path, size):
    rows = bytearray()
    for y in range(size):
        rows.append(0)  # filter: none
        for x in range(size):
            rows.extend(pixel(x, y, size / 32))
    data = zlib.compress(bytes(rows), 9)

    def chunk(tag, payload):
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", data)
    png += chunk(b"IEND", b"")
    path.write_bytes(png)
    print(f"wrote {path} ({len(png)} bytes)")


if __name__ == "__main__":
    write_png(STATIC / "favicon-32.png", 32)
    write_png(STATIC / "apple-touch-icon.png", 180)
