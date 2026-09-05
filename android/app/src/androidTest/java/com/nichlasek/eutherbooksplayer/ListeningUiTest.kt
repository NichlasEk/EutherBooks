package com.nichlasek.eutherbooksplayer

import android.app.Application
import android.graphics.Bitmap
import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.After
import org.junit.Rule
import org.junit.Test
import java.io.File

class ListeningUiTest {
    @get:Rule val compose = createComposeRule()
    private val store = androidx.lifecycle.ViewModelStore()
    @After fun closeViewModels() { store.clear() }
    private val books = listOf(
        Book("a", "Skogen vid havet", "Anna Lind"),
        Book("b", "Vägen hem", "Bo Berg"),
        Book("c", "När stjärnorna tänds", "Clara Holm"),
    )
    private val bookmark = Bookmark("a", 3, "sv", "dots.tts-mf", 1, 32_000, 100, "På andra sidan viken")
    private val fixture = AppUiState(
        authenticated = true, books = books,
        recentBookmarks = mapOf("a" to bookmark), finishedBooks = setOf("c"),
        voices = listOf(Voice("sv", "Svensk berättare", "sv", modelBackend = "dots.tts-mf")), voiceId = "sv",
        player = PlayerUiState(ready = true, title = books[0].title, subtitle = "På andra sidan viken",
            itemCount = 4, positionMs = 332_000, durationMs = 900_000, bookId = "a", chapterIndex = 3,
            chapterTimeline = true, chapterComplete = true),
    )

    private fun show(state: AppUiState) {
        val app = InstrumentationRegistry.getInstrumentation().targetContext.applicationContext as Application
        val viewModel = androidx.lifecycle.ViewModelProvider(store, androidx.lifecycle.ViewModelProvider.AndroidViewModelFactory(app))[MainViewModel::class.java]
        compose.setContent { MaterialTheme(colorScheme = EutherDark) { MainScreen(state, viewModel, {}, {}) } }
    }

    private fun screenshot(name: String) {
        compose.waitForIdle()
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val dir = File(instrumentation.targetContext.getExternalFilesDir(null), "review").apply { mkdirs() }
        instrumentation.uiAutomation.takeScreenshot().let { bitmap ->
            File(dir, "$name.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
            bitmap.recycle()
        }
    }

    @Test fun libraryShowsContinueAndSearchesAuthorsWithoutVoiceControls() {
        show(fixture)
        compose.onNodeWithText("FORTSÄTT LYSSNA").assertIsDisplayed()
        compose.onNodeWithText("Röstmodell").assertDoesNotExist()
        screenshot("library")
        compose.onNodeWithText("Sök titel eller författare").performTextInput("Bo Berg")
        compose.onNodeWithText("Vägen hem").assertIsDisplayed()
        compose.onNodeWithText("FORTSÄTT LYSSNA").assertDoesNotExist()
        compose.onNodeWithText("Färdiga").performClick()
        compose.onNodeWithText("Inga böcker matchar ditt val.").assertIsDisplayed()
    }

    @Test fun expandedPlayerShowsChapterTimelineAndSpeed() {
        show(fixture)
        compose.onNodeWithContentDescription("Öppna spelaren").performClick()
        compose.onNodeWithText("Kapitlet").assertIsDisplayed()
        compose.onNodeWithText("15:00").assertIsDisplayed()
        compose.onNodeWithText("Uppspelningshastighet").assertIsDisplayed()
        screenshot("player")
    }

    @Test fun bookKeepsVoiceSetupBehindSettings() {
        show(fixture.copy(selectedBook = books[0], selectedChapter = Chapter(3, "På andra sidan viken"),
            chapters = listOf(Chapter(0, "Den första morgonen"), Chapter(1, "Ett oväntat brev"), Chapter(3, "På andra sidan viken"))))
        compose.onNodeWithText("Fortsätt där jag slutade").assertIsDisplayed()
        screenshot("chapters")
        compose.onNodeWithContentDescription("Inställningar").performClick()
        compose.onNodeWithText("Bokens inställningar").assertIsDisplayed()
        compose.onNodeWithText("Röstmodell").assertIsDisplayed()
    }
}
