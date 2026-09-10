package com.jarvis.companion

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * RFC-0063 — 6-digit numeric keypad entry and enroll trigger.
 *
 * Wire from the app shell (#132) with [baseUrl], device [publicKey], and [deviceName].
 */
@Composable
fun PairingScreen(
    baseUrl: String,
    publicKey: String,
    deviceName: String,
    enrollClient: CompanionEnrollClient = remember(baseUrl) { CompanionEnrollClient(baseUrl) },
    onEnrolled: (Map<String, String>) -> Unit = {},
) {
    var digits by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    fun appendDigit(value: String) {
        if (busy) return
        error = null
        digits = CompanionCodeValidator.normalize(digits + value)
        if (CompanionCodeValidator.isComplete(digits)) {
            scope.launch {
                busy = true
                val result = withContext(Dispatchers.IO) {
                    enrollClient.enroll(digits, publicKey, deviceName)
                }
                busy = false
                when (result) {
                    is CompanionEnrollResult.Success -> onEnrolled(result.payload)
                    is CompanionEnrollResult.InvalidCode -> {
                        error = result.message
                        digits = ""
                    }
                    is CompanionEnrollResult.Expired -> {
                        error = result.message
                        digits = ""
                    }
                    is CompanionEnrollResult.RateLimited -> error = result.message
                    is CompanionEnrollResult.Unauthorized -> error = result.message
                    is CompanionEnrollResult.ApiUnavailable -> error = result.message
                    is CompanionEnrollResult.NetworkError -> error = result.message
                    is CompanionEnrollResult.ServerError -> error = result.message
                }
            }
        }
    }

    fun backspace() {
        if (busy) return
        error = null
        digits = digits.dropLast(1)
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(20.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text(
            text = "Enter pairing code",
            style = MaterialTheme.typography.headlineSmall,
        )
        Text(
            text = "Open Jarvis on your PC → Settings → Pair phone, then type the 6-digit code.",
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        CodeDisplay(digits = digits, busy = busy)

        if (error != null) {
            Text(
                text = error!!,
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodyMedium,
                textAlign = TextAlign.Center,
            )
        }

        NumericKeypad(
            enabled = !busy,
            onDigit = ::appendDigit,
            onBackspace = ::backspace,
        )

        if (busy) {
            CircularProgressIndicator(modifier = Modifier.size(28.dp))
        }
    }
}

@Composable
private fun CodeDisplay(digits: String, busy: Boolean) {
    val padded = digits.padEnd(6, '·')
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        padded.forEach { ch ->
            Box(
                modifier = Modifier
                    .size(width = 44.dp, height = 56.dp)
                    .clip(RoundedCornerShape(10.dp))
                    .background(MaterialTheme.colorScheme.surfaceVariant)
                    .border(1.dp, MaterialTheme.colorScheme.outline, RoundedCornerShape(10.dp)),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = ch.toString(),
                    fontFamily = FontFamily.Monospace,
                    fontSize = 28.sp,
                    color = if (busy) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.primary,
                )
            }
        }
    }
}

@Composable
private fun NumericKeypad(
    enabled: Boolean,
    onDigit: (String) -> Unit,
    onBackspace: () -> Unit,
) {
    val keys = listOf(
        listOf("1", "2", "3"),
        listOf("4", "5", "6"),
        listOf("7", "8", "9"),
        listOf("", "0", "⌫"),
    )
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        keys.forEach { row ->
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceEvenly,
            ) {
                row.forEach { key ->
                    if (key.isEmpty()) {
                        Spacer(modifier = Modifier.size(72.dp))
                    } else {
                        KeyButton(
                            label = key,
                            enabled = enabled,
                            onClick = {
                                if (key == "⌫") onBackspace() else onDigit(key)
                            },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun KeyButton(label: String, enabled: Boolean, onClick: () -> Unit) {
    Box(
        modifier = Modifier
            .size(72.dp)
            .clip(RoundedCornerShape(36.dp))
            .background(
                if (enabled) MaterialTheme.colorScheme.primaryContainer
                else MaterialTheme.colorScheme.surfaceVariant,
            )
            .clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = label,
            fontSize = 24.sp,
            color = MaterialTheme.colorScheme.onPrimaryContainer,
        )
    }
}
