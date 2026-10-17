package org.beaconcomputinginitiative.bciwhisper.audio

import java.io.File
import java.io.RandomAccessFile
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.*

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
    private val filter =
        AdaptiveLockIsolationFilter(
            sampleRate
        )

    val active: Boolean
        get() = rawWriter != null

    val lockedSeconds: Double
        get() =
            lockedFrames.toDouble() /
                sampleRate

    val totalSeconds: Double
        get() =
            totalFrames.toDouble() /
                sampleRate

    fun start(
        preRoll: ShortArray?,
        lockLowHz: Double,
        lockHighHz: Double
    ) {
        if (active) return

        directory.mkdirs()

        val stamp =
            SimpleDateFormat(
                "yyyyMMdd_HHmmss_SSS",
                Locale.US
            ).format(Date())

        rawFile =
            File(
                directory,
                "bci_event_${stamp}_raw.wav"
            )

        isolatedFile =
            File(
                directory,
                "bci_event_${stamp}_isolated.wav"
            )

        rawWriter =
            WavWriter(
                rawFile!!,
                sampleRate
            )

        isolatedWriter =
            WavWriter(
                isolatedFile!!,
                sampleRate
            )

        totalFrames = 0
        lockedFrames = 0
        releaseFrames = 0

        filter.reset(
            lockLowHz,
            lockHighHz
        )

        if (
            preRoll != null &&
            preRoll.isNotEmpty()
        ) {
            append(
                preRoll,
                preRoll.size,
                signalActive = false,
                lockLowHz = lockLowHz,
                lockHighHz = lockHighHz
            )
        }
    }

    fun append(
        block: ShortArray,
        count: Int,
        signalActive: Boolean,
        lockLowHz: Double,
        lockHighHz: Double
    ) {
        if (!active) return

        val n =
            count.coerceAtMost(
                block.size
            )

        rawWriter?.write(
            block,
            n
        )

        val isolated =
            filter.process(
                block,
                n,
                lockLowHz,
                lockHighHz
            )

        isolatedWriter?.write(
            isolated,
            isolated.size
        )

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
            releaseFrames
                .toDouble() /
                sampleRate >=
            RELEASE_SECONDS

    fun finish(
        reason: String
    ): FinishedEvent {
        val raw = rawFile
        val isolated = isolatedFile

        rawWriter?.close()
        isolatedWriter?.close()

        rawWriter = null
        isolatedWriter = null

        val locked =
            lockedSeconds
        val total =
            totalSeconds

        val keep =
            locked >=
                MIN_SAVED_LOCK_SECONDS

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
            rawFile =
                if (keep) raw else null,
            isolatedFile =
                if (keep) isolated else null,
            lockedSeconds =
                locked,
            totalSeconds =
                total,
            reason =
                reason
        )
    }

    fun abort() {
        if (!active) return

        val raw = rawFile
        val isolated =
            isolatedFile

        runCatching {
            rawWriter?.close()
        }

        runCatching {
            isolatedWriter?.close()
        }

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
        const val RELEASE_SECONDS =
            5.0
        const val MIN_SAVED_LOCK_SECONDS =
            15.0
    }
}

private class AdaptiveLockIsolationFilter(
    private val sampleRate: Int
) {
    private val hp1 = Biquad()
    private val hp2 = Biquad()
    private val lp1 = Biquad()
    private val lp2 = Biquad()

    private var lowHz = 120.0
    private var highHz = 8000.0

    fun reset(
        initialLowHz: Double,
        initialHighHz: Double
    ) {
        lowHz =
            targetLow(
                initialLowHz
            )

        highHz =
            targetHigh(
                initialHighHz
            )

        hp1.reset()
        hp2.reset()
        lp1.reset()
        lp2.reset()

        configure()
    }

    fun process(
        input: ShortArray,
        count: Int,
        lockLowHz: Double,
        lockHighHz: Double
    ): ShortArray {
        val targetLow =
            targetLow(
                lockLowHz
            )

        val targetHigh =
            targetHigh(
                lockHighHz
            )

        lowHz +=
            FILTER_TRACKING *
                (targetLow - lowHz)

        highHz +=
            FILTER_TRACKING *
                (targetHigh - highHz)

        if (
            highHz - lowHz <
            MIN_PASSBAND_HZ
        ) {
            val center =
                (highHz + lowHz) *
                    0.5

            lowHz =
                center -
                    MIN_PASSBAND_HZ /
                    2.0

            highHz =
                center +
                    MIN_PASSBAND_HZ /
                    2.0
        }

        configure()

        val n =
            count.coerceAtMost(
                input.size
            )

        val output =
            ShortArray(n)

        for (i in 0 until n) {
            var x =
                input[i]
                    .toDouble() /
                    32768.0

            x = hp1.process(x)
            x = hp2.process(x)
            x = lp1.process(x)
            x = lp2.process(x)

            output[i] =
                (
                    x.coerceIn(
                        -1.0,
                        1.0
                    ) *
                        32767.0
                    )
                    .roundToInt()
                    .toShort()
        }

        return output
    }

    private fun targetLow(
        lockLowHz: Double
    ): Double =
        (
            lockLowHz -
                LOW_GUARD_HZ
            )
            .coerceIn(
                45.0,
                sampleRate *
                    0.40
            )

    private fun targetHigh(
        lockHighHz: Double
    ): Double =
        (
            lockHighHz +
                HIGH_GUARD_HZ
            )
            .coerceIn(
                300.0,
                sampleRate *
                    0.47
            )

    private fun configure() {
        hp1.highPass(
            sampleRate,
            lowHz,
            Q_BUTTERWORTH
        )
        hp2.highPass(
            sampleRate,
            lowHz,
            Q_BUTTERWORTH
        )
        lp1.lowPass(
            sampleRate,
            highHz,
            Q_BUTTERWORTH
        )
        lp2.lowPass(
            sampleRate,
            highHz,
            Q_BUTTERWORTH
        )
    }

    companion object {
        private const val LOW_GUARD_HZ =
            90.0
        private const val HIGH_GUARD_HZ =
            140.0
        private const val MIN_PASSBAND_HZ =
            420.0
        private const val FILTER_TRACKING =
            0.22
        private const val Q_BUTTERWORTH =
            0.70710678
    }
}

private class Biquad {
    private var b0 = 1.0
    private var b1 = 0.0
    private var b2 = 0.0
    private var a1 = 0.0
    private var a2 = 0.0

    private var z1 = 0.0
    private var z2 = 0.0

    fun reset() {
        z1 = 0.0
        z2 = 0.0
    }

    fun highPass(
        sampleRate: Int,
        frequency: Double,
        q: Double
    ) {
        configure(
            sampleRate,
            frequency,
            q,
            highPass = true
        )
    }

    fun lowPass(
        sampleRate: Int,
        frequency: Double,
        q: Double
    ) {
        configure(
            sampleRate,
            frequency,
            q,
            highPass = false
        )
    }

    private fun configure(
        sampleRate: Int,
        frequency: Double,
        q: Double,
        highPass: Boolean
    ) {
        val f =
            frequency.coerceIn(
                20.0,
                sampleRate *
                    0.48
            )

        val w0 =
            2.0 *
                Math.PI *
                f /
                sampleRate

        val cosW0 =
            cos(w0)
        val sinW0 =
            sin(w0)

        val alpha =
            sinW0 /
                (2.0 * q)

        val rawB0: Double
        val rawB1: Double
        val rawB2: Double

        if (highPass) {
            rawB0 =
                (1.0 + cosW0) /
                    2.0
            rawB1 =
                -(1.0 + cosW0)
            rawB2 =
                (1.0 + cosW0) /
                    2.0
        } else {
            rawB0 =
                (1.0 - cosW0) /
                    2.0
            rawB1 =
                1.0 - cosW0
            rawB2 =
                (1.0 - cosW0) /
                    2.0
        }

        val rawA0 =
            1.0 + alpha
        val rawA1 =
            -2.0 * cosW0
        val rawA2 =
            1.0 - alpha

        b0 =
            rawB0 / rawA0
        b1 =
            rawB1 / rawA0
        b2 =
            rawB2 / rawA0
        a1 =
            rawA1 / rawA0
        a2 =
            rawA2 / rawA0
    }

    fun process(
        input: Double
    ): Double {
        val output =
            b0 * input +
                z1

        z1 =
            b1 * input -
                a1 * output +
                z2

        z2 =
            b2 * input -
                a2 * output

        return output
    }
}

private class WavWriter(
    private val file: File,
    private val sampleRate: Int
) {
    private val raf =
        RandomAccessFile(
            file,
            "rw"
        )

    private var dataBytes =
        0L

    init {
        raf.setLength(0)
        writeHeader(0)
    }

    fun write(
        samples: ShortArray,
        count: Int
    ) {
        val n =
            count.coerceAtMost(
                samples.size
            )

        val bytes =
            ByteArray(
                n * 2
            )

        var offset = 0

        for (i in 0 until n) {
            val value =
                samples[i]
                    .toInt()

            bytes[offset++] =
                (value and 0xff)
                    .toByte()

            bytes[offset++] =
                (
                    value ushr 8 and
                        0xff
                    )
                    .toByte()
        }

        raf.write(bytes)

        dataBytes +=
            bytes.size
    }

    fun close() {
        raf.seek(0)
        writeHeader(dataBytes)
        raf.close()
    }

    private fun writeHeader(
        dataSize: Long
    ) {
        val byteRate =
            sampleRate * 2

        val riffSize =
            36L + dataSize

        raf.writeBytes("RIFF")
        writeIntLE(
            riffSize.toInt()
        )

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
        writeIntLE(
            dataSize.toInt()
        )
    }

    private fun writeIntLE(
        value: Int
    ) {
        raf.write(
            byteArrayOf(
                (value and 0xff)
                    .toByte(),
                (
                    value ushr 8 and
                        0xff
                    )
                    .toByte(),
                (
                    value ushr 16 and
                        0xff
                    )
                    .toByte(),
                (
                    value ushr 24 and
                        0xff
                    )
                    .toByte()
            )
        )
    }

    private fun writeShortLE(
        value: Int
    ) {
        raf.write(
            byteArrayOf(
                (value and 0xff)
                    .toByte(),
                (
                    value ushr 8 and
                        0xff
                    )
                    .toByte()
            )
        )
    }
}
