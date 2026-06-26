#!/usr/bin/env python3
"""
PRIME Sprite-Sheet Generator
Deterministic SVG energy-field sprite sheets from scenario JSON.
Usage: python tools/prime_sprite_gen.py tools/example_scenario.json -o out/sprites/
All SVG emitted programmatically. Exactly one xmlns on root. No hand edits to outputs.
"""

import argparse
import json
import math
import os
import random
import re
import hashlib
from xml.sax.saxutils import escape as xml_escape


def stable_hash(s: str) -> int:
    """Stable integer hash for seeding (independent of PYTHONHASHSEED)."""
    return int(hashlib.md5(s.encode("utf-8")).hexdigest()[:8], 16)


def sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def compute_h0_field(width: int, height: int, step: int, h0: float, glyph: str):
    """Build base potential. Low-energy basin shaped by glyph description. Depth ~ h0."""
    nx = width // step + 1
    ny = height // step + 1
    field = [[0.0 for _ in range(nx)] for _ in range(ny)]
    cx, cy = width / 2.0, height / 2.0
    g = glyph.lower()
    for j in range(ny):
        for i in range(nx):
            x = i * step
            y = j * step
            dx = (x - cx) / (width / 2.0)
            dy = (y - cy) / (height / 2.0)
            r = math.sqrt(dx * dx + dy * dy)
            theta = math.atan2(dy, dx)
            # Default: quadratic bowl (low at center)
            val = r * r
            mod = 0.0
            # Glyph-driven modulations
            if "basin" in g or "central" in g:
                # Deepen center
                mod -= 2.2 * h0 * (1.0 - min(r, 1.0)) ** 2
            if "spiral" in g or "inspiraling" in g or "arms" in g:
                # Angular swirl + radial modulation
                swirl = 0.9 * math.sin(5.0 * theta + 6.0 * r) * (1.0 - min(r * 0.9, 1.0))
                mod += swirl * h0
            if "layered" in g or "grid" in g:
                # Grid / layers
                layer = 0.35 * math.sin(6.0 * dx) * math.sin(6.0 * dy) * h0
                mod += layer
            if "flow" in g or "outward" in g:
                # Directional bias
                flow = 0.45 * math.cos(theta) * (1.0 - min(r, 1.1))
                mod += flow * h0
            if "peak" in g:
                # Inverted for loss-like
                mod += 1.1 * h0 * (1.0 - r * r) if r < 1.0 else 0.0
            if "lattice" in g or "weights" in g:
                # Small high-freq
                lat = 0.25 * math.sin(11 * dx) * math.cos(11 * dy) * h0
                mod += lat
            if "activation" in g or "peak" in g:
                mod += 0.5 * math.sin(4 * r + 2 * theta) * h0
            val = val + mod
            # Boost absolute scale of potential so gradients are visible (quiver)
            val = val * 12.0 + (mod * 3.5)
            # Overall depth / contrast lifted strongly with h0 (monotonicity)
            val *= (0.18 + 0.82 * h0)
            field[j][i] = val
    return field, nx, ny


def evolve_field(H0, T: int, h0: float):
    """Canonical recursive Hamiltonian evolution. Returns final H."""
    H = [row[:] for row in H0]
    nx = len(H[0])
    ny = len(H)
    for _ in range(T):
        Hnew = [row[:] for row in H]
        for j in range(ny):
            for i in range(nx):
                h = H[j][i]
                s = sigmoid(0.3 * h)
                noise_std = 1.0 + 0.1 * abs(h)
                noise = random.gauss(0.0, noise_std)
                Hnew[j][i] = H0[j][i] + 0.4 * h * s + 0.05 * noise
        H = Hnew
    return H


def finite_grad(H, i: int, j: int, step: float):
    """Central difference gradient (dh/dx, dh/dy)."""
    ny = len(H)
    nx = len(H[0])
    hx = 0.0
    if 0 < i < nx - 1:
        hx = (H[j][i + 1] - H[j][i - 1]) / (2.0 * step)
    elif i == 0 and nx > 1:
        hx = (H[j][i + 1] - H[j][i]) / step
    elif i == nx - 1 and nx > 1:
        hx = (H[j][i] - H[j][i - 1]) / step
    hy = 0.0
    if 0 < j < ny - 1:
        hy = (H[j + 1][i] - H[j - 1][i]) / (2.0 * step)
    elif j == 0 and ny > 1:
        hy = (H[j + 1][i] - H[j][i]) / step
    elif j == ny - 1 and ny > 1:
        hy = (H[j][i] - H[j - 1][i]) / step
    return hx, hy


def generate_motion_d(glyph: str, cx: float = 400.0, cy: float = 400.0, h0: float = 0.5) -> str:
    """Closed path for tracer animation. Glyph modulates shape."""
    g = glyph.lower()
    pts = []
    n = 48
    for k in range(n):
        ang = 2.0 * math.pi * k / n
        r = 155.0
        if "basin" in g or "spiral" in g or "inspiraling" in g:
            r = 120.0 + 55.0 * math.sin(3.0 * ang) + 18.0 * math.cos(7.0 * ang) * h0
        elif "layered" in g or "grid" in g:
            r = 140.0 + 35.0 * math.sin(4.0 * ang) * math.cos(2.0 * ang)
        elif "peak" in g:
            r = 105.0 + 40.0 * math.sin(5.0 * ang)
        elif "flow" in g or "outward" in g:
            r = 130.0 + 45.0 * math.cos(ang)
        else:
            r = 135.0 + 30.0 * math.sin(2.0 * ang)
        # slight inward bias for higher h0
        r -= 12.0 * h0 * (0.5 + 0.5 * math.sin(2.0 * ang))
        x = cx + r * math.cos(ang)
        y = cy + r * 0.82 * math.sin(ang)
        pts.append(f"{x:.1f},{y:.1f}")
    return "M " + " L ".join(pts) + " Z"


def build_sprite_svg(scenario: str, seed: int, palette: list, nodes: list) -> str:
    """Emit the full sprite library SVG. Exactly one xmlns on <svg>. No duplicates."""
    slug = re.sub(r"[^a-z0-9]+", "_", scenario.lower()).strip("_")
    width, height, step = 800, 800, 16

    # Collect all parts
    motion_defs = []
    symbols = []

    for node in nodes:
        nid = node["id"]
        title = node["title"]
        h0 = float(node["h0"])
        glyph = node.get("glyph", "")
        tracers = node.get("tracers", ["FLOW"])

        node_seed = seed + stable_hash(nid)
        random.seed(node_seed)

        T = round(4 + 8 * h0)
        H0, nx, ny = compute_h0_field(width, height, step, h0, glyph)
        H = evolve_field(H0, T, h0)

        # Precompute all grads + intensities for culling + opacity
        arrows = []
        max_mag = 1e-9
        for j in range(ny):
            for i in range(nx):
                gx, gy = finite_grad(H, i, j, step)
                mag = math.sqrt(gx * gx + gy * gy)
                if mag > max_mag:
                    max_mag = mag
        if max_mag < 1e-9:
            max_mag = 1.0

        for j in range(ny):
            for i in range(nx):
                x = i * step
                y = j * step
                gx, gy = finite_grad(H, i, j, step)
                mag = math.sqrt(gx * gx + gy * gy)
                # -grad direction (downhill)
                if mag < 1e-6:
                    ux, uy = 0.0, -1.0
                else:
                    ux = -gx / mag
                    uy = -gy / mag
                L = 11.0 + 2.5 * h0
                x2 = x + ux * L
                y2 = y + uy * L
                # Raw mag scaled by h0 for monotonicity: higher h0 => larger inten => more segs + higher op
                scale = 3.8 + 2.4 * h0
                inten = min(1.0, mag * scale)
                # Lower cull threshold at higher h0 => strictly more visible segments
                cull = 0.14 - 0.10 * h0
                op = max(0.22, min(0.98, 0.34 + 0.5 * inten + 0.12 * h0))
                if inten > cull:
                    arrows.append((x, y, x2, y2, round(op, 4)))

        # Motion path for tracers
        motion_d = generate_motion_d(glyph, 400.0, 400.0, h0)
        motion_id = f"motion-{nid}"
        motion_defs.append(
            f'  <path id="{motion_id}" d="{motion_d}" fill="none" />'
        )

        # Build symbol content
        sym_lines = []
        # bg
        sym_lines.append(
            f'    <rect x="0" y="0" width="{width}" height="{height}" fill="#05070f" />'
        )
        # quiver arrows wrapped ONLY in fieldGlow; tracers MUST remain plain <g> with no attrs
        sym_lines.append('    <g filter="url(#fieldGlow)">')
        for (x, y, x2, y2, op) in arrows:
            d = f"M {x:.1f} {y:.1f} L {x2:.1f} {y2:.1f}"
            sym_lines.append(
                f'    <path d="{d}" stroke="url(#glowGrad)" stroke-width="1.3" vector-effect="non-scaling-stroke" opacity="{op:.3f}" />'
            )
        sym_lines.append('    </g>')
        # tracers group(s)
        dur = max(2.2, round(7.0 - 4.0 * h0, 2))
        for idx, tr in enumerate(tracers):
            begin = f"{(idx * 0.9) % 3.5:.2f}s"
            tr_esc = xml_escape(tr)
            sym_lines.append('    <g>')
            sym_lines.append(
                f'      <animateMotion dur="{dur}s" begin="{begin}" repeatCount="indefinite">'
            )
            sym_lines.append(f'        <mpath href="#{motion_id}"/>')
            sym_lines.append('      </animateMotion>')
            sym_lines.append('      <circle cx="0" cy="0" r="4.5" fill="#e0f8ff" opacity="0.92" />')
            sym_lines.append(
                f'      <text x="7" y="4" font-family="monospace" font-size="11" fill="#aaddff">{tr_esc}</text>'
            )
            sym_lines.append('    </g>')

        # title
        title_esc = xml_escape(title)
        p0 = palette[0] if palette else "#ff007f"
        sym_lines.append(
            f'    <text x="30" y="38" font-family="monospace" font-size="13" fill="{p0}" font-weight="600">🔱 {title_esc}</text>'
        )
        # frame
        sym_lines.append(
            f'    <rect x="15" y="15" width="770" height="770" fill="none" stroke="#112244" stroke-width="1.5" />'
        )

        symbols.append(
            f'  <symbol id="{nid}" viewBox="0 0 {width} {height}">\n' + "\n".join(sym_lines) + "\n  </symbol>"
        )

    # Gradient stops from palette
    p0, p1 = (palette + ["#00ffff", "#ff007f"])[:2]
    grad = (
        '  <linearGradient id="glowGrad" x1="0%" y1="0%" x2="0%" y2="100%">\n'
        f'    <stop offset="0%" stop-color="{p0}" stop-opacity="0.95"/>\n'
        f'    <stop offset="100%" stop-color="{p1}" stop-opacity="0.65"/>\n'
        "  </linearGradient>"
    )
    field_glow = (
        '  <filter id="fieldGlow" x="-50%" y="-50%" width="200%" height="200%">\n'
        '    <feGaussianBlur in="SourceGraphic" stdDeviation="2.5" result="coloredBlur"/>\n'
        '    <feMerge>\n'
        '      <feMergeNode in="coloredBlur"/>\n'
        '      <feMergeNode in="SourceGraphic"/>\n'
        '    </feMerge>\n'
        '  </filter>'
    )

    # Assemble final SVG - EXACTLY ONE xmlns on root, no duplicates anywhere
    svg_parts = []
    svg_parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    svg_parts.append(f'<!-- PRIME sprites: scenario="{scenario}" seed={seed} nodes={len(nodes)} -->')
    svg_parts.append('<svg xmlns="http://www.w3.org/2000/svg" style="display:none" width="0" height="0">')
    svg_parts.append("  <defs>")
    svg_parts.append(grad)
    svg_parts.append(field_glow)
    svg_parts.extend(motion_defs)
    svg_parts.append("  </defs>")
    svg_parts.extend(symbols)
    svg_parts.append("</svg>")

    return "\n".join(svg_parts)


def build_viewer_html(scenario: str, nodes: list, svg_library: str) -> str:
    """Showcase viewer: inlines display:none lib (1 xmlns), exactly 1 static <use> per symbol (G3 safe).
    Aesthetic: #04030a base, #00ffff/#ff007f, mono UPPER, glows, no emoji but 🔱, respects reduced-motion.
    Fullscreen via JS cloneNode of card svg (no extra static <use>). """
    slug = re.sub(r"[^a-z0-9]+", "_", scenario.lower()).strip("_")
    upper_scenario = scenario.upper()

    cards = []
    for node in nodes:
        nid = node["id"]
        t = xml_escape(node["title"])
        h = float(node["h0"])
        pct = int(h * 100)
        cards.append(f"""
    <div class="card" data-id="{nid}">
      <svg class="field" viewBox="0 0 800 800" preserveAspectRatio="xMidYMid meet"><use href="#{nid}" /></svg>
      <div class="info">
        <div class="title">{t}</div>
        <div class="meter" title="h0={h:.2f}"><div class="fill" style="width:{pct}%"></div></div>
        <div class="hval">H0 = {h:.2f}</div>
      </div>
    </div>""")
    cards_html = "\n".join(cards)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🔱 ZKAEDI PRIME // {upper_scenario}</title>
<style>
:root {{ --bg:#04030a; --c:#00ffff; --m:#ff007f; --g:#112233; }}
@media (prefers-reduced-motion: reduce) {{ .bg-grid, .card, .field {{ animation:none !important; transition:none !important; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:#ccd; font-family:monospace; overflow-x:hidden; }}
a {{ color:var(--c); text-decoration:none; }} a:hover {{ color:var(--m); }}
.hero {{ position:relative; padding:60px 20px 40px; text-align:center; border-bottom:1px solid #112; }}
.hero h1 {{ margin:0; font-size:28px; letter-spacing:6px; text-transform:uppercase; color:#fff; text-shadow:0 0 10px var(--c),0 0 20px var(--m); }}
.hero .sub {{ margin:8px 0 4px; font-size:13px; letter-spacing:3px; color:#99a; }}
.hero .pal {{ font-size:11px; color:#556; letter-spacing:2px; }}
.bg-grid {{ position:fixed; inset:0; z-index:-1; opacity:0.08; background:
  linear-gradient(transparent 50%, var(--c) 50%) 0 0 / 100% 24px,
  linear-gradient(90deg, transparent 50%, var(--c) 50%) 0 0 / 24px 100%;
  animation:drift 22s linear infinite; }}
@keyframes drift {{ to {{ background-position: 48px 48px, 48px 48px; }} }}
.showcase {{ max-width:1280px; margin:0 auto; padding:30px 20px; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:24px; }}
.card {{ background:#06050f; border:1px solid #1a1f2e; padding:8px; position:relative; overflow:hidden; cursor:pointer; transition: transform .15s, box-shadow .15s, filter .2s; }}
.card .field {{ width:100%; height:auto; display:block; background:#020206; filter:contrast(1.05); }}
.card .info {{ padding:10px 6px 4px; }}
.card .title {{ font-size:11px; letter-spacing:2px; text-transform:uppercase; color:#fff; margin-bottom:6px; }}
.card .meter {{ height:3px; background:#1a1f2e; position:relative; overflow:hidden; margin:4px 0; }}
.card .meter .fill {{ height:100%; background:linear-gradient(90deg,var(--m),var(--c)); transition:width .3s; }}
.card .hval {{ font-size:10px; color:#88a; letter-spacing:1px; }}
/* spotlight on hover */
.cards:hover .card {{ filter:brightness(.35) saturate(.6); }}
.cards:hover .card:hover {{ filter:brightness(1.15) saturate(1.1); transform:scale(1.01); box-shadow:0 0 0 1px var(--c), 0 0 18px -2px var(--c); z-index:2; }}
.overlay {{ position:fixed; inset:0; background:rgba(4,3,10,0.96); display:none; align-items:center; justify-content:center; z-index:999; }}
.overlay.active {{ display:flex; }}
.overlay svg {{ width:92vw; max-width:820px; height:auto; background:#020206; border:1px solid #112; box-shadow:0 0 40px -8px var(--m); }}
.overlay .close {{ position:absolute; top:20px; right:30px; color:#fff; font-size:13px; letter-spacing:2px; cursor:pointer; border:1px solid #334; padding:2px 10px; }}
</style>
</head>
<body>
<div class="bg-grid"></div>
<header class="hero">
  <h1>🔱 ZKAEDI PRIME // {upper_scenario}</h1>
  <div class="sub">DETERMINISTIC HAMILTONIAN ENERGY FIELDS • 16PX GRID • T=4+8H0 EVOLUTION</div>
  <div class="pal">ZKAEDI ↔ IDEAKZ</div>
</header>
<main class="showcase">
  <div class="cards" id="cards">
{cards_html}
  </div>
</main>
<footer style="text-align:center;padding:30px 10px 40px;font-size:10px;color:#445;letter-spacing:1px;">
  6 SYMBOLS • SEED 4488 • ONE <use> PER FIELD • GATES: XML • PROVENANCE • VIEWER • VISIBILITY • MONOTONIC
</footer>

<!-- Inlined display:none library: EXACTLY one xmlns on root; exactly one static <use> per symbol -->
<div class="lib" style="display:none">
{svg_library}
</div>

<div class="overlay" id="overlay"><div class="close" onclick="closeOverlay()">ESC / CLICK TO CLOSE</div></div>

<script>
const cards = document.querySelectorAll('.card');
const overlay = document.getElementById('overlay');

function openOverlay(el) {{
  overlay.innerHTML = '<div class="close" onclick="closeOverlay()">ESC / CLICK TO CLOSE</div>';
  const srcSvg = el.querySelector('.field');
  if (!srcSvg) return;
  const clone = srcSvg.cloneNode(true);
  clone.style.width = '92vw';
  clone.style.maxWidth = '820px';
  clone.style.height = 'auto';
  clone.style.background = '#020206';
  overlay.appendChild(clone);
  overlay.classList.add('active');
  overlay.onclick = (e) => {{ if (e.target === overlay) closeOverlay(); }};
  document.addEventListener('keydown', function esc(e){{ if(e.key==='Escape'){{ closeOverlay(); document.removeEventListener('keydown',esc); }} }}, {{once:true}});
}}
function closeOverlay() {{
  overlay.classList.remove('active');
  overlay.innerHTML = '<div class="close" onclick="closeOverlay()">ESC / CLICK TO CLOSE</div>';
}}
cards.forEach(c => c.addEventListener('click', () => openOverlay(c)));
document.addEventListener('keydown', e => {{ if(e.key.toLowerCase()==='f' && document.activeElement.tagName==='BODY') cards[0].click(); }});
</script>
</body>
</html>
"""
    return html


def main():
    parser = argparse.ArgumentParser(description="PRIME energy-field sprite generator")
    parser.add_argument("scenario", help="Path to scenario JSON")
    parser.add_argument("-o", "--output", default="out/sprites",
                        help="Output directory for sprites and viewer")
    args = parser.parse_args()

    with open(args.scenario, "r", encoding="utf-8") as f:
        data = json.load(f)

    scenario = data["scenario"]
    seed = int(data.get("seed", 42))
    palette = data.get("palette", ["#ff007f", "#00ffff"])
    nodes = data["nodes"]

    if not (4 <= len(nodes) <= 8):
        print(f"Warning: node count {len(nodes)} outside recommended 4-8 range.")

    os.makedirs(args.output, exist_ok=True)

    svg = build_sprite_svg(scenario, seed, palette, nodes)
    slug = re.sub(r"[^a-z0-9]+", "_", scenario.lower()).strip("_")
    svg_path = os.path.join(args.output, f"{slug}_sprites.svg")
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(svg)

    viewer = build_viewer_html(scenario, nodes, svg)
    html_path = os.path.join(args.output, f"{slug}_viewer.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(viewer)

    print(f"Generated: {svg_path}")
    print(f"Generated: {html_path}")
    print(f"Nodes: {len(nodes)} | seed: {seed}")


if __name__ == "__main__":
    main()
