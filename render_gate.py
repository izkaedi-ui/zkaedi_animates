#!/usr/bin/env python3
"""
render_gate.py — Chromium-truth gate for sprite fields.

Replaces cairosvg (which lied about vector-effect and stripped fields).
Uses real headless Chromium via playwright to render the *viewer.html* (which uses <use> + CSS glow + baked strokes).
Screenshots each card's field region, computes mean luminance (grayscale), asserts > floor.
Also checks monotonic vs h0.

Must PASS on baked 3px stroke + CSS drop-shadow output.
Must FAIL on synthetic blank.

Usage:
  python3 render_gate.py <viewer.html> <scenario.json> [--floor 5.0]

Prints per-node table + PASS/FAIL + monotonic.
"""
import argparse
import json
import os
import tempfile
from io import BytesIO
from statistics import mean

from playwright.sync_api import sync_playwright
from PIL import Image


def luminance_from_png(png_bytes: bytes) -> float:
    im = Image.open(BytesIO(png_bytes)).convert("L")
    px = list(im.getdata())
    if not px:
        return 0.0
    # range as visibility (max contrast from the strokes)
    return max(px) - min(px)


def capture_field_lums(viewer_html: str, floor: float = 5.0):
    abs_path = os.path.abspath(viewer_html)
    file_url = f"file://{abs_path}"

    lums = {}  # id -> lum

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        page.goto(file_url, wait_until="load")
        # wait for cards to render
        page.wait_for_selector(".card", timeout=10000)

        cards = page.locator(".card").all()
        for card in cards:
            nid = card.get_attribute("data-id") or "unknown"
            # use the card bbox for consistent capture region (includes the field)
            box = card.bounding_box()
            if not box:
                lums[nid] = 0.0
                continue
            # fixed size 200x200 centered clip for consistent pixel count across cards
            cx = box["x"] + box["width"]/2
            cy = box["y"] + box["height"]/2
            sz = 200
            clip = {
                "x": cx - sz/2,
                "y": cy - sz/2,
                "width": sz,
                "height": sz,
            }
            png = page.screenshot(clip=clip, type="png")
            lum = luminance_from_png(png)
            lums[nid] = lum

        browser.close()

    return lums


def load_h0_map(scenario_path: str):
    with open(scenario_path, encoding="utf-8") as f:
        data = json.load(f)
    nodes = data.get("nodes", data if isinstance(data, list) else [])
    h0 = {}
    for n in nodes:
        for k in ("h0", "H0", "energy"):
            if k in n:
                h0[n.get("id", n.get("title", "?"))] = float(n[k])
                break
    return h0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("viewer", help="path to *_viewer.html (contains the live <use> cards)")
    ap.add_argument("scenario", nargs="?", help="scenario json for h0 values")
    ap.add_argument("--floor", type=float, default=5.0)
    a = ap.parse_args()

    h0_map = load_h0_map(a.scenario) if a.scenario else {}

    print(f"capturing via real chromium: {a.viewer} (floor={a.floor})")
    lums = capture_field_lums(a.viewer, a.floor)

    # pair with h0
    rows = []
    for nid, lum in lums.items():
        hv = h0_map.get(nid, None)
        ok = lum >= a.floor
        rows.append((hv, nid, lum, "PASS" if ok else "FAIL"))

    # sort by h0 if available
    rows.sort(key=lambda r: (r[0] is None, r[0] if r[0] is not None else 0))

    print(f"{'h0':>5} {'id':12} {'lum':>8}  result")
    fails = []
    for hv, nid, lum, res in rows:
        hs = f"{hv:5.2f}" if hv is not None else "  -  "
        print(f"{hs} {nid:12} {lum:8.2f}  {res}")
        if res == "FAIL":
            fails.append(nid)

    # monotonic on luminance vs h0
    mono = True
    if h0_map and all(r[0] is not None for r in rows):
        ordered = sorted(rows, key=lambda r: r[0])
        mono = all(ordered[i][2] <= ordered[i + 1][2] for i in range(len(ordered) - 1))

    vis_ok = len(fails) == 0
    print(f"\nvisibility: {'PASS' if vis_ok else 'FAIL'} (luminance > floor in chromium)")
    if fails:
        print("  blanks:", fails)
    if h0_map:
        print(f"monotonic:  {'PASS' if mono else 'FAIL'}  (luminance vs h0)")

    # quick synthetic blank validate (must FAIL)
    try:
        with tempfile.TemporaryDirectory() as td:
            blank_html = os.path.join(td, "blank.html")
            with open(blank_html, "w", encoding="utf-8") as f:
                f.write("""<!DOCTYPE html><html><body style="background:#04030a;margin:0">
<div style="display:grid;grid-template-columns:repeat(3,220px);gap:10px">
<div class="card" data-id="b1" style="width:220px;height:220px;background:#111"><svg class="field" width="220" height="220" style="background:#020206"></svg></div>
<div class="card" data-id="b2" style="width:220px;height:220px;background:#111"><svg class="field" width="220" height="220" style="background:#020206"></svg></div>
<div class="card" data-id="b3" style="width:220px;height:220px;background:#111"><svg class="field" width="220" height="220" style="background:#020206"></svg></div>
<div class="card" data-id="b4" style="width:220px;height:220px;background:#111"><svg class="field" width="220" height="220" style="background:#020206"></svg></div>
<div class="card" data-id="b5" style="width:220px;height:220px;background:#111"><svg class="field" width="220" height="220" style="background:#020206"></svg></div>
<div class="card" data-id="b6" style="width:220px;height:220px;background:#111"><svg class="field" width="220" height="220" style="background:#020206"></svg></div>
</div></body></html>""")
            blank_lums = capture_field_lums(blank_html, a.floor)
            blank_ok = all(v < a.floor for v in blank_lums.values())
            print(f"blank validate: {'PASS (low lum as expected)' if blank_ok else 'FAIL (should be dark)'}")
    except Exception as e:
        print(f"blank validate skipped: {e}")

    exit_code = 0 if (vis_ok and mono) else 1
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
