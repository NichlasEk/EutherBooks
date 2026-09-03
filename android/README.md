# EutherBooks Player for Android

Native Kotlin/Jetpack Compose client for EutherBooks. It keeps the existing
server API and Android package identity while replacing the Tauri/WebView
runtime with one Media3 playback state machine.

## Current native slice

- Existing EutherOxide login and token reuse.
- Automatic LAN/public server discovery and failover.
- Books, chapters, TTS voices, model selection, and generation jobs.
- Authenticated Media3/ExoPlayer audio queue.
- `MediaSessionService` background playback, notification, lock-screen,
  headset, and Bluetooth controls.
- A bounded 2 GiB on-device audio cache.
- Queue and position recovery after process recreation.
- Per-book/chapter/voice/model bookmarks.
- Automatic generation and queueing of up to three following chapters.
- 15, 30, and 60 minute sleep timers.

The application ID remains `com.nichlasek.eutherbooksplayer`. Version
`0.2.0-alpha.1` uses version code `1078`, directly after the last Tauri release
(`0.1.77`, code `1077`). A release APK must be signed with the existing
EutherBooks/EutherList sideload certificate to upgrade the installed app.

## Build

```bash
cd android
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk
export ANDROID_HOME=/opt/android-sdk
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export GRADLE_USER_HOME="$PWD/../.gradle-local"
./gradlew testDebugUnitTest assembleDebug
./gradlew assembleRelease
```

Unsigned release output:

```text
android/app/build/outputs/apk/release/app-release-unsigned.apk
```

Do not put signing passwords in Gradle files, shell scripts, Git, or this
directory. On the EutherBooks server, install or rotate the user- and
machine-bound encrypted credential through a hidden prompt:

```bash
android/scripts/install-signing-credential.sh
```

Then sign and verify an already-built release:

```bash
android/scripts/sign-release.sh
```

The signing script decrypts the password only in process memory. It refuses
the result unless the package ID, version code, and signing-certificate
fingerprint match the established EutherBooks Player identity. Signing does
not publish or overwrite any downloadable APK; publication is a separate,
deliberate step after device testing.

If a signing password may have been exposed, rotate it without changing the
app's signing identity:

```bash
android/scripts/rotate-signing-credential.sh
```

The rotation runs against a copy, signs a probe APK, verifies the established
certificate fingerprint, keeps a mode-0600 backup of the previous keystore,
and only then replaces the active keystore and encrypted credential.

### Disaster recovery

The normal credential is deliberately tied to the server and cannot by itself
survive total server loss. The server therefore also runs
`eutherbooks-signing-recovery-backup.timer`. It creates a portable bundle with
the keystore and its current password, but stages the plaintext only under the
RAM-backed `/run` filesystem and encrypts the bundle immediately to the
EutherVault age recovery key. The result uses the existing
`eutherhost-state-*.tar.gz.age` naming convention, so the pull-only mirror on
`192.168.32.88` copies and checksum-verifies it automatically.

Install or refresh the server unit after changing the scripts:

```bash
sudo install -m 0644 android/deploy/eutherbooks-signing-recovery-backup.service /etc/systemd/system/
sudo install -m 0644 android/deploy/eutherbooks-signing-recovery-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now eutherbooks-signing-recovery-backup.timer
sudo systemctl start eutherbooks-signing-recovery-backup.service
```

The outer archive must only be decrypted on a trusted recovery machine holding
the private age/SSH identity. Its `RECOVERY.txt` records the immutable package,
alias, certificate fingerprint, and keystore hash. `SHA256SUMS` validates every
file after decryption. The plaintext `keystore-password.txt` must never be
copied out of that protected recovery session.

## Architecture

- `EutherBooksApi.kt`: HTTP API, authentication headers, and route failover.
- `PlaybackService.kt`: the only owner of ExoPlayer, queue, cache, and session.
- `MainViewModel.kt`: app state, TTS job polling, lookahead, bookmarks, and timer.
- `AppUi.kt`: Compose UI; it controls playback through `MediaController` only.

The Python service remains the source of truth for books, voices, TTS jobs,
and generated audio. The Android app does not duplicate server job state.
