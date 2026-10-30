package com.jarvis.companion

import android.annotation.SuppressLint
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.runtime.*
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.unit.dp
import org.json.JSONObject

/** Ships the same geometry, motion and adaptive quality as the desktop showcase, entirely offline. */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun ShowcasePresence(phase: PresencePhase, audioLevel: Float, reducedMotion: Boolean, fallback: @Composable () -> Unit) {
    var failed by remember { mutableStateOf(false) }
    if (failed) { fallback(); return }
    val state = JSONObject().put("phase", if (phase == PresencePhase.WORKING) "executing" else phase.name.lowercase())
        .put("audioLevel", audioLevel).put("reducedMotion", reducedMotion).toString()
    val latest by rememberUpdatedState(state)
    AndroidView(
        modifier = Modifier.fillMaxWidth().height(340.dp),
        factory = { context -> WebView(context).apply {
            setBackgroundColor(android.graphics.Color.rgb(2, 5, 10))
            settings.javaScriptEnabled = true
            settings.allowFileAccess = false
            settings.allowContentAccess = false
            settings.blockNetworkLoads = true
            settings.mediaPlaybackRequiresUserGesture = true
            webChromeClient = object : WebChromeClient() {
                override fun onReceivedTitle(view: WebView?, title: String?) { if (title == "anzu-presence-fallback") failed = true }
            }
            webViewClient = object : WebViewClient() {
                override fun shouldInterceptRequest(view: WebView, request: android.webkit.WebResourceRequest): android.webkit.WebResourceResponse? {
                    val uri = request.url
                    if (uri.scheme != "https" || uri.host != "appassets.androidplatform.net") return android.webkit.WebResourceResponse("text/plain", "UTF-8", java.io.ByteArrayInputStream(ByteArray(0)))
                    val rawPath = uri.path ?: return null
                    val path = if (rawPath.startsWith("/presence/")) "presence$rawPath" else rawPath.removePrefix("/assets/")
                    if (!path.startsWith("presence/") || path.split('/').any { it == ".." }) return null
                    val mime = when (path.substringAfterLast('.')) { "js" -> "text/javascript"; "css" -> "text/css"; "html" -> "text/html"; "webp" -> "image/webp"; "png" -> "image/png"; else -> "application/octet-stream" }
                    return runCatching { android.webkit.WebResourceResponse(mime, "UTF-8", context.assets.open(path)) }.getOrNull()
                }
                override fun shouldOverrideUrlLoading(view: WebView?, request: android.webkit.WebResourceRequest?) = true
                override fun onPageFinished(view: WebView, url: String?) { view.evaluateJavascript("window.updateAnzuPresence?.($latest)", null) }
                override fun onReceivedError(view: WebView, request: android.webkit.WebResourceRequest, error: android.webkit.WebResourceError) { if (request.isForMainFrame) failed = true }
            }
            loadUrl("https://appassets.androidplatform.net/assets/presence/mobile-presence.html")
        } },
        update = { it.evaluateJavascript("window.updateAnzuPresence?.($state)", null) },
        onRelease = { it.stopLoading(); it.destroy() },
    )
}
