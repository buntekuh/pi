#!/usr/bin/env bash
# build.sh — compile, run, or test a Grue game file.
#
#   build.sh -c game.grue   compile  → dist/game.html  (print path on success)
#   build.sh -r game.grue   run      → compile + open in browser
#   build.sh -t game.grue   test     → compile + open in browser with tests auto-run
#   build.sh -ct game.grue  compile and test (flags combine freely)
#
# If no flag is given, -c is assumed.
# Errors and warnings are printed to stderr with file:line references.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPILER_DIR="$SCRIPT_DIR/compiler"
GRUC="$COMPILER_DIR/gruc"
DIST_DIR="$SCRIPT_DIR/dist"

# ── rebuild gruc when any .go source is newer than the binary ─────────────

if [[ ! -x "$GRUC" ]] || find "$COMPILER_DIR" -name '*.go' -newer "$GRUC" | grep -q .; then
    printf 'building gruc...\n' >&2
    (cd "$COMPILER_DIR" && go build -o gruc ./cmd/gruc) \
        || { printf 'build.sh: compiler build failed\n' >&2; exit 1; }
fi

# ── parse arguments ───────────────────────────────────────────────────────

do_compile=false
do_run=false
do_test=false

while getopts 'crt' opt; do
    case "$opt" in
        c) do_compile=true ;;
        r) do_run=true ;;
        t) do_test=true ;;
        *) printf 'usage: build.sh [-c|-r|-t] <file.grue>\n' >&2; exit 1 ;;
    esac
done
shift $((OPTIND - 1))

src="${1:-}"

if [[ -z "$src" ]]; then
    printf 'usage: build.sh [-c|-r|-t] <file.grue>\n' >&2
    exit 1
fi

if [[ ! -f "$src" ]]; then
    printf 'build.sh: %s: file not found\n' "$src" >&2
    exit 1
fi

# default to compile-only when no mode flag was given
if ! $do_compile && ! $do_run && ! $do_test; then
    do_compile=true
fi

# ── derive output path ────────────────────────────────────────────────────

src_abs="$(cd "$(dirname "$src")" && pwd)/$(basename "$src")"
src_name="$(basename "$src" .grue)"

# Extract version from the title line: "Title" by Author version some words
version_raw="$(grep -m1 '^"' "$src_abs" | grep -o 'version .*' | sed 's/^version //')"
# Slugify: replace runs of non-[0-9a-zA-Z_-] with a single dash, strip edge dashes
version_slug="$(printf '%s' "$version_raw" | tr -cs 'a-zA-Z0-9_.-' '-' | sed 's/^-//;s/-$//')"

if [[ -n "$version_slug" ]]; then
    base="${src_name}-${version_slug}"
else
    base="$src_name"
fi

out="$DIST_DIR/${base}.html"

# ── compile ───────────────────────────────────────────────────────────────

if ! "$GRUC" -o "$out" "$src_abs"; then
    exit 1
fi

printf '%s\n' "$out"

# ── open helpers ──────────────────────────────────────────────────────────

open_file() {
    if command -v open &>/dev/null; then
        open "$1"
    elif command -v xdg-open &>/dev/null; then
        xdg-open "$1"
    else
        printf 'build.sh: no browser opener found (tried open, xdg-open)\n' >&2
        exit 1
    fi
}

# ── run ───────────────────────────────────────────────────────────────────
# -t supersedes -r (tests implies run; don't open two tabs)

if $do_run && ! $do_test; then
    open_file "$out"
fi

# ── test ──────────────────────────────────────────────────────────────────

if $do_test; then
    # Inject a script that auto-clicks the Tests button once the page loads.
    test_out="$DIST_DIR/${base}.test.html"
    sed 's|</body>|<script>window.addEventListener("DOMContentLoaded",function(){var b=document.getElementById("tests-btn");if(b)b.click();});</script></body>|' \
        "$out" > "$test_out"
    open_file "$test_out"
fi
