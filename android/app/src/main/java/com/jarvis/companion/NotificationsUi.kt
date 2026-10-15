package com.jarvis.companion

import android.text.format.DateUtils
import androidx.compose.animation.core.animateFloat
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

private val InfoColor = Color(0xFF74DCCD)
private val WarningColor = Color(0xFFF5A623)
private val ErrorColor = Color(0xFFE8A87C)

internal fun severityColor(severity: NoticeSeverity): Color = when (severity) {
    NoticeSeverity.INFO -> InfoColor
    NoticeSeverity.WARNING -> WarningColor
    NoticeSeverity.ERROR -> ErrorColor
}

internal fun noticeTitleRes(kind: NoticeKind): Int = when (kind) {
    NoticeKind.DESKTOP_OFFLINE -> R.string.notice_title_desktop_offline
    NoticeKind.PENDING_MESSAGE -> R.string.notice_title_pending
    NoticeKind.MODEL_DOWNLOAD -> R.string.notice_title_model_download
    NoticeKind.VOICE_DOWNLOAD -> R.string.notice_title_voice_download
    NoticeKind.ERROR -> R.string.notice_title_error
}

private fun severityRes(severity: NoticeSeverity): Int = when (severity) {
    NoticeSeverity.INFO -> R.string.notice_severity_info
    NoticeSeverity.WARNING -> R.string.notice_severity_warning
    NoticeSeverity.ERROR -> R.string.notice_severity_error
}

private fun actionRes(action: NoticeAction): Int = when (action) {
    NoticeAction.RETRY_PENDING -> R.string.notice_action_retry_pending
    NoticeAction.DISCARD_PENDING -> R.string.notice_action_discard_pending
    NoticeAction.PAIR -> R.string.notice_action_pair
    NoticeAction.SCAN_WIFI -> R.string.notice_action_scan_wifi
    NoticeAction.RETRY_MODEL_DOWNLOAD, NoticeAction.RETRY_VOICE_DOWNLOAD -> R.string.notice_action_retry
    NoticeAction.OPEN_APP_SETTINGS -> R.string.notice_action_open_settings
}

/** Small unread marker for the Home header: a dot plus count, nothing when everything is read. */
@Composable
fun HomeNoticeIndicator(unread: Int, ongoing: Boolean = false, onClick: () -> Unit) {
    if (unread <= 0 && !ongoing) return
    val description = pluralStringResource(R.plurals.notices_unread, unread, unread)
    Row(
        Modifier.testTag("home_notice_indicator").clickable(onClick = onClick).padding(horizontal = 8.dp, vertical = 4.dp)
            .semantics { contentDescription = description },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        val pulse = androidx.compose.animation.core.rememberInfiniteTransition(label = "Unread notice")
        val alpha by pulse.animateFloat(
            initialValue = 1f, targetValue = if (unread > 0) 0.4f else 1f,
            animationSpec = androidx.compose.animation.core.infiniteRepeatable(
                androidx.compose.animation.core.tween(1000), androidx.compose.animation.core.RepeatMode.Reverse), label = "Notice pulse")
        Box(Modifier.size(8.dp).background(WarningColor.copy(alpha = alpha), CircleShape))
        Spacer(Modifier.width(4.dp))
        Text(if (unread > 99) "99+" else if (unread > 0) unread.toString() else "", fontSize = 11.sp, color = WarningColor)
    }
}

/** The Notifications tab: every notice with its time, severity, actions, and dismiss / clear all. */
@Composable
fun NotificationsScreen(
    notices: List<Notice>,
    actionsEnabled: Boolean,
    onAction: (NoticeAction) -> Unit,
    onDismiss: (String) -> Unit,
    onClearAll: () -> Unit,
) {
    var confirmDiscard by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(stringResource(R.string.notices_tab), fontSize = 25.sp, modifier = Modifier.weight(1f).padding(vertical = 12.dp))
            if (notices.isNotEmpty()) TextButton(onClick = onClearAll) { Text(stringResource(R.string.notices_clear_all)) }
        }
        if (notices.isEmpty()) {
            Text(stringResource(R.string.notices_empty), color = Muted, modifier = Modifier.padding(top = 24.dp))
        }
        LazyColumn(state = rememberLazyListState(), verticalArrangement = Arrangement.spacedBy(8.dp), contentPadding = PaddingValues(bottom = 16.dp)) {
            items(notices, key = { it.id }) { notice ->
                NoticeCard(notice, actionsEnabled, onAction = { action ->
                    if (action == NoticeAction.DISCARD_PENDING) confirmDiscard = true else onAction(action)
                }, onDismiss = { onDismiss(notice.id) })
            }
        }
    }
    if (confirmDiscard) AlertDialog(
        onDismissRequest = { confirmDiscard = false },
        title = { Text(stringResource(R.string.notice_discard_title)) },
        text = { Text(stringResource(R.string.notice_discard_body)) },
        confirmButton = { TextButton(onClick = { confirmDiscard = false; onAction(NoticeAction.DISCARD_PENDING) }) {
            Text(stringResource(R.string.notice_action_discard_pending)) } },
        dismissButton = { TextButton(onClick = { confirmDiscard = false }) { Text(stringResource(R.string.notice_discard_keep)) } },
    )
}

@Composable
private fun NoticeCard(notice: Notice, actionsEnabled: Boolean, onAction: (NoticeAction) -> Unit, onDismiss: () -> Unit) {
    val context = LocalContext.current
    val color = severityColor(notice.severity)
    val time = DateUtils.formatDateTime(context, notice.timeMillis,
        DateUtils.FORMAT_SHOW_TIME or DateUtils.FORMAT_SHOW_DATE or DateUtils.FORMAT_ABBREV_MONTH)
    Card(Modifier.fillMaxWidth().testTag("notice_${notice.id}"), colors = CardDefaults.cardColors(containerColor = Color(0xFF111B28))) {
        Column(Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (!notice.read) Box(Modifier.size(8.dp).background(color, CircleShape).testTag("unread_${notice.id}"))
                if (!notice.read) Spacer(Modifier.width(6.dp))
                Text(stringResource(severityRes(notice.severity)).uppercase(), color = color, fontSize = 10.sp, letterSpacing = 1.sp)
                if (notice.live) Text(" · " + stringResource(R.string.notice_ongoing), color = Muted, fontSize = 10.sp)
                Spacer(Modifier.weight(1f))
                Text(time, color = Muted, fontSize = 11.sp)
            }
            Text(stringResource(noticeTitleRes(notice.kind)), fontWeight = FontWeight.SemiBold, fontSize = 14.sp, modifier = Modifier.padding(top = 4.dp))
            val body = notice.body?.takeIf { it.isNotBlank() }
                ?: if (notice.kind == NoticeKind.PENDING_MESSAGE) stringResource(R.string.notice_body_pending) else null
            if (body != null) Text(body, fontSize = 12.sp, color = Color(0xFFC9D3DE), modifier = Modifier.padding(top = 4.dp))
            Row {
                notice.actions.forEach { action ->
                    TextButton(onClick = { onAction(action) }, enabled = actionsEnabled) { Text(stringResource(actionRes(action))) }
                }
                Spacer(Modifier.weight(1f))
                TextButton(onClick = onDismiss) { Text(stringResource(R.string.notices_dismiss)) }
            }
        }
    }
}
