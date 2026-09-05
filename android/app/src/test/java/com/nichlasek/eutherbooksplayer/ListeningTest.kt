package com.nichlasek.eutherbooksplayer

import org.junit.Assert.*
import org.junit.Test

class ListeningTest {
    private fun part(job: String, part: Int, duration: Long, chapter: Int = 0, complete: Boolean = true) =
        QueueEntry("https://example.invalid/$job/$part.mp3", "$job:$part", "Book", "Chapter",
            bookId = "book", chapterIndex = chapter, partIndex = part, durationMs = duration,
            chapterComplete = complete)

    @Test fun seekCrossesAudioPartsWithoutEnteringTheNextChapter() {
        val entries = listOf(part("a", 0, 10_000), part("a", 1, 20_000), part("b", 0, 50_000, chapter = 1))
        val timeline = chapterTimeline(entries, 1, 4_000)!!
        assertEquals(14_000L, timeline.positionMs)
        assertEquals(30_000L, timeline.durationMs)
        assertEquals(0 to 8_000L, timeline.seekTarget(8_000))
        assertEquals(1 to 0L, timeline.seekTarget(10_000))
        assertEquals(1 to 5_000L, timeline.seekTarget(15_000))
        assertEquals(1 to 20_000L, timeline.seekTarget(90_000))
        assertEquals(0 to 0L, timeline.seekTarget(-500))
    }

    @Test fun timelineUsesQueueIndexesButBookmarksUsePartIndexes() {
        val entries = listOf(part("a", 0, 10_000), part("b", 0, 20_000, chapter = 1), part("b", 1, 30_000, chapter = 1))
        val timeline = chapterTimeline(entries, 2, 5_000)!!
        assertEquals(25_000L, timeline.positionMs)
        assertEquals(1 to 5_000L, timeline.seekTarget(5_000))
        assertEquals(1, entries[2].partIndex)
    }

    @Test fun unknownDurationsAndLegacyQueuesDoNotPretendToHaveChapterTime() {
        assertNull(chapterTimeline(listOf(part("a", 0, 0)), 0, 0))
        assertNull(chapterTimeline(listOf(QueueEntry("uri", "legacy", "title", "subtitle")), 0, 0))
        assertNull(chapterTimeline(emptyList(), 0, 0))
    }

    @Test fun partialGenerationHasAvailableTimeWithoutClaimingTheChapterIsComplete() {
        val timeline = chapterTimeline(listOf(part("a", 0, 10_000, complete = false)), 0, 2_000)!!
        assertEquals(10_000L, timeline.durationMs)
        assertFalse(timeline.complete)
    }

    @Test fun alternateGenerationsOfTheSameChapterDoNotInflateDuration() {
        val timeline = chapterTimeline(listOf(part("a", 0, 10_000), part("b", 0, 20_000)), 0, 0)!!
        assertEquals(10_000L, timeline.durationMs)
    }

    @Test fun filtersDistinguishUnreadStartedAndFinishedAndSearchAuthors() {
        val books = listOf(Book("a", "Skogen", "Anna"), Book("b", "Havet", "Bo"), Book("c", "Bergen", "Anna"))
        val progress = mapOf("a" to Bookmark("a", 2, "sv", "dots", 0, 10, 100))
        assertEquals(listOf("a"), filteredBooks(books, " ANNA ", LibraryFilter.IN_PROGRESS, progress, setOf("c")).map { it.id })
        assertEquals(listOf("b"), filteredBooks(books, "", LibraryFilter.UNREAD, progress, setOf("c")).map { it.id })
        assertEquals(listOf("c"), filteredBooks(books, "", LibraryFilter.FINISHED, progress, setOf("c")).map { it.id })
        assertEquals(listOf("a", "c"), filteredBooks(books, "anna", LibraryFilter.ALL, progress, setOf("c")).map { it.id })
    }
}
