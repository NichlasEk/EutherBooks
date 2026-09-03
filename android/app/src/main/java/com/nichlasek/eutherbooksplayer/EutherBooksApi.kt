package com.nichlasek.eutherbooksplayer

import android.content.Context
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.concurrent.TimeUnit

class EutherBooksApi(context: Context) {
    private val preferences = AppPreferences(context)
    private val gson = Gson()
    private val client = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    @Volatile
    var activeBaseUrl: String = preferences.preferredServer
        private set

    suspend fun discoverRoutes(): RouteConfig = withContext(Dispatchers.IO) {
        val hosts = linkedSetOf(
            hostBaseUrl(preferences.preferredServer),
            AppPreferences.DEFAULT_LAN_HOST,
            AppPreferences.DEFAULT_PUBLIC_HOST,
            "https://apothictech.se",
        )
        for (host in hosts) {
            runCatching {
                executeJson<RouteConfig>(Request.Builder().url("$host/api/app/config").get().build())
            }.getOrNull()?.let { config ->
                preferences.routeConfig = config
                return@withContext config
            }
        }
        preferences.routeConfig
    }

    suspend fun login(username: String, password: String): LoginResponse = withContext(Dispatchers.IO) {
        val config = discoverRoutes()
        val hosts = hostCandidates(config)
        var lastError: Throwable? = null
        for (host in hosts) {
            try {
                val json = gson.toJson(mapOf("username" to username.trim(), "password" to password))
                val request = Request.Builder()
                    .url("$host/api/app/login")
                    .post(json.toRequestBody(JSON))
                    .build()
                val response = executeJson<LoginResponse>(request)
                require(response.token.isNotBlank()) { "Server returned an empty login token" }
                preferences.username = response.user.ifBlank { username }
                preferences.authToken = response.token
                response.lanServerUrl?.let { lan ->
                    val current = preferences.routeConfig
                    preferences.routeConfig = current.copy(lanServerUrl = lan)
                }
                connect()
                return@withContext response
            } catch (error: Throwable) {
                lastError = error
            }
        }
        throw IOException(lastError?.message ?: "Could not reach the login server", lastError)
    }

    suspend fun connect(): Health = request("/health")

    suspend fun books(): List<Book> = request("/books")

    suspend fun chapters(bookId: String): List<Chapter> = request("/books/${segment(bookId)}/chapters")

    suspend fun voices(): List<Voice> = request("/voices")

    suspend fun jobs(bookId: String? = null): List<Job> {
        val suffix = buildString {
            append("/jobs?owner=eutherbooks-player&limit=1000")
            if (!bookId.isNullOrBlank()) append("&book_id=${segment(bookId)}")
        }
        return request(suffix)
    }

    suspend fun job(jobId: String): Job = request("/jobs/${segment(jobId)}")

    suspend fun createJob(
        book: Book,
        chapter: Chapter,
        voice: Voice,
        modelBackend: String,
        cancelExisting: Boolean = true,
    ): Job {
        val options = linkedMapOf<String, Any?>(
            "chapters" to listOf(chapter.index),
            "voice" to voice.id,
            "language" to if (voice.language == "en") "en" else "sv",
            "model_backend" to modelBackend,
            "owner" to "eutherbooks-player",
            "cancel_existing" to cancelExisting,
            "force_regenerate" to false,
            "queue_remainder" to false,
        )
        voice.defaultLengthScale?.let { options["length_scale"] = it }
        voice.defaultSeed?.let { options["seed"] = it }
        if (modelBackend == "dots.tts-mf" || modelBackend == "dots.tts-soar") {
            options += mapOf(
                "cfg_value" to 2.8,
                "inference_timesteps" to 13,
                "dots_template_name" to "tts",
                "dots_ode_method" to "euler",
                "dots_num_steps" to if (modelBackend == "dots.tts-mf") 4 else 10,
                "dots_guidance_scale" to 1.2,
                "dots_speaker_scale" to 1.5,
                "dots_max_generate_length" to 500,
                "max_chunk_chars" to 520,
            )
        }
        return request(
            path = "/books/${segment(book.id)}/tts",
            method = "POST",
            body = gson.toJson(options),
        )
    }

    fun audioUrl(path: String): String = "$activeBaseUrl/audio/${path.split('/').joinToString("/") { segment(it) }}"

    private suspend inline fun <reified T> request(path: String, method: String = "GET", body: String? = null): T =
        withContext(Dispatchers.IO) {
            val token = preferences.authToken
            var lastError: Throwable? = null
            for (base in serverCandidates()) {
                try {
                    val builder = Request.Builder()
                        .url("$base$path")
                        .header("Accept", "application/json")
                    if (token.isNotBlank()) builder.header("X-Euther-App-Token", token)
                    if (method == "POST") builder.post((body ?: "{}").toRequestBody(JSON)) else builder.get()
                    val value: T = executeJson(builder.build())
                    activeBaseUrl = base
                    preferences.preferredServer = base
                    return@withContext value
                } catch (error: Throwable) {
                    lastError = error
                }
            }
            throw IOException(lastError?.message ?: "No EutherBooks server responded", lastError)
        }

    private inline fun <reified T> executeJson(request: Request): T {
        client.newCall(request).execute().use { response ->
            val payload = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                throw IOException("${response.code} ${response.message}${payload.takeIf(String::isNotBlank)?.let { ": $it" }.orEmpty()}")
            }
            return gson.fromJson(payload, object : TypeToken<T>() {}.type)
        }
    }

    private fun serverCandidates(): List<String> {
        val config = preferences.routeConfig
        return linkedSetOf<String>().apply {
            add(normalizeBaseUrl(preferences.preferredServer))
            config.eutherbooksUrls.forEach { add(normalizeBaseUrl(it)) }
            config.lanServerUrl?.let { add(normalizeBaseUrl(it)) }
            config.publicServerUrl?.let { add(normalizeBaseUrl(it)) }
            add(AppPreferences.DEFAULT_LAN_BOOKS)
            add(AppPreferences.DEFAULT_PUBLIC_BOOKS)
            add("https://apothictech.se/eutherbooks")
        }.toList()
    }

    private fun hostCandidates(config: RouteConfig): List<String> = linkedSetOf<String>().apply {
        add(hostBaseUrl(preferences.preferredServer))
        config.lanServerUrl?.trimEnd('/')?.let(::add)
        config.publicServerUrl?.trimEnd('/')?.let(::add)
        config.serverUrls.map { it.trimEnd('/') }.forEach(::add)
        add(AppPreferences.DEFAULT_LAN_HOST)
        add(AppPreferences.DEFAULT_PUBLIC_HOST)
        add("https://apothictech.se")
    }.toList()

    companion object {
        private val JSON = "application/json; charset=utf-8".toMediaType()

        internal fun segment(value: String): String =
            URLEncoder.encode(value, StandardCharsets.UTF_8.toString()).replace("+", "%20")
    }
}
