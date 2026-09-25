#!/usr/bin/env bash
set -e
ruff check api/
echo "Lint check passed."
