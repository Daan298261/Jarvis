package com.jarvis.companion

import android.Manifest
import android.app.role.RoleManager
import android.content.Intent
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun AssistantSettings(model: CompanionModel) {
    val context = LocalContext.current
    val wakeSettings = remember { WakeSettings(context) }
    val scope = rememberCoroutineScope()
    var wakePhrases by remember { mutableStateOf(wakeSettings.phrases) }
    var wakeThreshold by remember { mutableFloatStateOf(wakeSettings.threshold) }
    var screenContext by remember { mutableStateOf(wakeSettings.screenContext) }
    var wakeNotice by remember { mutableStateOf("") }
    var savingWake by remember { mutableStateOf(false) }
    val permissions = remember { PhoneToolPermissions(context) }
    var enabled by remember { mutableStateOf(permissions.enabled()) }
    val local by model.preferPhoneLocal.collectAsStateWithLifecycle()
    val wake by WakeAudioState.status.collectAsStateWithLifecycle()
    val activity by PhoneTools.activity.collectAsStateWithLifecycle()
    val import = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let(model::importPhoneModel) }
    val role = remember { context.getSystemService(RoleManager::class.java) }
    var assistantHeld by remember { mutableStateOf(role.isRoleHeld(RoleManager.ROLE_ASSISTANT)) }
    val assistant = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        assistantHeld = role.isRoleHeld(RoleManager.ROLE_ASSISTANT)
    }
    val microphone = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted && role.isRoleHeld(RoleManager.ROLE_ASSISTANT)) {
            wakeSettings.enabled = true
            runCatching { context.startForegroundService(Intent(context, AnzuWakeService::class.java).setAction("enable")) }
                .onFailure { wakeSettings.enabled = false; WakeAudioState.status.value = "Could not start wake listening: ${it.message}" }
        } else wakeNotice = if (!granted) "Microphone permission is required." else "Make ANZU your default assistant before enabling wake listening."
    }
    var packageName by remember { mutableStateOf("") }
    var categories by remember { mutableStateOf(emptySet<String>()) }
    var notice by remember { mutableStateOf("") }
    var appMenu by remember { mutableStateOf(false) }
    val installedApps = remember {
        @Suppress("DEPRECATION")
        context.packageManager.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0)
            .map { it.activityInfo.packageName to it.loadLabel(context.packageManager).toString() }.distinctBy { it.first }.sortedBy { it.second }
    }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Assistant", style = MaterialTheme.typography.titleLarge)
        Row { Text("Use phone-local model", Modifier.weight(1f)); Switch(local, model::preferLocal) }
        Text("PC ANZU is used by default when connected. Local mode uses this phone's CPU/RAM.")
        OutlinedButton(onClick = { import.launch(arrayOf("*/*")) }) { Text("Import a compatible GGUF") }
        Button(onClick = {
            val role = context.getSystemService(RoleManager::class.java)
            if (role.isRoleAvailable(RoleManager.ROLE_ASSISTANT)) assistant.launch(role.createRequestRoleIntent(RoleManager.ROLE_ASSISTANT))
            else assistant.launch(Intent(Settings.ACTION_VOICE_INPUT_SETTINGS))
        }) { Text("Make ANZU the default assistant") }
        Text(if (assistantHeld) "ANZU is your default digital assistant" else "ANZU is not your default digital assistant")
        OutlinedButton(onClick = { assistant.launch(Intent(Settings.ACTION_VOICE_INPUT_SETTINGS)) }) { Text("Android digital assistant settings") }
        OutlinedButton(onClick = { context.startActivity(Intent(ANZU_VOICE_ASSIST_ACTION).setPackage(context.packageName)) }) { Text("Test assistant button") }
        Text("Galaxy S23: Settings → Apps → Choose default apps → Digital assistant app → ANZU. On current One UI, set Advanced features → Side button → Long press → Digital assistant, then hold the Side button. Older One UI may offer a swipe inward from a bottom corner in Display → Navigation bar → Assistant app. Holding Side + Volume down opens the power menu.")
        Text("Choosing a default assistant does not enable wake listening. Enable it below; the notification confirms when the microphone is listening.")
        OutlinedTextField(value = wakePhrases, onValueChange = { wakePhrases = it.take(500) }, label = { Text("Wake phrases, separated by commas") }, modifier = Modifier.fillMaxWidth())
        Text("Includes ANZU, Anoe, Enzo, Anzoo, Aanzo and Jarvis. You can also use English dictionary words. Short names may trigger more often; use 'hey' for fewer accidental activations.")
        Text("Detection threshold: ${"%.2f".format(wakeThreshold)}. Lower makes activation easier; higher reduces accidental triggers.")
        Slider(value = wakeThreshold, onValueChange = { wakeThreshold = it }, valueRange = 0.05f..0.6f)
        OutlinedButton(enabled = !savingWake, onClick = {
            savingWake = true
            scope.launch {
                val result = withContext(Dispatchers.IO) { runCatching { wakeSettings.keywords(context, wakePhrases) } }
                result.onSuccess {
                    wakeSettings.phrases = wakePhrases
                    wakeSettings.threshold = wakeThreshold
                    wakeSettings.enabled = false
                    context.stopService(Intent(context, AnzuWakeService::class.java))
                    wakeNotice = "Wake settings saved. Enable listening to use them."
                }.onFailure { wakeNotice = it.message ?: "Could not validate wake phrases." }
                savingWake = false
            }
        }) { Text("Save wake settings") }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { microphone.launch(Manifest.permission.RECORD_AUDIO) }) { Text("Enable wake listening") }
            OutlinedButton(onClick = { wakeSettings.enabled = false; context.stopService(Intent(context, AnzuWakeService::class.java)) }) { Text("Stop listening") }
        }
        Text(wake)
        Text(wakeNotice)
        Text("Wake audio stays local. Listening pauses while locked, during calls, music or ANZU speech. Saved opt-in resumes when you reopen ANZU. If Samsung suspends it, review Settings → Battery → Background usage limits. No boot microphone restart.")
        Row { Text("Include visible screen text when assistant is invoked", Modifier.weight(1f)); Switch(screenContext, { screenContext = it; wakeSettings.screenContext = it }) }
        Row { Text("Allow requested app control", Modifier.weight(1f)); Switch(enabled, { enabled = it; permissions.enable(it) }) }
        Text("ANZU can read your screen and act in selected apps. Screen content is untrusted. Android permission/security screens and password fields stay manual.")
        OutlinedButton(onClick = { context.startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) }) { Text("Enable ANZU in Accessibility") }
        Box {
            OutlinedButton(onClick = { appMenu = true }) { Text(installedApps.firstOrNull { it.first == packageName }?.second ?: "Choose an app") }
            DropdownMenu(appMenu, { appMenu = false }) {
                installedApps.forEach { (pkg, label) -> DropdownMenuItem(text = { Text(label) }, onClick = {
                    packageName = pkg; categories = permissions.categories(pkg); appMenu = false
                }) }
            }
        }
        PhoneToolPermissions.CATEGORIES.forEach { category ->
            Row { Text("Approve $category in this app", Modifier.weight(1f)); Checkbox(category in categories, { checked ->
                categories = if (checked) categories + category else categories - category
            }) }
        }
        Text("These permissions apply to future requested tasks until revoked. Send, purchase, delete, and security are separate advance approvals.")
        OutlinedButton(onClick = {
            if (packageName.matches(Regex("[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z0-9_]+)+"))) {
                permissions.save(packageName, categories); notice = "App permissions saved"
            } else notice = "Choose an app first"
        }) { Text("Save / revoke app permissions") }
        Text(notice)
        Text(activity)
        Button(onClick = model::stopPhoneTask) { Text("Stop phone task now") }
        OutlinedButton(onClick = model::verifyRemoteConnection, enabled = model.api.deviceId.isNotEmpty()) { Text("Verify remote connection (Wi-Fi off)") }
        OutlinedButton(onClick = {
            val intent = context.packageManager.getLaunchIntentForPackage("com.tailscale.ipn")
                ?: Intent(Intent.ACTION_VIEW, android.net.Uri.parse("https://tailscale.com/download/android"))
            context.startActivity(intent)
        }) { Text("Open / install Tailscale") }
    }
}

@Composable
fun PhoneActionApprovalDialog() {
    val approval by PhoneTools.pending.collectAsStateWithLifecycle()
    approval?.let { request ->
        AlertDialog(onDismissRequest = { PhoneTools.answer(request.id, false) },
            title = { Text("Allow this phone action?") },
            text = { Text("${request.command.optString("action")} in ${request.command.optString("package")}\nCategories: ${request.categories.joinToString()}\n${request.command.optString("text").take(300)}") },
            confirmButton = { Button(onClick = { PhoneTools.answer(request.id, true) }) { Text("Allow once") } },
            dismissButton = { TextButton(onClick = { PhoneTools.answer(request.id, false) }) { Text("Decline") } })
    }
}
