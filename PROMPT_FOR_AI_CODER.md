# Master prompt — "Animation Maker" for Video Forge

**How to use:** open a new chat with any AI coder, **attach `apps/liquid-gradient-flow.html`**, paste everything
between the two `=====` lines, and fill in the **MY REQUEST** block at the bottom.
The attached file is the reference implementation of the system.

=====================================================================

You are a senior motion-graphics engineer. You will build ONE new **animation maker**: a single, fully
self-contained HTML file (HTML + CSS + JS, no external requests) that lets me preview an animated video in
my browser and tweak it with sliders, then export a small **job JSON**. A separate Python + GitHub Actions
renderer (already built) opens your HTML in headless Chromium, draws every frame at 4K, and encodes an MP4
that I sell as stock footage. So the preview and the final render must be **the same code path**.

## 0. What I attach
`liquid-gradient-flow.html` — the reference implementation. It has two scripts:

* `<script id="VIDEO">` — the part YOU write for each new video type.
* `<script id="FRAMEWORK">` — the shared engine (UI builder, preview player, bloom / vignette / film grain,
  job JSON export, and the `window.VIDEO_API` the renderer calls).
  **Copy the FRAMEWORK script, the HTML shell and the CSS byte-for-byte. Do not edit, rename, reformat or
  "improve" them.** If you believe the framework itself has a bug, tell me in the reply instead of changing it.

Your output is the same file layout with a brand-new `VIDEO` script (and a new `<title>`).

## 1. The VIDEO contract

```js
const VIDEO = {
  id: 'kebab-case-id',            // unique
  title: 'Human Title',
  file: 'kebab-case-id.html',     // MUST equal the file name I will save (it is written into every job JSON)
  defaults: { duration: 10, fps: 30, width: 3840, height: 2160, crf: 14 },   // output defaults
  schema: [ {key,label,type,group,default, min,max,step, options, showIf, rand}, ... ],
  presets: { 'Preset Name': { ...partial param overrides... }, ... },
  init: async (P, OUT, H) => {},  // OPTIONAL one-time async setup (decode embedded images, build a WebGL scene…)
  draw(ctx, w, h, T, P, H) { ... }
};
```
* Control types: `range` (min,max,step), `select` (options: `[[value,label],…]`), `color`, `checkbox`.
  `showIf: P => boolean` hides a control when it is irrelevant. `rand:false` keeps it out of "Randomize".
* The framework automatically adds the **Film & Finish** group (bloom, vignette, film grain, grain size, grain colour),
  the **Output** group (name, resolution, fps, duration, seed, quality) and **Presets / Randomize / Export**.
  Do **not** re-implement those. Presets may override `bloom`, `vignette`, `grain`, `grainSize`, `grainChroma`.
* `T` = `{ frame, frames, fps, duration, t (seconds), phase (0..1, loops), u (= h/1080), w, h }`
* `P` = current values (always includes `P.seed`). `H` = `{ TAU, clamp, lerp, smooth, rng(seed), hex, rgba, mix }`.

## 2. Non-negotiable rules

**A. Deterministic — `draw()` is a pure function of `(T, P)`.**
The renderer draws frames out of order, in several browsers at once, and checks that drawing the same frame twice gives
identical pixels. Therefore inside `draw()`/`init()`:
* NO `Math.random()` → use `H.rng(P.seed)` (create it fresh inside `draw`, so every frame sees the same sequence).
* NO `Date.now()`, `performance.now()`, `requestAnimationFrame`, `setTimeout`, CSS animations, video/audio elements.
* NO state that accumulates between frames (particle "update" loops, `x += v`). Compute every position directly from
  `T.t` / `T.phase`. If a real simulation is unavoidable, pre-compute it in `init()` for all `T.frames` with a fixed
  time step and look frames up by index.
* Everything may be cached across frames **only if** the cache depends solely on `P`/`w`/`h` and is rebuilt when they change.

**B. Resolution independent.** The same code runs at 960×540 (preview) and 3840×2160 (final). Size everything with
`T.u` (= `h/1080`) or fractions of `w`/`h`. Never hard-code pixel sizes. Line widths, blur radii, particle sizes, shadow
offsets: all × `u`. The final result must look identical (just sharper) at any resolution.

**C. Seamless loops (stock buyers love them).** Unless my request says otherwise, make the clip loop perfectly:
all motion is periodic in `T.phase` using **whole-number** multiples (`Math.sin(TAU * T.phase * cycles * k)`, with
integer `cycles`/`k`); things that travel (particles, scrolling) wrap with `frac(position - phase*cycles*m)`.
Frame 0 must be the natural successor of the last frame. Add a "Motion cycles per video" control (integer step 1).
(Linear one-shot animations such as "number counting up" or "chart growing" are fine when I ask for a one-shot; then say so
in your reply and add a hold at the end.)

**D. Fast enough at 4K.** The renderer uses a CPU (software) canvas on a shared GitHub runner, so be economical:
* No per-pixel JS loops over the full frame inside `draw()` (the framework's grain is the only exception).
* No `ctx.filter = 'blur()'` or `shadowBlur` on full-resolution content in a loop. For soft light use radial gradients,
  or draw small to an off-screen canvas at ¼ size and scale it up.
* Keep object counts sensible (a few hundred shapes, not tens of thousands) unless they are tiny.
* Pre-compute static layers once (in `init()` or a `P`-keyed cache), then just `drawImage` them.
* Estimated budget: a typical 4K frame should take **< 4 s** in software. Tell me your estimate in the reply.

**E. 100 % self-contained.** No CDN links, no external fonts/images/audio, no `fetch`. If you need
* **text** → embed the font as base64 `@font-face` (WOFF2) inside the HTML and `await document.fonts.load('48px "Name"')`
  in `init()`. The render machine has no fonts of its own. Prefer shapes over text.
* **images/textures** → generate procedurally, or embed as base64 and decode in `init()`.
* **3D** → either hand-written Canvas-2D projection (preferred for simple scenes), or paste the **minified Three.js
  build inline** in its own `<script>` before the FRAMEWORK. Render into your own WebGL canvas
  (`preserveDrawingBuffer:true`, `antialias:true`, pixel ratio 1, size = `w×h`) and `ctx.drawImage(glCanvas, 0, 0)`.
  The renderer has software WebGL (SwiftShader) — it works but is slow, so keep scenes modest and say so in the reply.

**F. Stock-footage hygiene.** No logos, brand names, trademarks, watermarks, recognisable people, real maps or
copyrighted characters. Any on-screen text must be generic and editable via a control. Backgrounds must be clean and
usable (no clutter in the corners). Avoid anything that looks like a screensaver cliché unless that is the request.

**G. Premium look, not demo look.** Think After Effects with a good colourist:
* Curated palettes (harmonious, intentional contrast) — never raw `#ff0000/#00ff00`. Include at least 8 palettes.
* Smooth, physically plausible motion: use easing (`H.smooth`, sine/cubic), layered parallax, subtle secondary motion,
  depth through scale/blur/opacity falloff. No linear robotic movement unless asked.
* Avoid banding: large smooth gradients are okay because the framework's grain dithers them, but never rely on very
  low-contrast dark gradients with grain off.
* The defaults of every control must already look great — I should be able to export without touching anything.
* Leave film grain / bloom / vignette to the framework (they are part of my signature finish).

**H. One app = 30–40 distinct videos.** Build in real variety, not just colour swaps:
* **≥ 3 structurally different styles/modes** (a `select`), each a different composition or motion idea.
* **≥ 8 palettes** (or a colour system) plus an optional **custom colours** toggle (`useCustom` + `showIf`).
* **≥ 10 named presets** that are clearly different from each other and each a finished, sellable look.
* **15–30 controls**, grouped (Look / Shapes / Motion / Details …), sensible ranges, step sizes that produce clean values.
* The `seed` (framework control) must change the composition (layout/phases), so each seed is a new video.
* Every control must visibly do something at its extremes without breaking the picture.

**I. Robust.** Never throw on any control combination. Guard divisions by zero. Clamp inputs. Keep `draw()` free of
`console.log`. Wrap nothing in try/catch that could hide errors.

## 3. Self-check before you answer (do it silently, fix anything that fails)
1. FRAMEWORK script, CSS and HTML shell are identical to the attachment.
2. `VIDEO.file` equals the file name; `VIDEO.id` is new; `<title>` updated.
3. Search your own code for `Math.random`, `Date`, `performance`, `requestAnimationFrame`, `setTimeout`, `fetch`,
   `http` → none inside `draw`/`init`.
4. Mentally render frame 0 and frame `T.frames` (one past the last) → identical composition (loop closes).
5. Every size uses `u`, `w` or `h`. Nothing is in absolute pixels.
6. Every preset only uses keys that exist in the schema, with values inside the schema's min/max.
7. All schema `default`s produce a beautiful frame.
8. No external resources of any kind.

## 4. Reply format
1. The complete HTML file in one code block (no placeholders, no "rest unchanged").
2. **Controls overview** — a short table: group → what each control does.
3. **Presets** — one line each.
4. **Recommended output** — duration, fps, whether it loops, and a rough render-time estimate for 4K.
5. **How to use** (always these 4 lines):
   1. Save as `apps/<VIDEO.file>` in my GitHub repo (replace the same-named file if it exists).
   2. Open the HTML in Chrome, pick a preset / tweak, set Name + Output, click **Download job JSON**.
   3. Upload the JSON to the repo's `jobs/` folder → the render starts automatically (Actions tab).
   4. Download the finished MP4 from the run's **Artifacts**.
6. **If something goes wrong** — map these messages to the cause:
   *"Pre-flight FAILED … not deterministic"* → `draw()` used randomness/time/state;
   *"App … not found"* → the HTML is not in `apps/` or `VIDEO.file` ≠ file name;
   *blank/black frames* → a JS error (check the log line starting `[page error]`);
   *job takes very long* → too many shapes/filters per frame, lower counts or duration.

## 5. MY REQUEST

**Video type / name:** …
**Visual idea (what it looks like and how it moves):** …
**Mood / palette hints:** …
**Loop?** yes / no (one-shot)
**Special requirements (text, data, 3D, camera moves, number of layers, etc.):** …

=====================================================================

## Example requests you can paste into the MY REQUEST block

**1 — Abstract (3D feel, Canvas 2D)**
> Video type: "Crystal Prism Tunnel". A slow camera glide through an endless tunnel of translucent glass prisms that
> refract coloured light. Three styles: hex tunnel, triangle shards, ring gates. Moody, expensive, cinematic. Dark
> backgrounds with neon edge-light, slight chromatic fringing on edges. Loops perfectly.

**2 — Financial growth**
> Video type: "Growth Chart Rise". Clean, dark-mode financial visuals with no text or numbers: glowing candlestick and
> area-chart landscapes that build and flow. Styles: candlesticks, rising area + moving average, bar race of 12 bars.
> Controls: trend direction (bull/bear/sideways), volatility, candle count, line thickness, grid on/off, accent colour.
> One-shot is fine: chart grows over the first 70 % then holds, with gentle camera push-in.

**3 — Botanical**
> Video type: "Botanical Bloom". Elegant line-art and soft-fill leaves/ferns/flowers that sway in a breeze and slowly grow
> on a warm paper or deep-forest background. Styles: fern fronds, monstera leaves, wildflower meadow. Procedural plants
> generated from the seed (L-system or parametric curves). Loops perfectly.

**4 — Infographic**
> Video type: "Infographic Elements Pack". Animated generic UI/infographic elements: radial progress rings, bar
> pulses, node-link networks, dotted map-less world grids, counters without text. Corporate blue/teal palettes, clean
> modern motion with easing, subtle parallax. Loops perfectly. No text.

**5 — 3D (Three.js)**
> Video type: "Glass Spheres Orbit". Inline minified Three.js; a cluster of 12–40 glossy spheres orbiting with soft
> studio lighting, depth of field faked via gradient overlay, and a clean gradient backdrop. Styles: orbit, grid wave,
> spiral. Keep the scene light enough to render in software in under 4 s per 4K frame (use low-poly spheres + env gradient
> instead of heavy reflections). Loops perfectly.
