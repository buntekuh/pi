#!/usr/bin/env bash
set -e

GRUE_ROOT="$(cd "$(dirname "$0")" && pwd)"
TRANSPILER="$GRUE_ROOT/compiler/grue.py"
RUNNER="$GRUE_ROOT/runner.py"
I6_LIB="/Users/buntekuh/projects/Inform/inform/Library/lib611"
BIN_DIR="$GRUE_ROOT/bin"

usage() {
    echo "usage: build.sh [-b|-r|-t|-br|-bt|-brt] <game.grue>"
    echo "  -b    build only (default)"
    echo "  -r    run only"
    echo "  -t    test only"
    echo "  -br   build then run"
    echo "  -bt   build then test"
    echo "  -brt  build, test, then run"
    exit 1
}

DO_BUILD=true
DO_RUN=false
DO_TEST=false

case "$1" in
    -b)   DO_BUILD=true;  DO_RUN=false; DO_TEST=false; shift ;;
    -r)   DO_BUILD=false; DO_RUN=true;  DO_TEST=false; shift ;;
    -t)   DO_BUILD=false; DO_RUN=false; DO_TEST=true;  shift ;;
    -br)  DO_BUILD=true;  DO_RUN=true;  DO_TEST=false; shift ;;
    -bt)  DO_BUILD=true;  DO_RUN=false; DO_TEST=true;  shift ;;
    -brt) DO_BUILD=true;  DO_RUN=false; DO_TEST=true;  DO_RUN=true; shift ;;
    -*)   usage ;;
esac

[ $# -lt 1 ] && usage

GRUE_FILE="$1"
[ ! -f "$GRUE_FILE" ] && { echo "build: file not found: $GRUE_FILE"; exit 1; }

BASE="$(basename "$GRUE_FILE" .grue)"
INF_FILE="$BIN_DIR/$BASE.inf"
Z5_FILE="$BIN_DIR/$BASE.z5"
GTS_FILE="$BIN_DIR/$BASE.gts"

if $DO_BUILD; then
    python3 "$TRANSPILER" "$GRUE_FILE" "$INF_FILE"
    inform +"$I6_LIB" "$INF_FILE" "$Z5_FILE"
    echo "ready: $Z5_FILE"
fi

if $DO_TEST; then
    [ ! -f "$GTS_FILE" ] && { echo "build: $GTS_FILE not found — no tests defined?"; exit 1; }
    python3 "$RUNNER" "$Z5_FILE" "$GTS_FILE"
fi

if $DO_RUN; then
    [ ! -f "$Z5_FILE" ] && { echo "build: $Z5_FILE not found — run with -b first"; exit 1; }
    frotz "$Z5_FILE"
fi
