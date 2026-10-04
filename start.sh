#!/usr/bin/env bash
# AudioScribe starten - macOS (Apple Silicon) und Linux. Gegenstueck zu start.ps1.
#
# Optionen: --torch auto|cpu|cu124   --port N   --no-browser   --doctor   --devices
#
# 'uv run' gleicht die Umgebung vor dem Start ab und installiert fehlende Pakete nach.
# uv selbst wird bei Bedarf installiert (astral.sh), Python 3.12 besorgt uv - kein
# Homebrew, kein System-Python noetig. Umgebungen: .venv = Linux/WSL, .venv-win =
# Windows, .venv-mac = macOS (getrennt, damit sich die Plattformen nicht gegenseitig
# die Pakete zerlegen). UV_PROJECT_ENVIRONMENT in der Shell hat Vorrang.
# Nur ASCII in dieser Datei.
set -euo pipefail
cd "$(dirname "$0")"

TORCH=auto
PORT=8766
NOBROWSER=""
MODE=ui
while [ $# -gt 0 ]; do
  case "$1" in
    --torch) TORCH="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --no-browser) NOBROWSER=1; shift ;;
    --doctor) MODE=doctor; shift ;;
    --devices) MODE=devices; shift ;;
    -h|--help) sed -n '2,4p' "$0"; exit 0 ;;
    *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
  esac
done

OS="$(uname -s)"
ARCH="$(uname -m)"
EXTRAS=(--extra review --extra agent --extra live)

if [ "$OS" = "Darwin" ]; then
  export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-$PWD/.venv-mac}"
  # torch: fehlende MPS-Operatoren (pyannote) rechnen auf der CPU statt abzubrechen.
  export PYTORCH_ENABLE_MPS_FALLBACK="${PYTORCH_ENABLE_MPS_FALLBACK:-1}"
  if [ "$TORCH" = auto ]; then TORCH=cpu; fi   # Apple Silicon: MPS steckt im Standard-Wheel
  if [ "$TORCH" = cu124 ]; then
    echo "CUDA gibt es nicht auf dem Mac - nehme cpu (MPS)." >&2
    TORCH=cpu
  fi
  if [ "$ARCH" = "arm64" ]; then
    EXTRAS+=(--extra mac)
  else
    echo "Hinweis: Intel-Mac erkannt - MLX und ScreenCaptureKit-Audio entfallen, CPU-Betrieb." >&2
  fi
else
  export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-$PWD/.venv}"
  if [ "$TORCH" = auto ]; then
    TORCH=cpu
    if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
      TORCH=cu124
    fi
  fi
fi

if ! command -v uv >/dev/null 2>&1; then
  if [ -x "$HOME/.local/bin/uv" ]; then
    export PATH="$HOME/.local/bin:$PATH"
  else
    echo "uv fehlt - wird nach ~/.local/bin installiert (https://astral.sh/uv) ..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  fi
fi

if [ "$OS" = "Darwin" ] && [ ! -d "$UV_PROJECT_ENVIRONMENT" ]; then
  cat <<'HINWEIS'
Erster Start auf macOS: Pakete und Modelle werden geladen (einige GB, nur einmal).
Beim ersten "Aufnahme starten" fragt macOS nach Berechtigungen fuer DIESE Terminal-App:
  - Mikrofon           (Systemeinstellungen > Datenschutz & Sicherheit > Mikrofon)
  - Bildschirmaufnahme (... > Bildschirmaufnahme; danach die Terminal-App neu starten)
Beide gelten fuer Terminal.app/iTerm/VS Code, nicht fuer "Python".
HINWEIS
fi

echo "AudioScribe: $OS/$ARCH, torch=$TORCH, Extras ${EXTRAS[*]}, venv $UV_PROJECT_ENVIRONMENT (beenden mit Strg+C)"
case "$MODE" in
  doctor)  exec uv run --extra "$TORCH" "${EXTRAS[@]}" audioscribe doctor ;;
  devices) exec uv run --extra "$TORCH" "${EXTRAS[@]}" audioscribe live --list-devices ;;
  *)
    if [ -n "$NOBROWSER" ]; then
      exec uv run --extra "$TORCH" "${EXTRAS[@]}" audioscribe ui --port "$PORT" --no-browser
    else
      exec uv run --extra "$TORCH" "${EXTRAS[@]}" audioscribe ui --port "$PORT"
    fi
    ;;
esac
