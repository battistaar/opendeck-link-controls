#!/usr/bin/env bash
# Copy the plugin into OpenDeck's plugin folder, then restart OpenDeck to load it.
# Run it again after every change.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
name="io.github.battistaar.linkcontrols.sdPlugin"
plugins="${XDG_CONFIG_HOME:-$HOME/.config}/opendeck/plugins"

if ! command -v linkctl >/dev/null && [ ! -e "$HOME/.local/bin/linkctl" ]; then
    echo "linkctl is not installed. Install it first, e.g. 'pipx install .' in insta360_link_control." >&2
    exit 1
fi
# Copy rather than symlink: OpenDeck's interface only serves files that really live
# under its config folder, so icons behind a symlink do not show.
mkdir -p "$plugins"
rm -rf "${plugins:?}/$name"
cp -r "$here/$name" "$plugins/$name"
rm -rf "$plugins/$name/plugin/__pycache__"
echo "installed $plugins/$name"

if pgrep -x opendeck >/dev/null; then
    pkill -x opendeck
    sleep 2
    setsid -f opendeck --hide >/dev/null 2>&1
    echo "restarted OpenDeck"
fi
