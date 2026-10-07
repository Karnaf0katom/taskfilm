"""Author a portable HyperFrames film from a complete Taskfilm take.

HyperFrames owns seeking, media playback, audio mixing and rendering. This
script validates the retained result, copies the named inputs and authors HTML.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

APP = {
    "excalidraw": {"name": "Excalidraw", "mode": "Product film", "accent": "#356448",
        "headline": ["Give your idea", "a shape."],
        "about": "An open-source whiteboard for hand-drawn diagrams.",
        "result": "Three steps. One clear direction.", "duration": 44,
        "repo": "https://github.com/excalidraw/excalidraw",
        "steps": ["Draw the steps.", "Connect the idea.", "Keep the editable result."]},
    "drawdb": {"name": "drawDB", "mode": "Feature lesson", "accent": "#286363",
        "headline": ["Your schema.", "In plain sight."],
        "about": "A database diagram editor and SQL generator.",
        "result": "Two tables. One relationship. Real SQL.", "duration": 72,
        "repo": "https://github.com/drawdb-io/drawdb",
        "steps": ["Import the schema.", "Follow the foreign key.", "Export PostgreSQL SQL."]},
    "penpot": {"name": "Penpot", "mode": "OSS walkthrough", "accent": "#a84423",
        "headline": ["One design.", "Two screens."],
        "about": "An open-source interface design and prototyping platform.",
        "result": "Desktop and mobile. In one editable file.", "duration": 52,
        "repo": "https://github.com/penpot/penpot",
        "steps": ["Import two original layouts.", "Explore the editable layers.", "Inspect and keep the native design."],
        "next_title": "For design handoff.",
        "next_copy": "For designers and developers reviewing layouts. Responsive application code is a separate build."},
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def duration(path: Path) -> float:
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of", "default=nw=1:nk=1", str(path)], text=True))


def result_proof(take: Path, app: str) -> dict:
    session = json.loads((take / "session.json").read_text())
    if session["steps"]["ok"] != session["steps"]["total"]:
        raise ValueError("the original capture contains failed steps")
    if session["streams"]["screen"]["status"] != "ok":
        raise ValueError("the original screen recording is incomplete")
    if any(a.get("status") != "passed" for a in session.get("assertions", [])):
        raise ValueError("a recorded result assertion failed")
    retained = []
    download_receipts = {}
    if app in {"excalidraw", "drawdb", "penpot"}:
        stream = session["streams"].get("downloads", {})
        if stream.get("status") != "ok":
            raise ValueError("the original native download stream did not complete")
        for line in (take / stream["path"]).read_text().splitlines():
            row = json.loads(line)
            artifact = row.get("artifact")
            if row.get("status") == "retained" and artifact:
                download_receipts[artifact["path"]] = artifact

    def retain_download(path: Path) -> None:
        relative = str(path.relative_to(take))
        expected = download_receipts.get(relative)
        if not expected or expected["sha256"] != digest(path) or expected["bytes"] != path.stat().st_size:
            raise ValueError("the retained export differs from its original native download receipt")
        retained.append({"path": relative, "sha256": digest(path), "bytes": path.stat().st_size})
    for assertion in session.get("assertions", []):
        path = take / assertion["screenshot"]
        if digest(path) != assertion["sha256"]:
            raise ValueError("a retained assertion screenshot changed")
        retained.append({"path": assertion["screenshot"], "sha256": digest(path)})
    if app == "excalidraw":
        path = take / "downloads/diagram/idea-to-launch.excalidraw"
        scene = json.loads(path.read_text())
        live = [e for e in scene["elements"] if not e.get("isDeleted")]
        if not {"Idea", "Prototype", "Ship"} <= {e.get("text") for e in live}:
            raise ValueError("the downloaded diagram is missing its task labels")
        if sum(e["type"] == "rectangle" for e in live) != 3 or sum(e["type"] == "arrow" for e in live) != 2:
            raise ValueError("the actual diagram differs from the expected three-step workflow")
        retain_download(path)
    elif app == "drawdb":
        path = take / "downloads/sql/project-tracker.sql"
        sql = path.read_text()
        if not all(re.search(pattern, sql, re.I | re.S) for pattern in (
            r'CREATE\s+TABLE.*?"users"', r'CREATE\s+TABLE.*?"projects"',
            r'FOREIGN\s+KEY\s*\("owner_id"\)\s+REFERENCES\s+"users"\s*\("id"\)')):
            raise ValueError("the actual SQL export is missing a table or its foreign key")
        retain_download(path)
    elif app == "penpot":
        if not {"desktop.png", "layouts.png", "mobile-inspection.png"} <= {row["path"] for row in retained}:
            raise ValueError("the Penpot take needs retained native layout and selection assertions")
        path = take / "downloads/design/fieldnotes.penpot"
        if path.stat().st_size < 512:
            raise ValueError("the native Penpot file is unexpectedly small")
        retain_download(path)
    return {"session_sha256": digest(take / "session.json"), "steps": session["steps"],
            "source": session["source"], "result_files": retained,
            "semantic_result": "passed", "visual_review": "not_performed"}


def author(app: str, take: Path, out: Path, voice: Path | None, seconds: float | None,
           words: Path | None = None) -> dict:
    from taskfilm.cli import VIDEO
    cfg = APP[app]
    take, out = take.resolve(), out.resolve()
    if out.exists():
        raise ValueError("film destination must be a new directory")
    proof = result_proof(take, app)
    source = take / "screen.mp4"
    raw = duration(source)
    total = float(seconds or cfg["duration"])
    if voice:
        total = max(total, duration(voice) + 2)
    if total < 20 or total > 100:
        raise ValueError("use a 20–100 second showcase")
    intro, end = (6.0, 7.0)
    task_start = intro
    if app == "drawdb" and words:
        timestamps = json.loads(words.read_text())
        choose = next((w for w in timestamps if str(w.get("text", "")).strip(".,").lower() == "choose"), None)
        if choose is None:
            raise ValueError("narration timestamps must include the lesson's Choose PostgreSQL cue")
        task_start = max(intro, float(choose["start"]) - 2)
    result_hold = 3.0 if app == "excalidraw" else 0.0
    span = total - task_start - end - result_hold
    if span <= 0:
        raise ValueError("the narration cue leaves no time for the browser task")
    # Keep every source frame. The lesson binds its three native beats to the
    # spoken instructions; browser automation's pauses can otherwise outlast VO.
    rate = max(1.0, raw / span)
    if app != "drawdb" and rate > 2.0:
        raise ValueError("capture is too long; give the task more time instead of hiding its actions")
    played = min(raw / rate, span)
    out.mkdir(parents=True)
    assets = out / "assets"
    assets.mkdir()
    shutil.copy2(source, assets / "take.mp4")
    font_owner = VIDEO / "hyperframes-lane/product-motion/assets"
    for name in ("Manrope.ttf", "Manrope-OFL.txt", "GeistMono.ttf", "GeistMono-OFL.txt"):
        shutil.copy2(font_owner / name, assets / name)
    subprocess.run(["ffmpeg", "-v", "error", "-threads", "1", "-sseof", "-0.15", "-i",
        str(source), "-frames:v", "1", str(assets / "result.png")], check=True, timeout=120)
    if app == "drawdb":
        schema_image = take / "tables.png"
        if not any(row["path"] == "tables.png" for row in proof["result_files"]):
            raise ValueError("the lesson preview needs the retained native schema assertion")
        shutil.copy2(schema_image, assets / "schema-preview.png")
    if voice:
        subprocess.run(["ffmpeg", "-v", "error", "-threads", "1", "-i", str(voice), "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", "-ac", "2", "-c:a",
            "pcm_s24le", str(assets / "voice.wav")], check=True, timeout=120)
        audio = f'<audio id="voice" src="assets/voice.wav" data-start="0" data-duration="{duration(voice):.3f}" data-volume="1" data-track-index="10"></audio>'
        # The lesson uses the narrator alone so instructions stay clear.
        audio_rights = "Original narration; provider and rights retained in the delivery media ledger."
    else:
        import numpy as np
        from scipy.io.wavfile import write
        spec = importlib.util.spec_from_file_location("original_sfx", VIDEO / "hyperframes-lane/product-motion/sfx.py")
        sfx = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sfx)
        samples = sfx.pulse_bed(total)
        n = round(sfx.SR * .12)
        samples[:n] *= np.linspace(0, 1, n)[:, None] ** 2
        samples[-sfx.SR:] *= np.linspace(1, 0, sfx.SR)[:, None] ** 2
        write(assets / "score-source.wav", sfx.SR, samples.astype(np.float32))
        subprocess.run(["ffmpeg", "-v", "error", "-threads", "1", "-i", str(assets / "score-source.wav"),
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", "-ac", "2", "-c:a",
            "pcm_s24le", str(assets / "score.wav")], check=True, timeout=120)
        audio = f'<audio id="score" src="assets/score.wav" data-start="0" data-duration="{total:g}" data-volume="1" data-track-index="10"></audio>'
        audio_rights = "Original deterministic pulse synthesis from the included Taskfilm SFX owner."
    e = html.escape
    title = ''.join(f'<div class="line"><span class="word word-{i}">{e(line)}</span></div>' for i, line in enumerate(cfg["headline"]))
    beats = [json.loads(line) for line in (take / "beats.jsonl").read_text().splitlines()]
    if len(beats) != 3:
        raise ValueError("the showcase needs three retained instruction beats")
    source_boundaries = [0.0] + [float(row["video_t"]) for row in beats[1:]] + [raw]
    boundaries = [task_start] + [task_start + value / rate for value in source_boundaries[1:]]
    segments = []
    if app == "drawdb" and words:
        cues = [next((w for w in timestamps if w.get("text") == text), None)
                for text in ("Both", "Open", "Taskfilm")]
        if any(cue is None for cue in cues):
            raise ValueError("the lesson needs Both, Open Export SQL and Taskfilm narration cues")
        boundaries = [task_start] + [float(cue["start"]) for cue in cues]
        for i in range(3):
            target_length = boundaries[i+1] - boundaries[i]
            if target_length <= 0:
                raise ValueError("the spoken lesson cues are out of order")
            factor = (source_boundaries[i+1] - source_boundaries[i]) / target_length
            if not .5 <= factor <= 4:
                raise ValueError("the native instruction beat needs a better-paced capture")
            segments.append({"source_start": source_boundaries[i], "source_end": source_boundaries[i+1],
                             "start": boundaries[i], "duration": target_length, "playback_rate": factor})
        played = boundaries[-1] - task_start
        rate = raw / played
    else:
        segments.append({"source_start": 0.0, "source_end": raw, "start": task_start,
                         "duration": played, "playback_rate": rate})
    if any(end <= start for start, end in zip(boundaries, boundaries[1:])):
        raise ValueError("instruction beats do not fit the complete source recording")
    labels = ''.join(f'<div id="step-{i}" class="clip step" data-start="{boundaries[i]:g}" data-duration="{boundaries[i+1]-boundaries[i]:g}" data-track-index="{3+i}"><span class="number">0{i+1}</span><span>{e(label)}</span></div>' for i, label in enumerate(cfg["steps"]))
    videos = ''.join(f'<video id="task-{i}" class="clip" src="assets/take.mp4" muted playsinline data-start="{segment["start"]:.8f}" data-duration="{segment["duration"]:.8f}" data-media-start="{segment["source_start"]:.8f}" data-playback-rate="{segment["playback_rate"]:.8f}" data-track-index="2"></video>' for i, segment in enumerate(segments))
    lesson_notes = ""
    if app == "drawdb" and task_start > 24:
        notes = [(intro, 12, "A small project tracker."),
                 (12, 21, "Two tables: users and projects."),
                 (21, 26, "Primary keys identify each row."),
                 (26, task_start, "One user can own many projects.")]
        lesson_notes = ''.join(f'<div id="lesson-note-{i}" class="clip step" data-start="{start:g}" data-duration="{end-start:g}" data-track-index="{12+i}"><span class="number">SCHEMA</span><span>{e(label)}</span></div>' for i, (start,end,label) in enumerate(notes))
    freeze_start = task_start + played
    freeze = f'<img id="result-hold" class="clip" src="assets/result.png" data-start="{freeze_start:g}" data-duration="{max(.001,total-end-freeze_start):g}" data-track-index="2">' if freeze_start < total-end else ''
    if task_start > intro:
        freeze += f'<img id="model-preview" class="clip" src="assets/schema-preview.png" data-start="{intro:g}" data-duration="{task_start-intro:g}" data-track-index="2">'
    if app == "drawdb" and freeze_start < total-end:
        labels += f'<div id="proof-label" class="clip step" data-start="{freeze_start:g}" data-duration="{total-end-freeze_start:g}" data-track-index="16"><span class="number">PROOF</span><span>Retained SQL. An editable lesson.</span></div>'
    elif app == "excalidraw" and freeze_start < total-end:
        labels += f'<div id="proof-label" class="clip step" data-start="{freeze_start:g}" data-duration="{total-end-freeze_start:g}" data-track-index="16"><span class="number">RESULT</span><span>Idea. Prototype. Ship.</span></div>'
    markup = (Path(__file__).parent / "showcase.tpl").read_text()
    replacements = {"__APP__": e(cfg["name"]), "__MODE__": e(cfg["mode"]), "__ID__": app + "-showcase",
        "__ACCENT__": cfg["accent"], "__DURATION__": f"{total:g}", "__TITLE__": title,
        "__ABOUT__": e(cfg["about"]), "__RESULT__": e(cfg["result"]), "__SOURCE__": e(cfg["repo"]),
        "__INTRO__": f"{intro:g}", "__PLAYED__": f"{played:g}", "__RATE__": f"{rate:.8f}",
        "__TASK_START__": f"{task_start:g}",
        "__END_START__": f"{total-end:g}", "__END__": f"{end:g}", "__LABELS__": labels,
        "__FREEZE__": freeze, "__AUDIO__": audio, "__LESSON_NOTES__": lesson_notes,
        "__NEXT_TITLE__": e(cfg.get("next_title", "Keep creating.")),
        "__NEXT_COPY__": e(cfg.get("next_copy", "Change the script, the copy and the timing. The recording and composition stay yours.")),
        "__VIDEOS__": videos,
        "__PREVIEW_MOTION__": "tl.fromTo('#model-preview',{scale:1},{scale:1.025,duration:22,ease:'sine.inOut'},6);" if lesson_notes else "",
        "__DETAIL_MOTION__": f"tl.to('#task-2',{{scale:1.20,duration:.6,ease:'power2.inOut'}},{boundaries[2]+.8:g});" if len(segments)==3 else ""}
    for key, value in replacements.items():
        markup = markup.replace(key, value)
    (out / "index.html").write_text(markup)
    (out / "hyperframes.json").write_text(json.dumps({"name": app + "-showcase", "entry": "index.html"}, indent=2) + "\n")
    (out / "package.json").write_text(json.dumps({"private": True, "scripts": {
        "check": "npx --yes hyperframes@0.8.134 check", "render": "npx --yes hyperframes@0.8.134 render"}}, indent=2) + "\n")
    (out / "frame.md").write_text(f"# {cfg['name']} showcase\n\nConcept: {cfg['headline'][0]} {cfg['headline'][1]}\n\nWarm paper #f3f2ed, ink #17251f, accent {cfg['accent']}. Manrope display and Geist Mono metadata. Anchor the app and mode to the upper corners. Feature actual browser footage, followed by the retained result. A single expanding rule follows the finite timeline. Large type reveals and a bounded perspective entrance dress the recording. No synthetic app interface.\n")
    (out / "BRIEF.md").write_text(f"---\nworkflow: general-video\nflow: autonomous\nstoryboard: no\n---\n\n# {cfg['name']} — {cfg['mode']}\n\nCreate the approved OSS showcase in 1920×1080 / 30fps. Explain the app, show one real useful task, and state Taskfilm's contribution. The user approved all proposed films in the release continuation. Keep the original take and semantic result proof. Deliver editable HTML plus reviewed MP4. {audio_rights}\n")
    (out / "STORYBOARD.md").write_text(f"# {cfg['name']}\n\n0–{intro:g}s: explain what the app does; discrete text assembly.\n{intro:g}–{task_start:g}s: preview the retained schema during the narration, when present.\n{task_start:g}–{freeze_start:g}s: actual browser task; bounded perspective entrance and three instruction labels.\n{freeze_start:g}–{total-end:g}s: hold the actual final result, when the lesson needs reading time.\n{total-end:g}–{total:g}s: show the checked result and Taskfilm's contribution; keep source attribution readable.\n")
    receipt = {"schema": "taskfilm-oss-showcase/v1", "app": app, "mode": cfg["mode"], "seconds": total,
        "hyperframes": "0.8.134", "capture": proof, "take_sha256": digest(assets / "take.mp4"),
        "source_seconds": raw, "source_playback_rate": rate, "task_start": task_start,
        "source_segments": segments, "source_coverage": "complete, contiguous; no omitted source intervals",
        "voice_words_sha256": digest(words) if words else None,
        "result_image_sha256": digest(assets / "result.png"),
        "schema_preview_sha256": digest(assets / "schema-preview.png") if app == "drawdb" else None,
        "audio_rights": audio_rights, "rendered": False, "encoded_visual_review": "not_performed"}
    (out / "EVIDENCE.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--app", choices=APP, required=True)
    p.add_argument("--take", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--voice", type=Path)
    p.add_argument("--words", type=Path)
    p.add_argument("--seconds", type=float)
    args = p.parse_args()
    print(json.dumps(author(args.app, args.take, args.out, args.voice, args.seconds, args.words), indent=2))
