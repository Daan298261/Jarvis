plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "com.jarvis.companion"
    compileSdk = 35
    defaultConfig {
        applicationId = "com.jarvis.companion"
        minSdk = 29
        targetSdk = 35
        versionCode = providers.gradleProperty("releaseCode").orElse("1").get().toInt()
        versionName = "1.3.1"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    signingConfigs {
        create("swarm") {
            System.getenv("JARVIS_APK_KEYSTORE")?.let {
                storeFile = file(it)
                storePassword = System.getenv("JARVIS_APK_PASSWORD")
                keyAlias = "jarvis"
                keyPassword = System.getenv("JARVIS_APK_PASSWORD")
            }
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            if (System.getenv("JARVIS_APK_KEYSTORE") != null) signingConfig = signingConfigs.getByName("swarm")
        }
    }
    buildFeatures { compose = true; buildConfig = true }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
    sourceSets["main"].assets.srcDir(layout.buildDirectory.dir("bootstrap"))
}

val bootstrap by tasks.registering {
    val source = providers.gradleProperty("bootstrapFile").orElse(rootProject.file("bootstrap.json").absolutePath)
    inputs.property("bootstrapPath", source)
    outputs.upToDateWhen { false }
    doLast {
        val destination = layout.buildDirectory.file("bootstrap/bootstrap.json").get().asFile
        destination.parentFile.mkdirs()
        val supplied = file(source.get())
        destination.writeText(if (supplied.exists()) supplied.readText() else "{}")
    }
}
tasks.named("preBuild") { dependsOn(bootstrap) }

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.ui:ui-tooling-preview")
    debugImplementation("androidx.compose.ui:ui-tooling")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.webkit:webkit:1.12.1")
    implementation("androidx.core:core-telecom:1.0.0")
    implementation("androidx.camera:camera-camera2:1.4.1")
    implementation("androidx.camera:camera-core:1.4.1")
    implementation("androidx.camera:camera-lifecycle:1.4.1")
    implementation("androidx.camera:camera-view:1.4.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.google.mlkit:barcode-scanning:17.3.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    implementation("com.google.firebase:firebase-messaging:24.1.0")
    implementation("io.github.webrtc-sdk:android:125.6422.07")
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
    androidTestImplementation(platform("androidx.compose:compose-bom:2024.12.01"))
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}
