import json
from pathlib import Path
import shutil
import subprocess
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile

import pytest

from taskfilm import media, studio
from taskfilm.project_library import ProjectLibrary


@pytest.fixture
def library(tmp_path):
    if not shutil.which('ffmpeg'):
        pytest.skip('ffmpeg required')
    lib = ProjectLibrary(tmp_path / 'library')
    first = lib.create({'name': 'Original project', 'format': 'portrait'})['id']
    ws = lib.workspace(first)
    pending = ws._clone(ws.directory())
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=30:d=1',
                    '-c:v', 'libx264', '-threads', '1', str(pending / 'delivery.mp4')], check=True)
    ws._commit(pending, 'Saved movie', 'render', ws.head)
    second = lib.create({'name': 'Independent copy', 'duplicate': first})['id']
    return lib, first, second


def test_library_creation_duplication_and_persistence(library):
    lib, first, second = library
    original, copied = lib.workspace(first), lib.workspace(second)
    assert media.digest(original.directory() / 'delivery.mp4') == media.digest(copied.directory() / 'delivery.mp4')
    a = original.directory() / 'ad.json'
    b = copied.directory() / 'ad.json'
    assert a.stat().st_ino != b.stat().st_ino
    assert len(list(original.versions.iterdir())) == 2
    assert len(list(copied.versions.iterdir())) == 1
    copied_ad = studio.read(b)
    copied_ad['scenes'][0]['headline'] = 'A separate creative direction.'
    copied.save({'base': copied.head, 'ad': copied_ad, 'stage': 'storyboard'})
    assert studio.read(a)['scenes'][0]['headline'] == 'Start with a clear hook.'
    reopened = ProjectLibrary(lib.root)
    rows = {row['id']: row for row in reopened.listing()['projects']}
    assert rows[first]['name'] == 'Original project' and rows[second]['name'] == 'Independent copy'
    assert rows[second]['versions'] == 2
    assert rows[first]['format'] == 'portrait'
    assert reopened.register(original.root, 'another-id') == first
    assert len(reopened.listing()['projects']) == 2


def test_invalid_creation_and_registration_leave_existing_projects(library):
    lib, first, second = library
    heads = [lib.workspace(i).head for i in (first, second)]
    for payload in [{'name': ' '}, {'name': 'Bad format', 'format': 'square/../../'},
                    {'name': 'Bad duplicate', 'duplicate': '../../private'}]:
        with pytest.raises((ValueError, FileNotFoundError)):
            lib.create(payload)
    assert [lib.workspace(i).head for i in (first, second)] == heads
    assert len(list(lib.projects.iterdir())) == 2
    with pytest.raises(ValueError):
        lib.register(lib.workspace(first).root, '../unsafe')
    with pytest.raises(FileNotFoundError):
        lib.workspace('../unsafe')


def test_project_http_routes_isolate_edits_media_exports_and_origins(library, tmp_path):
    lib, first, second = library
    app = studio.server(lib, '127.0.0.1', 0)
    worker = threading.Thread(target=app.serve_forever, daemon=True)
    worker.start()
    base = f'http://127.0.0.1:{app.server_address[1]}'
    def get(path):
        with urlopen(base + path) as response:
            return json.load(response)
    def post(path, payload, origin=None):
        headers = {'Content-Type': 'application/json'}
        if origin: headers['Origin'] = origin
        with urlopen(Request(base + path, data=json.dumps(payload).encode(), headers=headers)) as response:
            return json.load(response)
    try:
        with urlopen(base + '/') as response: assert b'Projects' in response.read()
        assert len(get('/api/projects')['projects']) == 2
        assert get('/api/state')['project']['name'] == 'Original project'
        p, q = f'/projects/{first}', f'/projects/{second}'
        state = get(p + '/api/state')
        assert state['preview']['url'].startswith(p + '/files/')
        assert all(row['url'].startswith(p + '/files/') for row in state['files'])
        old_other = get(q + '/api/state')['revision']['id']
        state['project']['name'] = 'Renamed original'
        saved = post(p + '/api/save', {'base': state['revision']['id'], 'project': state['project']})
        assert saved['project']['name'] == 'Renamed original'
        assert saved['preview']['url'].startswith(p + '/files/')
        assert get(q + '/api/state')['revision']['id'] == old_other
        with urlopen(Request(base + saved['preview']['url'], headers={'Range': 'bytes=0-99'})) as response:
            assert response.status == 206 and len(response.read()) == 100
        with pytest.raises(HTTPError):
            urlopen(base + q + '/files/' + saved['revision']['id'] + '/delivery.mp4')
        with pytest.raises(HTTPError) as error:
            post('/api/projects', {'name': 'Cross origin'}, 'https://elsewhere.example')
        assert error.value.code == 403
        made = post('/api/projects', {'name': 'Made through API', 'format': 'landscape'})
        assert get(made['url'] + 'api/state')['project']['name'] == 'Made through API'
        with urlopen(base + q + '/api/export/' + old_other + '.zip') as response:
            bundle = tmp_path / 'project.zip'; bundle.write_bytes(response.read())
        extracted = tmp_path / 'unpacked'
        with zipfile.ZipFile(bundle) as archive: archive.extractall(extracted)
        lib.workspace(second).verify(extracted)
        assert studio.read(extracted / 'project.json')['name'] == 'Independent copy'
        with pytest.raises(HTTPError) as error:
            urlopen(base + '/projects/no-such-project/api/state')
        assert error.value.code == 404
    finally:
        app.shutdown(); app.server_close(); worker.join()


def test_library_with_owned_projects_can_move_and_empty_home_serves(tmp_path):
    lib = ProjectLibrary(tmp_path / 'empty')
    app = studio.server(lib, '127.0.0.1', 0)
    thread = threading.Thread(target=app.serve_forever, daemon=True); thread.start()
    base = f'http://127.0.0.1:{app.server_address[1]}'
    try:
        for route in ['/', '/studio.css', '/projects.css', '/projects.js']:
            with urlopen(base + route) as r: assert r.status == 200 and r.read()
        with urlopen(base + '/api/projects') as r: assert json.load(r)['projects'] == []
    finally:
        app.shutdown(); app.server_close(); thread.join()
    ident = lib.create({'name': 'Portable collection'})['id']
    old = lib.workspace(ident).head
    moved = tmp_path / 'moved'
    shutil.copytree(lib.root, moved)
    shutil.rmtree(lib.root)
    reopened = ProjectLibrary(moved)
    assert reopened.workspace(ident).head == old
    reopened.workspace(ident).verify(reopened.workspace(ident).directory())
