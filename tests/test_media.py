import json
from pathlib import Path
import shutil
import subprocess

import pytest

from taskfilm import media


@pytest.fixture
def audio(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg required for real audio verification")
    def make(name, duration=1):
        path = tmp_path / name
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                        f"sine=frequency=440:duration={duration}", str(path)], check=True)
        return path
    return make


def test_music_selection_respects_mood_and_recent_use():
    tracks = [{"id": "acoustic", "tags": ["warm", "organic"]},
              {"id": "dance", "tags": ["energetic"]}]
    assert media.rank_music(tracks, ["warm"])[0]["id"] == "acoustic"
    assert media.rank_music(tracks, ["warm"], ["acoustic"])[0]["id"] == "dance"


def test_prepare_keeps_original_and_makes_seekable_video(tmp_path,audio):
    source=tmp_path/'source.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=s=320x180:r=30:d=2.2',
                    '-c:v','libx264','-g','600','-threads','1',str(source)],check=True)
    before=media.digest(source)
    result=media.prepare(source,tmp_path/'prepared.mp4')
    assert media.digest(source)==before==result['source_sha256']
    assert result['render_sha256']==media.digest(tmp_path/'prepared.mp4')
    stream=media.probe(tmp_path/'prepared.mp4')['streams'][0]
    assert (stream['width'],stream['height'])==(320,180)
    assert abs(result['duration']-2.2)<.05
    frames=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0',
        '-skip_frame','nokey','-show_frames','-show_entries','frame=best_effort_timestamp_time',
        '-of','json',str(tmp_path/'prepared.mp4')]))['frames']
    assert len(frames)>=3
    assert (tmp_path/'prepared.preparation.json').is_file()
    with pytest.raises(ValueError,match='new .mp4'):
        media.prepare(source,tmp_path/'prepared.mp4')


def test_audio_has_real_speech_music_and_provenance(tmp_path, audio):
    music = audio("music.wav", 2)
    voice = audio("voice.wav", .7)
    spec = tmp_path / "audio.json"
    spec.write_text(json.dumps({"schema": "taskfilm-audio/v1", "duration": 3,
        "music": {"path": str(music), "commercial_use": True, "license": "CC-BY-4.0",
                  "license_url": "https://creativecommons.org/licenses/by/4.0/", "attribution": "Artist credit"},
        "narration": [{"path": str(voice), "at": 1}]}))
    result = media.mix(spec, tmp_path / "mix.wav")
    assert abs(media.probe(tmp_path / "mix.wav")["duration"] - 3) < .03
    assert result["attribution"] == ["Artist credit"]
    assert result["inputs"][0]["sha256"] == media.digest(music)
    assert result["effects"]["count"] == 0
    assert (tmp_path / "mix.mix.json").is_file()


def test_narration_cannot_be_silently_cut_off(tmp_path, audio):
    voice = audio("voice.wav", 2)
    spec = tmp_path / "audio.json"
    spec.write_text(json.dumps({"schema": "taskfilm-audio/v1", "duration": 1,
                               "narration": [{"path": str(voice), "at": 0}]}))
    with pytest.raises(ValueError, match="ends after the film"):
        media.mix(spec, tmp_path / "mix.wav")


def test_effect_vocabulary_and_event_budget_are_enforced(tmp_path):
    spec = tmp_path / "audio.json"
    spec.write_text(json.dumps({"schema": "taskfilm-audio/v1", "duration": 3,
        "effects": [{"type": kind, "path": "not-needed.wav"} for kind in ["click", "boom", "sparkle"]]}))
    with pytest.raises(ValueError, match="at most two SFX types"):
        media.mix(spec, tmp_path / "mix.wav")


def test_music_cannot_be_used_without_commercial_license_metadata(tmp_path):
    spec = tmp_path / "audio.json"
    spec.write_text(json.dumps({"schema": "taskfilm-audio/v1", "duration": 3,
                               "music": {"path": "not-needed.wav"}}))
    with pytest.raises(ValueError, match="commercial-use license"):
        media.mix(spec, tmp_path / "mix.wav")


def test_ssh_host_cannot_supply_command_options(tmp_path):
    with pytest.raises(ValueError, match="valid host"):
        media.narrate("Hello", tmp_path / "voice.wav", ssh_host="-oProxyCommand=evil")


def test_narration_cache_does_not_call_provider_twice(tmp_path, audio, monkeypatch):
    wav = audio("sample.wav", .2).read_bytes()
    original = subprocess.run
    calls = []
    def run(command, **kwargs):
        if command[0] == "ssh":
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout=wav)
        return original(command, **kwargs)
    monkeypatch.setattr(media.subprocess, "run", run)
    output = tmp_path / "voice.wav"
    first = media.narrate("Hello", output, ssh_host="my-mac")
    second = media.narrate("Hello", output, ssh_host="my-mac")
    assert len(calls) == 1
    assert first["cached"] is False and second["cached"] is True
    output.write_bytes(b"changed")
    with pytest.raises(ValueError, match="different inputs"):
        media.narrate("Hello", output, ssh_host="my-mac")


def test_finish_burns_timed_captions_and_preserves_audio(tmp_path, audio):
    sound=audio("voice.wav",1)
    video=tmp_path/"source.mp4"
    subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i","color=c=white:s=320x180:d=1",
                    "-i",str(sound),"-c:v","libx264","-c:a","aac","-shortest",str(video)],check=True)
    captions=tmp_path/"captions.json"
    captions.write_text(json.dumps([{"start":0.1,"end":.9,"text":"A real result."}]))
    result=media.finish(video,tmp_path/"finished.mp4",captions=captions)
    actual=media.probe(tmp_path/"finished.mp4")
    assert {s['codec_type'] for s in actual['streams']} == {'video','audio'}
    assert abs(actual['duration']-1)<.1
    assert result['source']['sha256']==media.digest(video)
    assert result['captions']==str(captions)


def test_finish_checks_presenter_timing_before_overlay(tmp_path, audio):
    video=tmp_path/"source.mp4"
    presenter=tmp_path/"presenter.mp4"
    for path,duration in [(video,1),(presenter,2)]:
        subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i",f"color=c=white:s=320x180:d={duration}",
                        "-c:v","libx264",str(path)],check=True)
    with pytest.raises(ValueError,match="extend beyond"):
        media.finish(video,tmp_path/"finished.mp4",presenter=presenter,presenter_at=.5)


def test_finish_overlays_presenter_without_replacing_ad_audio(tmp_path, audio):
    sound=audio('sound.wav',1)
    video=tmp_path/'source.mp4'
    presenter=tmp_path/'presenter.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=white:s=640x360:d=1',
                    '-i',str(sound),'-c:v','libx264','-c:a','aac','-shortest',str(video)],check=True)
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=red:s=120x160:d=0.5',
                    '-c:v','libx264',str(presenter)],check=True)
    output=tmp_path/'finished.mp4'
    media.finish(video,output,presenter=presenter,presenter_at=.25)
    assert {s['codec_type'] for s in media.probe(output)['streams']}=={'audio','video'}
    from PIL import Image
    import io
    frame=subprocess.run(['ffmpeg','-v','error','-ss','0.5','-i',str(output),
                          '-frames:v','1','-f','image2pipe','-vcodec','png','-'],
                         capture_output=True,check=True).stdout
    rgb=Image.open(io.BytesIO(frame)).convert('RGB').tobytes()
    assert sum(r>180 and g<80 and b<80 for r,g,b in zip(rgb[0::3],rgb[1::3],rgb[2::3]))>1000


def test_google_narration_real_wav_cache_and_secret_free_receipt(tmp_path, audio, monkeypatch):
    import base64
    import io
    pcm = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(audio('provider.wav', 1)),
                                   '-ar', '24000', '-ac', '1', '-f', 's16le', '-'])
    requests = []
    def request(req, timeout):
        requests.append(req)
        assert req.get_header('X-goog-api-key') == 'test-secret'
        payload = json.loads(req.data)
        assert payload['contents'][0]['parts'][0]['text'].endswith('Hello.')
        assert payload['generationConfig']['speechConfig']['voiceConfig']['prebuiltVoiceConfig']['voiceName'] == 'Kore'
        return io.BytesIO(json.dumps({'candidates': [{'content': {'parts': [
            {'inlineData': {'mimeType': 'audio/L16;codec=pcm;rate=24000', 'data': base64.b64encode(pcm).decode()}}]}}]}).encode())
    monkeypatch.delenv('TASKFILM_GOOGLE_KEY_REF', raising=False)
    monkeypatch.setenv('GOOGLE_API_KEY', 'test-secret')
    monkeypatch.setattr(media, 'urlopen', request)
    out = tmp_path / 'google.wav'
    first = media.narrate('Hello.', out, provider='google', rate=1.5)
    assert .60 < first['duration'] < .75
    assert first['voice'] == 'Kore' and first['model'] == media.GOOGLE_TTS_MODEL
    assert media.narrate('Hello.', out, provider='google', rate=1.5)['cached']
    assert len(requests) == 1
    third = media.narrate('Hello.', tmp_path / 'slower.wav', provider='google', rate=1)
    assert .95 < third['duration'] < 1.05 and len(requests) == 1
    assert 'test-secret' not in out.with_suffix('.narration.json').read_text()


def test_google_errors_do_not_expose_provider_credentials(tmp_path, monkeypatch):
    import io
    from urllib.error import HTTPError
    monkeypatch.delenv('TASKFILM_GOOGLE_KEY_REF', raising=False)
    monkeypatch.setenv('GOOGLE_API_KEY', 'test-secret')
    def fail(req, timeout):
        raise HTTPError(req.full_url, 403, 'test-secret', {}, io.BytesIO(b'test-secret'))
    monkeypatch.setattr(media, 'urlopen', fail)
    with pytest.raises(ValueError) as error:
        media.narrate('Hello.', tmp_path / 'voice.wav', provider='google')
    assert 'HTTP 403' in str(error.value) and 'test-secret' not in str(error.value)
    assert not (tmp_path / 'voice.wav').exists()
