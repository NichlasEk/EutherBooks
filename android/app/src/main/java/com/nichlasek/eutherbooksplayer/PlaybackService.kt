package com.nichlasek.eutherbooksplayer

import android.content.Context
import android.net.Uri
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.database.StandaloneDatabaseProvider
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.datasource.TransferListener
import androidx.media3.datasource.cache.CacheDataSource
import androidx.media3.datasource.cache.LeastRecentlyUsedCacheEvictor
import androidx.media3.datasource.cache.SimpleCache
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.io.File
import java.io.IOException

@UnstableApi
class PlaybackService : MediaSessionService() {
    private lateinit var player: ExoPlayer
    private var mediaSession: MediaSession? = null
    private var audioCache: SimpleCache? = null
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var persistenceJob: Job? = null

    override fun onCreate() {
        super.onCreate()
        val cache = SimpleCache(
            File(cacheDir, "eutherbooks-media3"),
            LeastRecentlyUsedCacheEvictor(2L * 1024 * 1024 * 1024),
            StandaloneDatabaseProvider(this),
        )
        audioCache = cache
        val cacheFactory = CacheDataSource.Factory()
            .setCache(cache)
            .setUpstreamDataSourceFactory(FailoverHttpDataSourceFactory(this))
            .setFlags(CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR)

        player = ExoPlayer.Builder(this)
            .setMediaSourceFactory(DefaultMediaSourceFactory(cacheFactory))
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setContentType(C.AUDIO_CONTENT_TYPE_SPEECH)
                    .setUsage(C.USAGE_MEDIA)
                    .build(),
                true,
            )
            .setHandleAudioBecomingNoisy(true)
            .build()

        player.addListener(object : Player.Listener {
            override fun onEvents(player: Player, events: Player.Events) {
                if (events.containsAny(
                        Player.EVENT_MEDIA_ITEM_TRANSITION,
                        Player.EVENT_PLAY_WHEN_READY_CHANGED,
                        Player.EVENT_PLAYBACK_STATE_CHANGED,
                    )
                ) {
                    persistQueue()
                }
            }
        })
        restoreQueue()
        mediaSession = MediaSession.Builder(this, player).build()
        persistenceJob = serviceScope.launch {
            while (isActive) {
                delay(5_000)
                persistQueue()
            }
        }
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? = mediaSession

    override fun onDestroy() {
        persistQueue()
        persistenceJob?.cancel()
        mediaSession?.run {
            player.release()
            release()
        }
        mediaSession = null
        audioCache?.release()
        audioCache = null
        serviceScope.cancel()
        super.onDestroy()
    }

    private fun restoreQueue() {
        val saved = AppPreferences(this).savedQueue ?: return
        if (saved.entries.isEmpty()) return
        val items = saved.entries.map { it.toMediaItem() }
        player.setMediaItems(items, saved.index.coerceIn(items.indices), saved.positionMs.coerceAtLeast(0))
        player.prepare()
        player.playWhenReady = saved.playWhenReady
    }

    private fun persistQueue() {
        if (!::player.isInitialized || player.mediaItemCount == 0) return
        val entries = (0 until player.mediaItemCount).map { index ->
            val item = player.getMediaItemAt(index)
            QueueEntry(
                uri = item.localConfiguration?.uri?.toString().orEmpty(),
                mediaId = item.mediaId,
                title = item.mediaMetadata.title?.toString().orEmpty(),
                subtitle = item.mediaMetadata.subtitle?.toString().orEmpty(),
            )
        }.filter { it.uri.isNotBlank() }
        AppPreferences(this).savedQueue = SavedQueue(
            entries = entries,
            index = player.currentMediaItemIndex.coerceAtLeast(0),
            positionMs = player.currentPosition.coerceAtLeast(0),
            playWhenReady = player.playWhenReady,
        )
    }
}

internal fun QueueEntry.toMediaItem(): MediaItem = MediaItem.Builder()
    .setUri(uri)
    .setMediaId(mediaId)
    .setMediaMetadata(
        MediaMetadata.Builder()
            .setTitle(title)
            .setSubtitle(subtitle)
            .setArtist("EutherBooks")
            .build(),
    )
    .build()

@UnstableApi
private class FailoverHttpDataSourceFactory(context: Context) : DataSource.Factory {
    private val appContext = context.applicationContext

    override fun createDataSource(): DataSource = FailoverHttpDataSource(appContext)
}

@UnstableApi
private class FailoverHttpDataSource(context: Context) : DataSource {
    private val appContext = context.applicationContext
    private val listeners = mutableListOf<TransferListener>()
    private var active: DataSource? = null

    override fun addTransferListener(transferListener: TransferListener) {
        listeners += transferListener
    }

    override fun open(dataSpec: DataSpec): Long {
        var lastError: IOException? = null
        for (uri in audioRouteCandidates(dataSpec.uri, AppPreferences(appContext))) {
            val source = createHttpSource()
            listeners.forEach(source::addTransferListener)
            try {
                val length = source.open(dataSpec.withUri(uri))
                active = source
                return length
            } catch (error: IOException) {
                lastError = error
                runCatching { source.close() }
            }
        }
        throw lastError ?: IOException("No EutherBooks audio route responded")
    }

    override fun read(buffer: ByteArray, offset: Int, length: Int): Int =
        active?.read(buffer, offset, length) ?: throw IOException("Audio source is not open")

    override fun getUri(): Uri? = active?.uri

    override fun getResponseHeaders(): Map<String, List<String>> = active?.responseHeaders ?: emptyMap()

    override fun close() {
        active?.close()
        active = null
    }

    private fun createHttpSource(): DataSource {
        val token = AppPreferences(appContext).authToken
        return DefaultHttpDataSource.Factory()
            .setUserAgent("EutherBooksPlayer/0.2.0-alpha.2")
            .setAllowCrossProtocolRedirects(true)
            .apply {
                if (token.isNotBlank()) {
                    setDefaultRequestProperties(mapOf("X-Euther-App-Token" to token))
                }
            }
            .createDataSource()
    }
}

internal fun audioRouteCandidates(original: Uri, preferences: AppPreferences): List<Uri> {
    val path = original.encodedPath.orEmpty()
    val marker = "/eutherbooks"
    val markerIndex = path.indexOf(marker)
    if (markerIndex < 0) return listOf(original)
    val suffix = path.substring(markerIndex + marker.length)
    val config = preferences.routeConfig
    val bases = linkedSetOf(
        original.toString().substringBefore(marker),
        preferences.preferredServer.removeSuffix(marker),
        config.lanServerUrl.orEmpty().trimEnd('/'),
        config.publicServerUrl.orEmpty().trimEnd('/'),
        AppPreferences.DEFAULT_LAN_HOST,
        AppPreferences.DEFAULT_PUBLIC_HOST,
        "https://apothictech.se",
    ).filter { it.isNotBlank() }
    return bases.map { base -> Uri.parse("${base.trimEnd('/')}$marker$suffix") }.distinct()
}
