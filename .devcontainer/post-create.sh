#!/usr/bin/env bash
set -euo pipefail

export PATH="/usr/local/share/npm-global/bin:/usr/local/bin:${PATH}"

ensure_python_dependencies() {
  pip install -r requirements.txt
}

ensure_python_dependencies
mkdir -p .pi/sessions
