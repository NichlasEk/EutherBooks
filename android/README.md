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
directory. Sign through environment variables or an interactive password
prompt and verify both the certificate fingerprint and APK hash afterward.

## Architecture

- `EutherBooksApi.kt`: HTTP API, authentication headers, and route failover.
- `PlaybackService.kt`: the only owner of ExoPlayer, queue, cache, and session.
- `MainViewModel.kt`: app state, TTS job polling, lookahead, bookmarks, and timer.
- `AppUi.kt`: Compose UI; it controls playback through `MediaController` only.

The Python service remains the source of truth for books, voices, TTS jobs,
and generated audio. The Android app does not duplicate server job state.
