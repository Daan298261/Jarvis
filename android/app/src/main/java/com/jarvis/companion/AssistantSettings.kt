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

@Composable
fun AssistantSettings(model: CompanionModel) {
    val context = LocalContext.current
    val permissions = remember { PhoneToolPermissions(context) }
    var enabled by remember { mutableStateOf(permissions.enabled()) }
    val local by model.preferPhoneLocal.collectAsStateWithLifecycle()
    val wake by WakeAudioState.status.collectAsStateWithLifecycle()
    val activity by PhoneTools.activity.collectAsStateWithLifecycle()
    val import = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let(model::importPhoneModel) }
    val assistant = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { }
    val microphone = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) runCatching { context.startForegroundService(Intent(context, AnzuWakeService::class.java).setAction("enable")) }
            .onFailure { WakeAudioState.status.value = "Could not start wake listening: ${it.message}" }
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
        Text("Use your system assistant gesture/button. Samsung side-key behavior depends on your One UI settings.")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { microphone.launch(Manifest.permission.RECORD_AUDIO) }) { Text("Enable Hey ANZU / Hey Anu") }
            OutlinedButton(onClick = { context.stopService(Intent(context, AnzuWakeService::class.java)) }) { Text("Stop listening") }
        }
        Text(wake)
        Text("Wake audio stays local. Enable while ANZU is open. If Samsung suspends it, review Settings → Battery → Background usage limits. No boot microphone restart.")
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
