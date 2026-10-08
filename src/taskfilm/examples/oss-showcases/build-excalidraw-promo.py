"""Author a 48-second narrated Excalidraw product film from a checked take.

Provider calls are separate. Supply narration.json (path, sha256, at, until,
text per cue) and a licensed 48-second music file. HyperFrames owns playback,
the mix and rendering. No Adobe project or invented app UI is produced.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def probe_seconds(path):
    return float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
        'format=duration', '-of', 'default=nw=1:nk=1', str(path)], text=True))


def author(take: Path, narration: Path, music: Path, out: Path):
    from taskfilm.cli import VIDEO
    take, narration, music, out = [p.resolve() for p in (take, narration, music, out)]
    if out.exists():
        raise ValueError('Use a new output directory; keep previous projects.')
    spec = importlib.util.spec_from_file_location('taskfilm_showcase_result',
        Path(__file__).with_name('build-showcase.py'))
    owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner)
    proof = owner.result_proof(take, 'excalidraw')
    source = take / 'screen.mp4'
    raw = probe_seconds(source)
    beats = [json.loads(line) for line in (take / 'beats.jsonl').read_text().splitlines()]
    if len(beats) != 3:
        raise ValueError('The complete three-beat native capture is required.')
    bounds = [0, float(beats[1]['video_t']), float(beats[2]['video_t']), raw]
    timeline = [7, 21, 31, 37]
    segments = []
    for i in range(3):
        rate = (bounds[i + 1] - bounds[i]) / (timeline[i + 1] - timeline[i])
        if not .5 <= rate <= 2:
            raise ValueError('Capture pacing needs adjustment; retain every source interval.')
        segments.append({'start': timeline[i], 'duration': timeline[i + 1] - timeline[i],
            'source_start': bounds[i], 'source_end': bounds[i + 1], 'playback_rate': rate})
    cues = json.loads(narration.read_text())
    if not isinstance(cues, list) or len(cues) != 6:
        raise ValueError('Supply the six narrated storyboard cues.')
    for cue in cues:
        source_voice = narration.parent / cue['path']
        if source_voice.parent != narration.parent or source_voice.is_symlink():
            raise ValueError('Narration files must be direct local files.')
        if digest(source_voice) != cue['sha256']:
            raise ValueError('Narration changed after generation.')
        measured = probe_seconds(source_voice)
        if not 0 <= cue['at'] < cue['until'] <= 48 or measured > cue['until'] - cue['at']:
            raise ValueError(f'Narration cue does not fit its slot: {cue["text"]}')
        cue['seconds'] = measured
    if probe_seconds(music) < 47.9:
        raise ValueError('The supplied score must cover the complete 48-second film.')
    out.mkdir(parents=True)
    assets = out / 'assets'
    assets.mkdir()
    shutil.copy2(source, assets / 'take.mp4')
    native = take / 'downloads/diagram/idea-to-launch.excalidraw'
    shutil.copy2(native, assets / native.name)
    font_owner = VIDEO / 'hyperframes-lane/product-motion/assets'
    for name in ('Manrope.ttf', 'Manrope-OFL.txt', 'GeistMono.ttf', 'GeistMono-OFL.txt'):
        shutil.copy2(font_owner / name, assets / name)
    for i, cue in enumerate(cues):
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-threads', '1', '-i',
            str(narration.parent / cue['path']), '-af', 'loudnorm=I=-16:TP=-2:LRA=7',
            '-ar', '48000', '-ac', '2', str(assets / f'voice-{i + 1}.wav')], check=True)
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-threads', '1', '-i', str(music),
        '-t', '48', '-af', 'loudnorm=I=-18:TP=-2:LRA=9,afade=t=in:d=0.08,afade=t=out:st=46.7:d=1.3',
        '-ar', '48000', '-ac', '2', str(assets / 'music.wav')], check=True)
    scene = json.loads(native.read_text())
    vectors = []
    for element in scene['elements']:
        if element.get('isDeleted'):
            continue
        x, y = element['x'], element['y']
        if element['type'] == 'rectangle':
            vectors.append(f'<rect class="diagram-line" x="{x}" y="{y}" width="{element["width"]}" height="{element["height"]}" rx="24"/>')
        elif element['type'] == 'arrow':
            points = element['points']
            path = ' '.join(('M' if i == 0 else 'L') + f'{x + point[0]:.3f},{y + point[1]:.3f}'
                for i, point in enumerate(points))
            vectors.append(f'<path class="diagram-line" d="{path}" marker-end="url(#arrow-head)"/>')
        elif element['type'] == 'text':
            vectors.append(f'<text class="diagram-label" x="{x + element["width"] / 2:.3f}" y="{y + element["height"] / 2:.3f}" text-anchor="middle" dominant-baseline="middle">{html.escape(element["text"])}</text>')
    svg = '<svg id="native-diagram" viewBox="260 190 850 260" aria-label="Motion treatment of the saved Idea, Prototype, Ship diagram"><defs><marker id="arrow-head" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6" fill="none" stroke="#d7ff58" stroke-width="1.2"/></marker></defs>' + ''.join(vectors) + '</svg>'
    videos = ''.join(f'<video id="browser-take-{i}" class="clip take" src="assets/take.mp4" muted playsinline data-start="{s["start"]}" data-duration="{s["duration"]}" data-media-start="{s["source_start"]:.8f}" data-playback-rate="{s["playback_rate"]:.8f}" data-track-index="2"></video>' for i, s in enumerate(segments))
    voices = ''.join(f'<audio id="narration-{i + 1}" src="assets/voice-{i + 1}.wav" data-start="{cue["at"]}" data-duration="{cue["seconds"]:.6f}" data-volume="1" data-track-index="10"></audio>' for i, cue in enumerate(cues))
    markup = Path(__file__).with_name('excalidraw-promo.tpl').read_text()
    for key, value in {'__VIDEOS__': videos, '__DIAGRAM__': svg, '__VOICES__': voices}.items():
        markup = markup.replace(key, value)
    (out / 'index.html').write_text(markup)
    (out / 'hyperframes.json').write_text(json.dumps({'name': 'excalidraw-motion-promo', 'entry': 'index.html'}, indent=2) + '\n')
    (out / 'package.json').write_text(json.dumps({'private': True, 'scripts': {
        'check': 'npx --yes hyperframes@0.8.134 check',
        'render': 'npx --yes hyperframes@0.8.134 render'}}, indent=2) + '\n')
    (out / 'SCRIPT.json').write_text(json.dumps(cues, indent=2) + '\n')
    (out / 'BRIEF.md').write_text('---\nworkflow: product-launch-video\nflow: autonomous\nstoryboard: no\n---\n\n# Excalidraw: less explaining, more clarity\n\n48 seconds, 1920×1080, 30fps. A public Taskfilm showcase requested by the operator, with George narration from ElevenLabs and an original instrumental score. Show the complete retained browser workflow with disclosed bounded speed adjustments. Animate the actual native diagram as a clearly identified motion treatment. Deliver the editable composition, encoded film and evidence. HTML/SVG motion graphics; no native Adobe project.\n')
    (out / 'STORYBOARD.md').write_text('# Excalidraw motion promo\n\n0–7: masked oversized type and three idea cards resolve into a clear plan.\n7–21: browser window settles from perspective; show all native drawing actions.\n21–31: connect the real native diagram; a directed camera gives the result space.\n31–37: return to the full UI and save the native editable scene.\n37–42: draw the exact retained diagram as an explicitly labeled motion treatment.\n42–48: Taskfilm wordmark and a readable repository call to action; resolve the score.\n\nNarration uses measured cue durations in SCRIPT.json. All browser source intervals are present. The score is dynamically carved against narration before rendering.\n')
    receipt = {'schema': 'taskfilm-excalidraw-promo/v1', 'seconds': 48, 'width': 1920,
        'height': 1080, 'fps': 30, 'hyperframes': '0.8.134', 'capture': proof,
        'source_seconds': raw, 'source_segments': segments,
        'source_coverage': 'complete and contiguous; no omitted source intervals',
        'take_sha256': digest(source), 'native_scene_sha256': digest(native),
        'narration_cues': cues, 'music_source_sha256': digest(music),
        'rendered': False, 'encoded_visual_review': 'not_performed',
        'diagram_treatment': 'Native element geometry and text; styling and choreography are presentation.',
        'audio_rights': 'Generated on the supplied paid ElevenLabs account. See MEDIA-PROVENANCE.json and ElevenLabs terms; generated audio is not MIT-licensed code.'}
    (out / 'EVIDENCE.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('take', 'narration', 'music', 'out'):
        parser.add_argument('--' + flag, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(author(args.take, args.narration, args.music, args.out), indent=2))
