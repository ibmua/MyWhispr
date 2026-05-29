#!/usr/bin/env bash
# Download a whisper.cpp ggml model from HuggingFace into the local models dir,
# then merge it into MyWhispr's config.json so the daemon picks it up on reload.
#
# Usage:
#   scripts/download-model.sh <variant>
#
# Known variants (HuggingFace ggerganov/whisper.cpp):
#   tiny tiny.en base base.en small small.en small-q5_1
#   medium medium.en medium-q5_0 medium.en-q5_0
#   large-v2 large-v2-q5_0 large-v3 large-v3-q5_0
#   large-v3-turbo large-v3-turbo-q5_0 large-v3-turbo-q8_0
#
# The script is idempotent: re-running with the same variant resumes the
# download via `curl --continue-at`, and the config update is a no-op when
# the entry already exists with the same path.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

variant="${1:-}"
if [[ -z "$variant" ]]; then
  echo "usage: $0 <variant>"
  echo "e.g.  $0 medium"
  echo "      $0 large-v3-q5_0"
  exit 2
fi

repo="ggerganov/whisper.cpp"
file="ggml-${variant}.bin"
url="https://huggingface.co/${repo}/resolve/main/${file}"

models_dir="${MYWHISPR_MODELS_DIR:-$PROJECT_DIR/models}"
config_path="${MYWHISPR_CONFIG:-$PROJECT_DIR/config.json}"
dest="${models_dir}/${file}"

mkdir -p "$models_dir"

echo "Downloading $file from $repo ..."
curl --location --continue-at - --fail --progress-bar --output "$dest" "$url"

# Merge into config.json under "models" using the short variant name as key.
echo "Merging into $config_path ..."
python3 - "$dest" "$variant" "$config_path" <<'PY'
import json, sys, pathlib
path, name, cfg_path = sys.argv[1:]
p = pathlib.Path(cfg_path)
cfg = json.loads(p.read_text())
cfg.setdefault("models", {})
key = name  # e.g. "medium" or "distil-large-v3"
cfg["models"][key] = path
p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
print(f"  config: models[{key!r}] = {path}")
PY

echo
echo "Done. Reload the daemon to pick up the new model:"
echo "  systemctl --user restart mywhisprd"
