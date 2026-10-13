#include <jni.h>
#include <string.h>
#include <android/log.h>
static void fill(char *out, const char *in) { char buf[64]; strncpy(buf, in, sizeof buf - 1); buf[63] = 0; strcpy(out, buf); }
JNIEXPORT jstring JNICALL Java_org_anzu_test_MainActivity_stringFromJNI(JNIEnv *env, jobject self) {
    char out[64]; fill(out, "anzu"); __android_log_print(ANDROID_LOG_DEBUG, "anzu", "%s", out);
    return (*env)->NewStringUTF(env, out);
}
JNIEXPORT jint JNI_OnLoad(JavaVM *vm, void *reserved) { return JNI_VERSION_1_6; }
