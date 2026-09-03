package com.nichlasek.eutherbooksplayer

import org.junit.Assert.assertEquals
import org.junit.Test

class UrlHelpersTest {
    @Test
    fun normalizesKnownPublicHostAndPath() {
        assertEquals(
            "https://apothictech.se:8443/eutherbooks",
            normalizeBaseUrl("https://apothichtech.se/"),
        )
    }

    @Test
    fun preservesLanProxy() {
        assertEquals(
            "http://192.168.32.186:8080/eutherbooks",
            normalizeBaseUrl("http://192.168.32.186:8080"),
        )
    }

    @Test
    fun encodesAudioPathSegment() {
        assertEquals("part%20one.mp3", EutherBooksApi.segment("part one.mp3"))
    }
}
