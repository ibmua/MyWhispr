#!/usr/bin/env bash
# MyWhispr installer (idempotent). Sets up systemd user unit + GNOME shortcut.
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Verifying dependencies"
need_apt=()
need_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing: $1 ($2)"
    need_apt+=("$2")
  fi
}
need_bin pw-record pipewire-bin
need_bin pw-play pipewire-bin
need_bin wl-copy wl-clipboard
need_bin ydotool ydotool

python3 -c 'import evdev, pyudev, aiohttp' 2>/dev/null || {
  echo "missing Python deps; install: python3-evdev python3-pyudev python3-aiohttp"
  need_apt+=("python3-evdev python3-pyudev python3-aiohttp")
}

if [[ ${#need_apt[@]} -gt 0 ]]; then
  echo "Run: sudo apt install ${need_apt[*]}"
  exit 1
fi

echo "==> Verifying ydotool"
if ! systemctl --user is-active --quiet ydotool.service; then
  echo "ydotool.service is not active. Start it before continuing."
  exit 1
fi
if ! groups | grep -qw input; then
  echo "Warning: current user is not in 'input' group; EVIOCGRAB may fail."
fi

echo "==> Installing systemd user unit"
mkdir -p "$HOME/.config/systemd/user"
render_unit() {
  local src="$1"
  local dest="$2"
  local escaped="$HERE"
  escaped="${escaped//\\/\\\\}"
  escaped="${escaped//&/\\&}"
  escaped="${escaped//|/\\|}"
  sed "s|@PROJECT_DIR@|$escaped|g" "$src" > "$dest"
}
render_unit "$HERE/systemd/mywhisprd.service" "$HOME/.config/systemd/user/mywhisprd.service"
systemctl --user daemon-reload
systemctl --user enable --now mywhisprd.service

if [[ "${MYWHISPR_ENABLE_APPINDICATOR:-0}" == "1" ]]; then
  echo "==> Installing optional AppIndicator fallback"
  render_unit "$HERE/systemd/mywhispr-indicator.service" "$HOME/.config/systemd/user/mywhispr-indicator.service"
  systemctl --user enable --now mywhispr-indicator.service
else
  echo "==> Disabling standalone AppIndicator to avoid duplicate top-bar widgets"
  systemctl --user disable --now mywhispr-indicator.service >/dev/null 2>&1 || true
fi

echo "==> Wiring GNOME shortcut"
SCHEMA=org.gnome.settings-daemon.plugins.media-keys
KB_SCHEMA="$SCHEMA.custom-keybinding"
PATH_PREFIX=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings
OUR="$PATH_PREFIX/mywhispr-grave/"
CMD="$HERE/bin/mywhisprctl start grave"

current=$(gsettings get "$SCHEMA" custom-keybindings 2>/dev/null || echo "[]")
paths=$(CURRENT="$current" python3 - <<'PY'
import ast
import os

s = os.environ.get("CURRENT", "[]")
if s.startswith("@as "):
    s = s[4:]
try:
    print("\n".join(ast.literal_eval(s)))
except Exception:
    pass
PY
)
existing=""
conflict=""
while IFS= read -r path; do
  [[ -z "$path" ]] && continue
  binding=$(gsettings get "$KB_SCHEMA:$path" binding 2>/dev/null || true)
  command=$(gsettings get "$KB_SCHEMA:$path" command 2>/dev/null || true)
  name=$(gsettings get "$KB_SCHEMA:$path" name 2>/dev/null || true)
  if [[ "$binding" == "'grave'" ]]; then
    if [[ "$command" == "'$CMD'" || "$name" == "'MyWhispr grave'" ]]; then
      existing="$path"
      break
    fi
    conflict="$path name=$name command=$command"
  fi
done <<< "$paths"

if [[ -n "$conflict" && -z "$existing" ]]; then
  echo "grave is already bound by another shortcut: $conflict"
  echo "Resolve the conflict in GNOME Settings, then rerun this installer."
  exit 1
fi

if [[ -n "$existing" ]]; then
  OUR="$existing"
else
  case "$current" in
    *"$OUR"*) ;;
    "@as []"|"[]") gsettings set "$SCHEMA" custom-keybindings "['$OUR']" ;;
    *) gsettings set "$SCHEMA" custom-keybindings "${current%]*}, '$OUR']" ;;
  esac
fi
gsettings set "$KB_SCHEMA:$OUR" name "MyWhispr grave"
gsettings set "$KB_SCHEMA:$OUR" command "$CMD"
gsettings set "$KB_SCHEMA:$OUR" binding "grave"

echo "==> Installing GNOME top-bar extension"
DEST="$HOME/.local/share/gnome-shell/extensions/mywhispr@local"
mkdir -p "$DEST"
cp -f "$HERE/extensions/mywhispr@local/"* "$DEST/"
enabled=$(gsettings get org.gnome.shell enabled-extensions 2>/dev/null || echo "[]")
next_enabled=$(ENABLED="$enabled" python3 - <<'PY'
import ast
import os

raw = os.environ.get("ENABLED", "[]")
try:
    items = ast.literal_eval(raw)
except Exception:
    items = []
if "mywhispr@local" not in items:
    items.append("mywhispr@local")
print("[" + ", ".join(repr(x) for x in items) + "]")
PY
)
gsettings set org.gnome.shell enabled-extensions "$next_enabled" 2>/dev/null || true
gnome-extensions enable mywhispr@local 2>/dev/null || true

echo "==> Done. The GNOME Shell extension is the top-bar status widget."
echo "    Logout/login may be needed for GNOME Shell to load a newly installed extension under Wayland."
echo "    For the legacy AppIndicator fallback, rerun with MYWHISPR_ENABLE_APPINDICATOR=1."
echo "    Smoke test: $HERE/bin/mywhisprctl status"
