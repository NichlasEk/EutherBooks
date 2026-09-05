package com.nichlasek.eutherbooksplayer

import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
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
import androidx.compose.material.icons.filled.Hearing
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Replay10
import androidx.compose.material.icons.filled.Save
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.material3.Slider
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.DropdownMenuItem
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
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
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

internal val EutherDark = androidx.compose.material3.darkColorScheme(
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
fun EutherBooksApp(
    viewModel: MainViewModel,
    requestVoiceRecording: () -> Unit,
    pickVoiceSample: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    MaterialTheme(colorScheme = EutherDark) {
        Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
            if (!state.authenticated) LoginScreen(state, viewModel::login)
            else MainScreen(state, viewModel, requestVoiceRecording, pickVoiceSample)
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
        Text("Dina böcker, din berättarröst", color = MaterialTheme.colorScheme.secondary)
        Spacer(Modifier.height(28.dp))
        OutlinedTextField(
            value = username,
            onValueChange = { username = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Användarnamn") },
            singleLine = true,
        )
        Spacer(Modifier.height(12.dp))
        OutlinedTextField(
            value = password,
            onValueChange = { password = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Lösenord") },
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
            Text(if (state.connecting) "Ansluter…" else "Logga in")
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
internal fun MainScreen(
    state: AppUiState,
    viewModel: MainViewModel,
    requestVoiceRecording: () -> Unit,
    pickVoiceSample: () -> Unit,
) {
    var showSettings by rememberSaveable { mutableStateOf(false) }
    var showPlayer by rememberSaveable { mutableStateOf(false) }
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(state.selectedBook?.title ?: "Mitt bibliotek", maxLines = 1, overflow = TextOverflow.Ellipsis) },
                navigationIcon = {
                    if (state.selectedBook != null) IconButton(onClick = viewModel::backToLibrary) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, "Bibliotek")
                    }
                },
                actions = {
                    IconButton(onClick = viewModel::refreshLibrary) { Icon(Icons.Default.Refresh, "Uppdatera biblioteket") }
                    IconButton(onClick = { showSettings = true }) { Icon(Icons.Default.Settings, "Inställningar") }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
            )
        },
        bottomBar = {
            if (state.player.itemCount > 0) MiniPlayer(state, viewModel) { showPlayer = true }
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            if (state.busy && state.activeJob == null) LinearProgressIndicator(Modifier.fillMaxWidth())
            if (state.activeJob?.status in listOf("queued", "running")) {
                Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
                    Text(if (state.activeJob?.status == "queued") "Väntar på ljudservern…" else "Förbereder nästa ljud · ${(state.jobOverallProgress * 100).toInt()} %",
                        style = MaterialTheme.typography.labelMedium)
                    LinearProgressIndicator(progress = { state.jobOverallProgress }, modifier = Modifier.fillMaxWidth().padding(top = 4.dp))
                }
            }
            if (state.error.isNotBlank()) ErrorText(state.error)
            if (state.selectedBook == null) BookList(state, viewModel)
            else ChapterList(state, viewModel) { showSettings = true }
        }
    }
    if (showSettings) ModalBottomSheet(onDismissRequest = { showSettings = false }, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).navigationBarsPadding().padding(bottom = 24.dp)) {
            Text(if (state.selectedBook == null) "Inställningar" else "Bokens inställningar",
                modifier = Modifier.padding(horizontal = 16.dp), style = MaterialTheme.typography.headlineSmall)
            SettingsStrip(state, viewModel, requestVoiceRecording, pickVoiceSample)
            Text("Röstvalet sparas för varje bok. Ett nytt val används när du startar ett kapitel.",
                modifier = Modifier.padding(16.dp), style = MaterialTheme.typography.bodySmall)
            TextButton(onClick = { showSettings = false; viewModel.logout() }, modifier = Modifier.padding(horizontal = 8.dp)) { Text("Logga ut") }
        }
    }
    if (showPlayer) ModalBottomSheet(onDismissRequest = { showPlayer = false }, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).navigationBarsPadding()) {
            PlayerPanel(state, viewModel)
        }
    }
}

@Composable
private fun MiniPlayer(state: AppUiState, viewModel: MainViewModel, onOpen: () -> Unit) {
    Surface(color = MaterialTheme.colorScheme.surfaceVariant, shadowElevation = 8.dp) {
        Row(Modifier.fillMaxWidth().navigationBarsPadding().clickable(onClick = onOpen).padding(horizontal = 14.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically) {
            BookCover(state.player.title, compact = true)
            Column(Modifier.weight(1f).padding(horizontal = 12.dp)) {
                Text(state.player.title, maxLines = 1, overflow = TextOverflow.Ellipsis, fontWeight = FontWeight.SemiBold)
                Text(state.player.subtitle, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall)
                if (state.player.durationMs > 0) LinearProgressIndicator(
                    progress = { (state.player.positionMs.toFloat() / state.player.durationMs).coerceIn(0f, 1f) },
                    modifier = Modifier.fillMaxWidth().padding(top = 6.dp),
                )
            }
            IconButton(onClick = viewModel::togglePlayback) {
                Icon(if (state.player.playing) Icons.Default.Pause else Icons.Default.PlayArrow, if (state.player.playing) "Pausa" else "Spela")
            }
            Icon(Icons.Default.ExpandLess, "Öppna spelaren")
        }
    }
}

@Composable
private fun SettingsStrip(
    state: AppUiState,
    viewModel: MainViewModel,
    requestVoiceRecording: () -> Unit,
    pickVoiceSample: () -> Unit,
) {
    var ownVoiceExpanded by remember(state.voiceId) { mutableStateOf(false) }
    val voices = state.voices
        .filter { it.modelBackend.isNullOrBlank() || it.modelBackend == state.modelBackend }
        .sortedWith(compareBy<Voice>({ !it.id.contains("own") }, { it.language }, { it.label.lowercase() }))
    Surface(color = MaterialTheme.colorScheme.surface, tonalElevation = 3.dp) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 10.dp)) {
            Text("Berättarröst", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(
                "Välj hur den här boken ska berättas.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = .62f),
            )
            Spacer(Modifier.height(9.dp))
            SelectionDropdown(
                label = "Röstmodell",
                selected = modelChoices.firstOrNull { it.first == state.modelBackend }?.second ?: state.modelBackend,
                options = modelChoices,
                onSelected = viewModel::setModel,
            )
            Spacer(Modifier.height(8.dp))
            if (voices.isNotEmpty()) {
                SelectionDropdown(
                    label = "Röst",
                    selected = voices.firstOrNull { it.id == state.voiceId }?.label ?: state.voiceId,
                    options = voices.map { it.id to "${it.label} · ${it.language.uppercase()}" },
                    onSelected = viewModel::setVoice,
                )
            }
            if (state.voiceId.contains("own")) {
                TextButton(
                    onClick = { ownVoiceExpanded = !ownVoiceExpanded },
                    modifier = Modifier.align(Alignment.End),
                ) { Text(if (ownVoiceExpanded) "Dölj egen röst" else "Spela in eller byt egen röst") }
                if (ownVoiceExpanded) {
                    OwnVoicePanel(state, viewModel, requestVoiceRecording, pickVoiceSample)
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SelectionDropdown(
    label: String,
    selected: String,
    options: List<Pair<String, String>>,
    onSelected: (String) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    ExposedDropdownMenuBox(expanded = expanded, onExpandedChange = { expanded = !expanded }) {
        OutlinedTextField(
            value = selected,
            onValueChange = {},
            modifier = Modifier.fillMaxWidth().menuAnchor(MenuAnchorType.PrimaryNotEditable),
            readOnly = true,
            singleLine = true,
            label = { Text(label) },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded) },
        )
        ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            options.forEach { (id, optionLabel) ->
                DropdownMenuItem(
                    text = { Text(optionLabel) },
                    onClick = {
                        expanded = false
                        onSelected(id)
                    },
                )
            }
        }
    }
}

@Composable
private fun OwnVoicePanel(
    state: AppUiState,
    viewModel: MainViewModel,
    requestVoiceRecording: () -> Unit,
    pickVoiceSample: () -> Unit,
) {
    val language = state.voices.firstOrNull { it.id == state.voiceId }?.language ?: "sv"
    Card(
        modifier = Modifier.fillMaxWidth().padding(top = 10.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primary.copy(alpha = .09f)),
    ) {
        Column(Modifier.padding(12.dp)) {
            Text("Din egen röst", fontWeight = FontWeight.SemiBold)
            Text(
                ownVoicePrompt(language),
                modifier = Modifier.padding(top = 5.dp),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = .72f),
            )
            Row(
                modifier = Modifier.fillMaxWidth().padding(top = 9.dp),
                horizontalArrangement = Arrangement.spacedBy(7.dp),
            ) {
                if (state.voiceSampleRecording) {
                    Button(onClick = viewModel::stopVoiceRecording, modifier = Modifier.weight(1f)) {
                        Icon(Icons.Default.Stop, null)
                        Spacer(Modifier.width(5.dp))
                        Text("Stoppa")
                    }
                } else {
                    Button(onClick = requestVoiceRecording, enabled = !state.voiceSampleUploading, modifier = Modifier.weight(1f)) {
                        Icon(Icons.Default.Mic, null)
                        Spacer(Modifier.width(5.dp))
                        Text(if (state.voiceSampleReady) "Spela om" else "Spela in")
                    }
                }
                OutlinedButton(
                    onClick = if (state.voiceSamplePlaying) viewModel::stopVoicePreview else viewModel::playVoicePreview,
                    enabled = state.voiceSampleReady,
                    modifier = Modifier.weight(1f),
                ) {
                    Icon(if (state.voiceSamplePlaying) Icons.Default.Stop else Icons.Default.Hearing, null)
                    Spacer(Modifier.width(5.dp))
                    Text(if (state.voiceSamplePlaying) "Stoppa" else "Lyssna")
                }
            }
            OutlinedButton(
                onClick = pickVoiceSample,
                enabled = !state.voiceSampleRecording && !state.voiceSampleUploading,
                modifier = Modifier.fillMaxWidth().padding(top = 7.dp),
            ) { Text("Välj befintlig ljudfil") }
            Row(
                modifier = Modifier.fillMaxWidth().padding(top = 7.dp),
                horizontalArrangement = Arrangement.spacedBy(7.dp),
            ) {
                OutlinedButton(
                    onClick = viewModel::saveVoiceSample,
                    enabled = state.voiceSampleReady && !state.voiceSampleUploading,
                    modifier = Modifier.weight(1f),
                ) {
                    Icon(Icons.Default.Save, null)
                    Spacer(Modifier.width(5.dp))
                    Text("Spara")
                }
                OutlinedButton(
                    onClick = viewModel::replaySavedVoiceSample,
                    enabled = !state.voiceSampleUploading && !state.voiceSampleRecording,
                    modifier = Modifier.weight(1f),
                ) { Text("Sparad röst") }
            }
            if (state.voiceSampleStatus.isNotBlank()) {
                Text(state.voiceSampleStatus, modifier = Modifier.padding(top = 7.dp), style = MaterialTheme.typography.labelSmall)
            }
        }
    }
}

@Composable
private fun BookCover(title: String, compact: Boolean = false) {
    val colors = listOf(Color(0xFF455C51), Color(0xFF5A455F), Color(0xFF42596B), Color(0xFF76513D))
    val color = colors[(title.hashCode() and Int.MAX_VALUE) % colors.size]
    Box(
        Modifier.size(if (compact) 42.dp else 62.dp, if (compact) 56.dp else 86.dp)
            .clip(RoundedCornerShape(7.dp))
            .background(Brush.linearGradient(listOf(color, color.copy(alpha = .45f))))
            .padding(7.dp), contentAlignment = Alignment.Center,
    ) {
        Text(title.trim().take(1).uppercase(), color = Color(0xFFF3EFE7),
            style = if (compact) MaterialTheme.typography.titleLarge else MaterialTheme.typography.headlineLarge,
            fontWeight = FontWeight.Bold)
    }
}

@Composable
private fun BookList(state: AppUiState, viewModel: MainViewModel) {
    var query by rememberSaveable { mutableStateOf("") }
    var filter by rememberSaveable { mutableStateOf(LibraryFilter.ALL) }
    val books = filteredBooks(state.books, query, filter, state.recentBookmarks, state.finishedBooks)
    val recent = state.books.filter { it.id !in state.finishedBooks && it.id in state.recentBookmarks }
        .maxByOrNull { state.recentBookmarks[it.id]?.updatedAtMs ?: 0L }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (recent != null && query.isBlank() && filter == LibraryFilter.ALL) item(key = "continue") {
            val bookmark = state.recentBookmarks.getValue(recent.id)
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primary.copy(alpha = .13f))) {
                Column(Modifier.padding(18.dp)) {
                    Text("FORTSÄTT LYSSNA", color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.labelLarge)
                    Row(Modifier.fillMaxWidth().padding(vertical = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                        BookCover(recent.title)
                        Column(Modifier.weight(1f).padding(start = 16.dp)) {
                            Text(recent.title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold,
                                maxLines = 2, overflow = TextOverflow.Ellipsis)
                            Text(recent.author.orEmpty(), style = MaterialTheme.typography.bodyMedium)
                            Text("Kapitel ${bookmark.chapterIndex + 1}", modifier = Modifier.padding(top = 8.dp), color = MaterialTheme.colorScheme.secondary)
                        }
                    }
                    Button(onClick = { viewModel.continueBook(recent) }, enabled = state.player.ready && !state.busy,
                        modifier = Modifier.fillMaxWidth()) {
                        Icon(Icons.Default.PlayArrow, null)
                        Spacer(Modifier.width(8.dp))
                        Text("Fortsätt lyssna")
                    }
                }
            }
        }
        item(key = "search") {
            OutlinedTextField(value = query, onValueChange = { query = it }, modifier = Modifier.fillMaxWidth(),
                label = { Text("Sök titel eller författare") }, leadingIcon = { Icon(Icons.Default.Search, null) }, singleLine = true)
        }
        item(key = "filters") {
            LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                items(LibraryFilter.entries) { option ->
                    FilterChip(selected = filter == option, onClick = { filter = option }, label = { Text(option.label) })
                }
            }
        }
        if (books.isEmpty()) item {
            Text(if (state.books.isEmpty()) "Biblioteket är tomt. Lägg till en bok via EutherBooks på webben."
                else "Inga böcker matchar ditt val.", modifier = Modifier.padding(vertical = 24.dp))
        }
        items(books, key = { "book:${it.id}" }) { book ->
            Card(modifier = Modifier.fillMaxWidth().clickable { viewModel.selectBook(book) },
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
                Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                    BookCover(book.title)
                    Column(Modifier.weight(1f).padding(start = 16.dp)) {
                        Text(book.title, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        Text(book.author ?: book.format.uppercase(), style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurface.copy(alpha = .65f))
                        val progress = state.recentBookmarks[book.id]
                        Text(when {
                            book.id in state.finishedBooks -> "Färdiglyssnad"
                            progress != null -> "Pågående · kapitel ${progress.chapterIndex + 1}"
                            else -> "Oläst"
                        }, modifier = Modifier.padding(top = 8.dp), style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.secondary)
                    }
                }
            }
        }
    }
}

@Composable
private fun ChapterList(state: AppUiState, viewModel: MainViewModel, onVoiceSettings: () -> Unit) {
    val book = state.selectedBook ?: return
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item {
            Row(Modifier.fillMaxWidth().padding(bottom = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                BookCover(book.title)
                Column(Modifier.weight(1f).padding(start = 16.dp)) {
                    Text(book.title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                    Text(book.author.orEmpty(), color = MaterialTheme.colorScheme.secondary)
                    Text("${state.chapters.size} kapitel", style = MaterialTheme.typography.bodySmall)
                }
            }
            TextButton(onClick = onVoiceSettings) {
                Icon(Icons.Default.Hearing, null)
                Spacer(Modifier.width(8.dp))
                Text(state.voices.firstOrNull { it.id == state.voiceId }?.label ?: "Välj berättarröst")
            }
            if (book.id in state.recentBookmarks) OutlinedButton(
                onClick = { viewModel.continueBook(book) }, enabled = state.player.ready && !state.busy,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Fortsätt där jag slutade") }
            TextButton(onClick = { viewModel.toggleFinished(book) }) {
                Text(if (book.id in state.finishedBooks) "Markera som pågående" else "Markera som färdiglyssnad")
            }
            Text("Kapitel", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(vertical = 10.dp))
        }
        items(state.chapters, key = { it.index }) { chapter ->
            val selected = state.selectedChapter?.index == chapter.index
            val playing = state.player.bookId == book.id && state.player.chapterIndex == chapter.index &&
                state.player.voiceId == state.voiceId && state.player.modelBackend == state.modelBackend
            Card(
                modifier = Modifier.fillMaxWidth().clickable { viewModel.selectChapter(chapter) },
                colors = CardDefaults.cardColors(containerColor = if (selected) MaterialTheme.colorScheme.primary.copy(alpha = .13f) else MaterialTheme.colorScheme.surface),
            ) {
                Column(Modifier.padding(14.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("${chapter.index + 1}", color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Bold)
                        Spacer(Modifier.width(14.dp))
                        Text(chapter.title, modifier = Modifier.weight(1f), maxLines = 2, overflow = TextOverflow.Ellipsis)
                        if (playing) Icon(Icons.Default.Hearing, "Spelas nu", tint = MaterialTheme.colorScheme.secondary)
                    }
                    if (selected) Button(
                        onClick = { if (playing) viewModel.togglePlayback() else viewModel.generateOrPlay() },
                        enabled = state.player.ready && (!state.busy || playing),
                        modifier = Modifier.fillMaxWidth().padding(top = 10.dp),
                    ) { Text(if (playing && state.player.playing) "Pausa" else if (state.busy && !playing) "Förbereder ljud…" else "Spela kapitlet") }
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
                    progress = { state.jobOverallProgress },
                )
                val total = job.totalChunks.takeIf { it > 0 } ?: job.totalAudioFiles
                val complete = completedJobParts(job).coerceAtMost(total.coerceAtLeast(1))
                Text(
                    if (total > 0) "Del ${minOf(total, complete + 1)} av $total · ${formatDuration(state.jobElapsedSeconds)}" else job.progressLabel,
                    style = MaterialTheme.typography.labelMedium,
                    modifier = Modifier.padding(top = 5.dp),
                )
                Text(
                    when {
                        state.jobIdleSeconds >= 60 -> "Servern arbetar fortfarande · ingen ny del på ${formatDuration(state.jobIdleSeconds)}"
                        job.audioFiles.isNotEmpty() -> "${job.audioFiles.size} delar färdiga · spelar medan resten skapas"
                        else -> job.progressDetail.ifBlank { "Väntar på första ljuddelen…" }
                    },
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.secondary,
                    modifier = Modifier.padding(top = 2.dp, bottom = 6.dp),
                )
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
                var scrubPosition by remember { mutableStateOf<Float?>(null) }
                Text(when {
                    !state.player.chapterTimeline -> "Aktuell ljuddel"
                    state.player.chapterComplete -> "Kapitlet"
                    else -> "Tillgängligt ljud · mer skapas"
                }, style = MaterialTheme.typography.labelMedium, modifier = Modifier.padding(top = 16.dp))
                Slider(
                    value = scrubPosition ?: (state.player.positionMs.toFloat() / state.player.durationMs).coerceIn(0f, 1f),
                    onValueChange = { scrubPosition = it },
                    onValueChangeFinished = {
                        scrubPosition?.let { viewModel.seekToPosition((it * state.player.durationMs).toLong()) }
                        scrubPosition = null
                    },
                    modifier = Modifier.fillMaxWidth(),
                )
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(formatTime(scrubPosition?.let { (it * state.player.durationMs).toLong() } ?: state.player.positionMs), style = MaterialTheme.typography.labelSmall)
                    Text(formatTime(state.player.durationMs), style = MaterialTheme.typography.labelSmall)
                }
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = viewModel::previous) { Icon(Icons.Default.SkipPrevious, "Föregående kapitel") }
                IconButton(onClick = { viewModel.seekBy(-10_000) }) { Icon(Icons.Default.Replay10, "Bakåt 10 sekunder") }
                IconButton(onClick = viewModel::togglePlayback, modifier = Modifier.size(54.dp)) {
                    Icon(if (state.player.playing) Icons.Default.Pause else Icons.Default.PlayArrow, if (state.player.playing) "Pausa" else "Spela", modifier = Modifier.size(38.dp))
                }
                IconButton(onClick = { viewModel.seekBy(10_000) }) { Icon(Icons.Default.Forward10, "Framåt 10 sekunder") }
                IconButton(onClick = viewModel::next) { Icon(Icons.Default.SkipNext, "Nästa kapitel") }
            }
            SelectionDropdown(
                label = "Uppspelningshastighet",
                selected = "${state.player.speed}×",
                options = listOf(.5f, .75f, 1f, 1.25f, 1.5f, 1.75f, 2f).map { it.toString() to "${it}×" },
                onSelected = { viewModel.setPlaybackSpeed(it.toFloat()) },
            )
            TextButton(onClick = viewModel::saveBookmark, enabled = state.player.itemCount > 0) { Text("Spara lyssningsposition") }
            Text("Sovtimer", style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 10.dp))
            LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                items(listOf(0, 15, 30, 60)) { minutes ->
                    FilterChip(selected = (state.sleepMinutes ?: 0) == minutes,
                        onClick = { viewModel.setSleepTimer(minutes.takeIf { it > 0 }) },
                        label = { Text(if (minutes == 0) "Av" else "$minutes min") })
                }
            }
            FilterChip(selected = state.autoNext, onClick = { viewModel.setAutoNext(!state.autoNext) }, label = { Text("Fortsätt till nästa kapitel") })
            if (state.message.isNotBlank()) Text(state.message, style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.secondary, modifier = Modifier.padding(vertical = 8.dp))

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

private fun formatDuration(seconds: Long): String {
    val minutes = seconds / 60
    val remainder = seconds % 60
    return if (minutes > 0) "${minutes}m ${remainder}s" else "${remainder}s"
}
