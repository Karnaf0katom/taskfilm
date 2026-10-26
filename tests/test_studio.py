import copy
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile

import pytest

from taskfilm import ad, media, studio
from taskfilm.project_library import ProjectLibrary


@pytest.fixture
def workspace(tmp_path):
    if not shutil.which('ffmpeg'):
        pytest.skip('ffmpeg required')
    inputs = tmp_path / 'inputs'
    inputs.mkdir()
    capture = inputs / 'screen.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=30:d=3',
                    '-threads', '1', '-c:v', 'libx264', str(capture)], check=True)
    voice = inputs / 'voice.wav'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=duration=1', str(voice)], check=True)
    (inputs / 'logo.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="300" height="60"><text x="5" y="40">Studio</text></svg>')
    (inputs / 'session.json').write_text('{"steps":{"ok":2}}')
    spec = {'schema': 'taskfilm-ad/v1', 'id': 'studio-test', 'format': 'landscape',
            'brand': {'name': 'Studio', 'logo': 'logo.svg', 'font': str(ad.KIT / 'Manrope.ttf'),
                      'font_license': str(ad.KIT / 'Manrope-OFL.txt'),
                      'colors': {'background': '#f0ebe5', 'text': '#2d2b29', 'accent': '#f47761'}},
            'scenes': [{'id': 'proof', 'duration': 2, 'headline': 'See it clearly.', 'layout': 'hero-stage',
                        'media': {'type': 'video', 'path': 'screen.mp4', 'in': 0}}]}
    audio = {'schema': 'taskfilm-audio/v1', 'duration': 2,
             'narration': [{'path': 'voice.wav', 'at': .2, 'text': 'See it clearly.'}]}
    studio.write(voice.with_suffix('.narration.json'), {'text': 'See it clearly.',
        'sha256': media.digest(voice), 'provider': 'macos', 'voice': 'Samantha', 'ssh_host': None, 'rate': 1.0})
    studio.write(inputs / 'ad.json', spec)
    studio.write(inputs / 'audio.json', audio)
    media.mix(inputs / 'audio.json', inputs / 'mix.wav')
    spec['audio'] = {'path': 'mix.wav'}
    studio.write(inputs / 'ad.json', spec)
    ws = studio.Workspace(tmp_path / 'workspace')
    ws.import_project(inputs / 'ad.json', audio_path=inputs / 'audio.json', raw_video=capture,
                      delivery=capture, capture_dir=inputs)
    return ws


def wait_job(ws):
    limit = time.monotonic() + 15
    while ws.jobs[-1]['status'] == 'running' and time.monotonic() < limit:
        time.sleep(.02)
    assert ws.jobs[-1]['status'] == 'succeeded', ws.jobs[-1]


def statuses(state):
    return {s['id']: s['status'] for s in state['stages']}


def test_copy_edit_is_complete_portable_and_keeps_source_audio(workspace, tmp_path):
    ws = workspace
    old = ws.state()
    old_source = ws.directory()
    unchanged_voice = media.digest(old_source / old['audio']['narration'][0]['path'])
    edited = copy.deepcopy(old['ad'])
    edited['scenes'][0]['headline'] = 'Your numbers, clear.'
    new = ws.save({'base': ws.head, 'ad': edited, 'stage': 'storyboard', 'label': 'Headline improved'})
    assert statuses(new)['audio'] == 'ready'
    assert statuses(new)['composition'] == 'missing'
    assert statuses(new)['render'] == 'stale'
    assert ws.state(old['revision']['id'])['ad']['scenes'][0]['headline'] == 'See it clearly.'
    assert media.digest(ws.directory() / new['audio']['narration'][0]['path']) == unchanged_voice
    assert (ws.directory() / 'source/original/session.json').exists()
    bundle = ws.export(ws.head)
    extracted = tmp_path / 'extracted'
    with zipfile.ZipFile(bundle) as z:
        z.extractall(extracted)
        assert {'ad.json', 'audio.json', 'project.json', 'pipeline.json', 'VERSION.json', 'raw.mp4', 'delivery.mp4'} <= set(z.namelist())
    ws.verify(extracted)
    portable = studio.read(extracted / 'ad.json')
    ad.plan(portable, base_dir=extracted)
    assert studio.read(extracted / 'mix.mix.json')['path'] == 'mix.wav'
    for clip in studio.read(extracted / 'mix.mix.json')['inputs']:
        assert (extracted / clip['path']).is_file()
    reopened = studio.Workspace(tmp_path / 'reopened')
    reopened.import_project(extracted / 'ad.json')
    assert (reopened.directory() / 'source/original/session.json').exists()
    assert reopened.state()['audio']['narration'][0]['text'] == old['audio']['narration'][0]['text']
    assert reopened.state()['project']['narration'] == old['project']['narration']
    restore = ws.restore(old['revision']['id'])
    assert restore['revision']['id'] != old['revision']['id']
    assert restore['ad'] == old['ad']
    assert len(restore['versions']) == 3


def test_conflicts_and_mutating_saved_files_are_rejected(workspace):
    ws = workspace
    old = ws.head
    ws.save({'base': old, 'label': 'Version two'})
    with pytest.raises(studio.Conflict):
        ws.save({'base': old, 'label': 'Overwrite newer work'})
    before = ws.head
    malicious = ws.state()['ad']
    malicious['scenes'][0]['media']['path'] = '../../outside.mp4'
    with pytest.raises(ValueError, match='outside'):
        ws.save({'base': before, 'ad': malicious})
    assert ws.head == before
    empty_voice = ws.state()['audio']
    empty_voice['narration'][0]['text'] = ' '
    with pytest.raises(ValueError, match='cannot be empty'):
        ws.save({'base': before, 'audio': empty_voice})
    (ws.directory() / 'ad.json').write_text('{}')
    with pytest.raises(ValueError, match='changed on disk'):
        ws.export(before)


def test_rebuilt_composition_reopens_without_original_workspace(workspace, tmp_path):
    ws = workspace
    ws.run(ws.head, 'composition')
    wait_job(ws)
    extracted = tmp_path / 'rebuilt-export'
    with zipfile.ZipFile(ws.export(ws.head)) as bundle:
        bundle.extractall(extracted)
    shutil.rmtree(ws.root)
    shutil.rmtree(tmp_path / 'inputs')
    ws.verify(extracted)
    for filename in ('ad.json', 'AD-SOURCE.json'):
        ad.plan(extracted / 'composition' / filename)
    for filename in ('AD-PLAN.json', 'EDIT-DECISIONS.json', 'AD-SOURCE.json'):
        assert '.version-' not in (extracted / 'composition' / filename).read_text()
    reopened = studio.Workspace(tmp_path / 'rebuilt-reopened')
    reopened.import_project(extracted / 'ad.json')
    assert statuses(reopened.state())['composition'] == 'ready'


def test_preview_timing_stays_with_movie_after_edits_and_portable_reopen(workspace, tmp_path):
    ws = workspace
    baseline = ws.state()
    assert baseline['preview']['scenes'] == [{'id': 'proof', 'start': 0.0, 'end': 2.0}]
    edited = copy.deepcopy(baseline['ad'])
    edited['scenes'][0]['duration'] = 2.5
    edited['format'] = 'portrait'
    saved = ws.save({'base': ws.head, 'ad': edited})
    assert saved['preview']['scenes'] == baseline['preview']['scenes']
    assert saved['preview']['format'] == 'landscape'
    assert saved['preview']['stale']
    receipt = studio.read(ws.directory() / 'delivery.timeline.json')
    assert receipt['sha256'] == media.digest(ws.directory() / 'delivery.mp4')
    extracted = tmp_path / 'timing-export'
    with zipfile.ZipFile(ws.export(ws.head)) as bundle:
        bundle.extractall(extracted)
    shutil.rmtree(ws.root)
    shutil.rmtree(tmp_path / 'inputs')
    reopened = studio.Workspace(tmp_path / 'timing-reopened')
    reopened.import_project(extracted / 'ad.json')
    assert reopened.state()['ad']['scenes'][0]['duration'] == 2.5
    assert reopened.state()['preview']['scenes'] == baseline['preview']['scenes']
    assert reopened.state()['preview']['format'] == 'landscape'
    library = ProjectLibrary(tmp_path / 'timing-library')
    source = library.register(reopened.root)
    copied = library.create({'name': 'Independent timing copy', 'duplicate': source})
    assert library.workspace(copied['id']).state()['preview']['scenes'] == baseline['preview']['scenes']


def test_duration_edit_saves_even_while_previous_audio_is_shorter(workspace, tmp_path):
    ws = workspace
    state = ws.state()
    state['ad']['scenes'][0]['duration'] = 2.5
    saved = ws.save({'base': ws.head, 'ad': state['ad'], 'label': 'Longer scene'})
    assert saved['audio']['duration'] == 2.5
    assert statuses(saved)['audio'] == 'stale'
    extracted = tmp_path / 'longer'
    with zipfile.ZipFile(ws.export(ws.head)) as bundle:
        bundle.extractall(extracted)
    other = studio.Workspace(tmp_path / 'continued')
    other.import_project(extracted / 'ad.json')
    assert statuses(other.state())['audio'] == 'stale'


def test_changed_voice_regenerates_only_changed_line_and_reuses_render(workspace, monkeypatch):
    ws = workspace
    state = ws.state()
    edited = state['audio']
    edited['narration'][0]['text'] = 'A better explanation.'
    state = ws.save({'base': ws.head, 'audio': edited, 'stage': 'audio', 'label': 'New voice script'})
    assert statuses(state)['audio'] == 'stale'
    calls = []
    def narrate(text, path, **config):
        calls.append(text)
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ws.directory() / edited['narration'][0]['path'], path)
        studio.write(path.with_suffix('.narration.json'), {'text': text, 'sha256': media.digest(path)})
    monkeypatch.setattr(media, 'narrate', narrate)
    ws.run(ws.head, 'audio')
    wait_job(ws)
    assert calls == ['A better explanation.']
    assert statuses(ws.state())['audio'] == 'ready'
    ws.run(ws.head, 'audio')
    wait_job(ws)
    assert calls == ['A better explanation.']
    # Existing video pixels can be reused without launching HyperFrames/npm.
    pipe = studio.read(ws.directory() / 'pipeline.json')
    pipe['built']['composition'] = ws._inputs(ws.directory())['composition']
    # Test fixture lacks imported composition; create a new full checkpoint.
    pending = ws._clone(ws.directory())
    (pending / 'composition').mkdir()
    (pending / 'composition/index.html').write_text('<html></html>')
    studio.write(pending / 'pipeline.json', pipe)
    ws._commit(pending, 'Imported existing visuals', 'composition', ws.head)
    original_command = ws._command
    def command(job, args, cwd=None):
        assert 'taskfilm' not in args, 'Visual renderer should not run for audio-only edit'
        return original_command(job, args, cwd)
    monkeypatch.setattr(ws, '_command', command)
    ws.run(ws.head, 'render')
    wait_job(ws)
    assert statuses(ws.state())['render'] == 'ready'
    # Ready outputs remain ready when reopening the complete file version.
    reopened = studio.Workspace(ws.root.parent / 'ready-reopened')
    reopened.import_project(ws.directory() / 'ad.json')
    assert statuses(reopened.state())['render'] == 'ready'
    # Returning to the imported script reuses its receipt-bound clip.
    current = ws.state()
    current['audio']['narration'][0]['text'] = 'See it clearly.'
    ws.save({'base': ws.head, 'audio': current['audio'], 'stage': 'audio', 'label': 'Original voice'})
    ws.run(ws.head, 'audio')
    wait_job(ws)
    assert calls == ['A better explanation.']
    assert media.probe(ws.directory() / 'delivery.mp4')['duration'] == pytest.approx(2, abs=.1)
    receipt = studio.read(ws.directory() / 'delivery.delivery.json')
    assert receipt['source']['path'] == 'joined.mp4'
    assert (ws.directory() / receipt['source']['path']).exists()
    ws.run(ws.head, 'render')
    wait_job(ws)
    assert statuses(ws.state())['render'] == 'ready'


def test_browser_music_only_save_reuses_legacy_visuals(workspace, monkeypatch, tmp_path):
    ws = workspace
    pending = ws._clone(ws.directory())
    spec, audio = studio.read(pending / 'ad.json'), studio.read(pending / 'audio.json')
    spec['scenes'][0].update(duration=2.0)
    spec['scenes'][0]['media'].update({'in': 0.0, 'speed': 1.0})
    audio['duration'] = 2.0
    audio['music'] = {'path': audio['narration'][0]['path'], 'gain_db': -12.0,
                      'commercial_use': True, 'license': 'CC-BY-4.0',
                      'license_url': 'https://creativecommons.org/licenses/by/4.0/',
                      'attribution': 'Test tone'}
    studio.write(pending / 'ad.json', spec)
    studio.write(pending / 'audio.json', audio)
    (pending / 'mix.wav').unlink()
    media.mix(pending / 'audio.json', pending / 'mix.wav')
    visual = copy.deepcopy(spec)
    visual.pop('audio')
    ad.build(visual, pending / 'composition', base_dir=pending)
    studio.write(pending / 'publishing.json', {'posts_sent': 0})
    pipeline = studio.read(pending / 'pipeline.json')
    legacy = ws._inputs(pending, legacy=True)
    pipeline.update(built=legacy, raw_visual=legacy['composition'])
    studio.write(pending / 'pipeline.json', pipeline)
    baseline = ws._commit(pending, 'Existing float-valued checkpoint', 'render', ws.head)
    before = studio.read(ws.directory() / 'VERSION.json')
    assert set(statuses(ws.state()).values()) == {'ready'}
    ws.verify(ws.directory())
    assert studio.read(ws.directory() / 'pipeline.json') == pipeline  # No migration writes.
    # Reopening a legacy checkpoint also preserves successful stages.
    reopened = studio.Workspace(tmp_path / 'legacy-reopened')
    reopened.import_project(ws.directory() / 'ad.json')
    assert set(statuses(reopened.state()).values()) == {'ready'}
    state = ws.state()
    payload = json.loads(json.dumps({'ad': state['ad'], 'audio': state['audio'], 'project': state['project']}),
                         parse_float=lambda n: int(float(n)) if float(n).is_integer() else float(n))
    payload['audio']['music']['gain_db'] = -14
    payload.update(base=ws.head, stage='audio', label='Music volume only')
    saved = ws.save(payload)
    assert saved['ad']['scenes'][0]['duration'] == 2
    assert statuses(saved)['composition'] == 'ready'
    assert statuses(saved)['capture'] == 'ready'
    assert statuses(saved)['audio'] == statuses(saved)['render'] == 'stale'
    def refuse_narration(*args, **kwargs):
        pytest.fail('Music-only editing must not generate narration')
    monkeypatch.setattr(media, 'narrate', refuse_narration)
    original_command = ws._command
    def command(job, args, cwd=None):
        assert 'taskfilm' not in args and 'npm' not in args
        return original_command(job, args, cwd)
    monkeypatch.setattr(ws, '_command', command)
    ws.run(ws.head, 'audio')
    wait_job(ws)
    assert statuses(ws.state())['composition'] == 'ready'
    ws.run(ws.head, 'render')
    wait_job(ws)
    assert statuses(ws.state())['render'] == 'ready'
    after = studio.read(ws.directory() / 'VERSION.json')
    preserved = ['raw.mp4', state['audio']['narration'][0]['path'], state['ad']['scenes'][0]['media']['path']]
    assert all(before['files'][p] == after['files'][p] for p in preserved)
    assert before['files']['mix.wav']['sha256'] != after['files']['mix.wav']['sha256']
    assert before['files']['delivery.mp4']['sha256'] != after['files']['delivery.mp4']['sha256']
    assert statuses(ws.state(baseline))['render'] == 'ready'


def test_http_cold_seek_ranges_and_cross_origin_writes(workspace):
    app = studio.server(workspace, '127.0.0.1', 0)
    thread = threading.Thread(target=app.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{app.server_port}'
    try:
        preview = workspace.state()['preview']['url']
        with urlopen(Request(base + preview, headers={'Range': 'bytes=8-31'})) as response:
            assert response.status == 206
            assert response.headers['Content-Range'].startswith('bytes 8-31/')
            assert response.read() == (workspace.directory() / 'delivery.mp4').read_bytes()[8:32]
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base + preview, headers={'Range': 'bytes=999999999-'}))
        assert error.value.code == 416
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base + '/api/save', data=b'{}', headers={'Content-Type': 'application/json', 'Origin': 'https://untrusted.example'}))
        assert error.value.code == 403
        with urlopen(base + '/api/state') as response:
            assert json.load(response)['project']['destinations'] == ['instagram', 'facebook', 'youtube']
    finally:
        app.shutdown()
        app.server_close()


def test_provider_change_invalidates_audio_and_preserves_visuals_and_history(workspace, monkeypatch, tmp_path):
    ws = workspace
    old = ws.head
    before = ws.state()
    before_hash = media.digest(ws.directory() / 'raw.mp4')
    project = before['project']
    project['narration'] = {'provider': 'google', 'voice': 'Kore', 'ssh_host': None, 'rate': 1.1}
    changed = ws.save({'base': old, 'project': project, 'stage': 'audio'})
    assert statuses(changed)['audio'] == 'stale'
    assert statuses(changed)['render'] == 'stale'
    assert statuses(changed)['composition'] == statuses(before)['composition']
    assert ws.state(old)['project']['narration']['provider'] == 'macos'
    calls = []
    def narrate(text, output, **config):
        calls.append(config)
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ws.directory() / changed['audio']['narration'][0]['path'], output)
        studio.write(output.with_suffix('.narration.json'), {'text': text, **config, 'sha256': media.digest(output)})
    monkeypatch.setattr(media, 'narrate', narrate)
    ws.run(ws.head, 'audio'); wait_job(ws)
    ws.run(ws.head, 'audio'); wait_job(ws)
    assert calls == [project['narration']]
    assert statuses(ws.state())['audio'] == 'ready'
    assert media.digest(ws.directory() / 'raw.mp4') == before_hash
    extracted = tmp_path / 'google-project'
    with zipfile.ZipFile(ws.export(ws.head)) as bundle: bundle.extractall(extracted)
    reopened = studio.Workspace(tmp_path / 'continued-google')
    reopened.import_project(extracted / 'ad.json')
    assert reopened.state()['project']['narration'] == project['narration']
    assert statuses(reopened.state())['audio'] == 'ready'
    project['narration']['api_key'] = 'never-export-me'
    with pytest.raises(ValueError, match='credentials'):
        ws.save({'base': ws.head, 'project': project})
