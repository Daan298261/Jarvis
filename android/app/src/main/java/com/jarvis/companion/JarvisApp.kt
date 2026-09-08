package com.jarvis.companion

import android.app.Application
import com.google.firebase.FirebaseApp
import com.google.firebase.FirebaseOptions

class JarvisApp : Application() {
    lateinit var api: JarvisApi
    override fun onCreate() {
        super.onCreate()
        api = JarvisApi(this)
        api.firebase?.let { config ->
            runCatching {
                FirebaseApp.initializeApp(this, FirebaseOptions.Builder()
                    .setApplicationId(config.getString("app_id"))
                    .setApiKey(config.getString("api_key"))
                    .setProjectId(config.getString("project_id"))
                    .setGcmSenderId(config.getString("sender_id")).build())
            }
        }
    }
}
