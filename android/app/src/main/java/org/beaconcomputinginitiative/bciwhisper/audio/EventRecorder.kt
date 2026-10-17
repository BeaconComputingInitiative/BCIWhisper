package org.beaconcomputinginitiative.bciwhisper.audio

import java.io.File
import java.io.RandomAccessFile
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.PI
import kotlin.math.exp

class EventRecorder(
    private val directory: File,
    private val sampleRate: Int
) {
    data class FinishedEvent(
        val kept: Boolean,
        val rawFile: File?,
        val isolatedFile: File?,
        val lockedSeconds: Double,
        val totalSeconds: Double,
        val reason: String
    )

    private var rawWriter: WavWriter? = null
    private var isolatedWriter: WavWriter? = null
    private var rawFile: File? = null
    private var isolatedFile: File? = null
    private var totalFrames = 0L
    private var lockedFrames = 0L
    private var releaseFrames = 0L
    private val filter = MobileIsolationFilter(sampleRate)

    val active: Boolean
        get() = rawWriter != null

    val lockedSeconds: Double
        get() = lockedFrames.toDouble() / sampleRate

    val totalSeconds: Double
        get() = totalFrames.toDouble() / sampleRate

    fun start(preRoll: ShortArray?) {
        if (active) return

        directory.mkdirs()
        val stamp = SimpleDateFormat(
            "yyyyMMdd_HHmmss_SSS",
            Locale.US
        ).format(Date())

        rawFile = File(directory, "bci_event_${stamp}_raw.wav")
        isolatedFile = File(directory, "bci_event_${stamp}_isolated.wav")

        rawWriter = WavWriter(rawFile!!, sampleRate)
        isolatedWriter = WavWriter(isolatedFile!!, sampleRate)
        totalFrames = 0
        lockedFrames = 0
        releaseFrames = 0
        filter.reset()

        if (preRoll != null && preRoll.isNotEmpty()) {
            append(preRoll, preRoll.size, signalActive = false)
        }
    }

    fun append(
        block: ShortArray,
        count: Int,
        signalActive: Boolean
    ) {
        if (!active) return

        val n = count.coerceAtMost(block.size)
        rawWriter?.write(block, n)

        val isolated = filter.process(block, n)
        isolatedWriter?.write(isolated, isolated.size)

        totalFrames += n

        if (signalActive) {
            lockedFrames += n
            releaseFrames = 0
        } else {
            releaseFrames += n
        }
    }

    fun shouldStopForLoss(): Boolean =
        active &&
            releaseFrames.toDouble() / sampleRate >= RELEASE_SECONDS

    fun finish(reason: String): FinishedEvent {
        val raw = rawFile
        val isolated = isolatedFile

        rawWriter?.close()
        isolatedWriter?.close()

        rawWriter = null
        isolatedWriter = null

        val locked = lockedSeconds
        val total = totalSeconds
        val keep = locked >= MIN_SAVED_LOCK_SECONDS

        if (!keep) {
            raw?.delete()
            isolated?.delete()
        }

        rawFile = null
        isolatedFile = null
        totalFrames = 0
        lockedFrames = 0
        releaseFrames = 0

        return FinishedEvent(
            kept = keep,
            rawFile = if (keep) raw else null,
            isolatedFile = if (keep) isolated else null,
            lockedSeconds = locked,
            totalSeconds = total,
            reason = reason
        )
    }

    fun abort() {
        if (!active) return
        val raw = rawFile
        val isolated = isolatedFile

        runCatching { rawWriter?.close() }
        runCatching { isolatedWriter?.close() }

        rawWriter = null
        isolatedWriter = null
        raw?.delete()
        isolated?.delete()
        rawFile = null
        isolatedFile = null
        totalFrames = 0
        lockedFrames = 0
        releaseFrames = 0
    }

    companion object {
        const val RELEASE_SECONDS = 5.0
        const val MIN_SAVED_LOCK_SECONDS = 15.0
    }
}

private class MobileIsolationFilter(
    sampleRate: Int
) {
    private val hpAlpha: Double
    private val lpAlpha: Double

    private var previousInput = 0.0
    private var previousHigh = 0.0
    private var previousLow = 0.0

    init {
        val dt = 1.0 / sampleRate.toDouble()

        val highRc = 1.0 / (2.0 * PI * 120.0)
        hpAlpha = highRc / (highRc + dt)

        val lowRc = 1.0 / (2.0 * PI * 8000.0)
        lpAlpha = dt / (lowRc + dt)
    }

    fun reset() {
        previousInput = 0.0
        previousHigh = 0.0
        previousLow = 0.0
    }

    fun process(
        input: ShortArray,
        count: Int
    ): ShortArray {
        val n = count.coerceAtMost(input.size)
        val output = ShortArray(n)

        for (i in 0 until n) {
            val x = input[i].toDouble()

            val high =
                hpAlpha * (
                    previousHigh +
                        x -
                        previousInput
                    )

            previousInput = x
            previousHigh = high

            val low =
                previousLow +
                    lpAlpha * (
                        high -
                            previousLow
                        )

            previousLow = low

            output[i] = low
                .coerceIn(
                    Short.MIN_VALUE.toDouble(),
                    Short.MAX_VALUE.toDouble()
                )
                .toInt()
                .toShort()
        }

        return output
    }
}

private class WavWriter(
    private val file: File,
    private val sampleRate: Int
) {
    private val raf = RandomAccessFile(file, "rw")
    private var dataBytes = 0L

    init {
        raf.setLength(0)
        writeHeader(0)
    }

    fun write(
        samples: ShortArray,
        count: Int
    ) {
        val n = count.coerceAtMost(samples.size)

        val bytes = ByteArray(n * 2)
        var offset = 0

        for (i in 0 until n) {
            val value = samples[i].toInt()
            bytes[offset++] = (value and 0xff).toByte()
            bytes[offset++] = ((value ushr 8) and 0xff).toByte()
        }

        raf.write(bytes)
        dataBytes += bytes.size
    }

    fun close() {
        raf.seek(0)
        writeHeader(dataBytes)
        raf.close()
    }

    private fun writeHeader(dataSize: Long) {
        val byteRate = sampleRate * 2
        val riffSize = 36L + dataSize

        raf.writeBytes("RIFF")
        writeIntLE(riffSize.toInt())
        raf.writeBytes("WAVE")
        raf.writeBytes("fmt ")
        writeIntLE(16)
        writeShortLE(1)
        writeShortLE(1)
        writeIntLE(sampleRate)
        writeIntLE(byteRate)
        writeShortLE(2)
        writeShortLE(16)
        raf.writeBytes("data")
        writeIntLE(dataSize.toInt())
    }

    private fun writeIntLE(value: Int) {
        raf.write(
            byteArrayOf(
                (value and 0xff).toByte(),
                ((value ushr 8) and 0xff).toByte(),
                ((value ushr 16) and 0xff).toByte(),
                ((value ushr 24) and 0xff).toByte()
            )
        )
    }

    private fun writeShortLE(value: Int) {
        raf.write(
            byteArrayOf(
                (value and 0xff).toByte(),
                ((value ushr 8) and 0xff).toByte()
            )
        )
    }
}
