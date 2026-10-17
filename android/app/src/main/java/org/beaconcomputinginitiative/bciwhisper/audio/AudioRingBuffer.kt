package org.beaconcomputinginitiative.bciwhisper.audio

class AudioRingBuffer(private val capacitySamples: Int) {
    private val data = ShortArray(capacitySamples)
    private var writeIndex = 0
    private var size = 0

    @Synchronized
    fun write(src: ShortArray, count: Int) {
        val n = count.coerceAtMost(src.size)
        for (i in 0 until n) {
            data[writeIndex] = src[i]
            writeIndex = (writeIndex + 1) % capacitySamples
            if (size < capacitySamples) size++
        }
    }

    @Synchronized
    fun snapshot(maxSamples: Int = size): ShortArray {
        val n = maxSamples.coerceAtMost(size)
        val out = ShortArray(n)
        var start = writeIndex - n
        if (start < 0) start += capacitySamples
        for (i in 0 until n) {
            out[i] = data[(start + i) % capacitySamples]
        }
        return out
    }

    @Synchronized
    fun clear() {
        writeIndex = 0
        size = 0
    }
}
