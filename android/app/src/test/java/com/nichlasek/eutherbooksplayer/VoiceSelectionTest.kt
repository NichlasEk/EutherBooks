package com.nichlasek.eutherbooksplayer

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class VoiceSelectionTest {
    @Test
    fun keepsPreferredCompatibleVoice() {
        val voices = listOf(
            Voice(id = "sv-a", language = "sv", modelBackend = "voxcpm2"),
            Voice(id = "sv-own", language = "sv", modelBackend = "dots.tts-mf"),
        )
        assertEquals("sv-own", selectBestVoice(voices, "dots.tts-mf", "sv-own")?.id)
    }

    @Test
    fun rejectsVoiceFromAnotherBackend() {
        val voices = listOf(Voice(id = "sv-a", language = "sv", modelBackend = "voxcpm2"))
        assertNull(selectBestVoice(voices, "dots.tts-mf", "sv-a"))
    }
}
