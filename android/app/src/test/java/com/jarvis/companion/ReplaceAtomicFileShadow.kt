package com.jarvis.companion

import android.util.AtomicFile
import org.robolectric.annotation.Implementation
import org.robolectric.annotation.Implements
import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption

/** Match Android rename(2) replacement semantics on Windows test hosts. */
@Implements(AtomicFile::class)
class ReplaceAtomicFileShadow {
    companion object {
        @JvmStatic
        @Implementation
        fun rename(source: File, target: File) {
            Files.move(source.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING)
        }
    }
}
