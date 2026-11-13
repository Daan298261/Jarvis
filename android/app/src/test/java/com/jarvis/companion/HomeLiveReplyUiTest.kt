package com.jarvis.companion

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.darkColorScheme
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import org.json.JSONObject
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** RFC-0235 criterion E: Home shows a streamed on-device reply once, and the old line is unchanged otherwise. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], qualifiers = "w411dp-h2000dp")
class HomeLiveReplyUiTest {
    @get:Rule val compose = createComposeRule()

    private fun assistant(text: String) = JSONObject().put("role", "assistant").put("text", text)

    private fun show(state: CompanionState) = compose.setContent {
        MaterialTheme(colorScheme = darkColorScheme()) { Surface { Column { HomeReplyLines(state) } } }
    }

    @Test fun homeShowsTheStreamedReplyOnce() {
        // While streaming, the pending Chat bubble carries the same partial text as the Home preview.
        show(CompanionState(offlineAnswering = true, activity = "Writing reply · 2s",
            liveLocalReply = "Streaming reply so far", messages = listOf(assistant("Streaming reply so far"))))
        compose.onAllNodesWithText("Streaming reply so far").assertCountEquals(1)
        compose.onNodeWithText("Writing reply · 2s").assertExists()
    }

    @Test fun theStalePreviousReplyIsHiddenWhileTheStreamShows() {
        show(CompanionState(liveLocalReply = "New streamed words", messages = listOf(assistant("Last turn's answer"))))
        compose.onAllNodesWithText("New streamed words").assertCountEquals(1)
        compose.onAllNodesWithText("Last turn's answer").assertCountEquals(0)
    }

    @Test fun theExistingLastAssistantLineRendersAsBeforeWhenNothingStreams() {
        show(CompanionState(activity = "Ready when you are", liveLocalReply = "", messages = listOf(assistant("The answer you saw"))))
        compose.onAllNodesWithText("The answer you saw").assertCountEquals(1)
        compose.onNodeWithText("Ready when you are").assertExists()
    }

    @Test fun aFailedTurnsErrorBubbleShowsAsTheLastLineAfterThePreviewIsCleared() {
        show(CompanionState(error = "model crashed", liveLocalReply = "", messages = listOf(assistant("model crashed"))))
        compose.onAllNodesWithText("model crashed").assertCountEquals(1)
    }
}
