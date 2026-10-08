#!/usr/bin/env python3
"""Package retained browser evidence; never record, render, execute commands or publish.

Evidence checks are producer attestations bound to retained bytes, not independent
semantic verification. Paths are relative to the input manifest; output must be new.
"""
from __future__ import annotations

import argparse
import base64
import html
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import subprocess
import tempfile
from fractions import Fraction
from urllib.parse import urlsplit


def _owner():
    name = '_demo_package_capture_provenance'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / 'capture-lane/provenance.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


provenance = _owner()


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} is required')
    return value


MAX_MANIFEST_BYTES = 2 * 1024 * 1024
DEFAULT_PROOF_BYTES = 8 * 1024 * 1024
DEFAULT_TAKE_BYTES = 256 * 1024 * 1024
MAX_PROOF_BYTES = 16 * 1024 * 1024
MAX_TAKE_BYTES = 512 * 1024 * 1024


def _limit(value, maximum, label):
    if type(value) is not int or not 0 < value <= maximum:
        raise ValueError(f'{label} must be a positive integer <= {maximum}')
    return value


def _relative_file(root, name):
    if not isinstance(name, str) or not name or "\\" in name:
        raise ValueError('evidence path must be relative and contained')
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('evidence path must be relative and contained')
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('symlink evidence is unsupported')
    if not current.resolve().is_relative_to(root.resolve()) or not current.is_file():
        raise ValueError('missing or escaping evidence file')
    return current


def _bounded_read(path, limit):
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError('evidence byte limit exceeded or file missing')
    with path.open('rb') as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError('evidence byte limit exceeded')
    return data


def _proof(ref, root, proof_limit=DEFAULT_PROOF_BYTES, budget=None):
    path = _relative_file(root, ref['path'])
    if not re.fullmatch('[0-9a-f]{64}', ref.get('sha256', '')):
        raise ValueError('missing evidence SHA-256')
    data = _bounded_read(path, proof_limit)
    if budget is not None:
        budget[0] -= len(data)
        if budget[0] < 0:
            raise ValueError('total package input byte limit exceeded')
    proof = provenance.hash_file(path)
    if proof.sha256 != ref['sha256']:
        raise ValueError(f'evidence hash mismatch: {path.name}')
    return data


def _preflight_take(root, take_limit):
    session_path = _relative_file(root, 'session.json')
    session_bytes = _bounded_read(session_path, MAX_MANIFEST_BYTES)
    session = json.loads(session_bytes)
    names = {'session.json'}
    for stream in session.get('streams', {}).values():
        if isinstance(stream, dict) and stream.get('path') is not None:
            name = stream['path']
            path = _relative_file(root, name)
            if path.parent != root or name.startswith('.'):
                raise ValueError('take stream must be a direct retained file')
            names.add(name)
    if (root / 'plan.json').exists() or (root / 'plan.json').is_symlink():
        names.add('plan.json')
    total = 0
    for name in names:
        path = _relative_file(root, name)
        size = path.stat().st_size
        if size > take_limit:
            raise ValueError('take byte limit exceeded')
        total += size
        if total > take_limit:
            raise ValueError('total take byte limit exceeded')
    return total


def _uri(data, mime):
    return f'data:{mime};base64,' + base64.b64encode(data).decode('ascii')


def _download(data, name, label):
    return f'<a download="{html.escape(name, quote=True)}" href="{_uri(data, "application/octet-stream")}">{html.escape(label)}</a>'


def build_package(take_dir, evidence_manifest_path, out_dir, *, proof_limit=DEFAULT_PROOF_BYTES, take_limit=DEFAULT_TAKE_BYTES):
    """Validate demo-evidence/v1 and atomically emit PACKAGE.json + walkthrough.html.

    See DEMO-PACKAGE.md for the manifest and assertion receipt contracts.
    """
    manifest_path = Path(evidence_manifest_path).resolve()
    root = manifest_path.parent
    _limit(proof_limit, MAX_PROOF_BYTES, 'proof_limit')
    _limit(take_limit, MAX_TAKE_BYTES, 'take_limit')
    manifest_bytes = _bounded_read(manifest_path, MAX_MANIFEST_BYTES)
    m = json.loads(manifest_bytes)
    take_dir = Path(take_dir).resolve()
    take_size = _preflight_take(take_dir, take_limit)
    budget = [take_limit - take_size - len(manifest_bytes)]
    if m.get('schema') != 'demo-evidence/v1':
        raise ValueError('expected demo-evidence/v1')
    if m.get('enhancement'):
        raise ValueError('enhancement requires a separately verified baseline/after package; unsupported in v1')
    repository = m['repository']
    url = urlsplit(repository['url'])
    if url.scheme != 'https' or not url.netloc or url.username or url.password:
        raise ValueError('repository must be a public HTTPS source URL')
    label = _text(m.get('source_label'), 'source_label')
    license_id = _text(m['license'].get('spdx'), 'license.spdx')
    license_bytes = _proof(m['license']['artifact'], root, proof_limit, budget)
    if not license_bytes.strip():
        raise ValueError('license evidence is empty')
    # A page error is refused unless the manifest names it AND says why (matching
    # repo-lane/cohort.py's gate()) — silence is what this prevents, not tolerance.
    expected = m.get('expected_page_errors') or []
    for rule in expected:
        _text(rule.get('match'), 'expected_page_errors[].match')
        _text(rule.get('why'), 'expected_page_errors[].why')
    take_dir = Path(take_dir).resolve()
    bundle = provenance.assemble_webrec_take(take_dir, repository=repository, expected_page_errors=expected)
    receipt = json.loads(bundle['take-provenance.json'])
    session = json.loads(bundle['session.json'])
    if session['steps'].get('failures') != [] or session['steps'].get('setup_problems') != []:
        raise ValueError('take has failed steps or setup problems')
    page_errors_waived = [{'error': err, 'why': next(e['why'] for e in expected if e['match'] in err)}
                          for err in session.get('page_errors') or []]
    duration = session.get('duration_s')
    if isinstance(duration, bool) or not isinstance(duration, (float, int)) or not math.isfinite(duration) or duration <= 0:
        raise ValueError('take duration must be finite and positive')
    screen_name = session['streams']['screen']['path']
    if not screen_name.endswith('.mp4'):
        raise ValueError('companion requires an MP4 screen take')
    probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=codec_name:format=duration', '-of', 'json', str(take_dir / screen_name)], capture_output=True, text=True, timeout=30)
    try:
        media = json.loads(probe.stdout)
        playable = probe.returncode == 0 and bool(media['streams'][0]['codec_name']) and float(media['format']['duration']) > 0
    except (ValueError, KeyError, IndexError):
        playable = False
    if not playable:
        raise ValueError('retained screen is not a readable video')
    duration = min(duration, float(media['format']['duration']))
    for name, key in [('session.json', 'session_sha256'), (screen_name, 'screen_sha256')]:
        actual = next(p['sha256'] for p in receipt['sources'] if p['name'] == name)
        if m['take'].get(key) != actual:
            raise ValueError(f'take {key} mismatch')
    steps = m.get('steps')
    if not isinstance(steps, list) or not steps:
        raise ValueError('at least one evidence-backed step is required')
    cards, ids, previous = [], set(), -1
    proofs = []
    for step in steps:
        sid = _text(step.get('id'), 'step.id')
        if sid in ids:
            raise ValueError('duplicate step id')
        ids.add(sid)
        title = _text(step.get('title'), 'step.title')
        claim = _text(step.get('claim'), 'step.claim')
        at = step.get('at_s')
        if isinstance(at, bool) or not isinstance(at, (int, float)) or not math.isfinite(at) or not 0 <= at < duration or at < previous:
            raise ValueError('chapter times must be ordered and inside the take')
        previous = at
        evidence_bytes = _proof(step['evidence'], root, proof_limit, budget)
        check = json.loads(evidence_bytes)
        if (check.get('schema') != 'demo-assertion/v1' or check.get('step_id') != sid
                or check.get('claim') != claim or check.get('passed') is not True
                or check.get('take') != m['take'] or check.get('at_s') != at
                or 'expected' not in check or 'observed' not in check
                or check['expected'] != check['observed']
                or check.get('method') not in {'runtime_assertion', 'visual_review'}):
            raise ValueError('unsupported or failed step claim')
        _text(check.get('producer'), 'assertion.producer')
        detail = _download(evidence_bytes, f'step-{len(cards)+1}.json', 'Download assertion receipt')
        if step.get('screenshot'):
            png = _proof(step['screenshot'], root, proof_limit, budget)
            if not png.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('step screenshot must be PNG')
            detail += f'<img alt="{html.escape(title, quote=True)}" src="{_uri(png, "image/png")}">'
            proofs.append(step['screenshot'])
        if 'command' in step:
            command = _text(step['command'], 'step.command')
            run = check.get('command_execution', {})
            if run.get('command') != command or type(run.get('exit_code')) is not int or run['exit_code'] != 0:
                raise ValueError('copy command lacks successful execution evidence')
            detail += f'<pre><code>{html.escape(command)}</code></pre><button type="button" class="copy">Copy verified command</button>'
        cards.append(f'<section><h2><button type="button" class="chapter" data-time="{at}">{html.escape(title)}</button></h2><p>{html.escape(claim)}</p><p>Evidence: {html.escape(check["method"])} by {html.escape(check["producer"])}</p>{detail}</section>')
        proofs.append(step['evidence'])
    result = m['useful_result']
    match = next((s for s in steps if s['id'] == result.get('step_id')), None)
    if match is None or match['claim'] != result.get('claim'):
        raise ValueError('useful result must match an evidenced step claim')
    title = html.escape(_text(m.get('title'), 'title'))
    waived_note = (f'<p>Page errors waived: {"; ".join(html.escape(w["error"]) + " — " + html.escape(w["why"]) for w in page_errors_waived)}</p>'
                   if page_errors_waived else '')
    document = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>*{{box-sizing:border-box}}body{{font:18px system-ui;max-width:960px;margin:auto;padding:24px;line-height:1.5;overflow-wrap:anywhere}}video,img{{max-width:100%;height:auto}}video{{width:100%}}section{{border-top:1px solid;padding:16px 0;min-width:0}}button{{font:inherit;cursor:pointer;min-height:44px;max-width:100%;padding:8px 12px;white-space:normal;overflow-wrap:anywhere;text-align:start}}pre,code,a{{overflow-wrap:anywhere;word-break:break-word}}pre{{white-space:pre-wrap;max-width:100%}}@media(max-width:480px){{body{{padding:16px}}}}</style>
<h1>{title}</h1><p>Baseline demonstration · recorded take · final reel unrendered</p><p>{html.escape(label)}</p><p><a href="{html.escape(repository['url'], quote=True)}" rel="noreferrer">Source repository</a> @ <code>{html.escape(repository['commit'])}</code> · {html.escape(license_id)}</p>
<p>{_download(license_bytes, 'LICENSE.txt', 'Download retained license notice')} · {_download(bundle['take-provenance.json'], 'take-provenance.json', 'Download take provenance')} · {_download(bundle['session.json'], 'session.json', 'Download capture session')}</p>
{waived_note}
<video id="take" controls preload="metadata" src="{_uri(bundle[screen_name], 'video/mp4')}"></video>
<p>Useful result: {html.escape(result['claim'])}</p>
{''.join(cards)}<p>Assertions are attributed producer evidence bound to this take; packaging does not independently authenticate the producer or verify the claims. License metadata is retained evidence, not blanket rights clearance.</p><p id="copy-status" role="status"></p>
<script>const video=document.getElementById('take');document.querySelectorAll('.chapter').forEach(b=>b.addEventListener('click',()=>{{video.currentTime=Number(b.dataset.time);video.focus();}}));document.querySelectorAll('.copy').forEach(b=>b.addEventListener('click',async()=>{{const value=b.previousElementSibling.textContent;try{{await navigator.clipboard.writeText(value);document.getElementById('copy-status').textContent='Command copied';}}catch(e){{const range=document.createRange();range.selectNodeContents(b.previousElementSibling);const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);document.getElementById('copy-status').textContent='Command selected. Use your copy shortcut.';}}}}));</script></html>'''
    out = Path(out_dir).resolve()
    if out.exists():
        raise FileExistsError('output directory already exists; preserve previous package')
    owner = Path(__file__).parents[1] / 'capture-lane/reel.py'
    package = {'schema': 'demo-package/v1', 'status': 'companion_ready_reel_unrendered',
               'rendered_deliverable': False, 'narration_policy': 'silent', 'repository': repository,
               'source_label': label, 'license': m['license'], 'take': receipt,
               'page_errors_waived': page_errors_waived,
               'steps': steps, 'useful_result': result, 'enhancement': None,
               'evidence': proofs, 'evidence_manifest_sha256': provenance.hash_file(manifest_path).sha256,
               'reel_plan': {'executed': False, 'argv': [sys.executable, str(owner), str(take_dir), '--out', str(out / 'reel'), '--silent', '--check'],
                             'render_argv': ['npm', 'run', 'render'], 'render_cwd': str(out / 'reel')}}
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent, prefix='.demo-package-') as temp:
        staging = Path(temp) / 'package'
        staging.mkdir()
        (staging / 'walkthrough.html').write_text(document, encoding='utf-8')
        package['companion'] = {'path': 'walkthrough.html', 'sha256': provenance.hash_file(staging / 'walkthrough.html').sha256}
        (staging / 'PACKAGE.json').write_text(json.dumps(package, indent=2) + '\n')
        staging.rename(out)
    return package


def package_from_manifest(manifest_path, out_dir, **limits):
    path = Path(manifest_path).resolve()
    m = json.loads(_bounded_read(path, MAX_MANIFEST_BYTES))
    return build_package(path.parent / m['take_dir'], path, out_dir, **limits)


def showcase_from_manifest(manifest_path, out_dir):
    """Package already-rendered, hash-bound movies and distribution downloads.

    This is a static release document, not a production UI or a film renderer.
    Movie metadata is probed again; technical/creative approval stays with the
    supplied evidence producer. The original take companion is unchanged.
    """
    path = Path(manifest_path).resolve()
    m = json.loads(_bounded_read(path, MAX_MANIFEST_BYTES))
    if m.get('schema') != 'showcase-evidence/v1':
        raise ValueError('expected showcase-evidence/v1')
    out = Path(out_dir).absolute()
    if out.exists() or out.is_symlink():
        raise FileExistsError('output must be a new directory')
    title = html.escape(_text(m.get('title'), 'title'))
    intro = html.escape(_text(m.get('intro'), 'intro'))
    version = html.escape(_text(m.get('version'), 'version'))
    movies, downloads = m.get('movies'), m.get('downloads')
    if not isinstance(movies, list) or not 1 <= len(movies) <= 8:
        raise ValueError('showcase requires one to eight movies')
    if not isinstance(downloads, list) or not 1 <= len(downloads) <= 8:
        raise ValueError('showcase requires one to eight downloads')
    budget = [DEFAULT_TAKE_BYTES]
    files, sections, links, retained, navigation = {}, [], [], [], []
    kinds = {'product_promo': 'Product film', 'feature_lesson': 'Feature lesson',
             'motion_graphics': 'Motion graphics', 'oss_walkthrough': 'OSS walkthrough',
             'recording': 'Screen recording'}
    for i, movie in enumerate(movies):
        kind = movie.get('kind', 'recording')
        if not isinstance(kind, str) or kind not in kinds:
            raise ValueError('movie kind must name a supported production option')
        data = _proof(movie, path.parent, DEFAULT_TAKE_BYTES, budget)
        source = _relative_file(path.parent, movie['path'])
        if source.suffix != '.mp4':
            raise ValueError('showcase movies must be MP4')
        probed = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
            'format=duration:stream=codec_type,width,height,r_frame_rate', '-of', 'json', str(source)],
            capture_output=True, text=True, timeout=30)
        try:
            probe = json.loads(probed.stdout)
            video = next(s for s in probe['streams'] if s['codec_type'] == 'video')
            duration = float(probe['format']['duration'])
            expected = float(movie['seconds'])
            matching = (probed.returncode == 0 and math.isfinite(expected) and expected > 0
                        and abs(duration - expected) <= .05 and video['width'] == movie['width']
                        and video['height'] == movie['height']
                        and float(Fraction(video['r_frame_rate'])) == movie['fps'])
        except (ValueError, KeyError, StopIteration, ZeroDivisionError):
            matching = False
        if not matching:
            raise ValueError('movie metadata does not match retained evidence')
        name = f'assets/movie-{i + 1}.mp4'
        files[name] = data
        retained.append({'path': name, 'sha256': movie['sha256'], 'seconds': duration, 'kind': kind,
                         'width': video['width'], 'height': video['height'], 'fps': movie['fps']})
        poster = ''
        if movie.get('poster'):
            image_bytes = _proof(movie['poster'], path.parent, DEFAULT_PROOF_BYTES, budget)
            if not image_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('showcase poster must be PNG')
            poster_name = f'assets/poster-{i + 1}.png'
            files[poster_name] = image_bytes
            poster = f' poster="{poster_name}"'
        label = html.escape(_text(movie.get('label'), 'movie.label'))
        navigation.append(f'<a href="#film-{i + 1}">{label}</a>')
        description = html.escape(_text(movie.get('description'), 'movie.description'))
        details = [f'<p>{description}</p>']
        for key, heading in (('app_description', 'About the app'),
                             ('taskfilm_description', 'Made with Taskfilm')):
            if key in movie:
                details.append(f'<p><strong>{heading}.</strong> '
                               f'{html.escape(_text(movie[key], "movie." + key))}</p>')
        resources = movie.get('links', [])
        if not isinstance(resources, list) or len(resources) > 3:
            raise ValueError('movie links must contain at most three resources')
        resource_links = []
        for resource in resources:
            if not isinstance(resource, dict):
                raise ValueError('movie link must be an object')
            url = _text(resource.get('url'), 'movie.link.url')
            parsed = urlsplit(url)
            if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                    or parsed.password or any(c.isspace() for c in url)):
                raise ValueError('movie link must be a public HTTPS URL without credentials')
            resource_label = html.escape(_text(resource.get('label'), 'movie.link.label'))
            resource_links.append(f'<a href="{html.escape(url, quote=True)}" '
                                  f'rel="noreferrer">{resource_label}</a>')
        if resource_links:
            details.append('<p>' + ' · '.join(resource_links) + '</p>')
        sections.append(f'<section class="movie" id="film-{i + 1}" data-kind="{kind}"><div class="caption"><h2>{label}</h2><span>{kinds[kind]} · {expected:g}s · {video["width"]}×{video["height"]} · {movie["fps"]}fps</span></div><video controls playsinline preload="metadata"{poster} aria-label="{label}" src="{name}"></video>{"".join(details)}</section>')
    for i, download in enumerate(downloads):
        data = _proof(download, path.parent, DEFAULT_TAKE_BYTES, budget)
        source = _relative_file(path.parent, download['path'])
        if not source.name.endswith(('.zip', '.whl', '.tar.gz')):
            raise ValueError('showcase downloads must be release archives')
        name = f'downloads/{source.name}'
        if name in files:
            raise ValueError('showcase downloads must have distinct filenames')
        files[name] = data
        label = html.escape(_text(download.get('label'), 'download.label'))
        links.append(f'<a class="download" download="{html.escape(source.name, quote=True)}" href="{html.escape(name, quote=True)}">{label}<span>{len(data) / 1024 / 1024:.1f} MB ↗</span></a>')
        retained.append({'path': name, 'sha256': download['sha256'], 'bytes': len(data)})
    document = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} — release preview</title>
<style>*{{box-sizing:border-box}}body{{margin:0;background:#f3f2ed;color:#17251f;font:17px/1.6 system-ui,sans-serif}}main{{max-width:1120px;margin:auto;padding:32px 32px 80px}}header{{display:flex;justify-content:space-between;gap:16px;border-bottom:1px solid #b9c2b8;padding-bottom:20px}}header strong{{letter-spacing:.12em}}header span,.caption span{{font-size:13px;color:#53645b}}.intro{{padding:64px 0 40px;max-width:800px}}h1{{font-size:clamp(36px,6vw,68px);line-height:1.06;letter-spacing:-.045em;margin:0 0 24px}}.intro p{{max-width:650px;font-size:20px}}.caption{{display:flex;align-items:baseline;justify-content:space-between;gap:16px;margin:24px 0 12px}}h2{{font-size:24px;line-height:1.2;margin:0}}video{{display:block;width:100%;aspect-ratio:16/9;background:#10231d;border-radius:4px}}.movie{{margin-bottom:48px}}.movie p{{max-width:740px}}.modes{{border-collapse:collapse;width:100%;margin:20px 0 40px}}td,th{{padding:16px 8px;text-align:left;border-bottom:1px solid #b9c2b8}}th{{font-size:13px;text-transform:uppercase;letter-spacing:.08em}}td:first-child{{font-weight:600}}.download{{display:flex;justify-content:space-between;align-items:center;gap:16px;min-height:56px;padding:14px 0;color:inherit;text-decoration:none;border-bottom:1px solid #b9c2b8}}.download span{{font-size:13px;color:#53645b}}a:hover{{text-decoration:underline}}a:focus-visible{{outline:3px solid #24654f;outline-offset:4px}}pre{{background:#10231d;color:#f3f2ed;padding:20px;overflow:auto;font:14px/1.8 ui-monospace,monospace;border-radius:4px}}footer{{margin-top:48px;font-size:14px;color:#53645b}}@media(max-width:600px){{main{{padding:20px 18px 48px}}.intro{{padding:40px 0 20px}}.intro p{{font-size:17px}}.caption{{display:block}}.caption span{{display:block;margin-top:8px}}td,th{{padding:12px 4px;font-size:14px}}td:first-child{{width:38%}}}}</style></head>
<body><main><header><strong>{title}</strong><span>Release preview · {version}</span></header>
<div class="intro"><h1>Real product films.<br>Editable motion.</h1><p>{intro}</p><p><a href="#watch">Watch the films</a> · <a href="#options">Explore the options</a> · <a href="#install">Get Taskfilm</a></p></div>
<section id="watch"><h2>Pick a preview</h2><p>Compare the finished films, then choose the treatment for your own workflow.</p><nav class="film-nav" aria-label="Film previews">{''.join(navigation)}</nav><div class="filters" role="group" aria-label="Filter films"><button type="button" data-filter="all" aria-pressed="true">All films</button>{''.join(f'<button type="button" data-filter="{key}" aria-pressed="false">{value}</button>' for key, value in kinds.items() if any(movie.get('kind', 'recording') == key for movie in movies))}</div><p id="filter-status" role="status" aria-live="polite">{len(movies)} films</p></section>
{''.join(sections)}
<section id="options"><h2>Choose how to make your film</h2><table class="modes"><thead><tr><th scope="col">Option</th><th scope="col">What you can make</th></tr></thead><tbody><tr><td>Recorded feature lesson</td><td>Teach a real task with readable clicks, captions and a retained result. Preview the drawDB lesson.</td></tr><tr><td>Directed product film</td><td>Kinetic titles, perspective reveals, camera moves, a result hold and a scored end card. Preview Excalidraw and the Taskboard film.</td></tr><tr><td>After Effects-style motion</td><td>Editable HTML/SVG animation: masked type, drawn paths, shape interpolation and depth. Preview the motion lab. Native Adobe .aep import is not supported.</td></tr><tr><td>OSS walkthrough</td><td>Bind a pinned repository to an actual task, native export, fit and limitation.</td></tr><tr><td>Portrait reel</td><td>Compose for 9:16 social video, or use the product-film kit's portrait layout. Landscape and portrait recipes are included.</td></tr></tbody></table><p><strong>Voice and music.</strong> Bring narration from ElevenLabs or another provider as an audio file. The product-film kit accepts your licensed WAV score or its original synthesized music. Provider generation runs separately from the local CLI.</p><p><a href="https://github.com/Karnaf0katom/taskfilm/blob/main/docs/WORKFLOWS.md">Read the production recipes</a> · <a href="https://github.com/Karnaf0katom/taskfilm/blob/main/docs/PREVIEWS.md">Compare previews and source projects</a></p></section>
<section id="install"><h2>Try it locally</h2><p>Python 3.10+, FFmpeg/FFprobe and Chromium. Rendering also needs Node.js 22+.</p><pre>python -m pip install '.[browser,motion]'
python -m playwright install chromium
taskfilm doctor
taskfilm capture check
taskfilm init demo</pre><p>Run these commands from the extracted source. The README includes the capture, story and render recipes. The sample needs no account or API key.</p>{''.join(links)}</section>
<footer><p>Local CLI + agent skill · Real browser workflows · Editable HTML/SVG</p><p>This preview plays finished movies. Creating your own film runs locally through the included CLI. Review a new capture and render before sharing it.</p></footer></main><style>.film-nav{{display:flex;flex-wrap:wrap;gap:8px 24px;margin:20px 0}}.film-nav a{{color:inherit}}.filters{{display:flex;flex-wrap:wrap;gap:8px;margin:24px 0 8px}}.filters button{{min-height:44px;padding:10px 16px;border:1px solid #b9c2b8;border-radius:4px;background:transparent;color:#17251f;font:inherit;cursor:pointer}}.filters button[aria-pressed="true"]{{background:#17251f;color:#f3f2ed;border-color:#17251f}}.filters button:focus-visible{{outline:3px solid #24654f;outline-offset:3px}}.movie[hidden]{{display:none}}#filter-status{{font-size:14px;color:#53645b}}section{{scroll-margin-top:24px}}</style><script>const films=[...document.querySelectorAll('.movie')];const buttons=[...document.querySelectorAll('[data-filter]')];function filterFilms(kind){{let count=0;films.forEach(film=>{{film.hidden=kind!=='all'&&film.dataset.kind!==kind;if(film.hidden)film.querySelector('video').pause();else count++;}});buttons.forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.filter===kind)));document.getElementById('filter-status').textContent=count+' '+(count===1?'film':'films');}}buttons.forEach(button=>button.addEventListener('click',()=>filterFilms(button.dataset.filter)));document.querySelectorAll('.film-nav a').forEach(link=>link.addEventListener('click',()=>filterFilms('all')));</script></body></html>'''
    files['index.html'] = document.encode('utf-8')
    report = {'schema': 'showcase-package/v1', 'version': m['version'], 'files': retained,
              'evidence_manifest_sha256': provenance.hash_file(path).sha256,
              'publication': 'not_performed', 'creative_review': 'producer_evidence',
              'source_evidence': m.get('source_evidence', {})}
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent, prefix='.showcase-package-') as scratch:
        stage = Path(scratch) / 'showcase'
        stage.mkdir()
        for name, data in files.items():
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (stage / 'SHOWCASE.json').write_text(json.dumps(report, indent=2) + '\n')
        stage.rename(out)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--evidence', type=Path)
    inputs.add_argument('--showcase', type=Path, help='hash-bound finished movies and release downloads')
    parser.add_argument('--take', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    if args.showcase and args.take:
        parser.error('--take is only valid with --evidence')
    result = (showcase_from_manifest(args.showcase, args.out) if args.showcase else
              build_package(args.take, args.evidence, args.out) if args.take else
              package_from_manifest(args.evidence, args.out))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
