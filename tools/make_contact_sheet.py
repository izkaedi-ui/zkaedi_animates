#!/usr/bin/env python3
"""
make_contact_sheet.py
Rasterizes each symbol from the sprite lib (with bloom/filter) into a 3x2 montage.
Emulates non-scaling-stroke. Labels with id + h0. Base #04030a, cyan/mag accents.
Usage: python tools/make_contact_sheet.py out/sprites/ml_training_lifecycle_sprites.svg tools/example_scenario.json
"""
import re
import sys
import io
import json
import cairosvg
from PIL import Image, ImageDraw, ImageFont

def emulate_nonscaling(body, vbw, card):
    factor = vbw / card
    def repl(m):
        return f'stroke-width="{float(m.group(1)) * factor:.4f}"'
    out = []
    for chunk in re.split(r'(<path\b[^>]*?/>)', body):
        if 'non-scaling-stroke' in chunk:
            chunk = re.sub(r'stroke-width="([0-9.]+)"', repl, chunk)
        out.append(chunk)
    return ''.join(out)

def raster_symbol(defs, vb, body, card=256):
    field = re.sub(r"<g>.*?</g>", "", body, flags=re.S)  # strip tracers for pure field? no, keep full for showcase
    # For preview keep full including tracers and titles? but to match field focus, keep as is but render full symbol
    field = re.sub(r"<text\b.*?</text>", "", field, flags=re.S)  # optional: drop title for clean field view
    vbw = float(vb.split()[2])
    field = emulate_nonscaling(field, vbw, card)
    # include full defs for filters/grads + the symbol content as root graphic
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}">{defs}{body}</svg>'
    png = cairosvg.svg2png(bytestring=svg.encode(), output_width=card, output_height=card)
    return Image.open(io.BytesIO(png)).convert("RGBA")

def main():
    if len(sys.argv) < 2:
        print("usage: python tools/make_contact_sheet.py <sprites.svg> [scenario.json]")
        sys.exit(1)
    svg_path = sys.argv[1]
    scen_path = sys.argv[2] if len(sys.argv) > 2 else None

    src = open(svg_path, encoding="utf-8").read()
    defs_m = re.search(r"<defs>.*?</defs>", src, re.S)
    defs = defs_m.group(0) if defs_m else ""
    syms = re.findall(r'<symbol id="([^"]+)" viewBox="([^"]+)">(.*?)</symbol>', src, re.S)

    hmap = {}
    if scen_path:
        data = json.load(open(scen_path, encoding="utf-8"))
        for n in data.get("nodes", []):
            for k in ("h0", "H0", "energy"):
                if k in n:
                    hmap[n["id"]] = float(n[k])
                    break

    # 3x2 grid: 3 cols, 2 rows
    card = 256
    gap = 12
    label_h = 28
    cols, rows = 3, 2
    W = cols * card + (cols-1) * gap
    H = rows * (card + label_h) + (rows-1) * gap
    sheet = Image.new("RGB", (W, H), "#04030a")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 14)
    except:
        font = ImageFont.load_default()

    positions = []
    for r in range(rows):
        for c in range(cols):
            positions.append( (c * (card + gap), r * (card + label_h + gap)) )

    for idx, (sid, vb, body) in enumerate(syms):
        if idx >= len(positions): break
        x, y = positions[idx]
        im = raster_symbol(defs, vb, body, card)
        sheet.paste(im, (x, y), im)
        # label
        h = hmap.get(sid, 0.0)
        label = f"{sid.upper()}  H0={h:.2f}"
        # draw label below
        lx = x + 4
        ly = y + card + 4
        # accent color
        col = "#00ffff" if h < 0.6 else "#ff007f"
        draw.text((lx, ly), label, fill=col, font=font)

    out_path = "showcase/preview.png"
    sheet.save(out_path, "PNG")
    print(f"wrote {out_path} ({W}x{H})")

if __name__ == "__main__":
    main()