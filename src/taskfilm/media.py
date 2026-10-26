"""Reusable narration, licensed music selection, and restrained ad audio mixes."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from functools import lru_cache
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import wave
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


GOOGLE_TTS_MODEL = 'gemini-2.5-flash-preview-tts'
GOOGLE_TTS_STYLE = 'English, warm and confident, brisk conversational delivery for a short product ad. No long pauses.'


@lru_cache(maxsize=4)
def _referenced_google_key(reference: str) -> str:
    """Read a server-owned credential reference without duplicating its file."""
    match = re.fullmatch(r'([a-zA-Z0-9_][a-zA-Z0-9_.@-]*):(/[^\n]+)#([A-Z_][A-Z_0-9]*)', reference)
    if not match:
        raise ValueError('Google key reference must be host:/absolute/env/file#VARIABLE')
    host, path, variable = match.groups()
    code = ('import json,sys;from pathlib import Path;p=json.load(sys.stdin);'
            'lines=Path(p["path"]).read_text().splitlines();'
            'v=next((l.partition("=")[2].strip().strip(chr(34)+chr(39)) for l in lines '
            'if l.partition("=")[0].strip()==p["variable"]),"");sys.stdout.write(v)')
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', host,
                             shlex.join(['python3', '-c', code])],
                            input=json.dumps({'path': path, 'variable': variable}).encode(),
                            capture_output=True, timeout=30)
    if result.returncode or not result.stdout.strip():
        raise ValueError('Could not read the referenced Google credential')
    return result.stdout.decode().strip()


def google_speech(text: str, voice: str, output: Path) -> None:
    """Generate speech directly from this host. Never persist credentials."""
    reference = os.environ.get('TASKFILM_GOOGLE_KEY_REF')
    key = os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_API_KEY')
    if reference:
        key = _referenced_google_key(reference)
    if not key:
        raise ValueError('Google narration needs GOOGLE_API_KEY or GEMINI_API_KEY in the server environment')
    payload = {'contents': [{'parts': [{'text': f'{GOOGLE_TTS_STYLE}\nRead exactly this text: {text}'}]}],
               'generationConfig': {'responseModalities': ['AUDIO'], 'speechConfig': {
                   'voiceConfig': {'prebuiltVoiceConfig': {'voiceName': voice}}}}}
    request = Request(f'https://generativelanguage.googleapis.com/v1beta/models/{GOOGLE_TTS_MODEL}:generateContent',
                      data=json.dumps(payload).encode(), headers={
                          'Content-Type': 'application/json', 'x-goog-api-key': key})
    try:
        with urlopen(request, timeout=120) as response:
            result = json.load(response)
    except HTTPError as exc:
        # Provider bodies may contain credentials; keep errors status-only.
        raise ValueError(f'Google narration failed (HTTP {exc.code}); check account access and quota') from None
    except (URLError, TimeoutError):
        raise ValueError('Google narration could not reach the speech service') from None
    try:
        blocks = [p['inlineData'] for p in result['candidates'][0]['content']['parts'] if 'inlineData' in p]
        audio = blocks[0]
        pcm = base64.b64decode(audio['data'], validate=True)
        if audio['mimeType'].lower() not in ('audio/l16;codec=pcm;rate=24000', 'audio/l16;rate=24000') or not pcm or len(pcm) % 2:
            raise ValueError('Not 24 kHz PCM')
    except (KeyError, IndexError, ValueError, TypeError):
        raise ValueError('Google narration returned no valid PCM audio') from None
    with wave.open(str(output), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(pcm)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def probe(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f"Media does not exist: {path}")
    result = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams",
                             "-of", "json", str(path)], capture_output=True, text=True)
    if result.returncode:
        raise ValueError(f"Cannot read media: {path}")
    data = json.loads(result.stdout)
    data["duration"] = float(data.get("format", {}).get("duration", 0))
    return data


def number(value, name: str, minimum: float, maximum: float) -> float:
    value = float(value)
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def load_library(path: Path) -> list[dict]:
    document = json.loads(path.read_text())
    if document.get("schema") != "taskfilm-music/v1":
        raise ValueError("Expected taskfilm-music/v1 music library")
    tracks = document.get("tracks", [])
    seen = set()
    for track in tracks:
        for key in ("id", "title", "artist", "license", "license_url", "attribution", "tags"):
            if key not in track:
                raise ValueError(f"Music track is missing {key}")
        if track["id"] in seen or not re.fullmatch(r"[a-zA-Z0-9_-]+", track["id"]):
            raise ValueError("Music IDs must be unique safe filenames")
        seen.add(track["id"])
        if not isinstance(track["tags"], list):
            raise ValueError("Music tags must be a list")
    return tracks


def rank_music(tracks: list[dict], tags: list[str], recent: list[str] = ()) -> list[dict]:
    wanted = {tag.lower() for tag in tags}
    rows = []
    for track in tracks:
        score = 4 * len(wanted.intersection(tag.lower() for tag in track["tags"]))
        score -= 8 if track["id"] in recent else 0
        rows.append({**track, "score": score})
    return sorted(rows, key=lambda row: (-row["score"], row["id"]))


def fetch_music(library: Path, track_id: str, destination: Path) -> Path:
    track = next((t for t in load_library(library) if t["id"] == track_id), None)
    if not track:
        raise ValueError(f"Unknown music track: {track_id}")
    source = track.get("download_url", "")
    if urlparse(source).scheme != "https":
        raise ValueError("Music download URL must use HTTPS")
    destination.mkdir(parents=True, exist_ok=True)
    audio = destination / f"{track_id}.mp3"
    if audio.exists():
        recorded = destination / f"{track_id}.json"
        if not recorded.is_file() or json.loads(recorded.read_text()).get("sha256") != digest(audio):
            raise ValueError("Existing music has no matching provenance record")
        return audio
    with tempfile.TemporaryDirectory(dir=destination) as scratch:
        candidate = Path(scratch) / "download.mp3"
        with urlopen(source, timeout=60) as response, candidate.open("wb") as output:
            if urlparse(response.geturl()).scheme != "https":
                raise ValueError("Music download redirected away from HTTPS")
            shutil.copyfileobj(response, output)
        if not any(s.get("codec_type") == "audio" for s in probe(candidate)["streams"]):
            raise ValueError("Downloaded music has no audio stream")
        provenance = {**track, "path": audio.name, "sha256": digest(candidate)}
        candidate.replace(audio)
        (destination / f"{track_id}.json").write_text(json.dumps(provenance, indent=2) + "\n")
    return audio


def _audio_path(base: Path, item: dict) -> tuple[Path, float]:
    path = (base / item["path"]).resolve()
    data = probe(path)
    if not any(s.get("codec_type") == "audio" for s in data["streams"]):
        raise ValueError(f"No audio stream: {path}")
    if not 0 < data["duration"] < math.inf:
        raise ValueError(f"Invalid audio duration: {path}")
    return path, data["duration"]


def mix(spec_path: Path, output: Path) -> dict:
    """Mix real music + timed voice clips; speech drives side-chain ducking."""
    spec = json.loads(spec_path.read_text())
    if spec.get("schema") != "taskfilm-audio/v1":
        raise ValueError("Expected taskfilm-audio/v1 audio spec")
    duration = number(spec["duration"], "duration", 0.5, 600)
    music = spec.get("music")
    voices = spec.get("narration", [])
    cues = spec.get("effects", [])
    if len({c.get("type") for c in cues}) > 2 or len(cues) > 4:
        raise ValueError("Ads allow at most two SFX types and four SFX events")
    if not music and not voices and not cues:
        raise ValueError("Audio mix has no inputs")
    inputs, filters, manifest, captions = [], [], [], []
    channels = []
    index = 0
    if music:
        if music.get("commercial_use") is not True or not music.get("license") or not music.get("license_url"):
            raise ValueError("Music requires its commercial-use license record")
        if music.get("attribution_required", True) and not music.get("attribution"):
            raise ValueError("Music requires attribution text")
        path, length = _audio_path(spec_path.parent, music)
        offset = number(music.get("in", 0), "music offset", 0, length)
        if offset >= length:
            raise ValueError("Music offset must be inside the track")
        inputs += ["-stream_loop", "-1", "-i", str(path)]
        gain = number(music.get("gain_db", -12), "music gain", -60, 0)
        filters.append(f"[0:a]atrim=start={offset}:duration={duration},asetpts=PTS-STARTPTS,"
                       f"aresample=48000,aformat=channel_layouts=stereo,volume={gain}dB,"
                       f"afade=t=in:d=0.4,afade=t=out:st={max(0,duration-.8)}:d=0.8[bed]")
        manifest.append({**music, "path": str(path), "sha256": digest(path)})
        index += 1
    for group, items in (("voice", voices), ("effect", cues)):
        group_channels = []
        for ordinal, item in enumerate(items):
            path, length = _audio_path(spec_path.parent, item)
            at = number(item.get("at", 0), "audio start", 0, duration)
            if at + length > duration + 0.05:
                raise ValueError(f"{group} at {at}s ends after the film; revise duration or narration")
            gain = number(item.get("gain_db", 0 if group == "voice" else -16), "audio gain", -60, 6)
            channel = f"{group}{ordinal}"
            inputs += ["-i", str(path)]
            filters.append(f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo,"
                           f"volume={gain}dB,adelay={round(at*1000)}:all=1,"
                           f"apad,atrim=duration={duration}[{channel}]")
            group_channels.append(f"[{channel}]")
            manifest.append({**item, "kind": group, "path": str(path), "sha256": digest(path)})
            if group == "voice" and item.get("text"):
                captions.append({"start": at, "end": at+length,
                                 "text": re.sub(r"\s+", " ", item["text"]).strip()})
            index += 1
        if group_channels:
            filters.append("".join(group_channels) +
                           f"amix=inputs={len(group_channels)}:normalize=0:duration=longest[{group}]")
            channels.append(f"[{group}]")
    if music and voices:
        filters += ["[voice]asplit=2[speech][sidechain]",
                    "[bed][sidechain]sidechaincompress=threshold=0.03:ratio=6:attack=30:release=300[ducked]"]
        channels[channels.index("[voice]")] = "[speech]"
        channels.insert(0, "[ducked]")
    elif music:
        channels.insert(0, "[bed]")
    filters.append("".join(channels) + f"amix=inputs={len(channels)}:normalize=0:duration=longest,"
                   f"atrim=duration={duration},loudnorm=I=-16:TP=-1.5:LRA=11[out]")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError("Mix output must be a new file")
    cmd = ["ffmpeg", "-v", "error", *inputs, "-filter_complex", ";".join(filters),
           "-map", "[out]", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(output)]
    subprocess.run(cmd, check=True)
    result = {"schema": "taskfilm-audio-mix/v1", "duration": duration,
              "path": str(output.resolve()), "sha256": digest(output), "inputs": manifest,
              "attribution": [music["attribution"]] if music and music.get("attribution") else [],
              "effects": {"types": sorted({c.get("type", "") for c in cues}), "count": len(cues)}}
    output.with_suffix(".mix.json").write_text(json.dumps(result, indent=2) + "\n")
    if captions:
        output.with_suffix(".captions.json").write_text(json.dumps(captions, indent=2) + "\n")
        def stamp(t):
            ms = round(t*1000)
            return f"{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}"
        output.with_suffix(".srt").write_text("\n\n".join(
            f"{i+1}\n{stamp(c['start'])} --> {stamp(c['end'])}\n{c['text']}" for i,c in enumerate(captions))+"\n")
    return result


def narrate(text: str, output: Path, provider: str = "macos", voice: str | None = None,
            ssh_host: str | None = None, rate: float = 1.0) -> dict:
    if not text.strip():
        raise ValueError("Narration text cannot be empty")
    rate = number(rate, "speaking rate", 0.5, 2)
    if output.suffix.lower() != ".wav":
        raise ValueError("Narration output must be a .wav file")
    if ssh_host and (provider != "macos" or not re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_.@-]*", ssh_host)):
        raise ValueError("SSH narration needs a valid host and the macos provider")
    config = {"provider": provider, "voice": voice, "ssh_host": ssh_host, "rate": rate}
    if provider == 'google':
        config['voice'] = voice = voice or 'Kore'
    recipe = {'model': GOOGLE_TTS_MODEL, 'style': GOOGLE_TTS_STYLE} if provider == 'google' else {}
    key = hashlib.sha256(json.dumps({**config, **recipe, "text": text}, sort_keys=True).encode()).hexdigest()
    receipt = output.with_suffix(".narration.json")
    if output.exists():
        if receipt.exists():
            existing = json.loads(receipt.read_text())
            if existing.get("cache_key") == key and existing.get("sha256") == digest(output):
                return {**existing, "cached": True}
        raise ValueError("Narration output exists with different inputs or no matching receipt")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as scratch:
        raw = Path(scratch) / "voice.wav"
        if provider == "macos":
            chosen = voice or "Samantha"
            cmd = ["say", "-v", chosen, "-r", str(round(170 * rate)), "--file-format=WAVE",
                   "--data-format=LEI16@24000", "-o", str(raw), "-f", "-"]
            if ssh_host:
                code = (
                    "import json,sys,tempfile,subprocess;from pathlib import Path;"
                    "p=json.load(sys.stdin);"
                    "d=tempfile.TemporaryDirectory();f=Path(d.name)/'voice.wav';"
                    "subprocess.run(['say','-v',p['voice'],'-r',str(p['wpm']),"
                    "'--file-format=WAVE','--data-format=LEI16@24000','-o',str(f),'-f','-'],"
                    "input=p['text'].encode(),check=True,stdout=subprocess.DEVNULL);"
                    "sys.stdout.buffer.write(f.read_bytes());d.cleanup()"
                )
                result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                                         ssh_host, shlex.join(["python3", "-c", code])],
                                        input=json.dumps({"text": text, "voice": chosen,
                                                          "wpm": round(170*rate)}).encode(),
                                        capture_output=True, timeout=120)
                if result.returncode:
                    raise ValueError("Remote local narration failed; check SSH access and installed voice")
                raw.write_bytes(result.stdout)
            else:
                subprocess.run(cmd, input=text.encode(), check=True, stdout=subprocess.DEVNULL)
        elif provider == 'google':
            native_key = hashlib.sha256(json.dumps({'text': text, 'voice': voice, **recipe}, sort_keys=True).encode()).hexdigest()
            native = output.parent / '.google-source' / f'{native_key}.wav'
            native_receipt = native.with_suffix('.json')
            if (native.is_file() and native_receipt.is_file() and
                    json.loads(native_receipt.read_text()).get('sha256') == digest(native)):
                shutil.copy2(native, raw)
            else:
                google_speech(text, voice, raw)
                native.parent.mkdir(exist_ok=True)
                shutil.copy2(raw, native)
                native_receipt.write_text(json.dumps({'sha256': digest(native), 'cache_key': native_key}) + '\n')
        elif provider in {"elevenlabs", "deepgram"}:
            try:
                from video_claw import tts
                from video_claw.cache import Cache
            except ImportError as exc:
                raise ValueError("Install video-claw to use provider narration") from exc
            function = getattr(tts, f"make_audio_{provider}")
            settings = {"speaking_rate": rate}
            if voice:
                settings["voice_id" if provider == "elevenlabs" else "deepgram_voice"] = voice
            source, _ = function(text, 0, workdir=Path(scratch),
                                 cache=Cache(output.parent / ".narration-cache"), tts_cfg=settings)
            raw = source
        else:
            raise ValueError(f"Unsupported narration provider: {provider}")
        tempo = ['-af', f'atempo={rate}'] if provider == 'google' and rate != 1 else []
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(raw), *tempo, "-ar", "48000", "-ac", "1",
                        "-c:a", "pcm_s16le", str(output)], check=True)
    result = {"schema": "taskfilm-narration/v1", **config, **recipe, "cache_key": key, "text": text,
              "duration": probe(output)["duration"], "path": str(output.resolve()),
              "sha256": digest(output), "cached": False}
    receipt.write_text(json.dumps(result, indent=2) + "\n")
    return result


def avatar(audio: Path, image: Path, output: Path) -> dict:
    """Reuse video-claw's content-cached fal.ai presenter generation."""
    try:
        from video_claw.cache import Cache
        from video_claw.lipsync import fal_omnihuman_lipsync
    except ImportError as exc:
        raise ValueError("Install video-claw to generate a lip-synced presenter") from exc
    probe(audio)
    if not image.is_file() or output.exists():
        raise ValueError("Presenter needs an existing image and a new output file")
    output.parent.mkdir(parents=True, exist_ok=True)
    source = fal_omnihuman_lipsync(audio, image, cache=Cache(output.parent / ".presenter-cache"))
    shutil.copy2(source, output)
    return {"path": str(output.resolve()), "duration": probe(output)["duration"],
            "sha256": digest(output), "provider": "video-claw/fal.ai"}


def finish(video: Path, output: Path, *, captions: Path | None = None,
           presenter: Path | None = None, presenter_at: float = 0, presenter_size: float = .18,
           font_dir: Path | None = None) -> dict:
    """Burn scene-timed captions and optionally overlay an existing lip-sync clip.

    Presenter audio is discarded: the ad's timed narration/music remains intact.
    A short opening/closing presenter clip leaves the product demonstration clear.
    """
    if output.exists() or output.suffix.lower() != ".mp4":
        raise ValueError("Finished output must be a new .mp4 file")
    info = probe(video)
    stream = next((s for s in info["streams"] if s.get("codec_type") == "video"), None)
    if stream is None:
        raise ValueError("Finish input must contain video")
    w,h = stream["width"],stream["height"]
    duration = info["duration"]
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as scratch:
        scratch = Path(scratch)
        inputs = ["-i",str(video.resolve())]
        filters = []
        label = "0:v"
        if presenter:
            presenter_info = probe(presenter)
            at = number(presenter_at, "presenter start", 0, duration)
            if at+presenter_info["duration"] > duration+.05:
                raise ValueError("Presenter clip would extend beyond the ad")
            size = round(w*number(presenter_size,"presenter size", .10,.30)/2)*2
            inputs += ["-i",str(presenter.resolve())]
            filters.append(f"[1:v]scale={size}:{size}:force_original_aspect_ratio=increase,"
                           f"crop={size}:{size},format=rgba,"
                           "geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                           f"a='if(lte(pow(X-{size}/2,2)+pow(Y-{size}/2,2),pow({size}/2,2)),255,0)',"
                           f"setpts=PTS-STARTPTS+{at}/TB[presenter]")
            margin = round(w*.045)
            bottom = 350 if h>w else 100
            filters.append(f"[0:v][presenter]overlay=x=W-w-{margin}:y=H-h-{bottom}:"
                           f"enable='between(t,{at},{at+presenter_info['duration']})':eof_action=pass[withpresenter]")
            label = "withpresenter"
        if captions:
            rows=json.loads(captions.read_text())
            if not isinstance(rows,list):
                raise ValueError("Captions must be a timed JSON array")
            lines=[]
            def stamp(t):
                cs=round(t*100)
                return f"{cs//360000}:{cs//6000%60:02}:{cs//100%60:02}.{cs%100:02}"
            for row in rows:
                start=number(row["start"],"caption start",0,duration)
                end=number(row["end"],"caption end",start,duration)
                if end<=start or not isinstance(row["text"],str):
                    raise ValueError("Caption needs nonempty timing and text")
                text=re.sub(r"\s+"," ",row["text"]).replace("{", "").replace("}", "").replace("\\", "")
                lines.append(f"Dialogue: 0,{stamp(start)},{stamp(end)},Default,,0,0,0,,{text}")
            # Readable in a 312px-wide phone preview. Use frame-relative sizes
            # so low-resolution inputs do not inherit 1080p/1920p pixel values.
            size = round(w * (.056 if h > w else .034))
            margin = round(h * (.156 if h > w else .062))
            style=(f"[Script Info]\nScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\n"
                   "WrapStyle: 0\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
                   "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
                   "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
                   "Alignment, MarginL, MarginR, MarginV, Encoding\n"
                   f"Style: Default,Manrope,{size},&H00292B2D,&H00292B2D,&H00E5EBF0,&H00E5EBF0,"
                   f"-1,0,0,0,100,100,0,0,3,8,0,2,{round(w*.09)},{round(w*.12)},{margin},1\n\n"
                   "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
            (scratch/'captions.ass').write_text(style+'\n'.join(lines)+'\n')
            if font_dir:
                (scratch/'fonts').mkdir()
                for font in font_dir.iterdir():
                    if font.suffix.lower() in {'.ttf','.otf'} and font.is_file():
                        shutil.copy2(font,scratch/'fonts'/font.name)
            filters.append(f"[{label}]subtitles=filename=captions.ass"+
                           (":fontsdir=fonts" if font_dir else "")+"[captioned]")
            label="captioned"
        if not filters:
            raise ValueError("Finish requires captions or a presenter")
        subprocess.run(["ffmpeg","-v","error","-threads","2",*inputs,
                        "-filter_complex_threads","2","-filter_complex",";".join(filters),
                        "-map",f"[{label}]","-map","0:a?","-c:v","libx264","-preset","fast",
                        "-crf","18","-pix_fmt","yuv420p","-c:a","copy","-movflags","+faststart",
                        str(output.resolve())],cwd=scratch,check=True)
    receipt={"schema":"taskfilm-delivery/v1","path":str(output.resolve()),"sha256":digest(output),
             "source":{"path":str(video.resolve()),"sha256":digest(video)},
             "captions":str(captions.resolve()) if captions else None,
             "presenter":str(presenter.resolve()) if presenter else None,"duration":duration}
    output.with_suffix('.delivery.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt


def prepare(video: Path, output: Path, fps: int = 30) -> dict:
    """Create a seekable video derivative; leave the original recording intact."""
    info=probe(video)
    if not any(s.get('codec_type')=='video' for s in info['streams']):
        raise ValueError('Preparation requires a video stream')
    if output.exists() or output.suffix.lower()!='.mp4':
        raise ValueError('Prepared output must be a new .mp4 file')
    fps=int(number(fps,'preparation fps',1,60))
    output.parent.mkdir(parents=True,exist_ok=True)
    recipe={'fps':fps,'keyframe_interval':fps,'crf':16,'preset':'veryfast'}
    subprocess.run(['ffmpeg','-v','error','-i',str(video.resolve()),'-an','-c:v','libx264',
                    '-preset','veryfast','-crf','16','-r',str(fps),'-g',str(fps),
                    '-keyint_min',str(fps),'-sc_threshold','0','-pix_fmt','yuv420p',
                    '-threads','2','-movflags','+faststart',str(output.resolve())],check=True)
    receipt={'schema':'taskfilm-source-preparation/v1','source':str(video.resolve()),
             'source_sha256':digest(video),'render':str(output.resolve()),'render_sha256':digest(output),
             'recipe':recipe,'duration':probe(output)['duration'],
             'treatment':'Seekable video-only derivative; no authored crop, trim or speed change. Retain the original take.'}
    output.with_suffix('.preparation.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="taskfilm media")
    commands = parser.add_subparsers(dest="command", required=True)
    preparation=commands.add_parser('prepare')
    preparation.add_argument('video',type=Path)
    preparation.add_argument('--out',type=Path,required=True)
    preparation.add_argument('--fps',type=int,default=30)
    library = commands.add_parser("music")
    library.add_argument("library", type=Path)
    library.add_argument("--tags", nargs="*", default=[])
    library.add_argument("--recent", nargs="*", default=[])
    library.add_argument("--fetch")
    library.add_argument("--out", type=Path, default=Path("music"))
    mixer = commands.add_parser("mix")
    mixer.add_argument("spec", type=Path)
    mixer.add_argument("--out", type=Path, required=True)
    voice = commands.add_parser("narrate")
    voice.add_argument("script", type=Path)
    voice.add_argument("--out", type=Path, required=True)
    voice.add_argument("--provider", choices=["macos", "google", "elevenlabs", "deepgram"], default="macos")
    voice.add_argument("--voice")
    voice.add_argument("--ssh-host")
    voice.add_argument("--rate", type=float, default=1.0)
    presenter = commands.add_parser("avatar")
    presenter.add_argument("--audio", type=Path, required=True)
    presenter.add_argument("--image", type=Path, required=True)
    presenter.add_argument("--out", type=Path, required=True)
    delivery = commands.add_parser("finish")
    delivery.add_argument("video",type=Path)
    delivery.add_argument("--out",type=Path,required=True)
    delivery.add_argument("--captions",type=Path)
    delivery.add_argument("--presenter",type=Path)
    delivery.add_argument("--presenter-at",type=float,default=0)
    delivery.add_argument("--presenter-size",type=float,default=.18)
    delivery.add_argument("--font-dir",type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result=prepare(args.video,args.out,args.fps)
        elif args.command == "music":
            result = ({"path": str(fetch_music(args.library, args.fetch, args.out))} if args.fetch else
                      rank_music(load_library(args.library), args.tags, args.recent))
        elif args.command == "mix":
            result = mix(args.spec, args.out)
        elif args.command == "narrate":
            result = narrate(args.script.read_text(), args.out, args.provider, args.voice, args.ssh_host, args.rate)
        elif args.command == "avatar":
            result = avatar(args.audio, args.image, args.out)
        else:
            result = finish(args.video,args.out,captions=args.captions,presenter=args.presenter,
                            presenter_at=args.presenter_at,presenter_size=args.presenter_size,font_dir=args.font_dir)
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"taskfilm media: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
