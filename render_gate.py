#!/usr/bin/env python3
"""
render_gate.py (v2) — browser-truth visibility + energy-monotonicity gate.

Two fixes over v1:
  1. cairosvg ignores vector-effect="non-scaling-stroke"; v1 therefore measured a
     ~0.4px line and under-reported real (Chrome) visibility ~3x, producing false FAILs.
     v2 emulates non-scaling-stroke by pre-scaling those strokes to their on-screen px
     before rasterizing, so the luminance reflects what a browser actually paints.
  2. Energy monotonicity is checked on LUMINANCE (density x opacity), not raw segment
     count. Segment count has a hard grid ceiling, so lifting low-energy nodes to
     "visible" saturates the count and inverts it — segment count and floor-visibility
     are in genuine conflict. Luminance is the thing humans see and stays monotone.

Usage:
    pip install cairosvg pillow --break-system-packages
    python render_gate.py <sheet>_sprites.svg [<scenario>.json] [--card 240] [--floor 6.0]

If the scenario JSON is given, also asserts luminance is non-decreasing in h0.
Exit 0 = all visible (and monotone if JSON given); exit 1 = a node is blank or out of order.
"""
import re, sys, io, json, argparse
import cairosvg
from PIL import Image


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


def symbol_luminance(defs, vb, body, card):
    field = re.sub(r"<g>.*?</g>", "", body, flags=re.S)
    field = re.sub(r"<text\b.*?</text>", "", field, flags=re.S)
    vbw = float(vb.split()[2])
    field = emulate_nonscaling(field, vbw, card)
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}">{defs}{field}</svg>'
    png = cairosvg.svg2png(bytestring=svg.encode(), output_width=card, output_height=card)
    im = Image.open(io.BytesIO(png)).convert("L")
    px = list(im.getdata())
    return sum(px) / len(px) - min(px)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("svg")
    ap.add_argument("scenario", nargs="?")
    ap.add_argument("--card", type=int, default=240)
    ap.add_argument("--floor", type=float, default=6.0)
    a = ap.parse_args()

    src = open(a.svg, encoding="utf-8").read()
    defs = re.search(r"<defs>.*?</defs>", src, re.S)
    defs = defs.group(0) if defs else ""
    syms = re.findall(r'<symbol id="([^"]+)" viewBox="([^"]+)">(.*?)</symbol>', src, re.S)
    if not syms:
        print("no <symbol> found"); sys.exit(1)

    h0 = {}
    if a.scenario:
        data = json.load(open(a.scenario, encoding="utf-8"))
        nodes = data.get("nodes", data if isinstance(data, list) else [])
        for n in nodes:
            for k in ("h0", "H0", "energy"):
                if k in n: h0[n["id"]] = float(n[k]); break

    rows = [(h0.get(sid), sid, symbol_luminance(defs, vb, body, a.card)) for sid, vb, body in syms]

    print(f"{'h0':>5} {'id':14}{'lum':>8}  result   (card={a.card}px floor={a.floor})")
    fails = []
    for hv, sid, lum in rows:
        ok = lum >= a.floor
        if not ok: fails.append(sid)
        hs = f"{hv:5.2f}" if hv is not None else "  -  "
        print(f"{hs} {sid:14}{lum:8.2f}  {'PASS' if ok else 'FAIL'}")

    mono = True
    if h0 and all(r[0] is not None for r in rows):
        ordered = sorted(rows, key=lambda r: r[0])
        mono = all(ordered[i][2] <= ordered[i+1][2] for i in range(len(ordered)-1))

    vis_ok = not fails
    print(f"\nvisibility: {'PASS' if vis_ok else 'FAIL'}" + (f"  blank: {fails}" if fails else ""))
    if h0:
        print(f"monotonic:  {'PASS' if mono else 'FAIL'}  (luminance vs h0)")
    sys.exit(0 if (vis_ok and mono) else 1)


if __name__ == "__main__":
    main()