package org.beaconcomputinginitiative.bciwhisper.transcription

object WhisperNative {
    init {
        System.loadLibrary("bciwhisper_whisper")
    }

    external fun initContext(modelPath: String): Long
    external fun freeContext(contextPtr: Long)
    external fun transcribe(contextPtr: Long, audio: FloatArray, threads: Int): Int
    external fun segmentCount(contextPtr: Long): Int
    external fun segmentText(contextPtr: Long, index: Int): String
}
