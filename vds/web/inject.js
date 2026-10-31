/* Visual Death Studio – Seiten-Werkzeug für die Web-Vorschau: Elemente wählen, Stile live ändern, verschieben, skalieren, Text bearbeiten.
   Nachrichten an die IDE laufen über console.log("__VDS__" + JSON). Alle Änderungen sind nur Überschreibungen im DOM, bis die IDE sie in den Quellcode schreibt. */
(() => {
  if (window.__vds) return;
  const PREFIX = "__VDS__";
  const send = (k, d) => { try { console.log(PREFIX + JSON.stringify({ k, d })); } catch (e) { /* nichts */ } };
  const PROPS = ["display", "position", "top", "left", "right", "bottom", "width", "height", "min-width", "min-height", "max-width", "margin", "padding",
    "color", "background-color", "font-family", "font-size", "font-weight", "font-style", "line-height", "letter-spacing", "text-align", "text-decoration",
    "border", "border-radius", "box-shadow", "opacity", "overflow", "flex-direction", "justify-content", "align-items", "gap", "z-index"];
  let mode = "off", sel = null, hoverEl = null, drag = null, raf = 0;
  const overrides = new Map();   // Element -> { prop: { old, oldPrio, val } }
  const texts = new Map();       // Element -> ursprünglicher Text
  let ov, hoverBox, selBox, label, handles = {};

  const inOverlay = (el) => !!(ov && el && (el === ov || ov.contains(el)));
  const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : String(s).replace(/[^\w-]/g, "\\$&");

  function cssPath(el) {
    if (el.id && document.querySelectorAll("#" + esc(el.id)).length === 1) return "#" + esc(el.id);
    const parts = [];
    for (let n = el; n && n.nodeType === 1 && n !== document.documentElement; n = n.parentElement) {
      if (n === document.body) { parts.unshift("body"); break; }
      if (n.id && document.querySelectorAll("#" + esc(n.id)).length === 1) { parts.unshift("#" + esc(n.id)); break; }
      let i = 1; for (let s = n.previousElementSibling; s; s = s.previousElementSibling) if (s.tagName === n.tagName) i++;
      parts.unshift(n.tagName.toLowerCase() + ":nth-of-type(" + i + ")");
    }
    return parts.join(" > ");
  }
  const find = (path) => { try { return document.querySelector(path); } catch (e) { return null; } };

  function ownText(el) {
    let t = ""; for (const c of el.childNodes) if (c.nodeType === 3) t += c.nodeValue;
    return t.replace(/\s+/g, " ").trim();
  }
  const generated = (c) => /^[_\-]?[a-zA-Z]*[_-]{1,2}[a-zA-Z0-9]{5,}$/.test(c) && /\d/.test(c) || /^(css|sc|jsx|svelte|astro)-[a-z0-9]+$/i.test(c);

  function sheets() { const o = []; for (const s of document.styleSheets) { try { if (s.href && o.length < 30) o.push(new URL(s.href).pathname); } catch (e) { /* nichts */ } } return o; }

  function classCounts(el) {      // wie viele Elemente der Seite jede Klasse tragen (gemeinsame Regeln wie .btn-lg betreffen mehrere)
    const o = {}; for (const c of el.classList) { try { o[c] = document.querySelectorAll("." + esc(c)).length; } catch (e) { o[c] = 1; } } return o;
  }

  function info(el) {
    const cs = getComputedStyle(el), r = el.getBoundingClientRect(), computed = {};
    for (const p of PROPS) computed[p] = cs.getPropertyValue(p);
    const attrs = {}; for (const a of el.attributes) if (!["class", "id", "style"].includes(a.name)) attrs[a.name] = a.value.slice(0, 120);
    const chain = []; for (let n = el.parentElement; n && chain.length < 4 && n !== document.documentElement; n = n.parentElement)
      chain.push({ tag: n.tagName.toLowerCase(), id: n.id || "", classes: [...n.classList] });
    const v = el.closest("[data-vds]");
    return { path: cssPath(el), tag: el.tagName.toLowerCase(), id: el.id || "", classes: [...el.classList],
      stableClasses: [...el.classList].filter((c) => !generated(c)), text: ownText(el).slice(0, 160), attrs, inline: el.getAttribute("style") || "",
      rect: { x: r.x, y: r.y, w: r.width, h: r.height }, computed, chain, children: el.children.length, vds: v ? v.getAttribute("data-vds") : "",
      html: el.outerHTML.slice(0, 400), overrides: overridesOf(el), sheets: sheets(), classCounts: classCounts(el) };
  }
  function overridesOf(el) { const m = overrides.get(el), o = {}; if (m) for (const k in m) o[k] = m[k].val; return o; }

  // --- Überschreibungen --------------------------------------------------------------------------
  function setOverride(el, prop, val) {
    let m = overrides.get(el); if (!m) overrides.set(el, m = {});
    if (!m[prop]) m[prop] = { old: el.style.getPropertyValue(prop), oldPrio: el.style.getPropertyPriority(prop), val: "" };
    if (val === "" || val === null) { const o = m[prop]; el.style.removeProperty(prop); if (o.old) el.style.setProperty(prop, o.old, o.oldPrio); delete m[prop]; if (!Object.keys(m).length) overrides.delete(el); return; }
    m[prop].val = val; el.style.setProperty(prop, val);
  }
  function revertAll() {
    for (const [el, m] of overrides) for (const p in m) { el.style.removeProperty(p); if (m[p].old) el.style.setProperty(p, m[p].old, m[p].oldPrio); }
    overrides.clear();
    for (const [el, t] of texts) el.textContent = t;
    texts.clear(); draw();
  }
  const emitChanged = (el) => send("changed", { path: cssPath(el), props: overridesOf(el), info: info(el) });

  // --- Overlay --------------------------------------------------------------------------------------
  function box(color, fill) { const d = document.createElement("div"); d.style.cssText = "position:fixed;pointer-events:none;box-sizing:border-box;border:1px solid " + color + ";background:" + fill + ";display:none;"; return d; }
  function build() {
    if (ov) return;
    ov = document.createElement("div"); ov.id = "__vds_overlay"; ov.style.cssText = "position:fixed;left:0;top:0;width:0;height:0;z-index:2147483647;";
    hoverBox = box("#00e5ff", "rgba(0,229,255,.12)"); selBox = box("#b44cff", "rgba(180,76,255,.08)"); selBox.style.borderWidth = "2px";
    label = document.createElement("div"); label.style.cssText = "position:fixed;pointer-events:none;background:#0c0f22;color:#dbe6ff;font:11px/1.4 monospace;padding:1px 6px;border-radius:4px;border:1px solid #00e5ff;display:none;white-space:nowrap;";
    ov.append(hoverBox, selBox, label);
    const dirs = { nw: [-1, -1, "nwse-resize"], n: [0, -1, "ns-resize"], ne: [1, -1, "nesw-resize"], e: [1, 0, "ew-resize"], se: [1, 1, "nwse-resize"], s: [0, 1, "ns-resize"], sw: [-1, 1, "nesw-resize"], w: [-1, 0, "ew-resize"] };
    for (const k in dirs) {
      const h = document.createElement("div"); h.dataset.h = k; h.style.cssText = "position:fixed;width:9px;height:9px;background:#fff;border:1px solid #b44cff;box-sizing:border-box;pointer-events:auto;display:none;cursor:" + dirs[k][2];
      h.__dir = dirs[k]; handles[k] = h; ov.append(h);
    }
    (document.body || document.documentElement).append(ov);
  }
  function place(b, r) { b.style.display = "block"; b.style.left = r.left + "px"; b.style.top = r.top + "px"; b.style.width = r.width + "px"; b.style.height = r.height + "px"; }
  const describe = (el) => el.tagName.toLowerCase() + (el.id ? "#" + el.id : "") + [...el.classList].slice(0, 3).map((c) => "." + c).join("");
  function draw() {
    if (!ov) return;
    if (mode === "off") { for (const b of [hoverBox, selBox, label, ...Object.values(handles)]) b.style.display = "none"; return; }
    if (hoverEl && hoverEl !== sel && document.contains(hoverEl)) { place(hoverBox, hoverEl.getBoundingClientRect()); } else hoverBox.style.display = "none";
    if (sel && document.contains(sel)) {
      const r = sel.getBoundingClientRect(); place(selBox, r);
      label.style.display = "block"; label.textContent = describe(sel) + "  " + Math.round(r.width) + "×" + Math.round(r.height);
      label.style.left = Math.max(0, r.left) + "px"; label.style.top = Math.max(0, r.top - 20) + "px";
      for (const k in handles) { const [hx, hy] = handles[k].__dir, h = handles[k]; h.style.display = mode === "edit" ? "block" : "none";
        h.style.left = (r.left + (hx + 1) * r.width / 2 - 4) + "px"; h.style.top = (r.top + (hy + 1) * r.height / 2 - 4) + "px"; }
    } else { selBox.style.display = "none"; label.style.display = "none"; for (const k in handles) handles[k].style.display = "none"; }
  }
  const loop = () => { draw(); raf = mode === "off" ? 0 : requestAnimationFrame(loop); };

  function select(el, quiet) { sel = el; draw(); if (!quiet && el) send("pick", info(el)); }

  // --- Ereignisse ---------------------------------------------------------------------------------------
  const target = (e) => { const t = e.target; return t && t.nodeType === 1 && !inOverlay(t) ? t : null; };
  function onMove(e) {
    if (mode === "off") return;
    if (drag) return dragMove(e);
    const t = target(e); if (t !== hoverEl) { hoverEl = t; draw(); if (t) send("hover", { tag: describe(t) }); }
  }
  function onClick(e) {
    if (mode === "off" || inOverlay(e.target)) return;
    e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation();
    if (drag) return;
    const t = target(e); if (t && !(texts.has(t) && t.isContentEditable)) select(t);
  }
  function onDown(e) {
    if (mode === "off") return;
    const h = e.target && e.target.dataset && e.target.dataset.h && inOverlay(e.target) ? e.target : null;
    if (!h && inOverlay(e.target)) return;
    if (t0(e) && t0(e).isContentEditable) return;
    e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation();
    if (mode !== "edit" || e.button !== 0) return;
    let el = sel;
    if (!h) { const t = target(e); if (!t) return; if (t !== sel) select(t); el = t; }
    if (!el) return;
    const cs = getComputedStyle(el);
    drag = { el, dir: h ? h.__dir : null, x: e.clientX, y: e.clientY, moved: false, w: parseFloat(cs.width) || 0, h: parseFloat(cs.height) || 0,
      l: parseFloat(cs.left) || 0, t: parseFloat(cs.top) || 0, pos: cs.position };
  }
  const t0 = (e) => (e.target && e.target.nodeType === 1) ? e.target : null;
  function dragMove(e) {
    const d = drag, dx = e.clientX - d.x, dy = e.clientY - d.y;
    if (!d.moved && Math.abs(dx) < 3 && Math.abs(dy) < 3) return;
    d.moved = true; e.preventDefault();
    const px = (n) => Math.round(n) + "px";
    if (d.dir) {
      const [hx, hy] = d.dir;
      if (hx) setOverride(d.el, "width", px(Math.max(4, d.w + hx * dx)));
      if (hy) setOverride(d.el, "height", px(Math.max(4, d.h + hy * dy)));
      if (hx < 0 || hy < 0) { if (d.pos === "static") setOverride(d.el, "position", "relative");
        if (hx < 0) setOverride(d.el, "left", px(d.l + dx)); if (hy < 0) setOverride(d.el, "top", px(d.t + dy)); }
    } else {
      if (d.pos === "static") setOverride(d.el, "position", "relative");
      setOverride(d.el, "left", px(d.l + dx)); setOverride(d.el, "top", px(d.t + dy));
    }
    draw();
  }
  function onUp(e) {
    if (mode === "off") return;
    if (!inOverlay(e.target) || drag) { if (!(t0(e) && t0(e).isContentEditable)) { e.preventDefault(); e.stopPropagation(); } }
    if (drag) { const d = drag; drag = null; if (d.moved) emitChanged(d.el); }
  }
  function onDbl(e) {
    if (mode !== "edit") return;
    const t = target(e); if (!t || t.children.length) return;
    e.preventDefault(); e.stopPropagation();
    if (!texts.has(t)) texts.set(t, t.textContent);
    const before = t.textContent;
    t.contentEditable = "plaintext-only"; t.focus();
    const done = () => { t.removeEventListener("blur", done); t.removeEventListener("keydown", key); t.contentEditable = "false"; t.removeAttribute("contenteditable");
      const now = t.textContent; if (now !== before) send("text", { path: cssPath(t), old: before, new: now, info: info(t) }); else texts.delete(t); draw(); };
    const key = (ev) => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); t.blur(); } if (ev.key === "Escape") { t.textContent = before; t.blur(); } ev.stopPropagation(); };
    t.addEventListener("blur", done); t.addEventListener("keydown", key);
    const rg = document.createRange(); rg.selectNodeContents(t); const s = getSelection(); s.removeAllRanges(); s.addRange(rg);
  }
  document.addEventListener("keydown", (e) => {          // Pfeiltasten verschieben das gewählte Element (Umschalt = 10 px)
    if (mode !== "edit" || !sel || sel.isContentEditable || !/^Arrow(Left|Right|Up|Down)$/.test(e.key) || e.ctrlKey || e.metaKey || e.altKey) return;
    e.preventDefault(); e.stopPropagation();
    const step = e.shiftKey ? 10 : 1, cs = getComputedStyle(sel);
    if (cs.position === "static") setOverride(sel, "position", "relative");
    const dx = e.key === "ArrowLeft" ? -step : e.key === "ArrowRight" ? step : 0, dy = e.key === "ArrowUp" ? -step : e.key === "ArrowDown" ? step : 0;
    const px = (n) => Math.round(n) + "px";
    if (dx) setOverride(sel, "left", px((parseFloat(getComputedStyle(sel).left) || 0) + dx));
    if (dy) setOverride(sel, "top", px((parseFloat(getComputedStyle(sel).top) || 0) + dy));
    draw(); emitChanged(sel);
  }, true);
  function setMode(m) {
    mode = m; build(); hoverEl = null; if (m === "off") { drag = null; }
    document.documentElement.style.cursor = m === "off" ? "" : (m === "pick" ? "crosshair" : "default");
    if (m !== "off" && !raf) raf = requestAnimationFrame(loop); draw();
  }
  for (const [ev, fn] of [["mousemove", onMove], ["click", onClick], ["mousedown", onDown], ["mouseup", onUp], ["dblclick", onDbl], ["pointerdown", (e) => { if (mode !== "off" && !inOverlay(e.target)) { e.stopPropagation(); } }],
    ["submit", (e) => { if (mode !== "off") e.preventDefault(); }]]) document.addEventListener(ev, fn, true);
  window.addEventListener("scroll", draw, true); window.addEventListener("resize", draw);

  window.__vds = {
    setMode, info, find,
    selectPath(p) { const el = find(p); if (el) select(el); return !!el; },
    selectRelative(kind) {
      if (!sel) return false; let n = null;
      if (kind === "parent") n = sel.parentElement; else if (kind === "child") n = sel.firstElementChild; else if (kind === "next") n = sel.nextElementSibling; else if (kind === "prev") n = sel.previousElementSibling;
      if (!n || n === document.documentElement || inOverlay(n)) return false; select(n); return true;
    },
    setStyle(p, prop, val) { const el = find(p); if (!el) return null; setOverride(el, prop, val); draw(); emitChanged(el); return info(el); },
    setText(p, t) { const el = find(p); if (!el || el.children.length) return false; const before = el.textContent; if (!texts.has(el)) texts.set(el, before);
      el.textContent = t; send("text", { path: cssPath(el), old: texts.get(el), new: t, info: info(el) }); draw(); return true; },
    revertAll, overrides: () => [...overrides.keys()].map((el) => ({ path: cssPath(el), props: overridesOf(el) })),
    selected: () => sel && document.contains(sel) ? info(sel) : null,
    restore(p) { const el = p && find(p); if (el) select(el, true); },
  };
  send("ready", { url: location.href, title: document.title });
})();
