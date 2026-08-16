#!/usr/bin/env python3
"""Local subject segmentation + solid-background compositor for pSquare.

Runs only on compute-01. Inputs/outputs are generated temporary paths supplied
by the pSquare controller; background colors are restricted to a tiny allowlist.
"""
from __future__ import annotations

import pathlib
import sys

from PIL import Image
from rembg import new_session, remove

ALLOWED = {
    "black": (0, 0, 0, 255),
    "white": (255, 255, 255, 255),
}


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: psquare_background.py INPUT OUTPUT black|white", file=sys.stderr)
        return 2

    src = pathlib.Path(sys.argv[1])
    dst = pathlib.Path(sys.argv[2])
    color_name = sys.argv[3].lower()
    if color_name not in ALLOWED:
        print("unsupported background color", file=sys.stderr)
        return 3
    if not src.is_file():
        print("input file missing", file=sys.stderr)
        return 4

    session = new_session("u2net_human_seg")
    image = Image.open(src).convert("RGBA")
    foreground = remove(image, session=session).convert("RGBA")
    background = Image.new("RGBA", foreground.size, ALLOWED[color_name])
    result = Image.alpha_composite(background, foreground).convert("RGB")
    dst.parent.mkdir(parents=True, exist_ok=True)
    result.save(dst, format="PNG", optimize=True)
    print(f"BACKGROUND_REPLACED={color_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
