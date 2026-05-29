#!/usr/bin/env bash
# Download one of the configured Hugging Face GPU ASR models into the local HF cache.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/download-gpu-asr-model.sh MODEL_KEY|all

MODEL_KEY:
  qwen3-asr-1.7b
  parakeet-tdt-0.6b-v3
  granite-speech-4.1-2b
  cohere-transcribe-03-2026
  canary-qwen-2.5b
  canary-1b-v2
  seamless-m4t-v2-large
  qwen3-asr-0.6b

Runtime loading uses local_files_only=true by default, so download weights before
selecting these models in the web UI.
USAGE
}

declare -A REPOS=(
  ["qwen3-asr-1.7b"]="Qwen/Qwen3-ASR-1.7B"
  ["parakeet-tdt-0.6b-v3"]="nvidia/parakeet-tdt-0.6b-v3"
  ["granite-speech-4.1-2b"]="ibm-granite/granite-speech-4.1-2b"
  ["cohere-transcribe-03-2026"]="CohereLabs/cohere-transcribe-03-2026"
  ["canary-qwen-2.5b"]="nvidia/canary-qwen-2.5b"
  ["canary-1b-v2"]="nvidia/canary-1b-v2"
  ["seamless-m4t-v2-large"]="facebook/seamless-m4t-v2-large"
  ["qwen3-asr-0.6b"]="Qwen/Qwen3-ASR-0.6B"
)

declare -A EXCLUDES=(
  ["parakeet-tdt-0.6b-v3"]="*.nemo plots/*"
  ["granite-speech-4.1-2b"]=".eval_results/*"
  ["cohere-transcribe-03-2026"]=".eval_results/* assets/* demo/*"
)

MODEL_KEYS=(
  qwen3-asr-1.7b
  parakeet-tdt-0.6b-v3
  granite-speech-4.1-2b
  cohere-transcribe-03-2026
  canary-qwen-2.5b
  canary-1b-v2
  seamless-m4t-v2-large
  qwen3-asr-0.6b
)

if [[ $# -ne 1 || "$1" == "-h" || "$1" == "--help" ]]; then
  usage
  exit 0
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

if [[ -n "${HF_CLI:-}" ]]; then
  hf_cli=("$HF_CLI")
elif [[ -x "$PROJECT_DIR/.venv-gpu-asr/bin/hf" ]]; then
  hf_cli=("$PROJECT_DIR/.venv-gpu-asr/bin/hf")
elif command -v hf >/dev/null 2>&1; then
  hf_cli=("hf")
elif [[ -x "$PROJECT_DIR/.venv-gpu-asr/bin/huggingface-cli" ]]; then
  hf_cli=("$PROJECT_DIR/.venv-gpu-asr/bin/huggingface-cli")
elif command -v huggingface-cli >/dev/null 2>&1; then
  hf_cli=("huggingface-cli")
else
  echo "Hugging Face CLI is missing. Install it with: pip install -U 'huggingface_hub[cli]'" >&2
  exit 1
fi

download_one() {
  local key="$1"
  local repo="${REPOS[$key]:-}"
  if [[ -z "$repo" ]]; then
    echo "Unknown model key: $key" >&2
    usage >&2
    exit 2
  fi
  echo "==> Downloading $key ($repo)"
  local args=(download "$repo")
  local patterns="${EXCLUDES[$key]:-}"
  if [[ -n "$patterns" ]]; then
    local pattern
    for pattern in $patterns; do
      args+=(--exclude "$pattern")
    done
  fi
  "${hf_cli[@]}" "${args[@]}"
}

if [[ "$1" == "all" ]]; then
  for key in "${MODEL_KEYS[@]}"; do
    download_one "$key"
  done
else
  download_one "$1"
fi
