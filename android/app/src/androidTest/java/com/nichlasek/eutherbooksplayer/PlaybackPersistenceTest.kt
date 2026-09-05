package com.nichlasek.eutherbooksplayer

import android.content.ComponentName
import androidx.media3.common.Player
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import androidx.test.platform.app.InstrumentationRegistry
import com.google.gson.Gson
import org.junit.Assert.*
import org.junit.Test
import java.net.ServerSocket
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

class PlaybackPersistenceTest {
    @Test fun upgradeRetainsLegacyProgressAndKeepsNewBookPreferencesSeparate() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val raw = context.getSharedPreferences("eutherbooks-native", 0)
        val preferences = AppPreferences(context)
        val originalUser = preferences.username
        val owner = raw.getString("legacy_bookmark_owner", null)
        try {
            preferences.username = "upgrade-test"
            raw.edit().putString("legacy_bookmark_owner", "upgrade-test").commit()
            val old = Bookmark("legacy-book", 4, "sv", "dots", 2, 1500, 100)
            val oldKey = AppPreferences.bookmarkKey(old.bookId, old.chapterIndex, old.voiceId, old.modelBackend)
            raw.edit().putString(oldKey, Gson().toJson(old)).commit()
            assertEquals(old, preferences.recentBookmarks()["legacy-book"])
            assertEquals(old, preferences.bookmark("legacy-book", 4, "sv", "dots"))
            preferences.saveBookmark(old.copy(positionMs = 5000, updatedAtMs = 200))
            preferences.saveBookVoice("legacy-book", BookVoice("en", "other-model"))
            assertEquals(5000L, preferences.recentBookmarks().getValue("legacy-book").positionMs)
            assertEquals("en", preferences.bookVoice("legacy-book")?.voiceId)
            preferences.username = "other-test-user"
            assertNull(preferences.recentBookmarks()["legacy-book"])
            assertNull(preferences.bookVoice("legacy-book"))
            assertNull(preferences.bookmark("legacy-book", 4, "sv", "dots"))
        } finally {
            preferences.username = originalUser
            raw.edit().apply {
                raw.all.keys.filter { it.startsWith("user:upgrade-test:") || it.startsWith("bookmark:legacy-book:") }.forEach(::remove)
                if (owner == null) remove("legacy_bookmark_owner") else putString("legacy_bookmark_owner", owner)
            }.commit()
        }
    }

    @Test fun servicePersistsActualPlayingChapterPartAndSpeed() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val server = ServerSocket(0)
        val pcm = ByteArray(160_000)
        val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN).apply {
            put("RIFF".toByteArray()); putInt(36 + pcm.size); put("WAVEfmt ".toByteArray()); putInt(16)
            putShort(1); putShort(1); putInt(8000); putInt(16000); putShort(2); putShort(16)
            put("data".toByteArray()); putInt(pcm.size)
        }.array()
        val bytes = header + pcm
        val worker = thread(isDaemon = true) {
            while (!server.isClosed) runCatching {
                server.accept().use { socket ->
                    val reader = socket.getInputStream().bufferedReader()
                    while (!reader.readLine().isNullOrEmpty()) { }
                    socket.getOutputStream().apply {
                        write("HTTP/1.1 200 OK\r\nContent-Type: audio/wav\r\nContent-Length: ${bytes.size}\r\nConnection: close\r\n\r\n".toByteArray())
                        write(bytes); flush()
                    }
                }
            }
        }
        val first = QueueEntry("http://127.0.0.1:${server.localPort}/one.wav", "test-job:0", "Test book", "Kapitel två",
            bookId = "instrumented-book", chapterIndex = 1, chapterTitle = "Kapitel två", voiceId = "sv", modelBackend = "test",
            partIndex = 0, durationMs = 10_000, chapterComplete = true)
        val second = first.copy(uri = "http://127.0.0.1:${server.localPort}/two.wav", mediaId = "test-job:1", partIndex = 1)
        val restored = Gson().fromJson(Gson().toJson(SavedQueue(listOf(first, second), 1, 2500)), SavedQueue::class.java)
        assertEquals(second, restored.entries[1].toMediaItem().queueEntry())
        lateinit var future: com.google.common.util.concurrent.ListenableFuture<MediaController>
        instrumentation.runOnMainSync {
            future = MediaController.Builder(context, SessionToken(context, ComponentName(context, PlaybackService::class.java))).buildAsync()
        }
        val controller = future.get(15, TimeUnit.SECONDS)
        try {
            instrumentation.runOnMainSync {
                controller.setMediaItems(restored.entries.map { it.toMediaItem() }, restored.index, restored.positionMs)
                controller.prepare()
                controller.setPlaybackSpeed(1.5f)
                controller.play()
            }
            val deadline = System.currentTimeMillis() + 15_000
            var ready = false
            while (!ready && System.currentTimeMillis() < deadline) {
                instrumentation.runOnMainSync { ready = controller.playbackState == Player.STATE_READY && controller.currentPosition >= 2500 }
                Thread.sleep(100)
            }
            assertTrue("Audio should become playable", ready)
            instrumentation.runOnMainSync {
                assertEquals(1.5f, controller.playbackParameters.speed, .001f)
                controller.pause()
            }
            Thread.sleep(600)
            val progress = AppPreferences(context).recentBookmarks().getValue("instrumented-book")
            assertEquals(1, progress.chapterIndex)
            assertEquals(1, progress.mediaIndex)
            assertEquals("test", progress.modelBackend)
            assertTrue(progress.positionMs >= 2500)
        } finally {
            instrumentation.runOnMainSync { controller.stop(); controller.clearMediaItems(); controller.release() }
            server.close()
            worker.join(1000)
        }
    }
}
