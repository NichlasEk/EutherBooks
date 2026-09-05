package com.nichlasek.eutherbooksplayer

import android.app.Application
import android.media.MediaPlayer
import android.media.MediaRecorder
import android.net.Uri
import android.os.Build
import android.webkit.MimeTypeMap
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
import java.io.File

data class PlayerUiState(
    val ready: Boolean = false,
    val playing: Boolean = false,
    val title: String = "",
    val subtitle: String = "",
    val positionMs: Long = 0,
    val durationMs: Long = 0,
    val itemIndex: Int = 0,
    val itemCount: Int = 0,
    val bookId: String = "",
    val chapterIndex: Int = -1,
    val voiceId: String = "",
    val modelBackend: String = "",
    val chapterTimeline: Boolean = false,
    val chapterComplete: Boolean = false,
    val speed: Float = 1f,
)

data class AppUiState(
    val authenticated: Boolean = false,
    val connecting: Boolean = false,
    val busy: Boolean = false,
    val serverUrl: String = AppPreferences.DEFAULT_PUBLIC_BOOKS,
    val serverStatus: String = "Inte ansluten",
    val username: String = "nichlas",
    val books: List<Book> = emptyList(),
    val chapters: List<Chapter> = emptyList(),
    val recentBookmarks: Map<String, Bookmark> = emptyMap(),
    val finishedBooks: Set<String> = emptySet(),
    val voices: List<Voice> = emptyList(),
    val selectedBook: Book? = null,
    val selectedChapter: Chapter? = null,
    val voiceId: String = "dots-mf-own-sv",
    val modelBackend: String = "dots.tts-mf",
    val autoNext: Boolean = true,
    val activeJob: Job? = null,
    val jobOverallProgress: Float = 0f,
    val jobElapsedSeconds: Long = 0,
    val jobIdleSeconds: Long = 0,
    val voiceSampleRecording: Boolean = false,
    val voiceSampleUploading: Boolean = false,
    val voiceSampleReady: Boolean = false,
    val voiceSamplePlaying: Boolean = false,
    val voiceSampleStatus: String = "",
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
            recentBookmarks = preferences.recentBookmarks(),
            finishedBooks = preferences.finishedBooks(),
        ),
    )
    val state: StateFlow<AppUiState> = _state.asStateFlow()

    private var controller: MediaController? = null
    private var playerTicker: CoroutineJob? = null
    private var sleepJob: CoroutineJob? = null
    private var selectionSerial = 0
    private var generationSerial = 0
    private var generationStartedAtMs = 0L
    private var generationLastProgressAtMs = 0L
    private var generationProgressSignature = ""
    private var voiceRecorder: MediaRecorder? = null
    private var voicePreviewPlayer: MediaPlayer? = null
    private var voiceSampleFile: File? = null
    private var voiceSampleContentType = "audio/mp4"
    private var voiceSampleFileName = "voice-sample.m4a"

    private val playerListener = object : Player.Listener {
        override fun onEvents(player: Player, events: Player.Events) {
            refreshPlayerState()
            if (events.contains(Player.EVENT_MEDIA_ITEM_TRANSITION)) saveAutomaticBookmark()
        }

        override fun onPlayerError(error: androidx.media3.common.PlaybackException) {
            _state.update { it.copy(error = "Uppspelning: ${error.message.orEmpty()}") }
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
            _state.update { it.copy(error = "Ange användarnamn och lösenord") }
            return
        }
        viewModelScope.launch {
            _state.update { it.copy(connecting = true, error = "", message = "Loggar in…") }
            runCatching { api.login(username, password) }
                .onSuccess {
                    _state.update { state -> state.copy(authenticated = true, username = it.user, message = "Inloggad") }
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
            _state.update { it.copy(connecting = true, error = "", message = "Ansluter…") }
            runCatching { api.connect() }
                .onSuccess { health ->
                    _state.update {
                        it.copy(
                            authenticated = true,
                            serverUrl = api.activeBaseUrl,
                            serverStatus = "${health.status} · ${health.ttsBackend}",
                            message = "Ansluten",
                        )
                    }
                    loadLibrary()
                }
                .onFailure { error ->
                    _state.update { it.copy(error = readable(error), serverStatus = "Kunde inte ansluta") }
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
        _state.update { it.copy(busy = true, error = "", message = "Hämtar biblioteket…") }
        runCatching {
            val books = api.books()
            val voices = api.voices()
            Triple(books, voices, api.connect())
        }.onSuccess { (books, voices, health) ->
            val selectedVoice = selectBestVoice(voices, _state.value.modelBackend, _state.value.voiceId)
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
                    message = "${books.size} böcker",
                )
            }
        }.onFailure { error ->
            _state.update { it.copy(busy = false, error = readable(error), message = "") }
        }
    }

    fun refreshLibrary() {
        viewModelScope.launch { loadLibrary() }
    }

    fun selectBook(book: Book) = openBook(book, resume = false)

    fun continueBook(book: Book) = openBook(book, resume = true)

    private fun openBook(book: Book, resume: Boolean) {
        val serial = ++selectionSerial
        val bookmark = preferences.recentBookmarks()[book.id]
        val savedVoice = if (resume && bookmark != null) BookVoice(bookmark.voiceId, bookmark.modelBackend)
            else preferences.bookVoice(book.id)
        val model = savedVoice?.modelBackend ?: preferences.modelBackend
        val voice = selectBestVoice(_state.value.voices, model, savedVoice?.voiceId ?: preferences.voiceId)
        _state.update { it.copy(selectedBook = book, selectedChapter = null, chapters = emptyList(),
            modelBackend = model, voiceId = voice?.id ?: preferences.voiceId, error = "", message = "Hämtar kapitel…") }
        viewModelScope.launch {
            runCatching { api.chapters(book.id) }
                .onSuccess { chapters ->
                    if (serial != selectionSerial) return@onSuccess
                    val chapter = chapters.firstOrNull { it.index == bookmark?.chapterIndex } ?: chapters.firstOrNull()
                    _state.update { it.copy(chapters = chapters, selectedChapter = chapter, message = "") }
                    if (resume) {
                        val playing = controller?.currentMediaItem?.queueEntry()
                        if (playing?.bookId == book.id && controller?.playbackState != Player.STATE_ENDED) {
                            controller?.play()
                        } else generateOrPlay()
                    }
                }
                .onFailure { error -> if (serial == selectionSerial) _state.update { it.copy(error = readable(error)) } }
        }
    }

    fun backToLibrary() {
        selectionSerial += 1
        _state.update { it.copy(selectedBook = null, selectedChapter = null, chapters = emptyList(), error = "", message = "") }
    }

    fun selectChapter(chapter: Chapter) {
        _state.update { it.copy(selectedChapter = chapter, error = "", message = "") }
    }

    private fun rememberBookVoice() {
        val state = _state.value
        state.selectedBook?.let { preferences.saveBookVoice(it.id, BookVoice(state.voiceId, state.modelBackend)) }
    }

    fun setModel(model: String) {
        preferences.modelBackend = model
        val voice = selectBestVoice(_state.value.voices, model, "")
        if (voice != null) preferences.voiceId = voice.id
        _state.update { it.copy(modelBackend = model, voiceId = voice?.id ?: it.voiceId) }
        rememberBookVoice()
    }

    fun setVoice(voiceId: String) {
        preferences.voiceId = voiceId
        _state.update { it.copy(voiceId = voiceId) }
        rememberBookVoice()
    }

    fun toggleFinished(book: Book) {
        preferences.setFinished(book.id, book.id !in preferences.finishedBooks())
        _state.update { it.copy(finishedBooks = preferences.finishedBooks()) }
    }

    fun setPlaybackSpeed(speed: Float) {
        preferences.playbackSpeed = speed
        controller?.setPlaybackSpeed(preferences.playbackSpeed)
        refreshPlayerState()
    }

    fun startVoiceRecording() {
        if (voiceRecorder != null || _state.value.voiceSampleUploading) return
        val output = File(getApplication<Application>().cacheDir, "eutherbooks-voice-sample.m4a")
        runCatching {
            stopVoicePreview()
            if (output.exists()) output.delete()
            val recorder = if (Build.VERSION.SDK_INT >= 31) {
                MediaRecorder(getApplication())
            } else {
                @Suppress("DEPRECATION")
                MediaRecorder()
            }
            recorder.setAudioSource(MediaRecorder.AudioSource.MIC)
            recorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            recorder.setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
            recorder.setAudioEncodingBitRate(128_000)
            recorder.setAudioSamplingRate(44_100)
            recorder.setOutputFile(output.absolutePath)
            recorder.prepare()
            recorder.start()
            voiceRecorder = recorder
            voiceSampleFile = output
            voiceSampleContentType = "audio/mp4"
            voiceSampleFileName = "voice-sample.m4a"
            _state.update {
                it.copy(
                    voiceSampleRecording = true,
                    voiceSampleReady = false,
                    voiceSampleStatus = "Inspelning pågår…",
                    error = "",
                )
            }
        }.onFailure { error ->
            releaseVoiceRecorder()
            _state.update { it.copy(error = "Kunde inte starta mikrofonen: ${readable(error)}") }
        }
    }

    fun microphonePermissionDenied() {
        _state.update { it.copy(error = "Mikrofonbehörighet behövs för att spela in din röst") }
    }

    fun stopVoiceRecording() {
        val recorder = voiceRecorder ?: return
        runCatching { recorder.stop() }
            .onSuccess {
                _state.update {
                    it.copy(
                        voiceSampleRecording = false,
                        voiceSampleReady = voiceSampleFile?.length()?.let { bytes -> bytes > 0 } == true,
                        voiceSampleStatus = "Provlyssna och spara när rösten låter bra.",
                    )
                }
            }
            .onFailure { error ->
                voiceSampleFile?.delete()
                voiceSampleFile = null
                _state.update { it.copy(voiceSampleRecording = false, error = "Inspelningen blev för kort: ${readable(error)}") }
            }
        releaseVoiceRecorder()
    }

    fun playVoicePreview() {
        val file = voiceSampleFile
        if (file == null || !file.isFile) {
            _state.update { it.copy(error = "Spela in ett röstprov först") }
            return
        }
        playVoiceFile(file)
    }

    fun importVoiceSample(uri: Uri?) {
        if (uri == null || _state.value.voiceSampleRecording || _state.value.voiceSampleUploading) return
        runCatching {
            stopVoicePreview()
            val resolver = getApplication<Application>().contentResolver
            val contentType = resolver.getType(uri) ?: "application/octet-stream"
            val extension = MimeTypeMap.getSingleton().getExtensionFromMimeType(contentType)?.take(8) ?: "audio"
            val output = File(getApplication<Application>().cacheDir, "eutherbooks-voice-import.$extension")
            resolver.openInputStream(uri)?.use { input ->
                output.outputStream().use { outputStream -> input.copyTo(outputStream) }
            }
                ?: throw IllegalArgumentException("Kunde inte läsa ljudfilen")
            require(output.length() in 1..20_000_000) { "Ljudfilen är tom eller för stor" }
            voiceSampleFile = output
            voiceSampleContentType = contentType
            voiceSampleFileName = "voice-sample.$extension"
            _state.update {
                it.copy(
                    voiceSampleReady = true,
                    voiceSampleStatus = "Ljudfilen är vald. Provlyssna och spara.",
                    error = "",
                )
            }
        }.onFailure { error ->
            _state.update { it.copy(error = readable(error)) }
        }
    }

    fun saveVoiceSample() {
        val file = voiceSampleFile
        if (file == null || !file.isFile || _state.value.voiceSampleUploading) return
        val selectedVoiceId = _state.value.voiceId
        val selectedVoice = _state.value.voices.firstOrNull { it.id == selectedVoiceId }
        val language = if (selectedVoice?.language == "en") "en" else "sv"
        val prompt = ownVoicePrompt(language)
        val contentType = voiceSampleContentType
        val fileName = voiceSampleFileName
        viewModelScope.launch {
            _state.update { it.copy(voiceSampleUploading = true, voiceSampleStatus = "Sparar röstprov…", error = "") }
            runCatching {
                api.saveVoiceSample(
                    selectedVoiceId,
                    language,
                    prompt,
                    file.readBytes(),
                    contentType,
                    fileName,
                )
                }
                .onSuccess {
                    report("voice_sample_saved", mapOf("voice" to selectedVoiceId, "language" to language))
                    _state.update {
                        it.copy(
                            voiceSampleUploading = false,
                            voiceSampleStatus = "Röstprovet är sparat på servern.",
                            message = "Egen röst uppdaterad",
                        )
                    }
                }
                .onFailure { error ->
                    _state.update { it.copy(voiceSampleUploading = false, error = readable(error), voiceSampleStatus = "") }
                }
        }
    }

    fun replaySavedVoiceSample() {
        if (_state.value.voiceSampleUploading) return
        val voiceId = _state.value.voiceId
        viewModelScope.launch {
            _state.update { it.copy(voiceSampleUploading = true, voiceSampleStatus = "Hämtar sparat röstprov…", error = "") }
            runCatching {
                val bytes = api.voiceSample(voiceId)
                File(getApplication<Application>().cacheDir, "eutherbooks-saved-voice.wav").apply { writeBytes(bytes) }
            }.onSuccess { file ->
                _state.update { it.copy(voiceSampleUploading = false, voiceSampleStatus = "Spelar sparat röstprov.") }
                playVoiceFile(file)
            }.onFailure { error ->
                _state.update { it.copy(voiceSampleUploading = false, error = readable(error), voiceSampleStatus = "") }
            }
        }
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
            _state.update { it.copy(error = "Välj en berättarröst") }
            return
        }
        if (controller == null) {
            _state.update { it.copy(error = "Spelaren startar fortfarande") }
            return
        }
        saveAutomaticBookmark()
        rememberBookVoice()
        preferences.setFinished(book.id, false)
        val serial = ++generationSerial
        generationStartedAtMs = System.currentTimeMillis()
        generationLastProgressAtMs = generationStartedAtMs
        generationProgressSignature = ""
        viewModelScope.launch {
            _state.update {
                it.copy(
                    busy = true,
                    activeJob = null,
                    jobOverallProgress = 0f,
                    jobElapsedSeconds = 0,
                    jobIdleSeconds = 0,
                    error = "",
                    message = "Kontrollerar om ljudet redan finns…",
                )
            }
            runCatching {
                val jobs = api.jobs(book.id)
                val existing = matchingDoneJob(jobs, chapter, voice, snapshot.modelBackend)
                val job = existing ?: api.createJob(book, chapter, voice, snapshot.modelBackend)
                report("generation_started", mapOf("job_id" to job.id, "book_id" to book.id, "chapter" to chapter.index, "voice" to voice.id))
                val finished = awaitJob(job, serial, book, chapter, voice, streamAudio = true)
                if (serial != generationSerial) return@runCatching
                finalizeStreamedJob(book, chapter, voice, finished, jobs + finished, snapshot.chapters, snapshot.modelBackend)
                if (snapshot.autoNext) prepareLookahead(book, chapter, voice, snapshot.modelBackend, serial, snapshot.chapters)
            }.onFailure { error ->
                if (serial == generationSerial) {
                    report("generation_failed", mapOf("error" to readable(error)))
                    _state.update { it.copy(busy = false, error = readable(error), message = "") }
                }
            }
        }
    }

    private suspend fun awaitJob(
        initial: Job,
        serial: Int,
        book: Book? = null,
        chapter: Chapter? = null,
        voice: Voice? = null,
        streamAudio: Boolean = false,
    ): Job {
        var current = initial
        while (current.status == "queued" || current.status == "running") {
            if (serial != generationSerial) throw IllegalStateException("Valet ändrades")
            updateJobProgress(current)
            if (streamAudio && book != null && chapter != null && voice != null && current.audioFiles.isNotEmpty()) {
                syncStreamedAudio(book, chapter, current)
            }
            delay(2_000)
            current = api.job(current.id)
        }
        if (current.status != "done" || current.audioFiles.isEmpty()) {
            throw IllegalStateException(current.error ?: "Inget spelbart ljud kunde skapas")
        }
        if (serial != generationSerial) throw IllegalStateException("Valet ändrades")
        updateJobProgress(current)
        if (streamAudio && book != null && chapter != null && voice != null) syncStreamedAudio(book, chapter, current)
        return current
    }

    private fun updateJobProgress(job: Job) {
        val now = System.currentTimeMillis()
        val signature = "${job.status}:${job.currentChunkIndex}:${job.audioFiles.size}:${job.workerProgress}:${job.progressDetail}"
        if (signature != generationProgressSignature) {
            generationProgressSignature = signature
            generationLastProgressAtMs = now
        }
        _state.update {
            it.copy(
                activeJob = job,
                jobOverallProgress = overallJobProgress(job),
                jobElapsedSeconds = ((now - generationStartedAtMs).coerceAtLeast(0) / 1_000),
                jobIdleSeconds = ((now - generationLastProgressAtMs).coerceAtLeast(0) / 1_000),
                message = job.progressDetail.ifBlank { job.progressLabel },
            )
        }
    }

    private fun syncStreamedAudio(book: Book, chapter: Chapter, job: Job) {
        val player = controller ?: return
        val wanted = mediaItems(book, chapter, job)
        if (wanted.isEmpty()) return
        val currentJobIds = (0 until player.mediaItemCount)
            .map { player.getMediaItemAt(it).mediaId }
            .filter { it.startsWith("${job.id}:") }
            .toSet()
        if (currentJobIds.isEmpty()) {
            val bookmark = preferences.bookmark(book.id, chapter.index, job.voice, job.ttsOptions["model_backend"]?.toString().orEmpty())
            // Regeneration must reach the saved part before resuming it.
            if (job.status != "done" && bookmark != null && bookmark.mediaIndex >= wanted.size) return
            val startIndex = bookmark?.mediaIndex?.coerceIn(wanted.indices) ?: 0
            player.setMediaItems(wanted, startIndex, bookmark?.positionMs?.coerceAtLeast(0) ?: 0)
            player.prepare()
            player.play()
            report("partial_playback_started", mapOf("job_id" to job.id, "ready_parts" to wanted.size))
        } else {
            // Update duration/completion metadata without replacing the playing audio source.
            wanted.filter { it.mediaId in currentJobIds }.forEach { item ->
                val index = (0 until player.mediaItemCount).first { player.getMediaItemAt(it).mediaId == item.mediaId }
                if (player.getMediaItemAt(index).queueEntry() != item.queueEntry()) player.replaceMediaItem(index, item)
            }
            val additions = wanted.filterNot { it.mediaId in currentJobIds }
            if (additions.isNotEmpty()) {
                val firstNewIndex = player.mediaItemCount
                player.addMediaItems(additions)
                if (player.playbackState == Player.STATE_ENDED) {
                    player.seekTo(firstNewIndex, 0)
                    player.prepare()
                    player.play()
                }
            }
        }
        refreshPlayerState()
    }

    private fun finalizeStreamedJob(book: Book, chapter: Chapter, voice: Voice, job: Job, knownJobs: List<Job>, chapters: List<Chapter>, modelBackend: String) {
        syncStreamedAudio(book, chapter, job)
        val sortedChapters = chapters.sortedBy { it.index }
        val startPosition = sortedChapters.indexOfFirst { it.index == chapter.index }.coerceAtLeast(0)
        val existingIds = (0 until (controller?.mediaItemCount ?: 0))
            .mapNotNull { controller?.getMediaItemAt(it)?.mediaId }
            .toSet()
        val following = mutableListOf<MediaItem>()
        if (_state.value.autoNext) for (candidate in sortedChapters.drop(startPosition + 1).take(7)) {
            val ready = matchingDoneJob(knownJobs, candidate, voice, modelBackend) ?: break
            following += mediaItems(book, candidate, ready)
        }
        val additions = following.filterNot { it.mediaId in existingIds }
        if (additions.isNotEmpty()) controller?.addMediaItems(additions)
        _state.update {
            it.copy(
                activeJob = job,
                jobOverallProgress = 1f,
                busy = false,
                message = "Kapitlet är färdigt och spelar",
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
        bookChapters: List<Chapter>,
    ) {
        val chapters = bookChapters.sortedBy { it.index }
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
            _state.update { it.copy(message = "Ljud förberett till ${chapter.title}", busy = false) }
        }
    }

    private fun mediaItems(book: Book, chapter: Chapter, job: Job): List<MediaItem> =
        job.audioFiles.mapIndexed { index, path ->
            QueueEntry(
                uri = api.audioUrl(path), mediaId = "${job.id}:$index", title = book.title,
                subtitle = chapter.title, bookId = book.id, chapterIndex = chapter.index,
                chapterTitle = chapter.title, voiceId = job.voice,
                modelBackend = job.ttsOptions["model_backend"]?.toString().orEmpty(),
                partIndex = index, durationMs = ((job.audioDurations.getOrNull(index) ?: 0.0) * 1000).toLong(),
                chapterComplete = job.status == "done",
            ).toMediaItem()
        }

    private fun matchingDoneJob(jobs: List<Job>, chapter: Chapter, voice: Voice, modelBackend: String): Job? =
        jobs.firstOrNull { it.status == "done" && it.audioFiles.isNotEmpty() && matches(it, chapter, voice, modelBackend) }

    private fun matches(job: Job, chapter: Chapter, voice: Voice, modelBackend: String): Boolean =
        chapter.index in job.chapterIndexes && job.voice == voice.id && job.ttsOptions["model_backend"]?.toString() == modelBackend

    fun togglePlayback() {
        controller?.let { if (it.isPlaying) it.pause() else it.play() }
        refreshPlayerState()
    }

    private fun currentTimeline(): ChapterTimeline? {
        val player = controller ?: return null
        val entries = (0 until player.mediaItemCount).map { index ->
            val entry = player.getMediaItemAt(index).queueEntry()
            if (index == player.currentMediaItemIndex && entry.durationMs <= 0 && player.duration > 0)
                entry.copy(durationMs = player.duration) else entry
        }
        return chapterTimeline(entries, player.currentMediaItemIndex, player.currentPosition)
    }

    fun seekToPosition(positionMs: Long) {
        val player = controller ?: return
        val timeline = currentTimeline()
        val target = timeline?.seekTarget(positionMs)
        if (target != null) player.seekTo(target.first, target.second)
        else if (player.duration > 0) player.seekTo(positionMs.coerceIn(0, player.duration))
        saveAutomaticBookmark()
        refreshPlayerState()
    }

    fun seekBy(deltaMs: Long) = seekToPosition(_state.value.player.positionMs + deltaMs)

    fun next() { moveChapter(forward = true) }
    fun previous() { moveChapter(forward = false) }

    private fun moveChapter(forward: Boolean) {
        val player = controller ?: return
        val current = player.currentMediaItem?.queueEntry() ?: return
        val entries = (0 until player.mediaItemCount).map { player.getMediaItemAt(it).queueEntry() }
        val target = if (forward) entries.indices.firstOrNull { it > player.currentMediaItemIndex &&
            (entries[it].chapterIndex != current.chapterIndex || entries[it].bookId != current.bookId) }
        else {
            val previous = entries.indices.lastOrNull { it < player.currentMediaItemIndex &&
                (entries[it].chapterIndex != current.chapterIndex || entries[it].bookId != current.bookId) }
            previous?.let { last -> entries.indices.first { entries[it].bookId == entries[last].bookId && entries[it].chapterIndex == entries[last].chapterIndex } }
                ?: currentTimeline()?.queueIndexes?.firstOrNull()
        }
        if (target != null) player.seekTo(target, 0)
        else _state.update { it.copy(message = "Nästa kapitel är inte redo ännu.") }
        saveAutomaticBookmark()
    }

    fun saveBookmark() {
        saveBookmarkInternal(automatic = false)
        _state.update { it.copy(message = "Lyssningsposition sparad") }
    }

    fun resumeBookmark() {
        _state.value.selectedBook?.let(::continueBook)
    }

    private fun saveAutomaticBookmark() = saveBookmarkInternal(automatic = true)

    private fun saveBookmarkInternal(automatic: Boolean) {
        val player = controller ?: return
        player.currentMediaItem?.queueEntry()?.bookmark(player.currentPosition)?.let(preferences::saveBookmark)
        _state.update { it.copy(recentBookmarks = preferences.recentBookmarks(), finishedBooks = preferences.finishedBooks()) }
        if (!automatic) refreshPlayerState()
    }

    fun setSleepTimer(minutes: Int?) {
        sleepJob?.cancel()
        if (minutes == null) {
            _state.update { it.copy(sleepDeadlineMs = null, sleepMinutes = null, message = "Sovtimern är avstängd") }
            return
        }
        val deadline = System.currentTimeMillis() + minutes * 60_000L
        _state.update { it.copy(sleepDeadlineMs = deadline, sleepMinutes = minutes, message = "Sovtimer: $minutes min") }
        sleepJob = viewModelScope.launch {
            delay(minutes * 60_000L)
            controller?.pause()
            _state.update { it.copy(sleepDeadlineMs = null, sleepMinutes = null, message = "Sovtimern pausade uppspelningen") }
        }
    }

    private fun refreshPlayerState() {
        val player = controller
        if (player == null) {
            _state.update { it.copy(player = PlayerUiState()) }
            return
        }
        val metadata = player.mediaMetadata
        val entry = player.currentMediaItem?.queueEntry()
        val timeline = currentTimeline()
        _state.update {
            it.copy(
                recentBookmarks = preferences.recentBookmarks(),
                player = PlayerUiState(
                    ready = true,
                    playing = player.isPlaying,
                    title = metadata.title?.toString().orEmpty(),
                    subtitle = metadata.subtitle?.toString().orEmpty(),
                    positionMs = timeline?.positionMs ?: player.currentPosition.coerceAtLeast(0),
                    durationMs = timeline?.durationMs ?: (player.duration.takeIf { value -> value > 0 } ?: 0),
                    bookId = entry?.bookId.orEmpty(),
                    chapterIndex = entry?.chapterIndex ?: -1,
                    voiceId = entry?.voiceId.orEmpty(),
                    modelBackend = entry?.modelBackend.orEmpty(),
                    chapterTimeline = timeline != null,
                    chapterComplete = timeline?.complete ?: false,
                    speed = player.playbackParameters.speed,
                    itemIndex = player.currentMediaItemIndex.coerceAtLeast(0),
                    itemCount = player.mediaItemCount,
                ),
            )
        }
    }

    private fun playVoiceFile(file: File) {
        stopVoicePreview()
        runCatching {
            MediaPlayer().also { player ->
                voicePreviewPlayer = player
                player.setDataSource(file.absolutePath)
                player.setOnCompletionListener {
                    stopVoicePreview()
                    _state.update { state -> state.copy(voiceSampleStatus = "Provlyssningen är klar.") }
                }
                player.prepare()
                player.start()
                _state.update { it.copy(voiceSamplePlaying = true, voiceSampleStatus = "Spelar röstprov…") }
            }
        }.onFailure { error ->
            stopVoicePreview()
            _state.update { it.copy(error = "Kunde inte spela röstprovet: ${readable(error)}") }
        }
    }

    fun stopVoicePreview() {
        voicePreviewPlayer?.runCatching { stop() }
        voicePreviewPlayer?.release()
        voicePreviewPlayer = null
        _state.update { it.copy(voiceSamplePlaying = false) }
    }

    private fun releaseVoiceRecorder() {
        voiceRecorder?.release()
        voiceRecorder = null
    }

    private fun report(event: String, fields: Map<String, Any?> = emptyMap()) {
        viewModelScope.launch { runCatching { api.reportPlayerLog(event, fields) } }
    }

    override fun onCleared() {
        controller?.removeListener(playerListener)
        playerTicker?.cancel()
        sleepJob?.cancel()
        if (_state.value.voiceSampleRecording) voiceRecorder?.runCatching { stop() }
        releaseVoiceRecorder()
        stopVoicePreview()
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
    error.message?.replace(Regex("https?://[^ ]+"), "server")?.take(300) ?: "Ett okänt fel inträffade"

internal fun ownVoicePrompt(language: String): String = if (language == "en") {
    "The sun rises slowly over the forest. I read this text in my natural storytelling voice, clearly and calmly, so that every word can be heard."
} else {
    "Solen går långsamt upp över skogen. Jag läser den här texten med min naturliga berättarröst, tydligt och lugnt, så att varje ord hörs klart."
}

internal fun completedJobParts(job: Job): Int =
    maxOf(job.currentChunkIndex, job.audioFiles.size).coerceAtLeast(0)

internal fun overallJobProgress(job: Job): Float {
    val total = job.totalChunks.takeIf { it > 0 } ?: job.totalAudioFiles.takeIf { it > 0 } ?: return 0f
    val completed = completedJobParts(job).coerceAtMost(total)
    return ((completed + job.workerProgress.coerceIn(0.0, 1.0)) / total.toDouble())
        .coerceIn(0.0, 1.0)
        .toFloat()
}
