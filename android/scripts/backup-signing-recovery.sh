#!/usr/bin/env bash
set -euo pipefail

umask 077

SIGNING_USER="${EUTHERBOOKS_SIGNING_USER:-nichlas}"
SIGNING_UID="$(id -u "$SIGNING_USER")"
SIGNING_HOME="$(getent passwd "$SIGNING_USER" | cut -d: -f6)"
KEYSTORE="${EUTHERBOOKS_PLAYER_KEYSTORE:-$SIGNING_HOME/.eutherlist/eutherlist-sideload.jks}"
KEY_ALIAS="${EUTHERBOOKS_PLAYER_KEY_ALIAS:-eutherlist}"
CREDENTIAL_NAME="eutherbooks-player-keystore-pass"
CREDENTIAL_FILE="${EUTHERBOOKS_PLAYER_CREDENTIAL:-$SIGNING_HOME/.config/credentials/$CREDENTIAL_NAME.cred}"
RECIPIENT_FILE="${EUTHERHOST_BACKUP_RECIPIENTS:-/etc/eutheroxide-backup/recipients}"
BACKUP_DIR="${EUTHERHOST_BACKUP_DIR:-/srv/backups/eutheroxide/state}"
BACKUP_GROUP="${EUTHERHOST_BACKUP_GROUP:-eutherbackup}"
RETENTION_DAYS="${EUTHERBOOKS_SIGNING_RETENTION_DAYS:-30}"
EXPECTED_CERT_SHA256="b9ff592d5c8b183c339836537b43e2b0f6b7e65618db084f4e84631ef9fd9c3c"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE_NAME="eutherhost-state-eutherbooks-signing-$TIMESTAMP.tar.gz.age"
STAGING=""

cleanup() {
  unset PASSWORD STORE_PASS
  [[ -z "$STAGING" ]] || rm -rf -- "$STAGING"
}
trap cleanup EXIT

[[ "$EUID" -eq 0 ]] || { echo "signing recovery backup must run as root" >&2; exit 1; }
for command_name in age flock getent keytool openssl sha256sum systemd-creds tar; do
  command -v "$command_name" >/dev/null 2>&1 || { echo "$command_name is required" >&2; exit 1; }
done
for required_file in "$KEYSTORE" "$CREDENTIAL_FILE" "$RECIPIENT_FILE"; do
  [[ -f "$required_file" ]] || { echo "required file not found: $required_file" >&2; exit 1; }
done
grep -Evq '^(#|$|ssh-ed25519 |ssh-rsa )' "$RECIPIENT_FILE" && {
  echo "recipients file contains unsupported entries" >&2
  exit 1
}
getent group "$BACKUP_GROUP" >/dev/null

exec 9>/run/euthervault-backup.lock
flock -n 9 || { echo "another EutherVault backup is active" >&2; exit 1; }

# The systemd credential is intentionally tied to this user and machine. For
# disaster recovery we place its plaintext value only in a RAM-backed staging
# directory, then encrypt the complete portable bundle to the off-host age key.
PASSWORD="$(systemd-creds decrypt --user --uid="$SIGNING_UID" \
  --name="$CREDENTIAL_NAME" "$CREDENTIAL_FILE" -)"
[[ -n "$PASSWORD" ]] || { echo "decrypted signing password is empty" >&2; exit 1; }
export STORE_PASS="$PASSWORD"
keytool -list -keystore "$KEYSTORE" -storepass:env STORE_PASS -alias "$KEY_ALIAS" >/dev/null

CERT_SHA256="$(keytool -exportcert -rfc -keystore "$KEYSTORE" \
  -storepass:env STORE_PASS -alias "$KEY_ALIAS" 2>/dev/null \
  | openssl x509 -noout -fingerprint -sha256 \
  | cut -d= -f2 | tr -d ':' | tr '[:upper:]' '[:lower:]')"
[[ "$CERT_SHA256" == "$EXPECTED_CERT_SHA256" ]] || {
  echo "refusing backup: signing certificate identity changed" >&2
  exit 1
}

install -d -m 0750 -o root -g "$BACKUP_GROUP" "$BACKUP_DIR"
STAGING="$(mktemp -d /run/eutherbooks-signing-recovery.XXXXXX)"
install -d -m 0700 "$STAGING/payload"
install -m 0600 "$KEYSTORE" "$STAGING/payload/eutherbooks-player.jks"
printf '%s' "$PASSWORD" > "$STAGING/payload/keystore-password.txt"
chmod 0600 "$STAGING/payload/keystore-password.txt"
KEYSTORE_SHA256="$(sha256sum "$KEYSTORE" | awk '{print $1}')"
cat > "$STAGING/payload/RECOVERY.txt" <<EOF
EutherBooks Player portable signing recovery
created_utc=$TIMESTAMP
package_id=com.nichlasek.eutherbooksplayer
key_alias=$KEY_ALIAS
certificate_sha256=$CERT_SHA256
keystore_sha256=$KEYSTORE_SHA256

Decrypt this outer archive only on a trusted recovery machine. The password
inside keystore-password.txt belongs only to the bundled keystore. Never place
it in Git, Gradle properties, shell history, or an unencrypted backup.
EOF
chmod 0600 "$STAGING/payload/RECOVERY.txt"
sha256sum "$STAGING/payload/eutherbooks-player.jks" \
  "$STAGING/payload/keystore-password.txt" \
  "$STAGING/payload/RECOVERY.txt" > "$STAGING/payload/SHA256SUMS"

ENCRYPTED="$STAGING/$ARCHIVE_NAME"
tar -C "$STAGING/payload" --sort=name --owner=0 --group=0 --numeric-owner -czf - . \
  | age --encrypt --recipients-file "$RECIPIENT_FILE" --output "$ENCRYPTED"
[[ "$(head -n 1 "$ENCRYPTED")" == "age-encryption.org/v1" ]]
chmod 0640 "$ENCRYPTED"
chown root:"$BACKUP_GROUP" "$ENCRYPTED"
mv -- "$ENCRYPTED" "$BACKUP_DIR/$ARCHIVE_NAME"
(
  cd "$BACKUP_DIR"
  sha256sum "$ARCHIVE_NAME"
) > "$BACKUP_DIR/$ARCHIVE_NAME.sha256"
chmod 0640 "$BACKUP_DIR/$ARCHIVE_NAME.sha256"
chown root:"$BACKUP_GROUP" "$BACKUP_DIR/$ARCHIVE_NAME.sha256"

find "$BACKUP_DIR" -maxdepth 1 -type f \
  \( -name 'eutherhost-state-eutherbooks-signing-*.tar.gz.age' \
     -o -name 'eutherhost-state-eutherbooks-signing-*.tar.gz.age.sha256' \) \
  -mtime "+$RETENTION_DAYS" -delete

printf 'created %s (certificate_sha256=%s)\n' "$BACKUP_DIR/$ARCHIVE_NAME" "$CERT_SHA256"
