"""Generate the 1200x630 OG card for tryfurqan.com.

The card mirrors the editorial system from bayyinah.dev's OG card:
warm vellum panel on a dark plate, Source Serif 4 headline with an
italic gold accent, JetBrains Mono meta strip, single Inter footer.

Run:
    python scripts/generate_og_card.py
Output:
    static/og-tryfurqan.png  (1200 x 630, ~70 KiB)
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "og-tryfurqan.png"

W, H = 1200, 630

# Palette pulled from the landing CSS so the OG card and the page
# read as the same publication.
BG = (15, 17, 21)
RULE = (38, 44, 54)
VELLUM = (232, 228, 216)
INK = (232, 228, 216)
INK_2 = (181, 176, 162)
MUTED = (111, 118, 132)
LAMP = (244, 213, 138)


def _font(size: int, *, italic: bool = False, mono: bool = False, weight: str = "regular") -> ImageFont.FreeTypeFont:
    """Best-effort font loader; falls back to default if specific faces are missing."""
    candidates = []
    if mono:
        candidates += [
            "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        ]
    elif italic and weight == "medium":
        candidates += [
            "/usr/share/fonts/truetype/source-serif/SourceSerif4-MediumItalic.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
        ]
    elif italic:
        candidates += [
            "/usr/share/fonts/truetype/source-serif/SourceSerif4-Italic.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
        ]
    elif weight == "medium":
        candidates += [
            "/usr/share/fonts/truetype/source-serif/SourceSerif4-Medium.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        ]
    else:
        candidates += [
            "/usr/share/fonts/truetype/source-serif/SourceSerif4-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def main() -> int:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Lamp glow strip at top of vellum panel
    panel_x0, panel_y0 = 90, 90
    panel_x1, panel_y1 = W - 90, H - 90

    # Dark plate already filled. Now draw a thin lamp rule across the top.
    draw.rectangle((0, 0, W, 4), fill=LAMP)

    # Section mark (uppercase, lamp colour, mono small caps look)
    sec_font = _font(20, mono=True)
    draw.text((panel_x0, panel_y0), "\u00a7 FURQAN  \u00b7  HONEST BY CONSTRUCTION",
              font=sec_font, fill=LAMP)

    # Headline (Source Serif 4 medium, vellum, with italic gold accent)
    headline_font = _font(60, weight="medium")
    headline_italic = _font(60, italic=True, weight="medium")

    # Three balanced lines, each safely inside the 1020px panel width.
    line1_a = "A type-checker for code"
    line2_a = "that "
    line2_b = "promises more "
    line2_c = "than it can"
    line3 = "actually deliver."

    y = panel_y0 + 56
    draw.text((panel_x0, y), line1_a, font=headline_font, fill=VELLUM)
    y += 78

    # Mixed line: roman + italic gold + roman.
    a_w = draw.textlength(line2_a, font=headline_font)
    b_w = draw.textlength(line2_b, font=headline_italic)
    draw.text((panel_x0, y), line2_a, font=headline_font, fill=VELLUM)
    draw.text((panel_x0 + a_w, y), line2_b, font=headline_italic, fill=LAMP)
    draw.text((panel_x0 + a_w + b_w, y), line2_c, font=headline_font, fill=VELLUM)
    y += 78

    draw.text((panel_x0, y), line3, font=headline_font, fill=VELLUM)
    y += 90

    # Lede / subtitle (Source Serif 4 italic, dim ink)
    lede_font = _font(24, italic=True)
    draw.text((panel_x0, y),
              "Refuses signatures wider than the body delivers.",
              font=lede_font, fill=INK_2)
    y += 34
    draw.text((panel_x0, y),
              "Compile-time. Deterministic. Zero runtime dependencies.",
              font=lede_font, fill=INK_2)

    # Bottom meta row: tryfurqan.com  v0.10.1  527 tests  Phase 2
    meta_font = _font(20, mono=True)
    meta_y = panel_y1 - 32

    # Hairline rule above the meta strip
    draw.rectangle((panel_x0, meta_y - 18, panel_x1, meta_y - 17), fill=RULE)

    left = "TRYFURQAN.COM"
    right = "v0.10.1   \u00b7   527 TESTS   \u00b7   PHASE 2"

    draw.text((panel_x0, meta_y), left, font=meta_font, fill=LAMP)
    right_w = draw.textlength(right, font=meta_font)
    draw.text((panel_x1 - right_w, meta_y), right, font=meta_font, fill=MUTED)

    img.save(OUT, format="PNG", optimize=True)
    print(f"Wrote {OUT}  ({OUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
