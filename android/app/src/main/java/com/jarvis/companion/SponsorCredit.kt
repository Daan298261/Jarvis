package com.jarvis.companion

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp


object SponsorCredit {
    /** Default-browser intent for the Black Grid Publishing site (no WebView). */
    fun browserIntent(url: String = AnzuBranding.SPONSOR_URL): Intent =
        Intent(Intent.ACTION_VIEW, Uri.parse(url))

    /** Opens [url] (default: the sponsor site) in the default browser; also used for voice-pack licence links. */
    fun openInBrowser(context: Context, url: String = AnzuBranding.SPONSOR_URL): Boolean {
        // Do not pre-check with resolveActivity: on API 30+ (package visibility) it
        // returns null for browsers unless <queries> is declared. Manifest edits for
        // this slice stay at label/theme only, so startActivity and catch instead.
        val intent = browserIntent(url)
        if (context !is Activity) {
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        return try {
            context.startActivity(intent)
            true
        } catch (_: ActivityNotFoundException) {
            false
        }
    }
}

/** About row: BGP mark + exact sponsor sentence; tap opens the sponsor URL. */
@Composable
fun SponsorCreditRow(modifier: Modifier = Modifier) {
    val context = LocalContext.current
    var error by remember { mutableStateOf<String?>(null) }
    val openFailed = stringResource(R.string.sponsor_open_failed)
    Column(modifier = modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable {
                    error = if (SponsorCredit.openInBrowser(context)) null else openFailed
                }
                .padding(vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Image(
                painter = painterResource(R.drawable.bgp_logo),
                contentDescription = "Black Grid Publishing",
                modifier = Modifier.size(32.dp),
            )
            Text(
                text = AnzuBranding.SPONSOR_CREDIT,
                color = Muted,
                fontSize = 12.sp,
                modifier = Modifier.weight(1f),
            )
        }
        error?.let {
            Text(it, color = ErrorText, fontSize = 12.sp, modifier = Modifier.padding(top = 4.dp))
        }
    }
}
