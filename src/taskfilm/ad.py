"""Evidence-preserving ad authoring on Taskfilm's HyperFrames project contract.

No capture, narration, synthetic music, posting or global installation occurs here.
Call build(spec_path_or_dict, out) or main(["build", "spec.json", "--out", "cut"]).
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageFont

from .ad_templates import FORMATS, SAFE, rank_templates, templates

KIT = Path(__file__).parent / "_vendor/video/hyperframes-lane/product-motion/assets"
HF = "hyperframes@0.8.134"
IDENT = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\Z")
MOTION_FAMILIES = ("cut", "copy-fade-lift")


def _object(value, required, optional=(), label="object"):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    missing, extra = set(required)-value.keys(), value.keys()-set(required)-set(optional)
    if missing or extra:
        raise ValueError(f"{label}: missing {sorted(missing)}, unknown {sorted(extra)}")


def _text(value, label, maximum=500, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()) or len(value) > maximum:
        raise ValueError(f"{label}: expected {'optional' if empty else 'nonempty'} text, at most {maximum} characters")
    if any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise ValueError(f"{label}: control characters are not allowed")


def _number(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{label}: expected a finite number in {low}..{high}")
    return value


def _path(value, base, label):
    _text(value, label, 4096)
    path = (base / value).resolve()
    if not path.is_file():
        raise ValueError(f"{label}: local file does not exist: {path}")
    return path


def probe(path: Path) -> dict:
    """Read real media dimensions/duration; never infer them from a filename."""
    try:
        proc = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                              capture_output=True, text=True, check=True, timeout=60)
        return json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise ValueError(f"ffprobe could not read {path}: {exc}") from exc


def _duration(info, stream):
    for value in (stream.get("duration"), info.get("format", {}).get("duration")):
        try:
            result = float(value)
            if math.isfinite(result) and result > 0:
                return result
        except (ValueError, TypeError):
            pass
    raise ValueError("media has no positive, finite duration")


def _load(spec, base_dir=None):
    if isinstance(spec, (str, Path)):
        path = Path(spec).resolve()
        return json.loads(path.read_text()), Path(base_dir).resolve() if base_dir else path.parent
    return copy.deepcopy(spec), Path(base_dir or '.').resolve()


def load_history(history=None):
    if history is None:
        return []
    if isinstance(history, (str, Path)):
        path = Path(history)
        records = json.loads(path.read_text()) if path.exists() else []
    else:
        records = copy.deepcopy(history)
    if not isinstance(records, list):
        raise ValueError("history must be a JSON array, oldest first")
    for record in records:
        _object(record, ["ad_id", "templates", "product", "style"], ["rating"], "history record")
        for key in ("ad_id", "product", "style"):
            _text(record[key], f"history.{key}")
        if not isinstance(record['templates'], list) or not all(isinstance(t,str) for t in record['templates']):
            raise ValueError("history.templates must be a list of ids")
        if record.get("rating") is not None:
            _number(record["rating"], "rating", 1, 5)
    return records


def _contrast(foreground, background):
    def luminance(color):
        rgb = [int(color[i:i+2],16)/255 for i in (1,3,5)]
        return sum(c*w for c,w in zip([v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in rgb], [.2126,.7152,.0722]))
    a,b = sorted((luminance(foreground),luminance(background)))
    return (b+.05)/(a+.05)


def _validate(spec, base, registry):
    _object(spec, ["schema", "id", "brand", "scenes"], ["format", "product", "style", "template", "audio", "presenter"], "ad")
    if spec["schema"] != "taskfilm-ad/v1":
        raise ValueError("schema must be taskfilm-ad/v1")
    if not isinstance(spec['id'],str) or not IDENT.fullmatch(spec["id"]):
        raise ValueError("invalid ad id")
    fmt = spec.get("format", "portrait")
    if not isinstance(fmt, str) or fmt not in FORMATS:
        raise ValueError(f"format must be one of {list(FORMATS)}")
    for key in ("product", "style", "template"):
        if key in spec:
            _text(spec[key], key, 64)
    if "template" in spec and spec['template'] not in registry:
        raise ValueError(f"unknown template: {spec['template']}")
    brand = spec["brand"]
    _object(brand, ["name", "logo", "colors"], ["font", "headline_font", "font_license"], "brand")
    _text(brand["name"], "brand.name", 100)
    logo = _path(brand["logo"], base, "brand.logo")
    if logo.suffix.lower() == '.svg':
        try:
            root = ET.parse(logo).getroot()
            if root.tag.split('}')[-1] != 'svg':
                raise ValueError("logo is not SVG")
            for node in root.iter():
                if node.tag.split('}')[-1] in ('script','foreignObject'):
                    raise ValueError("logo SVG must be a self-contained image")
                for key,value in node.attrib.items():
                    if key.split('}')[-1] == 'href' and not value.startswith(('#','data:')):
                        raise ValueError("logo SVG must not reference external files")
        except ET.ParseError as exc:
            raise ValueError("invalid logo SVG") from exc
    else:
        try:
            with Image.open(logo) as image:
                image.verify()
        except (OSError, ValueError) as exc:
            raise ValueError("logo must be a real SVG or raster image") from exc
    font = _path(brand["font"], base, "brand.font") if "font" in brand else KIT / "Manrope.ttf"
    headline_font = _path(brand['headline_font'], base, 'brand.headline_font') if 'headline_font' in brand else font
    font_license = _path(brand['font_license'], base, 'brand.font_license') if 'font_license' in brand else None
    for face in (font, headline_font):
        try:
            ImageFont.truetype(str(face), 40)
        except OSError as exc:
            raise ValueError("brand fonts must be local TrueType/OpenType fonts readable by Pillow") from exc
        if face.suffix.lower() not in ('.ttf','.otf'):
            raise ValueError("brand fonts must be .ttf or .otf for matching browser/measurement metrics")
    _object(brand["colors"], ["background", "text", "accent"], label="brand.colors")
    if any(not isinstance(v,str) or not re.fullmatch(r"#[0-9a-fA-F]{6}",v) for v in brand["colors"].values()):
        raise ValueError("brand colors must be six-digit hex values")
    if _contrast(brand['colors']['text'], brand['colors']['background']) < 4.5:
        raise ValueError("brand text/background contrast must be at least 4.5:1")
    scenes = spec['scenes']
    if not isinstance(scenes,list) or not 1 <= len(scenes) <= 40:
        raise ValueError("scenes must contain 1..40 scenes")
    seen, media_info, cache = set(), {}, {}
    total = 0
    for scene in scenes:
        _object(scene, ["id", "duration", "headline"], ["layout", "body", "media", "caption"], "scene")
        ident = scene['id']
        if not isinstance(ident,str) or not IDENT.fullmatch(ident) or ident in seen:
            raise ValueError("scene ids must be valid and unique")
        seen.add(ident)
        duration = _number(scene['duration'], f"{ident}.duration", .5, 30)
        total += duration
        _text(scene['headline'], f"{ident}.headline",110)
        _text(scene.get('body',''), f"{ident}.body",220,empty=True)
        if 'caption' in scene:
            _text(scene['caption'], f"{ident}.caption", 180)
        if 'layout' in scene:
            _text(scene['layout'], f"{ident}.layout",64)
            if scene['layout'] not in registry:
                raise ValueError(f"{ident}: unknown layout {scene['layout']}")
        if 'media' not in scene:
            continue
        media = scene['media']
        _object(media,['path','type'],['in','speed','crop'],f"{ident}.media")
        if media['type'] not in ('video','image'):
            raise ValueError("media.type must be video or image")
        source = _path(media['path'],base,f"{ident}.media.path")
        if source not in cache:
            cache[source] = probe(source)
        info = cache[source]
        videos = [s for s in info.get('streams',[]) if s.get('codec_type') == 'video']
        if not videos:
            raise ValueError(f"{ident}: media has no visual stream")
        stream = videos[0]
        width,height = stream.get('width',0),stream.get('height',0)
        if width <= 0 or height <= 0:
            raise ValueError(f"{ident}: invalid source dimensions")
        if stream.get('sample_aspect_ratio') not in (None,'N/A','0:1','1:1'):
            raise ValueError(f"{ident}: normalize non-square source pixels explicitly before authoring")
        if any(abs(float(s.get('rotation',0))) > .01 for s in stream.get('side_data_list',[])) or float(stream.get('tags',{}).get('rotate',0)):
            raise ValueError(f"{ident}: normalize source rotation explicitly before authoring")
        crop = media.get('crop',[0,0,width,height])
        if not isinstance(crop,list) or len(crop) != 4:
            raise ValueError(f"{ident}.crop must be source pixels [x,y,width,height]")
        for value in crop:
            _number(value, f"{ident}.crop",0,max(width,height))
        x,y,w,h = crop
        if w <= 0 or h <= 0 or x+w > width or y+h > height:
            raise ValueError(f"{ident}: crop outside {width}x{height} source")
        start = _number(media.get('in',0),f"{ident}.in",0,86400)
        speed = _number(media.get('speed',1),f"{ident}.speed",.25,8)
        source_duration = None
        if media['type'] == 'video':
            source_duration = _duration(info,stream)
            if start + duration*speed > source_duration + .001:
                raise ValueError(f"{ident}: trim consumes {start+duration*speed:.3f}s but source lasts {source_duration:.3f}s")
            # Avoid silently treating a still as a video and inventing a workflow.
            if stream.get('codec_name') in ('png','mjpeg','webp') and info.get('format',{}).get('format_name') in ('image2','png_pipe','jpeg_pipe','webp_pipe'):
                raise ValueError(f"{ident}: still image declared as video")
        else:
            if 'in' in media or 'speed' in media:
                raise ValueError(f"{ident}: still images cannot have trim or speed")
            try:
                with Image.open(source) as image:
                    if image.getexif().get(274,1) != 1:
                        raise ValueError(f'{ident}: normalize image EXIF orientation before authoring')
                    if getattr(image,'n_frames',1) != 1:
                        raise ValueError("animated images must be converted to explicit video clips")
                    # getexif()/n_frames may decode PNG data and close its fp.
                    # load() safely completes decoding here; verify() requires
                    # a freshly opened image and would fail after those reads.
                    image.load()
            except OSError as exc:
                raise ValueError(f"{ident}: media is not a still image") from exc
        media_info[ident] = {'source':str(source),'width':width,'height':height,'crop':crop,
                             'in':start,'speed':speed,'source_duration':source_duration,
                             'source_out':start+duration*speed if source_duration else None,
                             'type':media['type']}
    total = round(total,6)
    if total > 180:
        raise ValueError("ad duration must be at most 180 seconds")
    audio = None
    if 'audio' in spec:
        _object(spec['audio'],['path'],label='audio (supply a finished mix)')
        audio = _path(spec['audio']['path'],base,'audio.path')
        info = probe(audio)
        streams = [s for s in info.get('streams',[]) if s.get('codec_type') == 'audio']
        if not streams or _duration(info,streams[0]) + .02 < total:
            raise ValueError("finished audio track must contain audio for the entire ad duration")
    presenter = None
    if 'presenter' in spec:
        overlay = spec['presenter']
        _object(overlay, ['path', 'scene_ids'], ['placement', 'size'], 'presenter')
        ids = overlay['scene_ids']
        if not isinstance(ids, list) or not ids or any(not isinstance(v, str) for v in ids):
            raise ValueError('presenter.scene_ids must be a nonempty list of scene ids')
        if len(set(ids)) != len(ids) or not set(ids) <= seen:
            raise ValueError('presenter.scene_ids must be unique existing scene ids')
        if overlay.get('placement', 'bottom-right') != 'bottom-right':
            raise ValueError('presenter.placement must be bottom-right')
        size = _number(overlay.get('size', .22), 'presenter.size', .12, .35)
        path = _path(overlay['path'], base, 'presenter.path')
        info = probe(path)
        streams = [s for s in info.get('streams', []) if s.get('codec_type') == 'video']
        if not streams:
            raise ValueError('presenter must contain a video stream')
        stream = streams[0]
        width, height = stream.get('width', 0), stream.get('height', 0)
        if width <= 0 or height <= 0 or stream.get('sample_aspect_ratio') not in (None, 'N/A', '0:1', '1:1'):
            raise ValueError('presenter must have positive dimensions and square pixels')
        if any(abs(float(s.get('rotation', 0))) > .01 for s in stream.get('side_data_list', [])) or float(stream.get('tags', {}).get('rotate', 0)):
            raise ValueError('normalize presenter rotation explicitly before authoring')
        source_duration = _duration(info, stream)
        elapsed, needed = 0, 0
        for scene in scenes:
            elapsed += scene['duration']
            if scene['id'] in ids:
                needed = elapsed
        if source_duration + .001 < needed:
            raise ValueError(f'presenter lasts {source_duration:.3f}s but selected scenes need global time {needed:.3f}s')
        presenter = {'source': str(path), 'width': width, 'height': height,
                     'source_duration': source_duration, 'scene_ids': ids,
                     'placement': 'bottom-right', 'size': size}
    return {'duration':total,'format':fmt,'font':font,'headline_font':headline_font,'font_license':font_license,
            'logo':logo,'audio':audio,'media':media_info,'presenter':presenter}


def _font(path, size):
    font = ImageFont.truetype(str(path),size)
    try:
        axes = font.get_variation_axes()
        font.set_variation_by_axes([min(a['maximum'],max(a['minimum'],700 if a['name'] == b'Weight' else a['default'])) for a in axes])
    except OSError:
        pass
    return font


def _wrap(text, font, width):
    lines=[]
    for paragraph in text.split('\n'):
        line=''
        for word in paragraph.split():
            if font.getlength(word) > width:
                return None
            candidate = f'{line} {word}'.strip()
            if font.getlength(candidate) <= width:
                line=candidate
            else:
                lines.append(line)
                line=word
        lines.append(line)
    return lines


def _fit(scene, frame, fmt, font_path, headline_font=None):
    width,height = FORMATS[fmt]
    cw,ch = frame['copy'][2]*width,frame['copy'][3]*height
    body_size = {'portrait': 44, 'landscape': 40, 'square': 36}[fmt]
    body = _wrap(scene.get('body',''),_font(font_path,body_size),cw-4) if scene.get('body') else []
    if body is None:
        raise ValueError(f"{scene['id']}: body contains an unbreakable word wider than the copy box")
    body_h = len(body)*body_size*1.35 + (20 if body else 0)
    minimum = 44 if fmt == 'portrait' else 40
    for size in range(int(frame['headline_size']),minimum-1,-1):
        lines = _wrap(scene['headline'],_font(headline_font or font_path,size),cw-4)
        if lines is not None and len(lines)*size*1.13 + body_h <= ch-4:
            return {'headline':lines,'headline_size':size,'body':body,'body_size':body_size}
    raise ValueError(f"{scene['id']}: copy does not fit {fmt} layout at readable size; shorten copy or select another layout")


def _reserve_footer(scene, frame, checked):
    """Reserve native-aspect presenter/caption space, then reflow existing boxes.

    Scaling only the template's Y coordinates keeps its hierarchy and horizontal
    measure intact. Text is measured again after reflow; it is never scaled down
    as an image or allowed to run into the reserved band.
    """
    fmt = checked['format']
    width, height = FORMATS[fmt]
    sx, sy, sw, sh = SAFE[fmt]
    presenter = checked['presenter']
    active = presenter and scene['id'] in presenter['scene_ids']
    avatar, caption = None, None
    band = 0
    gap = 24
    if active:
        side = presenter['size'] * min(width, height)
        scale = side / max(presenter['width'], presenter['height'])
        aw, ah = presenter['width'] * scale, presenter['height'] * scale
        box = [sx+sw-aw/width, sy+sh-ah/height, aw/width, ah/height]
        avatar = {**presenter, 'box': box}
        band = ah
    if 'caption' in scene:
        available = sw*width - ((avatar['box'][2]*width+gap) if avatar else 0)
        size = 32 if fmt == 'portrait' else 28
        lines = _wrap(scene['caption'], _font(checked['font'], size), available-4)
        if lines is None or len(lines) > 3:
            raise ValueError(f"{scene['id']}: caption must fit at most three readable lines beside presenter")
        ch = len(lines)*size*1.35+4
        caption = {'box': [sx, sy+sh-ch/height, available/width, ch/height],
                   'lines': lines, 'size': size}
        band = max(band, ch)
    if band:
        remaining = sh*height-band-gap
        if remaining < sh*height*.5:
            raise ValueError(f"{scene['id']}: presenter/caption leaves too little safe space for the product")
        ratio = remaining/(sh*height)
        for key in ('copy', 'media', 'logo'):
            x,y,w,h = frame[key]
            frame[key] = [x, sy+(y-sy)*ratio, w, h*ratio]
    return avatar, caption


def plan(spec, *, base_dir=None, history=None, template_paths=()):
    """Validate assets and return an auditable, deterministic scene plan."""
    spec,base = _load(spec,base_dir)
    registry = templates(template_paths)
    checked = _validate(spec,base,registry)
    records = load_history(history)
    used,scenes,warnings = [],[],[]
    if 'font' not in spec['brand']:
        warnings.append('brand.font omitted: bundled Manrope fallback is not an assertion of authentic brand typography')
    if not checked['audio']:
        warnings.append('No audio supplied: project is silent; supply audio.path for the finished music/narration mix')
    start=0
    for scene in spec['scenes']:
        ranking=rank_templates(registry,product=spec.get('product','saas'),style=spec.get('style','clear'),
                               history=records,used=used,has_media='media' in scene)
        explicit=scene.get('layout',spec.get('template'))
        candidates=[explicit] if explicit else [r['id'] for r in ranking]
        failures=[]
        for ident in candidates:
            frame=copy.deepcopy(registry[ident]['frames'][checked['format']])
            if 'media' not in scene and ident != 'brand-close':
                # Text-only scenes use the family's alignment but reclaim evidence space.
                frame['copy']=[.10,.25,.74,.44] if checked['format']=='portrait' else [.10,.27,.80,.56] if checked['format']=='landscape' else [.10,.25,.76,.57]
            try:
                avatar, caption = _reserve_footer(scene, frame, checked)
                typography=_fit(scene,frame,checked['format'],checked['font'],checked['headline_font'])
                break
            except ValueError as exc:
                failures.append(str(exc))
        else:
            raise ValueError('; '.join(failures))
        used.append(ident)
        scenes.append({'id':scene['id'],'start':round(start,6),'duration':scene['duration'],'layout':ident,
                       'frame':frame,'typography':typography,'media':checked['media'].get(scene['id']),
                       'presenter':avatar,'caption':caption,
                       'ranking':ranking,'selection':'explicit' if explicit else 'ranked'})
        start+=scene['duration']
    return {'schema':'taskfilm-ad-plan/v1','id':spec['id'],'format':checked['format'],
            'canvas':list(FORMATS[checked['format']]),'safe':SAFE[checked['format']],
            'duration':checked['duration'],'fps':30,'product':spec.get('product','saas'),
            'style':spec.get('style','clear'),'scenes':scenes,'warnings':warnings,
            'brand_assets':{'logo':str(checked['logo']),'font':str(checked['font']),
                            'headline_font':str(checked['headline_font']),
                            **({'font_license':str(checked['font_license'])} if checked['font_license'] else {})},
            'presenter':checked['presenter'],'motion_families':list(MOTION_FAMILIES),
            'audio':str(checked['audio']) if checked['audio'] else None}


def validate(spec, **kwargs):
    """Same validation and copy-fit checks as build; does not write files."""
    return plan(spec,**kwargs)


def _digest(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path,value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def _style(box,width,height):
    x,y,w,h=box
    return f'left:{x*width:.3f}px;top:{y*height:.3f}px;width:{w*width:.3f}px;height:{h*height:.3f}px'


def _markup(spec, decision, assets):
    w,h=decision['canvas']
    pal=spec['brand']['colors']
    esc=html.escape
    sections=[]
    tweens=[]
    for i,scene in enumerate(decision['scenes']):
        ident=f'scene-{scene["id"]}'
        frame=scene['frame']
        typo=scene['typography']
        copy_html='<br>'.join(esc(line) for line in typo['headline'])
        body_html='<br>'.join(esc(line) for line in typo['body'])
        media_html=''
        overlay_html=''
        if scene['presenter']:
            avatar=scene['presenter']
            overlay_html += (f'<video id="presenter-{scene["id"]}" class="clip presenter" '
                             f'src="{esc(assets[avatar["source"]],quote=True)}" muted playsinline preload="auto" '
                             f'data-start="{scene["start"]}" data-duration="{scene["duration"]}" '
                             f'data-media-start="{scene["start"]}" data-playback-rate="1" data-track-index="5" '
                             f'style="{_style(avatar["box"],w,h)}"></video>')
        if scene['caption']:
            caption=scene['caption']
            text='<br>'.join(esc(line) for line in caption['lines'])
            overlay_html += (f'<div id="subtitles-{scene["id"]}" class="clip subtitles" '
                             f'data-start="{scene["start"]}" data-duration="{scene["duration"]}" data-track-index="6" '
                             f'style="{_style(caption["box"],w,h)};font-size:{caption["size"]}px">{text}</div>')
        if scene['media']:
            media=scene['media']
            x,y,cw,ch=media['crop']
            bw,bh=frame['media'][2]*w,frame['media'][3]*h
            scale=min(bw/cw,bh/ch)
            iw,ih=cw*scale,ch*scale
            crop_style=f'left:{(bw-iw)/2:.3f}px;top:{(bh-ih)/2:.3f}px;width:{iw:.3f}px;height:{ih:.3f}px;border-radius:{frame["radius"]}px'
            source_style=f'left:{-x*scale:.3f}px;top:{-y*scale:.3f}px;width:{media["width"]*scale:.3f}px;height:{media["height"]*scale:.3f}px'
            source=esc(assets[media['source']],quote=True)
            if media['type']=='video':
                node=(f'<video id="media-{scene["id"]}" class="clip source" src="{source}" muted playsinline preload="auto" '
                      f'data-start="{scene["start"]}" data-duration="{scene["duration"]}" '
                      f'data-media-start="{media["in"]}" data-playback-rate="{media["speed"]}" '
                      f'data-track-index="2" style="{source_style}" data-layout-allow-overflow></video>')
            else:
                node=(f'<img id="media-{scene["id"]}" class="clip source" src="{source}" alt="" style="{source_style}" '
                      f'data-start="{scene["start"]}" data-duration="{scene["duration"]}" data-track-index="2" data-layout-allow-overflow>')
            media_html=f'<div class="media-box" style="{_style(frame["media"],w,h)}"><div class="crop" style="{crop_style}">{node}</div></div>'
        logo_src=esc(assets[decision['brand_assets']['logo']],quote=True)
        sections.append(f'''<section id="{ident}" class="scene" data-layout="{scene['layout']}">
<img id="logo-{scene['id']}" class="clip logo" data-start="{scene['start']}" data-duration="{scene['duration']}" data-track-index="3" src="{logo_src}" alt="{esc(spec['brand']['name'],quote=True)}" style="{_style(frame['logo'],w,h)}">
{media_html}{overlay_html}
<div id="caption-{scene['id']}" class="clip caption" data-start="{scene['start']}" data-duration="{scene['duration']}" data-track-index="4" style="{_style(frame['copy'],w,h)};text-align:{frame['align']}"><div id="copy-{scene['id']}" class="copy"><h1 style="font-size:{typo['headline_size']}px">{copy_html}</h1>{f'<p style="font-size:{typo["body_size"]}px">{body_html}</p>' if body_html else ''}</div></div>
</section>''')
        # Fade/lift the copy only. Runtime owns all timed clip visibility and media seeking.
        tweens.append(f'tl.fromTo("#copy-{scene["id"]}", {{opacity:0,y:12}}, {{opacity:1,y:0,duration:{min(.24,scene["duration"]/3)},ease:"power2.out",immediateRender:false}}, {scene["start"]});')
    audio=''
    if decision['audio']:
        audio=f'<audio id="mix" class="clip" src="{esc(assets[decision["audio"]],quote=True)}" data-start="0" data-duration="{decision["duration"]}" data-media-start="0" data-track-index="0"></audio>'
    font_src=assets[decision['brand_assets']['font']]
    headline_src=assets[decision['brand_assets']['headline_font']]
    # Keep this template in Python so the existing package-data configuration ships it.
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{esc(spec['brand']['name'])} — {esc(spec['id'])}</title>
<script src="{assets.get('gsap','https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js')}"></script>
<style>
@font-face{{font-family:AdBrand;src:url('{font_src}');font-weight:100 900;font-display:block}}
@font-face{{font-family:AdHeadline;src:url('{headline_src}');font-weight:100 900;font-display:block}}
*{{box-sizing:border-box;margin:0;padding:0}}html,body{{width:{w}px;height:{h}px;background:{pal['background']};overflow:hidden}}
body{{font-family:AdBrand,sans-serif;font-weight:700;color:{pal['text']};-webkit-font-smoothing:antialiased}}
#root{{position:relative;width:{w}px;height:{h}px;overflow:hidden;background:{pal['background']}}}
.scene{{position:absolute;inset:0}}.logo,.media-box,.crop,.source,.caption{{position:absolute}}.copy{{width:100%;height:100%}}
.logo{{object-fit:contain;object-position:left center}}.scene[data-layout="brand-close"] .logo{{object-position:center}}
.crop{{overflow:hidden;background:transparent}}.source{{max-width:none;object-fit:fill}}
.presenter,.subtitles{{position:absolute;z-index:10}}.presenter{{object-fit:contain;border-radius:16px}}
.subtitles{{line-height:1.35;font-weight:700}}
h1{{font-family:AdHeadline,sans-serif;line-height:1.13;font-weight:700;letter-spacing:0}}p{{line-height:1.35;margin-top:20px;font-weight:700}}
</style></head><body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{decision['duration']}" data-width="{w}" data-height="{h}">
{''.join(sections)}{audio}
</div><script>
window.__timelines = window.__timelines || {{}};
const tl=gsap.timeline({{paused:true}});
{''.join(tweens)}
const clock={{t:0}};tl.to(clock,{{t:{decision['duration']},duration:{decision['duration']},ease:"none"}},0);
window.__timelines.main=tl;
window.__taskfilmReady=document.fonts.ready.then(()=>true);
</script></body></html>'''


def build(spec, out, *, base_dir=None, history=None, template_paths=()) -> Path:
    """Write a portable editable project, preserving original media and receipts.

    Output must be absent or empty; failures cannot destroy an existing edit.
    Optional history must be a path to record this build (planning also accepts lists).
    """
    data,base=_load(spec,base_dir)
    decision=plan(data,base_dir=base,history=history,template_paths=template_paths)
    registry=templates(template_paths)
    out=Path(out).resolve()
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError(f"output must be absent or empty: {out}")
    if history is not None and not isinstance(history,(str,Path)):
        raise ValueError("build history must be a JSON file path")
    records=load_history(history)
    out.parent.mkdir(parents=True,exist_ok=True)
    temp=Path(tempfile.mkdtemp(prefix=f'.{out.name}-',dir=out.parent))
    try:
        (temp/'assets').mkdir()
        (temp/'evidence').mkdir()
        assets,receipts={},[]
        paths=[Path(p) for p in decision['brand_assets'].values()]
        paths += [Path(s['media']['source']) for s in decision['scenes'] if s['media']]
        if decision['audio']:
            paths.append(Path(decision['audio']))
        if decision['presenter']:
            paths.append(Path(decision['presenter']['source']))
        for source in dict.fromkeys(paths):
            digest=_digest(source)
            dest=Path('assets')/(digest[:20]+source.suffix.lower())
            shutil.copy2(source,temp/dest)
            assets[str(source)]=dest.as_posix()
            receipts.append({'source':str(source),'asset':dest.as_posix(),'sha256':digest,'bytes':source.stat().st_size})
            if (any(s['media'] and s['media']['source']==str(source) for s in decision['scenes'])
                    or decision['presenter'] and decision['presenter']['source']==str(source)):
                for name in ('session.json','input.jsonl','beats.jsonl','windows.jsonl'):
                    sidecar=source.parent/name
                    if sidecar.is_file():
                        dest_side=Path('evidence')/digest[:20]/name
                        (temp/dest_side).parent.mkdir(parents=True,exist_ok=True)
                        shutil.copy2(sidecar,temp/dest_side)
                        receipts.append({'source':str(sidecar),'asset':dest_side.as_posix(),'sha256':_digest(sidecar),'bytes':sidecar.stat().st_size})
        # Preserve bundled font license when using the explicit fallback.
        if Path(decision['brand_assets']['font']) == KIT/'Manrope.ttf':
            shutil.copy2(KIT/'Manrope-OFL.txt',temp/'assets/Manrope-OFL.txt')
        # Keep supplied font license sidecars with portable brand assets.
        for key in ('font','headline_font'):
            font=Path(decision['brand_assets'][key])
            for name in (font.stem+'-OFL.txt',font.stem+'-LICENSE.txt','OFL.txt','LICENSE.txt'):
                license_path=font.parent/name
                if license_path.is_file():
                    digest=_digest(license_path)
                    dest=Path('assets')/(digest[:20]+'-'+name)
                    shutil.copy2(license_path,temp/dest)
                    if not any(r['source']==str(license_path) for r in receipts):
                        receipts.append({'source':str(license_path),'asset':dest.as_posix(),
                                         'sha256':digest,'bytes':license_path.stat().st_size})
        if (KIT/'gsap.min.js').is_file():
            shutil.copy2(KIT/'gsap.min.js',temp/'assets/gsap.min.js')
            assets['gsap']='assets/gsap.min.js'
        (temp/'index.html').write_text(_markup(data,decision,assets))
        _write_json(temp/'index.motion.json',{'duration':decision['duration'],'assertions':[
            {'kind':'appearsBy','selector':f'#copy-{s["id"]}','bySec':round(s['start']+min(.3,s['duration']*.8),6)} for s in decision['scenes']]})
        _write_json(temp/'hyperframes.json',{'$schema':'https://hyperframes.heygen.com/schema/hyperframes.json',
                    'paths':{'blocks':'compositions','components':'compositions/components','assets':'assets'},'media':{'autoProxy':True}})
        _write_json(temp/'package.json',{'name':f'taskfilm-ad-{data["id"].lower()}','private':True,'type':'module',
                    'scripts':{verb:f'npx --yes {HF} {command}' for verb,command in [('dev','preview'),('check','check'),('render','render')]}})
        _write_json(temp/'AD-SOURCE.json',data)
        # Portable spec references copied assets and fixes the selected layouts.
        portable=copy.deepcopy(data)
        for key in decision['brand_assets']:
            portable['brand'][key]=assets[decision['brand_assets'][key]]
        for scene,planned in zip(portable['scenes'],decision['scenes']):
            scene['layout']=planned['layout']
            if planned['media']:
                scene['media']['path']=assets[planned['media']['source']]
        if decision['audio']:
            portable['audio']['path']=assets[decision['audio']]
        if decision['presenter']:
            portable['presenter']['path']=assets[decision['presenter']['source']]
        _write_json(temp/'ad.json',portable)
        _write_json(temp/'AD-PLAN.json',decision)
        _write_json(temp/'EDIT-DECISIONS.json',{'schema':'taskfilm-ad-evidence/v1','plan':decision,
                    'sources':receipts,'runtime':HF,'gsap':assets.get('gsap','https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js'),
                    'source_audio':'product and presenter muted; only supplied finished mix is audible',
                    'motion':'cuts; 240ms copy fade/lift; no generated SFX',
                    'motion_policy':{'maximum_families':2,'families':list(MOTION_FAMILIES),'generated_sfx':False},
                    'crop_policy':'contain the explicit crop; never stretch or auto-crop product pixels'})
        (temp/'templates').mkdir()
        for ident in dict.fromkeys(s['layout'] for s in decision['scenes']):
            _write_json(temp/'templates'/f'{ident}.json',registry[ident])
        if out.exists():
            out.rmdir()  # known empty; fails safely if another writer arrived
        temp.rename(out)
    finally:
        if temp.exists():
            shutil.rmtree(temp)
    if history is not None:
        records.append({'ad_id':data['id'],'templates':list(dict.fromkeys(s['layout'] for s in decision['scenes'])),
                        'product':decision['product'],'style':decision['style'],'rating':None})
        _save_history(Path(history),records)
    return out


def _save_history(path, records):
    path=path.resolve()
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix=f'.{path.name}-',dir=path.parent)
    os.close(fd)
    temp=Path(name)
    try:
        _write_json(temp,records)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def rate(history, ad_id, rating):
    _number(rating,'rating',1,5)
    records=load_history(history)
    for record in reversed(records):
        if record['ad_id']==ad_id:
            record['rating']=rating
            _save_history(Path(history),records)
            return record
    raise ValueError(f"ad id not found in history: {ad_id}")


def main(argv=None):
    parser=argparse.ArgumentParser(prog='taskfilm ad',description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    listing=sub.add_parser('templates',help='list or export declarative composition families')
    listing.add_argument('--template-file',action='append',default=[])
    listing.add_argument('--export',metavar='ID')
    listing.add_argument('--out',type=Path)
    for command in ('validate','plan','build'):
        p=sub.add_parser(command)
        p.add_argument('spec',type=Path)
        p.add_argument('--out',type=Path,required=command=='build')
        p.add_argument('--history',type=Path)
        p.add_argument('--template-file',action='append',default=[])
    rating=sub.add_parser('rate',help='rate the latest matching ad in a history file')
    rating.add_argument('ad_id')
    rating.add_argument('rating',type=float)
    rating.add_argument('--history',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='templates':
            registry=templates(args.template_file)
            if args.export and args.export not in registry:
                raise ValueError(f'unknown template {args.export}')
            result=registry[args.export] if args.export else list(registry.values())
        elif args.command=='rate':
            result=rate(args.history,args.ad_id,args.rating)
        elif args.command=='build':
            print(build(args.spec,args.out,history=args.history,template_paths=args.template_file))
            return 0
        else:
            result=plan(args.spec,history=args.history,template_paths=args.template_file)
        output=json.dumps(result,indent=2,ensure_ascii=False)+'\n'
        if getattr(args,'out',None):
            if args.out.exists():
                raise ValueError(f'refusing to overwrite {args.out}')
            args.out.parent.mkdir(parents=True,exist_ok=True)
            args.out.write_text(output)
        else:
            print(output,end='')
        return 0
    except (ValueError,OSError,TypeError) as exc:
        parser.exit(2,f'taskfilm ad: {exc}\n')


if __name__=='__main__':
    raise SystemExit(main())
