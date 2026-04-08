#!/bin/bash

# $1 = basename (e.g. evening2)
# $2 = optional scale number

INPUT="info/$1.png"
OUTPUT="info/$1.spans"

# Run img2spans
python3 tools/img2spans.py "$INPUT" "$OUTPUT"

# If second parameter exists AND is a number → add --scale
if [[ -n "$2" && "$2" =~ ^[0-9]+$ ]]; then
    python3 tools/spans_view.py "$OUTPUT" --scale "$2"
else
    python3 tools/spans_view.py "$OUTPUT"
fi

