package com.nichlasek.eutherbooksplayer

import android.content.Context
import com.google.gson.Gson
import java.io.File

class AppPreferences(context: Context) {
    private val appContext = context.applicationContext
    private val prefs = appContext.getSharedPreferences(FILE_NAME, Context.MODE_PRIVATE)
    private val gson = Gson()

    var authToken: String
        get() = prefs.getString(KEY_TOKEN, null)?.trim() ?: importLegacyToken()
        set(value) { prefs.edit().putString(KEY_TOKEN, value.trim()).apply() }

    var username: String
        get() = prefs.getString(KEY_USERNAME, "nichlas").orEmpty()
        set(value) { prefs.edit().putString(KEY_USERNAME, value.trim()).apply() }

    var preferredServer: String
        get() = prefs.getString(KEY_SERVER, DEFAULT_PUBLIC_BOOKS).orEmpty()
        set(value) { prefs.edit().putString(KEY_SERVER, normalizeBaseUrl(value)).apply() }

    var routeConfig: RouteConfig
        get() = runCatching {
            gson.fromJson(prefs.getString(KEY_ROUTES, "{}"), RouteConfig::class.java)
        }.getOrNull() ?: RouteConfig()
        set(value) { prefs.edit().putString(KEY_ROUTES, gson.toJson(value)).apply() }

    var voiceId: String
        get() = prefs.getString(KEY_VOICE, "dots-mf-own-sv").orEmpty()
        set(value) { prefs.edit().putString(KEY_VOICE, value).apply() }

    var modelBackend: String
        get() = prefs.getString(KEY_MODEL, "dots.tts-mf").orEmpty()
        set(value) { prefs.edit().putString(KEY_MODEL, value).apply() }

    var autoNext: Boolean
        get() = prefs.getBoolean(KEY_AUTO_NEXT, true)
        set(value) { prefs.edit().putBoolean(KEY_AUTO_NEXT, value).apply() }

    var savedQueue: SavedQueue?
        get() = runCatching {
            prefs.getString(KEY_QUEUE, null)?.let { gson.fromJson(it, SavedQueue::class.java) }
        }.getOrNull()
        set(value) {
            prefs.edit().apply {
                if (value == null) remove(KEY_QUEUE) else putString(KEY_QUEUE, gson.toJson(value))
            }.apply()
        }

    fun saveBookmark(bookmark: Bookmark) {
        prefs.edit().putString(bookmarkKey(bookmark.bookId, bookmark.chapterIndex, bookmark.voiceId, bookmark.modelBackend), gson.toJson(bookmark)).apply()
    }

    fun bookmark(bookId: String, chapterIndex: Int, voiceId: String, modelBackend: String): Bookmark? =
        runCatching {
            prefs.getString(bookmarkKey(bookId, chapterIndex, voiceId, modelBackend), null)
                ?.let { gson.fromJson(it, Bookmark::class.java) }
        }.getOrNull()

    fun logout() {
        // Keep an explicit empty value so a legacy Tauri token is not re-imported after logout.
        prefs.edit().putString(KEY_TOKEN, "").apply()
    }

    private fun importLegacyToken(): String {
        val candidates = listOf(
            File(appContext.filesDir, "auth-token"),
            File(appContext.dataDir, "auth-token"),
        )
        val token = candidates.firstNotNullOfOrNull { file ->
            runCatching { file.takeIf(File::isFile)?.readText()?.trim() }.getOrNull()
                ?.takeIf { it.length in 16..512 }
        }.orEmpty()
        if (token.isNotBlank()) {
            prefs.edit().putString(KEY_TOKEN, token).apply()
        }
        return token
    }

    companion object {
        const val DEFAULT_PUBLIC_HOST = "https://apothictech.se:8443"
        const val DEFAULT_PUBLIC_BOOKS = "$DEFAULT_PUBLIC_HOST/eutherbooks"
        const val DEFAULT_LAN_HOST = "http://192.168.32.186:8080"
        const val DEFAULT_LAN_BOOKS = "$DEFAULT_LAN_HOST/eutherbooks"

        private const val FILE_NAME = "eutherbooks-native"
        private const val KEY_TOKEN = "auth_token"
        private const val KEY_USERNAME = "username"
        private const val KEY_SERVER = "server"
        private const val KEY_ROUTES = "routes"
        private const val KEY_VOICE = "voice"
        private const val KEY_MODEL = "model"
        private const val KEY_AUTO_NEXT = "auto_next"
        private const val KEY_QUEUE = "queue"

        fun bookmarkKey(bookId: String, chapter: Int, voice: String, model: String) =
            "bookmark:$bookId:$chapter:$voice:$model"
    }
}

internal fun normalizeBaseUrl(value: String): String {
    var clean = value.trim().replace("apothichtech.se", "apothictech.se", ignoreCase = true).trimEnd('/')
    if (clean.isBlank()) return AppPreferences.DEFAULT_PUBLIC_BOOKS
    if (clean == "https://apothictech.se") clean = AppPreferences.DEFAULT_PUBLIC_HOST
    if (!clean.endsWith("/eutherbooks")) clean += "/eutherbooks"
    return clean
}

internal fun hostBaseUrl(eutherBooksUrl: String): String =
    normalizeBaseUrl(eutherBooksUrl).removeSuffix("/eutherbooks")
