"""Exercise the complete HyperFrames render path and compare its encoded audio.

This is an opt-in integration script, not a unit test or an alternate mixer.
Run from a clean installed TASKFILM environment with FFmpeg and Node.js present.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path


def loudness(path: Path) -> dict:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-threads", "1", "-i", str(path), "-vn", "-af",
         "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
        check=True, capture_output=True, text=True, timeout=120)
    values = re.findall(r'\{\s*"input_i".*?\}', result.stderr, re.S)
    if not values:
        raise ValueError("FFmpeg did not report the encoded audio level")
    stats = json.loads(values[-1])
    return {"lufs": float(stats["input_i"]), "true_peak_dbtp": float(stats["input_tp"])}


def smoke(out: Path, version: str, mix: Path | None = None) -> dict:
    from taskfilm.cli import VIDEO
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("use an explicit HyperFrames release version")
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    assets = out / "assets"
    assets.mkdir()
    if mix is None:
        import numpy as np
        from scipy.io.wavfile import write
        source = VIDEO / "hyperframes-lane/product-motion/sfx.py"
        spec = importlib.util.spec_from_file_location("taskfilm_original_sfx", source)
        sfx = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sfx)
        samples = sfx.pulse_bed(4.0)
        # Retain the original owner's transients, including an opening impact.
        impact = sfx.impact(0.7, seed=21)
        samples[:len(impact)] += impact * 0.4
        n = min(round(0.12 * sfx.SR), len(samples))
        samples[:n] *= np.linspace(0, 1, n)[:, None] ** 2
        samples[-n:] *= np.linspace(1, 0, n)[:, None] ** 2
        write(assets / "unnormalized.wav", sfx.SR, samples.astype(np.float32))
        mix = assets / "unnormalized.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-threads", "1", "-i", str(mix), "-t", "4", "-af",
         "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", "-ac", "2", "-c:a",
         "pcm_s24le", str(assets / "mix.wav")], check=True, timeout=120)
    shutil.copy2(VIDEO / "hyperframes-lane/product-motion/assets/Manrope.ttf", assets / "Manrope.ttf")
    (out / "hyperframes.json").write_text(json.dumps({
        "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
        "name": "taskfilm-audio-regression", "entry": "index.html"}, indent=2) + "\n")
    (out / "package.json").write_text(json.dumps({"private": True, "scripts": {
        "check": f"npx --yes hyperframes@{version} check",
        "render": f"npx --yes hyperframes@{version} render"}}, indent=2) + "\n")
    (out / "index.html").write_text('''<!doctype html>
<html><head><meta charset="utf-8"><style>
@font-face{font-family:Manrope;src:url(assets/Manrope.ttf)}
html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#f3f2ed}
#root{width:100%;height:100%;position:relative;color:#17251f;font-family:Manrope,sans-serif}
.ground{position:absolute;inset:0;background:#f3f2ed}
.word{position:absolute;left:64px;top:85px;font-size:72px;font-weight:800}
.line{position:absolute;left:64px;top:200px;width:450px;height:6px;background:#24654f;transform-origin:left center}
</style><script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script></head>
<body><div id="root" data-composition-id="audio-proof" data-width="640" data-height="360" data-duration="4">
<div class="clip ground" data-start="0" data-duration="4" data-track-index="0"></div>
<div class="clip" data-start="0" data-duration="4" data-track-index="1"><div class="word">TASKFILM</div><div class="line"></div></div>
<audio id="mix" src="assets/mix.wav" data-start="0" data-duration="4" data-track-index="2" data-volume="1"></audio>
</div><script>
const tl=gsap.timeline({paused:true});
tl.fromTo('.word',{y:24,opacity:0},{y:0,opacity:1,duration:0.6,ease:'power3.out'},0);
tl.fromTo('.line',{scaleX:0},{scaleX:1,duration:3.2,ease:'none'},0.4);
window.__timelines['audio-proof']=tl;
</script></body></html>''')
    with (out / "check.log").open("w") as log:
        subprocess.run(["npm", "run", "check", "--", "--timeout", "30000", "--json"],
                       cwd=out, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
    with (out / "render.log").open("w") as log:
        subprocess.run(["npm", "run", "render", "--", "--quality", "looks", "--fps", "30",
                        "--workers", "1", "--output", str(out / "out.mp4")],
                       cwd=out, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
    movie = out / "out.mp4"
    probe = json.loads(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(movie)], text=True))
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    audio = next(s for s in probe["streams"] if s["codec_type"] == "audio")
    source_level, encoded_level = loudness(assets / "mix.wav"), loudness(movie)
    failures = []
    if abs(encoded_level["lufs"] - source_level["lufs"]) > 1:
        failures.append("complete render changed audio loudness by more than 1 LU")
    if encoded_level["true_peak_dbtp"] > -1:
        failures.append("encoded audio exceeds -1 dBTP")
    if (video["width"], video["height"], video["r_frame_rate"], int(video["nb_frames"])) != (640, 360, "30/1", 120):
        failures.append("encoded video differs from the requested dimensions/fps/frame count")
    if abs(float(audio["duration"]) - 4) > 0.1:
        failures.append("encoded audio duration differs from picture")
    subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-threads", "1", "-i", str(movie),
                    "-f", "null", "-"], check=True, timeout=120)
    report = {"schema": "taskfilm-full-render-audio/v1", "hyperframes_version": version,
              "complete_render": True, "separate_audio_assembly": False,
              "source": source_level, "encoded": encoded_level, "failures": failures,
              "full_decode": "passed", "movie_sha256": hashlib.sha256(movie.read_bytes()).hexdigest()}
    (out / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    if failures:
        raise ValueError("; ".join(failures))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--hyperframes", default="0.8.134")
    parser.add_argument("--mix", type=Path)
    args = parser.parse_args()
    print(json.dumps(smoke(args.out, args.hyperframes, args.mix), indent=2))
