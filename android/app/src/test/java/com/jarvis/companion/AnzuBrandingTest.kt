package com.jarvis.companion

import org.junit.Assert.assertEquals
import org.junit.Test

class AnzuBrandingTest {
    @Test
    fun display_name_is_anzu() {
        assertEquals("ANZU", AnzuBranding.DISPLAY_NAME)
    }
}
