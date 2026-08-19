#!/usr/bin/env bash
# Caduceus bootstrap - run from the repo root on the Mac that runs Hermes.
set -euo pipefail

echo "⚕ caduceus setup"

if ! command -v python3 >/dev/null; then
  echo "python3 required"; exit 1
fi
if ! command -v hermes >/dev/null; then
  echo "WARNING: hermes not on PATH - install continues, but 'cad init' will refuse."
fi

pip3 install -e . --break-system-packages -q || pip3 install -e . -q
echo "[+] cad installed: $(command -v cad || echo 'NOT ON PATH - check pip bin dir')"

cad doctor || true
echo
echo "Next:"
echo "  cad init                 # provision the 5 seats"
echo "  cad init --guard-write   # wire the command guard"
echo "  cad init --cron          # morning brief + weekly ledger digest"
echo "  cad council ask \"...\" --quick"
