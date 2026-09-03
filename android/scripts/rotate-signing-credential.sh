#!/usr/bin/env bash
set -euo pipefail

ANDROID_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROBE_APK="${1:-$ANDROID_DIR/app/build/outputs/apk/release/app-release-unsigned.apk}"
KEYSTORE="${EUTHERBOOKS_PLAYER_KEYSTORE:-$HOME/.eutherlist/eutherlist-sideload.jks}"
KEY_ALIAS="${EUTHERBOOKS_PLAYER_KEY_ALIAS:-eutherlist}"
CREDENTIAL_NAME="eutherbooks-player-keystore-pass"
CREDENTIAL_FILE="${EUTHERBOOKS_PLAYER_CREDENTIAL:-${XDG_CONFIG_HOME:-$HOME/.config}/credentials/$CREDENTIAL_NAME.cred}"
EXPECTED_CERT_SHA256="b9ff592d5c8b183c339836537b43e2b0f6b7e65618db084f4e84631ef9fd9c3c"
BACKUP_DIR="$(dirname "$KEYSTORE")/backups"
BACKUP_FILE="$BACKUP_DIR/$(basename "$KEYSTORE").before-password-rotation-$(date -u +%Y%m%dT%H%M%SZ)"
WORK_KEYSTORE="${KEYSTORE}.rotate.$$"
WORK_CREDENTIAL="${CREDENTIAL_FILE}.rotate.$$"
PROBE_OUTPUT="${TMPDIR:-/tmp}/eutherbooks-signing-rotation-probe.$$.apk"

for command_name in systemd-creds keytool openssl apksigner sha256sum; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "$command_name is required" >&2
    exit 1
  }
done
for required_file in "$KEYSTORE" "$CREDENTIAL_FILE" "$PROBE_APK"; do
  [[ -f "$required_file" ]] || {
    echo "Required file not found: $required_file" >&2
    exit 1
  }
done

umask 077
mkdir -p "$BACKUP_DIR" "$(dirname "$CREDENTIAL_FILE")"
chmod 700 "$BACKUP_DIR" "$(dirname "$CREDENTIAL_FILE")"
cp -p "$KEYSTORE" "$WORK_KEYSTORE"

old_password="$(systemd-creds decrypt --user --name="$CREDENTIAL_NAME" "$CREDENTIAL_FILE" -)"
new_password="$(openssl rand -base64 36 | tr -d '\n')"
cleanup() {
  unset old_password new_password OLD_PASS NEW_PASS
  rm -f "$WORK_KEYSTORE" "$WORK_CREDENTIAL" "$PROBE_OUTPUT"
}
trap cleanup EXIT

export OLD_PASS="$old_password"
export NEW_PASS="$new_password"
keytool -storepasswd \
  -keystore "$WORK_KEYSTORE" \
  -storepass:env OLD_PASS \
  -new:env NEW_PASS
unset OLD_PASS

printf '%s\n%s\n' "$new_password" "$new_password" | apksigner sign \
  --ks "$WORK_KEYSTORE" \
  --ks-key-alias "$KEY_ALIAS" \
  --ks-pass stdin \
  --key-pass stdin \
  --out "$PROBE_OUTPUT" \
  "$PROBE_APK"

apksigner verify --verbose "$PROBE_OUTPUT" >/dev/null
probe_cert="$(apksigner verify --print-certs "$PROBE_OUTPUT" | sed -n 's/^Signer #1 certificate SHA-256 digest: //p')"
if [[ "$probe_cert" != "$EXPECTED_CERT_SHA256" ]]; then
  echo "Rotation aborted: the probe certificate changed" >&2
  exit 1
fi

printf '%s' "$new_password" | systemd-creds encrypt \
  --user \
  --name="$CREDENTIAL_NAME" \
  - \
  "$WORK_CREDENTIAL" >/dev/null
chmod 600 "$WORK_KEYSTORE" "$WORK_CREDENTIAL"

cp -p "$KEYSTORE" "$BACKUP_FILE"
chmod 600 "$BACKUP_FILE"
mv "$WORK_KEYSTORE" "$KEYSTORE"
mv "$WORK_CREDENTIAL" "$CREDENTIAL_FILE"
unset old_password new_password NEW_PASS

echo "Signing password rotated without changing the signing identity"
echo "certificate_sha256=$probe_cert"
echo "backup=$BACKUP_FILE"
sha256sum "$KEYSTORE" "$CREDENTIAL_FILE" "$BACKUP_FILE"
