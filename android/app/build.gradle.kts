import java.net.URI
import java.security.MessageDigest

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
        versionCode = providers.gradleProperty("releaseCode").orElse("9").get().toInt()
        versionName = "1.5.3-beta"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
        externalNativeBuild {
            cmake {
                cppFlags += "-std=c++17"
                arguments += listOf("-DANDROID_STL=c++_shared", "-DJARVIS_BUILD_VOICE_NATIVE=ON")
            }
        }
    }
    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = "3.22.1"
        }
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
            signingConfig = when {
                System.getenv("JARVIS_APK_KEYSTORE") != null -> signingConfigs.getByName("swarm")
                else -> signingConfigs.getByName("debug")
            }
        }
    }
    buildFeatures { compose = true; buildConfig = true }
    // Robolectric Compose UI tests need merged resources + ui-test-manifest's ComponentActivity.
    // src/test/resources/robolectric.properties keeps the plain Application tests always ran with.
    testOptions { unitTests.isIncludeAndroidResources = true }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
    sourceSets["main"].assets.srcDir(layout.buildDirectory.dir("bootstrap"))
    sourceSets["main"].assets.srcDir(layout.buildDirectory.dir("wake-assets"))
    sourceSets["main"].assets.srcDir(layout.buildDirectory.dir("generated/mobile-presence"))
    packaging {
        jniLibs {
            excludes += "**/libonnxruntime4j_jni.so"
            // libkiwix ships its own libc++_shared.so next to the app's CMake c++_shared; keep one copy.
            pickFirsts += "**/libc++_shared.so"
        }
    }
}

val mobilePresence by tasks.registering(Exec::class) {
    workingDir(rootProject.file("../frontend"))
    inputs.dir(rootProject.file("../frontend/src/presence"))
    inputs.dir(rootProject.file("../frontend/src/tts"))
    inputs.dir(rootProject.file("../frontend/public/presence/jarvis-original"))
    inputs.file(rootProject.file("../frontend/mobile-presence.html"))
    inputs.file(rootProject.file("../frontend/vite.mobile-presence.config.ts"))
    outputs.dir(layout.buildDirectory.dir("generated/mobile-presence"))
    if (System.getProperty("os.name").startsWith("Windows")) commandLine("cmd", "/c", "npm", "run", "build:android-presence")
    else commandLine("npm", "run", "build:android-presence")
}
tasks.named("preBuild") { dependsOn(mobilePresence) }

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

val wakeRuntime = tasks.register("prepareWakeRuntime") {
    val aar = layout.buildDirectory.file("wake/sherpa.aar")
    val model = layout.buildDirectory.file("wake/model.tar.bz2")
    outputs.file(aar)
    outputs.dir(layout.buildDirectory.dir("wake-assets"))
    doLast {
        fun hashedDownload(url: String, destination: File, expected: String) {
            fun digest(file: File): String {
                val hash = MessageDigest.getInstance("SHA-256")
                file.inputStream().use { input ->
                    val bytes = ByteArray(65536)
                    while (true) { val count = input.read(bytes); if (count < 0) break; hash.update(bytes, 0, count) }
                }
                return hash.digest().joinToString("") { "%02x".format(it) }
            }
            destination.parentFile.mkdirs()
            if (destination.isFile && digest(destination) == expected) return
            val partial = File(destination.path + ".partial")
            val connection = URI(url).toURL().openConnection().apply { connectTimeout = 30000; readTimeout = 120000 }
            connection.getInputStream().use { input -> partial.outputStream().use { input.copyTo(it) } }
            check(digest(partial) == expected) { "Wake artifact checksum mismatch: ${destination.name}" }
            check(partial.renameTo(destination)) { "Could not save verified wake artifact" }
        }
        hashedDownload("https://github.com/k2-fsa/sherpa-onnx/releases/download/v1.13.8/sherpa-onnx-static-link-onnxruntime-1.13.8.aar",
            aar.get().asFile, "b22c3fc1b6a45666d28892bb2f7694beeb77a8362d7ebd77c1a5431ec9435471")
        hashedDownload("https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20.tar.bz2",
            model.get().asFile, "68447f4fbc67e70eee3a93961f36e81e98f47aef73ce7e7ca00885c6cd3616a6")
        val extracted = layout.buildDirectory.dir("wake/extracted").get().asFile.apply { mkdirs() }
        val prefix = "sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/"
        val files = mapOf("encoder-epoch-13-avg-2-chunk-8-left-64.int8.onnx" to "encoder.onnx",
            "decoder-epoch-13-avg-2-chunk-8-left-64.onnx" to "decoder.onnx",
            "joiner-epoch-13-avg-2-chunk-8-left-64.int8.onnx" to "joiner.onnx", "tokens.txt" to "tokens.txt")
        exec { commandLine(listOf("tar", "-xf", model.get().asFile.absolutePath, "-C", extracted.absolutePath) + files.keys.map { prefix + it }) }
        val assets = layout.buildDirectory.dir("wake-assets/wake").get().asFile.apply { mkdirs() }
        files.forEach { (source, name) -> File(extracted, prefix + source).copyTo(File(assets, name), overwrite = true) }
        File(assets, "keywords.txt").writeText("HH EY1 AE1 N Z UW1 @HEY_ANZU\nHH EY1 AE1 N UW1 @HEY_ANU\n")
        File(assets, "NOTICE.txt").writeText("Keyword spotting: k2-fsa sherpa-onnx 1.13.8 (Apache-2.0). Model: sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20. https://github.com/k2-fsa/sherpa-onnx")
    }
}
tasks.named("preBuild") { dependsOn(wakeRuntime) }

dependencies {
    implementation(files(layout.buildDirectory.file("wake/sherpa.aar")).builtBy(wakeRuntime))
    implementation("com.google.mlkit:text-recognition:16.0.1")
    implementation("androidx.biometric:biometric:1.1.0")
    implementation("androidx.fragment:fragment-ktx:1.8.5")
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
    // RFC-0216 S2 off-grid content: MapLibre offline regions (OpenFreeMap tiles) + Kiwix ZIM reader.
    implementation("org.maplibre.gl:android-sdk:12.3.1")
    implementation("org.kiwix:libkiwix:2.6.0")
    // ONNX Runtime Mobile is linked from CMake (hashed Maven AAR), not Gradle,
    // so the APK does not ship libonnxruntime4j_jni.so or a duplicate .so.
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.robolectric:robolectric:4.14.1")
    testImplementation("androidx.test:core:1.6.1")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    testImplementation(platform("androidx.compose:compose-bom:2024.12.01"))
    testImplementation("androidx.compose.ui:ui-test-junit4")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
    androidTestImplementation(platform("androidx.compose:compose-bom:2024.12.01"))
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}
