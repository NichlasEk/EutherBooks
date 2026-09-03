package com.nichlasek.eutherbooksplayer

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.Player
import androidx.media3.session.MediaController
import kotlinx.coroutines.Job as CoroutineJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

data class PlayerUiState(
    val ready: Boolean = false,
    val playing: Boolean = false,
    val title: String = "",
    val subtitle: String = "",
    val positionMs: Long = 0,
    val durationMs: Long = 0,
    val itemIndex: Int = 0,
    val itemCount: Int = 0,
)

data class AppUiState(
    val authenticated: Boolean = false,
    val connecting: Boolean = false,
    val busy: Boolean = false,
    val serverUrl: String = AppPreferences.DEFAULT_PUBLIC_BOOKS,
    val serverStatus: String = "Not connected",
    val username: String = "nichlas",
    val books: List<Book> = emptyList(),
    val chapters: List<Chapter> = emptyList(),
    val voices: List<Voice> = emptyList(),
    val selectedBook: Book? = null,
    val selectedChapter: Chapter? = null,
    val voiceId: String = "dots-mf-own-sv",
    val modelBackend: String = "dots.tts-mf",
    val autoNext: Boolean = true,
    val activeJob: Job? = null,
    val message: String = "",
    val error: String = "",
    val sleepDeadlineMs: Long? = null,
    val sleepMinutes: Int? = null,
    val player: PlayerUiState = PlayerUiState(),
)

class MainViewModel(application: Application) : AndroidViewModel(application) {
    private val preferences = AppPreferences(application)
    private val api = EutherBooksApi(application)
    private val _state = MutableStateFlow(
        AppUiState(
            authenticated = preferences.authToken.isNotBlank(),
            serverUrl = preferences.preferredServer,
            username = preferences.username,
            voiceId = preferences.voiceId,
            modelBackend = preferences.modelBackend,
            autoNext = preferences.autoNext,
        ),
    )
    val state: StateFlow<AppUiState> = _state.asStateFlow()

    private var controller: MediaController? = null
    private var playerTicker: CoroutineJob? = null
    private var sleepJob: CoroutineJob? = null
    private var generationSerial = 0

    private val playerListener = object : Player.Listener {
        override fun onEvents(player: Player, events: Player.Events) {
            refreshPlayerState()
            if (events.contains(Player.EVENT_MEDIA_ITEM_TRANSITION)) saveAutomaticBookmark()
        }

        override fun onPlayerError(error: androidx.media3.common.PlaybackException) {
            _state.update { it.copy(error = "Playback: ${error.message.orEmpty()}") }
        }
    }

    init {
        viewModelScope.launch {
            runCatching { api.discoverRoutes() }
            if (preferences.authToken.isNotBlank()) connect()
        }
    }

    fun attachController(mediaController: MediaController) {
        controller?.removeListener(playerListener)
        controller = mediaController
        mediaController.addListener(playerListener)
        refreshPlayerState()
        playerTicker?.cancel()
        playerTicker = viewModelScope.launch {
            while (isActive) {
                refreshPlayerState()
                if (mediaController.isPlaying) saveAutomaticBookmark()
                delay(1_000)
            }
        }
    }

    fun login(username: String, password: String) {
        if (username.isBlank() || password.isBlank()) {
            _state.update { it.copy(error = "Enter username and password") }
            return
        }
        viewModelScope.launch {
            _state.update { it.copy(connecting = true, error = "", message = "Signing in…") }
            runCatching { api.login(username, password) }
                .onSuccess {
                    _state.update { state -> state.copy(authenticated = true, username = it.user, message = "Signed in") }
                    loadLibrary()
                }
                .onFailure { error ->
                    _state.update { it.copy(authenticated = false, error = readable(error), message = "") }
                }
            _state.update { it.copy(connecting = false) }
        }
    }

    fun connect() {
        viewModelScope.launch {
            _state.update { it.copy(connecting = true, error = "", message = "Connecting…") }
            runCatching { api.connect() }
                .onSuccess { health ->
                    _state.update {
                        it.copy(
                            authenticated = true,
                            serverUrl = api.activeBaseUrl,
                            serverStatus = "${health.status} · ${health.ttsBackend}",
                            message = "Connected",
                        )
                    }
                    loadLibrary()
                }
                .onFailure { error ->
                    _state.update { it.copy(error = readable(error), serverStatus = "Connection failed") }
                }
            _state.update { it.copy(connecting = false) }
        }
    }

    fun logout() {
        preferences.logout()
        generationSerial += 1
        controller?.pause()
        _state.update {
            AppUiState(
                authenticated = false,
                serverUrl = preferences.preferredServer,
                username = preferences.username,
                player = it.player,
            )
        }
    }

    private suspend fun loadLibrary() {
        _state.update { it.copy(busy = true, error = "", message = "Loading library…") }
        runCatching {
            val books = api.books()
            val voices = api.voices()
            Triple(books, voices, api.connect())
        }.onSuccess { (books, voices, health) ->
            val selectedVoice = selectBestVoice(voices, preferences.modelBackend, preferences.voiceId)
            selectedVoice?.let { preferences.voiceId = it.id }
            _state.update {
                it.copy(
                    authenticated = true,
                    busy = false,
                    books = books,
                    voices = voices,
                    voiceId = selectedVoice?.id ?: preferences.voiceId,
                    serverUrl = api.activeBaseUrl,
                    serverStatus = "${health.status} · ${health.ttsBackend}",
                    message = "${books.size} books",
                )
            }
        }.onFailure { error ->
            _state.update { it.copy(busy = false, error = readable(error), message = "") }
        }
    }

    fun refreshLibrary() {
        viewModelScope.launch { loadLibrary() }
    }

    fun selectBook(book: Book) {
        generationSerial += 1
        viewModelScope.launch {
            _state.update { it.copy(selectedBook = book, selectedChapter = null, chapters = emptyList(), busy = true, error = "") }
            runCatching { api.chapters(book.id) }
                .onSuccess { chapters -> _state.update { it.copy(chapters = chapters, busy = false, message = "${chapters.size} chapters") } }
                .onFailure { error -> _state.update { it.copy(busy = false, error = readable(error)) } }
        }
    }

    fun backToLibrary() {
        generationSerial += 1
        _state.update { it.copy(selectedBook = null, selectedChapter = null, chapters = emptyList(), activeJob = null, error = "") }
    }

    fun selectChapter(chapter: Chapter) {
        _state.update { it.copy(selectedChapter = chapter, activeJob = null, error = "", message = "Ready") }
    }

    fun setModel(model: String) {
        preferences.modelBackend = model
        val voice = selectBestVoice(_state.value.voices, model, "")
        if (voice != null) preferences.voiceId = voice.id
        _state.update { it.copy(modelBackend = model, voiceId = voice?.id ?: it.voiceId) }
    }

    fun setVoice(voiceId: String) {
        preferences.voiceId = voiceId
        _state.update { it.copy(voiceId = voiceId) }
    }

    fun setAutoNext(enabled: Boolean) {
        preferences.autoNext = enabled
        _state.update { it.copy(autoNext = enabled) }
    }

    fun generateOrPlay() {
        val snapshot = _state.value
        val book = snapshot.selectedBook ?: return
        val chapter = snapshot.selectedChapter ?: return
        val voice = snapshot.voices.firstOrNull { it.id == snapshot.voiceId }
        if (voice == null) {
            _state.update { it.copy(error = "No voice selected") }
            return
        }
        if (controller == null) {
            _state.update { it.copy(error = "The playback service is still starting") }
            return
        }
        val serial = ++generationSerial
        viewModelScope.launch {
            _state.update { it.copy(busy = true, error = "", message = "Checking generated audio…") }
            runCatching {
                val jobs = api.jobs(book.id)
                val existing = matchingDoneJob(jobs, chapter, voice, snapshot.modelBackend)
                val job = existing ?: api.createJob(book, chapter, voice, snapshot.modelBackend)
                val finished = awaitJob(job, serial)
                if (serial != generationSerial) return@runCatching
                playJob(book, chapter, voice, finished, jobs + finished)
                if (snapshot.autoNext) prepareLookahead(book, chapter, voice, snapshot.modelBackend, serial)
            }.onFailure { error ->
                if (serial == generationSerial) _state.update { it.copy(busy = false, error = readable(error), message = "") }
            }
        }
    }

    private suspend fun awaitJob(initial: Job, serial: Int): Job {
        var current = initial
        while (current.status == "queued" || current.status == "running") {
            if (serial != generationSerial) throw IllegalStateException("Selection changed")
            _state.update { it.copy(activeJob = current, message = current.progressDetail.ifBlank { current.progressLabel }) }
            delay(2_000)
            current = api.job(current.id)
        }
        if (current.status != "done" || current.audioFiles.isEmpty()) {
            throw IllegalStateException(current.error ?: "No playable audio was generated")
        }
        return current
    }

    private fun playJob(book: Book, chapter: Chapter, voice: Voice, job: Job, knownJobs: List<Job>) {
        val mediaItems = mutableListOf<MediaItem>()
        val sortedChapters = _state.value.chapters.sortedBy { it.index }
        val startPosition = sortedChapters.indexOfFirst { it.index == chapter.index }.coerceAtLeast(0)
        for (candidateChapter in sortedChapters.drop(startPosition).take(8)) {
            val candidateJob = if (candidateChapter.index == chapter.index) job else
                matchingDoneJob(knownJobs, candidateChapter, voice, _state.value.modelBackend) ?: break
            mediaItems += mediaItems(book, candidateChapter, candidateJob)
        }
        val bookmark = preferences.bookmark(book.id, chapter.index, voice.id, _state.value.modelBackend)
        val startIndex = bookmark?.mediaIndex?.coerceIn(mediaItems.indices) ?: 0
        val startMs = bookmark?.positionMs?.coerceAtLeast(0) ?: 0
        controller?.apply {
            setMediaItems(mediaItems, startIndex, startMs)
            prepare()
            play()
        }
        _state.update {
            it.copy(
                activeJob = job,
                busy = false,
                message = if (bookmark == null) "Playing" else "Resumed bookmark",
                error = "",
            )
        }
        refreshPlayerState()
    }

    private suspend fun prepareLookahead(
        book: Book,
        currentChapter: Chapter,
        voice: Voice,
        modelBackend: String,
        serial: Int,
    ) {
        val chapters = _state.value.chapters.sortedBy { it.index }
        val currentPosition = chapters.indexOfFirst { it.index == currentChapter.index }
        if (currentPosition < 0) return
        for (chapter in chapters.drop(currentPosition + 1).take(3)) {
            if (serial != generationSerial || !_state.value.autoNext) return
            val known = api.jobs(book.id)
            val initial = matchingDoneJob(known, chapter, voice, modelBackend)
                ?: known.firstOrNull { matches(it, chapter, voice, modelBackend) && it.status in listOf("queued", "running") }
                ?: api.createJob(book, chapter, voice, modelBackend, cancelExisting = false)
            val done = awaitJob(initial, serial)
            if (serial != generationSerial) return
            val existingIds = (0 until (controller?.mediaItemCount ?: 0)).mapNotNull { controller?.getMediaItemAt(it)?.mediaId }.toSet()
            val additions = mediaItems(book, chapter, done).filterNot { it.mediaId in existingIds }
            if (additions.isNotEmpty()) controller?.addMediaItems(additions)
            _state.update { it.copy(message = "Queued through ${chapter.title}", busy = false) }
        }
    }

    private fun mediaItems(book: Book, chapter: Chapter, job: Job): List<MediaItem> =
        job.audioFiles.mapIndexed { index, path ->
            MediaItem.Builder()
                .setUri(api.audioUrl(path))
                .setMediaId("${job.id}:$index")
                .setMediaMetadata(
                    MediaMetadata.Builder()
                        .setTitle(book.title)
                        .setSubtitle("${chapter.title} · part ${index + 1}/${job.audioFiles.size}")
                        .setArtist(book.author ?: "EutherBooks")
                        .build(),
                )
                .build()
        }

    private fun matchingDoneJob(jobs: List<Job>, chapter: Chapter, voice: Voice, modelBackend: String): Job? =
        jobs.firstOrNull { it.status == "done" && it.audioFiles.isNotEmpty() && matches(it, chapter, voice, modelBackend) }

    private fun matches(job: Job, chapter: Chapter, voice: Voice, modelBackend: String): Boolean =
        chapter.index in job.chapterIndexes && job.voice == voice.id && job.ttsOptions["model_backend"]?.toString() == modelBackend

    fun togglePlayback() {
        controller?.let { if (it.isPlaying) it.pause() else it.play() }
        refreshPlayerState()
    }

    fun seekBy(deltaMs: Long) {
        controller?.let { it.seekTo((it.currentPosition + deltaMs).coerceIn(0, it.duration.takeIf { value -> value > 0 } ?: Long.MAX_VALUE)) }
    }

    fun next() { controller?.seekToNextMediaItem() }

    fun previous() { controller?.seekToPreviousMediaItem() }

    fun saveBookmark() {
        saveBookmarkInternal(automatic = false)
        _state.update { it.copy(message = "Bookmark saved") }
    }

    fun resumeBookmark() {
        val state = _state.value
        val book = state.selectedBook ?: return
        val chapter = state.selectedChapter ?: return
        val bookmark = preferences.bookmark(book.id, chapter.index, state.voiceId, state.modelBackend) ?: run {
            _state.update { it.copy(error = "No bookmark for this voice and model") }
            return
        }
        controller?.seekTo(bookmark.mediaIndex, bookmark.positionMs)
        controller?.play()
    }

    private fun saveAutomaticBookmark() = saveBookmarkInternal(automatic = true)

    private fun saveBookmarkInternal(automatic: Boolean) {
        val state = _state.value
        val book = state.selectedBook ?: return
        val chapter = state.selectedChapter ?: return
        val player = controller ?: return
        if (player.mediaItemCount == 0 || player.currentMediaItemIndex < 0) return
        preferences.saveBookmark(
            Bookmark(
                bookId = book.id,
                chapterIndex = chapter.index,
                voiceId = state.voiceId,
                modelBackend = state.modelBackend,
                mediaIndex = player.currentMediaItemIndex,
                positionMs = player.currentPosition.coerceAtLeast(0),
                updatedAtMs = System.currentTimeMillis(),
            ),
        )
        if (!automatic) refreshPlayerState()
    }

    fun setSleepTimer(minutes: Int?) {
        sleepJob?.cancel()
        if (minutes == null) {
            _state.update { it.copy(sleepDeadlineMs = null, sleepMinutes = null, message = "Sleep timer off") }
            return
        }
        val deadline = System.currentTimeMillis() + minutes * 60_000L
        _state.update { it.copy(sleepDeadlineMs = deadline, sleepMinutes = minutes, message = "Sleep timer: $minutes min") }
        sleepJob = viewModelScope.launch {
            delay(minutes * 60_000L)
            controller?.pause()
            _state.update { it.copy(sleepDeadlineMs = null, sleepMinutes = null, message = "Sleep timer paused playback") }
        }
    }

    private fun refreshPlayerState() {
        val player = controller
        if (player == null) {
            _state.update { it.copy(player = PlayerUiState()) }
            return
        }
        val metadata = player.mediaMetadata
        _state.update {
            it.copy(
                player = PlayerUiState(
                    ready = true,
                    playing = player.isPlaying,
                    title = metadata.title?.toString().orEmpty(),
                    subtitle = metadata.subtitle?.toString().orEmpty(),
                    positionMs = player.currentPosition.coerceAtLeast(0),
                    durationMs = player.duration.takeIf { value -> value > 0 } ?: 0,
                    itemIndex = player.currentMediaItemIndex.coerceAtLeast(0),
                    itemCount = player.mediaItemCount,
                ),
            )
        }
    }

    override fun onCleared() {
        controller?.removeListener(playerListener)
        playerTicker?.cancel()
        sleepJob?.cancel()
        super.onCleared()
    }
}

val modelChoices = listOf(
    "dots.tts-mf" to "Dots MF",
    "dots.tts-soar" to "Dots SOAR",
    "voxcpm2" to "VoxCPM2",
    "grapheneos-matcha-en" to "Graphene Matcha",
    "auto-fallback" to "Auto fallback",
)

internal fun selectBestVoice(voices: List<Voice>, model: String, preferred: String): Voice? {
    val compatible = voices.filter { it.modelBackend.isNullOrBlank() || it.modelBackend == model }
    return compatible.firstOrNull { it.id == preferred }
        ?: compatible.firstOrNull { it.id.contains("own") && it.language == "sv" }
        ?: compatible.firstOrNull { it.language == "sv" }
        ?: compatible.firstOrNull()
}

private fun readable(error: Throwable): String =
    error.message?.replace(Regex("https?://[^ ]+"), "server")?.take(300) ?: "Unknown error"
