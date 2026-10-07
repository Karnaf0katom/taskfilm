"""Single-shot enriched DOM scan.

One ``page.evaluate`` returns every visible, meaningful element with the attributes the
agent actually needs to decide and to know when it is done:
  role/tag, accessible name (label association for inputs), input type, checked-state,
  value, placeholder, href, enabled, and whether it is in the viewport.

Why a single shot instead of the per-element ``vision/dom_extractor`` round-trips:
  * atomic — it cannot race a mid-scan navigation (the old extractor's failure mode),
  * fast — one round-trip instead of hundreds,
  * richer — checked-state fixes "did my checkbox click take?", in_viewport stops the
    pixel-mouse fallback from targeting off-screen coordinates.
Falls back to the per-element extractor on any evaluate error.
"""

from __future__ import annotations

from typing import Any

_SCAN_JS = r"""
() => {
  const vh = window.innerHeight || 800, vw = window.innerWidth || 1280;
  const FORM = new Set(['input','textarea','select','button']);
  function accName(el, tag){
    const aria = el.getAttribute('aria-label'); if (aria) return aria;
    // A <button> is named by its own contents (HTML-AAM), and the FORM branch below never looks
    // at innerText. Without this, every plain `<button>Choose folder</button>` scans as nameless
    // and the agent cannot see the one control the screen exists to offer.
    if (tag === 'button') { const bt = (el.innerText || '').trim(); if (bt) return bt; }
    if (FORM.has(tag)) {
      const ph = el.getAttribute('placeholder'); if (ph) return ph;
      if (el.id){ try { const l=document.querySelector('label[for="'+CSS.escape(el.id)+'"]'); if(l&&l.innerText) return l.innerText; } catch(e){} }
      const pl = el.closest('label'); if (pl && pl.innerText) return pl.innerText;
      const nm = el.getAttribute('name'); if (nm) return nm;
      if (el.value) return String(el.value);
      return el.getAttribute('title') || '';
    }
    const t = el.innerText || '';
    if (t) return t;
    return el.getAttribute('title') || el.getAttribute('alt') || '';
  }
  // A password / one-time-code / card field's value must never reach the model: the scan
  // is serialized into the brain's prompt, and a real Chrome autofills saved passwords.
  function secretField(el, tag){
    if (tag !== 'input') return false;
    const t = (el.getAttribute('type') || '').toLowerCase();
    const ac = (el.getAttribute('autocomplete') || '').toLowerCase();
    return t === 'password' || /password|one-time-code|cc-number|cc-csc|cc-exp/.test(ac);
  }
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width <= 2 || r.height <= 2) continue;
    const st = window.getComputedStyle(el);
    if (st.display==='none' || st.visibility==='hidden' || parseFloat(st.opacity||'1')===0) continue;
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role');
    const clickable = FORM.has(tag) || tag==='a' || role==='button' || role==='link'
                      || role==='checkbox' || role==='tab' || role==='menuitem' || st.cursor==='pointer';
    const secret = secretField(el, tag);
    out.push({
      tag: tag,
      text: secret ? (el.getAttribute('aria-label') || el.getAttribute('placeholder')
                      || (el.labels && el.labels[0] && el.labels[0].innerText)
                      || el.getAttribute('name') || 'secret field').replace(/\s+/g, ' ').trim().slice(0, 180)
                   : (accName(el, tag) || '').replace(/\s+/g, ' ').trim().slice(0, 180),
      x: r.x, y: r.y, width: r.width, height: r.height,
      clickable: clickable,
      in_viewport: (r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw),
      id: el.id || null,
      data_testid: el.getAttribute('data-testid') || null,
      aria_label: el.getAttribute('aria-label') || null,
      class_name: (typeof el.className === 'string' && el.className.trim())
                  ? el.className.trim().split(/\s+/)[0] : null,
      role: role || null,
      type: el.getAttribute('type') || null,
      checked: (typeof el.checked === 'boolean') ? el.checked : null,
      value: (el.value != null && String(el.value) !== '')
             ? (secret ? '[hidden: filled]' : String(el.value).slice(0, 80)) : null,
      placeholder: el.getAttribute('placeholder') || null,
      href: el.getAttribute('href') || null,
      enabled: !el.disabled,
    });
  }
  return out;
}
"""


def scan_elements(page: Any) -> list[dict[str, Any]]:
    """Return rich element dicts via one page.evaluate; fall back to the per-element scan."""
    try:
        result = page.evaluate(_SCAN_JS)
        if isinstance(result, list):
            return result
    except Exception:
        pass
    from humanflow.vision.dom_extractor import extract_dom_elements  # robust fallback

    return extract_dom_elements(page)
