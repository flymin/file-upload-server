#!/usr/bin/env sh
set -eu

ITERATIONS="${PBKDF2_ITERATIONS:-390000}"
MODE="raw"
USERNAME=""

usage() {
  cat <<'EOF' >&2
Usage:
  ./hash-password.sh [password]
  ./hash-password.sh --yaml <username> [password]

Output modes:
  default        print only the pbkdf2 hash
  --yaml USER    print a config.yaml user block
EOF
  exit 1
}

if [ "${1:-}" = "--yaml" ]; then
  MODE="yaml"
  shift
  USERNAME="${1:-}"
  [ -n "$USERNAME" ] || usage
  shift
elif [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  usage
fi

prompt_password() {
  printf 'Password: ' >&2
  stty -echo
  IFS= read -r first
  printf '\nConfirm password: ' >&2
  IFS= read -r second
  stty echo
  printf '\n' >&2
  if [ "$first" != "$second" ]; then
    echo 'Passwords do not match.' >&2
    exit 1
  fi
  PASSWORD="$first"
}

if [ $# -ge 1 ]; then
  PASSWORD="$1"
else
  prompt_password
fi

HASH="$(PASSWORD="$PASSWORD" ITERATIONS="$ITERATIONS" python3 - <<'PY'
import hashlib
import os
import secrets

password = os.environ['PASSWORD']
iterations = int(os.environ['ITERATIONS'])
salt = secrets.token_bytes(16)
digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations).hex()
print(f"pbkdf2_sha256${iterations}${salt.hex()}${digest}")
PY
)"

if [ "$MODE" = "yaml" ]; then
  printf -- "- username: %s\n  display_name: %s\n  password_hash: %s\n" "$USERNAME" "$USERNAME" "$HASH"
else
  printf '%s\n' "$HASH"
fi
