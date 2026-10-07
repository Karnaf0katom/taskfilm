"""Release documents retain real media bytes and reject mismatched evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


def owner():
    path = Path(__file__).parents[1] / 'demo_package.py'
    if not path.is_file():
        import taskfilm
        path = Path(taskfilm.__file__).parent / '_vendor/video/reel-lane/demo_package.py'
    spec = importlib.util.spec_from_file_location('release_showcase_owner', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def showcase(tmp_path):
    if not shutil.which('ffmpeg'):
        pytest.skip('real MP4 fixture requires FFmpeg')
    movie = tmp_path / 'fixture.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
        'color=size=64x36:duration=1:rate=30', '-c:v', 'libx264', '-threads', '1', str(movie)], check=True)
    archive = tmp_path / 'fixture.zip'
    # This tests archive retention, not an installable package or a real product capture.
    archive.write_bytes(b'explicit test-only download fixture')
    m = {'schema': 'showcase-evidence/v1', 'title': 'Fixture <preview>', 'intro': 'Original fixture',
         'version': '0.1.0a1', 'movies': [{'path': movie.name,
            'sha256': hashlib.sha256(movie.read_bytes()).hexdigest(), 'label': 'Test movie',
            'description': 'Test-only media', 'seconds': 1, 'width': 64, 'height': 36, 'fps': 30}],
         'downloads': [{'path': archive.name, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                        'label': 'Test archive'}]}
    manifest = tmp_path / 'showcase.json'
    manifest.write_text(json.dumps(m))
    return manifest, m


def test_showcase_retains_movie_and_download_and_escapes_text(showcase):
    manifest, _ = showcase
    output = manifest.parent / 'preview'
    result = owner().showcase_from_manifest(manifest, output)
    assert (output / 'assets/movie-1.mp4').read_bytes() == (manifest.parent / 'fixture.mp4').read_bytes()
    assert (output / 'downloads/fixture.zip').read_bytes() == (manifest.parent / 'fixture.zip').read_bytes()
    document = (output / 'index.html').read_text()
    assert '<preview>' not in document and '&lt;preview&gt;' in document
    assert 'controls playsinline' in document
    assert 'OSS walkthrough' in document
    assert result['publication'] == 'not_performed'
    assert result['files'][0]['seconds'] == 1
    with pytest.raises(FileExistsError):
        owner().showcase_from_manifest(manifest, output)


@pytest.mark.parametrize('fault', ['hash', 'duration', 'geometry', 'path', 'symlink', 'fake_video', 'duplicate_download'])
def test_showcase_refuses_bad_evidence_atomically(showcase, fault):
    manifest, m = showcase
    movie = m['movies'][0]
    if fault == 'hash':
        movie['sha256'] = '0' * 64
    elif fault == 'duration':
        movie['seconds'] = 31
    elif fault == 'geometry':
        movie['width'] = 1920
    elif fault == 'path':
        movie['path'] = '../fixture.mp4'
    elif fault == 'symlink':
        linked = manifest.parent / 'linked.mp4'
        linked.symlink_to(manifest.parent / movie['path'])
        movie['path'] = linked.name
    elif fault == 'fake_video':
        (manifest.parent / movie['path']).write_bytes(b'not an MP4')
        movie['sha256'] = hashlib.sha256(b'not an MP4').hexdigest()
    else:
        m['downloads'].append(dict(m['downloads'][0]))
    manifest.write_text(json.dumps(m))
    output = manifest.parent / 'rejected-preview'
    with pytest.raises(ValueError):
        owner().showcase_from_manifest(manifest, output)
    assert not output.exists()


def test_showcase_explains_app_and_taskfilm_with_source_links(showcase):
    manifest, m = showcase
    m['movies'][0].update(app_description='Diagrams <and> SQL',
                         taskfilm_description='Real footage & editable motion',
                         links=[{'label': 'Source & licence',
                                 'url': 'https://github.com/drawdb-io/drawdb'}])
    manifest.write_text(json.dumps(m))
    output = manifest.parent / 'explained-preview'
    owner().showcase_from_manifest(manifest, output)
    document = (output / 'index.html').read_text()
    assert 'About the app.</strong> Diagrams &lt;and&gt; SQL' in document
    assert 'Made with Taskfilm.</strong> Real footage &amp; editable motion' in document
    assert 'href="https://github.com/drawdb-io/drawdb"' in document
    assert 'Source &amp; licence' in document


@pytest.mark.parametrize('url', ['javascript:alert(1)',
                                 'https://' + 'user:password' + '@example.com'])
def test_showcase_refuses_unsafe_resource_links(showcase, url):
    manifest, m = showcase
    m['movies'][0]['links'] = [{'label': 'Source', 'url': url}]
    manifest.write_text(json.dumps(m))
    output = manifest.parent / 'unsafe-preview'
    with pytest.raises(ValueError, match='public HTTPS'):
        owner().showcase_from_manifest(manifest, output)
    assert not output.exists()
