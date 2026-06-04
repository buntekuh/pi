"use strict";

// GrueRuntime — the Grue game engine.
// The compiled game script calls GrueRuntime.init(game) to start.
//
// Descriptor shape by milestone:
//   M1: meta, nodes, start
//   M2: + handlers, grammar, vocab
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

  // matchParam attempts to consume one typed parameter slot from tokens[pos].
  // Returns { value, consumed } on success, null on failure.
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
    // Object or class name — greedy multi-word vocab lookup.
    // Type comparison is case-insensitive: the library uses lowercase "object"
    // but class names in the descriptor are capitalised ("Object", "Room", …).
    const vocab = _game.vocab || {};
    const nodes = _game.nodes || {};
    const typeLower = type.toLowerCase();
    for (let len = tokens.length - pos; len >= 1; len--) {
      const phrase = tokens.slice(pos, pos + len).join(" ");
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

  // walkTrie recursively matches tokens against the pattern trie.
  // Returns { sigKey, args } on a complete match, null otherwise.
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
    for (const h of chain) {
      h.fn(...args);
    }
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

  // ── Tree view ────────────────────────────────────────────────────────────────

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  // renderTree rebuilds the tree panel from current runtime state.
  // In later milestones this will reflect live property values and locations.
  function renderTree() {
    const nodes  = _game.nodes   || {};
    const handlers = _game.handlers || {};
    const meta   = _game.meta    || {};

    // Group handler sigKeys by owner for display alongside each node.
    const ownerHandlers = {};
    for (const [sigKey, chain] of Object.entries(handlers)) {
      for (const h of chain) {
        const owner = h.owner || "__global__";
        if (!ownerHandlers[owner]) ownerHandlers[owner] = [];
        ownerHandlers[owner].push(sigKey);
      }
    }

    let html = `<style>
      #tree { font-family: monospace; font-size: 13px; padding: 0.5em 1em; }
      #tree table { border-collapse: collapse; width: 100%; }
      #tree td { padding: 2px 10px 2px 0; vertical-align: top; }
      #tree .cls  { color: #06c; }
      #tree .loc  { color: #080; font-size: 0.9em; }
      #tree .desc { color: #888; font-style: italic; }
      #tree .sig  { color: #080; font-size: 0.85em; display: inline-block; margin-right: 4px; }
      #tree .isig { color: #a60; font-size: 0.85em; display: inline-block; margin-right: 4px; }
      #tree .here { font-weight: bold; background: #ffe; }
      #tree h3    { font-size: 1em; border-bottom: 1px solid #ccc; margin: 0.8em 0 0.3em; }
    </style>`;

    if (meta.title) {
      html += `<p><b>"${esc(meta.title)}"</b> by ${esc(meta.author)}</p>`;
    }

    // Nodes
    html += `<h3>World</h3><table>`;
    for (const [name, node] of Object.entries(nodes)) {
      const isHere = name === _location;
      const rowClass = isHere ? " class='here'" : "";
      const loc = node.location ? `<span class='loc'> &#8594; ${esc(node.location)}</span>` : "";
      const desc = node.desc
        ? `<span class='desc'>"${esc(node.desc.length > 50 ? node.desc.slice(0, 50) + "…" : node.desc)}"</span>`
        : "";
      const sigs = (ownerHandlers[name] || [])
        .map(s => `<span class='sig'>${esc(s)}</span>`)
        .join("");
      html += `<tr${rowClass}>
        <td class='cls'>${esc(node.class)}</td>
        <td><b>${esc(name)}</b>${loc}</td>
        <td>${desc}</td>
        <td>${sigs}</td>
      </tr>`;
    }
    html += `</table>`;

    // Global handlers
    const global = ownerHandlers["__global__"] || [];
    if (global.length) {
      html += `<h3>Global handlers</h3>`;
      html += global.map(s => `<span class='sig'>${esc(s)}</span>`).join(" ");
    }

    // Vocab
    const vocab = _game.vocab || {};
    html += `<h3>Vocab</h3><p style="color:#888;font-size:0.9em">`;
    html += Object.keys(vocab).sort().map(k =>
      k === vocab[k] ? esc(k) : `${esc(k)} &#8594; ${esc(vocab[k])}`
    ).join(" &nbsp;&bull;&nbsp; ");
    html += `</p>`;

    _tree.innerHTML = html;
  }

  // ── Public API ───────────────────────────────────────────────────────────────

  return {
    say,

    init(game) {
      _game     = game;
      _out      = document.getElementById("output");
      _tree     = document.getElementById("tree");
      _location = game.start;

      // Expose the game-facing API as globals so compiled handler functions
      // can call say(...), and later fail(...), succeed(...), etc.
      window.say = say;

      // Title block
      if (game.meta && game.meta.title) {
        heading(game.meta.title);
        say("by " + game.meta.author);
        rule();
      }

      // Starting room description
      describeLocation();

      // Wire up the command input
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

      // Tree toggle
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
