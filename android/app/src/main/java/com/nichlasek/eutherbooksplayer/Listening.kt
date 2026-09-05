package com.nichlasek.eutherbooksplayer

/** Pure chapter arithmetic shared by the player and seek controls. */
data class ChapterTimeline(
    val queueIndexes: List<Int>,
    val durationsMs: List<Long>,
    val positionMs: Long,
    val complete: Boolean,
) {
    val durationMs: Long get() = durationsMs.sum()

    fun seekTarget(positionMs: Long): Pair<Int, Long>? {
        if (queueIndexes.isEmpty() || durationsMs.any { it <= 0 }) return null
        var remaining = positionMs.coerceIn(0, durationMs)
        durationsMs.forEachIndexed { index, duration ->
            if (remaining < duration || index == durationsMs.lastIndex) {
                return queueIndexes[index] to remaining.coerceAtMost(duration)
            }
            remaining -= duration
        }
        return null
    }
}

internal fun chapterTimeline(entries: List<QueueEntry>, currentIndex: Int, positionMs: Long): ChapterTimeline? {
    val current = entries.getOrNull(currentIndex) ?: return null
    if (current.bookId.isNullOrBlank() || current.chapterIndex < 0) return null
    val jobId = current.mediaId.substringBeforeLast(':')
    val indexes = entries.indices.filter {
        entries[it].bookId == current.bookId && entries[it].chapterIndex == current.chapterIndex &&
            entries[it].mediaId.substringBeforeLast(':') == jobId
    }
    val durations = indexes.map { entries[it].durationMs }
    if (durations.any { it <= 0 }) return null
    return ChapterTimeline(
        indexes, durations,
        indexes.takeWhile { it != currentIndex }.sumOf { entries[it].durationMs } +
            positionMs.coerceIn(0, current.durationMs),
        indexes.all { entries[it].chapterComplete },
    )
}

enum class LibraryFilter(val label: String) {
    ALL("Alla"), IN_PROGRESS("Pågående"), UNREAD("Olästa"), FINISHED("Färdiga"),
}

internal fun filteredBooks(
    books: List<Book>, query: String, filter: LibraryFilter,
    progress: Map<String, Bookmark>, finished: Set<String>,
): List<Book> = books.filter { book ->
    val matchesQuery = query.trim().let { it.isEmpty() || book.title.contains(it, true) || book.author.orEmpty().contains(it, true) }
    matchesQuery && when (filter) {
        LibraryFilter.ALL -> true
        LibraryFilter.IN_PROGRESS -> book.id in progress && book.id !in finished
        LibraryFilter.UNREAD -> book.id !in progress && book.id !in finished
        LibraryFilter.FINISHED -> book.id in finished
    }
}.sortedWith(compareByDescending<Book> { progress[it.id]?.updatedAtMs ?: 0L }.thenBy { it.title.lowercase() })
