package com.nichlasek.eutherbooksplayer

import com.google.gson.annotations.SerializedName

data class Book(
    val id: String = "",
    val title: String = "Untitled",
    val author: String? = null,
    val format: String = "",
)

data class Chapter(
    val index: Int = 0,
    val title: String = "Chapter",
    @SerializedName("char_count") val charCount: Int = 0,
)

data class Voice(
    val id: String = "",
    val label: String = "",
    val language: String = "",
    val backend: String = "",
    val path: String = "",
    @SerializedName("model_backend") val modelBackend: String? = null,
    @SerializedName("default_length_scale") val defaultLengthScale: Double? = null,
    @SerializedName("default_seed") val defaultSeed: Long? = null,
)

data class Job(
    val id: String = "",
    @SerializedName("book_id") val bookId: String = "",
    val status: String = "",
    val language: String = "",
    val voice: String = "",
    @SerializedName("chapter_indexes") val chapterIndexes: List<Int> = emptyList(),
    val owner: String = "",
    @SerializedName("audio_files") val audioFiles: List<String> = emptyList(),
    @SerializedName("audio_durations") val audioDurations: List<Double> = emptyList(),
    @SerializedName("total_audio_files") val totalAudioFiles: Int = 0,
    @SerializedName("tts_options") val ttsOptions: Map<String, Any?> = emptyMap(),
    @SerializedName("progress_label") val progressLabel: String = "",
    @SerializedName("progress_detail") val progressDetail: String = "",
    @SerializedName("current_chapter_index") val currentChapterIndex: Int? = null,
    @SerializedName("current_chunk_index") val currentChunkIndex: Int = 0,
    @SerializedName("worker_progress") val workerProgress: Double = 0.0,
    @SerializedName("total_chunks") val totalChunks: Int = 0,
    val error: String? = null,
)

data class Health(
    val status: String = "",
    @SerializedName("tts_backend") val ttsBackend: String = "",
)

data class RouteConfig(
    val publicServerUrl: String? = null,
    val lanServerUrl: String? = null,
    val serverUrls: List<String> = emptyList(),
    val eutherbooksUrls: List<String> = emptyList(),
)

data class LoginResponse(
    val token: String = "",
    val user: String = "",
    val lanServerUrl: String? = null,
)

data class Bookmark(
    val bookId: String,
    val chapterIndex: Int,
    val voiceId: String,
    val modelBackend: String,
    val mediaIndex: Int,
    val positionMs: Long,
    val updatedAtMs: Long,
    val chapterTitle: String = "",
)

data class BookVoice(val voiceId: String, val modelBackend: String)

data class QueueEntry(
    val uri: String,
    val mediaId: String,
    val title: String,
    val subtitle: String,
    val bookId: String = "",
    val chapterIndex: Int = -1,
    val chapterTitle: String = "",
    val voiceId: String = "",
    val modelBackend: String = "",
    val partIndex: Int = 0,
    val durationMs: Long = 0,
    val chapterComplete: Boolean = false,
)

data class SavedQueue(
    val entries: List<QueueEntry> = emptyList(),
    val index: Int = 0,
    val positionMs: Long = 0,
    val playWhenReady: Boolean = false,
)
