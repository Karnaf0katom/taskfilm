"""Offline product-motion/v1 conversion into a portable Workspace checkpoint.

The native movie is an explicitly imported delivery, not a render of the modern
composition. Rebuilding Render uses modern layouts; native animation/evidence is
retained under original/. No capture, speech generation or network is performed.
"""
from __future__ import annotations

import html
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont

from . import ad, media
from .studio import Workspace, build_composition, read, write

NOTICE = ('Imported film: the preview is the exact original movie. Scenes, copy and '
          'capture trims are editable; rebuilding Composition or Render uses modern '
          'Taskfilm layouts, not the original motion, cursor choreography or lens animation. '
          'The native project and capture evidence remain in original/ and source/original/.')


def _file(path: Path) -> Path:
    if not path.is_file():
        raise ValueError(f'Legacy import requires an existing file: {path}')
    return path


def _text(value) -> str:
    if isinstance(value, list):
        value = ' '.join(_text(part) for part in value)
    return re.sub(r'\s+', ' ', html.unescape(str(value))).replace('[', '').replace(']', '').strip()


def _wordmark(spec, assets: Path, target: Path):
    """Rasterize the native Manrope 800 wordmark, including its accent dot."""
    brand = spec['copy']['brand']
    font = ImageFont.truetype(str(assets / 'Manrope.ttf'), 160)
    try:
        font.set_variation_by_name('ExtraBold')
    except (OSError, ValueError):
        pass  # Static fonts already contain their native weight.
    name, dot = _text(brand['wordmark']), _text(brand.get('dot', ''))
    native_html = (assets.parent / 'index.html').read_text()
    style = re.search(r'\.wm\{font-size:([\d.]+)px;letter-spacing:([-\d.]+)px', native_html)
    tracking = 160 * float(style[2]) / float(style[1]) if style else 0
    width = int(font.getlength(name + dot)) + 32
    image = Image.new('RGBA', (width, 220))
    draw = ImageDraw.Draw(image)
    x = 8.0
    for letter in name:
        draw.text((x, 0), letter, font=font, fill=spec['palette']['ink'])
        x += font.getlength(letter) + tracking
    draw.text((x, 0), dot, font=font, fill=spec['palette']['accent'])
    image.crop(image.getbbox()).save(target)


def _convert(spec, decisions, fmt: str) -> dict:
    """Preserve each native source segment as a separately editable scene."""
    copytext, times = spec['copy'], decisions['times']
    scenes = []
    duration = float(decisions['duration'])

    def add(ident, start, end, headline, body='', source=None):
        length = round(end - start, 6)
        if length <= .000001:
            return
        if length < .5:
            raise ValueError(f'Native interval {ident} is {length}s; modern scenes require at least 0.5s')
        scene = {'id': ident, 'duration': length, 'headline': _text(headline), 'body': _text(body)}
        if source:
            scene['media'] = source
        scenes.append(scene)

    segments = sorted(decisions['segments'], key=lambda item: item['f0'])
    if not segments:
        raise ValueError('EDIT-DECISIONS.json needs native source segments')
    cursor = 0.0
    for index, segment in enumerate(segments):
        start, end = float(segment['f0']), float(segment['f1'])
        if start < cursor - .000001 or end <= start or end > duration:
            raise ValueError(f'Invalid/overlapping native segment: {segment["id"]}')
        if start > cursor:
            add(f'gap-{index}', cursor, start, copytext['hook']['a'], copytext['hook']['b'])
        if start < float(times['dive']):
            headline, body = copytext['intro']['tagline'], copytext['hero']['text']
        else:
            step = 0 if start < float(times['whip1']) else 1 if start < float(times['find']) else 2
            headline, body = copytext['steps'][step]['title'], copytext['steps'][step]['sub']
        add(f'segment-{index}-{segment["id"]}', start, end, headline, body,
            {'path': 'source/take.mp4', 'type': 'video', 'in': float(segment['s0']),
             'speed': float(segment['rate'])})
        cursor = end
    close = float(times['end'])
    if cursor < close:
        # Native recap images already contain the exact source crop.
        recaps = decisions.get('recap_frames', [])
        if recaps and (close - cursor) / len(recaps) >= .5:
            start = cursor
            for index, recap in enumerate(recaps):
                end = cursor + (close - cursor) * (index + 1) / len(recaps)
                name = Path(recap['path'])
                if name.is_absolute() or '..' in name.parts:
                    raise ValueError('Recap path must be relative to native assets')
                add(f'recap-{index}', start, end, copytext['recap'][index], source={
                    'path': f'assets/recap-{index}.png', 'type': 'image'})
                start = end
        else:
            add('recap', cursor, close, copytext['recap'])
        cursor = close
    add('close', cursor, duration, copytext['end']['tagline'], copytext['end']['url'].replace('/', '/ '))
    return {'schema': 'taskfilm-ad/v1', 'id': f'{spec["id"]}-{fmt}', 'format': fmt,
            'brand': {'name': copytext['brand']['name'], 'logo': 'assets/wordmark.png',
                      'font': 'original/native/assets/Manrope.ttf',
                      'font_license': 'original/native/assets/Manrope-OFL.txt',
                      'colors': {'background': spec['palette']['paper'], 'text': spec['palette']['ink'],
                                 'accent': spec['palette']['accent']}},
            'scenes': scenes, 'audio': {'path': 'mix.wav'}}


def _recap_assets(decisions, native: Path, assets: Path):
    """Strip inherited non-square PNG pixel-aspect metadata, never alter pixels."""
    for index, recap in enumerate(decisions.get('recap_frames', [])):
        name = Path(recap['path'])
        if name.is_absolute() or '..' in name.parts:
            raise ValueError('Recap path must be relative to native assets')
        with Image.open(_file(native / 'assets' / name)) as image:
            # Saving a fresh image omits pHYs/DPI metadata inherited from FFmpeg.
            clean = Image.new(image.mode, image.size)
            clean.paste(image)
            clean.save(assets / f'recap-{index}.png')


def _portable_build(directory: Path, spec: dict):
    build_composition(directory, spec)


def import_legacy(workspace: Path, spec_path: Path, format: str, movie: Path) -> dict:
    """Import existing inputs atomically; return version, film id and a summary.

    The only ready-render exception is the explicitly documented original movie.
    raw_visual is deliberately unset: the native movie cannot serve as a visual
    cache of a composition built with different layouts.
    """
    workspace, spec_path, movie = Path(workspace).resolve(), Path(spec_path).resolve(), Path(movie).resolve()
    if (workspace / 'HEAD').exists():
        raise ValueError('Legacy import requires a new workspace; HEAD already exists')
    if format not in ('portrait', 'landscape'):
        raise ValueError('Legacy format must be portrait or landscape')
    spec = read(_file(spec_path))
    if spec.get('schema') != 'product-motion/v1':
        raise ValueError('Legacy import requires product-motion/v1')
    native = spec_path.parent / 'cuts' / format
    decisions = read(_file(native / 'EDIT-DECISIONS.json'))
    if decisions.get('format') != format or decisions.get('film') != spec.get('id'):
        raise ValueError('Native edit decisions do not match the requested film/format')
    take = (spec_path.parent / spec['take']).resolve()
    required = [movie, native / 'index.html', native / 'assets/take.mp4',
                native / 'assets/Manrope.ttf', native / 'assets/Manrope-OFL.txt']
    required += [take / name for name in ('screen.mp4', 'session.json', 'input.jsonl', 'beats.jsonl', 'windows.jsonl')]
    mix = next((native / 'assets' / name for name in ('originalmix.wav', 'mix.wav')
                if (native / 'assets' / name).is_file()), native / 'assets/mix.wav')
    for path in [*required, mix]:
        _file(path)
    # Never create a workspace inside a tree we are about to archive.
    for source in (native.resolve(), take):
        if workspace == source or source in workspace.parents:
            raise ValueError('Workspace must be outside native project and capture directories')
    rights = decisions.get('music', {}).get('rights') or spec.get('music', {}).get('rights')
    if not rights or 'deterministic synthesis' not in rights.lower():
        raise ValueError('Expected original deterministic synthesis rights in native music metadata')
    info = ad.probe(movie)
    video = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'), None)
    if not video:
        raise ValueError(f'Original movie has no video stream: {movie}')
    if abs(ad._duration(info, video) - float(decisions['duration'])) > .15:
        raise ValueError('Original movie duration differs from native edit decisions')
    if (video['width'] < video['height']) != (format == 'portrait'):
        raise ValueError('Original movie orientation does not match requested format')
    ws = Workspace(workspace)
    pending = Path(tempfile.mkdtemp(prefix='.version-', dir=workspace))
    try:
        (pending / 'original').mkdir()
        (pending / 'source').mkdir()
        (pending / 'assets').mkdir()
        shutil.copytree(native, pending / 'original/native',
                        ignore=shutil.ignore_patterns('node_modules', '.git', '.env*'))
        shutil.copytree(take, pending / 'source/original',
                        ignore=shutil.ignore_patterns('node_modules', '.git', '.env*'))
        shutil.copy2(spec_path, pending / 'legacy-spec.json')
        shutil.copy2(native / 'EDIT-DECISIONS.json', pending / 'EDIT-DECISIONS.json')
        shutil.copy2(native / 'assets/take.mp4', pending / 'source/take.mp4')
        shutil.copy2(movie, pending / 'original/movie.mp4')
        shutil.copy2(movie, pending / 'delivery.mp4')
        shutil.copy2(mix, pending / 'mix.wav')
        _wordmark(spec, pending / 'original/native/assets', pending / 'assets/wordmark.png')
        _recap_assets(decisions, pending / 'original/native', pending / 'assets')
        try:
            modern = _convert(spec, decisions, format)
        except (KeyError, TypeError, IndexError) as exc:
            raise ValueError(f'Incomplete native spec/edit decisions for {spec_path}: {exc}') from exc
        ad.plan(modern, base_dir=pending)  # Includes real trim/speed/duration validation.
        config = {'provider': 'google', 'voice': 'Kore', 'rate': 1.15, 'ssh_host': None}
        metadata = {'schema': 'taskfilm-legacy-import/v1', 'notice': NOTICE,
                    'source_schema': spec['schema'], 'source_id': spec['id'], 'format': format,
                    'native_project': 'original/native/index.html', 'original_movie': 'original/movie.mp4',
                    'legacy_spec': 'legacy-spec.json', 'edit_decisions': 'EDIT-DECISIONS.json',
                    'capture': 'source/original', 'provenance': 'conversion-provenance.json',
                    'preview_is_original': True, 'rebuild_uses_modern_layouts': True}
        area = spec['id'].split('-', 1)[-1].replace('-', ' ').title()
        project = {'schema': 'taskfilm-studio/v1', 'name': f'{spec["copy"]["brand"]["name"]} · {area}',
                   'language': 'en', 'destinations': ['instagram', 'facebook', 'youtube'],
                   'captions': False, 'narration': config, 'publishing': {}, 'legacy_import': metadata}
        music = {'path': 'original/native/assets/' + mix.name, 'in': 0, 'gain_db': 0,
                 'license': 'Original deterministic synthesis (native kit)',
                 'license_url': 'conversion-provenance.json', 'commercial_use': True,
                 'attribution_required': True, 'attribution': rights}
        audio = {'schema': 'taskfilm-audio/v1', 'duration': sum(s['duration'] for s in modern['scenes']),
                 'music': music, 'narration': [], 'effects': []}
        write(pending / 'ad.json', modern)
        write(pending / 'audio.json', audio)
        write(pending / 'project.json', project)
        write(pending / 'conversion-provenance.json', {**metadata, 'music_rights': rights,
              'music_note': 'Original native synthesized music/SFX bed, not narration. No speech was generated.',
              'wordmark': 'Native wordmark and accent dot rasterized with native Manrope weight 800.',
              'timing_policy': 'Native f0/f1, s0 and rate retained; recap crops use native stills. Lens/cursor choreography remains native-only.',
              'recap_policy': 'Editable recap PNGs retain native pixels with non-square pixel-aspect metadata removed; originals preserved.',
              'copy_policy': 'HTML entities decoded; native emphasis brackets removed; URLs spaced after slashes for readable wrapping.',
              'original_movie_sha256': media.digest(movie), 'legacy_spec_sha256': media.digest(spec_path),
              'segments': decisions['segments'], 'scene_ids': [s['id'] for s in modern['scenes']]})
        # A preservation receipt, explicitly not a claim to have synthesized/mixed audio.
        write(pending / 'mix.mix.json', {'schema': 'taskfilm-imported-mix/v1', 'path': 'mix.wav',
              'sha256': media.digest(pending / 'mix.wav'), 'operation': 'preserved-native-mix',
              'inputs': [{**music, 'sha256': media.digest(mix)}], 'attribution': [rights]})
        _portable_build(pending, modern)
        subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(min(1.5, audio['duration'] / 2)),
                        '-i', str(movie), '-frames:v', '1', '-vf', 'scale=540:-1',
                        '-threads', '1', str(pending / 'preview.jpg')], check=True, capture_output=True)
        _file(pending / 'preview.jpg')
        inputs = ws._inputs(pending)
        write(pending / 'pipeline.json', {'built': {stage: inputs[stage] for stage in
              ('brief', 'capture', 'storyboard', 'audio', 'composition', 'render')},
              'raw_visual': None, 'voice_texts': [], 'voice_config': config,
              'imported_render': {'path': 'delivery.mp4', 'sha256': media.digest(movie),
                                  'kind': 'original-native-delivery', 'notice': NOTICE}})
        if (workspace / 'HEAD').exists():
            raise ValueError('Workspace HEAD appeared during import; existing versions are preserved')
        version = ws._commit(pending, 'Imported native film with editable scenes', 'render')
        return {'version': version, 'id': modern['id'], 'summary': NOTICE}
    finally:
        if pending.exists():
            shutil.rmtree(pending)
