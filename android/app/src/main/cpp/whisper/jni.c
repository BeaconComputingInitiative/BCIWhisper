#include <jni.h>
#include <android/log.h>
#include <stdlib.h>
#include "whisper.h"

#define TAG "BCIWhisperJNI"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)

static struct whisper_context * ctx_from(jlong ptr) {
    return (struct whisper_context *) (intptr_t) ptr;
}

JNIEXPORT jlong JNICALL
Java_org_beaconcomputinginitiative_bciwhisper_transcription_WhisperNative_initContext(
        JNIEnv *env, jobject thiz, jstring model_path) {
    (void) thiz;
    const char *path = (*env)->GetStringUTFChars(env, model_path, NULL);
    struct whisper_context_params cparams = whisper_context_default_params();
    struct whisper_context *ctx = whisper_init_from_file_with_params(path, cparams);
    (*env)->ReleaseStringUTFChars(env, model_path, path);
    return (jlong) (intptr_t) ctx;
}

JNIEXPORT void JNICALL
Java_org_beaconcomputinginitiative_bciwhisper_transcription_WhisperNative_freeContext(
        JNIEnv *env, jobject thiz, jlong ptr) {
    (void) env; (void) thiz;
    struct whisper_context *ctx = ctx_from(ptr);
    if (ctx) whisper_free(ctx);
}

JNIEXPORT jint JNICALL
Java_org_beaconcomputinginitiative_bciwhisper_transcription_WhisperNative_transcribe(
        JNIEnv *env, jobject thiz, jlong ptr, jfloatArray audio, jint threads) {
    (void) thiz;
    struct whisper_context *ctx = ctx_from(ptr);
    if (!ctx) return -1;

    jfloat *samples = (*env)->GetFloatArrayElements(env, audio, NULL);
    jsize n = (*env)->GetArrayLength(env, audio);

    struct whisper_full_params p = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    p.print_realtime = false;
    p.print_progress = false;
    p.print_timestamps = false;
    p.print_special = false;
    p.translate = false;
    p.language = "en";
    p.n_threads = threads;
    p.no_context = true;
    p.single_segment = false;

    int rc = whisper_full(ctx, p, samples, n);
    (*env)->ReleaseFloatArrayElements(env, audio, samples, JNI_ABORT);
    return rc;
}

JNIEXPORT jint JNICALL
Java_org_beaconcomputinginitiative_bciwhisper_transcription_WhisperNative_segmentCount(
        JNIEnv *env, jobject thiz, jlong ptr) {
    (void) env; (void) thiz;
    struct whisper_context *ctx = ctx_from(ptr);
    return ctx ? whisper_full_n_segments(ctx) : 0;
}

JNIEXPORT jstring JNICALL
Java_org_beaconcomputinginitiative_bciwhisper_transcription_WhisperNative_segmentText(
        JNIEnv *env, jobject thiz, jlong ptr, jint index) {
    (void) thiz;
    struct whisper_context *ctx = ctx_from(ptr);
    const char *text = ctx ? whisper_full_get_segment_text(ctx, index) : "";
    return (*env)->NewStringUTF(env, text);
}
