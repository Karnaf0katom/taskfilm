"""A persistent directory of isolated, fully versioned Taskfilm projects."""
from __future__ import annotations

from datetime import datetime, timezone
import html
from pathlib import Path
import re
import shutil
import tempfile
import threading
import uuid

from . import ad, studio

ID = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}\Z')


class ProjectLibrary:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.projects = self.root / 'projects'
        self.projects.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.workspaces = {}
        self.registry = self.root / 'library.json'
        if not self.registry.exists():
            self._write({'schema': 'taskfilm-library/v1', 'default': None, 'projects': {}})

    def _write(self, data):
        pending = self.registry.with_suffix('.tmp')
        studio.write(pending, data)
        pending.replace(self.registry)

    def workspace(self, ident=None):
        data = studio.read(self.registry)
        ident = ident or data['default']
        if not isinstance(ident, str) or not ID.fullmatch(ident) or ident not in data['projects']:
            raise FileNotFoundError('Unknown project')
        with self.lock:
            if ident not in self.workspaces:
                self.workspaces[ident] = studio.Workspace(self.root / data['projects'][ident]['workspace'])
            return self.workspaces[ident]

    def register(self, workspace: Path, ident: str | None = None, *, default=False):
        workspace = workspace.resolve()
        if ident is not None and not ID.fullmatch(ident):
            raise ValueError('Project ID must contain letters, numbers, hyphens or underscores')
        with self.lock:
            data = studio.read(self.registry)
            existing = next((key for key, row in data['projects'].items() if (self.root / row['workspace']).resolve() == workspace), None)
            if existing:
                if default:
                    data['default'] = existing
                    self._write(data)
                return existing
            ident = ident or uuid.uuid4().hex[:20]
            if ident in data['projects']:
                raise ValueError('Project ID already registered')
            ws = studio.Workspace(workspace)
            ws.verify(ws.directory())
            reference = workspace.relative_to(self.root) if workspace.is_relative_to(self.root) else workspace
            data['projects'][ident] = {'workspace': str(reference), 'registered_at': datetime.now(timezone.utc).isoformat()}
            if default or not data['default']:
                data['default'] = ident
            self._write(data)
            self.workspaces[ident] = ws
            return ident

    def listing(self):
        with self.lock:
            data = studio.read(self.registry)
            result = []
            for ident in data['projects']:
                ws = self.workspace(ident)
                try:
                    folder = ws.directory()
                    version, project, spec = (studio.read(folder / name) for name in ('VERSION.json', 'project.json', 'ad.json'))
                    prefix = f'/projects/{ident}'
                    result.append({'id': ident, 'name': project['name'], 'brand': spec['brand']['name'],
                        'format': spec['format'], 'duration': sum(s['duration'] for s in spec['scenes']),
                        'updated_at': version['created_at'], 'revision': version['id'],
                        'bytes': sum(r['bytes'] for r in version['files'].values()),
                        'versions': len(list(ws.versions.glob('*/VERSION.json'))),
                        'pinned': ident == data['default'],
                        'kind': 'imported' if (folder / 'legacy-spec.json').is_file() else 'studio',
                        'has_video': (folder / 'delivery.mp4').is_file(),
                        'poster': f'{prefix}/files/{version["id"]}/preview.jpg' if (folder / 'preview.jpg').is_file() else None,
                        'video': f'{prefix}/files/{version["id"]}/delivery.mp4' if (folder / 'delivery.mp4').is_file() else None,
                        'url': prefix + '/', 'running': any(j['status'] == 'running' for j in ws.jobs)})
                except (OSError, ValueError, KeyError) as exc:
                    result.append({'id': ident, 'name': ident, 'error': str(exc), 'updated_at': '', 'url': f'/projects/{ident}/'})
            return {'projects': sorted(result, key=lambda row: (row.get('pinned', False), row['updated_at']), reverse=True), 'default': data['default']}

    def create(self, payload):
        name = payload.get('name')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ValueError('Give your project a name of 1–100 characters')
        name = name.strip()
        format = payload.get('format', 'portrait')
        if format not in ('portrait', 'landscape', 'square'):
            raise ValueError('Choose portrait, landscape or square')
        ident = uuid.uuid4().hex[:20]
        target = self.projects / ident
        ws = studio.Workspace(target)
        try:
            if payload.get('duplicate'):
                original = self.workspace(payload['duplicate'])
                with original.lock:
                    folder = original.directory()
                    original.verify(folder)
                    pending = ws._clone(folder)
                    timeline = original.preview_timeline(folder)
                    if timeline:
                        studio.write(pending / 'delivery.timeline.json', timeline)
                    project = studio.read(pending / 'project.json')
                    project['name'] = name
                    studio.write(pending / 'project.json', project)
                    pipeline = ws._pipeline(pending)
                    pipeline['built']['brief'] = ws._inputs(pending)['brief']
                    studio.write(pending / 'pipeline.json', pipeline)
                    ws._commit(pending, 'Independent project copy', 'brief')
            else:
                with tempfile.TemporaryDirectory(dir=self.root) as scratch:
                    scratch = Path(scratch)
                    logo = scratch / 'wordmark.svg'
                    logo.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="120"><text x="12" y="84" fill="#263b35" font-family="sans-serif" font-size="64">{html.escape(name)}</text></svg>')
                    spec = {'schema': 'taskfilm-ad/v1', 'id': 'new-project', 'format': format,
                        'brand': {'name': name, 'logo': str(logo), 'font': str(ad.KIT / 'Manrope.ttf'),
                                  'font_license': str(ad.KIT / 'Manrope-OFL.txt'),
                                  'colors': {'background': '#f0ebe5', 'text': '#263b35', 'accent': '#f47761'}},
                        'scenes': [{'id': 'hook', 'duration': 3, 'headline': 'Start with a clear hook.', 'layout': 'hero-stage'},
                                   {'id': 'proof', 'duration': 6, 'headline': 'Show what your product can do.', 'layout': 'quiet-card'},
                                   {'id': 'close', 'duration': 3, 'headline': 'Give people their next step.', 'layout': 'hero-stage'}]}
                    studio.write(scratch / 'ad.json', spec)
                    studio.write(scratch / 'project.json', {'narration': {'provider': 'google', 'voice': 'Kore', 'ssh_host': None, 'rate': 1.15}})
                    ws.import_project(scratch / 'ad.json', name=name)
            self.register(target, ident)
            return {'id': ident, 'url': f'/projects/{ident}/'}
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise
