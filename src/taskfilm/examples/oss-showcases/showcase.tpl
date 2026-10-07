<!doctype html>
<html><head><meta charset="utf-8"><style>
@font-face{font-family:Manrope;src:url(assets/Manrope.ttf)}
@font-face{font-family:GeistMono;src:url(assets/GeistMono.ttf)}
*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#f3f2ed}
#root{position:relative;width:100%;height:100%;overflow:hidden;color:#17251f;font-family:Manrope,sans-serif}
.ground{position:absolute;inset:0;background:#f3f2ed}
.masthead{position:absolute;top:52px;left:78px;right:78px;display:flex;justify-content:space-between;font:24px GeistMono,monospace;z-index:20}
.masthead strong{font-family:Manrope,sans-serif;font-size:32px}.masthead .mode{color:__ACCENT__}
.progress{position:absolute;top:105px;left:78px;width:1764px;height:3px;background:__ACCENT__;transform-origin:left center;z-index:20}
.intro{position:absolute;inset:0}.intro-inner{position:absolute;left:108px;top:215px;width:1704px}
.eyebrow{font:25px GeistMono,monospace;color:__ACCENT__;margin-bottom:45px}
.line{overflow:hidden;height:167px;font-size:152px;line-height:1.08;font-weight:800;letter-spacing:-8px}
.word{display:block;will-change:transform}.about{font-size:37px;line-height:1.35;margin-top:47px;max-width:1450px}
.visual{position:absolute;left:96px;top:165px;width:1728px;height:782px;overflow:hidden;background:#ebeae5;border:2px solid #c4c8bf;border-radius:18px;perspective:1600px;opacity:0}
.screen{position:absolute;inset:0;transform-origin:center center;will-change:transform}
.screen video,.screen img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;object-position:center;background:#ebeae5}
.step{position:absolute;left:110px;bottom:58px;display:flex;align-items:center;gap:26px;font-size:35px;font-weight:650;z-index:15}
.number{font:23px GeistMono,monospace;color:__ACCENT__}
.outro{position:absolute;inset:0;background:#f3f2ed;z-index:16}
.outro-inner{position:absolute;left:108px;top:210px;width:1704px}
.result-title{font-size:86px;line-height:1.1;font-weight:800;letter-spacing:-4px;max-width:1650px}
.contribution{margin-top:66px;display:flex;align-items:flex-start;gap:66px}
.contribution strong{display:block;font-size:43px;margin-bottom:15px}
.contribution p{font-size:31px;line-height:1.4;margin:0;max-width:720px}
.source{position:absolute;bottom:74px;left:108px;font:24px GeistMono,monospace;color:__ACCENT__}
</style><script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script></head>
<body><div id="root" data-composition-id="__ID__" data-width="1920" data-height="1080" data-duration="__DURATION__">
<div id="paper-ground" class="clip ground" data-start="0" data-duration="__DURATION__" data-track-index="0"></div>
<header id="app-masthead" class="clip masthead" data-start="0" data-duration="__DURATION__" data-track-index="6"><strong>__APP__</strong><span class="mode">Taskfilm / __MODE__</span></header>
<div id="film-progress" class="clip" data-start="0" data-duration="__DURATION__" data-track-index="7"><div class="progress"></div></div>
<section id="app-intro" class="clip intro" data-start="0" data-duration="__INTRO__" data-track-index="1"><div class="intro-inner"><div class="eyebrow">ONE REAL WORKFLOW</div>__TITLE__<div class="about">__ABOUT__</div></div></section>
<div class="visual"><div class="screen">
__VIDEOS__
__FREEZE__
</div></div>
__LABELS__
__LESSON_NOTES__
<section id="workflow-result" class="clip outro" data-start="__END_START__" data-duration="__END__" data-track-index="8"><div class="outro-inner"><div class="eyebrow">THE RESULT</div><div class="result-title">__RESULT__</div><div class="contribution"><div><strong>Made with Taskfilm.</strong><p>Real browser footage, retained result evidence and editable HTML motion graphics.</p></div><div><strong>__NEXT_TITLE__</strong><p>__NEXT_COPY__</p></div></div></div><div class="source">__SOURCE__</div></section>
__AUDIO__
</div><script>
const tl=gsap.timeline({paused:true});
tl.fromTo('.word-0',{y:175},{y:0,duration:.9,ease:'power4.out'},.15);
tl.fromTo('.word-1',{y:175},{y:0,duration:.95,ease:'power3.out'},.38);
tl.fromTo('.intro-inner .eyebrow',{opacity:0,x:-25},{opacity:1,x:0,duration:.6,ease:'power2.out'},.1);
tl.fromTo('.about',{opacity:0,y:18},{opacity:1,y:0,duration:.8,ease:'power2.out'},.8);
tl.fromTo('.progress',{scaleX:0},{scaleX:1,duration:__DURATION__,ease:'none'},0);
tl.fromTo('.visual',{opacity:0},{opacity:1,duration:.35,ease:'power2.out'},__INTRO__);
tl.fromTo('.screen',{rotationY:5,scale:.94},{rotationY:0,scale:1,duration:1.1,ease:'power3.out'},__INTRO__);
__PREVIEW_MOTION__
__DETAIL_MOTION__
tl.fromTo('.outro-inner',{opacity:0,y:24},{opacity:1,y:0,duration:.65,ease:'power3.out'},__END_START__);
window.__timelines['__ID__']=tl;
</script></body></html>
