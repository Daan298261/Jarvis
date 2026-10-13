#!/bin/sh
# Rebuilds ../dex_endpoints.apk. Needs a JDK 17+, Android build-tools 34.0.0 (d8, aapt2) and
# platforms/android-34/android.jar:  BT=<build-tools dir> ANDROID_JAR=<android.jar> ./build.sh
set -eu
cd "$(dirname "$0")"
rm -rf build && mkdir -p build/classes build/dex
javac --release 11 -cp "$ANDROID_JAR" -d build/classes java/org/anzu/fixture/Main.java
"$BT/d8" --release --min-api 26 --lib "$ANDROID_JAR" --output build/dex build/classes/org/anzu/fixture/*.class
"$BT/aapt2" compile --dir res -o build/res.zip
"$BT/aapt2" link -I "$ANDROID_JAR" --manifest AndroidManifest.xml -o ../dex_endpoints.apk build/res.zip
python3 -c "import zipfile; z = zipfile.ZipFile('../dex_endpoints.apk', 'a', zipfile.ZIP_DEFLATED); z.write('build/dex/classes.dex', 'classes.dex'); z.close()"
rm -rf build
