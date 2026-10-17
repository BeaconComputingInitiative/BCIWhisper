#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$HOME/BCIWhisper"
source "$ROOT/.venv-bciwhisper/bin/activate"
export BCI_WHISPER_MODEL="${BCI_WHISPER_MODEL:-$ROOT/models/faster-whisper-small.en}"
export BUN_INSTALL="${BUN_INSTALL:-$HOME/.bun}"
export PATH="$BUN_INSTALL/bin:$PATH"
cd "$ROOT"
exec python BCIWhisper.py "$@"
