package com.jarvis.companion

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay

private val SplashInk = Color(0xFF070B12)
private val SplashGold = Color(0xFFF5A623)

/** Brief branded first frame: ink, orb, ANZU. No model load, no fake progress. */
@Composable
fun AnzuSplash(
    onFinished: () -> Unit,
    holdMillis: Long = 700L,
) {
    LaunchedEffect(Unit) {
        delay(holdMillis.coerceIn(0L, 999L))
        onFinished()
    }
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(SplashInk),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(20.dp),
        ) {
            Image(
                painter = painterResource(R.drawable.ic_jarvis),
                contentDescription = AnzuBranding.DISPLAY_NAME,
                modifier = Modifier.size(96.dp),
            )
            Text(
                text = AnzuBranding.DISPLAY_NAME,
                color = SplashGold,
                fontSize = 28.sp,
                fontWeight = FontWeight.SemiBold,
                letterSpacing = 6.sp,
            )
        }
    }
}
