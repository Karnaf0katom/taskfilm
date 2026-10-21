/* Original Taskfilm artwork. Every frame is a function of time and config. */
(() => {
  'use strict';
  const cfg = window.TASKFILM_STUDY;
  const canvas = document.getElementById('art');
  const ctx = canvas.getContext('2d', {willReadFrequently: true});
  const W = cfg.width, H = cfg.height, U = Math.min(W, H) / 1080;
  const portrait = H > W, C = cfg.palette, TAU = Math.PI * 2;
  const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
  const mix = (a, b, p) => a + (b - a) * p;
  const land = p => 1 - (1 - clamp(p)) ** 4;
  const leave = p => clamp(p) ** 3;
  const smooth = p => (p = clamp(p), p * p * (3 - 2 * p));
  const progress = (t, at, length = .4) => clamp((t - at) / length);
  const hash = n => { let x = (n + cfg.seed) | 0; x = Math.imul(x ^ (x >>> 16), 0x45d9f3b); x = Math.imul(x ^ (x >>> 16), 0x45d9f3b); return ((x ^ (x >>> 16)) >>> 0) / 4294967296; };
  const noise = document.createElement('canvas'); noise.width = noise.height = 128;
  const nc = noise.getContext('2d'), pixels = nc.createImageData(128, 128);
  for (let i = 0; i < pixels.data.length; i += 4) { const v = hash(i) > .5 ? 255 : 0; pixels.data.set([v, v, v, 11], i); }
  nc.putImageData(pixels, 0, 0);
  const grain = ctx.createPattern(noise, 'repeat');
  let textBoxes = [], lastTime = 0;

  function font(size, weight = 800) { ctx.font = `${weight} ${size}px Manrope, sans-serif`; }
  function fitted(value, size, maxWidth) {
    font(size);
    return Math.min(size, size * maxWidth / Math.max(1, ctx.measureText(value).width));
  }
  function words(value, maxWidth, size) {
    font(size); const lines = [''];
    for (const word of value.split(/\s+/)) {
      const next = lines[lines.length - 1] ? `${lines[lines.length - 1]} ${word}` : word;
      if (ctx.measureText(next).width > maxWidth && lines[lines.length - 1]) lines.push(word);
      else lines[lines.length - 1] = next;
    }
    return lines;
  }
  function label(value, x, y, size, color = C.ink, maxWidth = W * .86, weight = 800) {
    const s = fitted(value, size, maxWidth); font(s, weight);
    ctx.fillStyle = color; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(value, x, y);
    textBoxes.push({text: value, x, y, size: s, width: ctx.measureText(value).width});
  }
  function lines(values, y, size, color = C.ink, spacing = 1.06) {
    const s = Math.min(...values.map(value => fitted(value, size, W * .84)));
    values.forEach((value, i) => label(value, W / 2, y + (i - (values.length - 1) / 2) * s * spacing, s, color));
  }
  function dot(x, y, r, color) { ctx.beginPath(); ctx.arc(x, y, Math.max(.001, r), 0, TAU); ctx.fillStyle = color; ctx.fill(); }
  function rounded(x, y, w, h, r) { ctx.beginPath(); ctx.roundRect(x, y, w, h, r); }
  function ground(dark, t) {
    ctx.fillStyle = dark ? C.ink : C.paper; ctx.fillRect(0, 0, W, H);
    const x = W * (.50 + .12 * Math.sin(t * .21)), y = H * (.43 + .07 * Math.cos(t * .31));
    const glow = ctx.createRadialGradient(x, y, 0, x, y, Math.max(W, H) * .72);
    glow.addColorStop(0, dark ? '#46615e' : '#ffffff');
    glow.addColorStop(1, dark ? C.ink : C.paper);
    ctx.globalAlpha = .42; ctx.fillStyle = glow; ctx.fillRect(0, 0, W, H); ctx.globalAlpha = 1;
  }
  function finish() { ctx.save(); ctx.fillStyle = grain; ctx.fillRect(0, 0, W, H); ctx.restore(); }
  function sphere(x, y, r, color, alpha = 1) {
    ctx.save(); ctx.globalAlpha = alpha;
    const fill = ctx.createRadialGradient(x - r * .35, y - r * .44, r * .03, x + r * .15, y + r * .12, r * 1.08);
    fill.addColorStop(0, '#fff9e7'); fill.addColorStop(.24, color); fill.addColorStop(1, C.ink);
    ctx.shadowColor = '#030b0c66'; ctx.shadowBlur = r * .3; ctx.shadowOffsetY = r * .22;
    dot(x, y, r, fill); ctx.restore();
  }
  function signature(t, start) {
    ground(false, start); const p = land(progress(t, start, .6));
    const scale = mix(1.50, 1, p), y = H * .47;
    ctx.save(); ctx.translate(W / 2, y); ctx.scale(scale, scale);
    label(cfg.brand, 0, 0, 260 * U, C.ink, W * .80); ctx.restore();
    const tag = words(cfg.tagline, W * .84, Math.max(54 * U, H * .044));
    ctx.save(); ctx.translate(0, (1 - land(progress(t, start + .16, .38))) * 64 * U);
    lines(tag, y + Math.max(170 * U, H * .115), Math.max(54 * U, H * .044), C.ink, 1.15); ctx.restore();
    ctx.save(); ctx.globalAlpha = .16;
    dot(W * .78, H * .25, 170 * U, C.accent); dot(W * .19, H * .78, 84 * U, C.accent); ctx.restore();
  }

  function typography(t, condensed = false) {
    if (t < 2.6) {
      ground(false, t);
      const raw = cfg.headline.split(/\s+/);
      const values = raw.length <= 3 ? raw : words(cfg.headline, W * .76, 166 * U);
      const size = Math.min(portrait ? 204 : 218, 530 / values.length) * U;
      const spacing = size * 1.13;
      values.forEach((value, i) => {
        const p = land(progress(t, i * .13, .43));
        const z = mix(1.7, 1, p), direction = i % 2 ? -1 : 1;
        const y = H * .49 + (i - (values.length - 1) / 2) * spacing;
        ctx.save(); ctx.beginPath(); ctx.rect(0, y - spacing * .51, W, spacing); ctx.clip();
        ctx.translate(W / 2 + direction * (1 - p) * W * .64, y + (1 - p) * spacing * .95);
        ctx.rotate(direction * (1 - p) * .15); ctx.scale(z, z);
        label(value, 0, 0, size, i === values.length - 1 ? C.accent : C.ink, W * .78); ctx.restore();
      });
      ctx.beginPath(); ctx.moveTo(W * .16, H * .82);
      ctx.lineTo(W * (.16 + .68 * clamp(t / 2.6)), H * .82);
      ctx.strokeStyle = C.accent; ctx.lineWidth = 20 * U; ctx.lineCap = 'round'; ctx.stroke(); ctx.lineCap = 'butt';
      // A broad travelling stroke gives the lockup momentum into the cut.
      const p = leave(progress(t, 2.16, .44));
      ctx.save(); ctx.translate(W * p, 0); ctx.fillStyle = C.ink; ctx.fillRect(-W, H * .85, W * .92, 14 * U); ctx.restore();
    } else if (t < 6.8) {
      ground(true, t); const s = t - 2.6;
      const value = cfg.headline.split(/\s+/).slice(-1)[0];
      const turn = Math.sin(s * .85) * .09;
      ctx.save(); ctx.translate(W / 2, H * .49); ctx.rotate(turn);
      const size = fitted(value, 470 * U, W * .80);
      font(size); ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      for (let i = 12; i >= 1; i--) {
        ctx.fillStyle = i % 2 ? C.accent : '#682c22';
        ctx.fillText(value, i * 3.8 * U * Math.cos(s), i * 4.8 * U);
      }
      ctx.fillStyle = C.paper; ctx.fillText(value, 0, 0); ctx.restore();
      ctx.save(); ctx.strokeStyle = C.accent; ctx.lineWidth = 13 * U;
      const r = 185 * U + s * 42 * U;
      ctx.beginPath(); ctx.ellipse(W / 2, H * .49, r * 2, r, -.12 + s * .12, 0, TAU); ctx.stroke(); ctx.restore();
      const shift = leave(progress(t, 6.4, .4));
      ctx.fillStyle = C.paper; ctx.fillRect(-W + shift * W * 2, 0, W, H);
    } else {
      ground(false, t); const s = t - 6.8;
      for (let i = 0; i < 7; i++) {
        const h = H / 7, p = land(progress(s, i * .04, .46));
        ctx.fillStyle = i % 2 ? C.ink : C.accent;
        ctx.fillRect(mix(-W * 1.2, W * .90, p) + Math.sin(s * 1.2 + i) * 36 * U, i * h, W, h * .42);
      }
      const p = land(progress(s, .22, .45)); ctx.save(); ctx.translate(0, (1 - p) * H * .36);
      lines(['One idea.', 'Every frame.'], H * .46, portrait ? 162 * U : 184 * U); ctx.restore();
      const r = (86 + 18 * Math.sin(s * 2)) * U;
      dot(W / 2 + Math.sin(s * 1.4) * W * .24, H * .77, r, C.accent);
    }
  }

  function orbit(t, condensed = false) {
    ground(true, t); const s = t;
    const gather = smooth(progress(s, 5.7, 2.7));
    const radius = mix(portrait ? 360 : 470, 180, gather) * U;
    const cx = W / 2, cy = H * (portrait ? .54 : .55);
    const tilt = .42 + .15 * Math.sin(s * .34), spin = s * .53;
    const camera = 1 + .07 * Math.sin(s * .55);
    ctx.save(); ctx.translate(cx, cy); ctx.scale(camera, camera);
    const nodes = [];
    for (let ring = 0; ring < 3; ring++) {
      ctx.beginPath();
      for (let j = 0; j <= 120; j++) {
        const a = j / 120 * TAU, x = Math.cos(a) * radius * (1 + ring * .18);
        const z = Math.sin(a) * radius, y = Math.sin(a) * radius * tilt;
        const angle = -.45 + ring * .40 + .15 * Math.sin(s * .3);
        const qx = x * Math.cos(angle) - y * Math.sin(angle), qy = x * Math.sin(angle) + y * Math.cos(angle);
        const scale = 850 * U / (850 * U + z);
        if (!j) ctx.moveTo(qx * scale, qy * scale); else ctx.lineTo(qx * scale, qy * scale);
      }
      ctx.strokeStyle = ring === 1 ? C.accent : '#86a19b'; ctx.globalAlpha = ring === 1 ? .75 : .32;
      ctx.lineWidth = (ring === 1 ? 4.5 : 2) * U; ctx.stroke(); ctx.globalAlpha = 1;
      for (let j = 0; j < 3; j++) {
        const a = spin * (ring % 2 ? -.7 : 1) + j / 3 * TAU + ring;
        const z = Math.sin(a) * radius, x = Math.cos(a) * radius * (1 + ring * .18);
        const y = Math.sin(a) * radius * tilt;
        const angle = -.45 + ring * .40 + .15 * Math.sin(s * .3), scale = 850 * U / (850 * U + z);
        nodes.push({x: (x * Math.cos(angle) - y * Math.sin(angle)) * scale,
          y: (x * Math.sin(angle) + y * Math.cos(angle)) * scale, z, r: (ring === 1 ? 28 : 16) * U * scale,
          color: ring === 1 ? C.accent : C.paper});
      }
    }
    nodes.push({x: 0, y: 0, z: 0, r: (75 + 5 * Math.sin(s * 2.4)) * U, color: C.accent});
    nodes.sort((a, b) => b.z - a.z).forEach(node => sphere(node.x, node.y, node.r, node.color));
    ctx.restore();
    if (t < 2.6) {
      ctx.save(); ctx.translate(0, (1 - land(progress(t, .08, .4))) * -120 * U);
      lines(['Start with', 'an idea.'], H * (portrait ? .25 : .20), 87 * U, C.paper); ctx.restore();
    } else if (t >= 6.8) {
      const values = words(cfg.headline, W * .84, 128 * U);
      lines(values, H * (portrait ? .27 : .19), 128 * U, C.paper);
      const p = leave(progress(t, 9.6, .4));
      if (p > 0) dot(W / 2, cy, mix(45 * U, Math.hypot(W, H), p), C.paper);
    }
  }

  function ribbons(t) {
    ground(false, t);
    ctx.save(); ctx.strokeStyle = C.accent; ctx.lineWidth = 3.8 * U;
    for (let line = 0; line < 32; line++) {
      ctx.beginPath();
      for (let j = 0; j <= 100; j++) {
        const x = j / 100 * W, envelope = Math.sin(j / 100 * Math.PI);
        const y = H * .52 + (line - 16) * 12 * U + Math.sin(j * .054 + t * 1.4 + line * .11) * envelope * 170 * U;
        if (!j) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.globalAlpha = .35 + line / 64; ctx.stroke();
    }
    ctx.restore();
    const values = words(cfg.headline, W * .8, 154 * U);
    ctx.save(); ctx.translate(0, mix(-H * .20, 0, land(progress(t, .1, .42))));
    lines(values, H * .25, 154 * U); ctx.restore();
  }
  function knot(t) {
    ground(true, t); const cy = H * (portrait ? .58 : .59), r = (portrait ? 290 : 300) * U;
    ctx.save(); ctx.translate(W / 2, cy); ctx.rotate(t * .10);
    for (let line = 0; line < 54; line++) {
      const offset = line / 54 * TAU; ctx.beginPath();
      for (let j = 0; j <= 120; j++) {
        const a = j / 120 * TAU;
        const radius = r * (.76 + .26 * Math.sin(3 * a + t * .8 + offset));
        const x = radius * Math.cos(2 * a + offset * .17), z = radius * Math.sin(2 * a + offset * .17);
        const y = r * .70 * Math.sin(3 * a + offset + t * .5);
        const perspective = 1100 * U / (1100 * U + z);
        if (!j) ctx.moveTo(x * perspective, y * perspective); else ctx.lineTo(x * perspective, y * perspective);
      }
      ctx.strokeStyle = line % 9 === 0 ? C.paper : C.accent;
      ctx.lineWidth = (line % 9 === 0 ? 2.8 : 1.8) * U; ctx.globalAlpha = line % 9 === 0 ? .9 : .47; ctx.stroke();
    }
    ctx.restore();
    lines(['Find a different', 'rhythm.'], H * (portrait ? .25 : .17), 82 * U, C.paper);
  }
  function signal(t, condensed = false) {
    if (t < 2.6) ribbons(t);
    else if (t < 6.8) knot(t - 2.6);
    else {
      ground(false, t); const s = t - 6.8;
      ctx.save(); ctx.translate(W / 2, H * .59); ctx.rotate(s * .18);
      for (let i = 0; i < 20; i++) {
        ctx.beginPath(); ctx.ellipse(0, 0, (170 + i * 11) * U, (110 + i * 6) * U, Math.sin(s * .8) * .6, 0, TAU);
        ctx.strokeStyle = C.accent; ctx.lineWidth = 2.7 * U; ctx.globalAlpha = .60; ctx.stroke();
      }
      ctx.restore();
      lines(['One idea.', 'Many directions.'], H * .24, 106 * U);
      const p = leave(progress(t, 9.6, .4));
      if (p > 0) dot(W / 2, H * .59, mix(40 * U, Math.hypot(W, H), p), C.paper);
    }
  }

  function draw(seconds) {
    const endStart = cfg.duration - 2, holdStart = cfg.duration - 1;
    const t = clamp(Number(seconds) || 0, 0, holdStart); lastTime = t; textBoxes = [];
    ctx.resetTransform(); ctx.globalAlpha = 1; ctx.clearRect(0, 0, W, H);
    let scene;
    if (t >= endStart) { signature(t, endStart); scene = 'signature'; }
    else if (cfg.treatment === 'showreel') {
      if (t < 5.4) { typography(t); scene = 'type-sculpture'; }
      else if (t < 10.8) { orbit((t - 5.4) * 1.20); scene = 'orbit-story'; }
      else { knot((t - 10.8) * 1.08); scene = 'signal-field'; }
    } else {
      if (cfg.treatment === 'type-sculpture') typography(t);
      else if (cfg.treatment === 'orbit-story') orbit(t);
      else signal(t);
      scene = t < 2.6 ? 'opening' : t < 6.8 ? 'development' : 'resolution';
    }
    finish();
    return {time: t, scene, text: textBoxes, hold: seconds >= holdStart};
  }
  window.TaskfilmMotion = Object.freeze({draw, config: cfg,
    inspect: () => ({time: lastTime, text: textBoxes}),
    frameHash: () => {
      const bytes = ctx.getImageData(0, 0, W, H).data;
      let n = 2166136261; for (let i = 0; i < bytes.length; i++) n = Math.imul(n ^ bytes[i], 16777619);
      return (n >>> 0).toString(16).padStart(8, '0');
    }});
  draw(0);
})();
