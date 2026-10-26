import copy
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest
from PIL import Image

from taskfilm import ad, media
from taskfilm.legacy_import import import_legacy
from taskfilm.studio import Workspace, read, write


def ffmpeg(*args):
    subprocess.run(['ffmpeg', '-v', 'error', *map(str, args)], check=True, capture_output=True)


@pytest.fixture
def legacy(tmp_path):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('real ffmpeg and ffprobe required')
    root = tmp_path / 'legacy'
    take = root / 'takes/real'
    assets = root / 'cuts/landscape/assets'
    assets.mkdir(parents=True)
    take.mkdir(parents=True)
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=30:d=6', '-threads', '1',
           '-c:v', 'libx264', take / 'screen.mp4')
    shutil.copy2(take / 'screen.mp4', assets / 'take.mp4')
    for name in ('session.json', 'input.jsonl', 'beats.jsonl', 'windows.jsonl'):
        (take / name).write_text('{"fixture":"original capture evidence"}\n')
    for name in ('Manrope.ttf', 'Manrope-OFL.txt', 'GeistMono.ttf', 'GeistMono-OFL.txt'):
        shutil.copy2(ad.KIT / name, assets / name)
    ffmpeg('-f', 'lavfi', '-i', 'sine=frequency=220:duration=6', assets / 'mix.wav')
    movie = root / 'movie.mp4'
    ffmpeg('-i', take / 'screen.mp4', '-i', assets / 'mix.wav', '-c:v', 'copy', '-c:a', 'aac', movie)
    (assets.parent / 'index.html').write_text('<html>Original native animation</html>')
    (assets.parent / 'project.json').write_text('{"native":true}')
    spec = {'schema': 'product-motion/v1', 'id': 'test-film', 'take': 'takes/real', 'duration': 6,
            'palette': {'paper': '#f0ebe5', 'ink': '#2d2b29', 'accent': '#f47761'},
            'music': {'rights': "Original deterministic synthesis from the kit's sfx.py"},
            'copy': {'brand': {'name': 'Test Film', 'wordmark': 'testfilm', 'dot': '.'},
                     'hook': {'a': ['Find [the client.]'], 'b': ['One click.']},
                     'intro': {'tagline': ['Keep it simple.']}, 'hero': {'text': 'Real workflow'},
                     'steps': [{'title': 'Find a name.', 'sub': 'Type in the search field.'},
                               {'title': 'Match the payment.', 'sub': 'Pick the package.'},
                               {'title': 'Credits ready.', 'sub': 'See the result.'}],
                     'recap': ['Find.'], 'end': {'tagline': ['Done.'], 'url': 'github.com/example/project'}}}
    decision = {'film': 'test-film', 'format': 'landscape', 'duration': 6,
                'times': {'dive': 1, 'whip1': 2, 'find': 3, 'end': 5},
                'segments': [{'id': 'find', 'f0': 1, 'f1': 2, 's0': .5, 'rate': .5},
                             {'id': 'match', 'f0': 2, 'f1': 3, 's0': 2, 'rate': 1.5},
                             {'id': 'result', 'f0': 3, 'f1': 4, 's0': 4, 'rate': 1}],
                'music': spec['music']}
    Image.new('RGB', (160, 90), '#e57265').save(assets / 'recap-1.png', dpi=(72, 96))
    decision['recap_frames'] = [{'path': 'recap-1.png', 'source_time': 4, 'crop': [0, 0, 320, 180]}]
    write(root / 'spec.json', spec)
    write(assets.parent / 'EDIT-DECISIONS.json', decision)
    return root, movie


def statuses(state):
    return {s['id']: s['status'] for s in state['stages']}


def test_real_conversion_portable_reopen_and_edit(legacy, tmp_path):
    root, movie = legacy
    originals = {p.relative_to(root): media.digest(p) for p in root.rglob('*') if p.is_file()}
    result = import_legacy(tmp_path / 'workspace', root / 'spec.json', 'landscape', movie)
    ws = Workspace(tmp_path / 'workspace')
    directory, state = ws.directory(), ws.state()
    assert result['version'] == ws.head and result['id'] == 'test-film-landscape'
    assert len(state['versions']) == 1
    ws.verify(directory)
    assert all(statuses(state)[s] == 'ready' for s in ('capture', 'audio', 'composition', 'render'))
    assert media.digest(directory / 'delivery.mp4') == media.digest(movie)
    assert media.digest(directory / 'original/movie.mp4') == media.digest(movie)
    assert (directory / 'preview.jpg').stat().st_size > 1000
    assert (directory / 'original/native/project.json').read_bytes() == (root / 'cuts/landscape/project.json').read_bytes()
    assert (directory / 'legacy-spec.json').read_bytes() == (root / 'spec.json').read_bytes()
    for name in ('screen.mp4', 'session.json', 'input.jsonl', 'beats.jsonl', 'windows.jsonl'):
        assert media.digest(directory / 'source/original' / name) == media.digest(root / 'takes/real' / name)
    assert state['project']['narration'] == {'provider': 'google', 'voice': 'Kore', 'rate': 1.15, 'ssh_host': None}
    assert state['project']['legacy_import']['preview_is_original']
    assert state['audio']['narration'] == []
    assert not list(directory.rglob('*.narration.json'))
    assert 'CC-' not in state['audio']['music']['license']
    assert read(directory / 'pipeline.json')['voice_texts'] == []
    assert read(directory / 'pipeline.json')['raw_visual'] is None
    scenes = state['ad']['scenes']
    assert scenes[0]['headline'] == 'Find the client.'
    assert scenes[-1]['body'] == 'github.com/ example/ project'
    ad.plan({**state['ad'], 'format': 'portrait'}, base_dir=directory)
    assert scenes[2]['headline'] == 'Match the payment.'
    assert scenes[2]['media'] == {'path': 'source/take.mp4', 'type': 'video', 'in': 2.0, 'speed': 1.5}
    assert sum(s['duration'] for s in scenes) == 6
    assert scenes[-2]['media']['path'] == 'assets/recap-0.png'
    with Image.open(directory / 'assets/recap-0.png') as normalized, Image.open(directory / 'original/native/assets/recap-1.png') as original:
        assert normalized.tobytes() == original.tobytes()
        assert 'dpi' not in normalized.info
    assert all(s['media']['path'] != 'delivery.mp4' for s in scenes if s.get('media'))
    # The imported original remains byte-for-byte intact after an audio rebuild.
    media.mix(directory / 'audio.json', tmp_path / 'rebuilt.wav')
    assert (tmp_path / 'rebuilt.wav').stat().st_size > 1000
    for path, digest in originals.items():
        assert media.digest(root / path) == digest
    exported = tmp_path / 'export'
    with zipfile.ZipFile(ws.export(ws.head)) as bundle:
        bundle.extractall(exported)
    shutil.rmtree(root)
    ws.verify(exported)
    ad.plan(exported / 'ad.json')
    ad.plan(exported / 'composition/ad.json')
    ad.plan(exported / 'composition/AD-SOURCE.json')
    for name in ('AD-PLAN.json', 'EDIT-DECISIONS.json', 'AD-SOURCE.json'):
        assert '.version-' not in (exported / 'composition' / name).read_text()
    reopened = Workspace(tmp_path / 'reopened')
    reopened.import_project(exported / 'ad.json')
    assert statuses(reopened.state())['render'] == 'ready'
    assert reopened.state()['project']['legacy_import'] == state['project']['legacy_import']
    assert (reopened.directory() / 'original/native/index.html').exists()
    edited = copy.deepcopy(state['ad'])
    edited['scenes'][2]['headline'] = 'A new editable headline.'
    after = ws.save({'base': ws.head, 'ad': edited})
    assert statuses(after)['composition'] == 'stale'
    assert statuses(after)['render'] == 'stale'
    assert statuses(after)['audio'] == 'ready'
    assert after['preview']['url'] and after['preview']['stale']
    assert media.digest(ws.directory() / 'delivery.mp4') == originals[Path('movie.mp4')]
    ws.verify(directory)


@pytest.mark.parametrize('fault,match', [('missing', 'existing file'), ('trim', 'trim consumes'),
                                       ('rights', 'synthesis rights'), ('format', 'do not match')])
def test_bad_inputs_never_create_head(legacy, tmp_path, fault, match):
    root, movie = legacy
    path = root / 'cuts/landscape/EDIT-DECISIONS.json'
    decisions = read(path)
    if fault == 'missing':
        (root / 'takes/real/input.jsonl').unlink()
    elif fault == 'trim':
        decisions['segments'][0]['s0'] = 100
    elif fault == 'rights':
        decisions['music']['rights'] = 'unknown track'
    else:
        decisions['format'] = 'portrait'
    write(path, decisions)
    with pytest.raises(ValueError, match=match):
        import_legacy(tmp_path / 'workspace', root / 'spec.json', 'landscape', movie)
    assert not (tmp_path / 'workspace/HEAD').exists()
    assert not list((tmp_path / 'workspace').glob('.version-*'))


def test_existing_head_rejected_before_reading_inputs(tmp_path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'HEAD').write_text('keep me')
    with pytest.raises(ValueError, match='HEAD already exists'):
        import_legacy(workspace, tmp_path / 'absent.json', 'portrait', tmp_path / 'absent.mp4')
    assert (workspace / 'HEAD').read_text() == 'keep me'
