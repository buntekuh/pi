"use strict";

// GrueRuntime — the Grue game engine.
// The compiled game script calls GrueRuntime.init(game) to start.
// The game descriptor shape grows with each compiler milestone:
//   M1: meta, nodes, start
const GrueRuntime = (function () {

  let _out;

  // ── Output ──────────────────────────────────────────────────────────────────

  function para(text) {
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

  // ── Public API ───────────────────────────────────────────────────────────────

  return {
    init(game) {
      _out = document.getElementById("output");

      // Title block
      if (game.meta && game.meta.title) {
        heading(game.meta.title);
        para("by " + game.meta.author);
        rule();
      }

      // Starting room description
      const room = game.nodes && game.nodes[game.start];
      if (room && room.desc) {
        para(room.desc);
      }
    }
  };

}());
