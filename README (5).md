# ZKAEDI PRIME Blueprint Animator

A Claude Skill that turns **ZKAEDI PRIME blueprint SVGs** — SMIL-animated,
cyberpunk wireframe "card" graphics generated from edge-detected AI
images — into shareable media (GIF/MP4), gacha-style collection showcases,
PRIME-driven morphs between cards, audio-reactive drops, and X-ray
relief/curvature views.

Drop this skill into Claude (claude.ai, Claude Code, or any environment that
supports Claude Skills) and it will recognize blueprint SVGs by their header
comments (`ZKAEDI PRIME BLUEPRINT ENGINE`, `Subject:`, `Blueprint ID:`,
`Seed:`) and drive the full pipeline below automatically.

---

## What this does

| You ask for... | Skill produces |
|---|---|
| "animate this blueprint" / "make a GIF of this card" | Looping GIF + MP4 export |
| "catalog this collection" | `index.json` with subject, rarity, theme, blueprint ID, seed, dimensions per card, plus rarity/dimension stats |
| "build a pack opener" | Tap-to-reveal HTML widget with rarity-scaled flash |
| "make a gacha banner" | Side-by-side collection sheet with a shimmer sweep, single-row or multi-row grid |
| "X-ray / normal map / curvature view" | Normal map, curvature, ambient occlusion, depth bands, wireframe, heightmap, and composite relief views |
| "morph between these two cards" | A PRIME-recursion-driven crossfade SVG (feeds back into the GIF/MP4 exporter) |
| "build a full showcase page" | One self-contained HTML page combining banner + pack opener + X-ray toggle + morph centerpiece + live audio-reactive glow |
| "sync this to my Suno track" | Per-frame audio envelope (RMS + onsets + BPM + optional bass/mid/treble bands) for driving animation parameters |
| "split this into layers for a parallax card" | SVG re-grouped into background/midground/foreground `<g>` layers |

---

## Pipeline roles

The skill is organized into named roles, each with a script, defined
inputs/outputs, and pre/postconditions:

| Role | Script(s) | Input | Output |
|---|---|---|---|
| Cataloger | `collection_index.py`, `blueprint_meta.py` | Directory of `*.svg` | `index.json` (+ aggregate rarity/dimension stats) |
| Renderer | `capture_frames.py` | One SVG + dimensions | PNG frame sequence (headless Chromium) |
| Encoder | `encode_outputs.py` | PNG frames + dimensions | GIF and/or MP4 |
| Batch Coordinator | `batch_animate.py` | Directory of SVGs | Per-SVG GIF/MP4, Cataloger→Renderer→Encoder per file |
| Forensics Analyst | `curvature_map.py`, `assets/edge_forensics.html` | A rendered PNG | Normal map, curvature, AO, depth bands, wireframe, heightmap, composite |
| Morph Architect | `prime_morph.py` | Two SVGs (A, B) | SVG with PRIME-recursion-timed `<animate>` crossfade |
| Layer Splitter | `split_svg_layers.py` | One SVG | SVG re-grouped into `bgLayer`/`midLayer`/`fgLayer` |
| Showcase Builder | `build_pack_opener.py`, `build_gacha_banner.py`, `build_showcase.py` | `index.json` + GIFs (+ optional X-ray dir, morph GIF) | Self-contained HTML + `showcase_assets/` |
| Audio Analyst | `extract_audio_envelope.py` | Audio file | JSON envelope (`fps`, `envelope[]`, `onsets[]`, `bpm`, optional `bands`) |
| QA / Hardening Auditor | `tests/test_smoke.py` | Bundled fixtures | Pass/fail summary, 138 checks |

Every script in `scripts/` shares a small runtime helper (`zk_runtime.py`)
and follows a uniform **structured JSON contract**:

```json
{"ok": true,  "stage": "<script_name>", "result": {...}}
{"ok": false, "stage": "<script_name>", "reason": "<error_code>",
 "message": "...", "suggested_fix": "..."}
```

Common `reason` codes: `missing_file`, `invalid_svg_root`, `empty_file`,
`missing_svg_dimensions`, `missing_dependency`, `invalid_argument`,
`ffmpeg_failed`, `decode_failed`, `write_failed`, `no_input_files`,
`empty_collection`. Per-file failures in batch operations land in a
`skipped` list rather than aborting the whole run.

---

## Quick start

### 1. Animate a single blueprint (GIF + MP4)

```bash
# Get dimensions, subject, rarity, blueprint ID, seed, viewBox
python3 scripts/blueprint_meta.py path/to/blueprint.svg

# Capture animation frames (headless Chromium)
python3 scripts/capture_frames.py path/to/blueprint.svg work/ \
    --width <W> --height <H> --fps 12 --duration 4.0

# Encode to GIF (320px, 96-color, dithered-off) and MP4 (full-res)
python3 scripts/encode_outputs.py work/frames out/card \
    --src-width <W> --src-height <H> --fps 12 --formats gif,mp4
```

### 2. Batch-animate a whole drop

```bash
python3 scripts/batch_animate.py svgs/ batchout/ \
    --fps 12 --duration 4.0 --formats gif,mp4
```

### 3. Catalog a collection

```bash
python3 scripts/collection_index.py svgs/ --out index.json
# add --recursive to scan one subfolder per drop
```

`index.json` includes per-card `subject`, `theme`, `blueprint_id`, `seed`,
`width`/`height`, `viewbox`, `rarity_text`, and an aggregate `stats` block
(`rarity_counts` by tier, `dimensions` summary).

### 4. Build a full showcase page

```bash
python3 scripts/collection_index.py svgs/ --out index.json
python3 scripts/batch_animate.py svgs/ batchout/ --formats gif

# optional: X-ray relief maps for one card
python3 scripts/capture_frames.py card.svg frame_work/ --fps 1 --duration 1
python3 scripts/curvature_map.py frame_work/frames/frame_000.png xray_out/<stem> \
    --modes normal,curvature,ao,depth_bands,wireframe,heightmap,composite \
    --preset standard

# optional: PRIME morph between two cards
python3 scripts/prime_morph.py a.svg b.svg morph.svg --mode staggered --sigma 0 --global-seed 42
python3 scripts/capture_frames.py morph.svg morph_work/ --fps 12 --duration 3
python3 scripts/encode_outputs.py morph_work/frames morph --formats gif

python3 scripts/build_showcase.py index.json out/ \
    --gifs-dir batchout/ --xray-dir xray_out/ --morph-gif morph.gif \
    --title "ZKAEDI.AI — LEGENDARY COLLECTION"
```

Output is `out/zkaedi_showcase.html` + `out/showcase_assets/` — keep both
together. `--xray-dir` and `--morph-gif` are optional; the page degrades
gracefully without them.

---

## Script reference

### `blueprint_meta.py`
Extracts `subject`, `theme`, `blueprint_id`, `seed`, `width`, `height`,
`viewbox` (`{x, y, width, height}`), and `rarity_text` from a blueprint's
header comments and inline `<text>`. `--out meta.json` writes to a file
instead of stdout.

### `capture_frames.py`
Renders an SVG to a PNG frame sequence via headless Chromium (Playwright).
Embeds the SVG directly into the page (avoids `file://` CORS issues with
`fetch()`). Key flags:
- `--width/--height` (auto-detected from the SVG if omitted)
- `--fps`, `--duration`, `--settle-ms`
- `--background-color` (default `#0a0010`) — any CSS color value, validated
  against a CSS-injection guard

### `encode_outputs.py`
Encodes a frame sequence to GIF and/or MP4 via ffmpeg.
- `--formats gif,mp4`
- `--gif-max-width` (default 320), `--gif-colors` (default 96)
- `--mp4-max-width` (optional) — downscale MP4 same as GIF, aspect-preserving,
  even dimensions; rejects values larger than `--src-width` (no upscaling)

### `batch_animate.py`
Runs Cataloger → Renderer → Encoder across a directory of SVGs. Per-file
failures are recorded, not fatal.

### `collection_index.py`
Builds `index.json` from a directory of blueprint SVGs.
- `--pattern` (default `*.svg`)
- `--recursive` — scan subdirectories too
- `--out` — write to file (default stdout)
- Result includes `stats.rarity_counts` (SSR/SR/R/N/unrated tiers) and
  `stats.dimensions` (min/max width/height, unique aspect ratio count)

### `curvature_map.py`
Generates relief/X-ray views from a rendered PNG (numpy + Pillow).
- `--modes` (comma-separated, default `normal,curvature`): also supports
  `ao`, `depth_bands`, `wireframe`, `heightmap`, `composite`
- `--preset`: `subtle`, `standard`, `deep`, `engraved`, `sharp` — sets
  matched `--blur`/`--scale`; either can be overridden individually
- `ao`-specific: `--ao-radius` (default 8), `--ao-strength` (default 6.0)
- `depth_bands`-specific: `--bands` (default 6)
- `wireframe`-specific: `--wireframe-threshold` (percentile, default 70)
- Writes `<name>_<mode>.png` per requested mode, reported as `<mode>_map`

### `prime_morph.py`
Crossfades two blueprint SVGs using the canonical ZKAEDI PRIME recursion
(η=0.4, γ=0.3, β=0.1, σ=0.05 defaults). `--mode staggered` times each path's
reveal by its energy at that path's bounding-box centroid, producing a
"crystallization wave."
- `--sigma 0 --global-seed <int>` — fully reproducible output (same input →
  byte-identical SVG across separate runs)

### `split_svg_layers.py`
Heuristically regroups an SVG's drawable elements into
`<g id="bgLayer/midLayer/fgLayer">` based on filter references (glitch/scint
→ foreground, idolAura/holoShimmer/footer text → background, else
midground). Handles `<path>`, `<text>`, `<rect>`, `<circle>`, `<line>`,
`<ellipse>`, `<polygon>`, `<polyline>` (self-closing and
open-with-`<animate>`-children forms), and recursively unwraps nested `<g>`
wrappers (up to 6 levels) with correct `transform`/`opacity`/`style`/`filter`
composition.

### `build_pack_opener.py`
Builds a tap-to-reveal HTML widget from `index.json` + a GIFs directory,
with rarity-scaled reveal flash/pacing.

### `build_gacha_banner.py`
Builds a side-by-side collection-sheet SVG with a shimmer sweep.
- `--height`, `--gap`, `--title`
- `--max-row-width` — wrap cards into a multi-row grid instead of one long
  row (greedy left-to-right packing)

### `build_showcase.py`
Combines everything into one self-contained HTML page: gacha banner, pack
opener, per-card X-ray toggle (auto-detects whichever of the 7
`curvature_map.py` modes are present), optional PRIME morph centerpiece, and
a live Web-Audio-driven banner glow (user loads a track in-page, no
preprocessing).

### `extract_audio_envelope.py`
Per-frame RMS envelope + onset detection via ffmpeg (no librosa).
- `--fps`, `--start`, `--duration`, `--onset-ratio`
- `bpm` estimate included by default (autocorrelation,
  `--bpm-min`/`--bpm-max`, default 60–180); `--no-bpm` to skip
- `--bands` — also extract independently-normalized bass (20–250Hz), mid
  (250–2000Hz), treble (2000–8000Hz) envelopes

---

## Follow-on showcase formats

| Want... | Reference doc | Script |
|---|---|---|
| Reveal animation / pack opening | `references/pack_opener.md` | `build_pack_opener.py` |
| Gacha banner / shimmer sweep | `references/gacha_banner.md` | `build_gacha_banner.py` |
| Morph / "PRIME energy" blend | `references/prime_morph.md` | `prime_morph.py` |
| Beat-synced / audio-reactive | `references/audio_reactive.md` | `extract_audio_envelope.py` |
| Tilt-parallax card | `references/parallax_card.md` | `split_svg_layers.py` |

---

## Claude Code subagents

`assets/claude_code_agents/` contains one subagent definition per pipeline
role (cataloger, renderer, forensics analyst, morph architect, layer
splitter, showcase builder, QA auditor, pipeline orchestrator) — each with a
tool-usage guide and a worked example, for use with Claude Code's
multi-agent dispatch.

---

## Source asset prep: Edge Forensics widget

`assets/edge_forensics.html` is a standalone, client-side (no upload)
multi-pass edge-detection tool — Canny, multi-scale Canny, LAB
material-boundary, Sobel gradient magnitude, normal map, curvature, and a
blueprint-style composite overlay. This is the upstream step that turns a
raw rendered image into the edge-detected source used to generate a ZKAEDI
PRIME blueprint SVG. `curvature_map.py` is its CLI/batch counterpart.

---

## Testing

```bash
python3 tests/test_smoke.py            # full suite, ~60-90s (launches a browser)
python3 tests/test_smoke.py --skip-slow # fast pass, skips capture_frames/batch_animate
```

138 checks across 7 synthetic fixture SVGs (covering nested `<g>` groups,
animated primitives, deep nesting, various rarity-text formats and aspect
ratios), an invalid SVG, an empty file, a test tone WAV, pre-rendered GIFs,
all 7 X-ray modes, and a morph GIF — the full suite (including
`build_showcase.py`) runs without needing real DROP assets.

---

## Requirements

- Python 3
- `numpy`, `Pillow` (for `curvature_map.py`)
- Playwright + Chromium (for `capture_frames.py`)
- `ffmpeg` (for `encode_outputs.py`, `extract_audio_envelope.py`)

---

## License

See repository for license terms.
