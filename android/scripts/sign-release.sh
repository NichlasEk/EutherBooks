#!/usr/bin/env bash
set -euo pipefail

ANDROID_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INPUT_APK="${1:-$ANDROID_DIR/app/build/outputs/apk/release/app-release-unsigned.apk}"
OUTPUT_APK="${2:-$ANDROID_DIR/app/build/outputs/apk/release/EutherBooksPlayer-0.2.0-alpha.1-signed.apk}"
KEYSTORE="${EUTHERBOOKS_PLAYER_KEYSTORE:-$HOME/.eutherlist/eutherlist-sideload.jks}"
KEY_ALIAS="${EUTHERBOOKS_PLAYER_KEY_ALIAS:-eutherlist}"
CREDENTIAL_NAME="eutherbooks-player-keystore-pass"
CREDENTIAL_FILE="${EUTHERBOOKS_PLAYER_CREDENTIAL:-${XDG_CONFIG_HOME:-$HOME/.config}/credentials/$CREDENTIAL_NAME.cred}"
EXPECTED_CERT_SHA256="b9ff592d5c8b183c339836537b43e2b0f6b7e65618db084f4e84631ef9fd9c3c"
EXPECTED_APPLICATION_ID="com.nichlasek.eutherbooksplayer"
EXPECTED_VERSION_CODE="1078"

for command_name in systemd-creds apksigner aapt sha256sum; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "$command_name is required" >&2
    exit 1
  fi
done

if [[ ! -f "$INPUT_APK" ]]; then
  echo "Unsigned APK not found: $INPUT_APK" >&2
  exit 1
fi
if [[ ! -f "$KEYSTORE" ]]; then
  echo "Signing keystore not found: $KEYSTORE" >&2
  exit 1
fi
if [[ ! -f "$CREDENTIAL_FILE" ]]; then
  echo "Encrypted credential not found: $CREDENTIAL_FILE" >&2
  echo "Run android/scripts/install-signing-credential.sh first." >&2
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT_APK")"
keystore_password="$(systemd-creds decrypt --user --name="$CREDENTIAL_NAME" "$CREDENTIAL_FILE" -)"
trap 'unset keystore_password' EXIT
if [[ -z "$keystore_password" ]]; then
  echo "The decrypted signing password is empty" >&2
  exit 1
fi

printf '%s\n%s\n' "$keystore_password" "$keystore_password" | apksigner sign \
  --ks "$KEYSTORE" \
  --ks-key-alias "$KEY_ALIAS" \
  --ks-pass stdin \
  --key-pass stdin \
  --out "$OUTPUT_APK" \
  "$INPUT_APK"
unset keystore_password

apksigner verify --verbose "$OUTPUT_APK"
actual_cert="$(apksigner verify --print-certs "$OUTPUT_APK" | sed -n 's/^Signer #1 certificate SHA-256 digest: //p')"
if [[ "$actual_cert" != "$EXPECTED_CERT_SHA256" ]]; then
  echo "Refusing release: signing certificate does not match the established app identity" >&2
  exit 1
fi

badging="$(aapt dump badging "$OUTPUT_APK" | head -1)"
if [[ "$badging" != *"name='$EXPECTED_APPLICATION_ID'"* ]]; then
  echo "Refusing release: application ID is not $EXPECTED_APPLICATION_ID" >&2
  exit 1
fi
if [[ "$badging" != *"versionCode='$EXPECTED_VERSION_CODE'"* ]]; then
  echo "Refusing release: version code is not $EXPECTED_VERSION_CODE" >&2
  exit 1
fi

echo "Signed release verified"
echo "certificate_sha256=$actual_cert"
sha256sum "$OUTPUT_APK"
