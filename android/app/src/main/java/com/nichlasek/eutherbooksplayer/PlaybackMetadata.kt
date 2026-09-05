package com.nichlasek.eutherbooksplayer

import android.os.Bundle
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata

internal fun MediaItem.queueEntry(): QueueEntry {
    val extras = mediaMetadata.extras
    return QueueEntry(
        uri = localConfiguration?.uri?.toString().orEmpty(),
        mediaId = mediaId,
        title = mediaMetadata.title?.toString().orEmpty(),
        subtitle = mediaMetadata.subtitle?.toString().orEmpty(),
        bookId = extras?.getString("bookId").orEmpty(),
        chapterIndex = extras?.getInt("chapterIndex", -1) ?: -1,
        chapterTitle = extras?.getString("chapterTitle").orEmpty(),
        voiceId = extras?.getString("voiceId").orEmpty(),
        modelBackend = extras?.getString("modelBackend").orEmpty(),
        partIndex = extras?.getInt("partIndex") ?: 0,
        durationMs = extras?.getLong("durationMs") ?: 0,
        chapterComplete = extras?.getBoolean("chapterComplete") ?: false,
    )
}

internal fun QueueEntry.toMediaItem(): MediaItem = MediaItem.Builder()
    .setUri(uri)
    .setMediaId(mediaId)
    .setMediaMetadata(
        MediaMetadata.Builder()
            .setTitle(title)
            .setSubtitle(subtitle)
            .setArtist("EutherBooks")
            .setExtras(Bundle().apply {
                putString("bookId", bookId)
                putInt("chapterIndex", chapterIndex)
                putString("chapterTitle", chapterTitle)
                putString("voiceId", voiceId)
                putString("modelBackend", modelBackend)
                putInt("partIndex", partIndex)
                putLong("durationMs", durationMs)
                putBoolean("chapterComplete", chapterComplete)
            })
            .build(),
    )
    .build()

internal fun QueueEntry.bookmark(positionMs: Long, nowMs: Long = System.currentTimeMillis()): Bookmark? =
    if (bookId.isNullOrBlank() || chapterIndex < 0 || voiceId.isNullOrBlank()) null else Bookmark(
        bookId, chapterIndex, voiceId, modelBackend, partIndex, positionMs.coerceAtLeast(0), nowMs, chapterTitle.orEmpty(),
    )
