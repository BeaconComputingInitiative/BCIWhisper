#!/usr/bin/env bash
set -e
ROOT="$HOME/BCIWhisper"
source "$ROOT/.venv-bciwhisper/bin/activate"
export BCI_WHISPER_MODEL="${BCI_WHISPER_MODEL:-$ROOT/models/faster-whisper-small.en}"
export BUN_INSTALL="${BUN_INSTALL:-$HOME/.bun}"
export PATH="$BUN_INSTALL/bin:$PATH"
cd "$ROOT"
echo "[BCI] Environment activated"
echo "[BCI] Project: $ROOT"
echo "[BCI] Python: $(command -v python)"
echo "[BCI] Whisper model: $BCI_WHISPER_MODEL"
