'use strict';
(() => {
  const $ = s => document.querySelector(s);
  let projects = [], view = localStorage.getItem('taskfilm-project-view') || 'grid';
  const node = (tag, attrs = {}, ...children) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k.startsWith('on')) e.addEventListener(k.slice(2).toLowerCase(), v);
      else if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v === true ? '' : String(v));
    }
    children.flat().forEach(c => { if (c !== undefined && c !== null) e.append(c instanceof Node ? c : document.createTextNode(String(c))); });
    return e;
  };
  const label = value => String(value || '').replace(/^./, c => c.toUpperCase());
  const clock = s => { const total = Math.round(s); return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`; };
  const size = b => b >= 1e9 ? `${(b / 1e9).toFixed(1)} GB` : `${(b / 1e6).toFixed(1)} MB`;
  const edited = t => new Date(t).toLocaleDateString(undefined, {month: 'short', day: 'numeric', year: 'numeric'});
  function toast(message) { $('#toast').textContent = message; $('#toast').hidden = false; setTimeout(() => { $('#toast').hidden = true; }, 6500); }
  function render() {
    const q = $('#project-search').value.trim().toLowerCase(), format = $('#format-filter').value;
    let filtered = projects.filter(p => (!q || `${p.name} ${p.brand || ''}`.toLowerCase().includes(q)) && (format === 'all' || p.format === format));
    if ($('#project-sort').value === 'name') filtered.sort((a, b) => a.name.localeCompare(b.name));
    const surface = $('#projects'); surface.className = view === 'list' ? 'project-list' : 'project-grid';
    $('#grid-view').setAttribute('aria-pressed', view === 'grid'); $('#list-view').setAttribute('aria-pressed', view === 'list');
    $('#project-count').textContent = `${filtered.length} ${filtered.length === 1 ? 'project' : 'projects'}${filtered.length !== projects.length ? ` of ${projects.length}` : ''}`;
    surface.replaceChildren();
    if (!filtered.length) { surface.append(node('div', {class: 'library-empty'}, node('h2', {}, projects.length ? 'No matching projects.' : 'Your next story starts here.'), node('p', {}, projects.length ? 'Try another name or format.' : 'Create a project to begin, or duplicate an existing film.'))); return; }
    filtered.forEach(p => {
      const cover = node('div', {class: 'project-thumbnail'}, p.poster ? node('img', {src: p.poster, alt: '', loading: 'lazy'}) : node('span', {class: 'project-monogram'}, p.name.slice(0, 1).toUpperCase()), node('span', {class: 'format-badge'}, label(p.format || 'Project')), p.pinned ? node('span', {class: 'pinned-badge'}, 'Pinned') : null);
      const open = node('a', {href: p.url, class: 'project-open', 'aria-label': `Open ${p.name} · ${label(p.format)}`}, cover,
        node('div', {class: 'project-card-text'}, node('h2', {}, p.name), node('p', {class: 'project-kind'}, p.error ? 'Project needs attention' : p.running ? 'Building…' : p.kind === 'imported' ? 'Imported film · editable' : p.has_video ? 'Studio film' : 'Draft project')));
      const metadata = node('div', {class: 'project-metadata'}, node('span', {}, `${clock(p.duration || 0)} · ${size(p.bytes || 0)}`), node('time', {datetime: p.updated_at}, p.updated_at ? edited(p.updated_at) : 'Unavailable'));
      const actions = node('div', {class: 'project-card-actions'}, node('span', {}, `${p.versions || 0} ${(p.versions || 0) === 1 ? 'version' : 'versions'}`), node('button', {class: 'button quiet duplicate-project', 'aria-label': `Duplicate ${p.name} · ${label(p.format)}`, onClick: () => createDialog(p)}, 'Duplicate'));
      surface.append(node('article', {class: 'project-card', 'data-project': p.id}, open, metadata, actions));
    });
  }
  async function load() {
    try { const r = await fetch('/api/projects', {cache: 'no-store'}); const data = await r.json(); if (!r.ok) throw Error(data.error); projects = data.projects; render(); }
    catch (e) { $('#project-count').textContent = 'Could not load projects.'; toast(e.message); }
  }
  function createDialog(source = null) {
    const dialog = $('#create-dialog');
    const name = node('input', {id: 'new-name', type: 'text', required: true, maxLength: 100, autocomplete: 'off'}); name.value = source ? `${source.name.slice(0, 85)} — copy` : '';
    const format = node('select', {id: 'new-format'}, ...['portrait', 'landscape', 'square'].map(v => node('option', {value: v}, label(v)))); format.value = source?.format || 'portrait';
    const submit = node('button', {class: 'button coral', type: 'submit'}, source ? 'Create independent copy' : 'Create project');
    const status = node('p', {class: 'help', role: 'status'});
    const form = node('form', {onSubmit: async event => {
      event.preventDefault(); submit.disabled = true; status.textContent = source ? 'Copying all project files…' : 'Creating your project…';
      try {
        const response = await fetch('/api/projects', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name: name.value.trim(), format: format.value, duplicate: source?.id})});
        const result = await response.json(); if (!response.ok) throw Error(result.error || 'Project creation failed'); location.assign(result.url);
      } catch (e) { status.textContent = e.message; submit.disabled = false; }
    }}, node('label', {class: 'field'}, node('span', {class: 'field-label'}, 'Project name'), name),
    !source ? node('label', {class: 'field'}, node('span', {class: 'field-label'}, 'Film format'), format) : node('p', {class: 'help'}, 'Copies the latest complete version into a separate project. The original project stays available.'),
    node('div', {class: 'create-actions'}, submit, status));
    dialog.replaceChildren(node('div', {class: 'dialog-header'}, node('h2', {id: 'create-title'}, source ? 'Duplicate project' : 'A new story'), node('button', {class: 'button icon-button', 'aria-label': 'Close project dialog', onClick: () => dialog.close()}, '×')), node('div', {class: 'dialog-body'}, form));
    dialog.showModal(); name.focus();
  }
  $('#new-project').addEventListener('click', () => createDialog());
  $('#project-search').addEventListener('input', render); $('#format-filter').addEventListener('change', render); $('#project-sort').addEventListener('change', render);
  for (const mode of ['grid', 'list']) $(`#${mode}-view`).addEventListener('click', () => { view = mode; localStorage.setItem('taskfilm-project-view', mode); render(); });
  $('#refresh-projects').addEventListener('click', load); load();
})();
