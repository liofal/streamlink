#!/usr/bin/env bash
set -euo pipefail

PI_HOME="${PI_HOME:-$HOME/.pi}"
PI_PREFIX="${PI_PREFIX:-$PI_HOME/npm-global}"
PI_PACKAGE="${PI_PACKAGE:-@earendil-works/pi-coding-agent}"

mkdir -p "$PI_HOME/agent" "$PI_PREFIX"

export NPM_CONFIG_PREFIX="$PI_PREFIX"
export PATH="$PI_PREFIX/bin:$PATH"

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required to install ${PI_PACKAGE}" >&2
  exit 1
fi

latest="$(npm view "$PI_PACKAGE" version)"
current="$(pi --version 2>&1 || true)"
pi_path="$(command -v pi 2>/dev/null || true)"
expected_pi_path="$PI_PREFIX/bin/pi"

if [ "$current" != "$latest" ] || [ "$pi_path" != "$expected_pi_path" ]; then
  npm install -g "${PI_PACKAGE}@latest"
fi

echo "Pi: $(pi --version 2>&1)"
echo "Pi executable: $(command -v pi)"
