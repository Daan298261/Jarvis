package com.jarvis.companion

import android.content.Context
import java.util.Locale

/**
 * RFC-0216 S4: ANZU's voice language, independent of the phone's system locale.
 * Default is the product language (English) so a Dutch phone does not speak English with a Dutch voice.
 * STT language defaults to the voice language; S3 owns recognizer logic, S4 only supplies the tag.
 */
data class VoiceLanguageSetting(
    /** BCP-47 tag for spoken replies, e.g. "en", "en-GB", "nl-NL". */
    val ttsLanguage: String = VoiceLanguagePrefs.DEFAULT_LANGUAGE,
    /** Android TextToSpeech voice name; blank = best installed voice for [ttsLanguage]. */
    val ttsVoiceName: String = "",
    /** BCP-47 tag for speech recognition; blank = same as [ttsLanguage]. */
    val sttLanguageOverride: String = "",
) {
    val ttsLocale: Locale get() = Locale.forLanguageTag(ttsLanguage)
    val sttLanguage: String get() = sttLanguageOverride.ifBlank { ttsLanguage }
    /** Regioned tag for Android recognizers (bare "en" → "en-US"); on-device recognizers reject region-less tags. */
    val recognizerLanguage: String get() = VoiceLanguagePrefs.recognizerTag(sttLanguage)
}

data class VoiceLanguageOption(val tag: String, val label: String)

/** Minimal view of an Android TTS voice so selection is testable on the JVM. */
data class TtsVoiceCandidate(
    val name: String,
    val locale: Locale,
    val quality: Int,
    val latency: Int,
    val needsNetwork: Boolean,
    val notInstalled: Boolean,
)

object VoiceLanguagePrefs {
    const val PREFS = "voice_language"
    const val KEY_TTS_LANGUAGE = "tts_language"
    const val KEY_TTS_VOICE = "tts_voice"
    const val KEY_STT_LANGUAGE = "stt_language"
    /** ANZU's product/UI language. */
    const val DEFAULT_LANGUAGE = "en"

    val options = listOf(
        VoiceLanguageOption("en", "English"),
        VoiceLanguageOption("en-GB", "English (UK)"),
        VoiceLanguageOption("en-US", "English (US)"),
        VoiceLanguageOption("nl-NL", "Nederlands"),
        VoiceLanguageOption("de-DE", "Deutsch"),
        VoiceLanguageOption("fr-FR", "Français"),
        VoiceLanguageOption("es-ES", "Español"),
    )

    private val defaultRegion = mapOf("en" to "US", "nl" to "NL", "de" to "DE", "fr" to "FR", "es" to "ES")

    /** Adds a region to a region-less tag: explicit defaults first, then ICU likely subtags. */
    fun recognizerTag(tag: String): String {
        val locale = Locale.forLanguageTag(tag.ifBlank { DEFAULT_LANGUAGE })
        if (locale.country.isNotEmpty()) return locale.toLanguageTag()
        val region = defaultRegion[locale.language]
            ?: runCatching { android.icu.util.ULocale.addLikelySubtags(android.icu.util.ULocale.forLocale(locale)).country }
                .getOrNull().orEmpty()
        return if (region.isEmpty()) locale.toLanguageTag() else Locale(locale.language, region).toLanguageTag()
    }

    fun label(tag: String): String = options.firstOrNull { it.tag == tag }?.label ?: tag

    fun load(context: Context): VoiceLanguageSetting {
        val p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        return VoiceLanguageSetting(
            ttsLanguage = p.getString(KEY_TTS_LANGUAGE, null)?.takeIf { it.isNotBlank() } ?: DEFAULT_LANGUAGE,
            ttsVoiceName = p.getString(KEY_TTS_VOICE, "") ?: "",
            sttLanguageOverride = p.getString(KEY_STT_LANGUAGE, "") ?: "",
        )
    }

    fun save(context: Context, setting: VoiceLanguageSetting): Boolean =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString(KEY_TTS_LANGUAGE, setting.ttsLanguage)
            .putString(KEY_TTS_VOICE, setting.ttsVoiceName)
            .putString(KEY_STT_LANGUAGE, setting.sttLanguageOverride)
            .commit()

    /** Changing language drops a voice that belongs to another language. */
    fun withLanguage(current: VoiceLanguageSetting, tag: String): VoiceLanguageSetting =
        if (sameLanguage(current.ttsLanguage, tag)) current.copy(ttsLanguage = tag)
        else current.copy(ttsLanguage = tag, ttsVoiceName = "")

    fun sameLanguage(a: String, b: String): Boolean =
        Locale.forLanguageTag(a).language.equals(Locale.forLanguageTag(b).language, ignoreCase = true)

    /** Languages an on-device TTS pack can speak. Pocket TTS (Alba) is English-only. */
    fun packLanguages(pack: CompanionVoicePack?): Set<String> = when (pack?.engine) {
        CompanionVoicePackCatalog.POCKET_TTS_ENGINE -> setOf("en")
        else -> emptySet()
    }

    fun packSpeaks(pack: CompanionVoicePack?, tag: String): Boolean =
        packLanguages(pack).any { sameLanguage(it, tag) }

    /**
     * Voices usable for [setting], best first: explicit name (if it matches the language), then
     * installed offline voices for the exact region, then same language, by quality and latency.
     * Never returns a voice for a different language — callers must surface "install" instead.
     */
    fun rankVoices(voices: Collection<TtsVoiceCandidate>, setting: VoiceLanguageSetting): List<TtsVoiceCandidate> {
        val want = setting.ttsLocale
        val usable = voices.filter { !it.notInstalled && it.locale.language.equals(want.language, ignoreCase = true) }
        return usable.sortedWith(
            compareByDescending<TtsVoiceCandidate> { setting.ttsVoiceName.isNotBlank() && it.name == setting.ttsVoiceName }
                .thenByDescending { want.country.isNotEmpty() && it.locale.country.equals(want.country, ignoreCase = true) }
                .thenBy { it.needsNetwork }
                .thenByDescending { it.quality }
                .thenBy { it.latency }
                .thenBy { it.name },
        )
    }

    fun pickVoice(voices: Collection<TtsVoiceCandidate>, setting: VoiceLanguageSetting): TtsVoiceCandidate? =
        rankVoices(voices, setting).firstOrNull()

    fun missingVoiceMessage(setting: VoiceLanguageSetting): String {
        val name = label(setting.ttsLanguage)
        val pack = if (sameLanguage(setting.ttsLanguage, "en")) " or download ANZU's English voice (Pocket TTS) in More → Voice" else ""
        return "This phone has no $name voice installed. Install $name voice data in Android settings (Text-to-speech → Install voice data)$pack."
    }
}

/** RFC-0216 S4: what is left to say when the on-device pack fails mid-reply. */
object OnDeviceTtsFallback {
    fun remainingText(chunks: List<String>, played: Int): String =
        chunks.drop(played.coerceIn(0, chunks.size)).joinToString(" ").trim()

    fun fallbackNotice(packError: String?, languageLabel: String): String =
        "Offline voice failed${packError?.takeIf { it.isNotBlank() }?.let { " ($it)" } ?: ""} — finishing on this phone's $languageLabel voice."

    fun shouldUsePlatform(remaining: String, platformSpeaksLanguage: Boolean): Boolean =
        remaining.isNotEmpty() && platformSpeaksLanguage
}
