package com.nichlasek.eutherbooksplayer

import org.junit.Assert.assertEquals
import org.junit.Test

class JobProgressTest {
    @Test
    fun combinesCompletedPartsWithCurrentWorkerProgress() {
        val job = Job(
            currentChunkIndex = 3,
            totalChunks = 26,
            workerProgress = 0.5,
            audioFiles = listOf("a.mp3", "b.mp3", "c.mp3"),
        )
        assertEquals(3, completedJobParts(job))
        assertEquals(3.5f / 26f, overallJobProgress(job), 0.0001f)
    }

    @Test
    fun neverReportsMoreThanComplete() {
        val job = Job(
            currentChunkIndex = 26,
            totalChunks = 26,
            workerProgress = 1.0,
            audioFiles = List(26) { "$it.mp3" },
        )
        assertEquals(1f, overallJobProgress(job), 0f)
    }

    @Test
    fun hasNoFakeProgressWhenTotalIsUnknown() {
        assertEquals(0f, overallJobProgress(Job(workerProgress = 0.8)), 0f)
    }
}
