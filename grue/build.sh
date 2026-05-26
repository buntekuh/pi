#!/usr/bin/env bash

GRUE_ROOT="$(cd "$(dirname "$0")" && pwd)"
TRANSPILER="$GRUE_ROOT/compiler/grue.py"
RUNNER="$GRUE_ROOT/runner.py"
I6_LIB="/Users/buntekuh/projects/Inform/inform/Library/lib611"
BIN_DIR="$GRUE_ROOT/bin"

usage() {
    echo "usage: build.sh [-brtvа] [<game.grue>]"
    echo "  -b    build"
    echo "  -r    run"
    echo "  -t    test"
    echo "  -v    verbose test output"
    echo "  -a    build and test all files in tests/"
    exit 1
}

DO_BUILD=false
DO_RUN=false
DO_TEST=false
DO_VERBOSE=false
DO_ALL=false

if [[ "$1" == -* ]]; then
    flags="${1#-}"
    shift
    for (( i=0; i<${#flags}; i++ )); do
        case "${flags:$i:1}" in
            b) DO_BUILD=true ;;
            r) DO_RUN=true ;;
            t) DO_TEST=true ;;
            v) DO_VERBOSE=true ;;
            a) DO_ALL=true ;;
            *) usage ;;
        esac
    done
else
    DO_BUILD=true
fi

run_one() {
    local GRUE_FILE="$1"
    local BASE INF_FILE Z5_FILE GTS_FILE RUNNER_FLAGS
    BASE="$(basename "$GRUE_FILE" .grue)"
    INF_FILE="$BIN_DIR/$BASE.inf"
    Z5_FILE="$BIN_DIR/$BASE.z5"
    GTS_FILE="$BIN_DIR/$BASE.gts"

    if $DO_BUILD; then
        python3 "$TRANSPILER" "$GRUE_FILE" "$INF_FILE" || return 1
        local inform_out inform_rc
        inform_out=$(inform +"$I6_LIB" "$INF_FILE" "$Z5_FILE" 2>&1)
        inform_rc=$?
        while IFS= read -r line; do
            if [[ "$line" == *"Error"* ]]; then
                echo $'\033[31m'"$line"$'\033[0m'
            elif [[ "$line" == *"Warning"* ]]; then
                echo $'\033[33m'"$line"$'\033[0m'
            else
                echo "$line"
            fi
        done <<< "$inform_out"
        [ $inform_rc -ne 0 ] && return 1
        echo "ready: $Z5_FILE"
    fi

    if $DO_TEST; then
        [ ! -f "$GTS_FILE" ] && { echo "build: $GTS_FILE not found — no tests defined?"; return 1; }
        RUNNER_FLAGS=""
        $DO_VERBOSE && RUNNER_FLAGS="-v"
        while IFS= read -r line; do
            echo "$line"
            if [[ "$line" =~ ^([0-9]+)\ passed,\ ([0-9]+)\ failed ]]; then
                total_passed=$(( total_passed + ${BASH_REMATCH[1]} ))
                total_failed=$(( total_failed + ${BASH_REMATCH[2]} ))
            fi
        done < <(python3 "$RUNNER" $RUNNER_FLAGS "$Z5_FILE" "$GTS_FILE")
    fi

    if $DO_RUN; then
        [ ! -f "$Z5_FILE" ] && { echo "build: $Z5_FILE not found — run with -b first"; return 1; }
        frotz "$Z5_FILE"
    fi
}

if $DO_ALL; then
    DO_BUILD=true
    DO_TEST=true
    build_failures=0
    total_passed=0
    total_failed=0
    for f in "$GRUE_ROOT/tests/"*.grue; do
        echo ""
        echo "=== $(basename "$f") ==="
        if ! run_one "$f"; then
            (( build_failures++ )) || true
        fi
    done
    echo ""
    GREEN=$'\033[32m'; RED=$'\033[31m'; RESET=$'\033[0m'
    passed_str="${GREEN}${total_passed} passed${RESET}"
    (( total_failed > 0 ))    && failed_str="${RED}${total_failed} failed${RESET}"       || failed_str="${total_failed} failed"
    (( build_failures > 0 ))  && build_str="${RED}${build_failures} build error(s)${RESET}" || build_str="${build_failures} build error(s)"
    echo "=== total: ${passed_str}, ${failed_str}, ${build_str} ==="
    (( total_failed > 0 || build_failures > 0 )) && exit 1 || exit 0
fi

[ $# -lt 1 ] && usage
run_one "$1"
