package com.jarvis.companion

import android.app.KeyguardManager
import android.content.Context
import android.content.Intent
import android.os.Build
import android.provider.Settings
import android.view.WindowManager
import androidx.activity.result.contract.ActivityResultContracts
import androidx.biometric.BiometricManager.Authenticators.BIOMETRIC_STRONG
import androidx.biometric.BiometricManager.Authenticators.DEVICE_CREDENTIAL
import androidx.biometric.BiometricPrompt
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity

/** Android owns credentials and throttling; ANZU never stores a PIN or biometric. */
class AppAccessLock(private val activity: FragmentActivity) {
    private val prefs = activity.getSharedPreferences("app_access", Context.MODE_PRIVATE)
    private val keyguard = activity.getSystemService(KeyguardManager::class.java)
    var enabled by mutableStateOf(prefs.getBoolean("required", false))
        private set
    var unlocked by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    private var pending: (() -> Unit)? = null
    private var credentialActivityOpen = false
    val locked: Boolean get() = enabled && !unlocked

    private val credential = activity.registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        credentialActivityOpen = false
        if (result.resultCode == android.app.Activity.RESULT_OK) complete()
        else { pending = null; error = "Authentication cancelled. App protection was not changed." }
    }
    private val prompt = BiometricPrompt(activity, ContextCompat.getMainExecutor(activity),
        object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) = complete()
            override fun onAuthenticationError(code: Int, message: CharSequence) {
                pending = null
                credentialActivityOpen = false
                error = message.toString()
            }
            override fun onAuthenticationFailed() { error = "Not recognized. Try again or use your phone PIN." }
        })

    init { secureWindow() }

    private fun complete() {
        val action = pending ?: return
        pending = null
        credentialActivityOpen = false
        error = null
        action()
    }

    private fun secureWindow() {
        if (enabled) activity.window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        else activity.window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
    }

    fun background() {
        unlocked = false
        if (!credentialActivityOpen) {
            // A prompt dismissed after backgrounding cannot unlock the app later.
            pending = null
            prompt.cancelAuthentication()
        }
    }

    fun unlock() = authenticate { unlocked = true }

    fun changeProtection(required: Boolean) = authenticate {
        if (prefs.edit().putBoolean("required", required).commit()) {
            enabled = required
            unlocked = true
            secureWindow()
        } else error = "Could not save app protection. Please try again."
    }

    fun lockNow() { unlocked = false }

    private fun authenticate(action: () -> Unit) {
        if (pending != null) return
        if (!keyguard.isDeviceSecure) {
            error = "Set a screen-lock PIN or password in Android Settings first, then return and enable App lock."
            activity.startActivity(Intent(Settings.ACTION_SECURITY_SETTINGS))
            return
        }
        pending = action
        error = null
        if (Build.VERSION.SDK_INT >= 30) {
            // Device-credential fallback can temporarily put this activity in onStop.
            credentialActivityOpen = true
            prompt.authenticate(BiometricPrompt.PromptInfo.Builder()
                .setTitle("Unlock ANZU")
                .setSubtitle("Use your phone PIN, password, or strong biometric")
                .setAllowedAuthenticators(BIOMETRIC_STRONG or DEVICE_CREDENTIAL)
                .build())
        } else {
            // Biometric + device credential is unsupported by AndroidX on API 26–29.
            @Suppress("DEPRECATION")
            val intent = keyguard.createConfirmDeviceCredentialIntent("Unlock ANZU", "Confirm your phone screen lock")
            if (intent == null) { pending = null; error = "Set a phone screen lock first." }
            else { credentialActivityOpen = true; credential.launch(intent) }
        }
    }
}

@Composable
fun AppLockedScreen(lock: AppAccessLock) {
    Column(Modifier.fillMaxSize().padding(28.dp), verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally) {
        Text("ANZU is locked", style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(16.dp))
        Text("Unlock with your phone PIN, password, or biometric.")
        lock.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        Spacer(Modifier.height(16.dp))
        Button(onClick = lock::unlock) { Text("Unlock ANZU") }
    }
}

@Composable
fun AppAccessSettings(lock: AppAccessLock) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("App access", style = MaterialTheme.typography.titleLarge)
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Require phone PIN or biometric", Modifier.weight(1f))
            Switch(checked = lock.enabled, onCheckedChange = lock::changeProtection)
        }
        Text("Protects all app screens, including security features. Locks when you leave ANZU. Uses your Android screen lock.")
        lock.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        if (lock.enabled) TextButton(onClick = lock::lockNow) { Text("Lock now") }
    }
}
