#!/usr/bin/env bash
# create_wayfinding_env.sh
set -euo pipefail
umask 0027

APP_DIR="${APP_DIR:-$(pwd)}"
OUT="$APP_DIR/wayfinding.env"

# Prefer app venv python if present
VENV_PY="$APP_DIR/.venv/bin/python3"
PYBIN="${PYBIN:-}"
if [[ -x "$VENV_PY" ]]; then PYBIN="$VENV_PY"; else PYBIN="$(command -v python3 || true)"; fi
[[ -n "$PYBIN" ]] || { echo "python3 not found"; exit 1; }

# Ensure Werkzeug is available
if ! "$PYBIN" - <<'PY' >/dev/null 2>&1
import werkzeug
PY
then
  echo "Werkzeug not available in $PYBIN. Install it, e.g.:"
  echo "  $PYBIN -m pip install werkzeug"
  exit 1
fi

# Get admin password
PW="${1:-${WAYFINDING_ADMIN_PASSWORD:-}}"
if [[ -z "${PW}" ]]; then
  read -s -p "Enter admin password: " PW; echo
  read -s -p "Confirm admin password: " PW2; echo
  [[ "$PW" == "${PW2:-}" ]] || { echo "Passwords do not match"; unset PW PW2; exit 1; }
  unset PW2
fi

# Hash with scrypt (password via stdin; code via -c to avoid stdin collision)
HASH="$(
  printf '%s' "$PW" | "$PYBIN" -c '
import sys
from werkzeug.security import generate_password_hash
pw = sys.stdin.read().rstrip("\n")
print(generate_password_hash(pw, method="scrypt"))
'
)"
unset PW

# Generate 64-hex secret
if command -v openssl >/dev/null 2>&1; then
  SECRET="$(openssl rand -hex 32)"
else
  SECRET="$("$PYBIN" - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"
fi

# Write atomically
TMP="$(mktemp)"
cat > "$TMP" <<EOF
WAYFINDING_ADMIN_PWHASH=${HASH}
WAYFINDING_SECRET=${SECRET}
EOF

# Move into place + lock down
if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  sudo mv "$TMP" "$OUT"
  sudo chown root:www-data "$OUT"
  sudo chmod 0640 "$OUT"
else
  mv "$TMP" "$OUT"
  chown root:www-data "$OUT"
  chmod 0640 "$OUT"
fi

echo "✅ Created $OUT (owner root:www-data, mode 0640)."
echo "   Hash/secret not printed."

