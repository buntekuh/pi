"use strict";

// GrueRuntime — the Grue game engine.
// The compiled game script calls GrueRuntime.init(game) to start.
//
// Descriptor shape by milestone:
//   M1: meta, nodes, start
//   M2: + handlers, grammar, vocab
const GrueRuntime = (function () {

  let _out;
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
    const vocab = _game.vocab || {};
    const nodes = _game.nodes || {};
    for (let len = tokens.length - pos; len >= 1; len--) {
      const phrase = tokens.slice(pos, pos + len).join(" ");
      const canonical = vocab[phrase];
      if (canonical) {
        const node = nodes[canonical];
        if (node && (type === "Object" || node.class === type)) {
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
    // Keyword edge
    const word = tokens[pos];
    if (node.keywords && node.keywords[word]) {
      const r = walkTrie(node.keywords[word], tokens, pos + 1, args);
      if (r) return r;
    }
    // Param edges
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

  // describeLocation prints the current room's description.
  // Used by the built-in look fallback and on room entry (M3).
  function describeLocation() {
    const room = _game.nodes && _game.nodes[_location];
    if (room && room.desc) say(room.desc);
  }

  // dispatch fires the handler chain for sigKey with the resolved args.
  // In M2, all handlers in the chain fire unconditionally.
  // Scope filtering (room-local, class-specific) is added in M3+.
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

  // _builtins are commands recognised by the runtime when the grammar trie
  // has no entry for them — i.e. the game doesn't define an on-handler.
  // A game-defined handler always takes precedence (grammar is checked first).
  const _builtins = {
    "look": () => describeLocation()
  };

  // ── Turn loop ────────────────────────────────────────────────────────────────

  function handleInput(raw) {
    const input = raw.trim();
    if (!input) return;
    echo(input);

    // Grammar-defined commands take priority.
    const parsed = parseInput(input);
    if (parsed) {
      dispatch(parsed.sigKey, parsed.args);
      return;
    }

    // Fall back to built-in commands.
    const key = tokenize(input).join(" ");
    if (_builtins[key]) { _builtins[key](); return; }

    say("You don't know how to do that.");
  }

  // ── Public API ───────────────────────────────────────────────────────────────

  return {
    say,

    init(game) {
      _game = game;
      _out  = document.getElementById("output");
      _location = game.start;

      // Title block
      if (game.meta && game.meta.title) {
        heading(game.meta.title);
        say("by " + game.meta.author);
        rule();
      }

      // Starting room description
      describeLocation();

      // Wire up the input box
      const input = document.getElementById("cmd");
      const go    = document.getElementById("go");
      if (input && go) {
        go.addEventListener("click", () => {
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
    }
  };

}());
