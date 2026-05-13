#!/usr/bin/env bash
set -euo pipefail

export PATH="/usr/local/share/npm-global/bin:/usr/local/bin:${PATH}"

ensure_python_dependencies() {
  pip install -r requirements.txt
}

ensure_pi_coding_agent() {
  if ! command -v npm >/dev/null 2>&1; then
    echo "npm is required to install the Pi coding agent but was not found." >&2
    exit 1
  fi

  mkdir -p \
    "${HOME}/.pi/agent" \
    .pi/sessions

  bash .devcontainer/ensure-pi.sh
}

print_versions() {
  if command -v pi >/dev/null 2>&1; then
    echo "Pi: $(pi --version 2>&1)"
  else
    echo "Pi: $(command -v pi)"
  fi
}

ensure_python_dependencies
ensure_pi_coding_agent
print_versions
