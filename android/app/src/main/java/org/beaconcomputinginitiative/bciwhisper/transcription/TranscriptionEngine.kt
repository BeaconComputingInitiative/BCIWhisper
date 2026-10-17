package org.beaconcomputinginitiative.bciwhisper.transcription

import android.content.Context
import java.io.File
import java.io.RandomAccessFile
import kotlin.math.floor

class TranscriptionEngine(private val context: Context) {
    data class Result(
        val source: File,
        val transcript: File,
        val text: String
    )

    fun transcribe(wavFile: File): Result {
        require(wavFile.isFile) { "Recording not found: ${wavFile.name}" }

        val model = ensureModel()
        val pcm = readMonoPcm16Wav(wavFile)
        val audio16k = resampleTo16k(pcm.samples, pcm.sampleRate)

        val ptr = WhisperNative.initContext(model.absolutePath)
        require(ptr != 0L) { "whisper.cpp could not load the model" }

        try {
            val threads = (Runtime.getRuntime().availableProcessors() - 2).coerceIn(2, 6)
            val rc = WhisperNative.transcribe(ptr, audio16k, threads)
            require(rc == 0) { "whisper.cpp transcription failed: $rc" }

            val text = buildString {
                val count = WhisperNative.segmentCount(ptr)
                for (i in 0 until count) {
                    append(WhisperNative.segmentText(ptr, i))
                }
            }.trim()

            val outDir = File(context.filesDir, "transcripts").apply { mkdirs() }
            val out = File(outDir, wavFile.nameWithoutExtension + ".txt")
            out.writeText(text + "\n")

            return Result(wavFile, out, text)
        } finally {
            WhisperNative.freeContext(ptr)
        }
    }

    fun transcripts(): List<File> =
        File(context.filesDir, "transcripts")
            .listFiles { f -> f.isFile && f.extension.equals("txt", true) }
            ?.sortedByDescending { it.lastModified() }
            .orEmpty()

    private fun ensureModel(): File {
        val dir = File(context.filesDir, "models").apply { mkdirs() }
        val model = File(dir, MODEL_NAME)
        if (model.isFile && model.length() > 1_000_000L) return model

        context.assets.open("models/$MODEL_NAME").use { input ->
            model.outputStream().buffered().use { output ->
                input.copyTo(output)
            }
        }
        return model
    }

    private data class Pcm(val sampleRate: Int, val samples: ShortArray)

    private fun readMonoPcm16Wav(file: File): Pcm {
        RandomAccessFile(file, "r").use { raf ->
            require(raf.length() >= 44) { "WAV is too small" }
            raf.seek(22)
            val channels = readShortLE(raf)
            val sampleRate = readIntLE(raf)
            raf.seek(34)
            val bits = readShortLE(raf)
            require(channels == 1 && bits == 16) { "Expected mono PCM16 WAV" }

            raf.seek(12)
            var dataOffset = -1L
            var dataSize = 0
            while (raf.filePointer + 8 <= raf.length()) {
                val id = ByteArray(4).also { raf.readFully(it) }.toString(Charsets.US_ASCII)
                val size = readIntLE(raf)
                if (id == "data") {
                    dataOffset = raf.filePointer
                    dataSize = size
                    break
                }
                raf.seek((raf.filePointer + size + (size and 1)).coerceAtMost(raf.length()))
            }
            require(dataOffset >= 0) { "WAV data chunk missing" }
            raf.seek(dataOffset)
            val count = dataSize / 2
            val samples = ShortArray(count)
            for (i in 0 until count) samples[i] = readShortLE(raf).toShort()
            return Pcm(sampleRate, samples)
        }
    }

    private fun resampleTo16k(input: ShortArray, sourceRate: Int): FloatArray {
        if (sourceRate == 16000) {
            return FloatArray(input.size) { input[it] / 32768.0f }
        }
        val outSize = floor(input.size.toDouble() * 16000.0 / sourceRate).toInt().coerceAtLeast(1)
        val out = FloatArray(outSize)
        val ratio = sourceRate.toDouble() / 16000.0
        for (i in out.indices) {
            val pos = i * ratio
            val left = pos.toInt().coerceIn(0, input.lastIndex)
            val right = (left + 1).coerceAtMost(input.lastIndex)
            val frac = pos - left
            val sample = input[left] * (1.0 - frac) + input[right] * frac
            out[i] = (sample / 32768.0).toFloat()
        }
        return out
    }

    private fun readShortLE(raf: RandomAccessFile): Int {
        val a = raf.readUnsignedByte()
        val b = raf.readUnsignedByte()
        return a or (b shl 8)
    }

    private fun readIntLE(raf: RandomAccessFile): Int {
        val a = raf.readUnsignedByte()
        val b = raf.readUnsignedByte()
        val c = raf.readUnsignedByte()
        val d = raf.readUnsignedByte()
        return a or (b shl 8) or (c shl 16) or (d shl 24)
    }

    companion object {
        const val MODEL_NAME = "ggml-tiny.en.bin"
    }
}
