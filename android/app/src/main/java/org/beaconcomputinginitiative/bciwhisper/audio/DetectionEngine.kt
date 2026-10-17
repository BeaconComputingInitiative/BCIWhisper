package org.beaconcomputinginitiative.bciwhisper.audio

import kotlin.math.log10

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
        val confirmedTrigger: Boolean
    )

    private val baselineDb = ArrayList<Double>()
    private var baselineFrames = 0L
    private var triggerBlocks = 0
    private var noiseFloorDbfs = -120.0

    fun reset() {
        baselineDb.clear()
        baselineFrames = 0L
        triggerBlocks = 0
        noiseFloorDbfs = -120.0
    }

    fun process(block: ShortArray, count: Int): Result {
        val n = count.coerceAtMost(block.size).coerceAtLeast(1)

        var sumSq = 0.0
        for (i in 0 until n) {
            val normalized = block[i].toDouble() / 32768.0
            sumSq += normalized * normalized
        }

        val rms = kotlin.math.sqrt(sumSq / n)
        val currentDbfs = if (rms > 1e-12) {
            20.0 * log10(rms)
        } else {
            -120.0
        }

        val baselineSeconds = baselineFrames.toDouble() / sampleRate
        val baselineComplete = baselineSeconds >= baselineSecondsRequired

        if (!baselineComplete) {
            baselineDb += currentDbfs
            baselineFrames += n.toLong()

            if (baselineFrames.toDouble() / sampleRate >= baselineSecondsRequired) {
                noiseFloorDbfs = percentile(baselineDb, 0.40)
            }

            return Result(
                baselineComplete = false,
                baselineSeconds = (baselineFrames.toDouble() / sampleRate)
                    .coerceAtMost(baselineSecondsRequired),
                noiseFloorDbfs = noiseFloorDbfs,
                currentDbfs = currentDbfs,
                snrDb = 0.0,
                requiredSnrDb = requiredSnrDb(),
                signalActive = false,
                confirmedTrigger = false
            )
        }

        val snrDb = currentDbfs - noiseFloorDbfs
        val required = requiredSnrDb()
        val active = snrDb >= required

        triggerBlocks = if (active) triggerBlocks + 1 else 0

        return Result(
            baselineComplete = true,
            baselineSeconds = baselineSecondsRequired,
            noiseFloorDbfs = noiseFloorDbfs,
            currentDbfs = currentDbfs,
            snrDb = snrDb,
            requiredSnrDb = required,
            signalActive = active,
            confirmedTrigger = triggerBlocks >= MIN_TRIGGER_BLOCKS
        )
    }

    private fun requiredSnrDb(): Double =
        kotlin.math.max(
            2.0,
            10.0 - (sensitivity - 0.5) * 4.0
        )

    private fun percentile(values: List<Double>, q: Double): Double {
        if (values.isEmpty()) return -120.0
        val sorted = values.sorted()
        val index = ((sorted.size - 1) * q)
            .toInt()
            .coerceIn(0, sorted.lastIndex)
        return sorted[index]
    }

    companion object {
        private const val MIN_TRIGGER_BLOCKS = 2
    }
}
