#!/usr/bin/env bash
set -euo pipefail

# VoxPrompt — bootstrap do ambiente Python.
# Dependências de sistema (instale manualmente, exigem sudo):
#
#   sudo apt install -y libportaudio2 wl-clipboard   # Wayland (wl-copy)
#   # ou, em X11:
#   sudo apt install -y libportaudio2 xclip
#
# libportaudio2 -> captura de microfone (sounddevice)
# wl-clipboard / xclip -> copiar resultado para o clipboard
# claude (Claude Code CLI) -> estruturação via `claude -p` (deve estar no PATH)

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

echo ">> Criando .venv com $PYTHON"
"$PYTHON" -m venv .venv

# shellcheck disable=SC1091
source .venv/bin/activate

echo ">> Atualizando pip"
pip install --upgrade pip

echo ">> Instalando dependências Python"
pip install -r requirements.txt

cat <<'EOF'

Setup concluído.

Pendências de sistema (caso ainda não tenha):
  sudo apt install -y libportaudio2 wl-clipboard   # ou: xclip

Para rodar:
  source .venv/bin/activate && python -m voxprompt
EOF
