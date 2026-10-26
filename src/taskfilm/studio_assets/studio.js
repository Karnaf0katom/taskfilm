'use strict';

(() => {
  const $ = (selector, parent = document) => parent.querySelector(selector);
  const projectPrefix = location.pathname.match(/^\/projects\/[a-zA-Z0-9_-]+/)?.[0] || '';
  const STAGES = ['brief', 'capture', 'storyboard', 'audio', 'composition', 'render', 'publish'];
  const TITLES = {brief: 'Start with the story.', capture: 'Show the real product.', storyboard: 'Make every scene count.', audio: 'Give your story a voice.', composition: 'Bring the pieces together.', render: 'Your film, ready to watch.', publish: 'Ready for every destination.'};
  const DESCRIPTIONS = {brief: 'Set the direction. Every stage keeps a complete, downloadable version of your project.', capture: 'The original source stays with your project. Adjust individual shots in Storyboard, then continue from there.', storyboard: 'Edit one scene, save a version, and rebuild from the stage that changed.', audio: 'Keep spoken narration separate from the words on screen. Adjust your script, timing, and music mix here.', composition: 'Build the editable motion composition from your saved scenes and brand. Render it to watch the finished film.', render: 'Render the current composition into a finished video. Earlier versions remain available.', publish: 'Prepare the delivery package for Instagram, Facebook, and YouTube. Live publishing requires account reconnection.'};
  const RUN_LABELS = {brief: 'Save brief checkpoint', capture: 'Verify source', storyboard: 'Validate storyboard', audio: 'Build audio', composition: 'Build composition', render: 'Render film', publish: 'Prepare publishing'};
  let state, draft, activeStage = 'storyboard', selectedScene = 0, dirty = false, busy = false, historical = false, timer, toastTimer, conflict = false;
  let pendingSceneSeek = null;
  const clone = value => structuredClone(value);
  const title = value => String(value || '').replace(/(^|[-_ ])\w/g, part => part.replace(/[-_]/g, ' ').toUpperCase());
  const el = (tag, attrs = {}, ...children) => {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (key === 'class') node.className = value;
      else if (key.startsWith('on')) node.addEventListener(key.slice(2).toLowerCase(), value);
      else if (key === 'text') node.textContent = value;
      else if (value !== undefined && value !== null && value !== false) node.setAttribute(key, value === true ? '' : String(value));
    }
    children.flat(Infinity).forEach(child => { if (child !== undefined && child !== null && child !== false) node.append(child instanceof Node ? child : document.createTextNode(String(child))); });
    return node;
  };
  const button = (text, onClick, kind = '', attrs = {}) => el('button', {type: 'button', class: `button ${kind}`, onClick, ...attrs}, text);
  const stageInfo = id => (state.stages || []).find(stage => stage.id === id) || {id, status: 'missing'};
  const revisionId = () => state.revision.id;
  const fileURL = path => `${projectPrefix}/files/${encodeURIComponent(revisionId())}/${String(path).split('/').map(encodeURIComponent).join('/')}`;
  const safeURL = url => { try { const parsed = new URL(url, location.origin); return ['http:', 'https:'].includes(parsed.protocol) ? parsed.href : ''; } catch { return ''; } };
  const fileLink = file => safeURL(file.url || fileURL(file.path));
  const file = path => (state.files || []).find(item => item.path === path);
  const exportURL = id => `${projectPrefix}/api/export/${encodeURIComponent(id)}.zip`;
  const size = bytes => bytes >= 1e6 ? `${(bytes / 1e6).toFixed(1)} MB` : bytes >= 1024 ? `${Math.round(bytes / 1024)} KB` : `${bytes || 0} B`;
  const clock = seconds => `${Math.floor((seconds || 0) / 60)}:${String(Math.floor((seconds || 0) % 60)).padStart(2, '0')}`;
  const duration = () => (draft.ad?.scenes || []).reduce((sum, scene) => sum + Number(scene.duration || 0), 0);
  const running = () => (state.jobs || []).some(job => job.status === 'running' || job.status === 'queued');
  const date = value => { const parsed = new Date(value); return Number.isNaN(parsed.valueOf()) ? String(value || '') : parsed.toLocaleString(undefined, {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'}); };

  async function api(path, body) {
    const response = await fetch(projectPrefix + path, body === undefined ? {cache: 'no-store'} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    let result;
    try { result = await response.json(); } catch { throw new Error(`The studio returned an unreadable response (${response.status}).`); }
    if (!response.ok) {
      if (response.status === 409) conflict = true;
      throw new Error(typeof result.error === 'string' ? result.error : result.message || `Request failed (${response.status}).`);
    }
    return result;
  }
  function toast(message) {
    const node = $('#toast'); node.textContent = message; node.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { node.hidden = true; }, 6500);
  }
  function setState(next, reset = true) {
    state = next;
    if (reset) { draft = {ad: clone(state.ad), audio: clone(state.audio), project: clone(state.project)}; dirty = false; conflict = false; }
    selectedScene = Math.min(selectedScene, Math.max(0, (draft.ad?.scenes?.length || 1) - 1));
    render(); schedulePoll();
  }
  function markDirty() {
    dirty = true;
    const status = $('#save-status'); if (status) { status.textContent = 'Unsaved changes'; status.classList.add('dirty'); }
    const save = $('#save-button'); if (save) save.disabled = historical || busy || running();
    const total = $('#duration-total'); if (total) total.textContent = `${duration().toFixed(1)} seconds`;
    const stale = $('#preview-dirty'); if (stale) stale.hidden = false;
    updateSceneCards();
  }
  function inputField(label, value, change, options = {}) {
    const {type = 'text', help, textarea, select, ...attrs} = options;
    let control;
    const onInput = event => { change(type === 'number' || type === 'range' ? (event.target.value === '' ? null : Number(event.target.value)) : event.target.value); markDirty(); };
    if (select) control = el('select', {disabled: historical || busy || running(), onChange: onInput, ...attrs}, select.map(option => el('option', {value: typeof option === 'string' ? option : option.value}, typeof option === 'string' ? title(option) : option.label)));
    else control = el(textarea ? 'textarea' : 'input', {type: textarea ? undefined : type, disabled: historical || busy || running(), onInput, ...attrs});
    control.value = value ?? '';
    return el('label', {class: 'field'}, el('span', {class: 'field-label'}, label), control, help && el('span', {class: 'help'}, help));
  }
  function pill(status, text) { return el('span', {class: `pill ${status}`}, text || ({ready: 'Ready', stale: 'Needs update', missing: 'Not built'}[status] || title(status))); }
  function download(id, text = 'Download full version', kind = '') { return el('a', {class: `button ${kind}`, href: exportURL(id), download: ''}, '↓ ', text); }
  function changeStage(id) { activeStage = id; render(); }

  const previewScenes = () => state.preview?.scenes || [];
  function updateSceneCards() {
    document.querySelectorAll('.scene-card').forEach((card, index) => {
      const active = index === selectedScene, scene = draft.ad.scenes[index];
      card.classList.toggle('active', active);
      card.setAttribute('aria-pressed', String(active));
      if (active) card.setAttribute('aria-current', 'true'); else card.removeAttribute('aria-current');
      if (scene) {
        $('strong', card).textContent = scene.headline;
        $('span', card).textContent = `${scene.duration}s`;
        card.setAttribute('aria-label', `Scene ${index + 1}: ${scene.headline}`);
      }
    });
  }
  function refreshSceneDetails(force = false) {
    const details = $('#scene-details');
    if (!details || (!force && (details.contains(document.activeElement) || details.dataset.sceneIndex === String(selectedScene)))) return;
    details.dataset.sceneIndex = selectedScene;
    details.replaceChildren();
    sceneDetails(details);
  }
  function selectScene(index, seek = false) {
    selectedScene = index;
    updateSceneCards();
    refreshSceneDetails(seek);
    const video = $('#film-video');
    if (!video) {
      const headline = $('.preview-empty h3');
      if (headline) headline.textContent = draft.ad.scenes[index]?.headline || 'Your story starts here.';
      return;
    }
    if (seek) {
      const scene = previewScenes().find(item => item.id === draft.ad.scenes[index]?.id);
      if (!scene) { toast('This scene is not in the saved preview yet. Render your changes to preview it.'); return; }
      pendingSceneSeek = scene.start;
      applySceneSeek(video);
    }
  }
  function applySceneSeek(video) {
    if (pendingSceneSeek === null || !video.readyState) return;
    video.currentTime = pendingSceneSeek;
    pendingSceneSeek = null;
  }
  function syncSceneFromPreview(video, time = video.currentTime) {
    if (video !== $('#film-video') || pendingSceneSeek !== null) return;
    const scenes = previewScenes();
    const scene = scenes.find(item => time < item.end - 1e-6) || scenes.at(-1);
    const index = scene ? draft.ad.scenes.findIndex(item => item.id === scene.id) : -1;
    if (index >= 0 && index !== selectedScene) selectScene(index);
  }
  function watchPreview(video) {
    const sync = () => syncSceneFromPreview(video);
    video.addEventListener('loadedmetadata', () => { applySceneSeek(video); sync(); });
    ['timeupdate', 'seeking', 'seeked', 'ended'].forEach(event => video.addEventListener(event, sync));
    // Decode-time callbacks keep the highlight aligned with the displayed frame.
    if (video.requestVideoFrameCallback) {
      let callback;
      const frame = (_, metadata) => {
        callback = undefined;
        if (video !== $('#film-video')) return;
        syncSceneFromPreview(video, metadata.mediaTime);
        if (!video.paused && !video.ended) callback = video.requestVideoFrameCallback(frame);
      };
      video.addEventListener('play', () => { if (callback === undefined) callback = video.requestVideoFrameCallback(frame); });
      video.addEventListener('pause', () => { if (callback !== undefined) video.cancelVideoFrameCallback(callback); callback = undefined; });
    }
  }

  function render() {
    const app = $('#app');
    const top = el('header', {class: 'topbar'}, el(projectPrefix ? 'a' : 'div', {class: `brand ${projectPrefix ? 'back-brand' : ''}`, href: projectPrefix ? '/' : undefined, 'aria-label': projectPrefix ? 'Back to projects' : undefined}, el('span', {class: 'brand-mark', 'aria-hidden': 'true'}, 't'), 'taskfilm', el('small', {}, 'STUDIO')),
      el('div', {class: 'header-actions'}, el('span', {class: `save-status ${dirty ? 'dirty' : ''}`, id: 'save-status', role: 'status'}, historical ? 'Viewing saved version' : dirty ? 'Unsaved changes' : 'All changes saved'),
        projectPrefix && el('a', {class: 'button quiet', href: '/', 'aria-label': 'Back to projects'}, '← Projects'),
        button('↺ Versions', showVersions), download(revisionId(), 'Full project', 'download-header'),
        button(busy ? 'Working…' : 'Save version', () => save(), 'primary', {id: 'save-button', disabled: historical || busy || running() || !dirty})));
    const nav = el('nav', {class: 'stage-list', 'aria-label': 'Production stages'}, STAGES.map((id, i) => {
      const stage = stageInfo(id);
      return el('button', {class: `stage-button ${activeStage === id ? 'active' : ''} ${stage.status}`, type: 'button', 'aria-current': activeStage === id ? 'step' : undefined, onClick: () => changeStage(id)},
        el('span', {class: 'stage-number', 'aria-hidden': 'true'}, stage.status === 'ready' ? '✓' : String(i + 1).padStart(2, '0')),
        el('span', {class: 'stage-text'}, el('span', {class: 'stage-name'}, title(id)), el('span', {class: 'stage-state'}, stage.status === 'ready' ? 'Complete' : stage.status === 'stale' ? 'Needs update' : 'Not built')));
    }));
    const sidebar = el('aside', {class: 'sidebar'}, el('div', {}, el('div', {class: 'eyebrow'}, 'Your workflow'), nav), el('div', {class: 'side-note'}, el('h3', {}, 'Every step, saved.'), el('p', {}, 'Go back to any complete version. Change one thing. Keep moving forward.')));
    const main = el('main', {class: 'workspace', id: 'workspace'},
      el('div', {class: 'project-heading'}, el('div', {}, el('p', {class: 'eyebrow'}, 'Your film workspace'), el('h1', {}, draft.project?.name || draft.ad?.brand?.name || 'Untitled project'), el('p', {class: 'project-description'}, `${draft.ad?.scenes?.length || 0} scenes · ${duration().toFixed(1)} seconds · English · Instagram, Facebook & YouTube`)), pill('ready', 'Local project')));
    if (historical) main.append(el('div', {class: 'note warning historical-banner'}, el('span', {}, `Viewing “${state.revision.label || revisionId()}” · ${date(state.revision.created_at)}. This version is read-only.`), el('div', {class: 'button-row'}, button('Back to latest', () => loadLatest()), button('Restore version', () => restore(revisionId()), 'coral', {disabled: busy}))));
    if (state.files.some(item => item.path === 'legacy-spec.json')) main.append(el('div', {class: 'note'}, 'Imported film. Your original movie, composition and source capture are saved in this project. Rebuilding an edited scene uses the current Studio layouts.'));
    if (conflict) main.append(el('div', {class: 'note error'}, 'The project changed in another session. Your edits are still here. Download your edits before loading the latest version.', el('div', {class: 'button-row'}, button('Download my edits', downloadDraft), button('Load latest', () => loadLatest(true)))));
    const jobs = el('div', {id: 'jobs'}); renderJobs(jobs); main.append(jobs);
    main.append(el('div', {class: 'studio-grid'}, renderPreview(), renderEditor()), el('footer', {class: 'bottom-note'}, el('span', {}, 'Complete files at every stage. Your originals stay with your project.'), el('span', {}, `Saved ${date(state.revision.created_at)}`)));
    app.replaceChildren(top, el('div', {class: 'shell'}, sidebar, main));
  }
  function renderJobs(container) {
    const jobs = (state.jobs || []).slice(-3).reverse();
    container.replaceChildren(...jobs.map(job => el('div', {class: `job ${job.status}`, role: 'status'}, el('strong', {}, ['running', 'queued'].includes(job.status) && el('span', {class: 'spinner', 'aria-hidden': 'true'}), `${title(job.stage)} · ${title(job.status)}`), el('p', {}, job.message || ''), button('Read job log ↗', () => showLog(job), 'quiet'))));
  }
  function renderPreview() {
    const panel = el('section', {class: 'preview-panel', 'aria-label': 'Film preview'});
    panel.append(el('div', {class: 'panel-heading'}, el('h2', {}, 'The preview'), pill(state.preview?.stale ? 'stale' : 'ready', state.preview?.stale ? 'Earlier render' : 'Saved film')));
    const fmt = state.preview?.format || draft.ad?.format || 'portrait';
    const surface = el('div', {class: `preview-surface ${fmt}`});
    const previewUrl = state.preview?.url ? safeURL(state.preview.url) : '';
    let video;
    if (previewUrl) {
      pendingSceneSeek = null;
      video = el('video', {src: previewUrl, poster: state.preview?.poster ? safeURL(state.preview.poster) : undefined, playsinline: '', preload: 'metadata', 'aria-label': 'Rendered film', id: 'film-video'}); surface.append(video);
      video.addEventListener('error', () => toast('This preview could not be loaded. Check the render stage and job log.'));
      watchPreview(video);
    } else surface.append(el('div', {class: 'preview-empty'}, el('p', {class: 'eyebrow'}, draft.ad?.brand?.name || 'Your film'), el('h3', {}, draft.ad?.scenes?.[selectedScene]?.headline || 'Your story starts here.'), el('p', {}, 'Build a composition, then render your film to watch it here.')));
    panel.append(el('div', {class: 'preview-mat'}, surface));
    if (video) panel.append(videoControls(video));
    const previewDuration = previewUrl ? (previewScenes().at(-1)?.end ?? duration()) : duration();
    panel.append(el('div', {class: 'preview-caption'}, el('span', {}, `${title(fmt)} · ${fmt === 'portrait' ? '9:16' : fmt === 'landscape' ? '16:9' : '1:1'} · ${previewDuration.toFixed(1)}s`), previewUrl && el('a', {href: previewUrl, download: ''}, 'Download film ↓')));
    if (state.preview?.stale) panel.append(el('div', {class: 'stale-indicator'}, 'This is an earlier render. Continue the stages marked “Needs update” to include your changes.'));
    panel.append(el('div', {class: 'stale-indicator', id: 'preview-dirty', hidden: !dirty}, 'Your edits are unsaved. The preview shows the last built version.'));
    return panel;
  }
  function videoControls(video, compact = false) {
    const play = button('▶', async () => { if (video.paused) { try { await video.play(); } catch (error) { toast(error.message); } } else video.pause(); }, 'icon-button', {'aria-label': 'Play preview'});
    const range = el('input', {type: 'range', min: 0, max: 100, step: .05, value: 0, class: 'scrubber', 'aria-label': 'Preview position', onInput: event => { video.currentTime = Number(event.target.value); }});
    const time = el('span', {class: 'time'}, '0:00 / 0:00');
    const mute = button('♫', () => { video.muted = !video.muted; update(); }, 'icon-button', {'aria-label': 'Mute preview', 'aria-pressed': 'false'});
    const update = () => { const total = Number.isFinite(video.duration) ? video.duration : 0; range.max = total || 100; range.value = video.currentTime; range.disabled = !total; time.textContent = `${clock(video.currentTime)} / ${clock(total)}`; play.textContent = video.paused ? '▶' : 'Ⅱ'; play.setAttribute('aria-label', video.paused ? 'Play preview' : 'Pause preview'); mute.textContent = video.muted ? '♪̸' : '♫'; mute.setAttribute('aria-label', video.muted ? 'Unmute preview' : 'Mute preview'); mute.setAttribute('aria-pressed', String(video.muted)); };
    ['loadedmetadata', 'timeupdate', 'play', 'pause', 'ended', 'volumechange'].forEach(event => video.addEventListener(event, update));
    const fullscreen = !compact && document.fullscreenEnabled && button('⛶', async () => {
      try { if (document.fullscreenElement) await document.exitFullscreen(); else await video.closest('.preview-panel').requestFullscreen(); } catch (error) { toast(error.message); }
    }, 'icon-button', {'aria-label': 'Toggle full screen preview'});
    return el('div', {class: compact ? 'source-controls' : 'playback'}, el('div', {class: 'playback-row'}, play, range, time, mute, fullscreen));
  }
  function renderEditor() {
    const stage = stageInfo(activeStage);
    const panel = el('section', {class: 'editor-panel', 'aria-label': `${title(activeStage)} editor`}, el('div', {class: 'editor-intro'}, el('div', {class: 'row'}, el('p', {class: 'eyebrow'}, `Step ${String(STAGES.indexOf(activeStage) + 1).padStart(2, '0')} / 07`)), el('h2', {}, TITLES[activeStage]), el('p', {}, DESCRIPTIONS[activeStage])));
    const content = el('div', {class: 'editor-content'});
    if (stage.note) content.append(el('div', {class: `note ${stage.status === 'stale' ? 'warning' : ''}`}, stage.note));
    ({brief: briefEditor, capture: captureEditor, storyboard: storyboardEditor, audio: audioEditor, composition: compositionEditor, render: renderEditorContent, publish: publishEditor}[activeStage])(content);
    panel.append(content);
    panel.append(el('div', {class: 'stage-actions'}, el('p', {class: 'help'}, historical ? 'Restore this complete version to continue editing.' : 'Save a complete version and continue from this stage.'), button(busy ? 'Working…' : running() ? 'Stage in progress…' : RUN_LABELS[activeStage], () => runStage(activeStage), 'primary', {disabled: historical || busy || running()})));
    return panel;
  }
  function briefEditor(content) {
    content.append(inputField('Project name', draft.project?.name || '', value => { draft.project.name = value; }, {maxLength: 100, required: true}),
      el('div', {class: 'fields-2'}, inputField('Language', 'English', () => {}, {disabled: true}), inputField('Film format', draft.ad?.format || 'portrait', value => { draft.ad.format = value; }, {select: ['portrait', 'landscape', 'square']})),
      el('div', {class: 'section-label'}, 'Destinations'), el('div', {class: 'destinations'}, ['Instagram', 'Facebook', 'YouTube'].map(name => el('span', {class: 'destination'}, name))), el('hr', {class: 'divider', style: 'margin-top:24px'}),
      el('div', {class: 'section-label'}, 'Brand'), inputField('Brand name', draft.ad?.brand?.name || '', value => { draft.ad.brand.name = value; }, {maxLength: 100}),
      el('div', {class: 'note'}, 'English is the project language. Every saved version includes all three delivery destinations.'), fileSummary());
  }
  function captureEditor(content) {
    const sources = (state.files || []).filter(item => /^(source|assets)\//.test(item.path) && /\.(mp4|webm|mov|png|jpg|jpeg|webp)$/i.test(item.path));
    if (!sources.length) content.append(el('p', {class: 'empty'}, 'No source media is available in this version yet. Check the capture stage log for import details.'));
    sources.forEach((source, index) => {
      const card = el('div', {class: 'artifact-card'}, el('h3', {}, `Source ${index + 1}`));
      if (/\.(mp4|webm|mov)$/i.test(source.path)) { const video = el('video', {class: 'source-video', src: fileLink(source), playsinline: '', preload: 'metadata', 'aria-label': `Source ${index + 1}`}); card.append(video, videoControls(video, true)); }
      else card.append(el('img', {class: 'source-thumb', src: fileLink(source), alt: `Captured product source ${index + 1}`, loading: 'lazy'}));
      card.append(el('a', {class: 'file-link', href: fileLink(source), download: ''}, `Download original · ${size(source.bytes)} ↓`)); content.append(card);
    });
    content.append(el('div', {class: 'note'}, 'Source files are preserved in full. Use a scene’s framing controls to change its crop, source start, or playback speed.'), button('Edit scene framing →', () => changeStage('storyboard')));
  }
  function storyboardEditor(content) {
    const scenes = draft.ad?.scenes || [];
    content.append(el('div', {class: 'section-label'}, el('span', {}, 'Your scenes'), el('span', {class: 'duration-label', id: 'duration-total'}, `${duration().toFixed(1)} seconds`)));
    content.append(el('div', {class: 'scene-strip', role: 'group', 'aria-label': 'Select scene'}, scenes.map((scene, index) => el('button', {type: 'button', class: `scene-card ${index === selectedScene ? 'active' : ''}`, 'data-scene-index': index, 'aria-pressed': String(index === selectedScene), 'aria-current': index === selectedScene ? 'true' : undefined, 'aria-controls': 'scene-details', 'aria-label': `Scene ${index + 1}: ${scene.headline}`, onClick: () => selectScene(index, true)}, el('small', {}, String(index + 1).padStart(2, '0')), el('strong', {}, scene.headline), el('span', {}, `${scene.duration}s`)))));
    content.append(el('p', {class: 'help scene-sync-help'}, state.preview?.url ? 'Playback highlights the current scene. Select a scene to jump to its start in the saved video.' : 'Select a scene to edit it. Render your film to preview and jump between scenes.'));
    const details = el('div', {id: 'scene-details', 'data-scene-index': selectedScene, onFocusout: () => setTimeout(() => refreshSceneDetails(), 0)});
    sceneDetails(details);
    content.append(details);
  }
  function sceneDetails(content) {
    const scenes = draft.ad?.scenes || [];
    const scene = scenes[selectedScene]; if (!scene) { content.append(el('p', {class: 'empty'}, 'This version has no scenes.')); return; }
    content.append(el('div', {class: 'scene-heading'}, el('h3', {}, `Scene ${String(selectedScene + 1).padStart(2, '0')} · ${title(scene.id)}`), el('span', {class: 'scene-index'}, `${selectedScene + 1} of ${scenes.length}`)),
      inputField('Headline on screen', scene.headline, value => { scene.headline = value; }, {maxLength: 110, required: true}),
      inputField('Supporting copy', scene.body || '', value => { scene.body = value; }, {textarea: true, maxLength: 220}),
      el('div', {class: 'fields-2'}, inputField('Layout', scene.layout || draft.ad.template || '', value => { scene.layout = value; }, {select: [...new Set([scene.layout || draft.ad.template, ...(state.layouts || [])].filter(Boolean))], help: 'Choose a scene template. Save, build Composition, then Render to see the new layout.'}), inputField('Duration · seconds', scene.duration, value => { scene.duration = value; }, {type: 'number', min: .5, max: 30, step: .1, required: true})));
    if (scene.media) {
      const media = scene.media;
      const framing = el('details', {class: 'details', open: true}, el('summary', {}, 'Shot timing & framing'));
      if (media.type === 'video') framing.append(el('div', {class: 'fields-2'}, inputField('Source start · seconds', media.in ?? 0, value => { media.in = value; }, {type: 'number', min: 0, max: 86400, step: .1}), inputField('Playback speed', media.speed ?? 1, value => { media.speed = value; }, {type: 'number', min: .25, max: 8, step: .05})));
      const crop = media.crop;
      if (crop) framing.append(el('div', {class: 'section-label'}, 'Crop · source pixels'), el('div', {class: 'fields-4'}, ['Left', 'Top', 'Width', 'Height'].map((label, index) => inputField(label, crop[index], value => { media.crop[index] = value; }, {type: 'number', min: index > 1 ? 1 : 0, step: 1}))));
      framing.append(el('p', {class: 'help'}, crop ? 'Crop values are measured in the original source. The original recording stays intact.' : 'This scene uses the full source frame.')); content.append(framing);
    }
    content.append(el('div', {class: 'note'}, 'On-screen copy and spoken narration are separate. Edit the voice script in Audio.'), button('Edit narration →', () => changeStage('audio'), 'quiet'));
  }
  function audioEditor(content) {
    if (!draft.audio) { content.append(el('p', {class: 'empty'}, 'This version has no audio plan.')); return; }
    const voice = draft.project.narration;
    content.append(el('div', {class: 'track-card'}, el('div', {class: 'section-label'}, 'Narration voice'),
      el('div', {class: 'fields-2'}, inputField('Voice provider', voice.provider, value => {
        voice.provider = value; voice.ssh_host = null;
        voice.voice = {google: 'Kore', macos: 'Samantha', deepgram: 'aura-2-thalia-en', elevenlabs: ''}[value];
        render();
      }, {select: [{value: 'google', label: 'Google · Gemini TTS'}, {value: 'macos', label: 'macOS'}, {value: 'deepgram', label: 'Deepgram'}, {value: 'elevenlabs', label: 'ElevenLabs'}]}),
      inputField('Voice name', voice.voice || '', value => { voice.voice = value; }, {required: true, maxLength: 100})),
      inputField('Speaking speed', voice.rate ?? 1, value => { voice.rate = value; }, {type: 'number', min: .5, max: 2, step: .05, help: '1 is the original pace. A higher value speaks faster.'}),
      voice.provider === 'macos' && inputField('Mac SSH host · optional', voice.ssh_host || '', value => { voice.ssh_host = value || null; }, {maxLength: 100}),
      el('p', {class: 'help'}, voice.provider === 'google' ? 'Google generates English narration directly from this server using your account. Try Kore, Aoede, or Zephyr. Save and build Audio to hear the selected voice.' : 'Provider credentials come from the server environment. Save and build Audio to hear the selected voice.')));
    const music = draft.audio.music;
    if (music) content.append(el('div', {class: 'track-card'}, el('div', {class: 'section-label'}, 'Music bed', el('span', {class: 'duration-label'}, 'Licensed track')), el('h3', {}, music.title || 'Music'), el('p', {}, [music.artist, music.license].filter(Boolean).join(' · ')), inputField('Music level · dB', music.gain_db ?? -12, value => { music.gain_db = value; }, {type: 'number', min: -60, max: 0, step: 1, help: 'Lower the level to give the narration more space.'})));
    const mix = file('mix.wav'); if (mix) content.append(el('div', {class: 'section-label'}, 'Saved audio mix'), el('audio', {class: 'audio-player', src: fileLink(mix), controls: '', preload: 'metadata', 'aria-label': 'Saved audio mix'}));
    content.append(el('div', {class: 'section-label'}, 'Narration script', el('span', {class: 'duration-label'}, 'English')));
    const narration = draft.audio.narration || [];
    if (!narration.length) content.append(el('p', {class: 'empty'}, 'There are no narration clips in this version.'));
    narration.forEach((clip, index) => {
      const block = el('div', {class: 'narration-block'}, inputField(`Voice ${String(index + 1).padStart(2, '0')} · spoken words`, clip.text || '', value => { clip.text = value; }, {textarea: true, maxLength: 2000}), el('div', {class: 'fields-2'}, inputField('Starts at · seconds', clip.at ?? 0, value => { clip.at = value; }, {type: 'number', min: 0, max: 86400, step: .1}), inputField('Voice level · dB', clip.gain_db ?? 0, value => { clip.gain_db = value; }, {type: 'number', min: -60, max: 6, step: 1})));
      const audioFile = file(clip.path); if (audioFile) block.append(el('audio', {class: 'audio-player', src: fileLink(audioFile), controls: '', preload: 'none', 'aria-label': `Saved narration clip ${index + 1}`})); content.append(block);
    });
    content.append(el('p', {class: 'help', style: 'margin-top:15px'}, 'The players use saved audio. Build audio after changing the script or mix, then update Render. Visuals are reused.'));
  }
  function compositionEditor(content) {
    content.append(el('div', {class: 'artifact-card'}, el('h3', {}, 'A complete motion composition'), el('p', {}, `${draft.ad?.scenes?.length || 0} scenes · ${duration().toFixed(1)} seconds · ${title(draft.ad?.format || 'portrait')}. Build this stage to apply your saved storyboard and brand.`), file('composition/index.html') && el('a', {class: 'button', href: fileLink(file('composition/index.html')), download: ''}, 'Download composition HTML ↓')),
      el('div', {class: 'note'}, 'When you change one scene, the source remains available. Rebuild the affected stages and keep every previous version.'), fileSummary('composition/'));
  }
  function renderEditorContent(content) {
    const delivery = file('delivery.mp4');
    content.append(el('div', {class: 'artifact-card'}, el('h3', {}, delivery ? 'Your saved film' : 'Make the finished film'), el('p', {}, delivery ? `A ${title(draft.ad?.format || 'portrait').toLowerCase()} video is available in this saved version. ${size(delivery.bytes)}.` : 'Build the composition first, then render the film. Progress and any errors appear above the workspace.'), delivery && el('a', {class: 'button coral', href: fileLink(delivery), download: ''}, '↓ Download video')),
      el('div', {class: 'section-label'}, 'Keep the entire project'), el('p', {class: 'help', style: 'margin-bottom:14px'}, 'The full version includes your source media, editable scene and audio plans, and all artifacts saved at this point.'), download(revisionId()), fileSummary());
  }
  function publishEditor(content) {
    content.append(el('div', {class: 'note warning'}, 'Delivery preparation only. Reconnect your social accounts before live publishing can be enabled.'), ...['Instagram', 'Facebook', 'YouTube'].map(name => el('div', {class: 'publish-row'}, el('span', {}, name), el('small', {}, 'Account reconnection required'))),
      el('p', {class: 'help', style: 'margin:18px 0'}, 'Prepare an English delivery package for all three destinations. No posts are sent from this studio.'),
      file('publishing.json') && el('a', {class: 'button', href: fileLink(file('publishing.json')), download: ''}, '↓ Publishing plan'), download(revisionId(), 'Full delivery project'), button('Live publishing unavailable', () => {}, 'quiet', {disabled: true}));
  }
  function fileSummary(prefix = '') {
    const files = (state.files || []).filter(item => item.path.startsWith(prefix));
    return el('details', {class: 'details', style: 'margin-top:22px'}, el('summary', {}, `${files.length} files in this version`), el('div', {class: 'file-list'}, files.map(item => el('a', {class: 'file-item', href: fileLink(item), download: ''}, el('span', {class: 'file-name'}, item.path), el('span', {class: 'file-size'}, `${size(item.bytes)} ↓`)))));
  }
  async function save(stage = activeStage, label = null) {
    if (historical || busy || running()) return false;
    const invalid = $('input:invalid, textarea:invalid, select:invalid', $('#workspace'));
    if (invalid) { invalid.reportValidity(); return false; }
    busy = true;
    try {
      const result = await api('/api/save', {base: revisionId(), label: label || `${title(stage)} · ${new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}`, ad: draft.ad, audio: draft.audio, project: {...draft.project, language: 'en', destinations: ['instagram', 'facebook', 'youtube']}, stage});
      busy = false; setState(result); toast('Complete version saved.'); return true;
    } catch (error) { busy = false; toast(error.message); render(); return false; }
  }
  async function runStage(stage) {
    if (historical || busy || running()) return;
    if (dirty && !(await save(stage))) return;
    busy = true; render();
    try {
      await api('/api/run', {base: revisionId(), stage});
      busy = false; const fresh = await api('/api/state'); setState(fresh); toast(`${title(stage)} started.`);
    } catch (error) { busy = false; toast(error.message); render(); }
  }
  async function loadLatest(checkDirty = false) {
    if (checkDirty && dirty && !confirm('Load the latest version and discard your unsaved edits? Download your edits first if you want to keep them.')) return;
    try { const result = await api('/api/state'); historical = false; setState(result); } catch (error) { toast(error.message); }
  }
  async function loadVersion(id) {
    if (dirty && !confirm('Open this saved version and discard your unsaved edits? Save a version first to keep them.')) return;
    try { const result = await api(`/api/state?version=${encodeURIComponent(id)}`); historical = true; $('#versions-dialog').close(); setState(result); } catch (error) { toast(error.message); }
  }
  async function restore(id) {
    if (busy) return;
    if (dirty && !confirm('Restore this version and discard your unsaved edits? Your previously saved versions will remain available.')) return;
    busy = true;
    try { const result = await api('/api/restore', {version: id}); historical = false; busy = false; $('#versions-dialog').close(); setState(result); toast('Restored as a new complete version.'); } catch (error) { busy = false; toast(error.message); }
  }
  function showVersions() {
    const dialog = $('#versions-dialog');
    const versions = [...(state.versions || [])].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    dialog.replaceChildren(el('div', {class: 'dialog-header'}, el('h2', {id: 'versions-title'}, 'Your complete versions'), button('×', () => dialog.close(), 'icon-button', {'aria-label': 'Close versions'})),
      el('div', {class: 'dialog-body'}, el('p', {class: 'help'}, 'Every version includes the complete project at that moment. Preview it, download all its files, or restore it as a new version.'), versions.length ? versions.map(version => el('article', {class: 'version'}, el('div', {class: 'version-top'}, el('h3', {}, version.label || version.id), version.id === revisionId() && pill('ready', 'Viewing')), el('p', {}, `${title(version.stage)} · ${date(version.created_at)}`), el('div', {class: 'button-row'}, button('View version', () => loadVersion(version.id)), download(version.id, 'Full version'), button('Restore', () => restore(version.id), 'quiet', {disabled: busy || running()})))) : el('p', {class: 'empty'}, 'No saved versions are available yet.')));
    dialog.showModal();
  }
  async function showLog(job) {
    try {
      const result = await api(`/api/log/${encodeURIComponent(job.id)}`);
      const dialog = $('#versions-dialog');
      dialog.replaceChildren(el('div', {class: 'dialog-header'}, el('h2', {id: 'versions-title'}, `${title(job.stage)} log`), button('×', () => dialog.close(), 'icon-button', {'aria-label': 'Close log'})), el('div', {class: 'dialog-body'}, el('pre', {class: 'job-log'}, result.log || job.message || 'No output yet.')));
      dialog.showModal();
    } catch (error) { toast(error.message); }
  }
  function downloadDraft() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(draft, null, 2)], {type: 'application/json'}));
    const link = el('a', {href: url, download: 'taskfilm-unsaved-edits.json'}); link.click(); setTimeout(() => URL.revokeObjectURL(url), 2000);
  }
  function schedulePoll() {
    clearTimeout(timer);
    if (historical) return;
    timer = setTimeout(async () => {
      try {
        const next = await api('/api/state');
        if (historical) return;
        if (next.revision.id !== state.revision.id) {
          if (dirty) { state.jobs = next.jobs; state.versions = next.versions; const firstConflict = !conflict; conflict = true; if (firstConflict) render(); else renderJobs($('#jobs')); schedulePoll(); }
          else setState(next);
        } else {
          const changed = JSON.stringify(next.jobs) !== JSON.stringify(state.jobs);
          state.jobs = next.jobs; state.stages = next.stages; state.versions = next.versions;
          if (changed && !dirty) render(); else renderJobs($('#jobs'));
          schedulePoll();
        }
      } catch { schedulePoll(); }
    }, running() ? 2000 : 7000);
  }
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  document.addEventListener('keydown', event => { if ((event.ctrlKey || event.metaKey) && event.key === 's') { event.preventDefault(); if (dirty) save(); } });
  api('/api/state').then(result => setState(result)).catch(error => {
    $('#app').replaceChildren(el('div', {class: 'loading'}, el('span', {class: 'brand-mark'}, 't'), el('h1', {}, 'The studio could not open.'), el('p', {}, error.message), button('Try again', () => location.reload(), 'primary')));
  });
})();
