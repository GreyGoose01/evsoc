// English/German for the web pages. The pages are written in English; in German mode every text node
// and the attributes placeholder/title/aria-label are translated with the catalogue from
// evsoc/lang/de.txt (same rules as evsoc/i18n.py), also everything the page adds later.
// Language: localStorage "evsoc-lang", else the browser language (German -> de, anything else -> en).
(function () {
  "use strict";
  const PAIRS = window.EVSOC_I18N || [];
  let lang = null;
  try { lang = localStorage.getItem("evsoc-lang"); } catch (e) { /* private mode */ }
  if (lang !== "de" && lang !== "en") lang = (navigator.language || "en").toLowerCase().startsWith("de") ? "de" : "en";
  window.EVSOC_LANG = lang;
  window.EVSOC_LOCALE = lang === "de" ? "de-DE" : "en-GB";
  document.documentElement.lang = lang;

  const exact = new Map(), templates = [], phrases = [];
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  for (const [de, en] of PAIRS) {
    if (de.includes("{}")) {
      const parts = de.split("{}");
      let re = "";
      parts.forEach((part, i) => {
        re += esc(part);
        if (i < parts.length - 1) re += (i === parts.length - 2 && parts[parts.length - 1] === "") ? "([\\s\\S]+)" : "([\\s\\S]+?)";
      });
      templates.push([new RegExp("^" + re + "$"), en, parts.join("").length]);
    } else {
      exact.set(de, en);
      if (de.includes(" ") && de.length >= 8) phrases.push([de, en]);
    }
  }
  templates.sort((a, b) => b[2] - a[2]);
  phrases.sort((a, b) => b[0].length - a[0].length);
  const L = "A-Za-zÄÖÜäöüß0-9_";
  const phraseRes = phrases.map(([de, en]) => [new RegExp("(^|[^" + L + "])" + esc(de) + "(?![" + L + "])", "g"), en]);

  function fill(en, groups, depth) {
    let n = 0;
    return en.replace(/\{(\d*)\}/g, (m, i) => {
      const k = i === "" ? n++ : Number(i);
      return k < groups.length ? one(groups[k], depth + 1) : m;
    });
  }
  function one(text, depth) {
    const core = text.trim();
    if (!core || depth > 4) return text;
    const lead = text.slice(0, text.length - text.trimStart().length), trail = text.slice(text.trimEnd().length);
    if (exact.has(core)) return lead + exact.get(core) + trail;
    for (const [re, en] of templates) {
      const m = core.match(re);
      if (m) return lead + fill(en, m.slice(1), depth) + trail;
    }
    let out = core;
    for (const [re, en] of phraseRes) out = out.replace(re, (m, pre) => pre + en);
    if (out === core) out = fallback(core, depth);
    return lead + out + trail;
  }
  // lines put together from pieces: "a, b" lists, a message in trailing brackets, "name: message"
  function fallback(core, depth) {
    const stamp = core.match(/^(\(?\d\d:\d\d:\d\d[.\d]*\)?\s+)([\s\S]+)$/);
    if (stamp) return stamp[1] + one(stamp[2], depth + 1);  // log lines start with the time
    const parts = core.split(", ");
    if (parts.length > 1 && parts.every((p) => exact.has(p))) return parts.map((p) => exact.get(p)).join(", ");
    if (core.endsWith(")")) {
      let d = 0, start = -1;
      for (let i = core.length - 1; i >= 0; i--) {
        if (core[i] === ")") d++; else if (core[i] === "(") d--;
        if (d === 0) { start = i; break; }
      }
      if (start > 0) {
        const inner = core.slice(start + 1, -1), done = one(inner, depth + 1);
        if (done !== inner) return one(core.slice(0, start), depth + 1) + "(" + done + ")";
      }
    }
    const k = core.indexOf(": ");
    if (k > 0 && !core.slice(0, k).trim().includes(" ")) {
      const rest = core.slice(k + 2), done = one(rest, depth + 1);
      if (done !== rest) return core.slice(0, k + 2) + done;
    }
    return core;
  }
  function tr(text) {
    if (lang !== "de" || !text) return text;
    return text.split("\n").map((l) => one(l, 0)).join("\n");
  }
  window.T = tr;

  const SKIP = new Set(["SCRIPT", "STYLE", "CODE", "TEXTAREA"]);
  function translateText(node) {
    const parent = node.parentNode;
    if (!parent || SKIP.has(parent.nodeName)) return;
    const pre = parent.closest && parent.closest("pre");
    const src = node.data;
    let out;
    if (pre) out = tr(src);
    else {
      const core = src.replace(/\s+/g, " ");
      const t = tr(core);
      out = t === core ? src : t;
    }
    if (out !== src) node.data = out;
  }
  function translateAttrs(el) {
    for (const a of ["placeholder", "title", "aria-label"]) {
      const v = el.getAttribute && el.getAttribute(a);
      if (v) { const t = tr(v); if (t !== v) el.setAttribute(a, t); }
    }
  }
  function walk(root) {
    if (root.nodeType === 3) { translateText(root); return; }
    if (root.nodeType !== 1 || SKIP.has(root.nodeName)) return;
    translateAttrs(root);
    const it = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    let n;
    while ((n = it.nextNode())) {
      if (n.nodeType === 3) translateText(n); else translateAttrs(n);
    }
  }

  function addSwitch() {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn small lang-switch";
    btn.textContent = lang === "en" ? "Deutsch" : "English";
    btn.title = lang === "en" ? "Auf Deutsch umschalten" : "Switch to English";
    btn.onclick = () => {
      try { localStorage.setItem("evsoc-lang", lang === "en" ? "de" : "en"); } catch (e) { /* private mode */ }
      location.reload();
    };
    const slot = document.getElementById("langSlot");
    if (slot) slot.appendChild(btn);
    else {
      btn.style.cssText = "position:fixed;right:12px;bottom:12px;z-index:20;font:inherit;font-size:12.5px;padding:4px 10px;" +
        "border-radius:8px;border:1px solid rgba(127,127,127,.4);background:transparent;color:inherit;cursor:pointer;opacity:.75";
      document.body.appendChild(btn);
    }
  }

  function start() {
    if (lang === "de") {
      walk(document.body);
      document.title = tr(document.title);
      new MutationObserver((records) => {
        for (const r of records) {
          if (r.type === "characterData") translateText(r.target);
          else if (r.type === "attributes") translateAttrs(r.target);
          else r.addedNodes.forEach(walk);
        }
      }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true,
                                   attributeFilter: ["placeholder", "title", "aria-label"] });
    }
    addSwitch();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
