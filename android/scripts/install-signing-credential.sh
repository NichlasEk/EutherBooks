#!/usr/bin/env bash
set -euo pipefail

CREDENTIAL_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/credentials"
CREDENTIAL_FILE="$CREDENTIAL_DIR/eutherbooks-player-keystore-pass.cred"
CREDENTIAL_NAME="eutherbooks-player-keystore-pass"

if ! command -v systemd-creds >/dev/null 2>&1; then
  echo "systemd-creds is required" >&2
  exit 1
fi

umask 077
mkdir -p "$CREDENTIAL_DIR"
chmod 700 "$CREDENTIAL_DIR"

read -r -s -p "APK keystore password: " keystore_password
printf '\n'
if [[ -z "$keystore_password" ]]; then
  echo "Password must not be empty" >&2
  exit 1
fi

temporary_file="${CREDENTIAL_FILE}.tmp"
trap 'unset keystore_password; rm -f "$temporary_file"' EXIT
printf '%s' "$keystore_password" | systemd-creds encrypt \
  --user \
  --name="$CREDENTIAL_NAME" \
  - \
  "$temporary_file" >/dev/null
unset keystore_password
chmod 600 "$temporary_file"
mv "$temporary_file" "$CREDENTIAL_FILE"

echo "Encrypted signing credential installed at $CREDENTIAL_FILE"
