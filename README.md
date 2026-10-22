# Video Forge — coded 4K videos, rendered on GitHub

```
apps/    one self-contained HTML "animation maker" per video type (preview + sliders)
jobs/    the small JSON files you export from those apps — uploading one starts a render
render.py                    the renderer (headless Chromium → ffmpeg → 4K H.264 MP4)
.github/workflows/render.yml GitHub Actions workflow that runs render.py
PROMPT_FOR_AI_CODER.md       the master prompt you give an AI to create new apps
```

## 1. One-time setup (works from a phone browser too)

1. On GitHub create a **new repository** (e.g. `video-forge`). **Public** is recommended: standard runners are free for
   public repos and have more CPU/RAM (4 vCPU / 16 GB) than private ones (2 vCPU / 7 GB). Check GitHub's current
   Actions pricing/limits if you want it private.
2. Put these files in the repo (same folder names):
   `render.py`, `requirements.txt`, `.gitignore`, `PROMPT_FOR_AI_CODER.md`, `apps/liquid-gradient-flow.html`,
   `jobs/example-aurora-silk.json`, `.github/workflows/render.yml`.
   * **Desktop:** unzip the kit, then *Add file → Upload files* and drag everything in (including the `.github` folder).
   * **Phone (or if `.github` doesn't upload):** *Add file → Create new file*, type the full path as the file name,
     e.g. `.github/workflows/render.yml` (typing `/` makes folders), paste the file's content, *Commit*. Repeat per file.
3. Repo → **Settings → Actions → General** → make sure Actions are allowed to run.

## 2. Test run (do this first)

1. Repo → **Actions** tab → **Render videos** → **Run workflow**.
2. `job`: `jobs/example-aurora-silk.json` · tick **draft** (fast 1080p test) → **Run workflow**.
3. When the run turns green, open it → scroll to **Artifacts** → download `video-example-aurora-silk`.
   It contains the `.mp4`, a `_poster.png` still, and a copy of the job JSON.
4. Run it again **without** draft to get the real 4K version.

## 3. Everyday workflow

1. Open an app from `apps/` in Chrome (double-click the file — it works offline).
2. Pick a **preset** or tweak sliders; use **🎲 Randomize look** and the **Seed** for endless variations.
   Set **Name**, **Resolution** (3840×2160 for stock), **fps**, **Duration**, **Quality** in the *Output* group.
3. Click **⬇ Download job JSON**.
4. Upload that JSON into the repo's **`jobs/`** folder (*Add file → Upload files*). The render starts by itself.
   Upload several JSONs at once and they render in parallel (3 at a time).
5. When done, download the MP4 from the run's **Artifacts** (kept 14 days — download it, don't rely on GitHub as storage).

> The preview is for design decisions. It runs at low resolution and its grain is approximate; the final render draws
> every frame with the *same code* at full 4K, frame by frame, so it never drops frames.

## 4. Adding new video types

Open `PROMPT_FOR_AI_CODER.md`, paste the prompt into an AI chat, attach `apps/liquid-gradient-flow.html`, describe the
video in the **MY REQUEST** block. Save the HTML the AI gives you into `apps/` (file name must match what it tells you).
No changes to `render.py` or the workflow are ever needed — every app speaks the same `VIDEO_API`.

## 5. What the renderer does (so you can trust it)

* Headless Chromium draws each frame to a canvas at the exact output size → lossless PNG → ffmpeg.
* Frames are rendered by several browsers in parallel and re-ordered before encoding.
* **Pre-flight check:** the same frame is rendered twice (with another frame in between). If pixels differ, the render
  stops and tells you the app is not deterministic — so a bad app can never silently produce a flickering video.
* Encode: H.264 High profile, `yuv420p`, BT.709 tagged, `-crf 14`, preset `slow`, `faststart`, no audio.
  The poster frame is saved so you can check the look without opening the video.
* Final check: `ffprobe` verifies the codec/size and the frame count (a warning is printed on mismatch).

Job fields you may hand-edit in the JSON `output` block: `width`, `height`, `fps` (24/25/30/60), `duration` (seconds),
`crf` (lower = higher quality/bigger file; 12–18 is sensible), `preset` (`slow`, `slower`, `medium`…),
optional `"tune": "grain"` (keeps film grain crisper but makes much bigger files).

## 6. Speed and file size (measured on the example)

* One true-4K frame of the example (grain + bloom + vignette on) took about **5–6 s in a single browser on a 2-core
  machine**. A 10 s / 30 fps clip is 300 frames, so expect **~25–45 min on 2 cores**. GitHub's public-repo runner has
  4 cores and the renderer uses 3 browsers there, so plan on roughly **15–25 min** — that is an estimate; the first
  run prints an exact `ETA` in the log. Heavier scenes cost more; `draft` mode is ~4× cheaper.
* Film grain is the biggest file-size driver: **about 30 MB per second of video at CRF 14**. If a marketplace caps file
  size or bitrate, choose **Quality → Balanced (CRF 18)** in the app, lower the grain slider, or edit `crf` in the job JSON.
* Everything above is per video; several jobs uploaded together run in parallel on separate runners.

## 7. Troubleshooting

| You see | Meaning / fix |
|---|---|
| `Pre-flight FAILED … not deterministic` | The app used `Math.random`, time or frame-to-frame state. Send the message to the AI and ask it to fix `draw()`. |
| `App "xxx.html" not found in apps/` | Upload the HTML to `apps/`; the job's `"app"` must match the file name exactly. |
| `Not a valid job file` | Use the **Download job JSON** button of an app; don't hand-write the file. |
| `[page error] …` in the log | A JavaScript error inside the app. Paste the line to the AI. |
| Video looks different from preview | Only the grain *size* is approximate in the preview. Anything else = a bug in the app (tell the AI). |
| Run takes very long | Normal 4K frames take a few seconds each. The log shows `ETA`. For heavy scenes lower duration/fps while designing, or use *draft*. Jobs are limited to ~5 h 50 min by GitHub. |
| Nothing happens after uploading JSON | Check the Actions tab is enabled and the file is inside `jobs/` and ends with `.json`. You can always start it by hand with **Run workflow**. |

## 8. Selling the footage

Check each marketplace's *current* technical requirements and content rules before uploading (accepted resolution,
frame rates, clip length, codec, file size, rules about generative/algorithmic content, and keywording/disclosure).
Keep every clip free of logos, brand names, and recognisable people. The defaults here (3840×2160, 30 fps, H.264 MP4,
no audio, loopable) are a typical starting point, not a guarantee.
