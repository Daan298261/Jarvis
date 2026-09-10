package com.jarvis.companion

/**
 * RFC-0063 — validates 6-digit decimal pairing codes before enroll.
 */
object CompanionCodeValidator {
    private val CODE_PATTERN = Regex("^\\d{6}$")

    fun normalize(input: String): String = input.filter(Char::isDigit).take(6)

    fun isComplete(input: String): Boolean = normalize(input).length == 6

    fun validate(input: String): CompanionCodeValidation {
        val digits = input.trim()
        if (digits.any { !it.isDigit() }) {
            return CompanionCodeValidation.Invalid("Enter exactly 6 digits.")
        }
        if (digits.length != 6) {
            return CompanionCodeValidation.Incomplete(remaining = (6 - digits.length).coerceAtLeast(0))
        }
        if (!CODE_PATTERN.matches(digits)) {
            return CompanionCodeValidation.Invalid("Enter exactly 6 digits.")
        }
        return CompanionCodeValidation.Valid(digits)
    }
}

sealed class CompanionCodeValidation {
    data class Valid(val code: String) : CompanionCodeValidation()
    data class Incomplete(val remaining: Int) : CompanionCodeValidation()
    data class Invalid(val message: String) : CompanionCodeValidation()
}
