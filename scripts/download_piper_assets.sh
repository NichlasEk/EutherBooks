#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS_DIR="$ROOT_DIR/tools"
PIPER_DIR="$TOOLS_DIR/piper"
MODELS_DIR="$ROOT_DIR/models/piper"

mkdir -p "$PIPER_DIR" "$MODELS_DIR"

PIPER_RELEASE="2023.11.14-2"
PIPER_ARCHIVE="$TOOLS_DIR/piper_linux_x86_64.tar.gz"
PIPER_URL="https://github.com/rhasspy/piper/releases/download/${PIPER_RELEASE}/piper_linux_x86_64.tar.gz"

if [ ! -x "$PIPER_DIR/piper" ]; then
  curl -L --fail "$PIPER_URL" -o "$PIPER_ARCHIVE"
  tar -xzf "$PIPER_ARCHIVE" -C "$TOOLS_DIR"
fi

download_voice() {
  local language="$1"
  local locale="$2"
  local speaker="$3"
  local quality="$4"
  local name="${locale}-${speaker}-${quality}"
  local base_url="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/${language}/${locale}/${speaker}/${quality}/${name}"

  if [ ! -f "$MODELS_DIR/${name}.onnx" ]; then
    curl -L --fail "${base_url}.onnx" -o "$MODELS_DIR/${name}.onnx"
  fi
  if [ ! -f "$MODELS_DIR/${name}.onnx.json" ]; then
    curl -L --fail "${base_url}.onnx.json" -o "$MODELS_DIR/${name}.onnx.json"
  fi
}

download_voice "sv" "sv_SE" "nst" "medium"
download_voice "en" "en_US" "lessac" "medium"

cat <<EOF
Piper assets installed:
  binary: $PIPER_DIR/piper
  Swedish: $MODELS_DIR/sv_SE-nst-medium.onnx
  English: $MODELS_DIR/en_US-lessac-medium.onnx
EOF
