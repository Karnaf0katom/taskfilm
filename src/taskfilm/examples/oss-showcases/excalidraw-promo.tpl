<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=1920,height=1080"><title>Excalidraw — Less explaining. More clarity.</title>
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<style>
@font-face{font-family:Manrope;src:url('assets/Manrope.ttf')}@font-face{font-family:GeistMono;src:url('assets/GeistMono.ttf')}
*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;background:#111714;color:#f3f2ed;font-family:Manrope,sans-serif}#root{position:relative;width:100%;height:100%;overflow:hidden;background:#111714}.clip{position:absolute;inset:0}.ground{background:#111714}.chrome{position:absolute;left:96px;right:96px;top:58px;display:flex;justify-content:space-between;align-items:center;z-index:8}.brand{font-size:27px;font-weight:750;letter-spacing:-1px}.meta{font:18px GeistMono,monospace;letter-spacing:1px;color:#b2c2b7}.accent{color:#d7ff58}.footer-rule{position:absolute;left:96px;right:96px;bottom:49px;height:2px;background:#35443b;z-index:8}.progress{width:100%;height:100%;background:#d7ff58;transform-origin:left}.scene-inner{position:absolute;inset:0}.hero-copy{position:absolute;left:96px;top:240px;width:1150px}.kicker{font:20px GeistMono,monospace;letter-spacing:2px;color:#b2c2b7}.mask{overflow:hidden;padding-bottom:12px}.hero-title{display:block;font-size:122px;font-weight:750;line-height:1.14;letter-spacing:-6px}.hero-note{font-size:31px;line-height:1.5;margin:30px 0 0;max-width:920px;color:#c4d0c8}.idea-cards{position:absolute;left:1300px;top:254px;width:500px;height:540px;perspective:1400px}.idea-card{position:absolute;width:340px;height:140px;border:2px solid #8faaa0;border-radius:22px;background:#17291f;display:flex;align-items:center;justify-content:center;font-size:38px;font-weight:650}.idea-card:nth-child(1){left:10px;top:0}.idea-card:nth-child(2){left:90px;top:190px}.idea-card:nth-child(3){left:10px;top:380px;border-color:#d7ff58;color:#d7ff58}.hero-small{position:absolute;left:96px;bottom:158px;font:20px GeistMono,monospace;color:#9ab6a5}
#browser-stage{position:absolute;left:164px;top:164px;width:1592px;height:786px;perspective:1600px;opacity:0}.browser-window{width:100%;height:100%;border-radius:18px;background:#f3f2ed;overflow:hidden;border:2px solid #697d6e;transform-origin:50% 50%}.browser-bar{height:44px;background:#e7eae3;display:flex;align-items:center;gap:9px;padding:0 20px;color:#526254;font:16px GeistMono,monospace}.dot{width:10px;height:10px;border-radius:50%;background:#8c9d8f}.address{margin-left:28px}.screen-crop{position:relative;height:740px;overflow:hidden;background:#fff}.camera{position:absolute;inset:0;transform-origin:50% 43%}.take{width:100%;height:100%;object-fit:contain}.task-label{position:absolute;left:96px;top:972px;right:96px;display:flex;justify-content:space-between;align-items:baseline}.task-title{font-size:35px;font-weight:650;letter-spacing:-1px}.task-number{font:19px GeistMono,monospace;color:#b2c2b7}.caption-text{display:inline-block}.label-slot{height:54px;overflow:hidden}.source-tag{position:absolute;top:117px;left:170px;font:16px GeistMono,monospace;color:#a4bbaa;letter-spacing:1px}
.result-copy{position:absolute;left:96px;top:180px}.result-title{font-size:83px;font-weight:750;letter-spacing:-4px;margin:18px 0 0}.diagram-stage{position:absolute;left:150px;top:380px;width:1620px;height:470px}#native-diagram{width:100%;height:100%;overflow:visible}.diagram-line{fill:none;stroke:#d7ff58;stroke-width:3;stroke-linecap:round;stroke-linejoin:round}.diagram-label{fill:#f3f2ed;font-family:Manrope,sans-serif;font-size:26px;font-weight:650}.result-proof{position:absolute;left:96px;bottom:125px;right:96px;display:flex;justify-content:space-between;font:20px GeistMono,monospace;color:#afc9b7}.proof-dot{display:inline-block;width:11px;height:11px;border-radius:50%;background:#d7ff58;margin-right:12px}
.end-copy{position:absolute;left:96px;top:178px;width:1600px}.end-title{font-size:138px;line-height:1.1;font-weight:750;letter-spacing:-7px;margin:32px 0}.end-line{display:block}.end-note{font-size:32px;color:#c4d0c8;margin:28px 0 0}.cta{position:absolute;left:96px;bottom:172px;display:flex;align-items:center;gap:24px}.cta-pill{border:1px solid #d7ff58;border-radius:7px;background:#d7ff58;color:#111714;padding:17px 24px;font-size:27px;font-weight:750}.cta-url{font:25px GeistMono,monospace;color:#f3f2ed}.end-source{position:absolute;left:96px;bottom:109px;font:17px GeistMono,monospace;color:#9bb5a4}.end-mark{position:absolute;right:155px;top:300px;width:230px;height:230px;border:3px solid #d7ff58;border-radius:32px;display:grid;place-items:center;perspective:1000px}.play-mark{width:0;height:0;border-top:54px solid transparent;border-bottom:54px solid transparent;border-left:85px solid #d7ff58;margin-left:16px}
</style></head><body>
<div id="root" data-composition-id="excalidraw-motion-promo" data-width="1920" data-height="1080" data-duration="48" data-fps="30">
<div class="clip ground" data-start="0" data-duration="48" data-track-index="0"></div>
<header class="chrome"><span class="brand">Taskfilm<span class="accent"> / </span>Excalidraw</span><span class="meta">ONE REAL WORKFLOW <span class="accent">↗</span></span></header>
<div class="footer-rule"><div class="progress"></div></div>
<section class="clip" data-start="0" data-duration="7" data-track-index="1"><div class="scene-inner" id="hero-inner">
<div class="hero-copy"><div class="kicker" id="hero-kicker">AN IDEA YOU CAN ACTUALLY SEE</div><div class="mask"><span class="hero-title" id="hero-line-a">Less explaining.</span></div><div class="mask"><span class="hero-title accent" id="hero-line-b">More clarity.</span></div><p class="hero-note" id="hero-note">Give your next idea a clear picture.</p></div>
<div class="idea-cards"><div class="idea-card" id="idea-a">Idea</div><div class="idea-card" id="idea-b">Prototype</div><div class="idea-card" id="idea-c">Ship <span class="accent">↗</span></div></div>
<div class="hero-small" id="hero-small">EXCALIDRAW · OPEN-SOURCE WHITEBOARD</div></div></section>
<div id="browser-stage"><div class="browser-window" id="browser-window"><div class="browser-bar"><span class="dot"></span><span class="dot"></span><span class="dot"></span><span class="address">excalidraw.com</span></div><div class="screen-crop"><div class="camera" id="native-camera">__VIDEOS__</div></div></div></div>
<div class="clip" data-start="7" data-duration="30" data-track-index="4"><div class="source-tag">ACTUAL BROWSER RECORDING · COMPLETE SOURCE RETAINED</div></div>
<section class="clip" data-start="7" data-duration="14" data-track-index="5"><div class="task-label"><div class="label-slot"><span class="task-title caption-text" id="label-draw">Draw it. Name it.</span></div><span class="task-number">01 / DRAW</span></div></section>
<section class="clip" data-start="21" data-duration="10" data-track-index="5"><div class="task-label"><div class="label-slot"><span class="task-title caption-text" id="label-connect">Connect the next step.</span></div><span class="task-number">02 / CONNECT</span></div></section>
<section class="clip" data-start="31" data-duration="6" data-track-index="5"><div class="task-label"><div class="label-slot"><span class="task-title caption-text" id="label-save">Keep it editable.</span></div><span class="task-number">03 / SAVE</span></div></section>
<section class="clip" data-start="37" data-duration="5" data-track-index="6"><div class="scene-inner" id="result-inner"><div class="result-copy"><div class="kicker" id="result-kicker">THE SAME SAVED DIAGRAM. NOW IN MOTION.</div><div class="result-title" id="result-title">One picture. A clear direction.</div></div><div class="diagram-stage">__DIAGRAM__</div><div class="result-proof" id="result-proof"><span><span class="proof-dot"></span>Native .excalidraw saved</span><span>Retained geometry · motion treatment</span></div></div></section>
<section class="clip" data-start="42" data-duration="6" data-track-index="7"><div class="scene-inner" id="end-inner"><div class="end-copy"><div class="kicker" id="end-kicker">MAKE YOUR NEXT WORKFLOW WORTH WATCHING</div><div class="end-title"><div class="mask"><span class="end-line" id="end-line-a">Made with</span></div><div class="mask"><span class="end-line accent" id="end-line-b">Taskfilm.</span></div></div><p class="end-note" id="end-note">Real capture. Editable motion. Your film.</p></div><div class="end-mark" id="end-mark"><div class="play-mark"></div></div><div class="cta" id="end-cta"><span class="cta-pill">Try the workflow ↗</span><span class="cta-url">github.com/Karnaf0katom/taskfilm</span></div><div class="end-source" id="end-source">APP: github.com/excalidraw/excalidraw · Independent showcase</div></div></section>
__VOICES__
<audio id="music-bed" src="assets/music.wav" data-start="0" data-duration="48" data-volume="0.25" data-track-index="11"></audio>
</div>
<script>
const tl=gsap.timeline({paused:true});
tl.fromTo('.progress',{scaleX:0},{scaleX:1,duration:48,ease:'none'},0);
tl.fromTo('#hero-kicker',{y:18,opacity:0},{y:0,opacity:1,duration:.45,ease:'power2.out'},.1);
tl.fromTo('#hero-line-a',{yPercent:115},{yPercent:0,duration:.85,ease:'power4.out'},.25);
tl.fromTo('#hero-line-b',{yPercent:115},{yPercent:0,duration:.85,ease:'power4.out'},.7);
tl.fromTo('#hero-note',{y:25,opacity:0},{y:0,opacity:1,duration:.65,ease:'power3.out'},1.25);
tl.fromTo('#hero-small',{opacity:0},{opacity:1,duration:.6},1.6);
tl.fromTo('#idea-a',{x:65,y:35,rotation:-12,rotationY:-28,opacity:0},{x:0,y:0,rotation:0,rotationY:0,opacity:1,duration:1.4,ease:'power3.out'},.7);
tl.fromTo('#idea-b',{x:-90,y:-25,rotation:13,rotationY:30,opacity:0},{x:0,y:0,rotation:0,rotationY:0,opacity:1,duration:1.4,ease:'power3.out'},1.2);
tl.fromTo('#idea-c',{x:80,y:-20,rotation:-9,rotationY:-18,opacity:0},{x:0,y:0,rotation:0,rotationY:0,opacity:1,duration:1.4,ease:'power3.out'},1.7);
tl.to('#hero-inner',{y:-40,opacity:0,duration:.4,ease:'power2.in'},6.6);
tl.set('#browser-stage',{opacity:1},7);
tl.fromTo('#browser-window',{rotationX:13,rotationY:-7,scale:.87,y:64},{rotationX:0,rotationY:0,scale:1,y:0,duration:1.1,ease:'power3.out'},7);
tl.fromTo('#label-draw',{yPercent:110},{yPercent:0,duration:.65,ease:'power3.out'},7.15);
tl.fromTo('#label-connect',{yPercent:110},{yPercent:0,duration:.65,ease:'power3.out'},21.1);
tl.fromTo('#label-save',{yPercent:110},{yPercent:0,duration:.65,ease:'power3.out'},31.1);
tl.to('#native-camera',{scale:1.35,x:-55,y:40,duration:1.25,ease:'power3.inOut'},21);
tl.to('#native-camera',{scale:1,x:0,y:0,duration:.8,ease:'power3.inOut'},30.8);
tl.to('#browser-window',{scale:.97,y:-14,opacity:0,duration:.4,ease:'power2.in'},36.6);
tl.set('#browser-stage',{opacity:0},37);
tl.fromTo('#result-kicker',{opacity:0,y:18},{opacity:1,y:0,duration:.4,ease:'power2.out'},37.1);
tl.fromTo('#result-title',{opacity:0,y:30},{opacity:1,y:0,duration:.65,ease:'power3.out'},37.2);
document.querySelectorAll('.diagram-line').forEach((path,i)=>{const length=path.getTotalLength();tl.fromTo(path,{strokeDasharray:length,strokeDashoffset:length},{strokeDashoffset:0,duration:1.0,ease:'sine.inOut'},37.3+i*.18);});
tl.fromTo('.diagram-label',{opacity:0,y:9},{opacity:1,y:0,stagger:.22,duration:.55,ease:'power2.out'},37.8);
tl.fromTo('#result-proof',{opacity:0,y:15},{opacity:1,y:0,duration:.5,ease:'power2.out'},38.5);
tl.to('#result-inner',{opacity:0,y:-25,duration:.35,ease:'power2.in'},41.65);
tl.fromTo('#end-kicker',{opacity:0,y:15},{opacity:1,y:0,duration:.45,ease:'power2.out'},42.1);
tl.fromTo('#end-line-a',{yPercent:115},{yPercent:0,duration:.7,ease:'power4.out'},42.2);
tl.fromTo('#end-line-b',{yPercent:115},{yPercent:0,duration:.7,ease:'power4.out'},42.55);
tl.fromTo('#end-mark',{rotationY:-40,rotation:-12,scale:.75,opacity:0},{rotationY:0,rotation:0,scale:1,opacity:1,duration:1.1,ease:'power3.out'},42.5);
tl.fromTo('#end-note',{opacity:0,y:20},{opacity:1,y:0,duration:.55,ease:'power2.out'},43.1);
tl.fromTo('#end-cta',{opacity:0,y:25},{opacity:1,y:0,duration:.55,ease:'power3.out'},43.5);
tl.fromTo('#end-source',{opacity:0},{opacity:1,duration:.5},44.0);
tl.set({}, {},48);
window.__timelines=window.__timelines||{};window.__timelines['excalidraw-motion-promo']=tl;
</script></body></html>
