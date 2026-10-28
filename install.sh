#!/usr/bin/env sh
# Fail closed: the inherited network installer installed upstream HyprMod.
printf '%s\n' \
    'Attune network installation is disabled. Nothing was changed.' \
    'Use the local Attune checkout; see README.md: Local source setup and launch.' \
    'On this CachyOS machine, from the checkout:' \
    '  uv sync --python /usr/bin/python3' \
    '  uv run attune' \
    'If uv is not on PATH, see README.md for the temporary local uv path.' \
    'This script does not install, uninstall, download, or register desktop files.' >&2
exit 1
