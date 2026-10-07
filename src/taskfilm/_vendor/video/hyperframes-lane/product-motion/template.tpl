<!doctype html>
<html lang="en"><head><meta charset="UTF-8"><title>__TITLE__</title>
<script src="__GSAP_SRC__"></script>
<style>
@font-face{font-family:Manrope;src:url('assets/Manrope.ttf') format('truetype');font-weight:200 800;font-display:block}
@font-face{font-family:GeistMono;src:url('assets/GeistMono.ttf') format('truetype');font-weight:100 900;font-display:block}
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:var(--deep)}
body{font-family:Manrope,sans-serif;color:var(--paper);-webkit-font-smoothing:antialiased}
#root{position:relative;width:100%;height:100%;overflow:hidden;background:var(--deep)}
.layer{position:absolute;inset:0}
.mono{font-family:GeistMono,monospace}

/* ---------- HOOK ---------- */
#hook{z-index:1;overflow:hidden}
.hook-bg{position:absolute;inset:0}
.hook-glow{position:absolute;width:1000px;height:1000px;border-radius:50%;opacity:0}
.storm-stage{position:absolute;inset:0;perspective:1000px;perspective-origin:50% 50%}
.storm-world{position:absolute;width:10px;height:10px;transform-style:preserve-3d}
.scard{position:absolute;left:0;top:0;white-space:nowrap;background:var(--card);color:var(--ink);border-radius:24px;padding:20px 32px 22px;font-size:40px;font-weight:650;letter-spacing:-.6px;box-shadow:0 18px 44px rgba(0,0,0,.4);opacity:0}
.scard small{display:block;font-family:GeistMono;font-size:16px;font-weight:600;letter-spacing:.12em;color:var(--cardsmall);margin-bottom:6px}
.scard em{font-style:normal;color:var(--tag);font-weight:750;margin-left:10px}
.kgroup{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}
.kline{font-weight:800;line-height:1.04;color:var(--paper);white-space:nowrap;opacity:0;text-shadow:0 10px 40px rgba(0,0,0,.35)}
.kline .acc{color:var(--lime)}
.kline .ch{display:inline-block}
.kline .sp{display:inline-block;width:.26em}
.hero-wrap{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}
.hero{background:var(--card);color:var(--ink);border-radius:30px;padding:28px 46px 32px;font-weight:720;letter-spacing:-1.4px;line-height:1.12;box-shadow:0 40px 100px rgba(0,0,0,.5);opacity:0}
.hero small{display:block;font-family:GeistMono;font-size:20px;font-weight:600;letter-spacing:.14em;color:var(--cardsmall);margin-bottom:10px}
.hero b{color:var(--herob);font-weight:800}

/* ---------- PRODUCT ---------- */
#product{z-index:2;opacity:0}
.paper{position:absolute;inset:0;background:var(--paper);overflow:hidden}
.dots{position:absolute;left:-120px;top:-120px;background-size:38px 38px}
.blob{position:absolute;border-radius:50%}
.stage{position:absolute;inset:0;perspective:1500px;perspective-origin:50% 50%}
.world{position:absolute;inset:0;transform-style:preserve-3d}
.window{position:absolute;overflow:hidden;background:var(--page)}
.chrome{position:absolute;left:0;top:0;background:var(--chrome);border-bottom:1px solid var(--chromeline);display:flex;align-items:center;gap:12px;padding-left:28px}
.chrome i{width:16px;height:16px;border-radius:50%;background:var(--chromedot);display:block}
.chrome span{flex:1;text-align:center;padding-right:120px;font-family:GeistMono;font-size:17px;color:var(--chrometext);letter-spacing:.1em;white-space:nowrap}
.screen{position:absolute;left:0;overflow:hidden;background:var(--page)}
.lens{position:absolute;left:0;top:0;width:3840px;height:2160px;transform-origin:0 0}
.lens video{position:absolute;left:0;top:0;width:3840px;height:2160px;max-width:none;object-fit:fill}
.sheen{position:absolute;left:0;top:-200px;width:700px;background:linear-gradient(100deg,rgba(255,255,255,0) 0%,rgba(255,255,255,.62) 48%,rgba(255,255,255,0) 100%);opacity:0}

/* overlays in lens space (source 3840x2160 pixels) */
.ov{position:absolute}
#cursor{position:absolute;left:0;top:0;width:66px;height:66px;opacity:0}
.ring{position:absolute;width:190px;height:190px;border-radius:50%;border:9px solid var(--accent);opacity:0}
.ring.lime{border-color:var(--lime);border-width:7px}
#spot{position:absolute;width:9000px;height:9000px;opacity:0}
#stamp{position:absolute;padding:20px 40px 22px;border-radius:999px;background:var(--lime);color:var(--ink);font-size:70px;font-weight:800;letter-spacing:-1.5px;white-space:nowrap;opacity:0}
#tagc{position:absolute;overflow:visible;opacity:0}
#tagc path{fill:none;stroke:var(--accent);stroke-width:10;stroke-linecap:round;stroke-linejoin:round}
#tagnote{position:absolute;padding:14px 26px;border-radius:16px;background:var(--ink);color:var(--lime);font-family:GeistMono;font-size:34px;font-weight:600;letter-spacing:.06em;white-space:nowrap;opacity:0}
#lift{position:absolute;overflow:hidden;border-radius:26px}
#lift video{position:absolute;width:3840px;height:2160px;max-width:none}
#liftglow{position:absolute;border-radius:32px;border:7px solid var(--accent);opacity:0}
#scan{position:absolute;height:10px;background:var(--accent);opacity:0}
#scan i{position:absolute;left:0;right:0;bottom:10px;height:300px;display:block}
#track{position:absolute;opacity:0}
#track i{position:absolute;width:84px;height:84px;border:0 solid var(--ink);display:block}
#track .a{left:0;top:0;border-left-width:10px;border-top-width:10px;border-top-left-radius:18px}
#track .b{right:0;top:0;border-right-width:10px;border-top-width:10px;border-top-right-radius:18px}
#track .c{left:0;bottom:0;border-left-width:10px;border-bottom-width:10px;border-bottom-left-radius:18px}
#track .d{right:0;bottom:0;border-right-width:10px;border-bottom-width:10px;border-bottom-right-radius:18px}
#tlabel{position:absolute;padding:14px 26px;border-radius:16px;background:var(--ink);color:var(--lime);font-family:GeistMono;font-size:38px;font-weight:650;letter-spacing:.1em;white-space:nowrap;opacity:0}
#marker{position:absolute;mix-blend-mode:multiply;border-radius:10px;transform-origin:0 50%;opacity:0}
#lock{position:absolute;opacity:0}
#lock i{position:absolute;width:46px;height:46px;border:0 solid var(--ink);display:block}
#lock .a{left:0;top:0;border-left-width:8px;border-top-width:8px}
#lock .b{right:0;top:0;border-right-width:8px;border-top-width:8px}
#lock .c{left:0;bottom:0;border-left-width:8px;border-bottom-width:8px}
#lock .d{right:0;bottom:0;border-right-width:8px;border-bottom-width:8px}
#locklabel{position:absolute;padding:10px 20px;border-radius:12px;background:var(--lime);color:var(--ink);font-family:GeistMono;font-size:30px;font-weight:700;letter-spacing:.14em;white-space:nowrap;opacity:0}
.p{position:absolute;left:0;top:0;opacity:0}

/* screen-space HUD, copy and slabs */
.intro{position:absolute;color:var(--ink)}
.intro .eb{font-family:GeistMono;font-size:22px;letter-spacing:.24em;font-weight:650;color:var(--mute);opacity:0}
.wm{display:flex;align-items:flex-end;font-weight:800;line-height:1.02;margin-top:26px;perspective:900px;white-space:nowrap}
.wm .l{display:inline-block;transform-origin:50% 88%;opacity:0}
.wm .sp{display:inline-block;width:.24em}
.wm .dot{display:inline-block;color:var(--accent);opacity:0}
.intro .tag{margin-top:18px}
.intro .tag div{overflow:hidden}
.intro .tag span{display:block;font-weight:750;line-height:1.14;white-space:nowrap}
.intro .chips{display:flex;gap:14px;margin-top:30px}
.intro .chips span{display:block;padding:12px 20px;border-radius:999px;border:2px solid rgba(0,0,0,.28);font-family:GeistMono;font-size:19px;font-weight:650;letter-spacing:.14em;color:var(--ink);opacity:0}
#hud{position:absolute;inset:0;color:var(--ink);font-family:GeistMono;opacity:0}
#hud .corner{position:absolute;width:48px;height:48px;border:0 solid}
#hud .c1{left:34px;top:34px;border-left-width:3px;border-top-width:3px}
#hud .c2{right:34px;top:34px;border-right-width:3px;border-top-width:3px}
#hud .c3{left:34px;bottom:34px;border-left-width:3px;border-bottom-width:3px}
#hud .c4{right:34px;bottom:34px;border-right-width:3px;border-bottom-width:3px}
#hud .tl{position:absolute;display:flex;align-items:center;gap:14px;font-size:18px;font-weight:650;letter-spacing:.18em;padding:10px 16px;border-radius:12px;white-space:nowrap}
#hud .rec{width:13px;height:13px;border-radius:50%;background:var(--rec);display:block}
#hud .tr{position:absolute;font-size:18px;font-weight:650;letter-spacing:.18em;padding:10px 16px;border-radius:12px;text-align:right;white-space:nowrap}
#steps{position:absolute;width:620px;height:54px;border-radius:999px}
#pill{position:absolute;left:7px;top:7px;width:198px;height:40px;border-radius:999px;background:var(--ink);opacity:0}
#steps span{position:absolute;top:0;width:198px;height:54px;line-height:54px;text-align:center;font-size:17px;font-weight:650;letter-spacing:.16em;color:var(--ink);white-space:nowrap}
.slab{position:absolute;opacity:0}
.slab .bg{position:absolute;inset:0;border-radius:28px;background:var(--ink);transform-origin:0 50%}
.slab .in{position:relative;padding:24px 42px 30px}
.slab .eb{font-family:GeistMono;font-size:20px;font-weight:650;letter-spacing:.2em;color:var(--lime)}
.slab .mask{overflow:hidden;margin-top:6px;padding-bottom:6px}
.slab h2{font-weight:800;line-height:1.04;color:var(--paper);white-space:nowrap}
.slab p{font-weight:600;color:var(--slabp);margin-top:4px;white-space:nowrap}
.slab.save .bg{background:var(--accent)}
.slab.save .eb,.slab.save h2{color:var(--deep)}
.slab.save p{color:var(--savep)}

/* ---------- RECAP ---------- */
#recap{z-index:3;opacity:0}
.recap-bg{position:absolute;inset:0}
.recap-stage{position:absolute;inset:0;perspective:1300px}
.recap-world{position:absolute;inset:0;transform-style:preserve-3d}
.rcard{position:absolute;border-radius:26px;overflow:hidden;background:var(--page);box-shadow:0 40px 90px rgba(0,0,0,.45);opacity:0}
.rcard video{position:absolute;max-width:none}
.rl{position:absolute;text-align:center;font-weight:800;color:var(--paper);white-space:nowrap;text-shadow:0 10px 36px rgba(0,0,0,.5);opacity:0}
.rl.acc{color:var(--lime)}

/* ---------- END ---------- */
#endcard{z-index:4;overflow:hidden}
.end-bg{position:absolute;inset:0}
.rays{position:absolute;border-radius:50%;opacity:.6}
.mote{position:absolute;left:0;top:0;border-radius:50%;background:var(--lime);opacity:0}
.end-inner{position:absolute;left:0;display:flex;flex-direction:column;align-items:center}
.ewm{position:relative;display:flex;align-items:flex-end;font-weight:800;line-height:1;perspective:1000px;color:var(--paper);white-space:nowrap}
.glint{position:absolute;left:0;top:0;display:flex;align-items:flex-end;background:linear-gradient(100deg,rgba(255,255,255,0) 42%,rgba(255,255,255,.95) 50%,rgba(255,255,255,0) 58%);background-size:320% 100%;background-repeat:no-repeat;-webkit-background-clip:text;background-clip:text;color:transparent;pointer-events:none}
.glint span{display:inline-block}
.glint .sp,.ewm .sp{display:inline-block;width:.24em}
.ewm .l{display:inline-block;transform-origin:50% 90%;opacity:0}
.ewm .dot{display:inline-block;color:var(--lime);opacity:0}
.etag{display:flex;margin-top:40px}
.etag div{overflow:hidden}
.etag span{display:block;font-weight:750;color:var(--paper);white-space:nowrap}
.etag span.acc{color:var(--lime)}
.url{margin-top:44px;height:56px;display:flex;align-items:center;font-family:GeistMono;font-weight:600;letter-spacing:.02em;color:var(--paper);opacity:0;white-space:nowrap}
.url i{display:block;width:4px;height:44px;margin-left:6px;background:var(--lime)}
.echips{display:flex;gap:16px;margin-top:30px}
.echips span{display:block;padding:12px 22px;border-radius:999px;border:2px solid;font-family:GeistMono;font-size:20px;font-weight:650;letter-spacing:.16em;color:var(--lime);opacity:0}
.limit{margin-top:30px;font-size:27px;font-weight:600;color:var(--limit);opacity:0}
.efoot{position:absolute;left:0;text-align:center;font-family:GeistMono;font-size:18px;font-weight:650;letter-spacing:.3em;color:var(--foot);opacity:0}

#flash{position:absolute;inset:0;z-index:20;background:var(--flash);opacity:0}
#grain{position:absolute;left:-200px;top:-200px;z-index:21;opacity:0;background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='240' height='240'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 .55 0'/></filter><rect width='240' height='240' filter='url(%23n)'/></svg>")}
__LAYOUT_CSS__
</style></head>
<body>
<div id="root" data-composition-id="__COMP_ID__" data-width="__W__" data-height="__H__" data-duration="__DUR__">
  <svg width="0" height="0" style="position:absolute" aria-hidden="true">
    <filter id="stageblur" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur id="stageblur-n" stdDeviation="0 0"/></filter>
    <filter id="whip" x="-5%" y="-5%" width="110%" height="110%"><feGaussianBlur id="whip-n" stdDeviation="0 0"/></filter>
    <filter id="rgb" x="-5%" y="-5%" width="110%" height="110%" color-interpolation-filters="sRGB">
      <feColorMatrix in="SourceGraphic" type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="r"/>
      <feOffset id="rgb-r" in="r" dx="0" dy="0" result="r2"/>
      <feColorMatrix in="SourceGraphic" type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0" result="g"/>
      <feColorMatrix in="SourceGraphic" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0" result="b"/>
      <feOffset id="rgb-b" in="b" dx="0" dy="0" result="b2"/>
      <feBlend in="r2" in2="g" mode="screen" result="rg"/>
      <feBlend in="rg" in2="b2" mode="screen"/>
    </filter>
  </svg>

  <section id="hook" class="clip layer" data-start="0" data-duration="__HOOK_DUR__" data-track-index="1">
    <div class="hook-bg"></div>
    <div class="hook-glow" id="hook-glow"></div>
    <div class="storm-stage" id="storm-stage"><div class="storm-world" id="storm" data-layout-allow-overflow>__STORM__</div></div>
    <div class="kgroup" id="kg1"><div class="kline" id="k1">__K1__</div><div class="kline" id="k2">__K2__</div></div>
    <div class="kgroup" id="kg2"><div class="kline" id="k3">__K3__</div><div class="kline" id="k4">__K4__</div></div>
    <div class="hero-wrap"><div class="hero" id="hero">__HERO__</div></div>
  </section>

  <div id="product" class="layer" data-layout-allow-overflow>
    <div class="paper"><div class="dots" id="dots"></div><div class="blob b1" id="blob1"></div><div class="blob b2" id="blob2"></div></div>
    <div class="stage" id="stage">
      <div class="world" id="world">
        <div class="window" id="window">
          <div class="chrome"><i></i><i></i><i></i><span>__WINDOW_TITLE__</span></div>
          <div class="screen" id="screen">
            <div class="lens" id="lens" data-layout-allow-overflow>
              __VIDEOS__
              <div id="spot" class="ov"></div>
              <svg id="tagc" class="ov" __TAGC_ATTR__><path id="tagc-path" d="__TAGC_PATH__"/></svg>
              <div id="tagnote" class="ov">__TAG_NOTE__</div>
              __LIFT__
              <div id="liftglow" class="ov"></div>
              <div id="scan" class="ov"><i></i></div>
              <div id="marker" class="ov"></div>
              <div id="track" class="ov"><i class="a"></i><i class="b"></i><i class="c"></i><i class="d"></i></div>
              <div id="tlabel" class="ov">__TRACK_LABEL__</div>
              <div id="lock" class="ov"><i class="a"></i><i class="b"></i><i class="c"></i><i class="d"></i></div>
              <div id="locklabel" class="ov">__LOCK_LABEL__</div>
              <div id="stamp" class="ov">__STAMP__</div>
              __RINGS__
              <div id="parts" class="ov" style="left:0;top:0">__PARTS__</div>
              <div id="cursor"><svg width="66" height="66" viewBox="0 0 26 26" xmlns="http://www.w3.org/2000/svg"><path d="M4 2 L4 20.5 L9.1 15.9 L12.1 22.6 L15.4 21.1 L12.4 14.6 L19.3 14.3 Z" fill="#ffffff" stroke="#10271e" stroke-width="1.5" stroke-linejoin="round"/></svg></div>
            </div>
            <div class="sheen" id="sheen"></div>
          </div>
        </div>
      </div>
    </div>
    <div class="intro" id="intro">
      <div class="eb">__INTRO_EB__</div>
      <div class="wm">__WM__<span class="dot">__DOT__</span></div>
      <div class="tag">__ITAG__</div>
      <div class="chips">__ICHIPS__</div>
    </div>
    <div id="hud">
      <i class="corner c1"></i><i class="corner c2"></i><i class="corner c3"></i><i class="corner c4"></i>
      <div class="tl"><i class="rec" id="rec"></i><span>__REC_LABEL__</span></div>
      <div class="tr" id="tc">SRC 00:00.00</div>
      <div id="steps"><div id="pill"></div>__PILLS__</div>
    </div>
    __SLABS__
  </div>

  <div id="recap" class="layer">
    <div class="recap-bg"></div>
    <div class="recap-stage"><div class="recap-world" id="recap-world">__RECAP__</div></div>
    __RECAP_WORDS__
  </div>

  <section id="endcard" class="clip layer" data-start="__END_START__" data-duration="__END_DUR__" data-track-index="6">
    <div class="end-bg"></div>
    <div class="rays" id="rays" data-layout-ignore></div>
    <div id="motes">__MOTES__</div>
    <div class="end-inner">
      <div class="ewm" id="ewm" data-layout-allow-occlusion>__EWM__<span class="dot">__DOT__</span><div class="glint" id="glint" aria-hidden="true" data-layout-ignore>__GLINT__</div></div>
      <div class="etag">__ETAG__</div>
      <div class="url" id="url"><span id="url-text"></span><i id="caret"></i></div>
      <div class="echips">__ECHIPS__</div>
      <div class="limit">__LIMIT__</div>
    </div>
    <div class="efoot">__FOOT__</div>
  </section>

  <div id="flash" data-layout-ignore></div>
  <div id="grain" data-layout-ignore></div>
  <audio id="mix" src="assets/mix.wav" data-start="0" data-duration="__DUR__" data-track-index="100" data-volume="1"></audio>
</div>
<script>
const P = __PLAN__;
const tl = gsap.timeline({ paused: true });
const T = P.t, L = P.L, DUR = P.dur;
const B = (n) => P.beat0 + P.period * n;
const EZ = {};
const ez = (n) => EZ[n] || (EZ[n] = gsap.parseEase(n));
const prand = (n) => { const x = Math.sin(n * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); };
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const $ = (id) => document.getElementById(id);

// Keyframe channel: [[t, value, easeIntoThisKey], ...] -> value at time t (pure function of t).
function kf(keys, t) {
  if (t <= keys[0][0]) return keys[0][1];
  for (let i = 1; i < keys.length; i++) {
    const k = keys[i];
    if (t < k[0]) {
      const a = keys[i - 1];
      const p = (t - a[0]) / (k[0] - a[0]);
      return a[1] + (k[1] - a[1]) * ez(k[2] || "none")(p);
    }
  }
  return keys[keys.length - 1][1];
}
// Shots: [[start, duration, {cx,cy,s}, ease]] -> per-channel keyframes that hold between moves.
function shots(initial, list) {
  const ch = {};
  for (const k of Object.keys(initial)) ch[k] = [[0, initial[k]]];
  let cur = { ...initial };
  for (const [at, d, to, e] of list) {
    for (const k of Object.keys(to)) {
      ch[k].push([at, cur[k]]);
      ch[k].push([at + d, to[k], e]);
    }
    cur = { ...cur, ...to };
  }
  return ch;
}
// Three-phase whip (nudge curve): 10% ramp-in, 65% linear burst, 25% hard landing.
function whip(at, from, to) {
  const mid = (f) => {
    const o = {};
    for (const k of Object.keys(to)) o[k] = from[k] + (to[k] - from[k]) * f;
    return o;
  };
  return [[at, 0.12, mid(0.1), "power3.in"], [at + 0.12, 0.1, mid(0.75), "none"], [at + 0.22, 0.36, to, "power4.out"]];
}

// ---------------- camera plans ----------------
const WORLD = P.world;
const F = P.frames;  // named lens framings, source pixels
const LENS = shots(F.full, [
  [B(7) + 0.4, B(11) - B(7) - 0.4, F.revealPush, "sine.inOut"],
  [B(11), 0.95, F.editorWide, "power3.inOut"],
  [T.edClick + 0.08, 0.6, F.typeIn, "power3.out"],
  [T.type1[0], T.type1[1] - T.type1[0], F.typeOut, "sine.inOut"],
  ...whip(T.whip1, F.typeOut, F.save),
  [T.save + 0.16, 0.85, F.savedWide, "power3.inOut"],
  [T.save + 1.05, T.find - T.save - 1.3, F.savedDrift, "sine.inOut"],
  ...whip(T.find, F.savedDrift, F.search),
  [T.filtered + 0.06, 0.8, F.foundWide, "power3.inOut"],
  [T.track + 0.95, 0.9, F.foundClose, "power3.inOut"],
]);
const STORM = { z: [[0, -320], [B(7), 2150, "power2.in"]], ry: [[0, -10], [B(7), 8, "sine.inOut"]], rx: [[0, 5], [B(7), -3, "sine.inOut"]] };
const STAGE_BLUR = [[0, 0], [B(7) - 0.01, 0], [B(7), 16], [B(7) + 0.6, 0, "power4.out"], [B(11), 0], [B(11) + 0.45, 7, "power2.in"], [B(11) + 0.95, 0, "power3.out"]];
const WHIPS = [T.whip1, T.find];

// ---------------- per-frame procedural layer ----------------
const el = {
  storm: $("storm"), world: $("world"), lens: $("lens"), screen: $("screen"), stage: $("stage"),
  cursor: $("cursor"), tc: $("tc"), kg1: $("kg1"), kg2: $("kg2"), grain: $("grain"), urlText: $("url-text"),
  caret: $("caret"), rec: $("rec"), stageBlur: $("stageblur-n"), whipBlur: $("whip-n"), rgbR: $("rgb-r"), rgbB: $("rgb-b"),
};
const cards = P.storm.map((c, i) => ({ ...c, node: $("sc" + i) }));
const parts = P.parts.map((p, i) => ({ ...p, node: $("pt" + i) }));
const motes = P.motes.map((m, i) => ({ ...m, node: $("mo" + i) }));
const SW = P.screen[0], SH = P.screen[1], FX = P.focus[0], FY = P.focus[1];
const pad2 = (n) => String(n).padStart(2, "0");

function frame(t) {
  // Storm: a forward flight through drifting cards, depth of field from distance to the focal plane.
  if (t < B(7) + 0.3) {
    const z = kf(STORM.z, t), ry = kf(STORM.ry, t), rx = kf(STORM.rx, t);
    el.storm.style.transform = `translate3d(0px,0px,${z}px) rotateX(${rx}deg) rotateY(${ry}deg)`;
    for (const c of cards) {
      const ze = c.z + z;
      const near = ze > 420 ? clamp(1 - (ze - 420) / 260, 0, 1) : 1;
      const far = clamp((ze + 3300) / 900, 0, 1);
      const fadeOut = t > B(5.6) ? clamp(1 - (t - B(5.6)) / 0.5, 0, 1) : 1;
      const on = clamp((t - c.delay) / 0.35, 0, 1);
      c.node.style.opacity = String(near * far * on * fadeOut * c.alpha);
      c.node.style.filter = `blur(${clamp(Math.abs(ze + 160) / 120, 0, 13).toFixed(2)}px)`;
    }
  }
  // Hook text glitches: RGB split on quantized time, decaying.
  const glitchText = (node, at, len) => {
    if (t >= at && t < at + len) {
      const q = Math.floor(t * 30), a = 1 - (t - at) / len;
      const dx = (prand(q * 3.7) - 0.5) * 46 * a;
      node.style.textShadow = `${dx.toFixed(1)}px 0 rgba(255,72,112,.85), ${(-dx).toFixed(1)}px 0 rgba(84,222,255,.85)`;
      node.style.transform = `translate(${((prand(q * 5.3) - 0.5) * 34 * a).toFixed(1)}px,0px)`;
    } else { node.style.textShadow = "none"; node.style.transform = "none"; }
  };
  glitchText(el.kg1, B(2.6), 0.42);
  glitchText(el.kg2, B(3.1), 0.36);

  // World (window) pose + save shake, one writer.
  let sx = 0, sy = 0;
  const ds = t - T.save;
  if (ds >= 0 && ds < 0.6) {
    const a = 18 * Math.exp(-ds * 7);
    sx = a * Math.sin(ds * 2 * Math.PI * 17);
    sy = a * 0.7 * Math.sin(ds * 2 * Math.PI * 13 + 1.1);
  }
  el.world.style.transform = `translate3d(${(kf(WORLD.x, t) + sx).toFixed(2)}px,${(kf(WORLD.y, t) + sy).toFixed(2)}px,${kf(WORLD.z, t).toFixed(2)}px) rotateX(${kf(WORLD.rx, t).toFixed(3)}deg) rotateY(${kf(WORLD.ry, t).toFixed(3)}deg) rotateZ(${kf(WORLD.rz, t).toFixed(3)}deg)`;
  const sb = kf(STAGE_BLUR, t);
  el.stageBlur.setAttribute("stdDeviation", `${sb.toFixed(2)} ${sb.toFixed(2)}`);
  el.stage.style.filter = sb > 0.05 ? "url(#stageblur)" : "none";

  // Lens: a virtual camera over the 4K capture (never above native pixels).
  const s = kf(LENS.s, t), cx = kf(LENS.cx, t), cy = kf(LENS.cy, t);
  let jx = 0;
  const filters = [];
  for (const w of WHIPS) {
    const d = t - w;
    if (d >= 0 && d < 0.58) {
      const v = d < 0.12 ? 22 * ez("power3.in")(d / 0.12) : d < 0.22 ? 22 : 22 * (1 - ez("power4.out")((d - 0.22) / 0.36));
      if (v > 0.05) { el.whipBlur.setAttribute("stdDeviation", `${v.toFixed(2)} 0`); filters.push("url(#whip)"); }
    }
  }
  const dg = t - T.find;
  if (dg >= -0.06 && dg < 0.34) {
    const q = Math.floor(t * 30), a = 1 - clamp(dg, 0, 0.34) / 0.34;
    const dx = (10 + prand(q * 2.1) * 26) * a;
    el.rgbR.setAttribute("dx", dx.toFixed(1)); el.rgbB.setAttribute("dx", (-dx).toFixed(1));
    filters.unshift("url(#rgb)");
    jx = (prand(q * 9.1) - 0.5) * 60 * a;
  }
  el.screen.style.filter = filters.length ? filters.join(" ") : "none";
  el.lens.style.transform = `translate(${(SW * FX - s * cx + jx).toFixed(2)}px,${(SH * FY - s * cy).toFixed(2)}px) scale(${s.toFixed(4)})`;

  // Cursor drawn from the logged pointer path (input.jsonl), per film frame.
  const fi = clamp(Math.round(t * 30), 0, P.cur.length - 1);
  const c = P.cur[fi];
  el.cursor.style.opacity = String(c[2]);
  el.cursor.style.transform = `translate(${(c[0] - 10).toFixed(1)}px,${(c[1] - 5).toFixed(1)}px) scale(${c[3]})`;

  // HUD: live source timecode of whichever take range is on screen.
  let src = null;
  for (const g of P.seg) if (t >= g.f0 && t < g.f1) { src = g.s0 + (t - g.f0) * g.rate; break; }
  if (src !== null) el.tc.textContent = `SRC ${pad2(Math.floor(src / 60))}:${pad2(Math.floor(src % 60))}.${pad2(Math.floor((src % 1) * 100))}` + (P.tcRes ? "  ·  3840×2160" : "");
  el.rec.style.opacity = Math.floor(t * 2) % 2 === 0 ? "1" : "0.25";

  // Key-click burst: ballistic particles, a pure function of time since the click.
  const db = t - T.save;
  for (const p of parts) {
    if (db < 0 || db > 1.3) { p.node.style.opacity = "0"; continue; }
    const x = p.vx * db, y = p.vy * db + 0.5 * 2600 * db * db;
    p.node.style.opacity = String(clamp(1 - db / 1.3, 0, 1));
    p.node.style.transform = `translate(${x.toFixed(1)}px,${y.toFixed(1)}px) rotate(${(p.spin * db).toFixed(1)}deg)`;
  }

  // End card: rising motes, URL typewriter, blinking caret.
  const de = t - T.end;
  for (const m of motes) {
    if (de < 0) { m.node.style.opacity = "0"; continue; }
    const life = (de * m.speed + m.phase) % 1;
    const y = m.y0 - life * 900, x = m.x0 + Math.sin((de + m.phase * 6) * m.wob) * 30;
    m.node.style.opacity = String((Math.sin(life * Math.PI) * m.alpha).toFixed(3));
    m.node.style.transform = `translate(${x.toFixed(1)}px,${y.toFixed(1)}px)`;
  }
  const du = t - T.url;
  el.urlText.textContent = du < 0 ? "" : P.url.slice(0, clamp(Math.floor(du / 0.045) + 1, 0, P.url.length));
  el.caret.style.opacity = du < 0 ? "0" : (Math.floor(t * 2.2) % 2 === 0 ? "1" : "0");

  // Film grain on the dark scenes only; the product capture stays clean.
  const q2 = Math.floor(t * 15);
  el.grain.style.transform = `translate(${(prand(q2 * 1.7) * 200).toFixed(0)}px,${(prand(q2 * 2.9) * 200).toFixed(0)}px)`;
}

// ---------------- authored tweens ----------------
// HOOK
tl.fromTo("#hook-glow", { opacity: 0, scale: 0.8 }, { opacity: 1, scale: 1.15, duration: B(7), ease: "sine.inOut" }, 0);
tl.fromTo("#k1", { scale: 1.6, opacity: 0, filter: "blur(18px)" }, { scale: 1, opacity: 1, filter: "blur(0px)", duration: 0.5, ease: "power4.out" }, B(0));
tl.fromTo("#k2", { x: 460, opacity: 0, filter: "blur(10px)" }, { x: 0, opacity: 1, filter: "blur(0px)", duration: 0.42, ease: "expo.out" }, B(1));
tl.fromTo("#kg1", { opacity: 1 }, { opacity: 0, duration: 0.1, ease: "none", immediateRender: false }, B(3.1) - 0.1);
tl.fromTo("#k3", { opacity: 0, scale: 1.12 }, { opacity: 1, scale: 1, duration: 0.3, ease: "power4.out" }, B(3.1));
tl.fromTo("#k4", { y: 120, rotation: 5, opacity: 0 }, { y: 0, rotation: 0, opacity: 1, duration: 0.5, ease: "circ.out" }, B(3.9));
gsap.utils.toArray("#kg2 .ch").forEach((c, i) => {
  const a = prand(i * 3.1) * 2 - 1, b = prand(i * 7.7) * 2 - 1;
  tl.fromTo(c, { x: 0, y: 0, rotation: 0, opacity: 1, filter: "blur(0px)" },
    { x: a * P.kgExplode[0], y: -140 + b * P.kgExplode[1], rotation: a * 80, opacity: 0, filter: "blur(9px)", duration: 0.62, ease: "power2.in", immediateRender: false },
    B(4.8) + i * 0.011);
});
tl.fromTo("#hero", { scale: 0.34, y: 60, opacity: 0, filter: "blur(12px)" }, { scale: 0.64, y: 0, opacity: 1, filter: "blur(0px)", duration: 0.75, ease: "power3.out" }, B(5.2));
tl.fromTo("#hero", { scale: 0.64 }, { scale: 1, duration: 0.42, ease: "power2.inOut", immediateRender: false }, B(6));
tl.fromTo("#hero", { scale: 1, opacity: 1, filter: "blur(0px)" }, { scale: 5.2, opacity: 0, filter: "blur(16px)", duration: 0.3, ease: "power3.in", immediateRender: false }, B(7) - 0.3);

// FLASH + scene switches
const flash = (at, peak, out) => {
  tl.fromTo("#flash", { opacity: 0 }, { opacity: peak, duration: 0.06, ease: "none", immediateRender: false }, at - 0.06);
  tl.fromTo("#flash", { opacity: peak }, { opacity: 0, duration: out, ease: "power2.out", immediateRender: false }, at);
};
flash(B(7), 1, 0.5);
flash(T.save, 0.6, 0.32);
flash(T.end, 0.85, 0.5);
tl.set("#product", { opacity: 1 }, B(7) - 0.06);
tl.set("#product", { opacity: 0 }, T.recap);
tl.set("#recap", { opacity: 1 }, T.recap);
tl.set("#recap", { opacity: 0 }, T.end);
tl.set("#grain", { opacity: 0.07 }, 0);
tl.set("#grain", { opacity: 0 }, B(7) - 0.06);
tl.set("#grain", { opacity: 0.06 }, T.recap);

// REVEAL
tl.fromTo("#dots", { x: 0, y: 0 }, { x: -76, y: -38, duration: T.recap - B(7), ease: "none" }, B(7));
tl.fromTo("#blob1", { x: 0, y: 0, scale: 1 }, { x: -220, y: 90, scale: 1.12, duration: T.recap - B(7), ease: "sine.inOut" }, B(7));
tl.fromTo("#blob2", { x: 0, y: 0 }, { x: 260, y: -60, duration: T.recap - B(7), ease: "sine.inOut" }, B(7));
tl.fromTo("#sheen", { x: -900, opacity: 0 }, { x: SW + 700, opacity: 1, duration: 1.05, ease: "power2.inOut" }, B(8.6));
tl.fromTo("#intro .eb", { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 0.35, ease: "power2.out" }, B(7.5));
gsap.utils.toArray("#intro .wm .l").forEach((n, i) => {
  tl.fromTo(n, { rotationX: -95, y: 80, opacity: 0 }, { rotationX: 0, y: 0, opacity: 1, duration: 0.62, ease: "back.out(1.7)" }, B(8) + i * 0.06);
});
tl.fromTo("#intro .wm .dot", { y: -420, opacity: 0 }, { y: 0, opacity: 1, duration: 0.72, ease: "bounce.out" }, B(9));
tl.fromTo("#intro .tag span", { yPercent: 110 }, { yPercent: 0, duration: 0.52, stagger: 0.1, ease: "power4.out" }, B(9.5));
tl.fromTo("#intro .chips span", { scale: 0, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.42, stagger: 0.08, ease: "back.out(2.2)" }, B(10.1));
tl.fromTo("#intro", { x: 0, opacity: 1, filter: "blur(0px)" }, { x: -180, opacity: 0, filter: "blur(12px)", duration: 0.42, ease: "power2.in", immediateRender: false }, B(11) - 0.05);

// HUD + step indicator
tl.fromTo("#hud", { opacity: 0 }, { opacity: 1, duration: 0.4, ease: "power2.out" }, B(7.6));
tl.fromTo("#hud", { opacity: 1 }, { opacity: 0, duration: 0.2, ease: "none", immediateRender: false }, T.recap - 0.2);
const INK = getComputedStyle(document.documentElement).getPropertyValue("--ink").trim();
const LIME = getComputedStyle(document.documentElement).getPropertyValue("--lime").trim();
tl.fromTo("#pill", { opacity: 0, x: 0 }, { opacity: 1, x: 0, duration: 0.3, ease: "power2.out" }, B(11.5));
tl.fromTo("#st1", { color: INK }, { color: LIME, duration: 0.2, ease: "none" }, B(11.5));
tl.fromTo("#pill", { x: 0 }, { x: 204, duration: 0.5, ease: "expo.inOut", immediateRender: false }, T.save);
tl.fromTo("#st1", { color: LIME }, { color: INK, duration: 0.2, ease: "none", immediateRender: false }, T.save + 0.1);
tl.fromTo("#st2", { color: INK }, { color: LIME, duration: 0.2, ease: "none" }, T.save + 0.2);
tl.fromTo("#pill", { x: 204 }, { x: 408, duration: 0.5, ease: "expo.inOut", immediateRender: false }, T.find);
tl.fromTo("#st2", { color: LIME }, { color: INK, duration: 0.2, ease: "none", immediateRender: false }, T.find + 0.1);
tl.fromTo("#st3", { color: INK }, { color: LIME, duration: 0.2, ease: "none" }, T.find + 0.2);

// Slabs
const slabIn = (id, at) => {
  tl.fromTo(id, { opacity: 0, y: 0 }, { opacity: 1, y: 0, duration: 0.01, ease: "none" }, at);
  tl.fromTo(`${id} .bg`, { scaleX: 0 }, { scaleX: 1, duration: 0.4, ease: "expo.out" }, at);
  tl.fromTo(`${id} .eb`, { y: 16, opacity: 0 }, { y: 0, opacity: 1, duration: 0.3, ease: "power2.out" }, at + 0.12);
  tl.fromTo(`${id} h2`, { yPercent: 115 }, { yPercent: 0, duration: 0.5, ease: "power4.out" }, at + 0.1);
  tl.fromTo(`${id} p`, { y: 16, opacity: 0 }, { y: 0, opacity: 1, duration: 0.35, ease: "power2.out" }, at + 0.26);
};
const slabOut = (id, at) => tl.fromTo(id, { y: 0, opacity: 1 }, { y: 36, opacity: 0, duration: 0.26, ease: "power2.in", immediateRender: false }, at);
slabIn("#slab1", B(12)); slabOut("#slab1", T.whip1 - 0.3);
slabIn("#slab2", T.save + 0.75); slabOut("#slab2", T.find - 0.3);
slabIn("#slab3", T.find + 0.5); slabOut("#slab3", T.recap - 0.35);

// Clicks: two rings each, at the logged pointer position.
P.clicks.forEach((k, i) => {
  // immediateRender:false: the rings stay hidden (CSS opacity 0) until their click.
  tl.fromTo(`#rg${i}a`, { scale: 0.2, opacity: 0.95 }, { scale: 1.9, opacity: 0, duration: 0.55, ease: "power2.out", immediateRender: false }, k.t);
  tl.fromTo(`#rg${i}b`, { scale: 0.2, opacity: 0.8 }, { scale: 2.8, opacity: 0, duration: 0.75, ease: "power2.out", immediateRender: false }, k.t + 0.08);
});

// Act 1 annotation: a hand-drawn loop around the detail worth noticing, and a note.
if (P.annot) {
  const tagPath = $("tagc-path");
  tagPath.style.strokeDasharray = `${P.tagLen}`;
  // Hidden until it draws: a round line cap on an undrawn dash still paints a dot.
  tl.set("#tagc", { opacity: 1 }, T.tagDone + 0.1);
  tl.fromTo(tagPath, { strokeDashoffset: P.tagLen }, { strokeDashoffset: 0, duration: 0.5, ease: "power2.out" }, T.tagDone + 0.1);
  tl.fromTo("#tagnote", { scale: 0, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.4, ease: "back.out(2)" }, T.tagDone + 0.35);
  tl.fromTo("#tagc", { opacity: 1 }, { opacity: 0, duration: 0.2, ease: "none", immediateRender: false }, T.whip1 - 0.05);
  tl.fromTo("#tagnote", { opacity: 1 }, { opacity: 0, duration: 0.2, ease: "none", immediateRender: false }, T.whip1 - 0.05);
}

// Act 2, the key click: spotlight, lock-on, stamp, lifted result.
tl.fromTo("#spot", { opacity: 0 }, { opacity: 1, duration: 1.3, ease: "power1.in" }, T.save - 1.5);
tl.fromTo("#spot", { opacity: 1 }, { opacity: 0, duration: 0.3, ease: "power2.out", immediateRender: false }, T.save + 0.05);
tl.fromTo("#lock", { scale: 2.4, rotation: 45, opacity: 0 }, { scale: 1, rotation: 0, opacity: 1, duration: 0.5, ease: "power3.out" }, T.save - 0.9);
tl.fromTo("#lock", { scale: 1 }, { scale: 1.07, duration: 0.16, yoyo: true, repeat: 1, ease: "sine.inOut", immediateRender: false }, T.save - 0.36);
tl.fromTo("#lock", { scale: 1, opacity: 1 }, { scale: 1.75, opacity: 0, duration: 0.35, ease: "power2.out", immediateRender: false }, T.save + 0.02);
tl.fromTo("#locklabel", { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: 0.25, ease: "power2.out" }, T.save - 0.55);
tl.fromTo("#locklabel", { opacity: 1 }, { opacity: 0, duration: 0.12, ease: "none", immediateRender: false }, T.save);
tl.fromTo("#stamp", { scale: 0, rotation: -28, opacity: 0 }, { scale: 1, rotation: -7, opacity: 1, duration: 0.55, ease: "back.out(2.4)" }, T.save + 0.03);
tl.fromTo("#stamp", { scale: 1, opacity: 1 }, { scale: 0.85, opacity: 0, duration: 0.24, ease: "power2.in", immediateRender: false }, T.save + 1.15);
tl.fromTo("#lift", { scale: 1, y: 0, boxShadow: "0px 0px 0px rgba(0,0,0,0)" }, { scale: 1.05, y: -30, boxShadow: "0px 60px 110px rgba(0,0,0,.3)", duration: 0.55, ease: "back.out(1.6)" }, T.lift);
tl.fromTo("#liftglow", { scale: 1, y: 0, opacity: 0 }, { scale: 1.05, y: -30, opacity: 1, duration: 0.55, ease: "back.out(1.6)" }, T.lift);
tl.fromTo("#lift", { scale: 1.05, y: -30, boxShadow: "0px 60px 110px rgba(0,0,0,.3)" }, { scale: 1, y: 0, boxShadow: "0px 0px 0px rgba(0,0,0,0)", duration: 0.5, ease: "power3.inOut", immediateRender: false }, T.find - 0.7);
tl.fromTo("#liftglow", { scale: 1.05, y: -30, opacity: 1 }, { scale: 1, y: 0, opacity: 0, duration: 0.5, ease: "power3.inOut", immediateRender: false }, T.find - 0.7);

// Act 3, the payoff: scan, tracking box, marker.
tl.fromTo("#scan", { y: 0, opacity: 0 }, { y: L.scanTravel, opacity: 1, duration: 0.55, ease: "power2.inOut" }, T.filtered - 0.05);
tl.fromTo("#scan", { opacity: 1 }, { opacity: 0, duration: 0.15, ease: "none", immediateRender: false }, T.filtered + 0.5);
tl.fromTo("#track", { scale: 1.22, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.5, ease: "back.out(1.8)" }, T.track);
tl.fromTo("#tlabel", { scale: 0, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.4, ease: "back.out(2.2)" }, T.track + 0.18);
tl.fromTo("#marker", { scaleX: 0, opacity: 1 }, { scaleX: 1, opacity: 1, duration: 0.4, ease: "power2.out" }, T.track + 0.4);

// RECAP: three tilted beats, then the whole wall pushes back.
const RC = P.recap;
["#rc1", "#rc2", "#rc3"].forEach((id, i) => {
  tl.fromTo(id, { ...RC.enter[i], opacity: 0 }, { ...RC.rest[i], opacity: 1, duration: 0.5, ease: "expo.out" }, T.recap + i * P.period);
});
["#rl1", "#rl2", "#rl3"].forEach((id, i) => {
  tl.fromTo(id, { scale: 1.5, opacity: 0, filter: "blur(14px)" }, { scale: 1, opacity: 1, filter: "blur(0px)", duration: 0.36, ease: "power4.out" }, T.recap + i * P.period + 0.04);
  if (RC.word_shift) tl.fromTo(id, { y: 0 }, { y: RC.word_shift, duration: 0.45, ease: "power3.inOut", immediateRender: false }, T.recap + 3 * P.period);
});
tl.fromTo("#recap-world", { z: 0, rotationX: 0, scale: 1 }, { z: RC.push.z, rotationX: RC.push.rotationX, scale: 1, duration: 0.5, ease: "power2.inOut" }, T.recap + 3 * P.period);
tl.fromTo("#recap-world", { scale: 1, opacity: 1 }, { scale: 2.6, opacity: 0, duration: 0.3, ease: "power3.in", immediateRender: false }, T.end - 0.3);

// END
tl.fromTo("#rays", { rotation: 0 }, { rotation: 24, duration: DUR - T.end, ease: "none" }, T.end);
gsap.utils.toArray("#ewm .l").forEach((n, i) => {
  tl.fromTo(n, { rotationX: -100, y: 90, opacity: 0 }, { rotationX: 0, y: 0, opacity: 1, duration: 0.7, ease: "back.out(1.6)" }, T.end + 0.15 + i * 0.065);
});
tl.fromTo("#ewm .dot", { y: -520, opacity: 0 }, { y: 0, opacity: 1, duration: 0.8, ease: "bounce.out" }, T.end + 0.65);
tl.fromTo("#endcard .etag span", { yPercent: 115 }, { yPercent: 0, duration: 0.55, stagger: 0.14, ease: "power4.out" }, T.end + 1.0);
tl.fromTo("#url", { opacity: 0 }, { opacity: 1, duration: 0.15, ease: "none" }, T.url - 0.1);
tl.fromTo("#endcard .echips span", { scale: 0, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.42, stagger: 0.09, ease: "back.out(2.2)" }, T.url + 1.25);
tl.fromTo("#endcard .limit", { y: 16, opacity: 0 }, { y: 0, opacity: 1, duration: 0.45, ease: "power2.out" }, T.url + 1.75);
tl.fromTo("#glint", { backgroundPosition: "100% 0%" }, { backgroundPosition: "0% 0%", duration: 1.0, ease: "power2.inOut" }, T.shine);
tl.fromTo("#endcard .efoot", { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: 0.5, ease: "power2.out" }, T.shine + 0.3);

// The clock: every procedural channel above is a pure function of this value.
const clock = { t: 0 };
tl.fromTo(clock, { t: 0 }, { t: DUR, duration: DUR, ease: "none", onUpdate: () => frame(clock.t) }, 0);
frame(0);
window.__timelines["__COMP_ID__"] = tl;
</script>
</body></html>
