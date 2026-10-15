package com.jarvis.companion

import android.accessibilityservice.AccessibilityService
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.graphics.Bitmap
import android.os.Build
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID
import kotlin.coroutines.resume

class AnzuAccessibilityService : AccessibilityService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var screenId = ""
    private var observedAt = 0L
    private val nodes = linkedMapOf<Int, AccessibilityNodeInfo>()
    override fun onServiceConnected() {
        current = this
        scope.launch {
            val api = (application as JarvisApp).api
            val receipts = getSharedPreferences("phone_tool_receipts", MODE_PRIVATE)
            while (isActive) {
                if (api.deviceId.isNotBlank() && PhoneToolPermissions(this@AnzuAccessibilityService).enabled()) {
                    runCatching {
                        val commands = api.json("/phone-tools").optJSONArray("commands")?.objects().orEmpty()
                        val epoch = PhoneTools.epoch()
                        for (item in commands.take(10)) {
                            val id = item.getString("id")
                            val key = "${api.deviceId}:$id"
                            val cached = receipts.getString(key, null)
                            val result = if (cached != null) JSONObject(cached) else {
                                // Mark before execution: process death must never repeat a send/purchase.
                                val interrupted = JSONObject().put("ok", false).put("error", "Action was interrupted; inspect the app before retrying.")
                                check(receipts.edit().putString(key, interrupted.toString()).commit()) { "Could not record phone action" }
                                val completed = PhoneTools.execute(this@AnzuAccessibilityService, item.getJSONObject("command"), epoch)
                                check(receipts.edit().putString(key, completed.toString()).commit()) { "Could not record phone action result" }
                                completed
                            }
                            api.json("/phone-tools/$id/result", "POST", JSONObject().put("result", result))
                            receipts.edit().remove(key).apply()
                        }
                    }
                }
                delay(1500)
            }
        }
    }
    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event?.eventType in setOf(AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED, AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED)) {
            screenId = ""
            nodes.clear()
        }
    }
    override fun onInterrupt() { PhoneTools.stop() }
    override fun onDestroy() { scope.cancel(); ocr.close(); current = null; PhoneTools.stop(); super.onDestroy() }
    private val ocr = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)

    suspend fun snapshot(pkg: String): JSONObject {
        val root = rootInActiveWindow ?: error("No readable screen")
        check(root.packageName?.toString() == pkg) { "Open the target app before reading its screen" }
        nodes.clear()
        val output = JSONArray()
        var containsPassword = false
        fun visit(node: AccessibilityNodeInfo, depth: Int) {
            if (nodes.size >= 120 || depth > 20) return
            if (node.isPassword) containsPassword = true
            if (node.isVisibleToUser && !node.isPassword) {
                val id = nodes.size
                nodes[id] = node
                output.put(JSONObject().put("node_id", id).put("text", node.text?.toString()?.take(400).orEmpty())
                    .put("description", node.contentDescription?.toString()?.take(400).orEmpty())
                    .put("clickable", node.isClickable).put("editable", node.isEditable).put("scrollable", node.isScrollable))
            }
            for (i in 0 until node.childCount) node.getChild(i)?.let { visit(it, depth + 1) }
        }
        visit(root, 0)
        screenId = UUID.randomUUID().toString()
        observedAt = android.os.SystemClock.elapsedRealtime()
        val id = screenId
        // OCR is local and only requested by an owner-authorized read.
        val text = if (!containsPassword && Build.VERSION.SDK_INT >= 30 && output.objects().all { it.optString("text").isBlank() })
            screenshotText() else ""
        check(rootInActiveWindow?.packageName?.toString() == pkg && screenId == id) { "Screen changed while reading; retry" }
        return JSONObject().put("screen_id", id).put("package", pkg).put("nodes", output)
            .put("ocr_text", text.take(8000)).put("untrusted_screen_data", true)
    }

    fun target(command: JSONObject): AccessibilityNodeInfo? {
        if (screenId.isBlank() || command.optString("screen_id") != screenId ||
            android.os.SystemClock.elapsedRealtime() - observedAt > 15_000 ||
            rootInActiveWindow?.packageName?.toString() != command.optString("package")) return null
        return nodes[command.optInt("node_id", -1)]?.takeIf { it.refresh() && it.isVisibleToUser && !it.isPassword }
    }

    @androidx.annotation.RequiresApi(30)
    private suspend fun screenshotText(): String = suspendCancellableCoroutine { continuation ->
        takeScreenshot(android.view.Display.DEFAULT_DISPLAY, mainExecutor, object : TakeScreenshotCallback {
            override fun onFailure(errorCode: Int) { if (continuation.isActive) continuation.resume("") }
            override fun onSuccess(result: ScreenshotResult) {
                val buffer = result.hardwareBuffer
                val hardware = Bitmap.wrapHardwareBuffer(buffer, result.colorSpace)
                val bitmap = hardware?.copy(Bitmap.Config.ARGB_8888, false)
                hardware?.recycle(); buffer.close()
                if (bitmap == null) { if (continuation.isActive) continuation.resume(""); return }
                ocr.process(InputImage.fromBitmap(bitmap, 0)).addOnCompleteListener { task ->
                    bitmap.recycle()
                    if (continuation.isActive) continuation.resume(if (task.isSuccessful) task.result.text else "")
                }
            }
        })
    }
    companion object { @Volatile var current: AnzuAccessibilityService? = null }
}
