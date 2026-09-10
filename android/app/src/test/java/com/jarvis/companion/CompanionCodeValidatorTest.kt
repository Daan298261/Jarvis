package com.jarvis.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CompanionCodeValidatorTest {
    @Test
    fun normalize_strips_non_digits_and_caps_length() {
        assertEquals("012345", CompanionCodeValidator.normalize("01-23-45-99"))
        assertEquals("123456", CompanionCodeValidator.normalize("abc1234567890"))
    }

    @Test
    fun validate_accepts_six_digits() {
        val result = CompanionCodeValidator.validate("012345")
        assertTrue(result is CompanionCodeValidation.Valid)
        assertEquals("012345", (result as CompanionCodeValidation.Valid).code)
    }

    @Test
    fun validate_rejects_short_input() {
        val result = CompanionCodeValidator.validate("123")
        assertTrue(result is CompanionCodeValidation.Incomplete)
        assertEquals(3, (result as CompanionCodeValidation.Incomplete).remaining)
    }

    @Test
    fun isComplete_requires_six_digits() {
        assertEquals(false, CompanionCodeValidator.isComplete("12345"))
        assertEquals(true, CompanionCodeValidator.isComplete("123456"))
    }
}
