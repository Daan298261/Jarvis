package com.jarvis.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MediaUploadPlannerTest {
    @Test
    fun detectKindFromMime() {
        assertEquals("image", MediaUploadPlanner.detectKind("image/jpeg", "photo.jpg"))
        assertEquals("video", MediaUploadPlanner.detectKind("video/mp4", "clip.mp4"))
        assertEquals("audio", MediaUploadPlanner.detectKind("audio/mpeg", "note.mp3"))
        assertEquals("file", MediaUploadPlanner.detectKind("application/pdf", "doc.pdf"))
    }

    @Test
    fun chunkCountAndPolicy() {
        assertEquals(1, MediaUploadPlanner.chunkCount(1024))
        assertEquals(2, MediaUploadPlanner.chunkCount(MediaUploadPlanner.CHUNK_SIZE.toLong() + 1))
        assertTrue(MediaUploadPlanner.shouldChunk("video", 1024))
        assertTrue(MediaUploadPlanner.shouldChunk("image", MediaUploadPlanner.CHUNK_SIZE.toLong() + 1))
    }
}
