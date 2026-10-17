package org.beaconcomputinginitiative.bciwhisper.audio

import org.jtransforms.fft.DoubleFFT_1D
import kotlin.math.*

class DetectionEngine(
    private val sampleRate: Int,
    private val blockSize: Int,
    private val baselineSecondsRequired: Double = 60.0,
    private val sensitivity: Double = 1.2
) {
    data class Result(
        val baselineComplete: Boolean,
        val baselineSeconds: Double,
        val noiseFloorDbfs: Double,
        val currentDbfs: Double,
        val snrDb: Double,
        val requiredSnrDb: Double,
        val signalActive: Boolean,
        val confirmedTrigger: Boolean,
        val lockLowHz: Double,
        val lockHighHz: Double,
        val lockCenterHz: Double,
        val lockExcessDb: Double,
        val spectrumBands: FloatArray
    )

    private val baselineDb = ArrayList<Double>()
    private var baselineFrames = 0L
    private var triggerBlocks = 0
    private var noiseFloorDbfs = -120.0

    private val fftSize =
        Integer.highestOneBit(blockSize).coerceAtLeast(256)
    private val fft =
        DoubleFFT_1D(fftSize.toLong())

    private val spectralBaseline =
        Array(fftSize / 2 + 1) {
            ArrayList<Double>()
        }

    private var lockLowHz = 80.0
    private var lockHighHz = 8500.0
    private var lockCenterHz = 1200.0
    private var lockInitialized = false

    fun reset() {
        baselineDb.clear()
        spectralBaseline.forEach { it.clear() }
        baselineFrames = 0L
        triggerBlocks = 0
        noiseFloorDbfs = -120.0
        lockLowHz = 80.0
        lockHighHz = 8500.0
        lockCenterHz = 1200.0
        lockInitialized = false
    }

    fun process(
        block: ShortArray,
        count: Int
    ): Result {
        val n =
            count
                .coerceAtMost(block.size)
                .coerceAtLeast(1)

        var sumSq = 0.0

        for (i in 0 until n) {
            val normalized =
                block[i].toDouble() / 32768.0
            sumSq += normalized * normalized
        }

        val rms = sqrt(sumSq / n)

        val currentDbfs =
            if (rms > 1e-12) {
                20.0 * log10(rms)
            } else {
                -120.0
            }

        val spectrum = spectrumPower(block, n)
        val baselineSeconds =
            baselineFrames.toDouble() / sampleRate
        val baselineComplete =
            baselineSeconds >= baselineSecondsRequired

        if (!baselineComplete) {
            baselineDb += currentDbfs

            if (
                baselineFrames / blockSize %
                    BASELINE_SPECTRUM_STRIDE == 0L
            ) {
                for (bin in spectrum.indices) {
                    spectralBaseline[bin] += spectrum[bin]
                }
            }

            baselineFrames += n.toLong()

            if (
                baselineFrames.toDouble() / sampleRate >=
                baselineSecondsRequired
            ) {
                noiseFloorDbfs =
                    percentile(baselineDb, 0.40)
            }

            return Result(
                baselineComplete = false,
                baselineSeconds =
                    (
                        baselineFrames.toDouble() /
                            sampleRate
                        ).coerceAtMost(
                        baselineSecondsRequired
                    ),
                noiseFloorDbfs = noiseFloorDbfs,
                currentDbfs = currentDbfs,
                snrDb = 0.0,
                requiredSnrDb = requiredSnrDb(),
                signalActive = false,
                confirmedTrigger = false,
                lockLowHz = lockLowHz,
                lockHighHz = lockHighHz,
                lockCenterHz = lockCenterHz,
                lockExcessDb = -120.0,
                spectrumBands = visualBands(spectrum)
            )
        }

        val snrDb =
            currentDbfs - noiseFloorDbfs
        val required =
            requiredSnrDb()

        val spectral =
            estimateSpectralLock(
                spectrum
            )

        val active =
            snrDb >= required &&
                spectral.excessDb >= LOCK_PRESENCE_DB

        triggerBlocks =
            if (active) {
                triggerBlocks + 1
            } else {
                0
            }

        if (active) {
            updateLock(
                spectral.lowHz,
                spectral.highHz,
                spectral.centerHz
            )
        }

        return Result(
            baselineComplete = true,
            baselineSeconds =
                baselineSecondsRequired,
            noiseFloorDbfs =
                noiseFloorDbfs,
            currentDbfs =
                currentDbfs,
            snrDb =
                snrDb,
            requiredSnrDb =
                required,
            signalActive =
                active,
            confirmedTrigger =
                triggerBlocks >=
                    MIN_TRIGGER_BLOCKS,
            lockLowHz =
                lockLowHz,
            lockHighHz =
                lockHighHz,
            lockCenterHz =
                lockCenterHz,
            lockExcessDb =
                spectral.excessDb,
            spectrumBands =
                visualBands(spectrum)
        )
    }

    private data class SpectralLock(
        val lowHz: Double,
        val highHz: Double,
        val centerHz: Double,
        val excessDb: Double
    )

    private fun estimateSpectralLock(
        power: DoubleArray
    ): SpectralLock {
        val cleaned =
            DoubleArray(power.size)

        var total = 0.0
        var baselineTotal = 0.0

        for (bin in power.indices) {
            val hz =
                bin.toDouble() *
                    sampleRate /
                    fftSize

            if (
                hz < LOW_LIMIT_HZ ||
                hz > HIGH_LIMIT_HZ
            ) {
                continue
            }

            val floor =
                percentile(
                    spectralBaseline[bin],
                    0.40
                ).coerceAtLeast(1e-14)

            baselineTotal += floor

            val residual =
                max(
                    power[bin] -
                        1.5 * floor,
                    0.0
                )

            cleaned[bin] =
                residual

            total += residual
        }

        if (total <= 1e-18) {
            return SpectralLock(
                lockLowHz,
                lockHighHz,
                lockCenterHz,
                -120.0
            )
        }

        val lowTarget =
            total * LOW_QUANTILE
        val highTarget =
            total * HIGH_QUANTILE

        var cumulative = 0.0
        var lowBin = 0
        var highBin = power.lastIndex
        var weighted = 0.0

        for (bin in cleaned.indices) {
            val p = cleaned[bin]
            if (p <= 0.0) continue

            cumulative += p
            val hz =
                bin.toDouble() *
                    sampleRate /
                    fftSize
            weighted += hz * p

            if (
                cumulative >= lowTarget &&
                lowBin == 0
            ) {
                lowBin = bin
            }

            if (cumulative >= highTarget) {
                highBin = bin
                break
            }
        }

        val center =
            (
                weighted /
                    total
                ).coerceIn(
                LOW_LIMIT_HZ,
                HIGH_LIMIT_HZ
            )

        var low =
            lowBin.toDouble() *
                sampleRate /
                fftSize -
                LOCK_MARGIN_HZ

        var high =
            highBin.toDouble() *
                sampleRate /
                fftSize +
                LOCK_MARGIN_HZ

        if (high - low < MIN_BANDWIDTH_HZ) {
            low =
                center -
                    MIN_BANDWIDTH_HZ / 2.0
            high =
                center +
                    MIN_BANDWIDTH_HZ / 2.0
        }

        low =
            low.coerceIn(
                LOW_LIMIT_HZ,
                HIGH_LIMIT_HZ -
                    MIN_BANDWIDTH_HZ
            )

        high =
            high.coerceIn(
                low + MIN_BANDWIDTH_HZ,
                HIGH_LIMIT_HZ
            )

        val excess =
            10.0 * log10(
                (
                    total /
                        baselineTotal
                            .coerceAtLeast(1e-18)
                    ).coerceAtLeast(1e-12)
            )

        return SpectralLock(
            low,
            high,
            center,
            excess
        )
    }

    private fun updateLock(
        candidateLow: Double,
        candidateHigh: Double,
        candidateCenter: Double
    ) {
        if (!lockInitialized) {
            lockLowHz = candidateLow
            lockHighHz = candidateHigh
            lockCenterHz = candidateCenter
            lockInitialized = true
            return
        }

        lockLowHz =
            smoothAndLimit(
                lockLowHz,
                candidateLow
            )
        lockHighHz =
            smoothAndLimit(
                lockHighHz,
                candidateHigh
            )
        lockCenterHz =
            smoothAndLimit(
                lockCenterHz,
                candidateCenter
            )
    }

    private fun smoothAndLimit(
        current: Double,
        candidate: Double
    ): Double {
        val smoothed =
            current +
                LOCK_SMOOTHING *
                    (candidate - current)

        val delta =
            (smoothed - current)
                .coerceIn(
                    -LOCK_MAX_STEP_HZ,
                    LOCK_MAX_STEP_HZ
                )

        return current + delta
    }

    private fun spectrumPower(
        block: ShortArray,
        count: Int
    ): DoubleArray {
        val real =
            DoubleArray(fftSize)

        val use =
            min(
                count,
                fftSize
            )

        for (i in 0 until use) {
            val window =
                0.5 -
                    0.5 *
                    cos(
                        2.0 *
                            Math.PI *
                            i /
                            (fftSize - 1)
                    )

            real[i] =
                (
                    block[i].toDouble() /
                        32768.0
                    ) *
                    window
        }

        fft.realForward(real)

        val power =
            DoubleArray(
                fftSize / 2 + 1
            )

        power[0] =
            real[0] * real[0]
        power[fftSize / 2] =
            real[1] * real[1]

        for (
            bin in
            1 until fftSize / 2
        ) {
            val re =
                real[2 * bin]
            val im =
                real[2 * bin + 1]

            power[bin] =
                re * re + im * im
        }

        return power
    }


    private fun visualBands(
        power: DoubleArray
    ): FloatArray {
        val out = FloatArray(VISUAL_BANDS)
        val low = LOW_LIMIT_HZ
        val high = HIGH_LIMIT_HZ
        val ratio = (high / low).pow(1.0 / VISUAL_BANDS)

        var edgeLow = low
        for (band in 0 until VISUAL_BANDS) {
            val edgeHigh =
                if (band == VISUAL_BANDS - 1) {
                    high
                } else {
                    edgeLow * ratio
                }

            var sum = 0.0
            var count = 0

            for (bin in power.indices) {
                val hz =
                    bin.toDouble() * sampleRate / fftSize

                if (hz >= edgeLow && hz < edgeHigh) {
                    sum += power[bin]
                    count++
                }
            }

            val avg =
                if (count > 0) sum / count else 0.0

            val db =
                if (avg > 1e-20) {
                    10.0 * log10(avg)
                } else {
                    -120.0
                }

            out[band] =
                ((db + 90.0) / 72.0)
                    .coerceIn(0.0, 1.0)
                    .toFloat()

            edgeLow = edgeHigh
        }

        return out
    }

    private fun requiredSnrDb(): Double =
        max(
            2.0,
            10.0 -
                (sensitivity - 0.5) *
                4.0
        )

    private fun percentile(
        values: List<Double>,
        q: Double
    ): Double {
        if (values.isEmpty()) {
            return 1e-14
        }

        val sorted =
            values.sorted()

        val index =
            (
                (sorted.size - 1) *
                    q
                )
                .toInt()
                .coerceIn(
                    0,
                    sorted.lastIndex
                )

        return sorted[index]
    }

    companion object {
        private const val MIN_TRIGGER_BLOCKS = 2
        private const val BASELINE_SPECTRUM_STRIDE = 3L
        private const val LOW_LIMIT_HZ = 80.0
        private const val HIGH_LIMIT_HZ = 8500.0
        private const val LOW_QUANTILE = 0.12
        private const val HIGH_QUANTILE = 0.92
        private const val MIN_BANDWIDTH_HZ = 700.0
        private const val LOCK_MARGIN_HZ = 150.0
        private const val LOCK_SMOOTHING = 0.35
        private const val LOCK_MAX_STEP_HZ = 500.0
        private const val LOCK_PRESENCE_DB = 3.0
        private const val VISUAL_BANDS = 40
    }
}
