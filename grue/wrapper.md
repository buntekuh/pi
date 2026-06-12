# wrapper.md — things that belong to the wrapper, not to Grue

This file tracks temporary scaffolding that lives inside the Grue compiler or
runtime today but should be moved to the host wrapper once one exists.
Everything here is intentionally provisional and must be cleaned up before
Grue is deployed inside a real container (Pi terminal, web app, etc.).

---

## Test CSS

The generated HTML currently injects a minimal `<style>` block so games look
readable during development. The rules target the CSS class names and HTML element types that Grue emits
(`p.text`, `p.mono`, `h2` for headline, `em` for emphasize, `strong` for bold,
custom span classes, etc.).

**What needs to happen**: the wrapper owns the stylesheet. Grue just emits
class names; the wrapper provides the design tokens. Remove the embedded
`<style>` block from the HTML template in `compiler/codegen/codegen.go` once
a wrapper ships.

**Current test rules** (in `codegen.go` HTML template):
```css
body   { max-width: 680px; margin: 40px auto; font: 1.05em/1.7 Georgia, serif; color: #222; background: #f7f6f2; }
p.text { background: #eeede6; padding: 6px 10px; border-radius: 3px; margin: 4px 0; }
h2     { font-size: 1.25em; font-weight: bold; margin: 1.2em 0 0.2em; color: #333; }
```

---

## Input field pre-fill (`directions`)

`directions "go east"` currently writes directly into the browser `<input>`
field (`_pendingDirection` → `input.value` after each turn).

**What needs to happen**: once a wrapper exists, `directions` should call an
interface handler that the wrapper intercepts and routes to whichever input
mechanism the platform uses (readline buffer on the Pi terminal, a different
widget on mobile, etc.). The direct `input.value` write is a browser-only
shortcut.

**Affected code**: `applyPendingDirection()` in `compiler/codegen/runtime.js`.
