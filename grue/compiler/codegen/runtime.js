"use strict";

// GrueRuntime — the Grue game engine.
// The compiled game script calls GrueRuntime.init(game) to start.
//
// Descriptor shape by milestone:
//   M1: meta, nodes, start
//   M2: + handlers, grammar, vocab
//   M3: + library loading, exits, connects
//   M4: + kinds, classes, node props
//   M9: + location on nodes (containment model)
//   M11: + movement — exit lookup, player relocation, room description
const GrueRuntime = (function () {

  let _out;
  let _tree;
  let _game;
  let _location; // canonical name of the room the player is currently in
  let _muted = false;
  let _currentPara = null;
  let _pendingDirection = null; // set by directions(); applied to input field after each turn

  // ── Output ──────────────────────────────────────────────────────────────────

  // Seal the current paragraph. The <p>'s browser margin provides the
  // paragraph break before the next turn's output.
  function _flushPara() {
    _currentPara = null;
  }

  function say(text, cls) {
    if (_muted) return;
    if (cls || !_currentPara) {
      _flushPara();
      _currentPara = document.createElement("p");
      _currentPara.className = cls || "text";
      _out.appendChild(_currentPara);
    } else {
      _currentPara.insertAdjacentHTML("beforeend", "<br>");
    }
    _currentPara.insertAdjacentHTML("beforeend", text);
    if (cls) _flushPara();
  }

  function heading(text) {
    if (_muted) return;
    _flushPara();
    const h1 = document.createElement("h1");
    h1.textContent = text;
    _out.appendChild(h1);
  }

  function rule() {
    if (_muted) return;
    _flushPara();
    _out.appendChild(document.createElement("hr"));
  }

  function directions(text) {
    _pendingDirection = text;
  }

  function echo(text) {
    if (_muted) return;
    const p = document.createElement("p");
    p.textContent = "> " + text;
    p.dataset.echo = "1";
    _out.appendChild(p);
  }

  // ── World-state helpers ──────────────────────────────────────────────────────

  // _worldState holds mutable world-level property values (score, turn, kind
  // variables declared at world scope). Initialised lazily on first write.
  const _worldState = {};

  // _nodeOf returns the live node object for a name, or null.
  function _nodeOf(nameOrRef) {
    if (nameOrRef === null || nameOrRef === undefined) return null;
    return (_game.nodes || {})[nameOrRef] || null;
  }

  // _prop(node, key) reads a property from a named node, falling back to the
  // class default then to parent class defaults. Key may be a number (array
  // index) — it is coerced to a string for the lookup.
  function _prop(nameOrRef, key) {
    const k = String(key);
    const node = _nodeOf(nameOrRef);
    if (node) {
      if (k === "location") return node.location ?? null;
      if (k === "desc")     return node.desc     ?? null;
      if (node.props && k in node.props) return node.props[k];
      // Walk class hierarchy for defaults.
      let clsName = node.class;
      while (clsName) {
        const cls = (_game.classes || {})[clsName];
        if (!cls) break;
        if (cls.props && k in cls.props) return cls.props[k];
        clsName = cls.parent;
      }
    }
    // World-level property fallback.
    if (k in _worldState) return _worldState[k];
    return null;
  }

  // _setProp(node, key, value) writes a property on a named node.
  function _setProp(nameOrRef, key, value) {
    const k = String(key);
    const node = _nodeOf(nameOrRef);
    if (!node) return;
    if (k === "location") {
      node.location = value;
      if (nameOrRef === "player") _location = value;
      return;
    }
    if (!node.props) node.props = {};
    node.props[k] = value;
  }

  // _move(item, dest) relocates a node to a new parent.
  function _move(item, dest) {
    const node = _nodeOf(item);
    if (node) node.location = dest;
  }

  // _through(door, fromRoom) returns the room on the far side of a door —
  // the entry in door.connects that is not fromRoom.
  function _through(door, fromRoom) {
    const n = _nodeOf(door);
    if (!n) return null;
    const cs = n.connects || [];
    return cs.find(r => r !== fromRoom) ?? null;
  }

  // _newNode / _freeNode — runtime allocation for var Class l declarations.
  // The name is a unique string; the node lives in _game.nodes like any other.
  let _varSeq = 0;
  function _newNode(className) {
    const name = "__var_" + (++_varSeq);
    (_game.nodes || (_game.nodes = {}))[name] = { class: className, props: {} };
    return name;
  }
  // _freeNode deletes a node only if no persistent node still references it
  // by name — either as a location or as a property value. This lets node vars
  // survive handler return when they have been stored in a world object.
  function _freeNode(name) {
    const nodes = _game.nodes || {};
    for (const node of Object.values(nodes)) {
      if (node.location === name) return;
      if (Object.values(node.props || {}).includes(name)) return;
    }
    delete nodes[name];
  }

  // _inScope(name) — true when the player can currently perceive / refer to name.
  // An item is in scope if its location chain transitively reaches the current
  // room or the player's inventory. Top-level nodes (rooms, etc.) with no
  // location are always in scope.
  function _inScope(name) {
    const nodes = _game.nodes || {};
    const node  = nodes[name];
    if (!node) return false;
    let loc = node.location;
    if (!loc) return true; // top-level (rooms) — always visible
    while (loc) {
      if (loc === _location || loc === "player") return true;
      loc = (nodes[loc] || {}).location;
    }
    return false;
  }

  // _get / _set access world-level (root) properties by name.
  function _get(key) {
    if (key in _worldState) return _worldState[key];
    // Fall back to root node props emitted by the compiler.
    const root = (_game.nodes || {})["world"];
    if (root && root.props && key in root.props) return root.props[key];
    return null;
  }
  function _set(key, value) {
    _worldState[key] = value;
  }

  // _kindOrd(value) returns the ordinal (integer index) of a kind value name.
  // Used for ordering comparisons such as peter.wet < damp.
  let _kindOrdCache = null;
  function _kindOrd(v) {
    if (!_kindOrdCache) {
      _kindOrdCache = {};
      for (const k of (_game.kinds || [])) {
        k.values.forEach((val, i) => { _kindOrdCache[val] = i; });
      }
    }
    return _kindOrdCache[v] ?? 0;
  }

  // _isset(v) is Grue's set/unset test — only null (unset) is false.
  function _isset(v) { return v !== null && v !== undefined; }

  // _truthy(v) is Grue's boolean coercion: only null/undefined and the string
  // "false" (a kind value) are falsy. 0 and "" are truthy.
  function _truthy(v) {
    return v !== null && v !== undefined && v !== false && v !== "false";
  }

  // _length(node) returns the count of set properties on a node.
  // For List nodes, traverses the linked chain and counts items instead.
  function _length(nameOrRef) {
    if (_instanceof(nameOrRef, "List")) {
      let count = 0, cur = nameOrRef;
      while (cur) {
        const n = _nodeOf(cur);
        if (!n || (n.props || {}).value == null) break;
        count++;
        cur = (n.props || {}).next ?? null;
      }
      return count;
    }
    const node = _nodeOf(nameOrRef);
    if (!node || !node.props) return 0;
    return Object.values(node.props).filter(v => v !== null).length;
  }

  // _listIter(name) traverses a linked List chain and returns an array of values.
  function _listIter(nameOrRef) {
    const result = [];
    let cur = nameOrRef;
    while (cur) {
      const n = _nodeOf(cur);
      if (!n) break;
      const val = (n.props || {}).value ?? null;
      if (val === null) break;
      result.push(val);
      cur = (n.props || {}).next ?? null;
    }
    return result;
  }

  // _iter(node) — for item in expr: dispatches to _listIter for List nodes,
  // otherwise falls back to _children (containment-based iteration).
  function _iter(nameOrRef) {
    if (_instanceof(nameOrRef, "List")) return _listIter(nameOrRef);
    return _children(nameOrRef);
  }

  // _class(node) returns the class name of a node, or "Number"/"Text" for
  // primitive JS values — enables dynamic dispatch for typed handler parameters.
  function _class(nameOrRef) {
    if (typeof nameOrRef === "number") return "Number";
    const node = _nodeOf(nameOrRef);
    if (node) return node.class;
    if (typeof nameOrRef === "string") return "Text";
    return null;
  }

  // _name(node) returns the canonical name string of a node reference.
  function _name(nameOrRef) { return nameOrRef ?? ""; }

  // _instanceof(node, className) checks whether a node is an instance of a
  // class or any of its subclasses.
  function _instanceof(nameOrRef, className) {
    if (className === "Number") return typeof nameOrRef === "number" || (typeof nameOrRef === "string" && nameOrRef !== "" && !isNaN(Number(nameOrRef)));
    if (className === "Text")   return typeof nameOrRef === "string";
    const node = _nodeOf(nameOrRef);
    if (!node) return false;
    let clsName = node.class;
    while (clsName) {
      if (clsName === className) return true;
      const cls = (_game.classes || {})[clsName];
      clsName = cls ? cls.parent : null;
    }
    return false;
  }

  // _filter(node, className) returns an array of child node names that are
  // instances of the given class (or any subclass).
  function _filter(nameOrRef, className) {
    const nodes = _game.nodes || {};
    return Object.entries(nodes)
      .filter(([name, n]) => n.location === nameOrRef && _instanceof(name, className))
      .map(([name]) => name);
  }

  // _children(node) returns an iterable of child node names.
  function _children(nameOrRef) {
    const nodes = _game.nodes || {};
    return Object.entries(nodes)
      .filter(([, n]) => n.location === nameOrRef)
      .map(([name]) => name);
  }

  // _entries(node) returns an iterable of [key, value] pairs for node props.
  function _entries(nameOrRef) {
    const node = _nodeOf(nameOrRef);
    if (!node || !node.props) return [];
    return Object.entries(node.props).filter(([, v]) => v !== null);
  }

  // _str(v) converts any Grue value to a display string (plain text).
  // Used for test assertions, directions strings, and non-say contexts.
  function _str(v) {
    if (v === null || v === undefined) return "";
    if (typeof v === "number" && !Number.isInteger(v)) return String(Math.round(v));
    return String(v);
  }

  // _hstr(v) is _str with HTML-escaping for safe insertion via innerHTML.
  // Used by compiled say strings for {expr} interpolation.
  function _hstr(v) {
    const s = _str(v);
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // ── Chain control ────────────────────────────────────────────────────────────

  // Fail and succeed exit the current handler by throwing a signal object.
  // The dispatch loop catches these and stops the chain (break). A normal
  // return also stops the chain. The only way to continue is via parent().
  class _FailSignal    { constructor(t) { this.token = t; } }
  class _SucceedSignal { constructor(t) { this.token = t; } }
  class _ChooseSignal  { constructor(p, a) { this.prompt = p; this.arms = a; } }

  function _fail(token)    { throw new _FailSignal(token); }
  function _succeed(token) { throw new _SucceedSignal(token ?? "succeed"); }
  let _handlerStopped = false;
  function _stop()         { _handlerStopped = true; throw new _SucceedSignal(); }

  let _pendingChoice = null;
  function _choose(prompt, arms) { throw new _ChooseSignal(prompt, arms); }
  function _presentChoice(prompt, arms) {
    _pendingChoice = arms;
    if (prompt) say(_hstr(prompt));
    for (const arm of arms) say("  &gt; " + _hstr(arm.label));
  }

  // _currentChain / _currentChainPos / _currentArgs / _currentRan track the
  // in-progress dispatch so _parent() can invoke the next handler.
  // _currentRan is a Set of chain indices already executed via _parent(), so
  // the outer dispatch loop skips them and avoids double-firing.
  let _currentChain = null;
  let _currentChainPos = 0;
  let _currentArgs = null;
  let _currentRan = null;

  function _parent() {
    if (!_currentChain) return;
    const next = _currentChainPos + 1;
    if (next >= _currentChain.length) return;
    if (_currentRan) _currentRan.add(next);
    const saved = _currentChainPos;
    _currentChainPos = next;
    try {
      _currentChain[next].fn(..._currentArgs);
    } catch (e) {
      if (e instanceof _FailSignal || e instanceof _SucceedSignal) { /* absorbed */ }
      else throw e;
    } finally {
      _currentChainPos = saved;
    }
  }

  function _parentS() {
    const prev = _muted;
    _muted = true;
    try { _parent(); } finally { _muted = prev; }
  }

  // _call(sigKey, ...args) dispatches a handler call from within handler code.
  // _resolveKey replaces "_" placeholders in a sigKey with the runtime class of
  // the corresponding positional arg, enabling dynamic dispatch for world vars
  // and property-access expressions where the type is not known at compile time.
  // Concrete type markers (uppercase-leading words, "number", "string") also
  // advance the arg index so that mixed sigKeys like "append Object to _" map
  // "_" to the correct positional arg.
  function _resolveKey(raw, args) {
    if (!raw.includes("_")) return raw;
    let i = 0;
    return raw.split(" ").map(p => {
      if (p === "_") return _class(args[i++]) || "_";
      if (/^[A-Z]/.test(p) || p === "number" || p === "string") i++;
      return p;
    }).join(" ");
  }

  function _call(rawKey, ...args) {
    let sigKey = _resolveKey(rawKey, args);
    let chain = (_game.handlers || {})[sigKey];
    if (!chain || chain.length === 0) {
      const fb = sigKey.replace(/\b(Text|Number)\b/g, "Object");
      if (fb !== sigKey) { sigKey = fb; chain = (_game.handlers || {})[sigKey]; }
    }
    if (!chain || chain.length === 0) return null;
    const savedChain = _currentChain;
    const savedPos   = _currentChainPos;
    const savedArgs  = _currentArgs;
    const savedRan   = _currentRan;
    _currentChain    = chain;
    _currentChainPos = 0;
    _currentArgs     = args;
    _currentRan      = new Set();
    let result = null;
    try {
      chain[0].fn(...args);
    } catch (e) {
      if (e instanceof _SucceedSignal) result = e.token;
      else if (!(e instanceof _FailSignal)) throw e;
    } finally {
      _currentChain    = savedChain;
      _currentChainPos = savedPos;
      _currentArgs     = savedArgs;
      _currentRan      = savedRan;
    }
    return result;
  }
  function _callS(sigKey, ...args) {
    const prev = _muted;
    _muted = true;
    try { return _call(sigKey, ...args); } finally { _muted = prev; }
  }

  // _callT is like _call but returns the token for both _SucceedSignal and
  // _FailSignal. Used when the call is the switch expression of a when statement,
  // where arms need to match named failure outcomes as well as success tokens.
  function _callT(rawKey, ...args) {
    let sigKey = _resolveKey(rawKey, args);
    let chain = (_game.handlers || {})[sigKey];
    if (!chain || chain.length === 0) {
      const fb = sigKey.replace(/\b(Text|Number)\b/g, "Object");
      if (fb !== sigKey) { sigKey = fb; chain = (_game.handlers || {})[sigKey]; }
    }
    if (!chain || chain.length === 0) return null;
    const savedChain = _currentChain;
    const savedPos   = _currentChainPos;
    const savedArgs  = _currentArgs;
    const savedRan   = _currentRan;
    _currentChain    = chain;
    _currentChainPos = 0;
    _currentArgs     = args;
    _currentRan      = new Set();
    let result = "succeed"; // normal return = succeed
    try {
      chain[0].fn(...args);
    } catch (e) {
      if (e instanceof _SucceedSignal || e instanceof _FailSignal) result = e.token;
      else throw e;
    } finally {
      _currentChain    = savedChain;
      _currentChainPos = savedPos;
      _currentArgs     = savedArgs;
      _currentRan      = savedRan;
    }
    return result;
  }

  // ── RNG ──────────────────────────────────────────────────────────────────────

  let _rngSeed = Date.now();
  function _seed(n) { _rngSeed = n; }
  function _random(min, max) {
    _rngSeed = (_rngSeed * 1664525 + 1013904223) & 0xffffffff;
    const t = ((_rngSeed >>> 0) / 0x100000000);
    return Math.floor(t * (max - min + 1)) + min;
  }

  // ── Input parsing ────────────────────────────────────────────────────────────

  function tokenize(input) {
    const tokens = [];
    const re = /"([^"]*)"|(\S+)/g;
    let m;
    while ((m = re.exec(input)) !== null) {
      tokens.push(m[1] !== undefined ? m[1] : m[2].toLowerCase());
    }
    return tokens;
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
    const vocab = _game.vocab || {};
    const nodes = _game.nodes || {};
    for (let len = tokens.length - pos; len >= 1; len--) {
      const phrase    = tokens.slice(pos, pos + len).join(" ");
      const canonical = vocab[phrase];
      if (canonical && nodes[canonical] && _instanceof(canonical, type) && _inScope(canonical)) {
        return { value: canonical, consumed: len };
      }
    }
    return null;
  }

  function _classDepth(typeName) {
    let depth = 0, name = typeName;
    while (name) {
      const cls = (_game.classes || {})[name];
      name = cls ? cls.parent : null;
      depth++;
    }
    return depth;
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
    // Try all param edges and keep the most-specific successful match so that
    // "on greet Item:x:" wins over "on greet Object:x:" for an Item argument.
    let best = null, bestDepth = -1;
    for (const edge of (node.params || [])) {
      const m = matchParam(edge.type, tokens, pos);
      if (m) {
        const r = walkTrie(edge.next, tokens, pos + m.consumed, [...args, m.value]);
        if (r) {
          const d = _classDepth(edge.type);
          if (d > bestDepth) { best = r; bestDepth = d; }
        }
      }
    }
    return best;
  }

  function parseInput(input) {
    const g = _game.grammar;
    if (!g) return null;
    return walkTrie(g, tokenize(input), 0, []);
  }

  // ── Dispatch ─────────────────────────────────────────────────────────────────

  function dispatch(sigKey, args) {
    const chain = (_game.handlers || {})[sigKey];
    if (!chain || chain.length === 0) {
      say("You can't do that.");
      return;
    }
    const savedChain = _currentChain;
    const savedPos   = _currentChainPos;
    const savedArgs  = _currentArgs;
    const savedRan   = _currentRan;
    _currentChain    = chain;
    _currentArgs     = args;
    _currentRan      = new Set();
    for (let i = 0; i < chain.length; i++) {
      if (_currentRan.has(i)) continue;
      _currentChainPos = i;
      try {
        chain[i].fn(...args);
      } catch (e) {
        if (e instanceof _FailSignal || e instanceof _SucceedSignal) break;
        throw e;
      }
      break;
    }
    _currentChain    = savedChain;
    _currentChainPos = savedPos;
    _currentArgs     = savedArgs;
    _currentRan      = savedRan;
  }

  const _builtins = {};

  // ── Every-turn and turn-range handlers ───────────────────────────────────────

  function _ownerInScope(owner) {
    const nodes = _game.nodes || {};
    const node  = nodes[owner];
    if (!node) return false;
    if (_instanceof(owner, "Room")) return owner === _location;
    const loc = node.location;
    return loc === _location || loc === "player";
  }

  function _fireEveryTurn() {
    const chain = (_game.handlers || {})["every turn"];
    if (!chain) return;
    const turnRoom = _location; // freeze room for this turn — mid-turn teleports don't trigger other rooms
    const nodes = _game.nodes || {};
    for (const h of chain) {
      if (h.owner) {
        const ownerNode = nodes[h.owner];
        if (!ownerNode) {
          // h.owner is a class name — fire once per in-scope instance of that class.
          if ((_game.classes || {})[h.owner]) {
            for (const [name, node] of Object.entries(nodes)) {
              if (!_instanceof(name, h.owner)) continue;
              if (_instanceof(name, "Room")) {
                if (name !== turnRoom) continue;
              } else if (node.location && node.location !== _location && node.location !== "player") {
                continue;
              }
              try { h.fn(name); } catch(e) {
                if (e instanceof _FailSignal || e instanceof _SucceedSignal) continue;
                throw e;
              }
            }
          }
          continue;
        }
        if (_instanceof(h.owner, "Room")) {
          if (h.owner !== turnRoom) continue;
        } else if (ownerNode.location && ownerNode.location !== _location && ownerNode.location !== "player") {
          continue;
        }
      }
      try { h.fn(h.owner); } catch(e) {
        if (e instanceof _FailSignal || e instanceof _SucceedSignal) continue;
        throw e;
      }
    }
  }

  // ── Turn synchronization ─────────────────────────────────────────────────────
  //
  // A turn is a transaction. It opens, all handlers run (synchronously or via
  // async interface calls), and closes only when every handler has signalled
  // completion. No timeouts are used for sequencing — only for genuine calls
  // to the outside world (network, AI, etc.).
  //
  // Async interface handlers call _holdTurn() to keep the turn open and receive
  // a release() function. They MUST call release() — on success or failure —
  // so the turn always eventually closes:
  //
  //   const release = _holdTurn();
  //   Promise.resolve(aiFunction(response, request)).then(release, release);

  let _turnPending  = 0;
  let _turnResolve  = null;

  function _holdTurn() {
    _turnPending++;
    return function release() {
      if (--_turnPending === 0 && _turnResolve) {
        const r = _turnResolve;
        _turnResolve = null;
        r();
      }
    };
  }

  // executeTurn dispatches one player command and returns a Promise that
  // resolves when all synchronous and asynchronous work for that turn is done.
  // Pure-sync turns resolve immediately via Promise.resolve().
  function executeTurn(input) {
    _turnPending = 0;
    _turnResolve = null;
    _set("turn", (_get("turn") ?? 0) + 1);
    if (input) handleInput(input);
    _fireEveryTurn();
    if (_turnPending === 0) {
      _flushPara();
      return Promise.resolve();
    }
    return new Promise(r => { _turnResolve = function() { _flushPara(); r(); }; });
  }

  // ── Turn loop ────────────────────────────────────────────────────────────────

  function _doExitMove(dest) {
    const destNode = (_game.nodes || {})[dest];
    if (destNode && _instanceof(dest, "Door")) {
      if (_prop(dest, "locked") === "true") { say("The " + dest + " is locked."); return; }
      if (_prop(dest, "open") !== "true") { say("The " + dest + " is closed."); return; }
      const connects = destNode.connects || [];
      const through  = connects.find(r => r !== _location) ?? connects[0];
      if (!through) { say("The " + dest + " doesn't lead anywhere."); return; }
      dispatch("go Room", [through]);
    } else {
      dispatch("go Room", [dest]);
    }
  }

  function _runChoiceArm(arm) {
    try {
      arm.fn();
    } catch (e) {
      if (e instanceof _ChooseSignal) { _presentChoice(e.prompt, e.arms); return; }
      if (e instanceof _SucceedSignal || e instanceof _FailSignal) return;
      throw e;
    }
  }

  function handleInput(raw) {
    const input = raw.trim();
    if (!input) return;
    echo(input);

    // Pending choice: match input against arm labels (case-insensitive, trailing
    // punctuation stripped) rather than running normal grammar dispatch.
    if (_pendingChoice) {
      const arms = _pendingChoice;
      _pendingChoice = null;
      const normalize = s => s.toLowerCase().replace(/[.!?,;]+$/, "").trim();
      const key = normalize(input);
      const arm = arms.find(a => normalize(a.label) === key);
      if (arm) { _runChoiceArm(arm); } else {
        say("Please choose one of the options.");
        _presentChoice(null, arms);
      }
      return;
    }

    const words = tokenize(input);

    // Grammar dispatch first — user-defined handlers like "on go north:" fire
    // before the built-in exit-lookup movement. If the handler calls stop(),
    // movement is blocked; otherwise the exit lookup runs afterwards so the
    // player actually moves.
    const parsed = parseInput(input);
    if (parsed) {
      _handlerStopped = false;
      const prevLoc = _location;
      try {
        dispatch(parsed.sigKey, parsed.args);
      } catch (e) {
        if (e instanceof _ChooseSignal) { _presentChoice(e.prompt, e.arms); return; }
        throw e;
      }
      if (_location !== prevLoc) return;
      if (_handlerStopped) return;
      // Handler ran without stopping or moving — try exit lookup so that
      // direction handlers act as before-movement hooks.
      if (words[0] === "go" && words.length > 1) {
        const phrase = words.slice(1).join(" ");
        const room   = (_game.nodes || {})[_location];
        const exits  = (room && room.exits) ? room.exits : {};
        if (phrase in exits) { _doExitMove(exits[phrase]); }
      }
      return;
    }

    // Exit-phrase lookup: fallback for directions not in the grammar (e.g.,
    // multi-word exits like "top of ladder" used without a grammar rule).
    if (words[0] === "go" && words.length > 1) {
      const phrase = words.slice(1).join(" ");
      const room   = (_game.nodes || {})[_location];
      const exits  = (room && room.exits) ? room.exits : {};
      if (phrase in exits) { _doExitMove(exits[phrase]); return; }
    }

    const key = words.join(" ");
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

  // ── Test runner ──────────────────────────────────────────────────────────────
  //
  // Each test step is fed through handleInput — the same path a real player
  // uses. The echo shows the command, say() shows the response, and the turn
  // handler machinery (on every turn:, on turn N:) fires between steps once M8
  // lands. The runner only adds assertion results on top of that normal output.

  function _flattenTest(name, tests, out, stack) {
    if (stack.has(name)) return;
    const test = tests[name];
    if (!test) return;
    const next = new Set(stack);
    next.add(name);
    if (name) out.push({ _header: name });
    if (test.room) out.push({ _teleport: test.room });
    for (const step of (test.steps || [])) {
      if (step.sub) _flattenTest(step.sub, tests, out, next);
      else out.push(step);
    }
  }

  async function runTests() {
    const tests = _game.tests || {};
    if (!tests[""]) { say("No tests defined."); return; }

    _out.innerHTML = "";
    _currentPara = null;
    _location = _game.start;
    if ((_game.nodes || {})["player"]) _game.nodes["player"].location = _location;
    Object.keys(_worldState).forEach(k => delete _worldState[k]);
    _worldState["player"] = "player";
    _fireEveryTurn();
    _flushPara();

    const steps = [];
    _flattenTest("", tests, steps, new Set());

    let passed = 0, failed = 0;

    for (const step of steps) {
      if (step._header) {
        _pendingChoice = null;
        const el = document.createElement("p");
        el.style.cssText = "color:#888; margin-top:1em";
        el.textContent = `-- test "${step._header}"`;
        _out.appendChild(el);
        await new Promise(r => requestAnimationFrame(r));
        continue;
      }

      if (step._teleport) {
        _location = step._teleport;
        if ((_game.nodes || {})["player"]) _game.nodes["player"].location = _location;
        _set("last_location", _location);
        continue;
      }

      if (step.setup) {
        step.setup();
        continue;
      }

      // Each step runs through the same turn machinery as a real player.
      // executeTurn waits for all handlers — including async interface calls —
      // to complete before the assertion is checked.
      const before = _out.children.length;
      if (step.exprFn) {
        const el = document.createElement("p");
        el.textContent = step.exprFn();
        _out.appendChild(el);
      } else if (step.cmd) {
        _pendingDirection = null;
        await executeTurn(step.cmd);
      } else if (step.tick) {
        // A bare tick (.) accepts the pending direction, as if the player pressed Enter.
        const cmd = _pendingDirection || "";
        _pendingDirection = null;
        await executeTurn(cmd);
      }

      let outputText = "";
      for (let j = before; j < _out.children.length; j++) {
        const el = _out.children[j];
        if (el.dataset && el.dataset.echo) continue;
        outputText += " " + el.textContent;
      }
      outputText = outputText.trim();

      if (step.assert !== undefined) {
        const hit = outputText.toLowerCase().includes(step.assert.toLowerCase());
        const pass = step.negate ? !hit : hit;
        if (pass) passed++; else failed++;
        const el = document.createElement("div");
        el.style.cssText = `font-family:monospace; color:${pass ? "#080" : "#c00"}`;
        const sym = pass ? "OK" : "FAIL";
        const notStr = step.negate ? " not" : "";
        el.textContent = `${sym}${notStr} "${step.assert}"` +
          (pass ? "" : `  -- got: "${outputText}"`);
        _out.appendChild(el);
      }

      // Yield to the browser renderer between steps — a legitimate outside-world
      // call: we are asking the browser to paint before continuing.
      await new Promise(r => requestAnimationFrame(r));
    }

    const ok = failed === 0;
    const el = document.createElement("p");
    el.style.cssText = `font-weight:bold; color:${ok ? "#080" : "#c00"}`;
    el.textContent = `${passed} passed, ${failed} failed`;
    _out.appendChild(el);
  }

  // ── Public API ───────────────────────────────────────────────────────────────

  return {
    // All helpers are exposed so that handler functions and exprFn closures
    // compiled into the game script (outside the IIFE) can reach them via
    // the R parameter of the (function(R){...})(GrueRuntime) wrapper.
    say, directions, _hstr,
    _str, _prop, _setProp, _get, _set,
    _kindOrd, _isset, _truthy, _length, _class, _name, _instanceof,
    _filter, _children, _entries, _iter, _listIter,
    _move, _inScope, _newNode, _freeNode, _through,
    _fail, _succeed, _parent, _parentS, _stop, _choose,
    _call, _callS, _callT, _holdTurn,
    _random, _seed,

    init(game) {
      _game     = game;
      _out      = document.getElementById("output");
      _tree     = document.getElementById("tree");
      _location = game.start;
      _worldState["player"] = "player";   // _get("player") → "player" (inventory container)
      if (!_game.nodes) _game.nodes = {};
      if (!_game.nodes["player"]) {
        _game.nodes["player"] = { class: "Player", location: _location, props: {} };
      } else {
        _game.nodes["player"].location = _location;
      }

      window.say = say;

      if (game.meta && game.meta.title) {
        heading(game.meta.title);
        say("by " + game.meta.author);
        rule();
      }
      _fireEveryTurn();

      const input   = document.getElementById("cmd");
      const goBtn   = document.getElementById("go");
      const treeBtn = document.getElementById("tree-btn");

      if (input && goBtn) {
        function applyPendingDirection() {
          if (_pendingDirection) {
            input.value = _pendingDirection;
            input.select();
            _pendingDirection = null;
          }
        }
        async function submit() {
          const raw = input.value.trim();
          if (!raw) return;
          input.value = "";
          _pendingDirection = null;
          await executeTurn(raw);
          applyPendingDirection();
          input.focus();
        }
        goBtn.addEventListener("click", submit);
        input.addEventListener("keydown", e => { if (e.key === "Enter") submit(); });
        applyPendingDirection(); // catch any direction set during init's _fireEveryTurn
      }

      const testsBtn = document.getElementById("tests-btn");
      if (testsBtn) {
        testsBtn.addEventListener("click", () => {
          _tree.style.display = "none";
          _out.style.display  = "";
          runTests();
          input && input.focus();
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
