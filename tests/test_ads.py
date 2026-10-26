"""Ad authoring: real media bounds, layout contracts, selection and receipts."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from PIL import Image
import pytest

from taskfilm.ad import build, main, plan, rate, validate
from taskfilm.ad_templates import FORMATS, rank_templates, templates, validate_template


@pytest.fixture
def source(tmp_path):
    Image.new('RGB',(320,180),'#eeeeee').save(tmp_path/'still.png')
    (tmp_path/'logo.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><circle cx="10" cy="10" r="9"/></svg>')
    return {'schema':'taskfilm-ad/v1','id':'test-ad','brand':{'name':'Real Brand','logo':'logo.svg',
            'colors':{'background':'#f5f1eb','text':'#222222','accent':'#662288'}},
            'scenes':[{'id':'proof','duration':2,'headline':'Know your numbers.',
                       'media':{'type':'image','path':'still.png'}}]}


@pytest.fixture
def video(tmp_path):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('ffmpeg/ffprobe required for media integration')
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=30',
                    '-t','3','-an','-c:v','libx264','-threads','1','-pix_fmt','yuv420p',str(tmp_path/'take.mp4')],check=True)
    return tmp_path/'take.mp4'


def test_all_families_are_valid_and_have_distinct_geometry():
    registry=templates()
    assert len(registry)==8
    for fmt in FORMATS:
        assert len({json.dumps(t['frames'][fmt],sort_keys=True) for t in registry.values()})==8
    for template in registry.values():
        assert validate_template(template)==template


def test_portable_custom_font_keeps_original_license(source,tmp_path):
    from taskfilm.ad import KIT
    shutil.copy2(KIT/'Manrope.ttf',tmp_path/'brand.ttf')
    original=(KIT/'Manrope-OFL.txt').read_bytes()
    (tmp_path/'OFL.txt').write_bytes(original)
    source['brand']['font']='brand.ttf'
    build(source,tmp_path/'portable',base_dir=tmp_path)
    receipts=json.loads((tmp_path/'portable/EDIT-DECISIONS.json').read_text())['sources']
    row=next(r for r in receipts if r['source']==str(tmp_path/'OFL.txt'))
    assert (tmp_path/'portable'/row['asset']).read_bytes()==original


@pytest.mark.parametrize('fmt',list(FORMATS))
def test_every_family_fits_a_real_short_headline(source,tmp_path,fmt):
    source['format']=fmt
    for ident in templates():
        source['template']=ident
        decision=validate(source,base_dir=tmp_path)
        assert decision['scenes'][0]['layout']==ident
        assert decision['scenes'][0]['typography']['headline_size']>=40


def test_selection_is_deterministic_and_avoids_immediate_repeat(source,tmp_path):
    source['scenes']=[dict(copy.deepcopy(source['scenes'][0]),id=f'proof-{i}') for i in range(6)]
    a=plan(source,base_dir=tmp_path)
    assert a==plan(source,base_dir=tmp_path)
    selected=[s['layout'] for s in a['scenes']]
    assert all(a!=b for a,b in zip(selected,selected[1:]))
    assert len(set(selected))>=4
    assert a['duration']==12
    assert a['scenes'][-1]['start']==10


def test_ranking_product_style_history_and_feedback():
    registry=templates()
    initial=rank_templates(registry,product='wellness',style='calm')
    assert initial[0]['id']=='quiet-card'
    record={'ad_id':'x','templates':['quiet-card'],'product':'wellness','style':'calm','rating':1}
    recent=rank_templates(registry,product='wellness',style='calm',history=[record]*5)
    assert recent[0]['id']!='quiet-card'
    bad=next(r for r in recent if r['id']=='quiet-card')
    assert bad['feedback']==-3
    record['rating']=5
    good=next(r for r in rank_templates(registry,product='wellness',style='calm',history=[record]) if r['id']=='quiet-card')
    assert good['feedback']==3


def test_source_trim_speed_and_crop_are_in_real_source_units(source,tmp_path,video):
    source['scenes'][0].update(duration=1,media={'path':'take.mp4','type':'video','in':1,'speed':2,'crop':[20,10,100,100]})
    decision=plan(source,base_dir=tmp_path)
    media=decision['scenes'][0]['media']
    assert media['source_out']==3
    assert media['crop']==[20,10,100,100]
    assert (media['width'],media['height'])==(320,180)
    source['scenes'][0]['media']['in']=1.1
    with pytest.raises(ValueError,match='source lasts'):
        plan(source,base_dir=tmp_path)


@pytest.mark.parametrize('crop',[[300,0,50,50],[0,0,0,20],[-1,0,20,20],[0,0,320,181],[0,0,float('nan'),10]])
def test_invalid_crops_fail(source,tmp_path,crop):
    source['scenes'][0]['media']['crop']=crop
    with pytest.raises(ValueError,match='crop'):
        validate(source,base_dir=tmp_path)


@pytest.mark.parametrize('key,value',[('speed',9),('speed',True),('in',-1),('speed',float('inf'))])
def test_bad_video_mapping_fails(source,tmp_path,video,key,value):
    source['scenes'][0]['media']={'path':'take.mp4','type':'video',key:value}
    with pytest.raises(ValueError):
        validate(source,base_dir=tmp_path)


def test_still_cannot_pretend_to_be_a_workflow(source,tmp_path):
    source['scenes'][0]['media']['speed']=2
    with pytest.raises(ValueError,match='still images cannot'):
        validate(source,base_dir=tmp_path)


def test_external_template_interface_and_unknown_layout(source,tmp_path):
    template=copy.deepcopy(templates()['hero-stage'])
    template['id']='custom-proof'
    path=tmp_path/'custom.json'
    path.write_text(json.dumps(template))
    source['template']='custom-proof'
    decision=plan(source,base_dir=tmp_path,template_paths=[path])
    assert decision['scenes'][0]['layout']=='custom-proof'
    with pytest.raises(ValueError,match='unknown template'):
        plan(source,base_dir=tmp_path)
    template['frames']['portrait']['copy']=[0,0,1,1]
    with pytest.raises(ValueError,match='safe'):
        validate_template(template)
    template=copy.deepcopy(templates()['hero-stage'])
    template['frames']['portrait']['copy']=template['frames']['portrait']['media']
    with pytest.raises(ValueError,match='overlap'):
        validate_template(template)
    template['javascript']='alert(1)'
    with pytest.raises(ValueError,match='exactly'):
        validate_template(template)


def test_copy_and_contrast_fail_instead_of_silent_clipping(source,tmp_path):
    source['template']='caption-rail'
    source['scenes'][0]['headline']='W'*100
    with pytest.raises(ValueError,match='does not fit'):
        validate(source,base_dir=tmp_path)
    source['brand']['colors']['text']='#f5f1eb'
    with pytest.raises(ValueError,match='contrast'):
        validate(source,base_dir=tmp_path)


def test_unique_scene_ids_and_unknown_keys(source,tmp_path):
    source['scenes'].append(copy.deepcopy(source['scenes'][0]))
    with pytest.raises(ValueError,match='unique'):
        validate(source,base_dir=tmp_path)
    source['scenes'].pop()
    source['synth_pulse']=True
    with pytest.raises(ValueError,match='unknown'):
        validate(source,base_dir=tmp_path)


def test_finished_audio_is_checked_and_emitted(source,tmp_path):
    import wave
    with wave.open(str(tmp_path/'mix.wav'),'wb') as wav:
        wav.setparams((1,2,8000,0,'NONE','not compressed'))
        wav.writeframes(b'\0\0'*16000)
    source['audio']={'path':'mix.wav'}
    out=build(source,tmp_path/'cut',base_dir=tmp_path)
    assert '<audio id="mix" class="clip"' in (out/'index.html').read_text()
    source['scenes'][0]['duration']=3
    with pytest.raises(ValueError,match='entire ad duration'):
        validate(source,base_dir=tmp_path)


def test_build_portable_evidence_and_runtime_ownership(source,tmp_path,video):
    source['scenes'][0].update(duration=1,media={'path':'take.mp4','type':'video','in':.5,'speed':2,'crop':[20,10,100,100]})
    source['scenes'].append({'id':'end','duration':2,'headline':'Try <Real Brand> & go.'})
    (tmp_path/'session.json').write_text('{"session_id":"original"}')
    source_hash=hashlib.sha256(video.read_bytes()).hexdigest()
    history=tmp_path/'history.json'
    out=build(source,tmp_path/'cut',base_dir=tmp_path,history=history)
    assert out==tmp_path/'cut'
    markup=(out/'index.html').read_text()
    assert 'data-media-start="0.5" data-playback-rate="2"' in markup
    assert 'data-composition-id="main"' in markup
    assert 'window.__timelines.main=tl' in markup
    assert 'tl.fromTo("#copy-proof"' in markup
    assert 'tl.fromTo("#scene-' not in markup
    # Media must never inherit a second scene clock (HyperFrames static guard).
    import re
    assert all('data-start' not in tag for tag in re.findall(r'<section[^>]+>', markup))
    assert 'id="caption-proof" class="clip caption" data-start="0"' in markup
    assert '&lt;Real Brand&gt; &amp; go.' in markup.replace('<br>', ' ')
    assert 'recap' not in markup
    receipt=json.loads((out/'EDIT-DECISIONS.json').read_text())
    take=next(r for r in receipt['sources'] if r['source']==str(video))
    assert take['sha256']==source_hash==hashlib.sha256((out/take['asset']).read_bytes()).hexdigest()
    assert list((out/'evidence').rglob('session.json'))[0].read_text()=='{"session_id":"original"}'
    assert validate(out/'ad.json')['duration']==3
    rating=rate(history,'test-ad',5)
    assert rating['rating']==5
    assert json.loads(history.read_text())[-1]['rating']==5
    with pytest.raises(ValueError,match='absent or empty'):
        build(source,out,base_dir=tmp_path)
    assert hashlib.sha256(video.read_bytes()).hexdigest()==source_hash


def test_cli_plan_and_template_export(source,tmp_path):
    path=tmp_path/'spec.json'
    path.write_text(json.dumps(source))
    assert main(['plan',str(path),'--out',str(tmp_path/'plan.json')])==0
    assert json.loads((tmp_path/'plan.json').read_text())['schema']=='taskfilm-ad-plan/v1'
    assert main(['templates','--export','quiet-card','--out',str(tmp_path/'template.json')])==0
    assert json.loads((tmp_path/'template.json').read_text())['id']=='quiet-card'


def test_text_only_variable_scene_count(source,tmp_path):
    source['scenes']=[{'id':'single','duration':2,'headline':'A clear promise.'}]
    decision=validate(source,base_dir=tmp_path)
    assert len(decision['scenes'])==1
    assert decision['scenes'][0]['media'] is None


def _overlaps(a,b):
    return min(a[0]+a[2],b[0]+b[2])-max(a[0],b[0]) > 1e-8 and min(a[1]+a[3],b[1]+b[3])-max(a[1],b[1]) > 1e-8


@pytest.mark.parametrize('fmt',list(FORMATS))
def test_presenter_and_captions_reserve_safe_space(source,tmp_path,video,fmt):
    source['format']=fmt
    source['presenter']={'path':'take.mp4','scene_ids':['proof'],'placement':'bottom-right','size':.22}
    source['scenes'][0]['caption']='Real results, in one place.'
    for ident in templates():
        source['template']=ident
        decision=plan(source,base_dir=tmp_path)
        scene=decision['scenes'][0]
        avatar,caption=scene['presenter']['box'],scene['caption']['box']
        safe=decision['safe']
        boxes=list(scene['frame'][key] for key in ('copy','media','logo'))+[avatar,caption]
        for i,box in enumerate(boxes):
            assert box[0]>=safe[0]-1e-8 and box[1]>=safe[1]-1e-8
            assert box[0]+box[2]<=safe[0]+safe[2]+1e-8
            assert box[1]+box[3]<=safe[1]+safe[3]+1e-8
            assert all(not _overlaps(box,other) for other in boxes[i+1:])
        width,height=decision['canvas']
        assert avatar[2]*width/(avatar[3]*height)==pytest.approx(320/180)
        assert max(avatar[2]*width,avatar[3]*height)==pytest.approx(.22*min(width,height))


def test_presenter_uses_global_clock_and_portable_assets(source,tmp_path,video):
    source['scenes'].append({'id':'close','duration':1,'headline':'Try it today.','caption':'Start here.'})
    source['presenter']={'path':'take.mp4','scene_ids':['close']}
    out=build(source,tmp_path/'with-presenter',base_dir=tmp_path)
    decision=json.loads((out/'AD-PLAN.json').read_text())
    assert decision['scenes'][0]['presenter'] is None
    assert decision['scenes'][1]['presenter']['source']==str(video)
    markup=(out/'index.html').read_text()
    import re
    presenter=re.search(r'<video id="presenter-close"[^>]+>',markup).group()
    assert 'data-start="2"' in presenter
    assert 'data-media-start="2"' in presenter
    assert ' muted ' in presenter
    assert 'presenter-proof' not in markup
    assert 'id="subtitles-close"' in markup
    portable=json.loads((out/'ad.json').read_text())
    assert (out/portable['presenter']['path']).is_file()
    assert validate(out/'ad.json')['presenter']['source_duration']==3
    receipt=json.loads((out/'EDIT-DECISIONS.json').read_text())
    assert receipt['motion_policy']=={'maximum_families':2,'families':['cut','copy-fade-lift'],'generated_sfx':False}
    assert any(r['source']==str(video) for r in receipt['sources'])


@pytest.mark.parametrize('override',[
    {'scene_ids':['missing']}, {'scene_ids':['proof','proof']},
    {'placement':'top-left'}, {'size':.36}, {'size':True},
])
def test_presenter_rejects_invalid_contract(source,tmp_path,video,override):
    source['presenter']={'path':'take.mp4','scene_ids':['proof'],**override}
    with pytest.raises(ValueError,match='presenter'):
        validate(source,base_dir=tmp_path)


def test_presenter_duration_must_cover_last_selected_scene(source,tmp_path,video):
    source['scenes'].append({'id':'last','duration':2,'headline':'Try it.'})
    source['presenter']={'path':'take.mp4','scene_ids':['last']}
    with pytest.raises(ValueError,match='global time 4'):
        validate(source,base_dir=tmp_path)


def test_caption_fit_and_two_explicit_font_assets(source,tmp_path):
    from taskfilm.ad import KIT
    source['brand']['font']=str(KIT/'Manrope.ttf')
    source['brand']['headline_font']=str(KIT/'GeistMono.ttf')
    source['scenes'][0]['caption']='An explicit caption.'
    out=build(source,tmp_path/'fonts-and-caption',base_dir=tmp_path)
    spec=json.loads((out/'ad.json').read_text())
    assert spec['brand']['font']!=spec['brand']['headline_font']
    assert 'font-family:AdHeadline;' in (out/'index.html').read_text()
    assert validate(out/'ad.json')['scenes'][0]['caption']['lines']==['An explicit caption.']
    source['scenes'][0]['caption']='W'*170
    with pytest.raises(ValueError,match='caption must fit'):
        validate(source,base_dir=tmp_path)
    source.pop('presenter',None)
    source['motion']=['particles','typing','wobble']
    with pytest.raises(ValueError,match='unknown'):
        validate(source,base_dir=tmp_path)


def test_supplied_font_license_is_preserved_and_portable(source,tmp_path):
    license_path=tmp_path/'OFL.txt'
    original=b'SIL OPEN FONT LICENSE\nFixture license text.\n'
    license_path.write_bytes(original)
    source['brand']['font_license']='OFL.txt'
    out=build(source,tmp_path/'licensed',base_dir=tmp_path)
    portable=json.loads((out/'ad.json').read_text())
    asset=portable['brand']['font_license']
    assert (out/asset).read_bytes()==original
    receipt=json.loads((out/'EDIT-DECISIONS.json').read_text())
    entry=next(r for r in receipt['sources'] if r['source']==str(license_path))
    assert entry['asset']==asset
    assert entry['sha256']==hashlib.sha256(original).hexdigest()
    assert validate(out/'ad.json')['brand_assets']['font_license']==str(out/asset)
    source['brand']['font_license']='missing-OFL.txt'
    with pytest.raises(ValueError,match='brand.font_license'):
        validate(source,base_dir=tmp_path)


@pytest.mark.skipif(__import__('os').environ.get('TASKFILM_RENDER_TESTS') != '1',
                    reason='set TASKFILM_RENDER_TESTS=1 for real HyperFrames/Chrome render verification')
def test_playback_rate_render_maps_actual_source_frames(source,tmp_path):
    """A changing color clock makes ignored speed distinguishable in real pixels."""
    from taskfilm.ad import HF
    if any(not shutil.which(tool) for tool in ('ffmpeg','ffprobe','npx')):
        pytest.skip('requires ffmpeg, ffprobe and Node/npm with HyperFrames browser available')
    clock=tmp_path/'clock.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',
                    "nullsrc=s=160x90:r=10:d=8,geq=r='32+24*floor(T)':g=40:b=40",
                    '-an','-c:v','libx264','-threads','1','-g','10','-pix_fmt','yuv420p',str(clock)],check=True)
    source['format']='landscape'
    source['scenes']=[{'id':'intro','duration':1,'headline':'Clock test.'},
                      {'id':'fast','layout':'hero-stage','duration':1,'headline':'Six times faster.',
                       'media':{'type':'video','path':str(clock),'in':.5,'speed':6}}]
    project=build(source,tmp_path/'speed-project',base_dir=tmp_path)
    rendered=tmp_path/'render.mp4'
    subprocess.run(['npx','--yes',HF,'render',str(project),'--output',str(rendered),
                    '--fps','10','--quality','draft','--workers','1'],capture_output=True,check=True,timeout=180)
    decision=json.loads((project/'AD-PLAN.json').read_text())
    x,y,w,h=decision['scenes'][1]['frame']['media']
    width,height=decision['canvas']
    cx,cy=round((x+w/2)*width),round((y+h/2)*height)
    def pixel(path,time,x,y):
        return list(subprocess.check_output(['ffmpeg','-v','error','-ss',str(time),'-i',str(path),
                     '-vf',f'crop=8:8:{x-4}:{y-4},scale=1:1','-frames:v','1','-pix_fmt','rgb24','-f','rawvideo','-']))
    for output_time,source_time,wrong_time in [(1.2,1.7,.7),(1.5,3.5,1),(1.8,5.3,1.3)]:
        actual=pixel(rendered,output_time,cx,cy)
        expected=pixel(clock,source_time,80,45)
        unretimed=pixel(clock,wrong_time,80,45)
        assert len(actual)==len(expected)==3
        assert max(abs(a-b) for a,b in zip(actual,expected))<10
        assert abs(actual[0]-unretimed[0])>15
