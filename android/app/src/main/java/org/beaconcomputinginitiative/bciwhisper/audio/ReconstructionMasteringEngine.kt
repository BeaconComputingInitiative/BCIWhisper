package org.beaconcomputinginitiative.bciwhisper.audio

import org.jtransforms.fft.DoubleFFT_1D
import java.io.File
import java.io.RandomAccessFile
import kotlin.math.*

class ReconstructionMasteringEngine {
    data class Output(
        val reconstructed: File,
        val mastered: File,
        val inputRmsDbfs: Double,
        val outputRmsDbfs: Double,
        val outputPeakDbfs: Double
    )

    fun process(source: File): Output {
        val wav = readWav(source)
        val normalized = DoubleArray(wav.samples.size) {
            wav.samples[it] / 32768.0
        }

        val reconstructed = spectralReconstruct(
            normalized,
            wav.sampleRate
        )

        val mastered = master(
            reconstructed,
            wav.sampleRate
        )

        val base = source.nameWithoutExtension
            .removeSuffix("_isolated")

        val reconstructedFile = File(
            source.parentFile,
            "${base}_reconstructed.wav"
        )
        val masteredFile = File(
            source.parentFile,
            "${base}_mastered.wav"
        )

        writeWav(
            reconstructedFile,
            wav.sampleRate,
            reconstructed
        )
        writeWav(
            masteredFile,
            wav.sampleRate,
            mastered
        )

        return Output(
            reconstructed = reconstructedFile,
            mastered = masteredFile,
            inputRmsDbfs = rmsDbfs(normalized),
            outputRmsDbfs = rmsDbfs(mastered),
            outputPeakDbfs = peakDbfs(mastered)
        )
    }

    private fun spectralReconstruct(
        input: DoubleArray,
        sampleRate: Int
    ): DoubleArray {
        if (input.size < NFFT) return input.copyOf()

        val fft = DoubleFFT_1D(NFFT.toLong())
        val window = DoubleArray(NFFT) { i ->
            0.5 - 0.5 * cos(
                2.0 * Math.PI * i / (NFFT - 1)
            )
        }

        val frameCount = 1 +
            max(0, (input.size - NFFT + HOP - 1) / HOP)

        val spectra = Array(frameCount) {
            DoubleArray(NFFT * 2)
        }
        val powers = Array(frameCount) {
            DoubleArray(NFFT / 2 + 1)
        }

        for (frame in 0 until frameCount) {
            val start = frame * HOP
            val data = spectra[frame]

            for (i in 0 until NFFT) {
                val index = start + i
                data[i] =
                    if (index < input.size) {
                        input[index] * window[i]
                    } else {
                        0.0
                    }
            }

            fft.realForwardFull(data)

            for (bin in powers[frame].indices) {
                val re = data[2 * bin]
                val im = data[2 * bin + 1]
                powers[frame][bin] = re * re + im * im
            }
        }

        val noise = DoubleArray(NFFT / 2 + 1)
        val scratch = DoubleArray(frameCount)

        for (bin in noise.indices) {
            for (frame in 0 until frameCount) {
                scratch[frame] = powers[frame][bin]
            }
            scratch.sort()
            val index = (
                (scratch.lastIndex * NOISE_PERCENTILE)
                    .roundToInt()
            ).coerceIn(0, scratch.lastIndex)
            noise[bin] = scratch[index].coerceAtLeast(1e-14)
        }

        val output = DoubleArray(
            input.size + NFFT
        )
        val norm = DoubleArray(
            output.size
        )

        for (frame in 0 until frameCount) {
            val spectrum = spectra[frame]
            val power = powers[frame]

            for (bin in power.indices) {
                val signal = max(
                    0.0,
                    power[bin] -
                        WIENER_OVERSUBTRACT * noise[bin]
                )
                val snr = signal / noise[bin]
                var gain = sqrt(snr / (1.0 + snr))
                gain = SPECTRAL_FLOOR +
                    (1.0 - SPECTRAL_FLOOR) * gain

                if (
                    bin > 0 &&
                    bin < power.lastIndex &&
                    power[bin] > power[bin - 1] &&
                    power[bin] >= power[bin + 1] &&
                    power[bin] > 3.5 * noise[bin]
                ) {
                    gain = max(gain, HARMONIC_FLOOR)
                }

                val hz =
                    bin.toDouble() * sampleRate / NFFT

                val bandGain = when {
                    hz < 80.0 -> 0.15
                    hz < 120.0 -> 0.65
                    hz <= 8500.0 -> 1.0
                    hz <= 10500.0 -> 0.65
                    else -> 0.20
                }

                val g = gain * bandGain
                spectrum[2 * bin] *= g
                spectrum[2 * bin + 1] *= g

                if (bin != 0 && bin != NFFT / 2) {
                    val mirror = NFFT - bin
                    spectrum[2 * mirror] *= g
                    spectrum[2 * mirror + 1] *= g
                }
            }

            fft.complexInverse(spectrum, true)

            val start = frame * HOP

            for (i in 0 until NFFT) {
                val index = start + i
                if (index >= output.size) break

                val sample = spectrum[2 * i] * window[i]
                output[index] += sample
                norm[index] += window[i] * window[i]
            }
        }

        return DoubleArray(input.size) { i ->
            if (norm[i] > 1e-12) {
                output[i] / norm[i]
            } else {
                0.0
            }
        }
    }

    private fun master(
        input: DoubleArray,
        sampleRate: Int
    ): DoubleArray {
        val hp = HighPass(sampleRate, 80.0)
        val presence = PeakingEq(
            sampleRate,
            2600.0,
            0.9,
            2.6
        )
        val air = PeakingEq(
            sampleRate,
            6200.0,
            0.7,
            1.1
        )

        val shaped = DoubleArray(input.size)

        for (i in input.indices) {
            var x = hp.process(input[i])
            x = presence.process(x)
            x = air.process(x)
            shaped[i] = x
        }

        val current = rmsDbfs(shaped)
        val desiredGainDb =
            (TARGET_RMS_DBFS - current)
                .coerceIn(-12.0, MAX_GAIN_DB)

        val gain = 10.0.pow(desiredGainDb / 20.0)

        var peak = 0.0
        for (i in shaped.indices) {
            shaped[i] *= gain
            peak = max(peak, abs(shaped[i]))
        }

        val limit = 10.0.pow(TRUE_PEAK_DBTP / 20.0)

        if (peak > limit && peak > 0.0) {
            val limiterGain = limit / peak
            for (i in shaped.indices) {
                shaped[i] *= limiterGain
            }
        }

        return shaped
    }

    private fun rmsDbfs(data: DoubleArray): Double {
        if (data.isEmpty()) return -120.0
        var sum = 0.0
        for (v in data) sum += v * v
        val rms = sqrt(sum / data.size)
        return if (rms > 1e-12) {
            20.0 * log10(rms)
        } else {
            -120.0
        }
    }

    private fun peakDbfs(data: DoubleArray): Double {
        var peak = 0.0
        for (v in data) peak = max(peak, abs(v))
        return if (peak > 1e-12) {
            20.0 * log10(peak)
        } else {
            -120.0
        }
    }

    private data class Wav(
        val sampleRate: Int,
        val samples: ShortArray
    )

    private fun readWav(file: File): Wav {
        RandomAccessFile(file, "r").use { raf ->
            require(raf.length() >= 44) {
                "Invalid WAV"
            }

            raf.seek(22)
            val channels = readShortLE(raf)
            val sampleRate = readIntLE(raf)
            raf.seek(34)
            val bits = readShortLE(raf)

            require(channels == 1 && bits == 16) {
                "Expected mono PCM16 WAV"
            }

            raf.seek(12)
            var dataSize = -1
            var dataOffset = -1L

            while (raf.filePointer + 8 <= raf.length()) {
                val id = ByteArray(4)
                raf.readFully(id)
                val size = readIntLE(raf)

                if (
                    id.toString(Charsets.US_ASCII) == "data"
                ) {
                    dataSize = size
                    dataOffset = raf.filePointer
                    break
                }

                raf.seek(
                    raf.filePointer +
                        size +
                        (size and 1)
                )
            }

            require(dataSize >= 0 && dataOffset >= 0) {
                "WAV data chunk missing"
            }

            raf.seek(dataOffset)
            val samples = ShortArray(dataSize / 2)

            for (i in samples.indices) {
                samples[i] =
                    readShortLE(raf).toShort()
            }

            return Wav(
                sampleRate,
                samples
            )
        }
    }

    private fun writeWav(
        file: File,
        sampleRate: Int,
        data: DoubleArray
    ) {
        RandomAccessFile(file, "rw").use { raf ->
            raf.setLength(0)

            val dataBytes = data.size * 2
            raf.writeBytes("RIFF")
            writeIntLE(raf, 36 + dataBytes)
            raf.writeBytes("WAVE")
            raf.writeBytes("fmt ")
            writeIntLE(raf, 16)
            writeShortLE(raf, 1)
            writeShortLE(raf, 1)
            writeIntLE(raf, sampleRate)
            writeIntLE(raf, sampleRate * 2)
            writeShortLE(raf, 2)
            writeShortLE(raf, 16)
            raf.writeBytes("data")
            writeIntLE(raf, dataBytes)

            for (value in data) {
                val s = (
                    value.coerceIn(-1.0, 1.0) *
                        32767.0
                    ).roundToInt()
                writeShortLE(raf, s)
            }
        }
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
        return a or
            (b shl 8) or
            (c shl 16) or
            (d shl 24)
    }

    private fun writeShortLE(
        raf: RandomAccessFile,
        value: Int
    ) {
        raf.write(value and 0xff)
        raf.write((value ushr 8) and 0xff)
    }

    private fun writeIntLE(
        raf: RandomAccessFile,
        value: Int
    ) {
        raf.write(value and 0xff)
        raf.write((value ushr 8) and 0xff)
        raf.write((value ushr 16) and 0xff)
        raf.write((value ushr 24) and 0xff)
    }

    private class HighPass(
        sampleRate: Int,
        cutoff: Double
    ) {
        private val alpha: Double
        private var previousInput = 0.0
        private var previousOutput = 0.0

        init {
            val dt = 1.0 / sampleRate
            val rc = 1.0 / (2.0 * Math.PI * cutoff)
            alpha = rc / (rc + dt)
        }

        fun process(x: Double): Double {
            val y =
                alpha * (
                    previousOutput +
                        x -
                        previousInput
                    )
            previousInput = x
            previousOutput = y
            return y
        }
    }

    private class PeakingEq(
        sampleRate: Int,
        frequency: Double,
        q: Double,
        gainDb: Double
    ) {
        private val b0: Double
        private val b1: Double
        private val b2: Double
        private val a1: Double
        private val a2: Double

        private var x1 = 0.0
        private var x2 = 0.0
        private var y1 = 0.0
        private var y2 = 0.0

        init {
            val a = 10.0.pow(gainDb / 40.0)
            val w0 =
                2.0 * Math.PI * frequency / sampleRate
            val alpha = sin(w0) / (2.0 * q)
            val c = cos(w0)

            val rawB0 = 1.0 + alpha * a
            val rawB1 = -2.0 * c
            val rawB2 = 1.0 - alpha * a
            val rawA0 = 1.0 + alpha / a
            val rawA1 = -2.0 * c
            val rawA2 = 1.0 - alpha / a

            b0 = rawB0 / rawA0
            b1 = rawB1 / rawA0
            b2 = rawB2 / rawA0
            a1 = rawA1 / rawA0
            a2 = rawA2 / rawA0
        }

        fun process(x: Double): Double {
            val y =
                b0 * x +
                    b1 * x1 +
                    b2 * x2 -
                    a1 * y1 -
                    a2 * y2

            x2 = x1
            x1 = x
            y2 = y1
            y1 = y

            return y
        }
    }

    companion object {
        private const val NFFT = 2048
        private const val HOP = 512
        private const val NOISE_PERCENTILE = 0.18
        private const val WIENER_OVERSUBTRACT = 1.15
        private const val SPECTRAL_FLOOR = 0.08
        private const val HARMONIC_FLOOR = 0.72

        // Mobile mastering target. RMS is used as a deterministic
        // pre-release proxy until EBU R128 / true-peak validation
        // is added on physical devices.
        private const val TARGET_RMS_DBFS = -16.0
        private const val MAX_GAIN_DB = 24.0
        private const val TRUE_PEAK_DBTP = -1.0
    }
}
