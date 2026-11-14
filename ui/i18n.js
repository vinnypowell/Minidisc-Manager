/* Language engine for MiniDisc Manager (TEST).
 *
 * English is the key: every visible English string is looked up as it is, so no string in index.html has to be rewritten. The page's text
 * nodes and its title / placeholder / aria-label / alt attributes are translated as they are drawn (a MutationObserver sees every pop-up and
 * every card as it is built), and switching language re-draws everything on the fly; English comes straight back from the stored originals.
 *
 * The words live in ui/lang.js as rows:  [english, french, german, dutch]  (LANGS below says which column is which).
 * An English entry may hold {name} placeholders ("{n} tracks"; {n} is a number, other names are any text): it then matches any text of that shape and the translation reuses the values.
 * A string with no entry stays English, so the program can be translated in stages.
 *
 * In script: I18N.t('English text') or I18N.t('{n} tracks', { n: 5 }) for text that is not put on the page (an alert, a title bar).
 * Put translate="no" on an element whose text must never be translated.
 */
(function () {
  'use strict';
  const LANGS = [['en', 'English'], ['fr', 'Français'], ['de', 'Deutsch'], ['nl', 'Nederlands']];     // column order in lang.js (en first)
  const exact = {};                      // lang -> Map(english -> translation)
  const pats = {};                       // lang -> [{ re, keys, out }]
  let cur = 'en';
  const textState = new WeakMap();       // text node -> { orig, out }
  const attrState = new WeakMap();       // element -> { attr -> { orig, out } }
  const ATTRS = ['title', 'placeholder', 'aria-label', 'alt'];
  const SKIP = { SCRIPT: 1, STYLE: 1, TEXTAREA: 1, CANVAS: 1, CODE: 1, PRE: 1 };
  let observer = null, queue = new Set(), pending = false;

  LANGS.forEach(l => { exact[l[0]] = new Map(); pats[l[0]] = []; });

  function add(rows) {                    // rows: [[en, fr, de, nl], ...]
    const more = [];
    rows.forEach(r => {                   // the help pop-ups write a bullet as "• text" in their data but show it without the bullet: match both
      if (typeof r[0] === 'string' && r[0].indexOf('• ') === 0) more.push(r.map(x => String(x || '').replace(/^•\s+/, '')));
    });
    if (more.length) rows = rows.concat(more);
    rows.forEach(r => {
      r = r.map(x => String(x || '').trim());                       // the page's own spaces around a text are kept when it is translated
      for (let i = 1; i < LANGS.length; i++) {
        const lang = LANGS[i][0], out = r[i];
        if (!out || !r[0]) continue;
        if (r[0].indexOf('{') >= 0) {
          // {n} is a number, any other name is any text. Placeholders written straight after each other ("{x1}{x2}", as the page builds
          // "5 track" + "s") are one piece of text: the first takes it all and the later ones stay empty. Text that fills a placeholder is
          // translated too ("5 tracks" -> "5 pistes"), except when it sits in quotes (a title or a name).
          const keys = [], noRec = []; let src = '', lit = 0, afterPh = false, quoted = false, suffix = false, must = '';
          r[0].split(/(\{\w+\})/).forEach(p => {
            const m = /^\{(\w+)\}$/.exec(p);
            if (m) {
              keys.push(m[1]); noRec.push(quoted);
              // a placeholder stuck to a word ("file{x2}") is an ending such as "s" and may be empty
              src += afterPh ? '()' : (m[1] === 'n' ? '(\\d[\\d.,]*)' : (suffix ? '(.*?)' : '(.+?)'));
              afterPh = true;
            } else if (p) {
              src += p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); lit += p.length; afterPh = false;
              quoted = /[“"]$/.test(p); suffix = /[A-Za-z]$/.test(p);
              if (p.length > must.length) must = p;
            }
          });
          pats[lang].push({ re: new RegExp('^' + src + '$', 's'), keys, noRec, lit, must, out });
          sorted = false; cache.clear();
        } else { exact[lang].set(r[0], out); cache.clear(); }
      }
    });
  }
  let sorted = true;
  const cache = new Map();                // "lang\u0001text" -> translation or null (the page asks for the same texts again and again)

  function lookup(s, lang, depth) {       // the translation of one trimmed English string, or null
    if (lang === 'en') return null;
    const hit = exact[lang].get(s);
    if (hit !== undefined) return hit;
    const ck = lang + '\u0001' + s;
    if (!depth && cache.has(ck)) return cache.get(ck);
    const r = lookupPattern(s, lang, depth);
    if (!depth) { if (cache.size > 20000) cache.clear(); cache.set(ck, r); }
    return r;
  }

  function lookupPattern(s, lang, depth) {
    if (!sorted) { LANGS.forEach(l => pats[l[0]].sort((a, b) => b.lit - a.lit)); sorted = true; }   // the most specific pattern (most fixed words) first
    const list = pats[lang];
    for (let i = 0; i < list.length; i++) {
      if (list[i].must && s.indexOf(list[i].must) < 0) continue;      // its fixed words are not in this text: skip the regular expression
      const m = list[i].re.exec(s);
      if (m) {
        let out = list[i].out;
        list[i].keys.forEach((k, j) => {
          let v = m[j + 1];
          if (v && !list[i].noRec[j] && (depth || 0) < 2) v = convert(v, lang, (depth || 0) + 1);
          out = out.split('{' + k + '}').join(v);
        });
        return out;
      }
    }
    return null;
  }

  function convert(s, lang, depth) {      // keeps the spaces around the text
    const m = /^(\s*)([\s\S]*?)(\s*)$/.exec(s);
    if (!m[2]) return s;
    const t = lookup(m[2], lang, depth);
    return t === null ? s : m[1] + t + m[3];
  }

  function t(s, vars) {
    let out = convert(String(s), cur);
    if (vars) Object.keys(vars).forEach(k => { out = out.split('{' + k + '}').join(vars[k]); });
    return out;
  }

  function skipNode(n) {
    for (let p = n.nodeType === 1 ? n : n.parentNode; p && p.nodeType === 1; p = p.parentNode) {
      if (SKIP[p.tagName] || p.getAttribute('translate') === 'no') return true;
    }
    return false;
  }

  function doText(node) {
    let st = textState.get(node);
    if (!st || node.data !== st.out) st = { orig: node.data, out: node.data };     // new text, or the page changed it: that is the new English original
    const out = convert(st.orig, cur);
    if (out !== node.data) node.data = out;
    st.out = out; textState.set(node, st);
  }

  function doAttrs(e) {
    let map = attrState.get(e);
    for (const a of ATTRS) {
      if (!e.hasAttribute(a)) continue;
      const v = e.getAttribute(a);
      let st = map && map[a];
      if (!st || v !== st.out) st = { orig: v, out: v };
      const out = convert(st.orig, cur);
      if (out !== v) e.setAttribute(a, out);
      st.out = out;
      if (!map) { map = {}; attrState.set(e, map); }
      map[a] = st;
    }
  }

  function walk(root) {
    if (!root || skipNode(root)) return;
    if (root.nodeType === 3) { doText(root); return; }
    if (root.nodeType !== 1) return;
    doAttrs(root);
    const tw = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode: n => (n.nodeType === 1 && (SKIP[n.tagName] || n.getAttribute('translate') === 'no')) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT
    });
    for (let n = tw.nextNode(); n; n = tw.nextNode()) { if (n.nodeType === 3) doText(n); else doAttrs(n); }
  }

  function flush() {
    pending = false;
    const nodes = Array.from(queue); queue = new Set();
    if (observer) observer.disconnect();                            // our own edits must not come back as new changes
    try { nodes.forEach(walk); } finally { observe(); }
  }
  function observe() {
    if (observer && document.body) observer.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  }
  function schedule(n) {
    queue.add(n);
    if (!pending) { pending = true; Promise.resolve().then(flush); }
  }

  function set(lang, remember) {
    if (!exact[lang]) lang = 'en';
    cur = lang;
    document.documentElement.setAttribute('lang', lang);
    if (remember !== false) { try { localStorage.setItem('lang', lang); } catch (e) { /* not remembered */ } }
    if (document.body) { if (observer) observer.disconnect(); try { walk(document.body); } finally { observe(); } }
    document.title = t('MiniDisc Manager');
    paintPicker();
    window.dispatchEvent(new CustomEvent('languagechange-app', { detail: lang }));
  }

  function start() {
    let lang = 'en';
    try { lang = localStorage.getItem('lang') || ''; } catch (e) { lang = ''; }
    if (!lang) {                                                    // first run: the Windows language, when it is one we have
      const nav = String(navigator.language || 'en').slice(0, 2).toLowerCase();
      lang = exact[nav] ? nav : 'en';
    }
    observer = new MutationObserver(recs => {
      recs.forEach(r => {
        if (r.type === 'childList') r.addedNodes.forEach(schedule);
        else schedule(r.target);                                      // changed text or attribute
      });
    });
    buildPicker();
    set(lang, false);
  }

  // ---- the language button: a small drawn flag and the language's own name (Windows cannot draw flag emoji, so the flags are tiny SVG pictures)
  const FLAGS = {
    en: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 30"><clipPath id="s"><path d="M0,0 v30 h60 v-30 z"/></clipPath><clipPath id="t"><path d="M30,15 h30 v15 z v15 h-30 z h-30 v-15 z v-15 h30 z"/></clipPath><g clip-path="url(#s)"><path d="M0,0 v30 h60 v-30 z" fill="#012169"/><path d="M0,0 L60,30 M60,0 L0,30" stroke="#fff" stroke-width="6"/><path d="M0,0 L60,30 M60,0 L0,30" clip-path="url(#t)" stroke="#C8102E" stroke-width="4"/><path d="M30,0 v30 M0,15 h60" stroke="#fff" stroke-width="10"/><path d="M30,0 v30 M0,15 h60" stroke="#C8102E" stroke-width="6"/></g></svg>',
    fr: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 3 2"><rect width="1" height="2" fill="#0055A4"/><rect x="1" width="1" height="2" fill="#fff"/><rect x="2" width="1" height="2" fill="#EF4135"/></svg>',
    de: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 5 3"><rect width="5" height="1" fill="#000"/><rect y="1" width="5" height="1" fill="#DD0000"/><rect y="2" width="5" height="1" fill="#FFCE00"/></svg>',
    nl: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 9 6"><rect width="9" height="2" fill="#AE1C28"/><rect y="2" width="9" height="2" fill="#fff"/><rect y="4" width="9" height="2" fill="#21468B"/></svg>'
  };
  function flagImg(code) {
    const i = document.createElement('img');
    i.className = 'flag'; i.alt = ''; i.src = 'data:image/svg+xml,' + encodeURIComponent(FLAGS[code] || FLAGS.en);
    i.style.cssText = 'width:20px;height:14px;object-fit:cover;border-radius:2px;border:1px solid rgba(128,128,128,.45);vertical-align:-2px;margin-right:7px;flex:none';
    return i;
  }
  function paintPicker() {
    const b = document.getElementById('langBtn'); if (!b) return;
    const l = LANGS.find(x => x[0] === cur) || LANGS[0];
    b.textContent = ''; b.append(flagImg(l[0]), document.createTextNode(l[1] + ' ▾'));
    b.title = t('Choose the language of the program');
    document.querySelectorAll('#langMenu .lang-item').forEach(r => r.classList.toggle('on', r.dataset.lang === cur));
  }
  function buildPicker() {
    const b = document.getElementById('langBtn'), m = document.getElementById('langMenu'); if (!b || !m) return;
    m.style.minWidth = '0'; m.style.padding = '6px';
    LANGS.forEach(l => {
      const r = document.createElement('button');
      r.type = 'button'; r.className = 'lang-item'; r.dataset.lang = l[0];
      r.style.cssText = 'display:flex;align-items:center;border:0;background:transparent;padding:6px 10px;border-radius:8px;text-align:left;font-weight:500;cursor:pointer;white-space:nowrap';
      r.append(flagImg(l[0]), document.createTextNode(l[1]));
      r.addEventListener('click', () => { m.classList.add('hidden'); set(l[0]); });
      m.appendChild(r);
    });
    const st = document.createElement('style');
    st.textContent = '#langMenu .lang-item:hover{background:rgba(128,128,128,.18)} #langMenu .lang-item.on{font-weight:700;box-shadow:inset 3px 0 0 var(--accent,#4da3ff)}';
    document.head.appendChild(st);
    b.addEventListener('click', e => { e.stopPropagation(); m.classList.toggle('hidden'); });
    document.addEventListener('click', e => { if (!m.contains(e.target)) m.classList.add('hidden'); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') m.classList.add('hidden'); });
  }

  window.I18N = { add, t, set, get: () => cur, langs: LANGS.map(l => ({ code: l[0], name: l[1] })) };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
