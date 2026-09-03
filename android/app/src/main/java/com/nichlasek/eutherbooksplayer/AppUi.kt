package com.nichlasek.eutherbooksplayer

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.LibraryBooks
import androidx.compose.material.icons.automirrored.filled.Login
import androidx.compose.material.icons.filled.Book as BookIcon
import androidx.compose.material.icons.filled.Forward10
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Replay10
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlin.math.roundToInt

private val EutherDark = androidx.compose.material3.darkColorScheme(
    primary = Color(0xFFE4B96B),
    onPrimary = Color(0xFF241A08),
    secondary = Color(0xFFA8C7A0),
    tertiary = Color(0xFF9CCBE4),
    background = Color(0xFF11100E),
    surface = Color(0xFF1A1916),
    surfaceVariant = Color(0xFF292722),
    onBackground = Color(0xFFF3EFE7),
    onSurface = Color(0xFFF3EFE7),
)

@Composable
fun EutherBooksApp(viewModel: MainViewModel) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    MaterialTheme(colorScheme = EutherDark) {
        Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
            if (!state.authenticated) LoginScreen(state, viewModel::login)
            else MainScreen(state, viewModel)
        }
    }
}

@Composable
private fun LoginScreen(state: AppUiState, onLogin: (String, String) -> Unit) {
    var username by remember(state.username) { mutableStateOf(state.username) }
    var password by remember { mutableStateOf("") }
    Column(
        modifier = Modifier.fillMaxSize().padding(horizontal = 28.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Icon(Icons.AutoMirrored.Filled.LibraryBooks, null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(58.dp))
        Spacer(Modifier.height(18.dp))
        Text("EutherBooks", style = MaterialTheme.typography.headlineLarge, fontWeight = FontWeight.Bold)
        Text("Native Android player", color = MaterialTheme.colorScheme.secondary)
        Spacer(Modifier.height(28.dp))
        OutlinedTextField(
            value = username,
            onValueChange = { username = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Username") },
            singleLine = true,
        )
        Spacer(Modifier.height(12.dp))
        OutlinedTextField(
            value = password,
            onValueChange = { password = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Password") },
            singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
        )
        Spacer(Modifier.height(18.dp))
        Button(
            onClick = { onLogin(username, password) },
            enabled = !state.connecting,
            modifier = Modifier.fillMaxWidth(),
        ) {
            if (state.connecting) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
            else Icon(Icons.AutoMirrored.Filled.Login, null)
            Spacer(Modifier.width(10.dp))
            Text(if (state.connecting) "Connecting…" else "Sign in")
        }
        Text(
            state.serverUrl,
            modifier = Modifier.padding(top = 14.dp),
            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.55f),
            style = MaterialTheme.typography.bodySmall,
        )
        if (state.error.isNotBlank()) ErrorText(state.error)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun MainScreen(state: AppUiState, viewModel: MainViewModel) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(state.selectedBook?.title ?: "EutherBooks", maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(
                            state.serverStatus,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.secondary,
                        )
                    }
                },
                navigationIcon = {
                    if (state.selectedBook != null) IconButton(onClick = viewModel::backToLibrary) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, "Library")
                    }
                },
                actions = {
                    IconButton(onClick = viewModel::refreshLibrary) { Icon(Icons.Default.Refresh, "Refresh") }
                    TextButton(onClick = viewModel::logout) { Text("Log out") }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.surface),
            )
        },
        bottomBar = {
            if (state.player.ready && (state.player.itemCount > 0 || state.selectedChapter != null)) {
                PlayerPanel(state, viewModel)
            }
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            SettingsStrip(state, viewModel)
            if (state.busy && state.activeJob == null) LinearProgressIndicator(Modifier.fillMaxWidth())
            if (state.error.isNotBlank()) ErrorText(state.error)
            if (state.message.isNotBlank()) {
                Text(
                    state.message,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 7.dp),
                    color = MaterialTheme.colorScheme.secondary,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            if (state.selectedBook == null) BookList(state.books, viewModel::selectBook)
            else ChapterList(state, viewModel)
        }
    }
}

@Composable
private fun SettingsStrip(state: AppUiState, viewModel: MainViewModel) {
    Column(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surface).padding(vertical = 8.dp)) {
        Text("Model", modifier = Modifier.padding(horizontal = 16.dp), style = MaterialTheme.typography.labelMedium)
        LazyRow(
            contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(7.dp),
        ) {
            items(modelChoices) { (id, label) ->
                FilterChip(selected = state.modelBackend == id, onClick = { viewModel.setModel(id) }, label = { Text(label) })
            }
        }
        val voices = state.voices.filter { it.modelBackend.isNullOrBlank() || it.modelBackend == state.modelBackend }
        if (voices.isNotEmpty()) {
            Text("Voice", modifier = Modifier.padding(horizontal = 16.dp, vertical = 2.dp), style = MaterialTheme.typography.labelMedium)
            LazyRow(
                contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 12.dp),
                horizontalArrangement = Arrangement.spacedBy(7.dp),
            ) {
                items(voices, key = { it.id }) { voice ->
                    FilterChip(selected = state.voiceId == voice.id, onClick = { viewModel.setVoice(voice.id) }, label = { Text(voice.label) })
                }
            }
        }
    }
}

@Composable
private fun BookList(books: List<Book>, onBook: (Book) -> Unit) {
    if (books.isEmpty()) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Text("No books found") }
        return
    }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(9.dp),
    ) {
        items(books, key = { it.id }) { book ->
            Card(
                modifier = Modifier.fillMaxWidth().clickable { onBook(book) },
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
            ) {
                Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Default.BookIcon, null, tint = MaterialTheme.colorScheme.primary)
                    Spacer(Modifier.width(14.dp))
                    Column(Modifier.weight(1f)) {
                        Text(book.title, fontWeight = FontWeight.SemiBold)
                        Text(book.author ?: book.format.uppercase(), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurface.copy(alpha = .65f))
                    }
                }
            }
        }
    }
}

@Composable
private fun ChapterList(state: AppUiState, viewModel: MainViewModel) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(7.dp),
    ) {
        items(state.chapters, key = { it.index }) { chapter ->
            val selected = state.selectedChapter?.index == chapter.index
            Card(
                modifier = Modifier.fillMaxWidth().clickable { viewModel.selectChapter(chapter) },
                colors = CardDefaults.cardColors(
                    containerColor = if (selected) MaterialTheme.colorScheme.primary.copy(alpha = .18f) else MaterialTheme.colorScheme.surfaceVariant,
                ),
            ) {
                Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("${chapter.index + 1}", color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.width(14.dp))
                    Column(Modifier.weight(1f)) {
                        Text(chapter.title, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        Text("${chapter.charCount} characters", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurface.copy(alpha = .55f))
                    }
                    if (selected) Icon(Icons.Default.PlayArrow, null, tint = MaterialTheme.colorScheme.primary)
                }
            }
        }
    }
}

@Composable
private fun PlayerPanel(state: AppUiState, viewModel: MainViewModel) {
    Surface(color = Color(0xFF211F1A), tonalElevation = 8.dp, shadowElevation = 12.dp) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 10.dp)) {
            val job = state.activeJob
            if (job != null && job.status != "done") {
                LinearProgressIndicator(
                    modifier = Modifier.fillMaxWidth(),
                    progress = { job.workerProgress.coerceIn(0.0, 1.0).toFloat() },
                )
                Text(job.progressDetail, style = MaterialTheme.typography.labelSmall, modifier = Modifier.padding(top = 4.dp))
            }
            Text(
                state.player.title.ifBlank { state.selectedBook?.title.orEmpty() },
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                state.player.subtitle.ifBlank { state.selectedChapter?.title.orEmpty() },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = .65f),
                maxLines = 1,
            )
            if (state.player.durationMs > 0) {
                LinearProgressIndicator(
                    progress = { (state.player.positionMs.toFloat() / state.player.durationMs).coerceIn(0f, 1f) },
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                )
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(formatTime(state.player.positionMs), style = MaterialTheme.typography.labelSmall)
                    Text(formatTime(state.player.durationMs), style = MaterialTheme.typography.labelSmall)
                }
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = viewModel::previous) { Icon(Icons.Default.SkipPrevious, "Previous") }
                IconButton(onClick = { viewModel.seekBy(-10_000) }) { Icon(Icons.Default.Replay10, "Back 10 seconds") }
                IconButton(onClick = viewModel::togglePlayback, modifier = Modifier.size(54.dp)) {
                    Icon(if (state.player.playing) Icons.Default.Pause else Icons.Default.PlayArrow, if (state.player.playing) "Pause" else "Play", modifier = Modifier.size(38.dp))
                }
                IconButton(onClick = { viewModel.seekBy(10_000) }) { Icon(Icons.Default.Forward10, "Forward 10 seconds") }
                IconButton(onClick = viewModel::next) { Icon(Icons.Default.SkipNext, "Next") }
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                Button(
                    onClick = viewModel::generateOrPlay,
                    enabled = state.selectedChapter != null && !state.busy,
                    modifier = Modifier.weight(1f),
                ) { Text(if (state.busy) "Generating…" else "Generate & play") }
                OutlinedButton(onClick = viewModel::saveBookmark, enabled = state.player.itemCount > 0) { Text("Bookmark") }
                OutlinedButton(onClick = viewModel::resumeBookmark, enabled = state.selectedChapter != null) { Text("Resume") }
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(7.dp), verticalAlignment = Alignment.CenterVertically) {
                FilterChip(selected = state.autoNext, onClick = { viewModel.setAutoNext(!state.autoNext) }, label = { Text("Auto-next") })
                listOf(null to "Off", 15 to "15m", 30 to "30m", 60 to "60m").forEach { (minutes, label) ->
                    FilterChip(
                        selected = state.sleepMinutes == minutes,
                        onClick = { viewModel.setSleepTimer(minutes) },
                        label = { Text(label) },
                    )
                }
            }
        }
    }
}

@Composable
private fun ErrorText(message: String) {
    Text(
        message,
        color = MaterialTheme.colorScheme.error,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 9.dp)
            .background(MaterialTheme.colorScheme.error.copy(alpha = .1f), RoundedCornerShape(8.dp)).padding(10.dp),
        style = MaterialTheme.typography.bodySmall,
    )
}

private fun formatTime(milliseconds: Long): String {
    val total = (milliseconds / 1000.0).roundToInt().coerceAtLeast(0)
    return "%d:%02d".format(total / 60, total % 60)
}
