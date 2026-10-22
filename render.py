#!/usr/bin/env python3
"""
Video Forge renderer
====================
Takes a job JSON (exported from any app in apps/) and renders a high-quality MP4.

  python render.py jobs/my-video.json            # full quality (usually 4K)
  python render.py jobs/my-video.json --draft    # fast 1080p test render
  python render.py jobs/my-video.json --max-seconds 2   # only the first 2 s (pipeline test)

How it works
  1. Opens the app's HTML in headless Chromium (software rendering, so results are the
     same on every machine).
  2. For every frame index i, calls  VIDEO_API.renderFrame(i)  -> PNG at the full output size.
     Several Chromium workers run in parallel; frames are re-ordered and piped into ffmpeg.
  3. ffmpeg encodes H.264 (High profile, yuv420p, BT.709, faststart) -> .mp4
  4. Also writes a poster PNG and a copy of the job JSON next to the video.

Before rendering it runs a quick pre-flight check that renders the same frame twice
(with another frame in between). If the two PNGs differ the animation is not
deterministic (it used Math.random / Date.now / accumulated state) and the render stops
with a clear message, because the final video would not match the preview.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import multiprocessing as mp
import os
import re
import shutil
import subprocess
import sys
import time
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

CHROMIUM_ARGS = [
    "--allow-file-access-from-files",
    "--disable-dev-shm-usage",
    "--hide-scrollbars",
    "--force-color-profile=srgb",
    "--disable-lcd-text",
    "--disable-gpu-vsync",
    "--ignore-gpu-blocklist",
    "--use-angle=swiftshader",          # lets WebGL / three.js work without a GPU
    "--enable-unsafe-swiftshader",
]

JOB_SCHEMA = "html-video-job/1"


def log(*a):
    print(*a, flush=True)


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-") or "video"


def fmt_time(sec: float) -> str:
    sec = int(max(0, sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"


# --------------------------------------------------------------------------- page helpers
def open_page(pw, app: Path, job: dict, w: int, h: int):
    browser = pw.chromium.launch(args=CHROMIUM_ARGS)
    page = browser.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=1)
    page.on("pageerror", lambda e: log(f"[page error] {e}"))
    page.on(
        "console",
        lambda m: log(f"[console.{m.type}] {m.text}") if m.type in ("error", "warning") else None,
    )
    page.goto(app.resolve().as_uri() + "?render=1")
    page.wait_for_function("window.VIDEO_API && window.VIDEO_API.ready === true", timeout=60_000)
    info = page.evaluate("([j, w, h]) => window.VIDEO_API.prepare(j, w, h)", [job, w, h])
    return browser, page, info


def grab(page, i: int) -> bytes:
    b64 = page.evaluate("(i) => window.VIDEO_API.renderFrame(i)", i)
    return base64.b64decode(b64)


# --------------------------------------------------------------------------- worker pool
_W: dict = {}


def _worker_init(app: str, job: dict, w: int, h: int):
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser, page, _ = open_page(pw, Path(app), job, w, h)
    _W.update(pw=pw, browser=browser, page=page)


def _worker_frame(i: int):
    return i, grab(_W["page"], i)


# --------------------------------------------------------------------------- pre-flight
def preflight(app: Path, job: dict, w: int, h: int, frames: int, out_dir: Path, stem: str, skip_det: bool):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, info = open_page(pw, app, job, w, h)
        try:
            mid = max(0, min(info["frames"] - 1, int(info["frames"] * 0.35)))
            grab(page, 0)                                  # warm-up (JIT, fonts, caches)
            a = grab(page, mid)
            grab(page, 0)
            t = time.time()
            b = grab(page, mid)
            per_frame = time.time() - t
        finally:
            browser.close()

    poster = out_dir / f"{stem}_poster.png"
    poster.write_bytes(a)
    same = hashlib.sha256(a).digest() == hashlib.sha256(b).digest()
    log(f"  pre-flight: poster frame #{mid} saved ({len(a)/1e6:.1f} MB), {per_frame:.2f} s/frame in one browser")
    if not same:
        msg = (
            "Pre-flight FAILED: rendering the same frame twice gave different pixels.\n"
            "The animation is not deterministic. Inside draw() it must only depend on T (time) and P (params):\n"
            "  - no Math.random()  -> use H.rng(P.seed)\n"
            "  - no Date.now() / performance.now() / requestAnimationFrame timing\n"
            "  - no state that accumulates from frame to frame (compute from T.t / T.phase instead)\n"
            "Fix the app (or set SKIP_DETERMINISM_CHECK=1 to render anyway)."
        )
        if skip_det:
            log("  WARNING: " + msg.splitlines()[0] + " (continuing because the check is skipped)")
        else:
            raise SystemExit(msg)
    else:
        log("  pre-flight: deterministic ✔")
    return per_frame


# --------------------------------------------------------------------------- main render
def build_ffmpeg_cmd(ffmpeg: str, out: Path, fps: int, crf: int, preset: str, tune: str | None):
    level = "5.1" if fps <= 30 else "5.2"
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "warning",
        "-f", "image2pipe", "-framerate", str(fps), "-c:v", "png", "-i", "-",
        "-vf", "scale=in_range=full:out_range=tv:out_color_matrix=bt709:flags=accurate_rnd+full_chroma_int+bicubic,format=yuv420p",
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-profile:v", "high", "-level:v", level, "-pix_fmt", "yuv420p",
        "-x264-params", "aq-mode=3:aq-strength=0.9",
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
        "-r", str(fps), "-movflags", "+faststart", "-an",
    ]
    if tune:
        cmd += ["-tune", tune]
    cmd.append(str(out))
    return cmd


def probe(out: Path):
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    r = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name,profile,width,height,r_frame_rate,nb_frames,pix_fmt,color_space,duration",
         "-of", "json", str(out)],
        capture_output=True, text=True,
    )
    try:
        return json.loads(r.stdout)["streams"][0]
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description="Render a Video Forge job to MP4")
    ap.add_argument("job", help="path to job JSON, e.g. jobs/my-video.json")
    ap.add_argument("--apps", default="apps", help="folder that holds the app HTML files")
    ap.add_argument("--out", default="out", help="output folder")
    ap.add_argument("--workers", type=int, default=0, help="parallel Chromium workers (default: CPU count - 1)")
    ap.add_argument("--draft", action="store_true", help="half resolution, fast encode (for testing)")
    ap.add_argument("--max-seconds", type=float, default=0, help="render only the first N seconds (for testing)")
    ap.add_argument("--skip-check", action="store_true", help="skip the pre-flight check entirely")
    args = ap.parse_args()

    job_path = Path(args.job)
    if not job_path.is_file():
        raise SystemExit(f"Job file not found: {job_path}")
    job = json.loads(job_path.read_text(encoding="utf-8"))
    if job.get("schema") != JOB_SCHEMA:
        raise SystemExit(f'Not a valid job file (expected "schema": "{JOB_SCHEMA}")')
    app = Path(args.apps) / job["app"]
    if not app.is_file():
        raise SystemExit(f'App "{job["app"]}" not found in {args.apps}/ — upload it to that folder first.')

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg not found")

    o = job.get("output", {})
    w, h = int(o.get("width", 3840)), int(o.get("height", 2160))
    fps = int(o.get("fps", 30))
    duration = float(o.get("duration", 10))
    crf = int(o.get("crf", 14))
    preset = str(o.get("preset", "slow"))
    tune = o.get("tune")
    if args.draft:
        w, h, crf, preset = w // 2, h // 2, 23, "veryfast"
    w -= w % 2
    h -= h % 2
    total = max(1, round(duration * fps))
    if args.max_seconds > 0:
        total = min(total, max(1, round(args.max_seconds * fps)))

    workers = args.workers or max(1, (os.cpu_count() or 2) - 1)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = slug(job_path.stem)
    mp4 = out_dir / f"{stem}.mp4"

    log(f"== {stem}: {w}x{h} @ {fps} fps, {duration:g}s -> {total} frames, crf {crf}, preset {preset}, {workers} workers")
    t_start = time.time()

    job_for_page = dict(job)
    per_frame = preflight(app, job_for_page, w, h, total, out_dir, stem, bool(os.environ.get("SKIP_DETERMINISM_CHECK")) or args.skip_check) \
        if not args.skip_check else 0.0
    if per_frame:
        est = per_frame * total / workers
        log(f"  estimated render time ≈ {fmt_time(est)} (frames only; encoding runs in parallel)")

    proc = subprocess.Popen(build_ffmpeg_cmd(ffmpeg, mp4, fps, crf, preset, tune), stdin=subprocess.PIPE)
    ctx = mp.get_context("spawn")
    done = 0
    t_render = time.time()
    try:
        with ProcessPoolExecutor(
            max_workers=workers, mp_context=ctx,
            initializer=_worker_init, initargs=(str(app), job_for_page, w, h),
        ) as ex:
            window = workers * 2
            pending: deque = deque()
            nxt = 0
            while nxt < total and len(pending) < window:
                pending.append(ex.submit(_worker_frame, nxt)); nxt += 1
            while pending:
                i, png = pending.popleft().result()
                proc.stdin.write(png)
                done += 1
                if nxt < total:
                    pending.append(ex.submit(_worker_frame, nxt)); nxt += 1
                if done % 10 == 0 or done == total:
                    rate = done / max(1e-6, time.time() - t_render)
                    eta = (total - done) / max(1e-6, rate)
                    log(f"  frame {done}/{total}  {rate:.2f} fps  elapsed {fmt_time(time.time()-t_render)}  ETA {fmt_time(eta)}")
        proc.stdin.close()
    except BrokenPipeError:
        proc.kill()
        raise SystemExit("ffmpeg stopped unexpectedly (see its message above)")
    except BaseException:
        proc.kill()
        raise
    rc = proc.wait()
    if rc != 0:
        raise SystemExit(f"ffmpeg failed with exit code {rc}")

    shutil.copyfile(job_path, out_dir / f"{stem}.job.json")
    info = probe(mp4)
    size_mb = mp4.stat().st_size / 1e6
    log(f"== done in {fmt_time(time.time()-t_start)}: {mp4} ({size_mb:.1f} MB)")
    lines = [f"### ✅ {stem}", f"- {w}×{h} @ {fps} fps, {total} frames ({total/fps:.1f} s), {size_mb:.1f} MB",
             f"- total time {fmt_time(time.time()-t_start)} with {workers} workers"]
    if info:
        log(f"   ffprobe: {info}")
        nb = info.get("nb_frames")
        if nb and str(nb).isdigit() and int(nb) != total:
            log(f"   WARNING: expected {total} frames but the file reports {nb}")
            lines.append(f"- ⚠ frame count mismatch: expected {total}, file has {nb}")
        lines.append(f"- {info.get('codec_name')} {info.get('profile')} {info.get('pix_fmt')} {info.get('color_space')}")
    summ = os.environ.get("GITHUB_STEP_SUMMARY")
    if summ:
        with open(summ, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
