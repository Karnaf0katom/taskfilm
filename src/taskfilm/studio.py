"""Local visual studio with complete immutable checkpoints and selective rebuilds.

No database or web dependency. A checkpoint is an ordinary portable directory;
the server only creates new ones. Existing source captures are never modified.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from urllib.parse import parse_qs, quote, unquote, urlsplit
import uuid
import zipfile

from . import ad as ads, media
from .ad_templates import templates

STAGES = [('brief', 'Brief'), ('capture', 'Capture'), ('storyboard', 'Storyboard'),
          ('audio', 'Audio'), ('composition', 'Composition'), ('render', 'Render'),
          ('publish', 'Publish')]
ARTIFACTS = dict(brief='project.json', capture='source', storyboard='ad.json',
                 audio='mix.wav', composition='composition/index.html',
                 render='delivery.mp4', publish='publishing.json')
ASSETS = Path(__file__).parent / 'studio_assets'


def write(path: Path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def read(path: Path):
    return json.loads(path.read_text())


def scene_timeline(spec):
    start, scenes = 0.0, []
    for scene in spec['scenes']:
        end = start + float(scene['duration'])
        scenes.append({'id': scene['id'], 'start': start, 'end': end})
        start = end
    return {'format': spec['format'], 'scenes': scenes}


def build_composition(directory: Path, spec: dict):
    """Build visuals with portable source and evidence paths for the checkpoint."""
    visual = copy.deepcopy(spec)
    visual.pop('audio', None)
    composition = ads.build(visual, directory / 'composition', base_dir=directory)

    def relative(value, base):
        if isinstance(value, dict):
            return {k: relative(v, base) for k, v in value.items()}
        if isinstance(value, list):
            return [relative(v, base) for v in value]
        if isinstance(value, str) and value.startswith(str(directory) + '/'):
            return os.path.relpath(value, base)
        return value

    for path in composition.glob('*.json'):
        write(path, relative(read(path), path.parent))
    # The archived source spec originally resolved against the workspace root.
    source = read(composition / 'AD-SOURCE.json')
    for key in ('logo', 'font', 'headline_font', 'font_license'):
        if source['brand'].get(key):
            source['brand'][key] = '../' + source['brand'][key]
    for scene in source['scenes']:
        if scene.get('media'):
            scene['media']['path'] = '../' + scene['media']['path']
    if source.get('presenter'):
        source['presenter']['path'] = '../' + source['presenter']['path']
    write(composition / 'AD-SOURCE.json', source)
    return composition


def fingerprint(value, *, legacy=False):
    # JavaScript round-trips 3.0 as 3. Equivalent numeric inputs must not
    # invalidate an otherwise unchanged capture, composition or audio cache.
    def canonical(item):
        if isinstance(item, float) and item.is_integer():
            return int(item)
        if isinstance(item, dict):
            return {k: canonical(v) for k, v in item.items()}
        if isinstance(item, list):
            return [canonical(v) for v in item]
        return item
    data = value if legacy else canonical(value)
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def inside(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError('File path must be relative to this version')
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('File path is outside this version')
    return path


def files(root: Path):
    return sorted(p for p in root.rglob('*') if p.is_file() and p.name != 'VERSION.json')


class Conflict(ValueError):
    pass


class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.versions = self.root / 'versions'
        self.versions.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.jobs = []

    @property
    def head(self):
        return (self.root / 'HEAD').read_text().strip()

    def directory(self, version=None):
        version = version or self.head
        if not re.fullmatch(r'[0-9a-f]{20}', version):
            raise ValueError('Unknown version')
        path = self.versions / version
        if not (path / 'VERSION.json').is_file():
            raise ValueError('Unknown version')
        return path

    def verify(self, directory: Path):
        manifest = read(directory / 'VERSION.json')
        actual = {p.relative_to(directory).as_posix() for p in files(directory)}
        if actual != set(manifest['files']):
            raise ValueError('Version files changed on disk; import an edited copy as a new project')
        for name, record in manifest['files'].items():
            if media.digest(inside(directory, name)) != record['sha256']:
                raise ValueError(f'Version file changed on disk: {name}')

    def _commit(self, pending: Path, label: str, stage: str, parent=None, advance=True):
        if stage not in dict(STAGES) or not isinstance(label, str) or not 1 <= len(label.strip()) <= 160:
            raise ValueError('A version needs a stage and a label of 1–160 characters')
        ident = uuid.uuid4().hex[:20]
        copied = {}
        for path in files(pending):
            copied.setdefault(media.digest(path), path)
        # Receipts emitted by media helpers reference the temporary working
        # directory. Relocate those references before sealing the checkpoint.
        def relocate(value, base):
            if isinstance(value, dict):
                result = {k: relocate(v, base) for k, v in value.items()}
                if isinstance(value.get('path'), str) and value.get('sha256') in copied:
                    result['path'] = os.path.relpath(copied[value['sha256']], base)
                return result
            if isinstance(value, list):
                return [relocate(v, base) for v in value]
            if isinstance(value, str) and value.startswith(str(pending) + '/'):
                return os.path.relpath(value, base)
            return value
        for path in pending.rglob('*.json'):
            if path.name.endswith(('.mix.json', '.delivery.json', '.narration.json')):
                data = relocate(read(path), path.parent)
                suffix = next(s for s in ('.mix.json', '.delivery.json', '.narration.json') if path.name.endswith(s))
                target = path.name[:-len(suffix)] + ('.mp4' if suffix == '.delivery.json' else '.wav')
                if (path.parent / target).exists():
                    data['path'] = target
                write(path, data)
        manifest = {'schema': 'taskfilm-version/v1', 'id': ident, 'label': label.strip(),
                    'stage': stage, 'parent': parent, 'created_at': datetime.now(timezone.utc).isoformat(),
                    'files': {p.relative_to(pending).as_posix():
                              {'sha256': media.digest(p), 'bytes': p.stat().st_size} for p in files(pending)}}
        write(pending / 'VERSION.json', manifest)
        pending.rename(self.versions / ident)
        if advance:
            head = self.root / '.HEAD-new'
            head.write_text(ident + '\n')
            head.replace(self.root / 'HEAD')
        return ident

    def _clone(self, directory):
        pending = Path(tempfile.mkdtemp(prefix='.version-', dir=self.root))
        shutil.copytree(directory, pending, dirs_exist_ok=True)
        (pending / 'VERSION.json').unlink(missing_ok=True)
        return pending

    def preview_timeline(self, directory, revision=None):
        """Use the saved movie's scene boundaries, including before newer edits."""
        revision = revision or read(directory / 'VERSION.json')
        movie = revision['files'].get('delivery.mp4')
        if not movie:
            return None
        receipt = directory / 'delivery.timeline.json'
        if receipt.is_file():
            timeline = read(receipt)
            if timeline.get('sha256') == movie['sha256']:
                return timeline
        # Older sealed versions predate timeline receipts. Find the first copy
        # of this exact delivery without changing any historical files.
        candidates = [(revision['created_at'], directory)]
        for version in self.versions.iterdir():
            manifest = version / 'VERSION.json'
            if not manifest.is_file() or version == directory:
                continue
            saved = read(manifest)
            if saved['files'].get('delivery.mp4', {}).get('sha256') == movie['sha256']:
                candidates.append((saved['created_at'], version))
        origin = min(candidates, key=lambda row: row[0])[1]
        return {'schema': 'taskfilm-delivery-timeline/v1', 'sha256': movie['sha256'],
                **scene_timeline(read(origin / 'ad.json'))}

    def _inputs(self, directory, *, legacy=False, voice_config=True):
        hash_value = lambda value: fingerprint(value, legacy=legacy)
        spec, audio, project = read(directory / 'ad.json'), read(directory / 'audio.json'), read(directory / 'project.json')
        refs = []
        brand = spec['brand']
        for key in ('logo', 'font', 'headline_font', 'font_license'):
            if brand.get(key):
                refs.append(brand[key])
        for scene in spec['scenes']:
            if scene.get('media'):
                refs.append(scene['media']['path'])
        if spec.get('presenter'):
            refs.append(spec['presenter']['path'])
        for item in [audio.get('music'), *audio.get('narration', []), *audio.get('effects', [])]:
            if item:
                refs.append(item['path'])
        hashes = {name: media.digest(inside(directory, name)) for name in set(refs)}
        visual = copy.deepcopy(spec)
        visual.pop('audio', None)
        source = {name: hashes[name] for name in refs if name.startswith('source/')}
        art = {'brief': hash_value({'project': project, 'brand': brand}),
               'capture': hash_value(source),
               'storyboard': hash_value({'ad': visual, 'assets': {n: h for n, h in hashes.items() if n not in [i.get('path') for i in [audio.get('music') or {}, *audio.get('narration', []), *audio.get('effects', [])]]}}),
               'audio': hash_value({'audio': audio, 'narration': project['narration']} if voice_config else audio)}
        art['composition'] = art['storyboard']
        art['render'] = hash_value({'visual': art['composition'], 'audio': art['audio'],
                                     'captions': project.get('captions', True), 'caption_style': 2})
        art['publish'] = hash_value({'render': art['render'], 'destinations': project['destinations'],
                                      'language': project['language'], 'publishing': project.get('publishing', {})})
        return art

    def _pipeline(self, directory, current=None):
        """Recognize valid older caches without mutating sealed checkpoints."""
        current = current or self._inputs(directory)
        pipeline = read(directory / 'pipeline.json')
        built = pipeline['built']
        if (any(value != current.get(stage) for stage, value in built.items()) or
                pipeline.get('raw_visual') not in (None, current['composition'])):
            voice_matches = pipeline.get('voice_config') == read(directory / 'project.json')['narration']
            for legacy in (self._inputs(directory, legacy=True), self._inputs(directory, voice_config=False),
                           self._inputs(directory, legacy=True, voice_config=False)):
                for stage in built:
                    if stage in ('audio', 'render', 'publish') and not voice_matches:
                        continue
                    if stage in current and built[stage] == legacy[stage]:
                        built[stage] = current[stage]
                if pipeline.get('raw_visual') == legacy['composition']:
                    pipeline['raw_visual'] = current['composition']
        return pipeline

    def import_project(self, spec_path: Path, *, audio_path: Path | None = None,
                       composition: Path | None = None, raw_video: Path | None = None,
                       delivery: Path | None = None, capture_dir: Path | None = None,
                       campaign: Path | None = None, name: str | None = None,
                       narration_host: str | None = None, voice: str | None = None):
        with self.lock:
            if (self.root / 'HEAD').exists():
                raise ValueError('Import requires a new workspace; existing versions are preserved')
            pending = Path(tempfile.mkdtemp(prefix='.version-', dir=self.root))
            try:
                spec = read(spec_path)
                prior_project = read(spec_path.parent / 'project.json') if (spec_path.parent / 'project.json').is_file() else {}
                prior_pipeline = read(spec_path.parent / 'pipeline.json') if (spec_path.parent / 'pipeline.json').is_file() else {}
                prior_inputs = None
                if (spec_path.parent / 'VERSION.json').is_file():
                    self.verify(spec_path.parent)
                    prior_inputs = self._inputs(spec_path.parent)
                    prior_pipeline = self._pipeline(spec_path.parent, prior_inputs)
                    # Reopening a full export retains all evidence and artifacts,
                    # including items no longer referenced by the latest scene.
                    shutil.copytree(spec_path.parent, pending, dirs_exist_ok=True)
                    (pending / 'VERSION.json').unlink()
                    audio_path = audio_path or spec_path.parent / 'audio.json'
                    composition = composition or (spec_path.parent / 'composition' if (spec_path.parent / 'composition').is_dir() else None)
                    raw_video = raw_video or (spec_path.parent / 'raw.mp4' if (spec_path.parent / 'raw.mp4').is_file() else None)
                    delivery = delivery or (spec_path.parent / 'delivery.mp4' if (spec_path.parent / 'delivery.mp4').is_file() else None)
                audio = read(audio_path) if audio_path else {'schema': 'taskfilm-audio/v1',
                    'duration': sum(s['duration'] for s in spec['scenes']), 'narration': []}
                assets = {}
                def collect(value, base, folder='assets'):
                    path = Path(value)
                    source = (base / path).resolve() if not path.is_absolute() else path.resolve()
                    if not source.is_file():
                        raise ValueError(f'Input file is missing: {source.name}')
                    key = media.digest(source)
                    rel = f'{folder}/{key[:20]}{source.suffix.lower()}'
                    (pending / folder).mkdir(exist_ok=True)
                    if rel not in assets:
                        shutil.copy2(source, pending / rel)
                        assets[rel] = source
                    return rel
                for key in ('logo', 'font', 'headline_font', 'font_license'):
                    if spec['brand'].get(key):
                        spec['brand'][key] = collect(spec['brand'][key], spec_path.parent)
                for scene in spec['scenes']:
                    if scene.get('media'):
                        scene['media']['path'] = collect(scene['media']['path'], spec_path.parent, 'source')
                if spec.get('presenter'):
                    spec['presenter']['path'] = collect(spec['presenter']['path'], spec_path.parent)
                if spec.get('audio'):
                    source_mix = (spec_path.parent / spec['audio']['path']).resolve()
                    shutil.copy2(source_mix, pending / 'mix.wav')
                    for suffix in ('.mix.json', '.captions.json', '.srt'):
                        if source_mix.with_suffix(suffix).is_file():
                            shutil.copy2(source_mix.with_suffix(suffix), pending / ('mix' + suffix))
                    spec['audio']['path'] = 'mix.wav'
                for item in [audio.get('music'), *audio.get('narration', []), *audio.get('effects', [])]:
                    if item:
                        base = audio_path.parent if audio_path else spec_path.parent
                        item['path'] = collect(item['path'], base)
                for index, item in enumerate(audio.get('narration', [])):
                    original = assets[item['path']]
                    receipt = original.with_suffix('.narration.json')
                    if receipt.is_file():
                        data = read(receipt)
                        baseline = prior_pipeline.get('voice_texts', [])
                        data['text'] = baseline[index] if index < len(baseline) else item.get('text')
                        write((pending / item['path']).with_suffix('.narration.json'), data)
                if capture_dir:
                    evidence = pending / 'source' / 'original'
                    evidence.mkdir(parents=True, exist_ok=True)
                    for filename in ('screen.mp4', 'session.json', 'input.jsonl', 'beats.jsonl', 'windows.jsonl'):
                        source = capture_dir / filename
                        if source.is_file():
                            shutil.copy2(source, evidence / filename)
                if composition:
                    # The user-authored HTML/project itself is part of this version.
                    shutil.copytree(composition, pending / 'composition', dirs_exist_ok=True,
                                    ignore=shutil.ignore_patterns('node_modules', '.git', '.env*'))
                for source, filename in ((raw_video, 'raw.mp4'), (delivery, 'delivery.mp4')):
                    if source:
                        shutil.copy2(source, pending / filename)
                project = {'schema': 'taskfilm-studio/v1', 'name': name or prior_project.get('name') or spec['brand']['name'],
                           'language': 'en', 'destinations': ['instagram', 'facebook', 'youtube'],
                           'captions': prior_project.get('captions', True),
                           'narration': {'provider': prior_project.get('narration', {}).get('provider', 'macos'), 'voice': voice or prior_project.get('narration', {}).get('voice', 'Samantha'),
                                        'ssh_host': narration_host or prior_project.get('narration', {}).get('ssh_host'),
                                        'rate': prior_project.get('narration', {}).get('rate', 1.0)},
                           'publishing': prior_project.get('publishing', {})}
                if prior_project.get('legacy_import'):
                    project['legacy_import'] = copy.deepcopy(prior_project['legacy_import'])
                if campaign:
                    imported = read(campaign)
                    project['publishing'] = {'title': imported.get('title', spec['brand']['name']),
                                             'caption': imported.get('caption', ''), 'status': 'needs_reconnect'}
                write(pending / 'project.json', project)
                write(pending / 'ad.json', spec)
                write(pending / 'audio.json', audio)
                visual = copy.deepcopy(spec)
                visual.pop('audio', None)
                ads.plan(visual, base_dir=pending)
                inputs = self._inputs(pending)
                built = {stage: inputs[stage] for stage in ('brief', 'capture', 'storyboard')}
                if (pending / 'mix.wav').is_file():
                    ready = not prior_inputs or prior_pipeline.get('built', {}).get('audio') == prior_inputs['audio']
                    built['audio'] = inputs['audio'] if ready else 'stale-import'
                if composition:
                    ready = not prior_inputs or prior_pipeline.get('built', {}).get('composition') == prior_inputs['composition']
                    built['composition'] = inputs['composition'] if ready else 'stale-import'
                if delivery:
                    ready = prior_inputs and prior_pipeline.get('built', {}).get('render') == prior_inputs['render']
                    built['render'] = inputs['render'] if ready else 'imported-before-caption-style-2'
                if prior_inputs and prior_pipeline.get('built', {}).get('publish') == prior_inputs['publish']:
                    built['publish'] = inputs['publish']
                write(pending / 'pipeline.json', {'built': built,
                    'raw_visual': inputs['composition'] if raw_video and (not prior_inputs or prior_pipeline.get('raw_visual') == prior_inputs['composition']) else None,
                    'voice_texts': prior_pipeline.get('voice_texts', [i.get('text') for i in audio.get('narration', [])]),
                    'voice_config': prior_pipeline.get('voice_config', project['narration'])})
                (pending / 'RESUME.md').write_text(
                    '# Complete Taskfilm version\n\nAll working inputs, source captures, editable projects and available outputs are here.\n'
                    'Files use paths relative to this directory. Previous renders are retained when stale.\n'
                    'Import this ad.json/audio.json with taskfilm studio import, or edit a copy and use taskfilm ad build.\n'
                    'VERSION.json records the full file hashes. No credentials are included.\n')
                return self._commit(pending, 'Imported complete film', 'render' if delivery else 'storyboard')
            except Exception:
                shutil.rmtree(pending, ignore_errors=True)
                raise

    def save(self, payload):
        with self.lock:
            if payload.get('base') != self.head:
                raise Conflict('A newer version exists. Reload before saving your edits.')
            original = self.directory()
            self.verify(original)
            pipeline = self._pipeline(original)
            pending = self._clone(original)
            try:
                timeline = self.preview_timeline(original)
                if timeline:
                    write(pending / 'delivery.timeline.json', timeline)
                for key in ('ad', 'audio', 'project'):
                    if key in payload:
                        if not isinstance(payload[key], dict):
                            raise ValueError(f'{key} must be an object')
                        write(pending / f'{key}.json', payload[key])
                project = read(pending / 'project.json')
                if not isinstance(project.get('name'), str) or not 1 <= len(project['name'].strip()) <= 100:
                    raise ValueError('Give your project a name of 1–100 characters')
                if project.get('language') != 'en' or project.get('destinations') != ['instagram', 'facebook', 'youtube']:
                    raise ValueError('This campaign uses English and all three destinations')
                config = project.get('narration', {})
                if set(config) != {'provider', 'voice', 'ssh_host', 'rate'}:
                    raise ValueError('Narration settings must contain provider, voice, ssh_host and rate; keep credentials in the server environment')
                if config['provider'] not in {'google', 'macos', 'deepgram', 'elevenlabs'}:
                    raise ValueError('Unsupported narration provider')
                if not isinstance(config['voice'], str) or not config['voice'].strip() or len(config['voice']) > 100:
                    raise ValueError('Choose a narration voice')
                media.number(config['rate'], 'speaking rate', .5, 2)
                if config['ssh_host'] and (config['provider'] != 'macos' or not isinstance(config['ssh_host'], str) or
                        not re.fullmatch(r'[a-zA-Z0-9_][a-zA-Z0-9_.@-]*', config['ssh_host'])):
                    raise ValueError('SSH narration needs a valid host and the macos provider')
                self._inputs(pending)  # Reject all escaping or missing file references.
                spec = read(pending / 'ad.json')
                if spec.get('audio'):
                    if not inside(pending, spec['audio']['path']).is_file():
                        raise ValueError('Saved mix file is missing')
                visual = copy.deepcopy(spec)
                visual.pop('audio', None)
                ads.plan(visual, base_dir=pending)
                audio = read(pending / 'audio.json')
                if audio.get('schema') != 'taskfilm-audio/v1' or not isinstance(audio.get('narration', []), list):
                    raise ValueError('Expected taskfilm-audio/v1 with narration clips')
                for clip in audio.get('narration', []):
                    if 'text' in clip and (not isinstance(clip['text'], str) or not clip['text'].strip()):
                        raise ValueError('Narration text cannot be empty; keep the script or remove the clip in an edited copy')
                # A changed film length updates mix duration but does not regenerate voice.
                audio['duration'] = sum(s['duration'] for s in spec['scenes'])
                write(pending / 'audio.json', audio)
                current = self._inputs(pending)
                pipeline['built'].update({key: current[key] for key in ('brief', 'capture', 'storyboard')})
                write(pending / 'pipeline.json', pipeline)
                ident = self._commit(pending, payload.get('label', 'Saved edits'), payload.get('stage', 'storyboard'), self.head)
                return self.state(ident)
            except Exception:
                shutil.rmtree(pending, ignore_errors=True)
                raise

    def restore(self, version):
        with self.lock:
            source = self.directory(version)
            self.verify(source)
            ident = self._commit(self._clone(source), f'Restored {read(source / "VERSION.json")["label"]}'[:160],
                                 read(source / 'VERSION.json')['stage'], self.head)
            return self.state(ident)

    def state(self, version=None):
        with self.lock:
            directory = self.directory(version)
            revision = read(directory / 'VERSION.json')
            current = self._inputs(directory)
            pipeline = self._pipeline(directory, current)
            stages = []
            notes = {'brief': 'English campaign · Instagram, Facebook and YouTube',
                     'capture': 'Saved real product capture. Reused when copy or audio changes.',
                     'storyboard': 'Edit scene copy, timing, crops and layout.',
                     'audio': 'Only changed narration lines regenerate. Music and voice mix separately.',
                     'composition': 'Editable HTML project. Audio changes reuse the visual render.',
                     'render': 'Previous film stays available while changes need rendering.',
                     'publish': 'Prepare a release for all three platforms. Accounts need reconnecting; posting is disabled.'}
            for key, label in STAGES:
                exists = (directory / ARTIFACTS[key]).exists()
                status = 'ready' if pipeline['built'].get(key) == current[key] and exists else ('stale' if exists else 'missing')
                stages.append({'id': key, 'label': label, 'status': status, 'note': notes[key], 'artifact': ARTIFACTS[key] if exists else None})
            timeline = self.preview_timeline(directory, revision) or {}
            return {'project': read(directory / 'project.json'), 'revision': {k: v for k, v in revision.items() if k != 'files'},
                    'versions': [{k: v for k, v in read(p / 'VERSION.json').items() if k != 'files'}
                                 for p in sorted(self.versions.iterdir(), key=lambda p: p.name)
                                 if (p / 'VERSION.json').is_file()],
                    'ad': read(directory / 'ad.json'), 'audio': read(directory / 'audio.json'), 'stages': stages,
                    'files': [{'path': name, 'bytes': rec['bytes'], 'url': f'/files/{revision["id"]}/{quote(name)}'}
                              for name, rec in revision['files'].items()],
                    'preview': {'url': f'/files/{revision["id"]}/delivery.mp4' if (directory / 'delivery.mp4').exists() else None,
                                'poster': f'/files/{revision["id"]}/preview.jpg' if (directory / 'preview.jpg').exists() else None,
                                'format': timeline.get('format', read(directory / 'ad.json').get('format', 'landscape')),
                                'stale': stages[5]['status'] != 'ready',
                                'scenes': timeline.get('scenes', [])},
                    'jobs': [{k: v for k, v in j.items() if k != 'log'} for j in self.jobs],
                    'layouts': list(templates())}

    def export(self, version):
        with self.lock:
            return self._export(version)

    def _export(self, version):
        directory = self.directory(version)
        self.verify(directory)
        destination = self.root / 'exports' / f'{version}.zip'
        destination.parent.mkdir(exist_ok=True)
        if not destination.exists():
            tmp = destination.with_suffix('.tmp')
            with zipfile.ZipFile(tmp, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as bundle:
                for path in [*files(directory), directory / 'VERSION.json']:
                    bundle.write(path, path.relative_to(directory).as_posix())
            tmp.replace(destination)
        return destination

    def run(self, base, stage):
        with self.lock:
            if base != self.head:
                raise Conflict('Run a stage from the current version, or restore this version first.')
            if stage not in dict(STAGES):
                raise ValueError('Unknown stage')
            if any(j['status'] == 'running' for j in self.jobs):
                raise Conflict('A stage is already running; its result will become a new version.')
            self.verify(self.directory(base))
            ident = uuid.uuid4().hex[:12]
            job = {'id': ident, 'stage': stage, 'status': 'running', 'message': f'Updating {dict(STAGES)[stage]}…',
                   'base': base, 'log': ''}
            self.jobs.append(job)
            threading.Thread(target=self._job, args=(job,), daemon=True).start()
            return {'job': ident}

    def _command(self, job, command, cwd=None):
        job['log'] += '\n' + ' '.join(map(str, command)) + '\n'
        with subprocess.Popen(list(map(str, command)), cwd=cwd, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, start_new_session=True,
                              stderr=subprocess.STDOUT, text=True) as process:
            def stop():
                job['log'] += '\nStage command exceeded its 10 minute limit.\n'
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            timer = threading.Timer(600, stop)
            timer.start()
            try:
                for line in process.stdout:
                    job['log'] += line
                    job['message'] = line.strip()[-220:] or job['message']
                if process.wait():
                    raise ValueError('Stage command failed. Open the job log for details.')
            finally:
                timer.cancel()

    def _job(self, job):
        pending = None
        try:
            source = self.directory(job['base'])
            pending = self._clone(source)
            timeline = self.preview_timeline(source)
            if timeline:
                write(pending / 'delivery.timeline.json', timeline)
            pipeline = self._pipeline(pending)
            current = self._inputs(pending)
            stage = job['stage']
            if stage == 'audio':
                audio = read(pending / 'audio.json')
                project = read(pending / 'project.json')
                config = project['narration']
                baseline = pipeline.get('voice_texts', [])
                for i, item in enumerate(audio.get('narration', [])):
                    if item.get('text') and (i >= len(baseline) or baseline[i] != item['text'] or pipeline.get('voice_config') != config):
                        # Voice receipts travel in the complete version. A→B→A
                        # can reuse A even after the workspace cache was lost.
                        reusable = None
                        for receipt in (pending / 'assets').glob('*.narration.json'):
                            record = read(receipt)
                            wav = receipt.parent / (receipt.name[:-len('.narration.json')] + '.wav')
                            if (record.get('text') == item['text'] and
                                    all(record.get(k) == v for k, v in config.items()) and
                                    wav.is_file() and record.get('sha256') == media.digest(wav)):
                                reusable = wav
                                break
                        if reusable:
                            item['path'] = reusable.relative_to(pending).as_posix()
                            continue
                        key = fingerprint({'text': item['text'], 'config': config})[:20]
                        cache = self.root / 'cache' / 'voice' / f'{key}.wav'
                        media.narrate(item['text'], cache, **config)
                        rel = f'assets/voice-{key}.wav'
                        shutil.copy2(cache, pending / rel)
                        shutil.copy2(cache.with_suffix('.narration.json'), (pending / rel).with_suffix('.narration.json'))
                        item['path'] = rel
                write(pending / 'audio.json', audio)
                for suffix in ('.wav', '.mix.json', '.captions.json', '.srt'):
                    (pending / ('mix' + suffix)).unlink(missing_ok=True)
                media.mix(pending / 'audio.json', pending / 'mix.wav')
                spec = read(pending / 'ad.json')
                spec['audio'] = {'path': 'mix.wav'}
                write(pending / 'ad.json', spec)
                pipeline['voice_texts'] = [i.get('text') for i in audio.get('narration', [])]
                pipeline['voice_config'] = config
            elif stage == 'composition':
                shutil.rmtree(pending / 'composition', ignore_errors=True)
                spec = read(pending / 'ad.json')
                build_composition(pending, spec)
            elif stage == 'render':
                if pipeline['built'].get('audio') != current['audio'] and (read(pending / 'audio.json').get('music') or read(pending / 'audio.json').get('narration')):
                    raise ValueError('Update Audio first. Your saved capture and visuals are reusable.')
                if pipeline['built'].get('composition') != current['composition']:
                    raise ValueError('Update Composition first. Your saved capture and narration are reusable.')
                if pipeline.get('raw_visual') != current['composition'] or not (pending / 'raw.mp4').exists():
                    (pending / 'raw.mp4').unlink(missing_ok=True)
                    self._command(job, [sys.executable, '-m', 'taskfilm', 'render', pending / 'composition',
                                        '--quality', 'looks', '--output', pending / 'raw.mp4'])
                    pipeline['raw_visual'] = current['composition']
                else:
                    job['message'] = 'Reusing the visual render; updating audio and captions…'
                joined = pending / 'joined.mp4'
                joined.unlink(missing_ok=True)
                if (pending / 'mix.wav').exists():
                    self._command(job, ['ffmpeg', '-v', 'error', '-i', pending / 'raw.mp4', '-i', pending / 'mix.wav',
                                        '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac',
                                        '-shortest', '-movflags', '+faststart', joined])
                else:
                    shutil.copy2(pending / 'raw.mp4', joined)
                (pending / 'delivery.mp4').unlink(missing_ok=True)
                (pending / 'delivery.delivery.json').unlink(missing_ok=True)
                if (pending / 'mix.captions.json').exists() and read(pending / 'project.json').get('captions', True):
                    media.finish(joined, pending / 'delivery.mp4', captions=pending / 'mix.captions.json', font_dir=pending / 'assets')
                else:
                    shutil.copy2(joined, pending / 'delivery.mp4')
                write(pending / 'delivery.timeline.json', {
                    'schema': 'taskfilm-delivery-timeline/v1',
                    'sha256': media.digest(pending / 'delivery.mp4'),
                    **scene_timeline(read(pending / 'ad.json'))})
                # Retain the uncaptioned mix as an editable stage output too.
                (pending / 'preview.jpg').unlink(missing_ok=True)
                self._command(job, ['ffmpeg', '-v', 'error', '-ss', '1.5', '-i', pending / 'delivery.mp4',
                                    '-frames:v', '1', '-vf', 'scale=540:-1', pending / 'preview.jpg'])
            elif stage == 'publish':
                if pipeline['built'].get('render') != current['render']:
                    raise ValueError('Update Render before preparing a release.')
                project = read(pending / 'project.json')
                write(pending / 'publishing.json', {'schema': 'taskfilm-release/v1', 'language': project['language'],
                    'destinations': project['destinations'], 'video': 'delivery.mp4',
                    'sha256': media.digest(pending / 'delivery.mp4'), 'metadata': project.get('publishing', {}),
                    'credits': read(pending / 'mix.mix.json').get('attribution', []) if (pending / 'mix.mix.json').exists() else [],
                    'status': 'needs_reconnect', 'live_posting_enabled': False, 'posts_sent': 0})
            elif stage == 'storyboard':
                spec = read(pending / 'ad.json')
                spec.pop('audio', None)
                ads.plan(spec, base_dir=pending)
            elif stage == 'capture':
                if not (pending / 'source').exists():
                    raise ValueError('Import a real capture first using taskfilm studio import --ad …')
            current = self._inputs(pending)
            pipeline['built'][stage] = current[stage]
            write(pending / 'pipeline.json', pipeline)
            with self.lock:
                advanced = self.head == job['base']
                ident = self._commit(pending, f'{dict(STAGES)[stage]} updated', stage, job['base'], advance=advanced)
                pending = None
                job.update(status='succeeded', version=ident,
                           message=f'{dict(STAGES)[stage]} saved as a complete version.' +
                                   ('' if advanced else ' Newer edits kept; this result is in Versions.'))
        except Exception as exc:
            job.update(status='failed', message=str(exc))
            job['log'] += '\n' + str(exc)
        finally:
            if pending:
                shutil.rmtree(pending, ignore_errors=True)


def server(workspace, host: str, port: int):
    from .project_library import ProjectLibrary
    library = workspace if isinstance(workspace, ProjectLibrary) else None
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def json(self, value, status=200):
            content = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(content)

        def send_file(self, path: Path, download=False):
            if not path.is_file():
                self.send_error(404)
                return
            length = path.stat().st_size
            begin, end, status = 0, length - 1, 200
            requested = self.headers.get('Range')
            if requested:
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested)
                if not match or not any(match.groups()):
                    self.send_error(416)
                    return
                if match[1]:
                    begin = int(match[1])
                    end = min(int(match[2]), length - 1) if match[2] else length - 1
                else:
                    begin = max(0, length - int(match[2]))
                if begin > end or begin >= length:
                    self.send_response(416)
                    self.send_header('Content-Range', f'bytes */{length}')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                status = 206
            self.send_response(status)
            self.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
            self.send_header('Content-Length', str(end - begin + 1))
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cache-Control', 'no-cache')
            if status == 206:
                self.send_header('Content-Range', f'bytes {begin}-{end}/{length}')
            if download:
                self.send_header('Content-Disposition', f'attachment; filename="taskfilm-{path.name}"')
            self.end_headers()
            if self.command != 'HEAD':
                with path.open('rb') as source:
                    source.seek(begin)
                    remaining = end - begin + 1
                    try:
                        while remaining:
                            chunk = source.read(min(remaining, 256 * 1024))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        pass

        def do_HEAD(self):
            self.do_GET()

        def context(self):
            url = urlsplit(self.path)
            path = unquote(url.path)
            prefix = ''
            if library and path.startswith('/projects/'):
                parts = path.split('/', 3)
                selected = library.workspace(parts[2])
                prefix = '/projects/' + parts[2]
                path = '/' + parts[3] if len(parts) == 4 else '/'
            else:
                selected = library.workspace() if library else workspace
            return selected, path, url, prefix

        def state(self, selected, version, prefix):
            state = selected.state(version)
            if prefix:
                for item in state['files']:
                    item['url'] = prefix + item['url']
                for key in ('url', 'poster'):
                    if state['preview'].get(key):
                        state['preview'][key] = prefix + state['preview'][key]
            return state

        def do_GET(self):
            try:
                path = urlsplit(self.path).path
                if path in ('/studio.js', '/studio.css'):
                    self.send_file(ASSETS / path[1:])
                    return
                if library and path in ('/', '/index.html', '/projects.js', '/projects.css', '/api/projects'):
                    if path == '/api/projects':
                        self.json(library.listing())
                    else:
                        self.send_file(ASSETS / ('projects.html' if path in ('/', '/index.html') else path[1:]))
                    return
                if library and path.startswith('/projects/') and path.count('/') == 2:
                    library.workspace(path.split('/')[2])
                    self.send_response(302)
                    self.send_header('Location', path + '/')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                selected, path, url, prefix = self.context()
                if path == '/api/state':
                    self.json(self.state(selected, parse_qs(url.query).get('version', [None])[0], prefix))
                elif path.startswith('/api/export/') and path.endswith('.zip'):
                    self.send_file(selected.export(path.split('/')[-1][:-4]), download=True)
                elif path.startswith('/api/log/'):
                    job = next((j for j in selected.jobs if j['id'] == path.split('/')[-1]), None)
                    self.json({'log': job['log']} if job else {'error': 'Unknown job'}, 200 if job else 404)
                elif path.startswith('/files/'):
                    _, _, version, relative = path.split('/', 3)
                    self.send_file(inside(selected.directory(version), relative))
                elif path in ('/', '/index.html', '/studio.js', '/studio.css'):
                    self.send_file(ASSETS / ('index.html' if path == '/' else path[1:]))
                else:
                    self.send_error(404)
            except FileNotFoundError:
                self.send_error(404, 'Unknown project or file')
            except (ValueError, OSError, KeyError) as exc:
                self.json({'error': str(exc)}, 400)

        def do_POST(self):
            try:
                origin = self.headers.get('Origin')
                if origin and urlsplit(origin).netloc != self.headers.get('Host'):
                    self.json({'error': 'Cross-origin writes are disabled'}, 403)
                    return
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    self.json({'error': 'Expected application/json'}, 415)
                    return
                length = int(self.headers.get('Content-Length', 0))
                if length <= 0 or length > 2_000_000:
                    raise ValueError('Request must contain a JSON object under 2 MB')
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError('Expected an object')
                if library and self.path == '/api/projects':
                    self.json(library.create(payload), 201)
                    return
                selected, path, _, prefix = self.context()
                if path == '/api/save':
                    result = selected.save(payload)
                    self.json(self.state(selected, result['revision']['id'], prefix))
                elif path == '/api/restore':
                    result = selected.restore(payload['version'])
                    self.json(self.state(selected, result['revision']['id'], prefix))
                elif path == '/api/run':
                    self.json(selected.run(payload['base'], payload['stage']))
                else:
                    self.send_error(404)
            except Conflict as exc:
                self.json({'error': str(exc)}, 409)
            except (ValueError, OSError, KeyError, TypeError) as exc:
                self.json({'error': str(exc)}, 400)
    return ThreadingHTTPServer((host, port), Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='taskfilm studio', description='Visual workflow with complete file versions and selective resume.')
    sub = parser.add_subparsers(dest='command', required=True)
    load = sub.add_parser('import', help='Import an existing film into a new portable workspace')
    load.add_argument('workspace', type=Path)
    load.add_argument('--ad', type=Path, required=True)
    for flag in ('audio', 'composition', 'raw-video', 'delivery', 'capture-dir', 'campaign'):
        load.add_argument('--' + flag, type=Path)
    load.add_argument('--name')
    load.add_argument('--narration-host')
    load.add_argument('--voice')
    legacy = sub.add_parser('import-legacy', help='Preserve a native film and import its editable scenes')
    legacy.add_argument('workspace', type=Path)
    legacy.add_argument('--spec', type=Path, required=True)
    legacy.add_argument('--movie', type=Path, required=True)
    legacy.add_argument('--format', choices=('portrait', 'landscape'), required=True)
    serve = sub.add_parser('serve', help='Open the local visual studio')
    serve.add_argument('workspace', type=Path)
    serve.add_argument('--host', default='127.0.0.1')
    serve.add_argument('--port', type=int, default=8795)
    serve.add_argument('--library', action='store_true', help='Show the Projects home and serve all registered workspaces')
    register = sub.add_parser('register', help='Add an existing workspace to a Projects library without moving its files')
    register.add_argument('library', type=Path)
    register.add_argument('workspace', type=Path)
    register.add_argument('--id')
    register.add_argument('--default', action='store_true')
    listing = sub.add_parser('list', help='List projects in a library')
    listing.add_argument('library', type=Path)
    export = sub.add_parser('export', help='Download a complete portable version ZIP')
    export.add_argument('workspace', type=Path)
    export.add_argument('--version')
    options = parser.parse_args(argv)
    try:
        from .project_library import ProjectLibrary
        if options.command == 'register':
            print(json.dumps({'project': ProjectLibrary(options.library).register(options.workspace, options.id, default=options.default)}))
            return 0
        if options.command == 'list':
            print(json.dumps(ProjectLibrary(options.library).listing()))
            return 0
        if options.command == 'import-legacy':
            from .legacy_import import import_legacy
            print(json.dumps(import_legacy(options.workspace, options.spec, options.format, options.movie)))
            return 0
        workspace = ProjectLibrary(options.workspace) if options.command == 'serve' and options.library else Workspace(options.workspace)
        if options.command == 'import':
            values = vars(options).copy()
            for key in ('command', 'workspace'):
                values.pop(key)
            spec = values.pop('ad')
            audio = values.pop('audio')
            values['audio_path'] = audio
            print(json.dumps({'version': workspace.import_project(spec, **values), 'workspace': str(workspace.root)}))
        elif options.command == 'export':
            print(workspace.export(options.version or workspace.head))
        else:
            if isinstance(workspace, Workspace):
                workspace.directory()
            app = server(workspace, options.host, options.port)
            print(f'Taskfilm Studio: http://{options.host}:{app.server_address[1]}/', flush=True)
            try:
                app.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                app.server_close()
        return 0
    except (ValueError, OSError) as exc:
        print(f'taskfilm studio: {exc}', file=sys.stderr)
        return 2
