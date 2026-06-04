"use strict";

// GrueRuntime — the Grue game engine.
// The compiled game script calls GrueRuntime.init(game) to start.
//
// Descriptor shape by milestone:
//   M1: meta, nodes, start
//   M2: + handlers, grammar, vocab
//   M3: + library loading, exits, connects
//   M4: + kinds, classes, node props
const GrueRuntime = (function () {

  let _out;
  let _tree;
  let _game;
  let _location; // canonical name of the room the player is currently in

  // ── Output ──────────────────────────────────────────────────────────────────

  function say(text) {
    const p = document.createElement("p");
    p.textContent = text;
    _out.appendChild(p);
  }

  function heading(text) {
    const h1 = document.createElement("h1");
    h1.textContent = text;
    _out.appendChild(h1);
  }

  function rule() {
    _out.appendChild(document.createElement("hr"));
  }

  function echo(text) {
    const p = document.createElement("p");
    p.textContent = "> " + text;
    _out.appendChild(p);
  }

  // ── Input parsing ────────────────────────────────────────────────────────────

  function tokenize(input) {
    return input.trim().toLowerCase().split(/\s+/).filter(t => t.length > 0);
  }

  function matchParam(type, tokens, pos) {
    if (type === "number") {
      const n = Number(tokens[pos]);
      return (tokens[pos] !== undefined && !isNaN(n))
        ? { value: n, consumed: 1 } : null;
    }
    if (type === "string") {
      return tokens[pos] !== undefined
        ? { value: tokens[pos], consumed: 1 } : null;
    }
    const vocab    = _game.vocab || {};
    const nodes    = _game.nodes || {};
    const typeLower = type.toLowerCase();
    for (let len = tokens.length - pos; len >= 1; len--) {
      const phrase    = tokens.slice(pos, pos + len).join(" ");
      const canonical = vocab[phrase];
      if (canonical) {
        const node = nodes[canonical];
        if (node && (typeLower === "object" || node.class.toLowerCase() === typeLower)) {
          return { value: canonical, consumed: len };
        }
      }
    }
    return null;
  }

  function walkTrie(node, tokens, pos, args) {
    if (pos === tokens.length) {
      return node.sigKey ? { sigKey: node.sigKey, args } : null;
    }
    const word = tokens[pos];
    if (node.keywords && node.keywords[word]) {
      const r = walkTrie(node.keywords[word], tokens, pos + 1, args);
      if (r) return r;
    }
    for (const edge of (node.params || [])) {
      const m = matchParam(edge.type, tokens, pos);
      if (m) {
        const r = walkTrie(edge.next, tokens, pos + m.consumed, [...args, m.value]);
        if (r) return r;
      }
    }
    return null;
  }

  function parseInput(input) {
    const g = _game.grammar;
    if (!g) return null;
    return walkTrie(g, tokenize(input), 0, []);
  }

  // ── Dispatch ─────────────────────────────────────────────────────────────────

  function describeLocation() {
    const room = _game.nodes && _game.nodes[_location];
    if (room && room.desc) say(room.desc);
  }

  function dispatch(sigKey, args) {
    const chain = (_game.handlers || {})[sigKey];
    if (!chain || chain.length === 0) {
      say("You can't do that.");
      return;
    }
    for (const h of chain) h.fn(...args);
  }

  const _builtins = {
    "look": () => describeLocation()
  };

  // ── Turn loop ────────────────────────────────────────────────────────────────

  function handleInput(raw) {
    const input = raw.trim();
    if (!input) return;
    echo(input);
    const parsed = parseInput(input);
    if (parsed) { dispatch(parsed.sigKey, parsed.args); return; }
    const key = tokenize(input).join(" ");
    if (_builtins[key]) { _builtins[key](); return; }
    say("You don't know how to do that.");
  }

  // ── Tree / inspector helpers ─────────────────────────────────────────────────

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // link — emits a clickable <a> using data attributes.
  // A single delegated listener on _tree handles all clicks (no inline JS,
  // so object names with quotes or special characters never break the HTML).
  function link(label, name, kind) {
    return `<a href="#" class="dl" data-name="${esc(name)}" data-kind="${esc(kind)}">${esc(label)}</a>`;
  }

  // ── Detail panel ─────────────────────────────────────────────────────────────

  function showDetail(name, kind) {
    const panel = document.getElementById("tree-detail");
    if (!panel) return;
    panel.innerHTML = buildDetail(name, kind);
  }

  function buildDetail(name, kind) {
    if (kind === "node")  return detailNode(name);
    if (kind === "class") return detailClass(name);
    if (kind === "kind")  return detailKind(name);
    return "";
  }

  function detailNode(name) {
    const node = (_game.nodes || {})[name];
    if (!node) return `<em>Unknown node: ${esc(name)}</em>`;

    const cls     = (_game.classes || {})[node.class] || {};
    const vocab   = _game.vocab || {};
    const nodes   = _game.nodes || {};

    // All surface forms registered in the vocab pointing to this node.
    const vocabNames = Object.entries(vocab)
      .filter(([, v]) => v === name)
      .map(([k]) => k);

    // Declared aliases from source — may differ from vocab if another node
    // claimed the same name (last-declaration wins in the vocab builder).
    const declaredAliases = node.aliases || [];

    let h = `<h3>${esc(name)}</h3>`;
    h += `<table>`;
    h += row("class",    link(node.class, node.class, "class"));
    if (node.location)  h += row("location", link(node.location, node.location, "node"));
    if (node.desc)      h += row("desc",     `<em>${esc(node.desc.replace(/\n/g," "))}</em>`);
    h += `</table>`;

    // Names section — canonical + declared aliases (bold = reachable in vocab,
    // red = declared but shadowed by another object) + word-level suggestions
    // extracted from multi-word names (grey = not yet registered as aliases).
    const allDeclared = [name, ...declaredAliases];
    let namesCells = allDeclared.map(n => {
      const inVocab = vocabNames.some(v => v.toLowerCase() === n.toLowerCase());
      if (inVocab) return `<b>${esc(n)}</b>`;
      const owner = vocab[n] || vocab[n.toLowerCase()];
      const ownerLabel = owner && owner !== name
        ? ` <span style="color:#c00">&#9888; shadowed by ${link(owner, owner, "node")}</span>`
        : ` <span style="color:#c00">&#9888; not in vocab</span>`;
      return `<span style="color:#888">${esc(n)}</span>${ownerLabel}`;
    });

    // Word-level suggestions: individual words from the canonical name that
    // are not already declared as aliases and not registered in the vocab.
    // Shown greyed — the author can add them explicitly if desired.
    const stopWords = new Set(["a","an","the","of","in","on","at","to","by","for"]);

    // Build a word → Set<canonicalName> index across ALL nodes so we can detect
    // clashes between objects that share a word but neither has it as an alias.
    const wordIndex = {};
    for (const [n, nd] of Object.entries(_game.nodes || {})) {
      const forms = [n, ...(nd.aliases || [])];
      for (const form of forms) {
        for (const w of form.toLowerCase().split(/\s+/)) {
          if (w.length > 1 && !stopWords.has(w)) {
            if (!wordIndex[w]) wordIndex[w] = new Set();
            wordIndex[w].add(n);
          }
        }
      }
    }

    const wordSuggestions = name.split(/\s+/)
      .filter(w => w.length > 1 && !stopWords.has(w.toLowerCase()))
      .filter(w => !allDeclared.some(d => d.toLowerCase() === w.toLowerCase()))
      .filter(w => !vocabNames.some(v => v.toLowerCase() === w.toLowerCase()));

    wordSuggestions.forEach(w => {
      const clashNodes = [...(wordIndex[w.toLowerCase()] || new Set())]
        .filter(n => n !== name);
      const clashNote = clashNodes.length
        ? ` <span style="color:#c66;font-size:0.8em">&#9888; not unique (${clashNodes.map(n => link(n, n, "node")).join(", ")})</span>`
        : "";
      namesCells.push(`<span style="color:#bbb" title="not registered as alias">${esc(w)}</span>${clashNote}`);
    });

    h += `<h4>Names</h4><p>${namesCells.join(" &nbsp;&bull;&nbsp; ")}</p>`;

    // Exits — dedicated section for Room nodes
    if (node.class === "Room") {
      const exits = node.exits || {};
      const dirs  = Object.keys(exits);
      if (dirs.length) {
        h += `<h4>Exits</h4><table>`;
        dirs.forEach(dir => {
          const dest     = exits[dir];
          const destNode = (_game.nodes || {})[dest];
          if (destNode && destNode.class === "Door") {
            const other = (destNode.connects || []).filter(r => r !== name);
            h += row(dir, `${link(dest, dest, "node")} (door)${other.length ? " &rarr; " + other.map(r => link(r, r, "node")).join(", ") : ""}`);
          } else {
            h += row(dir, link(dest, dest, "node"));
          }
        });
        h += `</table>`;
      }
    }

    // Connections — dedicated section for Door nodes
    if (node.class === "Door") {
      const connects = node.connects || [];
      if (connects.length) {
        h += `<h4>Connects</h4><p>`;
        h += connects.map(r => link(r, r, "node")).join(" &#8596; ");
        h += `</p>`;
      }
    }

    // Props — everything else (skip compass directions and "leads to" already shown above)
    const SKIP = new Set(["north","south","east","west","up","down","in","out",
                          "northeast","northwest","southeast","southwest","leads to"]);
    const props = node.props || {};
    const propKeys = Object.keys(props).filter(k =>
      node.class === "Room" ? SKIP.has(k) === false : k !== "leads to"
    );
    if (propKeys.length) {
      h += `<h4>Properties</h4><table>`;
      for (const k of propKeys) {
        const v = props[k];
        const display = Array.isArray(v)
          ? v.map(x => maybeLink(x)).join(", ")
          : maybeLink(v);
        h += row(esc(k), display);
      }
      h += `</table>`;
    }

    // Handlers on this node
    const handlers = (_game.handlers || {});
    const own = Object.entries(handlers)
      .filter(([, chain]) => chain.some(h => h.owner === name))
      .map(([sig]) => sig);
    if (own.length) {
      h += `<h4>Handlers on this instance</h4><ul>`;
      own.forEach(s => { h += `<li class="handler">${esc(s)}</li>`; });
      h += `</ul>`;
    }

    // Inherited from class
    if (cls.handlers && cls.handlers.length) {
      h += `<h4>Inherited from ${link(node.class, node.class, "class")}</h4><ul>`;
      cls.handlers.forEach(s => { h += `<li class="handler">${esc(s)}</li>`; });
      h += `</ul>`;
    }

    return h;
  }

  function detailClass(name) {
    const cls = (_game.classes || {})[name];
    if (!cls) return `<em>Unknown class: ${esc(name)}</em>`;

    // instances of this class
    const instances = Object.entries(_game.nodes || {})
      .filter(([, n]) => n.class === name)
      .map(([n]) => n);

    let h = `<h3>${esc(name)}</h3><table>`;
    h += row("type", "class");
    if (cls.parent) h += row("extends", link(cls.parent, cls.parent, "class"));
    if (cls.isLibrary) h += row("", `<span class="lib">library</span>`);
    h += `</table>`;

    const propKeys = Object.keys(cls.props || {});
    if (propKeys.length) {
      h += `<h4>Default properties</h4><table>`;
      for (const k of propKeys) {
        h += row(esc(k), esc(String(cls.props[k])));
      }
      h += `</table>`;
    }

    if (cls.handlers && cls.handlers.length) {
      h += `<h4>Handlers</h4><ul>`;
      cls.handlers.forEach(s => { h += `<li class="handler">${esc(s)}</li>`; });
      h += `</ul>`;
    }

    if (instances.length) {
      h += `<h4>Instances</h4><ul>`;
      instances.forEach(n => { h += `<li>${link(n, n, "node")}</li>`; });
      h += `</ul>`;
    }

    return h;
  }

  function detailKind(name) {
    const kind = (_game.kinds || []).find(k => k.name === name);
    if (!kind) return `<em>Unknown kind: ${esc(name)}</em>`;

    let h = `<h3>${esc(name)}</h3><table>`;
    h += row("type", "kind");
    h += `</table><h4>Values</h4><ul>`;
    kind.values.forEach((v, i) => {
      const def = i === kind.defaultIdx ? " <em>(default)</em>" : "";
      h += `<li>${esc(v)}${def}</li>`;
    });
    h += `</ul>`;

    // nodes/classes that carry this kind
    const carriers = [];
    for (const [n, node] of Object.entries(_game.nodes || {})) {
      if ((node.props || {})[name] !== undefined) carriers.push(link(n, n, "node"));
    }
    for (const [c, cls] of Object.entries(_game.classes || {})) {
      if ((cls.props || {})[name] !== undefined) carriers.push(link(c, c, "class"));
    }
    if (carriers.length) {
      h += `<h4>Used by</h4><p>${carriers.join(", ")}</p>`;
    }
    return h;
  }

  // maybeLink: if the value is a known node name, make it a link.
  function maybeLink(v) {
    if (v === null) return "<em>unset</em>";
    const s = String(v);
    return (_game.nodes || {})[s] ? link(s, s, "node") : esc(s);
  }

  function row(label, value) {
    if (!label) return `<tr><td></td><td>${value}</td></tr>`;
    return `<tr><td style="color:#888;padding-right:1em">${label}</td><td>${value}</td></tr>`;
  }

  // ── Map section ──────────────────────────────────────────────────────────────

  function renderMap(nodes) {
    const rooms = Object.entries(nodes).filter(([, n]) => n.class === "Room");
    const doors = Object.entries(nodes).filter(([, n]) => n.class === "Door");
    if (rooms.length === 0 && doors.length === 0) return "";

    let html = `<h3>Map</h3><ul style="list-style:none;padding:0">`;
    for (const [name, node] of rooms) {
      const isHere  = name === _location;
      const style   = isHere ? " style='font-weight:bold;background:#ffe;padding:1px 3px'" : "";
      html += `<li${style}>&#9679; <span class="cls">Room</span> ${link(name, name, "node")}`;
      if (node.desc) {
        const short = node.desc.replace(/\n/g, " ");
        html += ` <span class="desc">"${esc(short.length > 55 ? short.slice(0,55)+"…" : short)}"</span>`;
      }
      const exits = node.exits || {};
      if (Object.keys(exits).length) {
        html += `<ul style="list-style:none;margin:2px 0 4px 1.5em;padding:0">`;
        for (const [dir, dest] of Object.entries(exits)) {
          const destNode = nodes[dest];
          if (destNode && destNode.class === "Door") {
            const other = (destNode.connects || []).filter(r => r !== name);
            html += `<li>${dir} &rarr; ${link(dest, dest, "node")} (door)`;
            if (other.length) html += ` &rarr; ${other.map(r => link(r, r, "node")).join(", ")}`;
            html += `</li>`;
          } else {
            html += `<li>${dir} &rarr; ${link(dest, dest, "node")}</li>`;
          }
        }
        html += `</ul>`;
      }
      html += `</li>`;
    }
    html += `</ul>`;

    if (doors.length) {
      html += `<ul style="list-style:none;padding:0">`;
      for (const [name, node] of doors) {
        const connects = node.connects || [];
        html += `<li>&#9670; <span class="cls">Door</span> ${link(name, name, "node")}`;
        if (node.desc) html += ` <span class="desc">"${esc(node.desc)}"</span>`;
        if (connects.length) html += ` &nbsp; ${connects.map(r => link(r,r,"node")).join(" &#8596; ")}`;
        html += `</li>`;
      }
      html += `</ul>`;
    }
    return html;
  }

  // ── Main tree render ─────────────────────────────────────────────────────────

  function renderTree() {
    const nodes    = _game.nodes    || {};
    const handlers = _game.handlers || {};
    const meta     = _game.meta     || {};

    // owner → [sigKeys] index
    const ownerH = {};
    for (const [sig, chain] of Object.entries(handlers)) {
      for (const h of chain) {
        const o = h.owner || "__global__";
        (ownerH[o] = ownerH[o] || []).push(sig);
      }
    }

    const css = `
      <style>
        #tree-panel { display:flex; gap:1.5em; font-family:monospace; font-size:13px; }
        #tree-list  { flex:1; min-width:0; overflow-y:auto; }
        #tree-detail{ width:360px; border-left:1px solid #ccc; padding-left:1em;
                      overflow-y:auto; max-height:80vh; }
        #tree-panel h3 { font-size:1em; border-bottom:1px solid #ccc;
                         margin:0.8em 0 0.3em; }
        #tree-panel h4 { font-size:0.9em; margin:0.6em 0 0.2em; color:#444; }
        #tree-panel table { border-collapse:collapse; }
        #tree-panel td   { padding:1px 0; vertical-align:top; }
        .cls     { color:#06c; }
        .handler { color:#080; }
        .internal{ color:#a60; }
        .lib     { color:#aaa; font-size:0.85em; }
        .desc    { color:#888; font-style:italic; }
        .alias   { color:#888; font-size:0.85em; }
        .here    { font-weight:bold; background:#ffe; padding:1px 3px; }
        .sig     { color:#080; font-size:0.85em; margin-right:4px; }
      </style>`;

    let list = "";

    // Kinds
    const kinds = _game.kinds || [];
    if (kinds.length) {
      list += `<h3>Kinds</h3><table>`;
      for (const k of kinds) {
        const vals = k.values.map((v, i) =>
          i === k.defaultIdx ? `<u>${esc(v)}</u>` : esc(v)
        ).join("  ");
        list += `<tr><td style="padding-right:1em">${link(k.name, k.name, "kind")}</td><td>${vals}</td></tr>`;
      }
      list += `</table>`;
    }

    // Classes
    const classes = _game.classes || {};
    const ownClasses = Object.entries(classes).filter(([, c]) => !c.isLibrary);
    if (ownClasses.length) {
      list += `<h3>Classes</h3><table>`;
      for (const [name, cls] of ownClasses) {
        const parent = cls.parent ? ` <span class="cls">extends ${esc(cls.parent)}</span>` : "";
        const sigs   = (cls.handlers || []).map(s => `<span class="sig">${esc(s)}</span>`).join(" ");
        list += `<tr>
          <td style="padding-right:1em">${link(name, name, "class")}${parent}</td>
          <td>${sigs}</td></tr>`;
      }
      list += `</table>`;
    }

    // Vocab reverse index: canonical → [all surface forms]
    const vocabRev = {};
    for (const [form, canonical] of Object.entries(_game.vocab || {})) {
      (vocabRev[canonical] = vocabRev[canonical] || []).push(form);
    }

    // Word → Set<canonical> index to flag shared words in the world table
    const stop = new Set(["a","an","the","of","in","on","at","to","by","for"]);
    const wordIdx = {};
    for (const [n, nd] of Object.entries(nodes)) {
      for (const form of [n, ...(nd.aliases || [])]) {
        for (const w of form.toLowerCase().split(/\s+/)) {
          if (w.length > 1 && !stop.has(w)) {
            if (!wordIdx[w]) wordIdx[w] = new Set();
            wordIdx[w].add(n);
          }
        }
      }
    }
    const ambiguous = new Set();
    for (const set of Object.values(wordIdx)) {
      if (set.size > 1) set.forEach(n => ambiguous.add(n));
    }

    // World nodes
    list += `<h3>World</h3><table>`;
    for (const [name, node] of Object.entries(nodes)) {
      const isHere    = name === _location;
      const rc        = isHere ? " class='here'" : "";
      const loc       = node.location ? ` <span style="color:#080;font-size:0.9em">&rarr; ${esc(node.location)}</span>` : "";
      const desc      = node.desc
        ? `<span class="desc"> "${esc(node.desc.replace(/\n/g," ").slice(0,45))}${node.desc.length>45?"…":""}"</span>`
        : "";
      const sigs      = (ownerH[name] || []).map(s => `<span class="sig">${esc(s)}</span>`).join(" ");
      const nameLower = name.toLowerCase();
      const altNames  = (vocabRev[name] || []).filter(n => n.toLowerCase() !== nameLower);
      const aliasBit  = altNames.length
        ? ` <span class="alias">(${altNames.map(esc).join(", ")})</span>`
        : "";
      const ambigBit  = ambiguous.has(name)
        ? ` <span style="color:#c66;font-size:0.8em" title="shares words with other objects">&#9888;</span>`
        : "";
      list += `<tr${rc}>
        <td style="padding-right:6px"><span class="cls">${esc(node.class)}</span></td>
        <td style="padding-right:8px">${link(name, name, "node")}${aliasBit}${ambigBit}${loc}</td>
        <td>${desc}</td>
        <td>${sigs}</td></tr>`;
    }
    list += `</table>`;

    // Global handlers
    const global = ownerH["__global__"] || [];
    if (global.length) {
      list += `<h3>Global handlers</h3>`;
      list += global.map(s => `<span class="sig">${esc(s)}</span>`).join(" ");
    }

    // Map
    list += renderMap(nodes);

    // Vocab
    const vocab = _game.vocab || {};
    list += `<h3>Vocab</h3><p style="color:#888;font-size:0.9em">`;
    list += Object.keys(vocab).sort().map(k =>
      k === vocab[k] ? esc(k) : `${esc(k)} &rarr; ${esc(vocab[k])}`
    ).join(" &bull; ");
    list += `</p>`;

    _tree.innerHTML = `${css}
      <div id="tree-panel">
        <div id="tree-list">${list}</div>
        <div id="tree-detail"><em>Click any item to inspect it.</em></div>
      </div>`;

    // Delegated click handler — one listener covers every .dl link in the panel.
    _tree.addEventListener("click", e => {
      const a = e.target.closest(".dl");
      if (!a) return;
      e.preventDefault();
      showDetail(a.dataset.name, a.dataset.kind);
    });
  }

  // ── Public API ───────────────────────────────────────────────────────────────

  return {
    say,

    init(game) {
      _game     = game;
      _out      = document.getElementById("output");
      _tree     = document.getElementById("tree");
      _location = game.start;

      window.say = say;

      if (game.meta && game.meta.title) {
        heading(game.meta.title);
        say("by " + game.meta.author);
        rule();
      }
      describeLocation();

      const input   = document.getElementById("cmd");
      const goBtn   = document.getElementById("go");
      const treeBtn = document.getElementById("tree-btn");

      if (input && goBtn) {
        goBtn.addEventListener("click", () => {
          handleInput(input.value);
          input.value = "";
          input.focus();
        });
        input.addEventListener("keydown", e => {
          if (e.key === "Enter") {
            handleInput(input.value);
            input.value = "";
          }
        });
      }

      if (treeBtn && _tree) {
        treeBtn.addEventListener("click", () => {
          const treeVisible = _tree.style.display !== "none";
          if (treeVisible) {
            _tree.style.display = "none";
            _out.style.display  = "";
            treeBtn.textContent = "Tree";
          } else {
            renderTree();
            _tree.style.display = "";
            _out.style.display  = "none";
            treeBtn.textContent = "Game";
          }
          input && input.focus();
        });
      }
    }
  };

}());
